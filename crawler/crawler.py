import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import html

from database.db import initialize_database


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "sources.xlsx"
DB_FILE = BASE_DIR / "output" / "safety_trigger.db"
PDF_DIR = BASE_DIR / "output" / "pdfs"

PDF_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/147.0 Safari/537.36"
    )
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection():
    initialize_database()
    return sqlite3.connect(DB_FILE)


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def extract_date(text):
    """
    Try to find common date formats in the document title/link text.
    """
    patterns = [
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b",
        r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b",
        r"\b([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(0)

    return ""


def make_filename(title, url):
    title = clean_text(title)

    if not title:
        title = Path(url.split("?")[0]).stem

    title = re.sub(r'[<>:"/\\|?*]', "_", title)
    title = re.sub(r"\s+", "_", title)

    return title[:150] + ".pdf"


def calculate_hash(content):
    return hashlib.sha256(content).hexdigest()


def save_pdf(url, filename):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=60
    )

    response.raise_for_status()

    filepath = PDF_DIR / filename

    with open(filepath, "wb") as file:
        file.write(response.content)

    return filepath, response.status_code, calculate_hash(response.content)


def upsert_source(conn, row):
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sources (
            health_authority,
            source_name,
            url,
            active,
            section_xpath,
            link_xpath,
            frequency,
            last_crawled,
            last_status,
            last_error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(url) DO UPDATE SET
            health_authority = excluded.health_authority,
            source_name = excluded.source_name,
            active = excluded.active,
            section_xpath = excluded.section_xpath,
            link_xpath = excluded.link_xpath,
            frequency = excluded.frequency,
            last_crawled = excluded.last_crawled,
            last_status = excluded.last_status,
            last_error = excluded.last_error
        """,
        (
            clean_text(row["Health Authority"]),
            clean_text(row["Source Name"]),
            clean_text(row["URL"]),
            clean_text(row["Active"]),
            clean_text(row["Section XPath"]),
            clean_text(row["Link XPath"]),
            clean_text(row["Frequency"]),
            now(),
            "",
            ""
        )
    )

    conn.commit()

    cursor.execute(
        "SELECT id FROM sources WHERE url = ?",
        (clean_text(row["URL"]),)
    )

    return cursor.fetchone()[0]


def document_exists(conn, url):
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, document_hash, status
        FROM documents
        WHERE url = ?
        """,
        (url,)
    )

    return cursor.fetchone()


def save_document(
    conn,
    source_id,
    row,
    title,
    url,
    pdf_filename,
    meeting_date,
    document_hash,
    status,
    http_status
):
    timestamp = now()

    existing = document_exists(conn, url)

    cursor = conn.cursor()

    if existing:
        document_id = existing[0]

        cursor.execute(
            """
            UPDATE documents
            SET
                source_id = ?,
                health_authority = ?,
                source_name = ?,
                title = ?,
                pdf_filename = ?,
                meeting_date = ?,
                document_hash = ?,
                status = ?,
                http_status = ?,
                last_checked = ?
            WHERE id = ?
            """,
            (
                source_id,
                clean_text(row["Health Authority"]),
                clean_text(row["Source Name"]),
                title,
                pdf_filename,
                meeting_date,
                document_hash,
                status,
                http_status,
                timestamp,
                document_id
            )
        )

    else:
        cursor.execute(
            """
            INSERT INTO documents (
                source_id,
                health_authority,
                source_name,
                title,
                url,
                pdf_filename,
                meeting_date,
                publication_date,
                document_hash,
                status,
                http_status,
                discovered_at,
                first_seen,
                last_checked,
                pages_extracted,
                blocks_extracted,
                extraction_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'PENDING')
            """,
            (
                source_id,
                clean_text(row["Health Authority"]),
                clean_text(row["Source Name"]),
                title,
                url,
                pdf_filename,
                meeting_date,
                meeting_date,
                document_hash,
                status,
                http_status,
                timestamp,
                timestamp,
                timestamp
            )
        )

        document_id = cursor.lastrowid

    conn.commit()

    return document_id


def crawl_source(conn, row):
    health_authority = clean_text(row["Health Authority"])
    source_name = clean_text(row["Source Name"])
    source_url = clean_text(row["URL"])

    section_xpath = clean_text(row["Section XPath"])
    link_xpath = clean_text(row["Link XPath"])

    print()
    print("=" * 70)
    print(f"SOURCE: {health_authority} - {source_name}")
    print(f"URL: {source_url}")
    print("=" * 70)

    source_id = upsert_source(conn, row)

    try:
        response = requests.get(
            source_url,
            headers=HEADERS,
            timeout=60
        )

        print(f"HTTP Status: {response.status_code}")

        response.raise_for_status()

        page = html.fromstring(response.content)

        # ------------------------------------------------------------
        # SECTION XPATH
        # ------------------------------------------------------------

        section_nodes = page.xpath(section_xpath)

        print(f"Section XPath: {section_xpath}")
        print(f"Sections found: {len(section_nodes)}")

        # ------------------------------------------------------------
        # LINK XPATH
        # ------------------------------------------------------------

        links = page.xpath(link_xpath)

        print(f"Link XPath: {link_xpath}")
        print(f"Links found: {len(links)}")

        documents_found = 0
        new_documents = 0
        existing_documents = 0

        for link in links:

            href = link.get("href")

            if not href:
                continue

            url = urljoin(source_url, href)

            # Only process PDF links
            if not url.lower().endswith(".pdf"):
                continue

            documents_found += 1

            title = clean_text(link.text_content())

            if not title:
                title = Path(
                    url.split("?")[0]
                ).stem

            meeting_date = extract_date(
                title + " " + url
            )

            print()
            print(f"Document {documents_found}:")
            print(f"Title: {title}")
            print(f"URL: {url}")
            print(f"Date: {meeting_date}")

            existing = document_exists(conn, url)

            # --------------------------------------------------------
            # EXISTING DOCUMENT
            # --------------------------------------------------------

            if existing:
                existing_documents += 1

                print("Status: EXISTING")

                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE documents
                    SET
                        last_checked = ?,
                        status = 'EXISTING',
                        http_status = ?
                    WHERE id = ?
                    """,
                    (
                        now(),
                        response.status_code,
                        existing[0]
                    )
                )

                conn.commit()

                continue

            # --------------------------------------------------------
            # NEW DOCUMENT
            # --------------------------------------------------------

            new_documents += 1

            print("Status: NEW")

            filename = make_filename(
                title,
                url
            )

            try:

                filepath, pdf_status, document_hash = save_pdf(
                    url,
                    filename
                )

                print(f"PDF saved: {filepath}")
                print(f"PDF HTTP Status: {pdf_status}")

                save_document(
                    conn=conn,
                    source_id=source_id,
                    row=row,
                    title=title,
                    url=url,
                    pdf_filename=filename,
                    meeting_date=meeting_date,
                    document_hash=document_hash,
                    status="NEW",
                    http_status=pdf_status
                )

            except Exception as pdf_error:

                print(
                    f"PDF download failed: {pdf_error}"
                )

                save_document(
                    conn=conn,
                    source_id=source_id,
                    row=row,
                    title=title,
                    url=url,
                    pdf_filename="",
                    meeting_date=meeting_date,
                    document_hash="",
                    status="DOWNLOAD_FAILED",
                    http_status=0
                )

        # ------------------------------------------------------------
        # CRAWL HISTORY
        # ------------------------------------------------------------

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO crawl_history (
                health_authority,
                source_name,
                crawl_time,
                crawl_status,
                documents_found,
                new_documents,
                existing_documents,
                section_found,
                links_found,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                health_authority,
                source_name,
                now(),
                "SUCCESS",
                documents_found,
                new_documents,
                existing_documents,
                1 if section_nodes else 0,
                len(links),
                ""
            )
        )

        cursor.execute(
            """
            UPDATE sources
            SET
                last_crawled = ?,
                last_status = ?,
                last_error = ?
            WHERE id = ?
            """,
            (
                now(),
                "SUCCESS",
                "",
                source_id
            )
        )

        conn.commit()

        print()
        print("-" * 70)
        print("CRAWL SUMMARY")
        print("-" * 70)
        print(f"Sections found      : {len(section_nodes)}")
        print(f"Links found         : {len(links)}")
        print(f"PDF documents found : {documents_found}")
        print(f"New documents       : {new_documents}")
        print(f"Existing documents  : {existing_documents}")

        return True

    except Exception as error:

        print()
        print(f"CRAWL ERROR: {error}")

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO crawl_history (
                health_authority,
                source_name,
                crawl_time,
                crawl_status,
                documents_found,
                new_documents,
                existing_documents,
                section_found,
                links_found,
                error_message
            )
            VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0, ?)
            """,
            (
                health_authority,
                source_name,
                now(),
                "FAILED",
                str(error)
            )
        )

        cursor.execute(
            """
            UPDATE sources
            SET
                last_crawled = ?,
                last_status = ?,
                last_error = ?
            WHERE id = ?
            """,
            (
                now(),
                "FAILED",
                str(error),
                source_id
            )
        )

        conn.commit()

        return False


def run_crawler():
    print()
    print("=" * 70)
    print("SAFETY TRIGGER CRAWLER")
    print("=" * 70)

    if not CONFIG_FILE.exists():
        print(f"ERROR: Excel configuration not found:")
        print(CONFIG_FILE)
        return

    try:
        sources = pd.read_excel(CONFIG_FILE)
    except Exception as error:
        print(f"ERROR reading Excel: {error}")
        return

    required_columns = [
        "Health Authority",
        "Source Name",
        "URL",
        "Active",
        "Section XPath",
        "Link XPath",
        "Frequency"
    ]

    missing = [
        column
        for column in required_columns
        if column not in sources.columns
    ]

    if missing:
        print()
        print("ERROR: Missing Excel columns:")
        for column in missing:
            print(f" - {column}")
        return

    conn = get_connection()

    total_sources = 0
    successful_sources = 0

    for _, row in sources.iterrows():

        active = clean_text(row["Active"]).lower()

        if active not in ["yes", "true", "1", "active"]:
            continue

        total_sources += 1

        if crawl_source(conn, row):
            successful_sources += 1

    conn.close()

    print()
    print("=" * 70)
    print("CRAWLER FINISHED")
    print("=" * 70)
    print(f"Active sources     : {total_sources}")
    print(f"Successful sources : {successful_sources}")
    print("=" * 70)


if __name__ == "__main__":
    run_crawler()