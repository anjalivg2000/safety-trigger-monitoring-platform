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


def calculate_text_hash(text):
    return hashlib.sha256(
        text.encode("utf-8", errors="ignore")
    ).hexdigest()


def extract_pdf(pdf_path):
    """
    Extract text page-by-page and block-by-block
    from a PDF using PyMuPDF.
    """

    document = pymupdf.open(pdf_path)

    pages = []
    total_blocks = 0

    for page_number, page in enumerate(document, start=1):

        text = page.get_text("text")

        blocks = page.get_text("blocks")

        page_blocks = []

        for block in blocks:

            if len(block) >= 5:

                block_text = str(block[4]).strip()

                if block_text:
                    page_blocks.append(block_text)

        total_blocks += len(page_blocks)

        pages.append(
            {
                "page_number": page_number,
                "text": text.strip(),
                "blocks": page_blocks,
            }
        )

    document.close()

    return pages, total_blocks


def update_document(
    conn,
    pdf_filename,
    pages,
    total_blocks,
    extraction_status="SUCCESS"
):
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE documents
        SET
            pages_extracted = ?,
            blocks_extracted = ?,
            extraction_status = ?
        WHERE pdf_filename = ?
        """,
        (
            len(pages),
            total_blocks,
            extraction_status,
            pdf_filename
        )
    )

    conn.commit()


def save_extraction_history(
    conn,
    pdf_filename,
    status,
    pages,
    blocks,
    error_message=""
):
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO extraction_history (
            pdf_filename,
            extraction_time,
            status,
            pages,
            blocks,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            pdf_filename,
            now(),
            status,
            pages,
            blocks,
            error_message
        )
    )

    conn.commit()


def extract_all_pdfs():
    print()
    print("=" * 70)
    print("PDF EXTRACTION")
    print("=" * 70)

    if not PDF_DIR.exists():
        print("PDF directory does not exist:")
        print(PDF_DIR)
        return

    pdf_files = list(PDF_DIR.glob("*.pdf"))

    print(f"PDF directory : {PDF_DIR}")
    print(f"PDF files     : {len(pdf_files)}")

    if not pdf_files:
        print()
        print("No PDF files found.")
        print("Run the crawler first.")
        return

    conn = get_connection()

    successful = 0
    failed = 0

    for pdf_path in pdf_files:

        print()
        print("-" * 70)
        print(f"FILE: {pdf_path.name}")
        print("-" * 70)

        try:

            pages, total_blocks = extract_pdf(pdf_path)

            total_characters = sum(
                len(page["text"])
                for page in pages
            )

            print(f"Pages extracted      : {len(pages)}")
            print(f"Blocks extracted     : {total_blocks}")
            print(f"Characters extracted : {total_characters}")

            update_document(
                conn,
                pdf_path.name,
                pages,
                total_blocks,
                "SUCCESS"
            )

            save_extraction_history(
                conn,
                pdf_path.name,
                "SUCCESS",
                len(pages),
                total_blocks
            )

            successful += 1

        except Exception as error:

            print(f"Extraction failed: {error}")

            update_document(
                conn,
                pdf_path.name,
                [],
                0,
                "FAILED"
)

            save_extraction_history(
                conn,
                pdf_path.name,
                "FAILED",
                0,
                0,
                str(error)
            )

            failed += 1

    conn.close()

    print()
    print("=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)
    print(f"Total PDFs : {len(pdf_files)}")
    print(f"Successful : {successful}")
    print(f"Failed     : {failed}")
    print("=" * 70)


if __name__ == "__main__":
    extract_all_pdfs()