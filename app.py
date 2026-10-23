import sys
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re
import sqlite3

import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import html as lxml_html
import pymupdf
import streamlit as st

# ============================================================
# PROJECT PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PDF_DIR = OUTPUT_DIR / "pdfs"
DB_FILE = OUTPUT_DIR / "safety_trigger.db"
CONFIG_DIR = BASE_DIR / "config"
SOURCE_FILE = CONFIG_DIR / "sources.xlsx"
TRIGGER_FILE = CONFIG_DIR / "triggers.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE_DIR))

from database.db import initialize_database
from crawler.crawler import run_crawler
from extraction.pdf_extractor import extract_all_pdfs
from detection.trigger_detector import run_detection
from detection.comparator import run_comparison


# ============================================================
# STREAMLIT CONFIG
# ============================================================
st.set_page_config(
    page_title="Safety Trigger Monitoring",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# DATABASE
# ============================================================
initialize_database()


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_FILE)


def read_table(table_name):
    try:
        with get_connection() as conn:
            return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    except Exception:
        return pd.DataFrame()


def scalar(query, params=()):
    try:
        with get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


# ============================================================
# SOURCE CONFIGURATION
# Handles Sheet 2, title rows, blank rows, whitespace and
# minor header variations.
# ============================================================
EXPECTED_SOURCE_COLUMNS = [
    "Health Authority",
    "Source Name",
    "URL",
    "Active",
    "Section XPath",
    "Link XPath",
    "Frequency",
]

HEADER_ALIASES = {
    "health authority": "Health Authority",
    "health_authority": "Health Authority",
    "authority": "Health Authority",
    "ha": "Health Authority",
    "source name": "Source Name",
    "source_name": "Source Name",
    "source": "Source Name",
    "url": "URL",
    "website": "URL",
    "web url": "URL",
    "active": "Active",
    "status": "Active",
    "section xpath": "Section XPath",
    "section_xpath": "Section XPath",
    "section x path": "Section XPath",
    "link xpath": "Link XPath",
    "link_xpath": "Link XPath",
    "link x path": "Link XPath",
    "frequency": "Frequency",
    "monitoring frequency": "Frequency",
}


def normalize_text(value):
    value = "" if value is None else str(value)
    value = value.replace("\n", " ").replace("\r", " ")
    value = value.replace("\u00a0", " ")
    return " ".join(value.strip().lower().split())


def canonical_header(value):
    normalized = normalize_text(value)
    return HEADER_ALIASES.get(normalized, normalized)


def is_active(value):
    return normalize_text(value) in {
        "yes", "y", "true", "1", "active", "enabled"
    }


def load_source_config():
    empty = pd.DataFrame(columns=EXPECTED_SOURCE_COLUMNS)

    if not SOURCE_FILE.exists():
        return empty, None, None, "sources.xlsx was not found."

    try:
        workbook = pd.ExcelFile(SOURCE_FILE, engine="openpyxl")
    except Exception as exc:
        return empty, None, None, f"Unable to open sources.xlsx: {exc}"

    required = set(EXPECTED_SOURCE_COLUMNS)

    # Search every sheet and first 30 rows for the real header.
    for sheet_name in workbook.sheet_names:
        try:
            raw = pd.read_excel(
                SOURCE_FILE,
                sheet_name=sheet_name,
                header=None,
                engine="openpyxl",
            )
        except Exception:
            continue

        if raw.empty:
            continue

        scan_rows = min(30, len(raw))

        for header_row in range(scan_rows):
            canonical = [canonical_header(x) for x in raw.iloc[header_row].tolist()]
            present = {x for x in canonical if x in required}

            if not required.issubset(present):
                continue

            data = raw.iloc[header_row + 1:].copy()
            data.columns = canonical

            # Remove duplicate column names while retaining the first one.
            data = data.loc[:, ~pd.Index(data.columns).duplicated()]

            for column in EXPECTED_SOURCE_COLUMNS:
                if column not in data.columns:
                    data[column] = ""

            data = data[EXPECTED_SOURCE_COLUMNS].copy()

            # Remove completely empty rows.
            data = data[
                data.apply(
                    lambda row: any(
                        normalize_text(v) for v in row.tolist()
                    ),
                    axis=1,
                )
            ]

            for column in EXPECTED_SOURCE_COLUMNS:
                data[column] = (
                    data[column]
                    .fillna("")
                    .astype(str)
                    .str.replace("\n", " ", regex=False)
                    .str.replace("\r", " ", regex=False)
                    .str.strip()
                )

            # Keep rows with a URL.
            data = data[data["URL"].str.strip() != ""].reset_index(drop=True)

            return data, sheet_name, header_row + 1, None

    return (
        empty,
        None,
        None,
        "The workbook was opened, but no row containing all seven required "
        "source columns was found.",
    )


def sync_sources_to_database(source_df):
    if source_df.empty:
        return

    with get_connection() as conn:
        for _, row in source_df.iterrows():
            url = str(row["URL"]).strip()
            if not url:
                continue

            values = (
                str(row["Health Authority"]).strip(),
                str(row["Source Name"]).strip(),
                url,
                str(row["Active"]).strip(),
                str(row["Section XPath"]).strip(),
                str(row["Link XPath"]).strip(),
                str(row["Frequency"]).strip(),
            )

            existing = conn.execute(
                "SELECT id FROM sources WHERE url = ?",
                (url,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE sources
                    SET health_authority = ?,
                        source_name = ?,
                        active = ?,
                        section_xpath = ?,
                        link_xpath = ?,
                        frequency = ?
                    WHERE url = ?
                    """,
                    (
                        values[0], values[1], values[3],
                        values[4], values[5], values[6], values[2],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sources
                    (
                        health_authority, source_name, url, active,
                        section_xpath, link_xpath, frequency
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )


source_config, detected_sheet, detected_header_row, source_config_error = (
    load_source_config()
)
sync_sources_to_database(source_config)

sources_df = read_table("sources")
documents_df = read_table("documents")
findings_df = read_table("safety_findings")
crawl_history_df = read_table("crawl_history")
extraction_history_df = read_table("extraction_history")


# ============================================================
# SAFE COLUMNS
# ============================================================
def ensure_column(df, column, default=""):
    if column not in df.columns:
        df[column] = default
    return df


for col in [
    "finding_status", "comparison_status", "reviewer_decision",
    "reviewer_comment", "evidence", "context_before", "context_after",
]:
    findings_df = ensure_column(findings_df, col)

for col in [
    "title", "pdf_filename", "meeting_date", "publication_date",
    "status", "extraction_status", "pages_extracted", "blocks_extracted",
    "health_authority", "source_name", "url",
]:
    documents_df = ensure_column(documents_df, col)


# ============================================================
# TRIGGERS
# ============================================================
def load_triggers():
    if not TRIGGER_FILE.exists():
        return []
    try:
        return json.loads(
            TRIGGER_FILE.read_text(encoding="utf-8")
        ).get("triggers", [])
    except Exception:
        return []


triggers = load_triggers()
active_trigger_count = sum(
    1 for trigger in triggers if trigger.get("active", True)
)


# ============================================================
# METRICS
# ============================================================
total_sources = len(source_config) if not source_config.empty else len(sources_df)
total_documents = len(documents_df)
total_findings = len(findings_df)

if documents_df.empty:
    new_documents = 0
else:
    new_documents = int(
        documents_df["status"]
        .fillna("")
        .astype(str)
        .str.upper()
        .isin(["NEW", "UPDATED"])
        .sum()
    )

if findings_df.empty:
    new_information = 0
    reviewed = 0
else:
    new_information = int(
        findings_df["comparison_status"]
        .fillna("")
        .astype(str)
        .str.upper()
        .eq("NEW_INFORMATION")
        .sum()
    )
    reviewed = int(
        findings_df["finding_status"]
        .fillna("")
        .astype(str)
        .str.upper()
        .eq("REVIEWED")
        .sum()
    )


# ============================================================
# ENTERPRISE THEME
# ============================================================
st.markdown(
    """
    <style>
    .stApp {
        background: #f4f6f9;
    }

    [data-testid="stSidebar"] {
        background: #101827;
    }

    [data-testid="stSidebar"] * {
        color: #e5e7eb;
    }

    [data-testid="stSidebar"] .stButton > button {
        border: 1px solid #334155;
        background: #172338;
        color: #f8fafc;
    }

    [data-testid="stSidebar"] .stButton > button:hover {
        border-color: #94a3b8;
        background: #22324d;
    }

    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dbe2ea;
        border-radius: 12px;
        padding: 14px 16px;
    }

    [data-testid="stMetricValue"] {
        color: #172033;
    }

    div[data-testid="stButton"] > button {
        border-radius: 8px;
        font-weight: 600;
        min-height: 42px;
    }

    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        color: #172033;
    }

    [data-testid="stExpander"] {
        border: 1px solid #dbe2ea;
        border-radius: 10px;
        background: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# FAST SOURCE CHECK
# Does NOT download PDFs. It only checks configured pages and
# compares discovered PDF URLs with the database.
# ============================================================
def fast_source_check(source_df):
    discovered_urls = set()
    errors = []

    if source_df.empty:
        return discovered_urls, errors

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 Safety-Trigger-Monitoring-POC "
                "compatible; regulatory monitoring"
            )
        }
    )

    for _, row in source_df.iterrows():
        if not is_active(row["Active"]):
            continue

        url = str(row["URL"]).strip()
        section_xpath = str(row["Section XPath"]).strip()
        link_xpath = str(row["Link XPath"]).strip()

        if not url or not link_xpath:
            continue

        try:
            response = session.get(
                url,
                timeout=20,
                allow_redirects=True,
            )
            response.raise_for_status()

            tree = lxml_html.fromstring(response.content)

            # Prefer the configured section as the search area.
            section_nodes = (
                tree.xpath(section_xpath)
                if section_xpath
                else [tree]
            )

            if not section_nodes:
                section_nodes = [tree]

            links = []
            for node in section_nodes:
                try:
                    links.extend(node.xpath(link_xpath))
                except Exception:
                    pass

            # If the link XPath is absolute against the full page,
            # try it against the page too.
            if not links:
                try:
                    links = tree.xpath(link_xpath)
                except Exception:
                    links = []

            for link in links:
                href = ""

                if isinstance(link, str):
                    href = link
                else:
                    href = (
                        link.get("href")
                        or link.get("src")
                        or ""
                    )

                if not href:
                    continue

                absolute = requests.compat.urljoin(response.url, href)

                if ".pdf" in absolute.lower():
                    discovered_urls.add(absolute)

        except Exception as exc:
            errors.append(
                f"{row['Source Name']}: {type(exc).__name__}: {exc}"
            )

    return discovered_urls, errors


def get_existing_document_urls():
    if documents_df.empty or "url" not in documents_df.columns:
        return set()
    return {
        str(x).strip()
        for x in documents_df["url"].dropna().tolist()
        if str(x).strip()
    }


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.title("Safety Surveillance")
    st.caption("Regulatory Monitoring Platform")
    st.divider()

    st.subheader("Actions")

    st.caption("FAST MONITORING")
    st.caption(
        "Checks source pages first. Existing PDFs are not reprocessed "
        "when no new documents are detected."
    )

    run_button = st.button(
        "Run monitoring",
        use_container_width=True,
        type="primary",
        key="run_monitoring_button",
    )

    if run_button:
        if source_config.empty:
            st.error(
                "Monitoring cannot start because sources.xlsx has no valid "
                "source configuration."
            )
        else:
            with st.status(
                "Running safety surveillance...",
                expanded=True,
            ) as status:
                try:
                    st.write("1/4  Fast-checking Health Authority pages")
                    discovered_urls, check_errors = fast_source_check(
                        source_config
                    )

                    existing_urls = get_existing_document_urls()
                    new_urls = discovered_urls - existing_urls

                    if check_errors:
                        for message in check_errors:
                            st.warning(message)

                    st.write(
                        f"Source check complete: "
                        f"{len(discovered_urls)} PDF link(s) found, "
                        f"{len(new_urls)} new."
                    )

                    if not new_urls:
                        status.update(
                            label="Monitoring complete — no new documents",
                            state="complete",
                            expanded=False,
                        )
                        st.success(
                            "No new documents were detected. "
                            "Existing documents were not reprocessed."
                        )
                    else:
                        st.write("2/4  Downloading and registering new documents")
                        run_crawler()

                        st.write("3/4  Extracting PDF content")
                        extract_all_pdfs()

                        st.write("4/4  Detecting and comparing safety information")
                        run_detection()
                        run_comparison()

                        status.update(
                            label="Monitoring completed",
                            state="complete",
                            expanded=False,
                        )
                        st.success(
                            f"Monitoring completed. "
                            f"{len(new_urls)} new document link(s) were detected."
                        )

                    st.rerun()

                except Exception as exc:
                    status.update(
                        label="Monitoring failed",
                        state="error",
                        expanded=True,
                    )
                    st.error(
                        f"{type(exc).__name__}: {exc}"
                    )

    st.divider()

    st.subheader("System")
    st.caption("Environment")
    st.info("DEVELOPMENT POC")

    st.caption("Database")
    st.code(DB_FILE.name)

    s1, s2 = st.columns(2)
    with s1:
        st.metric("Sources", total_sources)
    with s2:
        st.metric("Triggers", active_trigger_count)

    st.divider()

    st.caption("Project")
    st.write("Safety Trigger Monitoring POC")
    st.caption(
        "Automated surveillance supports human PV/regulatory review. "
        "Final assessment remains with the designated reviewer."
    )


# ============================================================
# HEADER
# ============================================================
left, right = st.columns([5, 1])

with left:
    st.title("Safety Trigger Monitoring")
    st.caption(
        "Health Authority surveillance and safety information review"
    )

with right:
    st.info("DEVELOPMENT POC")

st.divider()


# ============================================================
# KPI
# ============================================================
k1, k2, k3, k4, k5, k6 = st.columns(6)

k1.metric("Sources", total_sources)
k2.metric("Documents", total_documents)
k3.metric("New Documents", new_documents)
k4.metric("Findings", total_findings)
k5.metric("New Information", new_information)
k6.metric("Reviewed", reviewed)


# ============================================================
# NAVIGATION
# ============================================================
tabs = st.tabs(
    [
        "Overview",
        "Health Authority Sources",
        "Documents",
        "New Information",
        "Safety Findings",
        "Document Viewer",
        "Configuration",
        "History",
    ]
)


# ============================================================
# OVERVIEW
# ============================================================
with tabs[0]:
    st.header("Monitoring Overview")
    st.caption(
        "Operational view of surveillance sources, documents and findings."
    )

    a, b = st.columns([1.5, 1])

    with a:
        st.subheader("Source Status")

        if sources_df.empty:
            if source_config.empty:
                st.warning(
                    "No configured sources are available."
                )
            else:
                st.info(
                    "Source configuration was loaded, but the database "
                    "does not yet contain source records."
                )
        else:
            overview = sources_df.copy()

            display_cols = [
                c for c in [
                    "health_authority",
                    "source_name",
                    "active",
                    "frequency",
                    "last_status",
                    "last_crawled",
                ]
                if c in overview.columns
            ]

            st.dataframe(
                overview[display_cols],
                use_container_width=True,
                hide_index=True,
            )

    with b:
        st.subheader("Latest Monitoring Run")

        if crawl_history_df.empty:
            st.info("No monitoring run has been recorded yet.")
        else:
            latest = crawl_history_df.sort_values(
                "id",
                ascending=False,
            ).iloc[0]

            r1, r2 = st.columns(2)
            r1.metric(
                "Documents found",
                int(latest.get("documents_found", 0) or 0),
            )
            r2.metric(
                "New",
                int(latest.get("new_documents", 0) or 0),
            )

            st.metric(
                "Existing",
                int(latest.get("existing_documents", 0) or 0),
            )

            st.caption(
                f"Run: {latest.get('crawl_time', '')}"
            )

    st.divider()

    st.subheader("Processing Pipeline")

    p1, p2, p3, p4 = st.columns(4)

    p1.info("1  Source discovery\n\nHealth Authority pages + XPath")
    p2.info("2  Document extraction\n\nPDF text and page metadata")
    p3.info("3  Trigger detection\n\nConfigured substances + terms")
    p4.info("4  Comparison\n\nNew information for human review")

    st.divider()

    if not findings_df.empty:
        st.subheader("Finding Summary")

        summary = (
            findings_df.groupby(
                ["trigger_name", "comparison_status"],
                dropna=False,
            )
            .size()
            .reset_index(name="Count")
        )

        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# HEALTH AUTHORITY SOURCES
# ============================================================
with tabs[1]:
    st.header("Health Authority Sources")
    st.caption(
        "Configured surveillance endpoints, XPath rules and monitoring frequency."
    )

    if source_config_error:
        st.error(source_config_error)

        if SOURCE_FILE.exists():
            st.write("Workbook diagnostics")
            st.write(
                f"File: {SOURCE_FILE.name}"
            )

            try:
                workbook = pd.ExcelFile(
                    SOURCE_FILE,
                    engine="openpyxl",
                )
                st.write(
                    f"Sheets found: {', '.join(workbook.sheet_names)}"
                )

                diagnostic_rows = []
                for sheet in workbook.sheet_names:
                    raw = pd.read_excel(
                        SOURCE_FILE,
                        sheet_name=sheet,
                        header=None,
                        nrows=8,
                        engine="openpyxl",
                    )

                    diagnostic_rows.append(
                        {
                            "Sheet": sheet,
                            "Rows inspected": len(raw),
                            "First-row values": " | ".join(
                                normalize_text(x)
                                for x in (
                                    raw.iloc[0].tolist()
                                    if len(raw) else []
                                )
                                if normalize_text(x)
                            )[:300],
                        }
                    )

                st.dataframe(
                    pd.DataFrame(diagnostic_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception as exc:
                st.error(f"Workbook diagnostic failed: {exc}")

        st.write("Required columns:")
        st.code(
            "Health Authority | Source Name | URL | Active | "
            "Section XPath | Link XPath | Frequency"
        )

    else:
        st.success(
            f"Configuration loaded from sheet '{detected_sheet}' "
            f"(header row {detected_header_row})."
        )

        st.dataframe(
            source_config,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            f"{len(source_config)} configured source(s)"
        )

        if not source_config.empty:
            st.divider()
            st.subheader("Source Details")

            selected_source = st.selectbox(
                "Select source",
                source_config["Source Name"].tolist(),
                key="source_details_select",
            )

            source_row = source_config[
                source_config["Source Name"] == selected_source
            ].iloc[0]

            c1, c2 = st.columns(2)

            with c1:
                st.write("Health Authority")
                st.write(source_row["Health Authority"])

                st.write("Source Name")
                st.write(source_row["Source Name"])

                st.write("Frequency")
                st.write(source_row["Frequency"])

                st.write("Active")
                st.write(source_row["Active"])

            with c2:
                st.write("Source URL")
                st.code(source_row["URL"])

                st.write("Section XPath")
                st.code(source_row["Section XPath"])

                st.write("Link XPath")
                st.code(source_row["Link XPath"])

            st.divider()
            st.subheader("Database Source Status")

            db_match = sources_df[
                sources_df["url"].astype(str).eq(
                    str(source_row["URL"])
                )
            ] if not sources_df.empty and "url" in sources_df.columns else pd.DataFrame()

            if db_match.empty:
                st.warning(
                    "This source is configured in Excel but has not yet "
                    "been synchronized into the database."
                )
            else:
                st.dataframe(
                    db_match,
                    use_container_width=True,
                    hide_index=True,
                )


# ============================================================
# DOCUMENTS
# ============================================================
with tabs[2]:
    st.header("Documents")
    st.caption(
        "Documents discovered, downloaded and processed by the monitoring pipeline."
    )

    if documents_df.empty:
        st.info(
            "No documents are currently registered. Run monitoring to discover documents."
        )
    else:
        f1, f2, f3 = st.columns(3)

        statuses = ["All"] + sorted(
            documents_df["status"]
            .fillna("")
            .astype(str)
            .unique()
            .tolist()
        )

        with f1:
            selected_status = st.selectbox(
                "Status",
                statuses,
                key="document_status_filter_v2",
            )

        with f2:
            search = st.text_input(
                "Search documents",
                placeholder="Title, source or PDF filename",
                key="document_search_v2",
            )

        with f3:
            source_options = ["All"] + sorted(
                documents_df["source_name"]
                .fillna("")
                .astype(str)
                .unique()
                .tolist()
            )

            selected_source_filter = st.selectbox(
                "Source",
                source_options,
                key="document_source_filter_v2",
            )

        filtered = documents_df.copy()

        if selected_status != "All":
            filtered = filtered[
                filtered["status"]
                .fillna("")
                .astype(str)
                == selected_status
            ]

        if selected_source_filter != "All":
            filtered = filtered[
                filtered["source_name"]
                .fillna("")
                .astype(str)
                == selected_source_filter
            ]

        if search.strip():
            term = search.strip().lower()

            mask = (
                filtered["title"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
                |
                filtered["pdf_filename"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
                |
                filtered["source_name"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
            )

            filtered = filtered[mask]

        display_cols = [
            c for c in [
                "id",
                "health_authority",
                "source_name",
                "title",
                "pdf_filename",
                "meeting_date",
                "publication_date",
                "status",
                "pages_extracted",
                "blocks_extracted",
                "extraction_status",
            ]
            if c in filtered.columns
        ]

        st.dataframe(
            filtered[display_cols],
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            f"{len(filtered)} document(s) shown"
        )


# ============================================================
# NEW INFORMATION
# ============================================================
with tabs[3]:
    st.header("New Information Review")
    st.caption(
        "Findings identified by the comparison engine as new information."
    )

    if findings_df.empty:
        st.info("No findings are available.")
    else:
        new_df = findings_df[
            findings_df["comparison_status"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("NEW_INFORMATION")
        ].copy()

        no_new_df = findings_df[
            findings_df["comparison_status"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("NO_NEW_INFORMATION")
        ].copy()

        n1, n2, n3 = st.columns(3)
        n1.metric("New information", len(new_df))
        n2.metric("No new information", len(no_new_df))
        n3.metric("Total findings", len(findings_df))

        st.divider()

        if new_df.empty:
            st.success(
                "No findings are currently marked as new information."
            )
        else:
            for _, finding in new_df.iterrows():
                finding_id = int(finding["id"])

                with st.expander(
                    f"{finding.get('trigger_name', 'Trigger')}  |  "
                    f"{finding.get('pdf_filename', 'Document')}  |  "
                    f"Page {finding.get('page_number', '')}",
                    expanded=False,
                ):
                    a, b, c = st.columns(3)

                    a.write("Finding ID")
                    a.write(str(finding_id))

                    b.write("Comparison")
                    b.write(str(finding.get("comparison_status", "")))

                    c.write("Finding status")
                    c.write(str(finding.get("finding_status", "NEW")))

                    st.write("Matched substances")
                    st.write(
                        str(finding.get("matched_substances", ""))
                    )

                    st.write("Relevant terms")
                    st.write(
                        str(finding.get("relevant_terms", ""))
                    )

                    st.write("Evidence")
                    st.code(
                        str(finding.get("evidence", "")),
                        language="text",
                    )

                    if str(finding.get("context_before", "")).strip():
                        st.write("Context before")
                        st.code(
                            str(finding.get("context_before", "")),
                            language="text",
                        )

                    if str(finding.get("context_after", "")).strip():
                        st.write("Context after")
                        st.code(
                            str(finding.get("context_after", "")),
                            language="text",
                        )


# ============================================================
# SAFETY FINDINGS
# ============================================================
with tabs[4]:
    st.header("Safety Findings")
    st.caption(
        "Detected Safety Trigger matches. Human reviewer assessment remains required."
    )

    if findings_df.empty:
        st.info("No safety findings are available.")
    else:
        f1, f2, f3, f4 = st.columns(4)

        trigger_options = ["All"] + sorted(
            findings_df["trigger_name"]
            .fillna("")
            .astype(str)
            .unique()
            .tolist()
        )

        with f1:
            selected_trigger = st.selectbox(
                "Trigger",
                trigger_options,
                key="finding_trigger_filter_v2",
            )

        with f2:
            selected_status = st.selectbox(
                "Finding status",
                ["All", "NEW", "REVIEWED"],
                key="finding_status_filter_v2",
            )

        with f3:
            selected_comparison = st.selectbox(
                "Comparison",
                ["All", "NEW_INFORMATION", "NO_NEW_INFORMATION"],
                key="finding_comparison_filter_v2",
            )

        with f4:
            finding_search = st.text_input(
                "Search",
                placeholder="Substance, term or document",
                key="finding_search_v2",
            )

        filtered_findings = findings_df.copy()

        if selected_trigger != "All":
            filtered_findings = filtered_findings[
                filtered_findings["trigger_name"]
                .fillna("")
                .astype(str)
                == selected_trigger
            ]

        if selected_status != "All":
            filtered_findings = filtered_findings[
                filtered_findings["finding_status"]
                .fillna("")
                .astype(str)
                .str.upper()
                == selected_status
            ]

        if selected_comparison != "All":
            filtered_findings = filtered_findings[
                filtered_findings["comparison_status"]
                .fillna("")
                .astype(str)
                .str.upper()
                == selected_comparison
            ]

        if finding_search.strip():
            term = finding_search.strip().lower()

            mask = (
                filtered_findings["matched_substances"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
                |
                filtered_findings["relevant_terms"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
                |
                filtered_findings["pdf_filename"]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(term, regex=False)
            )

            filtered_findings = filtered_findings[mask]

        st.caption(
            f"{len(filtered_findings)} finding(s)"
        )

        for _, finding in filtered_findings.iterrows():
            finding_id = int(finding["id"])

            with st.expander(
                f"{finding.get('trigger_name', 'Trigger')}  |  "
                f"{finding.get('pdf_filename', 'Document')}  |  "
                f"Page {finding.get('page_number', '')}",
                expanded=False,
            ):
                a, b, c = st.columns(3)

                with a:
                    st.write("Finding status")
                    st.write(
                        str(finding.get("finding_status", "NEW"))
                    )

                with b:
                    st.write("Comparison")
                    st.write(
                        str(finding.get("comparison_status", ""))
                    )

                with c:
                    st.write("Page")
                    st.write(
                        str(finding.get("page_number", ""))
                    )

                st.write("Matched substances")
                st.write(
                    str(finding.get("matched_substances", ""))
                )

                st.write("Relevant terms")
                st.write(
                    str(finding.get("relevant_terms", ""))
                )

                st.write("Evidence")
                st.code(
                    str(finding.get("evidence", "")),
                    language="text",
                )

                st.divider()

                st.write("Reviewer Assessment")

                decisions = [
                    "",
                    "Relevant",
                    "Not Relevant",
                    "Needs Review",
                ]

                current_decision = finding.get(
                    "reviewer_decision",
                    "",
                )

                if pd.isna(current_decision):
                    current_decision = ""

                current_decision = str(current_decision)

                if current_decision not in decisions:
                    current_decision = ""

                decision = st.selectbox(
                    "Decision",
                    decisions,
                    index=decisions.index(current_decision),
                    key=f"decision_v2_{finding_id}",
                )

                current_comment = finding.get(
                    "reviewer_comment",
                    "",
                )

                if pd.isna(current_comment):
                    current_comment = ""

                comment = st.text_area(
                    "Reviewer comment",
                    value=str(current_comment),
                    height=100,
                    key=f"review_comment_v2_{finding_id}",
                )

                if st.button(
                    "Save assessment",
                    type="primary",
                    key=f"save_assessment_v2_{finding_id}",
                ):
                    with get_connection() as conn:
                        conn.execute(
                            """
                            UPDATE safety_findings
                            SET finding_status = 'REVIEWED',
                                reviewer_decision = ?,
                                reviewer_comment = ?,
                                reviewed_at = datetime('now')
                            WHERE id = ?
                            """,
                            (decision, comment, finding_id),
                        )

                    st.success("Assessment saved.")
                    st.rerun()


# ============================================================
# DOCUMENT VIEWER
# ============================================================
with tabs[5]:
    st.header("Document Viewer")
    st.caption(
        "Open, search, inspect and download the PDF documents in the POC library."
    )

    pdf_files = sorted(
        PDF_DIR.glob("*.pdf"),
        key=lambda p: p.name.lower(),
    )

    uploaded_pdf = st.file_uploader(
        "Add PDF to document library",
        type=["pdf"],
        key="document_library_uploader",
    )

    if uploaded_pdf is not None:
        target = PDF_DIR / Path(uploaded_pdf.name).name
        target.write_bytes(uploaded_pdf.getbuffer())
        st.success(
            f"Added: {target.name}"
        )

        pdf_files = sorted(
            PDF_DIR.glob("*.pdf"),
            key=lambda p: p.name.lower(),
        )

    if not pdf_files:
        st.info(
            "No PDFs are currently available. Run monitoring or upload a PDF."
        )
    else:
        selected_name = st.selectbox(
            "Select document",
            [p.name for p in pdf_files],
            key="viewer_document_select_v2",
        )

        selected_path = PDF_DIR / selected_name

        try:
            pdf = pymupdf.open(selected_path)
            page_count = len(pdf)

            v1, v2, v3, v4 = st.columns(4)

            v1.metric("Pages", page_count)
            v2.metric(
                "Size",
                f"{selected_path.stat().st_size / 1024:.1f} KB",
            )
            v3.metric(
                "Modified",
                datetime.fromtimestamp(
                    selected_path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M"),
            )
            v4.metric(
                "Document",
                selected_path.suffix.upper(),
            )

            st.download_button(
                "Download original PDF",
                data=selected_path.read_bytes(),
                file_name=selected_path.name,
                mime="application/pdf",
                key="download_pdf_v2",
            )

            st.divider()

            c1, c2 = st.columns([1, 3])

            with c1:
                page_number = st.number_input(
                    "Page",
                    min_value=1,
                    max_value=page_count,
                    value=1,
                    step=1,
                    key="viewer_page_number_v2",
                )

            with c2:
                search_term = st.text_input(
                    "Search page",
                    placeholder="Enter a word or phrase",
                    key="viewer_search_v2",
                )

            page = pdf.load_page(int(page_number) - 1)
            page_text = page.get_text("text")

            if search_term.strip():
                if search_term.strip().lower() in page_text.lower():
                    st.success(
                        f"'{search_term.strip()}' was found on page {page_number}."
                    )
                else:
                    st.warning(
                        f"'{search_term.strip()}' was not found on page {page_number}."
                    )

            st.subheader(
                f"Page {page_number} of {page_count}"
            )

            if page_text.strip():
                st.code(
                    page_text,
                    language="text",
                )
            else:
                st.info(
                    "This page does not contain selectable text."
                )

            pdf.close()

        except Exception as exc:
            st.error(
                f"Unable to open PDF: {type(exc).__name__}: {exc}"
            )


# ============================================================
# CONFIGURATION
# ============================================================
with tabs[6]:
    st.header("Configuration")
    st.caption(
        "POC trigger configuration and source workbook status."
    )

    st.subheader("Safety Triggers")

    if not triggers:
        st.warning(
            f"No trigger configuration found: {TRIGGER_FILE}"
        )
    else:
        for trigger_index, trigger in enumerate(triggers):
            name = trigger.get(
                "trigger_name",
                "Unnamed Trigger",
            )

            trigger_type = trigger.get(
                "trigger_type",
                "Unknown",
            )

            active = bool(
                trigger.get("active", True)
            )

            with st.expander(
                f"{name}  |  {trigger_type}  |  "
                f"{'ACTIVE' if active else 'INACTIVE'}",
                expanded=True,
            ):
                c1, c2 = st.columns(2)

                with c1:
                    st.write("Trigger type")
                    st.write(trigger_type)

                    st.write("Status")
                    st.write(
                        "Active" if active else "Inactive"
                    )

                    st.write("Substances")
                    st.code(
                        "\n".join(
                            str(x)
                            for x in trigger.get("substances", [])
                        ),
                        language="text",
                    )

                with c2:
                    st.write("Relevance terms")
                    st.code(
                        "\n".join(
                            str(x)
                            for x in trigger.get("relevance_terms", [])
                        ),
                        language="text",
                    )

    st.divider()

    st.subheader("Source Workbook")

    if source_config_error:
        st.error(source_config_error)
        st.write(
            f"Expected file: `{SOURCE_FILE}`"
        )
    else:
        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Configured sources",
            len(source_config),
        )
        c2.metric(
            "Workbook sheet",
            str(detected_sheet),
        )
        c3.metric(
            "Header row",
            int(detected_header_row or 0),
        )

        st.dataframe(
            source_config,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.subheader("Database")

    db_size = (
        DB_FILE.stat().st_size / 1024
        if DB_FILE.exists()
        else 0
    )

    d1, d2, d3 = st.columns(3)

    d1.metric(
        "Database",
        DB_FILE.name,
    )
    d2.metric(
        "Size",
        f"{db_size:.1f} KB",
    )
    d3.metric(
        "Documents",
        total_documents,
    )

    st.caption(
        f"Database path: {DB_FILE}"
    )


# ============================================================
# HISTORY
# ============================================================
with tabs[7]:
    st.header("Processing History")
    st.caption(
        "Audit-oriented record of source crawling and PDF extraction activity."
    )

    h1, h2 = st.columns(2)

    with h1:
        st.subheader("Crawler History")

        if crawl_history_df.empty:
            st.info(
                "No crawler history is available."
            )
        else:
            history = crawl_history_df.sort_values(
                "id",
                ascending=False,
            ).head(50)

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True,
            )

    with h2:
        st.subheader("Extraction History")

        if extraction_history_df.empty:
            st.info(
                "No extraction history is available."
            )
        else:
            history = extraction_history_df.sort_values(
                "id",
                ascending=False,
            ).head(50)

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    st.subheader("Database Activity Summary")

    activity = pd.DataFrame(
        [
            ["Configured sources", total_sources],
            ["Registered documents", total_documents],
            ["Safety findings", total_findings],
            ["New information", new_information],
            ["Reviewed findings", reviewed],
        ],
        columns=["Metric", "Value"],
    )

    st.dataframe(
        activity,
        use_container_width=False,
        hide_index=True,
    )


# ============================================================
# FOOTER
# ============================================================
st.divider()
st.caption(
    "Safety Trigger Monitoring POC  •  Automated surveillance and "
    "evidence extraction support human regulatory review."
)
