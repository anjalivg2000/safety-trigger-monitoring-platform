import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.main import (
    _record_discovered_documents,
    discover_crawl_documents,
)
from backend.models import CrawlDiscoverRequest


class ResultsPersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                authority TEXT,
                name TEXT,
                source_type TEXT,
                region TEXT,
                monitoring_frequency TEXT,
                website TEXT,
                safety_alert_type TEXT,
                url TEXT,
                content_types TEXT,
                instruction TEXT,
                active INTEGER,
                last_crawled_at TEXT,
                last_crawl_status TEXT,
                last_error_message TEXT,
                updated_at TEXT
            );
            CREATE TABLE documents (
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
                status TEXT NOT NULL DEFAULT 'NEW',
                created_at TEXT NOT NULL
            );
            INSERT INTO sources
                (id, reference_no, authority, name, url, content_types, active)
            VALUES (
                1,
                'EMA_PRAC_001',
                'EMA',
                'EMA PRAC',
                'https://example.test/prac',
                '["Meeting Minutes", "Agendas", "Highlights"]',
                1
            );
            """
        )

        @contextmanager
        def open_test_database():
            yield self.connection

        self.get_db_patch = patch(
            "backend.main.get_db",
            open_test_database,
        )
        self.get_db_patch.start()

    def tearDown(self):
        self.get_db_patch.stop()
        self.connection.close()

    def test_repeated_crawl_updates_existing_document_without_duplicate(self):
        source = {
            "id": 1,
            "reference_no": "EMA_PRAC_001",
        }
        first_document = {
            "title": "PRAC Meeting Minutes",
            "url": "https://example.test/minutes.pdf",
            "document_key": "https://example.test/minutes.pdf",
            "publication_date": "25-Sep-2026",
            "content_type": "Meeting Minutes",
        }

        new_count, _ = _record_discovered_documents(
            source,
            [first_document],
        )
        first_reference_id = first_document["reference_id"]
        self.assertEqual(new_count, 1)
        self.assertTrue(first_document["new_document"])
        self.assertEqual(
            first_reference_id,
            "EMA_PRAC_001_20260925_001",
        )

        repeated_document = {
            **first_document,
            "title": "PRAC Meeting Minutes - Updated link text",
            "publication_date": "04 September 2026",
            "status": "NEW",
            "new_document": True,
        }
        new_count, _ = _record_discovered_documents(
            source,
            [repeated_document],
        )

        row = self.connection.execute(
            "SELECT * FROM documents"
        ).fetchone()
        self.assertEqual(new_count, 0)
        self.assertFalse(repeated_document["new_document"])
        self.assertEqual(repeated_document["status"], "ALREADY_CRAWLED")
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()[0], 1)
        self.assertNotEqual(row["reference_id"], first_reference_id)
        self.assertEqual(
            row["reference_id"],
            "EMA_PRAC_001_20260904_001",
        )
        self.assertEqual(row["publication_date"], "04 September 2026")
        self.assertEqual(row["title"], "PRAC Meeting Minutes - Updated link text")

    def test_crawl_discovery_endpoint_persists_and_recognizes_duplicate(self):
        discovered = {
            "title": "PRAC Meeting Minutes",
            "url": "https://example.test/prac/minutes.pdf",
            "document_key": "https://example.test/prac/minutes.pdf",
            "filename": "minutes.pdf",
            "meeting_date": "8-11 June 2026",
            "publication_date": "25 September 2026",
            "content_type": "Meeting Minutes",
            "status": "NEW",
        }
        with patch(
            "backend.main.crawl_source",
            return_value={
                "success": True,
                "documents": [discovered.copy()],
                "documents_found": 1,
                "new_documents": 1,
            },
        ):
            first_result = discover_crawl_documents(
                CrawlDiscoverRequest(source_id=1),
            )
            self.assertEqual(first_result["new_documents"], 1)
            self.assertEqual(
                first_result["documents"][0]["status"],
                "NEW",
            )
            self.assertEqual(
                first_result["documents"][0]["reference_id"],
                "EMA_PRAC_001_20260925_001",
            )

            second_result = discover_crawl_documents(
                CrawlDiscoverRequest(source_id=1),
            )

        self.assertEqual(second_result["new_documents"], 0)
        self.assertEqual(
            second_result["documents"][0]["status"],
            "ALREADY_CRAWLED",
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
