"""
test_phase5_ingestion_and_alerts.py -- Unit tests for Phase 5 Data Ingestion Pipeline
and Smart Opportunity Alerts Engine.
"""

import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts import SmartAlertService
from db import get_connection
from ingestion import DataIngestionService
from main import get_smart_alerts, sync_agmarknet_prices


class TestPhase5IngestionAndAlerts(unittest.TestCase):
    """Test suite for Phase 5 ingestion and alerts."""

    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_daily_data_ingestion_service(self):
        """Test that DataIngestionService syncs market prices with Agmarknet provenance."""
        res = DataIngestionService.sync_daily_prices(self.conn, target_date="2026-08-30")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["date"], "2026-08-30")
        self.assertGreater(res["records_synced"], 0)
        self.assertEqual(res["source"], "agmarknet_api")
        self.assertEqual(res["confidence_score"], 0.95)

        # Verify rows in database
        count = self.conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE date = '2026-08-30' AND source = 'agmarknet_api'"
        ).fetchone()[0]
        self.assertEqual(count, res["records_synced"])

    def test_smart_alerts_generation(self):
        """Test that SmartAlertService generates actionable alerts."""
        alerts = SmartAlertService.get_alerts(self.conn)
        self.assertIsInstance(alerts, list)
        self.assertGreaterEqual(len(alerts), 1)

        first = alerts[0]
        self.assertIn("id", first)
        self.assertIn("type", first)
        self.assertIn("title", first)
        self.assertIn("message", first)
        self.assertIn("severity", first)
        self.assertIn(first["severity"], ["success", "info", "warning"])

        # Filter by crop
        tomato_alerts = SmartAlertService.get_alerts(self.conn, crop="Tomato")
        for a in tomato_alerts:
            self.assertEqual(a["crop"], "Tomato")

    def test_api_endpoints_wired(self):
        """Test FastAPI endpoints for sync-prices and alerts."""
        sync_res = sync_agmarknet_prices(date="2026-08-31")
        self.assertEqual(sync_res["status"], "success")

        alerts_res = get_smart_alerts(crop="Onion")
        self.assertIsInstance(alerts_res, list)

    def test_data_gov_status_endpoint(self):
        """Test GET /admin/data-gov-status endpoint."""
        from main import get_data_gov_status
        status = get_data_gov_status()
        self.assertEqual(status["status"], "ready")
        self.assertIn("api_key_configured", status)
        self.assertIn("resource_id", status)
        self.assertEqual(status["resource_id"], "9ef84268-d588-465a-a308-a864a43d0070")


if __name__ == "__main__":
    unittest.main()
