import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.database import init_db


class DatabaseMigrationTestCase(unittest.TestCase):
    def test_adds_relevant_terms_to_existing_findings_table(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE findings (
                        id INTEGER PRIMARY KEY,
                        document_id INTEGER NOT NULL,
                        comparison_status TEXT,
                        evidence TEXT
                    )
                    """
                )
            finally:
                connection.close()

            with patch("backend.database.DB_PATH", database_path):
                init_db()
                connection = sqlite3.connect(database_path)
                try:
                    columns = {
                        row[1]
                        for row in connection.execute(
                            "PRAGMA table_info(findings)"
                        ).fetchall()
                    }
                finally:
                    connection.close()

            self.assertIn("relevant_terms", columns)


if __name__ == "__main__":
    unittest.main()
