import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.main import dashboard


class DashboardAggregationTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                reference_no TEXT,
                name TEXT,
                active INTEGER,
                monitoring_frequency TEXT,
                content_types TEXT,
                last_crawl_status TEXT,
                last_error_message TEXT
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                source_id INTEGER,
                status TEXT,
                last_crawled_at TEXT,
                created_at TEXT,
                discovered_date TEXT,
                content_type TEXT,
                title TEXT,
                publication_date TEXT,
                url TEXT
            );
            CREATE TABLE findings (
                id INTEGER PRIMARY KEY,
                product_name TEXT,
                active_substance TEXT,
                comparison_status TEXT
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
            CREATE TABLE reviews (
                id INTEGER PRIMARY KEY,
                finding_id INTEGER,
                stage TEXT,
                decision TEXT
            );
            CREATE TABLE summaries (id INTEGER PRIMARY KEY);

            INSERT INTO sources VALUES
                (1, 'EMA_PRAC_001', 'EMA PRAC', 1, 'Monthly',
                 '["Meeting Minutes", "Agendas", "Highlights"]', 'success', NULL),
                (2, 'EMA_SIGNAL_001', 'EMA Signals', 0, 'Weekly',
                 '["Signals"]', 'failed', 'Crawl failed');

            INSERT INTO documents VALUES
                (1, 1, 'PROCESSED', '2026-10-01T00:00:00', '2026-10-01T00:00:00',
                 '2026-10-01T00:00:00', 'Meeting Minutes', 'Meeting minutes one',
                 '2026-09-30', 'https://example.test/document/1'),
                (2, 1, 'FAILED', '2026-10-01T00:00:00', '2026-10-01T00:00:00',
                 '2026-10-01T00:00:00', 'Agendas', 'Agenda two',
                 '2026-09-29', 'https://example.test/document/2'),
                (3, 2, 'NEW', NULL, '2026-10-01T00:00:00',
                 '2026-10-01T00:00:00', 'Signals', 'Signal three',
                 '2026-09-28', 'https://example.test/document/3');

            INSERT INTO findings VALUES
                (1, 'Alprazolam', NULL, 'NEW_INFORMATION'),
                (2, 'alprazolam', NULL, 'EXISTING'),
                (3, NULL, 'Diazepam', 'NEW'),
                (4, NULL, 'Diazepam', 'NEW');

            INSERT INTO reviews VALUES
                (1, 1, 'INITIAL', 'APPROVED'),
                (2, 1, 'FINAL', 'APPROVED'),
                (3, 2, 'INITIAL', 'APPROVED'),
                (4, 2, 'FINAL', 'REJECTED'),
                (5, 3, 'INITIAL', 'APPROVED');

            INSERT INTO crawl_history VALUES
                (1, 1, '2026-10-01T00:00:00', '2026-10-01T00:01:00',
                 'success', 2, 1, 2, NULL),
                (2, 2, '2026-10-01T00:02:00', '2026-10-01T00:03:00',
                 'failed', 0, 0, 1, 'Crawl failed');
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

    def test_dashboard_returns_database_aggregates_and_recent_crawls(self):
        data = dashboard()

        self.assertEqual(data["total_sources"], 2)
        self.assertEqual(data["active_sources"], 1)
        self.assertEqual(data["total_documents"], 3)
        self.assertEqual(data["new_documents"], 1)
        self.assertEqual(data["document_summary"]["documents_crawled"], 2)
        self.assertEqual(data["crawl_executions"], 2)
        self.assertEqual(data["safety_triggers"], 4)
        self.assertEqual(data["unique_products"], 2)
        self.assertEqual(data["pending_initial_reviews"], 1)
        self.assertEqual(data["pending_final_reviews"], 1)
        self.assertIsNone(data["approved_reviews"])
        self.assertIsNone(data["rejected_reviews"])
        self.assertIn("relevance decisions", data["review_outcomes_note"])
        self.assertEqual(data["document_summary"]["working_documents"], 1)
        self.assertEqual(data["document_summary"]["non_working_documents"], 1)
        self.assertEqual(data["content_type_summary"]["Meeting Minutes"], 1)
        self.assertEqual(data["content_type_summary"]["Agendas"], 1)
        self.assertEqual(data["content_type_summary"]["other_configured"][0]["content_type"], "Signals")
        self.assertEqual(data["source_status_summary"]["sources_with_errors"], 1)
        self.assertFalse(data["system_status"]["operational"])
        self.assertEqual(data["recent_crawl_activity"][0]["source_id"], "EMA_SIGNAL_001")
        self.assertEqual(data["recent_crawl_activity"][0]["status"], "failed")
        self.assertIsNone(data["recent_crawls"][0]["next_scheduled_run"])
        self.assertEqual(data["monitoring_status"][0]["monitoring_frequency"], "Monthly")
        self.assertTrue(data["monitoring_status"][0]["active"])
        self.assertEqual(data["recent_documents"][0]["title"], "Signal three")
        self.assertEqual(data["recent_documents"][0]["publication_date"], "2026-09-28")

    def test_dashboard_returns_zero_counts_and_empty_activity(self):
        self.connection.execute("DELETE FROM crawl_history")
        self.connection.execute("DELETE FROM findings")
        self.connection.execute("DELETE FROM documents")
        self.connection.execute("DELETE FROM sources")

        data = dashboard()

        self.assertEqual(data["total_sources"], 0)
        self.assertEqual(data["total_documents"], 0)
        self.assertEqual(data["crawl_executions"], 0)
        self.assertEqual(data["recent_crawl_activity"], [])
        self.assertTrue(data["system_status"]["operational"])


if __name__ == "__main__":
    unittest.main()
