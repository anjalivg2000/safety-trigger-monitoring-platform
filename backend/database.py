"""
Safety Trigger Monitoring Platform
Database Layer

SQLite database used for:
- Health authority sources
- PRAC documents
- PDF pages
- Safety findings
- AI summaries
- Human reviews
- Crawl history
- Extraction history
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional


# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

DB_PATH = DATA_DIR / "safety_trigger.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection() -> sqlite3.Connection:
    """
    Create a SQLite connection.

    Row factory allows access like:
        row["title"]
    instead of:
        row[2]
    """

    connection = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Database context manager.

    Automatically commits successful operations
    and rolls back when an exception occurs.
    """

    connection = get_connection()

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db() -> None:
    """
    Create all required database tables.

    This function is safe to call every time the
    FastAPI application starts.
    """

    with get_db() as conn:

        # ----------------------------------------------------
        # HEALTH AUTHORITY SOURCES
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                reference_no TEXT,

                authority TEXT NOT NULL,

                name TEXT NOT NULL,

                source_type TEXT,

                region TEXT DEFAULT 'EEA',

                monitoring_frequency TEXT DEFAULT 'Monthly',

                website TEXT DEFAULT 'EMA',

                safety_alert_type TEXT DEFAULT 'PRAC',

                url TEXT NOT NULL UNIQUE,

                content_types TEXT DEFAULT '[]',

                instruction TEXT,

                active INTEGER NOT NULL DEFAULT 1,

                last_crawled_at TEXT,

                last_crawl_status TEXT,

                last_error_message TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT
            )
            """
        )

        source_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }

        for column_name, column_sql in {
            "reference_no": "TEXT",
            "region": "TEXT DEFAULT 'EEA'",
            "monitoring_frequency": "TEXT DEFAULT 'Monthly'",
            "website": "TEXT DEFAULT 'EMA'",
            "safety_alert_type": "TEXT DEFAULT 'PRAC'",
            "content_types": "TEXT DEFAULT '[]'",
            "instruction": "TEXT",
            "last_crawled_at": "TEXT",
            "last_crawl_status": "TEXT",
            "last_error_message": "TEXT",
            "updated_at": "TEXT",
        }.items():
            if column_name not in source_columns:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {column_name} {column_sql}")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                reference_no TEXT NOT NULL UNIQUE,

                class_name TEXT NOT NULL,

                active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                product_class_id INTEGER NOT NULL,

                reference_no TEXT NOT NULL UNIQUE,

                product_name TEXT NOT NULL,

                active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT,

                FOREIGN KEY(product_class_id)
                    REFERENCES product_classes(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ----------------------------------------------------
        # PRAC DOCUMENTS
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_id INTEGER NOT NULL,

                title TEXT,

                url TEXT NOT NULL UNIQUE,

                meeting_date TEXT,

                publication_date TEXT,

                filename TEXT,

                discovered_date TEXT,

                last_crawled_at TEXT,

                content_type TEXT,

                reference_id TEXT UNIQUE,

                sha256 TEXT,

                status TEXT NOT NULL DEFAULT 'NEW',

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(source_id)
                    REFERENCES sources(id)
                    ON DELETE CASCADE
            )
            """
        )

        document_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }

        for column_name, column_sql in {
            "last_crawled_at": "TEXT",
            "content_type": "TEXT",
            "reference_id": "TEXT",
        }.items():
            if column_name not in document_columns:
                conn.execute(
                    f"ALTER TABLE documents ADD COLUMN {column_name} {column_sql}"
                )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_documents_reference_id
            ON documents(reference_id)
            """
        )

        # ----------------------------------------------------
        # EXTRACTED PDF PAGES
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                document_id INTEGER NOT NULL,

                page_number INTEGER NOT NULL,

                page_text TEXT NOT NULL DEFAULT '',

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(document_id, page_number),

                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )


        # ----------------------------------------------------
        # SAFETY FINDINGS
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                document_id INTEGER NOT NULL,

                page_number INTEGER,

                product_name TEXT,

                active_substance TEXT,

                trigger_name TEXT,

                safety_topic TEXT,

                relevant_terms TEXT,

                evidence TEXT,

                section TEXT,

                comparison_status TEXT DEFAULT 'NEW_INFORMATION',

                evidence_hash TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )


        # ----------------------------------------------------
        # AI GENERATED SUMMARIES
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                finding_id INTEGER NOT NULL,

                product_name TEXT,

                active_substance TEXT,

                safety_topic TEXT,

                prac_assessment TEXT,

                outcome TEXT,

                summary TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(finding_id)
                    REFERENCES findings(id)
                    ON DELETE CASCADE
            )
            """
        )


        # ----------------------------------------------------
        # HUMAN REVIEWS
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                finding_id INTEGER NOT NULL,

                reviewer TEXT NOT NULL,

                decision TEXT NOT NULL,

                comments TEXT,

                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(finding_id)
                    REFERENCES findings(id)
                    ON DELETE CASCADE
            )
            """
        )


        # ----------------------------------------------------
        # CRAWL HISTORY
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source_id INTEGER,

                started_at TEXT,

                completed_at TEXT,

                status TEXT,

                documents_found INTEGER DEFAULT 0,

                error_message TEXT,

                FOREIGN KEY(source_id)
                    REFERENCES sources(id)
                    ON DELETE SET NULL
            )
            """
        )


        # ----------------------------------------------------
        # EXTRACTION HISTORY
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                document_id INTEGER,

                started_at TEXT,

                completed_at TEXT,

                status TEXT,

                pages_extracted INTEGER DEFAULT 0,

                error_message TEXT,

                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE SET NULL
            )
            """
        )


        # ----------------------------------------------------
        # INDEXES
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_documents_source
            ON documents(source_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_documents_status
            ON documents(status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_document_pages_document
            ON document_pages(document_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_findings_document
            ON findings(document_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_findings_comparison
            ON findings(comparison_status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_reviews_finding
            ON reviews(finding_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_crawl_history_source
            ON crawl_history(source_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_extraction_history_document
            ON extraction_history(document_id)
            """
        )


# ============================================================
# SOURCE HELPERS
# ============================================================

def get_source_by_url(url: str) -> Optional[sqlite3.Row]:
    """
    Return a source using its URL.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM sources
            WHERE url = ?
            LIMIT 1
            """,
            (url,),
        ).fetchone()


def get_source_by_id(source_id: int) -> Optional[sqlite3.Row]:
    """
    Return a source using its database ID.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM sources
            WHERE id = ?
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()


def create_source(
    authority: str,
    name: str,
    source_type: str,
    url: str,
    active: bool = True,
) -> int:
    """
    Create a health authority source.

    If the URL already exists, the existing ID is returned.
    """

    with get_db() as conn:

        existing = conn.execute(
            """
            SELECT id
            FROM sources
            WHERE url = ?
            LIMIT 1
            """,
            (url,),
        ).fetchone()

        if existing:

            return int(existing["id"])


        cursor = conn.execute(
            """
            INSERT INTO sources
            (
                authority,
                name,
                source_type,
                url,
                active
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                authority,
                name,
                source_type,
                url,
                1 if active else 0,
            ),
        )

        return int(cursor.lastrowid)


# ============================================================
# DOCUMENT HELPERS
# ============================================================

def get_document_by_url(url: str) -> Optional[sqlite3.Row]:
    """
    Find a document using its source URL.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM documents
            WHERE url = ?
            LIMIT 1
            """,
            (url,),
        ).fetchone()


def get_document_by_id(
    document_id: int,
) -> Optional[sqlite3.Row]:
    """
    Find a document by database ID.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM documents
            WHERE id = ?
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()


# ============================================================
# PAGE HELPERS
# ============================================================

def get_document_pages(
    document_id: int,
):
    """
    Return all extracted pages for a document.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM document_pages
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()


# ============================================================
# FINDING HELPERS
# ============================================================

def get_findings_for_document(
    document_id: int,
):
    """
    Return findings belonging to a document.
    """

    with get_db() as conn:

        return conn.execute(
            """
            SELECT *
            FROM findings
            WHERE document_id = ?
            ORDER BY page_number, id
            """,
            (document_id,),
        ).fetchall()


# ============================================================
# DATABASE HEALTH CHECK
# ============================================================

def database_health() -> bool:
    """
    Check whether SQLite is accessible.
    """

    try:

        with get_db() as conn:

            conn.execute(
                "SELECT 1"
            ).fetchone()

        return True

    except Exception:

        return False


# ============================================================
# INITIALIZE DATABASE WHEN MODULE IS USED DIRECTLY
# ============================================================

if __name__ == "__main__":

    init_db()

    print(
        "Database initialized successfully."
    )

    print(
        f"Database path: {DB_PATH}"
    )