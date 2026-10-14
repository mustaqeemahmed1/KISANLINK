"""
test_logistics_and_deal_sheet.py -- Unit and integration tests for Smart Logistics Matching
and Downloadable Deal Sheet Certificate generation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from deal_sheet import generate_deal_sheet_html
from logistics import REGISTERED_PROVIDERS, SmartLogisticsService
from main import (
    DealSheetPreviewRequest,
    LogisticsMatchRequest,
    get_logistics_providers,
    get_produce_deal_sheet,
    match_logistics,
    preview_deal_sheet,
)


class TestSmartLogistics(unittest.TestCase):
    """Test smart carrier discovery and freight matching per ARCHITECTURE.md §7."""

    def test_registered_providers_exist(self):
        """Verify registered carriers have verified details, payloads, and ratings."""
        providers = SmartLogisticsService.get_providers()
        self.assertGreaterEqual(len(providers), 5)
        for p in providers:
            self.assertIn("name", p)
            self.assertIn("operator_name", p)
            self.assertIn("contact", p)
            self.assertGreater(p["max_payload_kg"], 0)
            self.assertGreater(p["rating"], 4.0)
            self.assertTrue(p["verified"])

    def test_filter_providers_by_hub(self):
        """Test filtering carriers by regional hub."""
        pune_carriers = SmartLogisticsService.get_providers(hub="Pune")
        self.assertGreaterEqual(len(pune_carriers), 1)
        for p in pune_carriers:
            self.assertEqual(p["base_hub"].lower(), "pune")

    def test_match_logistics_payload_filtering(self):
        """Carriers with insufficient payload capacity must be excluded."""
        # For a massive 10,000 kg cargo, mini-trucks (1.5 - 1.8 ton) must be excluded
        heavy_quotes = SmartLogisticsService.match_logistics(
            farmer_location="Pune",
            destination_market="Nagpur Market C",
            distance_km=705.0,
            quantity_kg=10000.0,
        )
        self.assertGreater(len(heavy_quotes), 0)
        for q in heavy_quotes:
            # Must only match large trucks (e.g., BharatBenz 12 Ton)
            self.assertEqual(q.vehicle_type, "large_truck")

    def test_freight_quote_formula_trd_4_1(self):
        """Verify matched quote follows TRD.md §4.1 formula."""
        quotes = SmartLogisticsService.match_logistics(
            farmer_location="Pune",
            destination_market="Nashik APMC",
            distance_km=210.0,
            quantity_kg=500.0,
            vehicle_type="mini_truck",
        )
        self.assertGreater(len(quotes), 0)
        best = quotes[0]
        # Base fee 500 + (210 * 12) + (500 * 0.50) = 500 + 2520 + 250 = 3270.0
        self.assertEqual(best.freight_cost, 3270.0)
        self.assertGreater(best.estimated_transit_hours, 0.0)


class TestDealSheetGeneration(unittest.TestCase):
    """Test print-ready Deal Sheet generation and financial audit breakdown."""

    def setUp(self):
        self.mock_sub = {
            "id": 101,
            "crop": "Tomato",
            "quantity_kg": 500.0,
            "location": "Pune",
            "harvest_date": "2026-10-04",
            "quality_grade": "Grade A",
        }
        self.mock_rec = {
            "market_name": "Nashik APMC",
            "predicted_price": 28.50,
            "distance_km": 210.0,
            "transport_cost": 3270.0,
            "other_costs": 750.0,
            "expected_revenue": 14250.0,
            "expected_net_return": 10230.0,
            "confidence": 0.96,
            "trend": "rising",
            "demand_level": "High",
        }
        self.mock_farmer = {
            "name": "Ramesh Patil",
            "mobile_number": "9876543210",
            "location": "Pune",
        }

    def test_deal_sheet_html_structure(self):
        """Verify deal sheet HTML contains audit tables, official provenance, and print styles."""
        html = generate_deal_sheet_html(self.mock_sub, self.mock_rec, self.mock_farmer)
        self.assertIn("KisanLink AI", html)
        self.assertIn("Farmer Selling Deal Sheet", html)
        self.assertIn("Nashik APMC", html)
        self.assertIn("₹10,230.00", html)
        self.assertIn("Net-Return Financial Audit", html)
        self.assertIn("Government APMC data (Agmarknet", html)
        self.assertIn("window.print()", html)
        self.assertIn("@page", html)

    def test_deal_sheet_preview_endpoint(self):
        """Test POST /produce/deal-sheet/preview generates full HTML response."""
        req = DealSheetPreviewRequest(
            crop="Tomato",
            quantity_kg=500.0,
            farmer_name="Ramesh Patil",
            farmer_location="Pune",
            market_name="Nashik APMC",
            predicted_price=28.50,
            distance_km=210.0,
            transport_cost=3270.0,
            other_costs=750.0,
            expected_revenue=14250.0,
            expected_net_return=10230.0,
            confidence=0.96,
            trend="rising",
            demand_level="High",
        )
        resp = preview_deal_sheet(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.media_type, "text/html")
        body = resp.body.decode("utf-8")
        self.assertIn("Ramesh Patil", body)
        self.assertIn("₹10,230.00", body)

    def test_api_match_logistics_endpoint(self):
        """Test POST /logistics/match endpoint."""
        req = LogisticsMatchRequest(
            farmer_location="Pune",
            destination_market="Nashik APMC",
            distance_km=210.0,
            quantity_kg=500.0,
            vehicle_type="mini_truck",
        )
        quotes = match_logistics(req)
        self.assertIsInstance(quotes, list)
        self.assertGreater(len(quotes), 0)
        self.assertEqual(quotes[0]["freight_cost"], 3270.0)


if __name__ == "__main__":
    unittest.main()
