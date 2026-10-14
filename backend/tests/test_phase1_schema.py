"""
test_phase1_schema.py -- Unit tests for Phase 1 expanded database schema,
multi-crop seeds, and foreign key constraints.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import create_tables, get_connection
from recommender import get_recommendations


class TestPhase1SchemaAndMultiCrop(unittest.TestCase):
    """Test suite for Phase 1 data architecture."""

    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_all_eight_tables_exist(self):
        """Verify all 8 core tables specified in TRD.md §2 exist in sqlite_master."""
        expected_tables = {
            "farmers",
            "markets",
            "price_history",
            "farmer_reports",
            "buyers",
            "buyer_requirements",
            "produce_submissions",
            "recommendations",
        }
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        actual_tables = {row["name"] for row in cursor.fetchall()}
        for table in expected_tables:
            self.assertIn(table, actual_tables, f"Missing table: {table}")

    def test_multi_crop_price_history_counts(self):
        """Verify that price_history contains records for all 5 crops."""
        crops = ["Tomato", "Onion", "Potato", "Soybean", "Wheat"]
        for crop in crops:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM price_history WHERE crop = ?", (crop,)
            ).fetchone()[0]
            self.assertGreaterEqual(count, 5, f"Expected price history rows for {crop}, found {count}")

    def test_recommendations_for_onion(self):
        """Test recommendation pipeline for Onion produces ranked results with net return."""
        recs = get_recommendations(
            crop="Onion",
            quantity_kg=1000.0,
            farmer_lat=18.5204,
            farmer_lng=73.8567,
            farmer_location="Pune",
            vehicle_type="mini_truck",
            conn=self.conn,
        )
        self.assertEqual(len(recs), 5)
        # Verify rank 1 has highest net return
        self.assertGreater(recs[0]["expected_net_return"], recs[-1]["expected_net_return"])
        # Verify net return formula matches TRD.md §4.2
        for r in recs:
            expected_net = round(r["expected_revenue"] - r["transport_cost"] - r["other_costs"], 2)
            self.assertAlmostEqual(r["expected_net_return"], expected_net, places=1)

    def test_recommendations_for_soybean(self):
        """Test recommendation pipeline for Soybean in Nagpur."""
        recs = get_recommendations(
            crop="Soybean",
            quantity_kg=2000.0,
            farmer_lat=21.1458,
            farmer_lng=79.0882,
            farmer_location="Nagpur",
            vehicle_type="large_truck",
            conn=self.conn,
        )
        self.assertEqual(len(recs), 5)
        self.assertEqual(recs[0]["rank"], 1)
        self.assertGreater(recs[0]["predicted_price"], 40.0)

    def test_buyer_requirements_linked_to_buyers(self):
        """Verify that seeded buyer requirements join correctly to verified buyers."""
        rows = self.conn.execute(
            """
            SELECT br.crop, br.quantity_kg, br.offered_price, b.name, b.verified
            FROM buyer_requirements br
            JOIN buyers b ON br.buyer_id = b.id
            """
        ).fetchall()
        self.assertGreaterEqual(len(rows), 5)
        for r in rows:
            self.assertTrue(bool(r["verified"]))
            self.assertGreater(r["quantity_kg"], 0)
            self.assertGreater(r["offered_price"], 0)

    def test_farmer_reports_confidence_scoring(self):
        """Verify that farmer reports carry confidence scores per ADR-003."""
        rows = self.conn.execute(
            "SELECT reported_price, confidence_score, validated FROM farmer_reports"
        ).fetchall()
        self.assertGreaterEqual(len(rows), 1)
        for r in rows:
            self.assertGreater(r["confidence_score"], 0.0)
            self.assertLessEqual(r["confidence_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
