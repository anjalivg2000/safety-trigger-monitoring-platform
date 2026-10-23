import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import sqlite3
from datetime import datetime

import pymupdf

from database.db import initialize_database


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "output" / "safety_trigger.db"
PDF_DIR = BASE_DIR / "output" / "pdfs"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection():
    initialize_database()
    return sqlite3.connect(DB_FILE)


def normalize(text):
    return " ".join(text.lower().split())


def text_hash(text):
    return hashlib.sha256(
        normalize(text).encode("utf-8", errors="ignore")
    ).hexdigest()


def extract_pdf_text(pdf_path):
    pdf = pymupdf.open(pdf_path)

    pages = []

    for page_number, page in enumerate(pdf, start=1):
        text = page.get_text("text").strip()

        if text:
            pages.append(
                {
                    "page_number": page_number,
                    "text": text
                }
            )

    pdf.close()

    return pages


def get_document_id(conn, pdf_filename):

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM documents
        WHERE pdf_filename = ?
        """,
        (pdf_filename,)
    )

    row = cursor.fetchone()

    return row[0] if row else None


def get_previous_document(conn, document_id):

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, pdf_filename, meeting_date
        FROM documents
        WHERE id < ?
        AND pdf_filename IS NOT NULL
        AND pdf_filename != ''
        ORDER BY id DESC
        LIMIT 1
        """,
        (document_id,)
    )

    return cursor.fetchone()


def save_comparison_status(
    conn,
    document_id,
    status
):

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE safety_findings
        SET comparison_status = ?
        WHERE document_id = ?
        """,
        (
            status,
            document_id
        )
    )

    conn.commit()


def compare_documents(
    current_pdf,
    previous_pdf
):

    current_pages = extract_pdf_text(
        current_pdf
    )

    previous_pages = extract_pdf_text(
        previous_pdf
    )

    previous_text = "\n".join(
        page["text"]
        for page in previous_pages
    )

    previous_normalized = normalize(
        previous_text
    )

    new_pages = []

    for page in current_pages:

        current_text = normalize(
            page["text"]
        )

        if not current_text:
            continue

        # Page-level comparison.
        # If the complete normalized page is not present
        # in the previous document, flag it as new.

        if current_text not in previous_normalized:

            new_pages.append(
                {
                    "page_number": page["page_number"],
                    "text": page["text"]
                }
            )

    return new_pages


def run_comparison():

    print()
    print("=" * 70)
    print("DOCUMENT COMPARISON")
    print("=" * 70)

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, pdf_filename
        FROM documents
        WHERE pdf_filename IS NOT NULL
        AND pdf_filename != ''
        ORDER BY id
        """
    )

    documents = cursor.fetchall()

    print(
        f"Documents available: {len(documents)}"
    )

    if len(documents) < 2:

        print(
            "At least two documents are required "
            "for comparison."
        )

        conn.close()

        return

    total_new_pages = 0

    for document_id, pdf_filename in documents:

        current_pdf = PDF_DIR / pdf_filename

        if not current_pdf.exists():
            continue

        previous = get_previous_document(
            conn,
            document_id
        )

        if not previous:
            print()
            print(
                f"{pdf_filename}: BASELINE DOCUMENT"
            )

            continue

        previous_id = previous[0]
        previous_filename = previous[1]

        previous_pdf = PDF_DIR / previous_filename

        if not previous_pdf.exists():
            continue

        print()
        print("-" * 70)
        print(
            f"CURRENT : {pdf_filename}"
        )
        print(
            f"PREVIOUS: {previous_filename}"
        )
        print("-" * 70)

        new_pages = compare_documents(
            current_pdf,
            previous_pdf
        )

        if new_pages:

            status = "NEW_INFORMATION"

            print(
                f"New information pages: "
                f"{len(new_pages)}"
            )

            for page in new_pages:

                print(
                    f"  Page {page['page_number']}"
                )

            total_new_pages += len(
                new_pages
            )

        else:

            status = "NO_NEW_INFORMATION"

            print(
                "No new page-level information detected."
            )

        # Apply status to findings belonging
        # to the current document.

        save_comparison_status(
            conn,
            document_id,
            status
        )

    conn.close()

    print()
    print("=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(
        f"New information pages: {total_new_pages}"
    )
    print("=" * 70)


if __name__ == "__main__":
    run_comparison()