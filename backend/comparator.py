"""
Safety Trigger Monitoring Platform
Evidence Comparison Engine

Responsibilities:
- Normalize extracted evidence
- Create stable evidence hashes
- Compare current findings with historical findings
- Identify NEW_INFORMATION
- Identify NO_NEW_INFORMATION
- Prevent duplicate safety findings
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger(__name__)

if not logger.handlers:

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(
    text: Optional[str],
) -> str:
    """
    Normalize text for comparison.

    This does NOT modify the evidence stored in the database.
    It creates a comparison-only representation.
    """

    if not text:

        return ""

    value = str(text)

    # Normalize line endings.
    value = value.replace(
        "\r\n",
        "\n",
    )

    value = value.replace(
        "\r",
        "\n",
    )

    # Convert whitespace runs into a single space.
    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    # Remove spaces around punctuation.
    value = re.sub(
        r"\s+([,.;:])",
        r"\1",
        value,
    )

    return value.strip().lower()


# ============================================================
# HASH
# ============================================================

def hash_text(
    text: Optional[str],
) -> str:
    """
    Generate SHA256 for normalized text.
    """

    normalized =normalize_text(
            text
        )

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# FINDING SIGNATURE
# ============================================================

def build_finding_signature(
    finding: Dict[str, Any],
) -> str:
    """
    Build a stable signature for a finding.

    The signature deliberately includes:
    - Trigger
    - Active substance
    - Safety topic
    - Evidence

    Product is included when explicitly available.
    """

    parts = [

        str(
            finding.get(
                "trigger_name",
                "",
            )
        ),

        str(
            finding.get(
                "active_substance",
                "",
            )
        ),

        str(
            finding.get(
                "safety_topic",
                "",
            )
        ),

        str(
            finding.get(
                "product_name",
                "",
            )
            or ""
        ),

        str(
            finding.get(
                "evidence",
                "",
            )
        ),
    ]


    combined =" | ".join(
            normalize_text(part)
            for part in parts
        )


    return hash_text(
        combined
    )


# ============================================================
# FINDING KEY
# ============================================================

def build_finding_key(
    finding: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    """
    Build a human-readable comparison key.

    Page number is intentionally NOT included because the same
    evidence can move between pages between document versions.
    """

    return (

        normalize_text(
            finding.get(
                "trigger_name",
                "",
            )
        ),

        normalize_text(
            finding.get(
                "active_substance",
                "",
            )
        ),

        normalize_text(
            finding.get(
                "safety_topic",
                "",
            )
        ),

        normalize_text(
            finding.get(
                "product_name",
                "",
            )
            or ""
        ),
    )


# ============================================================
# EVIDENCE SIMILARITY
# ============================================================

def evidence_similarity(
    current: str,
    previous: str,
) -> float:
    """
    Calculate a simple token-based similarity score.

    Returns a value between 0 and 1.

    1.0 = identical normalized text
    0.0 = no common tokens
    """

    current_normalized =normalize_text(
            current
        )

    previous_normalized =normalize_text(
            previous
        )


    if not current_normalized:
        return 0.0

    if not previous_normalized:
        return 0.0


    if (
        current_normalized
        == previous_normalized
    ):

        return 1.0


    current_tokens =set(
            current_normalized.split()
        )

    previous_tokens =set(
            previous_normalized.split()
        )


    if not current_tokens:
        return 0.0

    if not previous_tokens:
        return 0.0


    intersection =len(
            current_tokens
            & previous_tokens
        )

    union =len(
            current_tokens
            | previous_tokens
        )


    if union == 0:
        return 0.0


    return (
        intersection
        / union
    )


# ============================================================
# EXACT EVIDENCE MATCH
# ============================================================

def evidence_matches_exactly(
    current: Dict[str, Any],
    previous: Dict[str, Any],
) -> bool:
    """
    Check whether current and previous evidence are
    exactly identical after normalization.
    """

    return (
        normalize_text(
            current.get(
                "evidence",
                "",
            )
        )
        ==
        normalize_text(
            previous.get(
                "evidence",
                "",
            )
        )
    )


# ============================================================
# HISTORICAL EVIDENCE EXTRACTION
# ============================================================

def historical_evidence_set(
    previous_findings: Iterable[
        Dict[str, Any]
    ],
) -> set:
    """
    Build a set of normalized historical evidence.
    """

    evidence = set()


    for finding in previous_findings:

        value =normalize_text(
                finding.get(
                    "evidence",
                    "",
                )
            )


        if value:

            evidence.add(
                value
            )


    return evidence


# ============================================================
# HISTORICAL SIGNATURE SET
# ============================================================

def historical_signature_set(
    previous_findings: Iterable[
        Dict[str, Any]
    ],
) -> set:
    """
    Build a set of historical finding signatures.
    """

    signatures = set()


    for finding in previous_findings:

        signatures.add(
            build_finding_signature(
                finding
            )
        )


    return signatures


# ============================================================
# FIND BEST HISTORICAL MATCH
# ============================================================

def find_best_previous_match(
    current_finding: Dict[str, Any],
    previous_findings: List[
        Dict[str, Any]
    ],
) -> Optional[
    Dict[str, Any]
]:
    """
    Find the closest historical finding.

    Matching priority:
    1. Exact finding signature
    2. Same trigger/substance/topic/product
       with highest evidence similarity
    """

    if not previous_findings:

        return None


    current_signature =build_finding_signature(
            current_finding
        )


    # --------------------------------------------------------
    # Exact signature
    # --------------------------------------------------------

    for previous in previous_findings:

        if (
            build_finding_signature(
                previous
            )
            ==
            current_signature
        ):

            return previous


    # --------------------------------------------------------
    # Semantic comparison
    # --------------------------------------------------------

    current_key =build_finding_key(
            current_finding
        )


    candidates = []


    for previous in previous_findings:

        previous_key =build_finding_key(
                previous
            )


        # Require same trigger and substance.
        if (
            current_key[0]
            !=
            previous_key[0]
        ):

            continue


        if (
            current_key[1]
            !=
            previous_key[1]
        ):

            continue


        # If both products are known, they must match.
        if (
            current_key[3]
            and
            previous_key[3]
            and
            current_key[3]
            !=
            previous_key[3]
        ):

            continue


        similarity =evidence_similarity(
                current_finding.get(
                    "evidence",
                    "",
                ),
                previous.get(
                    "evidence",
                    "",
                ),
            )


        candidates.append(
            (
                similarity,
                previous,
            )
        )


    if not candidates:

        return None


    candidates.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )


    best_similarity, best_finding =candidates[0]


    # High similarity means the evidence is effectively
    # the same historical information.
    if best_similarity >= 0.92:

        return best_finding


    return None


# ============================================================
# COMPARE ONE FINDING
# ============================================================

def compare_finding(
    current_finding: Dict[str, Any],
    previous_findings: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:
    """
    Compare one current finding against historical findings.

    Returns the finding plus:
        comparison_status
        evidence_hash
        previous_finding
    """

    result =dict(
            current_finding
        )


    current_evidence =current_finding.get(
            "evidence",
            "",
        )


    result["evidence_hash"] =hash_text(
            current_evidence
        )


    previous =find_best_previous_match(
            current_finding,
            previous_findings,
        )


    if previous is None:

        result[
            "comparison_status"
        ] = "NEW_INFORMATION"

        result[
            "previous_finding"
        ] = None

        logger.info(
            "Finding classified as NEW_INFORMATION."
        )

        return result


    # --------------------------------------------------------
    # Exact evidence
    # --------------------------------------------------------

    if evidence_matches_exactly(
        current_finding,
        previous,
    ):

        result[
            "comparison_status"
        ] = "NO_NEW_INFORMATION"


        result[
            "previous_finding"
        ] = previous


        logger.info(
            "Finding classified as "
            "NO_NEW_INFORMATION."
        )


        return result


    # --------------------------------------------------------
    # Similar historical evidence
    # --------------------------------------------------------

    similarity =evidence_similarity(
            current_finding.get(
                "evidence",
                "",
            ),
            previous.get(
                "evidence",
                "",
            ),
        )


    if similarity >= 0.92:

        result[
            "comparison_status"
        ] = "NO_NEW_INFORMATION"

    else:

        result[
            "comparison_status"
        ] = "NEW_INFORMATION"


    result[
        "previous_finding"
    ] = previous


    result[
        "evidence_similarity"
    ] = similarity


    return result


# ============================================================
# COMPARE FINDINGS
# ============================================================

def compare_findings(
    current_findings: List[
        Dict[str, Any]
    ],
    previous_findings: Optional[
        List[Dict[str, Any]]
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Compare all current findings against previous findings.
    """

    previous_findings =previous_findings or []


    results = []


    for finding in current_findings:

        compared =compare_finding(
                finding,
                previous_findings,
            )


        results.append(
            compared
        )


    return results


# ============================================================
# COMPARE PAGE TEXT
# ============================================================

def compare_page_text(
    current_page_text: str,
    previous_page_text: Optional[str],
) -> str:
    """
    Compare two page texts.

    Returns:
        NEW_INFORMATION
        NO_NEW_INFORMATION
    """

    if not previous_page_text:

        return "NEW_INFORMATION"


    current =normalize_text(
            current_page_text
        )

    previous =normalize_text(
            previous_page_text
        )


    if current == previous:

        return "NO_NEW_INFORMATION"


    similarity =evidence_similarity(
            current,
            previous,
        )


    if similarity >= 0.98:

        return "NO_NEW_INFORMATION"


    return "NEW_INFORMATION"


# ============================================================
# FIND NEW INFORMATION
# ============================================================

def get_new_information(
    findings: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:
    """
    Return only findings classified as NEW_INFORMATION.
    """

    return [
        finding
        for finding in findings
        if finding.get(
            "comparison_status"
        )
        ==
        "NEW_INFORMATION"
    ]


# ============================================================
# FIND DUPLICATES
# ============================================================

def remove_duplicate_findings(
    findings: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:
    """
    Remove duplicate findings within the same monitoring run.
    """

    unique = []

    seen = set()


    for finding in findings:

        signature =build_finding_signature(
                finding
            )


        if signature in seen:

            continue


        seen.add(
            signature
        )


        unique.append(
            finding
        )


    return unique


# ============================================================
# COMPARISON SUMMARY
# ============================================================

def comparison_summary(
    findings: List[
        Dict[str, Any]
    ],
) -> Dict[str, int]:
    """
    Return simple comparison counts.
    """

    new_count = 0

    unchanged_count = 0


    for finding in findings:

        status =finding.get(
                "comparison_status"
            )


        if status == "NEW_INFORMATION":

            new_count += 1

        elif status == "NO_NEW_INFORMATION":

            unchanged_count += 1


    return {
        "total": len(findings),

        "new_information":
            new_count,

        "no_new_information":
            unchanged_count,
    }


# ============================================================
# MAIN TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\nSafety Trigger Comparator Test"
    )

    print(
        "=============================="
    )


    previous = [

        {
            "page_number": 10,

            "product_name":
                "Example Product",

            "active_substance":
                "alprazolam",

            "trigger_name":
                "Benzodiazepines",

            "safety_topic":
                "Safety Signal",

            "evidence":
                (
                    "The Committee reviewed "
                    "a safety signal concerning "
                    "alprazolam."
                ),
        }
    ]


    current_same = [

        {
            "page_number": 12,

            "product_name":
                "Example Product",

            "active_substance":
                "alprazolam",

            "trigger_name":
                "Benzodiazepines",

            "safety_topic":
                "Safety Signal",

            "evidence":
                (
                    "The Committee reviewed "
                    "a safety signal concerning "
                    "alprazolam."
                ),
        }
    ]


    current_new = [

        {
            "page_number": 15,

            "product_name":
                "Example Product",

            "active_substance":
                "alprazolam",

            "trigger_name":
                "Benzodiazepines",

            "safety_topic":
                "Pregnancy / Developmental Safety",

            "evidence":
                (
                    "The Committee reviewed "
                    "new safety information "
                    "concerning exposure during "
                    "pregnancy."
                ),
        }
    ]


    same_result =compare_findings(
            current_same,
            previous,
        )


    new_result =compare_findings(
            current_new,
            previous,
        )


    print(
        "\nExisting evidence:"
    )

    print(
        same_result[0][
            "comparison_status"
        ]
    )


    print(
        "\nNew evidence:"
    )

    print(
        new_result[0][
            "comparison_status"
        ]
    )


    print(
        "\nComparator test completed."
    )