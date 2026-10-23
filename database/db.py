import sqlite3
from pathlib import Path


DB_FILE = Path("output/safety_trigger.db")


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_FILE)


def add_column_if_missing(cursor, table, column, definition):
    columns = [
        row[1]
        for row in cursor.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
        print(f"Added: {table}.{column}")


def initialize_database():

    conn = get_connection()
    cursor = conn.cursor()

    # SOURCES
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            health_authority TEXT,
            source_name TEXT,
            url TEXT UNIQUE,
            active TEXT,
            section_xpath TEXT,
            link_xpath TEXT,
            frequency TEXT,
            last_crawled TEXT,
            last_status TEXT,
            last_error TEXT
        )
    """)

    # DOCUMENTS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            health_authority TEXT,
            source_name TEXT,
            title TEXT,
            url TEXT UNIQUE,
            pdf_filename TEXT,
            meeting_date TEXT,
            publication_date TEXT,
            document_hash TEXT,
            status TEXT DEFAULT 'NEW',
            http_status INTEGER,
            discovered_at TEXT,
            first_seen TEXT,
            last_checked TEXT,
            pages_extracted INTEGER DEFAULT 0,
            blocks_extracted INTEGER DEFAULT 0,
            extraction_status TEXT DEFAULT 'PENDING'
        )
    """)

    # SAFETY FINDINGS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS safety_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            health_authority TEXT,
            source_name TEXT,
            pdf_filename TEXT,
            page_number INTEGER,
            trigger_name TEXT,
            matched_substances TEXT,
            relevant_terms TEXT,
            evidence TEXT,
            context_before TEXT,
            context_after TEXT,
            evidence_hash TEXT UNIQUE,
            comparison_status TEXT DEFAULT 'NEW',
            finding_status TEXT DEFAULT 'NEW',
            reviewer_decision TEXT,
            reviewer_comment TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            detected_at TEXT
        )
    """)

    # CRAWL HISTORY
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            health_authority TEXT,
            source_name TEXT,
            crawl_time TEXT,
            crawl_status TEXT,
            documents_found INTEGER DEFAULT 0,
            new_documents INTEGER DEFAULT 0,
            existing_documents INTEGER DEFAULT 0,
            section_found INTEGER DEFAULT 0,
            links_found INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)

    # EXTRACTION HISTORY
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS extraction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_filename TEXT,
            extraction_time TEXT,
            status TEXT,
            pages INTEGER DEFAULT 0,
            blocks INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)

    # ============================================================
    # MIGRATE OLD DATABASE
    # ============================================================

    documents_columns = [
        ("source_id", "INTEGER"),
        ("health_authority", "TEXT"),
        ("source_name", "TEXT"),
        ("title", "TEXT"),
        ("url", "TEXT"),
        ("pdf_filename", "TEXT"),
        ("meeting_date", "TEXT"),
        ("publication_date", "TEXT"),
        ("document_hash", "TEXT"),
        ("status", "TEXT DEFAULT 'NEW'"),
        ("http_status", "INTEGER"),
        ("discovered_at", "TEXT"),
        ("first_seen", "TEXT"),
        ("last_checked", "TEXT"),
        ("pages_extracted", "INTEGER DEFAULT 0"),
        ("blocks_extracted", "INTEGER DEFAULT 0"),
        ("extraction_status", "TEXT DEFAULT 'PENDING'")
    ]

    for column, definition in documents_columns:
        add_column_if_missing(
            cursor,
            "documents",
            column,
            definition
        )

    sources_columns = [
        ("health_authority", "TEXT"),
        ("source_name", "TEXT"),
        ("url", "TEXT"),
        ("active", "TEXT"),
        ("section_xpath", "TEXT"),
        ("link_xpath", "TEXT"),
        ("frequency", "TEXT"),
        ("last_crawled", "TEXT"),
        ("last_status", "TEXT"),
        ("last_error", "TEXT")
    ]

    for column, definition in sources_columns:
        add_column_if_missing(
            cursor,
            "sources",
            column,
            definition
        )

    findings_columns = [
        ("document_id", "INTEGER"),
        ("health_authority", "TEXT"),
        ("source_name", "TEXT"),
        ("pdf_filename", "TEXT"),
        ("page_number", "INTEGER"),
        ("trigger_name", "TEXT"),
        ("matched_substances", "TEXT"),
        ("relevant_terms", "TEXT"),
        ("evidence", "TEXT"),
        ("context_before", "TEXT"),
        ("context_after", "TEXT"),
        ("evidence_hash", "TEXT"),
        ("comparison_status", "TEXT DEFAULT 'NEW'"),
        ("finding_status", "TEXT DEFAULT 'NEW'"),
        ("reviewer_decision", "TEXT"),
        ("reviewer_comment", "TEXT"),
        ("reviewed_by", "TEXT"),
        ("reviewed_at", "TEXT"),
        ("detected_at", "TEXT")
    ]

    for column, definition in findings_columns:
        add_column_if_missing(
            cursor,
            "safety_findings",
            column,
            definition
        )

    crawl_columns = [
        ("health_authority", "TEXT"),
        ("source_name", "TEXT"),
        ("crawl_time", "TEXT"),
        ("crawl_status", "TEXT"),
        ("documents_found", "INTEGER DEFAULT 0"),
        ("new_documents", "INTEGER DEFAULT 0"),
        ("existing_documents", "INTEGER DEFAULT 0"),
        ("section_found", "INTEGER DEFAULT 0"),
        ("links_found", "INTEGER DEFAULT 0"),
        ("error_message", "TEXT")
    ]

    for column, definition in crawl_columns:
        add_column_if_missing(
            cursor,
            "crawl_history",
            column,
            definition
        )

    extraction_columns = [
        ("pdf_filename", "TEXT"),
        ("extraction_time", "TEXT"),
        ("status", "TEXT"),
        ("pages", "INTEGER DEFAULT 0"),
        ("blocks", "INTEGER DEFAULT 0"),
        ("error_message", "TEXT")
    ]

    for column, definition in extraction_columns:
        add_column_if_missing(
            cursor,
            "extraction_history",
            column,
            definition
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":

    initialize_database()

    print()
    print("=" * 60)
    print("SAFETY TRIGGER DATABASE")
    print("=" * 60)
    print("Database upgrade/initialization successful.")
    print(f"Location: {DB_FILE}")