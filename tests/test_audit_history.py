import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.main import get_audit_history_page


class AuditHistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                name TEXT,
                authority TEXT,
                created_at TEXT
            );
            CREATE TABLE product_classes (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                class_name TEXT,
                created_at TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                product_class_id INTEGER,
                product_name TEXT,
                created_at TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                source_id INTEGER,
                reference_id TEXT,
                title TEXT,
                content_type TEXT
            );
            CREATE TABLE extraction_history (
                id INTEGER PRIMARY KEY,
                document_id INTEGER,
                started_at TEXT,
                completed_at TEXT,
                status TEXT,
                pages_extracted INTEGER,
                error_message TEXT
            );
            CREATE TABLE crawl_history (
                id INTEGER PRIMARY KEY,
                source_id INTEGER,
                started_at TEXT,
                completed_at TEXT,
                status TEXT,
                documents_found INTEGER,
                new_documents INTEGER,
                total_documents INTEGER,
                error_message TEXT
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY,
                created_at TEXT,
                event_type TEXT,
                details TEXT,
                entity_type TEXT,
                entity_id INTEGER,
                source_id INTEGER,
                reference_id TEXT,
                action TEXT,
                ai_model TEXT,
                result TEXT,
                status TEXT
            );
            CREATE TABLE document_ai_analyses (
                id INTEGER PRIMARY KEY,
                document_id INTEGER,
                provider TEXT,
                analysis_type TEXT,
                summary TEXT,
                status TEXT,
                error_message TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            INSERT INTO sources VALUES
                (1, 'EMA_PRAC_001', 'EMA PRAC', 'EMA', '2026-09-20T10:00:00');
            INSERT INTO documents VALUES
                (1, 1, 'EMA_PRAC_001_20260925_001', 'Meeting minutes', 'Meeting Minutes'),
                (2, 1, 'EMA_PRAC_001_20260926_001', 'Safety summary', 'Highlights');
            INSERT INTO extraction_history VALUES
                (1, 1, '2026-09-28T10:00:00', '2026-09-28T10:30:00', 'SUCCESS', 4, NULL);
            INSERT INTO crawl_history VALUES
                (1, 1, '2026-09-28T10:00:00', '2026-09-28T10:30:00', 'success', 2, 2, 12, NULL),
                (2, 1, '2026-09-29T10:00:00', '2026-09-29T10:30:00', 'success', 0, 0, 12, NULL);
            INSERT INTO audit_events VALUES
                (1, '2026-09-28T09:00:00', 'Source Updated', 'EMA_PRAC_001 – Frequency changed', 'source', 1, 1, 'EMA_PRAC_001', NULL, NULL, NULL, 'COMPLETED'),
                (2, '2026-09-28T11:00:00', 'AI Analysis (Summary)', 'Summary generated', 'document', 1, NULL, 'EMA_PRAC_001_20260925_001', 'AI Analysis (Summary)', 'ollama', 'Summary generated', 'COMPLETED');
            INSERT INTO document_ai_analyses VALUES
                (1, 2, 'ollama', 'summary', 'Stored summary', 'COMPLETED', NULL,
                 '2026-09-27T10:00:00', '2026-09-27T10:30:00');
            """
        )

        @contextmanager
        def open_test_database():
            yield self.connection

        self.get_db_patch = patch("backend.main.get_db", open_test_database)
        self.get_db_patch.start()

    def tearDown(self):
        self.get_db_patch.stop()
        self.connection.close()

    def get_page(self, section, **kwargs):
        return get_audit_history_page(
            section=section,
            page=kwargs.pop("page", 1),
            page_size=kwargs.pop("page_size", 4),
            date_from=kwargs.pop("date_from", None),
            date_to=kwargs.pop("date_to", None),
            source_id=kwargs.pop("source_id", None),
            type_filter=kwargs.pop("type_filter", None),
            search=kwargs.pop("search", None),
        )

    def test_returns_paginated_crawl_history_with_execution_counts(self):
        result = self.get_page("crawled", page_size=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["records"][0]["crawl_count"], 2)

    def test_filters_extraction_history_by_source_search_and_date(self):
        result = self.get_page(
            "extraction",
            source_id=1,
            search="Meeting minutes",
            date_from="2026-09-28",
            date_to="2026-09-28",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["records"][0]["reference_id"],
            "EMA_PRAC_001_20260925_001",
        )

    def test_returns_configuration_and_ai_action_events(self):
        config = self.get_page("configuration", search="Frequency")
        actions = self.get_page("actions", type_filter="AI Analysis (Summary)")

        self.assertEqual(config["records"][0]["type"], "Source Updated")
        self.assertEqual(actions["records"][0]["ai_model"], "ollama")
        self.assertEqual(actions["type_options"], ["AI Analysis (Summary)"])
        self.assertEqual(actions["total"], 2)

    def test_rejects_invalid_date_range(self):
        with self.assertRaises(Exception):
            self.get_page("crawled", date_from="not-a-date")


if __name__ == "__main__":
    unittest.main()
