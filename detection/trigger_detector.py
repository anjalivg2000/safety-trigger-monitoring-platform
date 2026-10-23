import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import json
import re
import sqlite3
from datetime import datetime

import pymupdf

from database.db import initialize_database


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "output" / "safety_trigger.db"
PDF_DIR = BASE_DIR / "output" / "pdfs"
TRIGGER_FILE = BASE_DIR / "config" / "triggers.json"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_triggers():
    with open(TRIGGER_FILE, "r", encoding="utf-8") as file:
        return json.load(file)["triggers"]


def get_connection():
    initialize_database()
    return sqlite3.connect(DB_FILE)


def normalize(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def create_hash(text):
    return hashlib.sha256(
        text.encode("utf-8", errors="ignore")
    ).hexdigest()


def find_matches(text, trigger):
    normalized = normalize(text)

    substances = [
        s.lower()
        for s in trigger.get("substances", [])
    ]

    terms = [
        t.lower()
        for t in trigger.get("relevance_terms", [])
    ]

    matched_substances = [
        s for s in substances
        if s in normalized
    ]

    matched_terms = [
        t for t in terms
        if t in normalized
    ]

    return matched_substances, matched_terms


def extract_context(text, start, end, context_size=500):
    before = text[
        max(0, start - context_size):start
    ]

    after = text[
        end:min(len(text), end + context_size)
    ]

    return before.strip(), after.strip()


def process_pdf(conn, pdf_filename, triggers):

    pdf_path = PDF_DIR / pdf_filename

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_filename}")
        return 0

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            health_authority,
            source_name
        FROM documents
        WHERE pdf_filename = ?
        """,
        (pdf_filename,)
    )

    document = cursor.fetchone()

    if not document:
        print(f"No database record for: {pdf_filename}")
        return 0

    document_id = document[0]
    health_authority = document[1] or ""
    source_name = document[2] or ""

    pdf = pymupdf.open(pdf_path)

    findings_count = 0

    for page_number, page in enumerate(pdf, start=1):

        text = page.get_text("text")

        if not text.strip():
            continue

        normalized_text = normalize(text)

        for trigger in triggers:

            if not trigger.get("active", True):
                continue

            trigger_name = trigger.get(
                "trigger_name",
                "Unknown"
            )

            matched_substances, matched_terms = find_matches(
                text,
                trigger
            )

            # A finding requires BOTH:
            # 1. A configured substance
            # 2. At least one relevant safety term

            if not matched_substances or not matched_terms:
                continue

            for substance in matched_substances:

                substance_pattern = re.escape(
                    substance
                )

                match = re.search(
                    substance_pattern,
                    normalized_text,
                    re.IGNORECASE
                )

                if not match:
                    continue

                start = match.start()
                end = match.end()

                before, after = extract_context(
                    text,
                    start,
                    end
                )

                evidence_start = max(
                    0,
                    start - 300
                )

                evidence_end = min(
                    len(text),
                    end + 500
                )

                evidence = text[
                    evidence_start:evidence_end
                ].strip()

                evidence_hash = create_hash(
                    f"{document_id}|"
                    f"{page_number}|"
                    f"{trigger_name}|"
                    f"{substance}|"
                    f"{evidence}"
                )

                cursor.execute(
                    """
                    SELECT id
                    FROM safety_findings
                    WHERE evidence_hash = ?
                    """,
                    (evidence_hash,)
                )

                if cursor.fetchone():
                    continue

                cursor.execute(
                    """
                    INSERT INTO safety_findings (
                        document_id,
                        health_authority,
                        source_name,
                        pdf_filename,
                        page_number,
                        trigger_name,
                        matched_substances,
                        relevant_terms,
                        evidence,
                        context_before,
                        context_after,
                        evidence_hash,
                        comparison_status,
                        finding_status,
                        detected_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        health_authority,
                        source_name,
                        pdf_filename,
                        page_number,
                        trigger_name,
                        ", ".join(matched_substances),
                        ", ".join(matched_terms),
                        evidence,
                        before,
                        after,
                        evidence_hash,
                        "NEW",
                        "NEW",
                        now()
                    )
                )

                findings_count += 1

    pdf.close()

    conn.commit()

    return findings_count


def run_detection():

    print()
    print("=" * 70)
    print("SAFETY TRIGGER DETECTION")
    print("=" * 70)

    triggers = load_triggers()

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT pdf_filename
        FROM documents
        WHERE pdf_filename IS NOT NULL
        AND pdf_filename != ''
        """
    )

    pdfs = [
        row[0]
        for row in cursor.fetchall()
    ]

    print(f"PDFs to analyse: {len(pdfs)}")
    print(
        f"Active triggers: "
        f"{sum(1 for t in triggers if t.get('active', True))}"
    )

    total_findings = 0

    for pdf_filename in pdfs:

        print()
        print("-" * 70)
        print(pdf_filename)
        print("-" * 70)

        findings = process_pdf(
            conn,
            pdf_filename,
            triggers
        )

        print(f"New findings: {findings}")

        total_findings += findings

    conn.close()

    print()
    print("=" * 70)
    print("DETECTION SUMMARY")
    print("=" * 70)
    print(f"Total new findings: {total_findings}")
    print("=" * 70)


if __name__ == "__main__":
    run_detection()