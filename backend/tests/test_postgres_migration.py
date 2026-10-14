"""
test_postgres_migration.py -- Unit tests for PostgreSQL DDL, connection wrapper, and migration tooling.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import PostgresConnectionWrapper, PostgresCursorWrapper, is_postgres_active
from migrate_postgres import POSTGRES_DDL


class TestPostgresMigrationAndWrapper(unittest.TestCase):
    """Test suite for PostgreSQL migration and query wrapper."""

    def test_postgres_ddl_contains_all_core_tables_and_columns(self):
        """Verify POSTGRES_DDL contains all 8 tables and new authentication/profile columns."""
        required_tables = [
            "CREATE TABLE IF NOT EXISTS farmers",
            "CREATE TABLE IF NOT EXISTS markets",
            "CREATE TABLE IF NOT EXISTS price_history",
            "CREATE TABLE IF NOT EXISTS farmer_reports",
            "CREATE TABLE IF NOT EXISTS buyers",
            "CREATE TABLE IF NOT EXISTS buyer_requirements",
            "CREATE TABLE IF NOT EXISTS produce_submissions",
            "CREATE TABLE IF NOT EXISTS recommendations",
        ]
        for tbl in required_tables:
            self.assertIn(tbl, POSTGRES_DDL)

        # Ensure farmer auth and profile columns are present
        self.assertIn("password_hash", POSTGRES_DDL)
        self.assertIn("profile_pic", POSTGRES_DDL)
        self.assertIn("farm_size_acres", POSTGRES_DDL)
        self.assertIn("upi_id", POSTGRES_DDL)
        self.assertIn("bio", POSTGRES_DDL)

    def test_sql_placeholder_translation_in_wrapper(self):
        """Verify PostgresConnectionWrapper translates SQLite '?' into PostgreSQL '%s'."""
        mock_raw_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        wrapper = PostgresConnectionWrapper(mock_raw_conn)

        # Test SELECT with ? placeholders
        wrapper.execute("SELECT * FROM farmers WHERE mobile_number = ? AND location = ?", ("9876543210", "Pune"))

        # Check what SQL was passed to the real cursor
        called_args = mock_cursor.execute.call_args[0]
        called_sql = called_args[0]
        self.assertIn("%s", called_sql)
        self.assertNotIn("?", called_sql)
        self.assertEqual(called_args[1], ("9876543210", "Pune"))

    def test_insert_returning_id_injection(self):
        """Verify INSERT statements without RETURNING get 'RETURNING id' appended to emulate lastrowid."""
        mock_raw_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 42}
        mock_raw_conn.cursor.return_value = mock_cursor

        wrapper = PostgresConnectionWrapper(mock_raw_conn)

        cur = wrapper.execute(
            "INSERT INTO farmers (name, mobile_number, location) VALUES (?, ?, ?)",
            ("Test Farmer", "9800000000", "Nashik"),
        )

        called_args = mock_cursor.execute.call_args[0]
        called_sql = called_args[0]
        self.assertTrue(called_sql.strip().endswith("RETURNING id;"))
        self.assertEqual(cur.lastrowid, 42)

    def test_transaction_lifecycle_methods(self):
        """Verify commit, rollback, and close methods on wrapper delegate properly."""
        mock_raw_conn = MagicMock()
        wrapper = PostgresConnectionWrapper(mock_raw_conn)

        wrapper.commit()
        mock_raw_conn.commit.assert_called_once()

        wrapper.rollback()
        mock_raw_conn.rollback.assert_called_once()

        wrapper.close()
        mock_raw_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
