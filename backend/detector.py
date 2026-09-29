"""
Safety Trigger Detector

Deterministic detection of configured safety-trigger evidence.

The detector:
- checks configured active substances
- checks safety terms
- requires proximity between substance and safety evidence
- skips likely table-of-contents pages
- extracts evidence windows
- identifies explicitly labelled products only
- does not make medical or regulatory decisions
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(
    "safety_trigger_poc.detector"
)


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_DIR = (
    Path(__file__).resolve().parent.parent
    / "config"
)

TRIGGER_FILE = (
    CONFIG_DIR / "triggers.json"
)


DEFAULT_SUBSTANCES = [
    "alprazolam",
    "bromazepam",
    "chlordiazepoxide",
    "clonazepam",
    "cloxazolam",
    "delorazepam",
    "diazepam",
    "flunitrazepam",
    "flurazepam",
    "loprazolam",
    "lorazepam",
    "lormetazepam",
    "midazolam",
    "nitrazepam",
    "oxazepam",
    "temazepam",
    "amitriptyline/chlordiazepoxide",
    "chlordiazepoxide/clidinium bromide",
]


DEFAULT_SAFETY_TERMS = [
    "safety signal",
    "signal",
    "adverse reaction",
    "adverse event",
    "risk",
    "risk assessment",
    "new safety information",
    "safety concern",
    "pregnancy",
    "miscarriage",
    "in-utero exposure",
    "congenital",
    "foetal",
    "fetal",
    "birth defect",
    "embryo",
    "teratogenic",
]


DEFAULT_TRIGGER: Dict[str, Any] = {
    "name": "Benzodiazepines",
    "type": "Effect Based",
    "active": True,
    "substances": DEFAULT_SUBSTANCES,
    "safety_terms": DEFAULT_SAFETY_TERMS,
}


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = text.replace(
        "\u00a0",
        " ",
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_for_matching(
    text: str,
) -> str:

    text = normalize_text(
        text
    ).lower()

    return text


# ============================================================
# TRIGGER CONFIGURATION
# ============================================================

def load_trigger_config() -> Dict[str, Any]:
    """
    Load trigger configuration from config/triggers.json.

    Falls back to the built-in Benzodiazepines trigger
    when the configuration file is unavailable or invalid.
    """

    if not TRIGGER_FILE.exists():

        return DEFAULT_TRIGGER.copy()

    try:

        with TRIGGER_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            config = json.load(
                file
            )

        if isinstance(
            config,
            dict,
        ):

            if "name" in config:

                return {
                    **DEFAULT_TRIGGER,
                    **config,
                }

            if isinstance(
                config.get(
                    "triggers"
                ),
                list,
            ):

                for trigger in config[
                    "triggers"
                ]:

                    if (
                        isinstance(
                            trigger,
                            dict,
                        )
                        and trigger.get(
                            "active",
                            True,
                        )
                    ):

                        configured = {
                            **DEFAULT_TRIGGER,
                            **trigger,
                        }
                        if (
                            "safety_terms" not in trigger
                            and isinstance(trigger.get("relevant_terms"), list)
                        ):
                            configured["safety_terms"] = trigger["relevant_terms"]
                        return configured

    except Exception as exc:

        logger.warning(
            "Could not load trigger config: %s",
            exc,
        )

    return DEFAULT_TRIGGER.copy()


# ============================================================
# TERM MATCHING
# ============================================================

def find_term_matches(
    text: str,
    terms: List[str],
) -> List[Dict[str, Any]]:
    """
    Find configured terms in text.

    Returns start/end positions and matched text.
    """

    normalized = normalize_for_matching(
        text
    )

    matches: List[Dict[str, Any]] = []

    unique_terms = sorted(
        {
            term.strip()
            for term in terms
            if term and term.strip()
        },
        key=len,
        reverse=True,
    )

    for term in unique_terms:

        normalized_term = normalize_for_matching(
            term
        )

        if not normalized_term:
            continue

        escaped = re.escape(
            normalized_term
        )

        for match in re.finditer(
            escaped,
            normalized,
        ):

            matches.append(
                {
                    "term": term,
                    "start": match.start(),
                    "end": match.end(),
                }
            )

    return matches


def terms_are_close(
    substance_match: Dict[str, Any],
    safety_match: Dict[str, Any],
    max_distance: int = 1200,
) -> bool:
    """Return True when two terms are reasonably close."""

    distance = min(
        abs(
            substance_match["end"]
            - safety_match["start"]
        ),
        abs(
            safety_match["end"]
            - substance_match["start"]
        ),
    )

    return distance <= max_distance


# ============================================================
# TABLE OF CONTENTS DETECTION
# ============================================================

def is_likely_table_of_contents(
    page_text: str,
) -> bool:
    """
    Detect pages that are probably tables of contents.

    These pages can contain many substance names but do not
    necessarily contain the actual safety evidence.
    """

    text = normalize_for_matching(
        page_text
    )

    if not text:
        return False

    first_part = text[:1200]

    toc_indicators = [
        "table of contents",
        "contents",
        "agenda",
        "list of abbreviations",
    ]

    if any(
        indicator in first_part
        for indicator in toc_indicators
    ):

        return True

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    if len(lines) < 8:
        return False

    dot_leaders = sum(
        1
        for line in lines
        if re.search(
            r"\.{3,}\s*\d+\s*$",
            line,
        )
    )

    if dot_leaders >= 3:
        return True

    return False


# ============================================================
# SAFETY TOPIC
# ============================================================

def detect_safety_topic(
    text: str,
) -> Optional[str]:
    """Classify the most obvious safety topic."""

    normalized = normalize_for_matching(
        text
    )

    topic_map = [
        (
            "Pregnancy / reproductive safety",
            [
                "pregnancy",
                "miscarriage",
                "in-utero exposure",
                "congenital",
                "foetal",
                "fetal",
                "birth defect",
                "embryo",
                "teratogenic",
            ],
        ),
        (
            "Adverse reaction / adverse event",
            [
                "adverse reaction",
                "adverse event",
            ],
        ),
        (
            "Safety signal",
            [
                "safety signal",
                "signal",
            ],
        ),
        (
            "Risk assessment",
            [
                "risk assessment",
                "risk",
            ],
        ),
        (
            "New safety information",
            [
                "new safety information",
                "safety concern",
            ],
        ),
    ]

    for topic, terms in topic_map:

        if any(
            term in normalized
            for term in terms
        ):

            return topic

    return None


# ============================================================
# PRODUCT EXTRACTION
# ============================================================

def extract_explicit_product(
    text: str,
) -> Optional[str]:
    """
    Extract a product only when the text explicitly labels it.

    This intentionally avoids assuming that an active
    substance name is a product name.
    """

    patterns = [
        r"\b(?:product|medicinal product)\s*:\s*([^\n.;]{2,120})",
        r"\b(?:product name)\s*:\s*([^\n.;]{2,120})",
        r"\b(?:brand name)\s*:\s*([^\n.;]{2,120})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            value = normalize_text(
                match.group(1)
            )

            if value:

                return value

    return None


# ============================================================
# EVIDENCE WINDOW
# ============================================================

def build_evidence_window(
    text: str,
    start: int,
    end: int,
    window: int = 500,
) -> str:
    """Build a readable evidence excerpt around matched terms."""

    start_index = max(
        0,
        start - window,
    )

    end_index = min(
        len(text),
        end + window,
    )

    evidence = text[
        start_index:end_index
    ]

    return normalize_text(
        evidence
    )


# ============================================================
# PAGE DETECTION
# ============================================================

def detect_page(
    page_number: int,
    page_text: str,
    trigger: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Detect potential safety-trigger evidence on one page.
    """

    if not page_text:
        return []

    if is_likely_table_of_contents(
        page_text
    ):

        logger.debug(
            "Skipping likely TOC page %s",
            page_number,
        )

        return []

    substances = trigger.get(
        "substances",
        DEFAULT_SUBSTANCES,
    )

    safety_terms = trigger.get(
        "safety_terms",
        DEFAULT_SAFETY_TERMS,
    )

    normalized_text = normalize_for_matching(
        page_text
    )

    substance_matches = find_term_matches(
        normalized_text,
        substances,
    )

    safety_matches = find_term_matches(
        normalized_text,
        safety_terms,
    )

    if not substance_matches:
        return []

    if not safety_matches:
        return []

    findings: List[Dict[str, Any]] = []

    for substance_match in substance_matches:

        related_safety = [
            safety_match
            for safety_match in safety_matches
            if terms_are_close(
                substance_match,
                safety_match,
            )
        ]

        if not related_safety:
            continue

        closest_safety = min(
            related_safety,
            key=lambda item: abs(
                item["start"]
                - substance_match["start"]
            ),
        )

        evidence_start = min(
            substance_match["start"],
            closest_safety["start"],
        )

        evidence_end = max(
            substance_match["end"],
            closest_safety["end"],
        )

        evidence = build_evidence_window(
            normalized_text,
            evidence_start,
            evidence_end,
        )

        if not evidence:
            continue

        safety_topic = detect_safety_topic(
            evidence
        )

        product_name = extract_explicit_product(
            evidence
        )

        relevant_terms = [
            substance_match["term"],
        ]

        for safety_match in related_safety:

            if (
                safety_match["term"]
                not in relevant_terms
            ):

                relevant_terms.append(
                    safety_match["term"]
                )

        findings.append(
            {
                "page_number": page_number,
                "product_name": product_name,
                "active_substance": (
                    substance_match["term"]
                ),
                "trigger_name": trigger.get(
                    "name",
                    "Benzodiazepines",
                ),
                "safety_topic": (
                    safety_topic
                    or "Safety-related information"
                ),
                "relevant_terms": ", ".join(
                    relevant_terms
                ),
                "evidence": evidence,
                "section": None,
            }
        )

    return findings


# ============================================================
# DOCUMENT DETECTION
# ============================================================

def detect_document(
    pages: List[Dict[str, Any]],
    trigger: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Detect potential findings across all PDF pages.
    """

    if trigger is None:

        trigger = load_trigger_config()

    findings: List[Dict[str, Any]] = []

    for page in pages:

        page_number = page.get(
            "page_number",
            page.get(
                "page",
                0,
            ),
        )

        page_text = page.get(
            "text",
            page.get(
                "page_text",
                "",
            ),
        )

        page_number = int(
            page_number
        )

        page_findings = detect_page(
            page_number,
            page_text,
            trigger,
        )

        findings.extend(
            page_findings
        )

    return findings


# ============================================================
# DUPLICATE FINDINGS
# ============================================================

def remove_duplicate_findings(
    findings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove duplicate findings."""

    unique: List[Dict[str, Any]] = []

    seen = set()

    for finding in findings:

        key = (
            finding.get(
                "page_number"
            ),
            (
                finding.get(
                    "active_substance"
                )
                or ""
            ).lower(),
            (
                finding.get(
                    "safety_topic"
                )
                or ""
            ).lower(),
            (
                finding.get(
                    "evidence"
                )
                or ""
            ).lower()[:500],
        )

        if key in seen:
            continue

        seen.add(key)

        unique.append(
            finding
        )

    return unique


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\nSafety Trigger Detector\n"
    )

    trigger = load_trigger_config()

    print(
        f"Trigger: "
        f"{trigger.get('name')}"
    )

    print(
        f"Type: "
        f"{trigger.get('type')}"
    )

    print(
        f"Substances: "
        f"{len(trigger.get('substances', []))}"
    )

    print(
        f"Safety terms: "
        f"{len(trigger.get('safety_terms', []))}"
    )