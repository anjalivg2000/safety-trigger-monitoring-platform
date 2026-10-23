"""
EMA PRAC Crawler

Discovers PRAC meeting-minute PDF documents from the
European Medicines Agency website.

The crawler:
- validates URLs
- requests the EMA page
- locates the PRAC minutes section
- discovers all matching meeting-minute PDF links
- extracts meeting dates from filenames
- downloads PDFs with retries
"""

from __future__ import annotations

import json
import ast
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from lxml import html


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "sources.json"
)

EMAPRAC_URL = (
    "https://www.ema.europa.eu/en/committees/"
    "pharmacovigilance-risk-assessment-committee-prac"
)

PRAC_SECTION_XPATH = (
    "//h2[normalize-space()='PRAC minutes']"
)

MEETING_PDF_XPATH = (
    "//a[contains(@href, "
    "'/documents/minutes/minutes-prac-meeting-')]"
)

REQUEST_TIMEOUT = 30

DOWNLOAD_TIMEOUT = 60

MAX_RETRIES = 3

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/147.0 Safari/537.36"
)

CONTENT_TYPE_MATCHERS = {
    "Meeting Minutes": {
        "keywords": [
            "meeting minutes",
            "minutes",
            "minutes-prac-meeting",
        ],
    },
    "Agendas": {
        "keywords": [
            "agenda",
            "agendas",
            "agenda-prac-meeting",
        ],
    },
    "Highlights": {
        "keywords": [
            "highlights",
            "committee highlights",
            "meeting highlights",
        ],
    },
    "Rules of Procedure": {
        "keywords": [
            "rules of procedure",
        ],
    },
    "Work Plan": {
        "keywords": [
            "work plan",
            "work programme",
            "work program",
        ],
    },
    "PRAC recommendation on signals": {
        "keywords": [
            "prac recommendation on safety signals",
            "recommendations on safety signals",
            "safety signals",
            "signal management",
        ],
    },
    "Other published documents": {
        "keywords": [],
    },
}

logger = logging.getLogger(
    "safety_trigger_poc.crawler"
)


def normalize_content_types(value: Any) -> List[str]:
    """Normalize user/config input into a consistent list of content types."""

    if value is None:
        return []

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = [parsed]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                parsed = raw
            value = parsed if isinstance(parsed, list) else [parsed]

    if not isinstance(value, list):
        value = [value]

    normalized: List[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)

    return normalized


def normalize_source_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize source config values to consistent defaults and names."""

    content_types = normalize_content_types(
        config.get("content_types", config.get("safety_alert_type"))
    )

    return {
        "reference_no": str(config.get("reference_no") or "UNSPECIFIED_001"),
        "region": str(config.get("region") or "EEA"),
        "monitoring_frequency": str(config.get("monitoring_frequency") or "Monthly"),
        "website": str(config.get("website") or "EMA"),
        "safety_alert_type": str(config.get("safety_alert_type") or "PRAC"),
        "source_type": str(config.get("source_type") or "Health Authority"),
        "name": str(config.get("name") or config.get("safety_alert_type") or "Configured Source"),
        "url": str(config.get("url") or EMAPRAC_URL),
        "content_types": content_types,
        "instruction": str(config.get("instruction") or ""),
        "active": bool(config.get("active", True)),
    }


def load_default_source_configs() -> List[Dict[str, Any]]:
    """Load the default source definitions from config/sources.json when present."""

    fallback = [
        normalize_source_config({
            "reference_no": "EMA_PRAC_001",
            "region": "EEA",
            "monitoring_frequency": "Monthly",
            "website": "EMA",
            "safety_alert_type": "PRAC",
            "source_type": "PRAC",
            "name": "EMA PRAC Monitoring",
            "url": EMAPRAC_URL,
            "content_types": [
                "Meeting Minutes",
                "Agendas",
                "Highlights",
            ],
            "instruction": "Monitor the configured PRAC content sections for the latest published documents.",
            "active": True,
        }),
        normalize_source_config({
            "reference_no": "EMA_SIGNAL_001",
            "region": "EEA",
            "monitoring_frequency": "Monthly",
            "website": "EMA",
            "safety_alert_type": "PRAC recommendation on signals",
            "source_type": "PRAC Signals",
            "name": "EMA PRAC Signals",
            "url": "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/pharmacovigilance-post-authorisation/signal-management/prac-recommendations-safety-signals",
            "content_types": [
                "PRAC recommendation on signals",
            ],
            "instruction": "Check for the latest published document, download it and summarize the topic.",
            "active": True,
        }),
    ]

    if not CONFIG_PATH.exists():
        return fallback

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if isinstance(payload, dict):
            raw_sources = payload.get("sources", [])
        else:
            raw_sources = payload

        if not isinstance(raw_sources, list) or not raw_sources:
            return fallback

        return [normalize_source_config(source) for source in raw_sources]
    except Exception as exc:  # pragma: no cover - defensive config fallback
        logger.warning("Could not load source configuration from %s: %s", CONFIG_PATH, exc)
        return fallback


DEFAULT_SOURCE_CONFIGS = load_default_source_configs()


# ============================================================
# URL VALIDATION
# ============================================================

def validate_url(url: str) -> bool:
    """Validate that a URL is HTTP/HTTPS."""

    try:

        parsed = urlparse(url)

        return parsed.scheme in {
            "http",
            "https",
        } and bool(parsed.netloc)

    except Exception:

        return False


# ============================================================
# HTTP REQUEST
# ============================================================

def request_with_retries(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    max_attempts: int = MAX_RETRIES,
) -> requests.Response:

    if not validate_url(url):

        raise ValueError(
            f"Invalid URL: {url}"
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml;q=0.9,"
            "*/*;q=0.8"
        ),
    }

    last_error = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):

        try:

            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

            response.raise_for_status()

            return response

        except requests.RequestException as exc:

            last_error = exc

            logger.warning(
                "Request attempt %s/%s failed for %s: %s",
                attempt,
                max_attempts,
                url,
                exc,
            )

            if attempt < max_attempts:

                time.sleep(
                    2 ** (attempt - 1)
                )

    raise RuntimeError(
        f"Request failed after "
        f"{max_attempts} attempts: "
        f"{last_error}"
    )


# ============================================================
# MEETING DATE
# ============================================================

def extract_meeting_date(
    filename: str,
) -> str | None:
    """
    Extract the meeting date/range from a PRAC
    meeting-minutes filename.

    Example:
        minutes-prac-meeting-8-11-june-2026_en.pdf

    Returns:
        8-11 June 2026
    """

    name = Path(filename).name

    pattern = re.compile(
        r"minutes-prac-meeting-"
        r"(.+?)"
        r"(?:_en)?\.pdf$",
        re.IGNORECASE,
    )

    match = pattern.search(name)

    if not match:
        return None

    value = match.group(1)

    value = value.replace(
        "-",
        " ",
    )

    return value.strip()


# ============================================================
# TITLE
# ============================================================

def clean_link_title(
    title: str,
    filename: str,
) -> str:

    title = " ".join(
        (title or "").split()
    )

    if title:
        return title

    meeting_date = extract_meeting_date(
        filename
    )

    if meeting_date:

        return (
            "PRAC Meeting Minutes - "
            f"{meeting_date}"
        )

    return filename


# ============================================================
# PDF DISCOVERY
# ============================================================

def normalize_date_value(value: str | None) -> str | None:
    """Normalize a discovered date string to a user-friendly form."""

    if not value:
        return None

    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None

    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        cleaned,
    )
    if match:
        return match.group(1)

    return cleaned


def extract_publication_date(
    link: Any,
    page_url: str,
    content_type: str,
) -> str | None:
    """Extract a publication date from explicit source metadata, not meeting titles."""

    ancestor = link
    for _ in range(5):
        ancestor = ancestor.getparent()
        if ancestor is None:
            break

        ancestor_text = " ".join((ancestor.text_content() or "").split())
        match = re.search(
            r"\bFirst\s+published\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            ancestor_text,
            flags=re.IGNORECASE,
        )
        if match:
            for date_format in ("%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(
                        match.group(1),
                        date_format,
                    ).strftime("%d %B %Y")
                except ValueError:
                    continue

    return None


def build_document_key(document: Dict[str, Any]) -> str:
    """Build a stable identifier for document-level duplicate detection."""

    candidate = (
        document.get("document_key")
        or document.get("canonical_key")
        or document.get("url")
        or document.get("title")
        or ""
    )

    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    return ""


def deduplicate_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return unique documents keyed by a stable URL/document identifier."""

    seen = set()
    unique: List[Dict[str, Any]] = []

    for document in documents:
        if not isinstance(document, dict):
            continue

        key = build_document_key(document)
        if not key:
            continue

        stable_key = key.lower().rstrip("/")
        if stable_key in seen:
            continue

        seen.add(stable_key)
        unique.append(document)

    return unique


def classify_content_type(link_text: str, href_value: str) -> str | None:
    """Map a link title/URL to the configured content group when possible."""

    combined = " ".join([link_text or "", href_value or ""]).lower()
    for content_type, config in CONTENT_TYPE_MATCHERS.items():
        for keyword in config.get("keywords", []):
            if keyword.lower() in combined:
                return content_type
    if urlparse(href_value).path.lower().endswith(".pdf"):
        return "Other published documents"
    return None


def discover_configured_documents(
    page_url: str = EMAPRAC_URL,
    content_types: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Discover configured PRAC/EMA document links using the selected content type list."""

    selected_types = normalize_content_types(content_types) or list(CONTENT_TYPE_MATCHERS)
    response = request_with_retries(page_url, timeout=10, max_attempts=2)
    tree = html.fromstring(response.text)
    links = tree.xpath("//a[@href]")

    documents: List[Dict[str, Any]] = []
    seen_urls = set()

    for link in links:
        href_value = link.get("href", "")
        if not href_value:
            continue

        absolute_url = urljoin(page_url, href_value)
        if absolute_url in seen_urls:
            continue

        link_text = " ".join((link.text_content() or "").split())
        matched_type = classify_content_type(link_text, href_value)
        if not matched_type:
            continue

        target_path = urlparse(absolute_url).path.lower()
        if matched_type in {"Meeting Minutes", "Agendas"} and (
            "/documents/" not in target_path
            or not target_path.endswith(".pdf")
        ):
            continue
        if matched_type == "Highlights" and (
            "/en/news/meeting-highlights-" not in target_path
            or "meeting highlights" not in link_text.lower()
        ):
            continue
        if (
            matched_type == "PRAC recommendation on signals"
            and not target_path.endswith(".pdf")
        ):
            continue

        if selected_types and matched_type not in selected_types and not any(
            selected.lower() in matched_type.lower() or matched_type.lower() in selected.lower()
            for selected in selected_types
        ):
            continue

        if not absolute_url.lower().startswith("http"):
            continue

        filename = Path(urlparse(absolute_url).path).name
        title = link_text or matched_type
        if title.lower() in {"view", "download"}:
            title = f"{matched_type} - {filename or 'Document'}"

        publication_date = extract_publication_date(
            link,
            page_url,
            matched_type,
        )

        document = {
            "title": title,
            "url": absolute_url,
            "document_key": absolute_url,
            "filename": filename,
            "meeting_date": extract_meeting_date(filename),
            "publication_date": publication_date,
            "content_type": matched_type,
            "status": "NEW",
        }

        seen_urls.add(absolute_url)
        documents.append(document)

    unique_documents = deduplicate_documents(documents)
    logger.info("Discovered %s configured documents from %s.", len(unique_documents), page_url)
    return unique_documents


def discover_meeting_pdfs(
    page_url: str = EMAPRAC_URL,
    content_types: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Backward-compatible entry point for the existing PRAC document discovery logic."""

    return discover_configured_documents(
        page_url=page_url,
        content_types=content_types or ["Meeting Minutes"],
    )


# ============================================================
# SOURCE CRAWL
# ============================================================

def crawl_source(
    source_url: str,
    source_id: int | None = None,
    content_types: List[str] | None = None,
    source_name: str | None = None,
    reference_no: str | None = None,
) -> Dict[str, Any]:
    """Crawl a configured health-authority source and mark each document as new/already crawled."""

    try:
        selected_types = normalize_content_types(content_types)
        documents = discover_configured_documents(
            page_url=source_url,
            content_types=selected_types,
        )

        if source_id is not None:
            try:
                from .database import get_db

                with get_db() as conn:
                    existing_rows = conn.execute(
                        "SELECT url FROM documents WHERE source_id = ?",
                        (source_id,),
                    ).fetchall()

                existing_urls = {
                    str(row["url"]).rstrip("/")
                    for row in existing_rows
                }

                for document in documents:
                    url_value = str(document.get("document_key") or document.get("url") or "").rstrip("/")
                    document["status"] = "ALREADY_CRAWLED" if url_value and url_value.lower() in {item.lower() for item in existing_urls} else "NEW"
                    document["new_document"] = document["status"] == "NEW"
            except Exception:
                logger.exception("Failed to compare documents against existing crawl data for source %s", source_id)

        new_documents = sum(
            1 for document in documents if str(document.get("status", "")).upper() == "NEW"
        )

        return {
            "success": True,
            "status": "COMPLETED",
            "source_url": source_url,
            "documents": documents,
            "documents_found": len(documents),
            "new_documents": new_documents,
            "error": None,
        }

    except Exception as exc:
        logger.exception("Source crawl failed for %s.", source_url)
        return {
            "success": False,
            "status": "FAILED",
            "source_url": source_url,
            "documents": [],
            "documents_found": 0,
            "new_documents": 0,
            "error": str(exc),
        }


# ============================================================
# DOWNLOAD PDF
# ============================================================

def download_pdf(
    url: str,
    destination: str,
) -> str | None:
    """
    Download a PDF file with retries.

    The destination is always treated as a local
    filesystem path.
    """

    if not validate_url(url):

        raise ValueError(
            f"Invalid PDF URL: {url}"
        )

    destination_path = Path(
        destination
    )

    destination_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,*/*",
    }

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            with requests.get(
                url,
                headers=headers,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
                allow_redirects=True,
            ) as response:

                response.raise_for_status()

                content_type = (
                    response.headers
                    .get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

                temp_path = (
                    destination_path.with_suffix(
                        ".part"
                    )
                )

                with temp_path.open(
                    "wb"
                ) as file:

                    for chunk in response.iter_content(
                        chunk_size=1024 * 64
                    ):

                        if chunk:

                            file.write(
                                chunk
                            )

                if (
                    not temp_path.exists()
                    or temp_path.stat().st_size == 0
                ):

                    raise RuntimeError(
                        "Downloaded file is empty."
                    )

                with temp_path.open(
                    "rb"
                ) as file:

                    header = file.read(
                        5
                    )

                if header != b"%PDF-":

                    temp_path.unlink(
                        missing_ok=True
                    )

                    raise RuntimeError(
                        "Downloaded content is "
                        "not a valid PDF."
                    )

                temp_path.replace(
                    destination_path
                )

                logger.info(
                    "Downloaded PDF: %s",
                    destination_path,
                )

                return str(
                    destination_path
                )

        except Exception as exc:

            last_error = exc

            logger.warning(
                "PDF download attempt "
                "%s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    2 ** (attempt - 1)
                )

    logger.error(
        "PDF download failed: %s",
        last_error,
    )

    return None


# ============================================================
# SOURCE TEST
# ============================================================

def test_source(
    url: str,
    content_types: List[str] | None = None,
) -> Dict[str, Any]:
    """Test a health-authority source without inserting anything into the database."""

    result = {
        "url": url,
        "http_status": None,
        "section_found": False,
        "meeting_links_found": 0,
        "pdf_links_found": 0,
        "status": "ERROR",
        "error": None,
    }

    try:
        if not validate_url(url):
            raise ValueError("Invalid HTTP/HTTPS URL.")

        response = request_with_retries(url)
        result["http_status"] = response.status_code

        documents = discover_configured_documents(
            page_url=url,
            content_types=normalize_content_types(content_types) or ["Meeting Minutes"],
        )

        result["meeting_links_found"] = len(documents)
        result["pdf_links_found"] = len(documents)
        result["section_found"] = bool(documents)
        result["status"] = "SUCCESS" if result["section_found"] else "WARNING"
        return result

    except Exception as exc:
        logger.exception("Source test failed.")
        result["error"] = str(exc)
        return result


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    print(
        "\nTesting EMA PRAC crawler...\n"
    )

    result = test_source(
        EMAPRAC_URL
    )

    print(
        f"HTTP status: "
        f"{result['http_status']}"
    )

    print(
        f"PRAC section found: "
        f"{result['section_found']}"
    )

    print(
        f"PDF links found: "
        f"{result['pdf_links_found']}"
    )

    if result["error"]:

        print(
            f"Error: {result['error']}"
        )

    print()