"""
test_phase2_apis.py -- Unit and integration tests for Phase 2 REST API endpoints.
Tests:
  - Farmer registration and login
  - Produce submission with recommendation persistence
  - Produce submission history
  - Market directory and detail views
  - Buyer requirements posting and filtering
  - Farmer crowdsourced price reporting and validation logic
  - Admin intelligence overview and regional balance analysis
"""

import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException

from db import get_connection
from main import (
    BuyerRequirementCreate,
    FarmerCreate,
    FarmerLoginRequest,
    FarmerProfileUpdateRequest,
    FarmerReportCreate,
    ProduceSubmissionRequest,
    create_or_login_farmer,
    get_admin_overview,
    get_admin_regional_intelligence,
    get_buyer_requirements,
    get_farmer_profile,
    get_farmer_reports,
    get_market_detail,
    get_markets,
    get_produce_history,
    login_farmer,
    post_buyer_requirement,
    post_farmer_report,
    post_produce_submission,
    register_farmer,
    update_farmer_profile,
)


class TestPhase2APIs(unittest.TestCase):
    """Test suite for Phase 2 REST API endpoints."""

    def test_farmer_registration_and_login(self):
        """Test that POST /farmers creates a new farmer or logs in existing."""
        req = FarmerCreate(
            name="Balasaheb Vikhe",
            mobile_number="9850999888",
            location="Nashik",
        )
        res = create_or_login_farmer(req)
        self.assertEqual(res.name, "Balasaheb Vikhe")
        self.assertEqual(res.mobile_number, "9850999888")
        self.assertEqual(res.location, "Nashik")
        self.assertIsNotNone(res.id)

        # Same mobile number -> acts as login/profile retrieval
        login_res = create_or_login_farmer(req)
        self.assertEqual(login_res.id, res.id)

        # Profile fetch
        profile = get_farmer_profile(res.id)
        self.assertEqual(profile.id, res.id)

    def test_farmer_auth_register_and_login(self):
        """Test dedicated POST /auth/register, password verification, and profile editing."""
        import uuid
        unique_phone = f"99{str(uuid.uuid4().int)[:8]}"

        # 1. Successful Registration with Password & Initial Profile
        reg_req = FarmerCreate(
            name="Kisan Dev",
            mobile_number=unique_phone,
            password="securePassword123",
            location="Pune",
            farm_size_acres=7.5,
            upi_id="kisandev@oksbi",
            profile_pic="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            bio="Farmer cultivating high-grade organic tomatoes.",
        )
        reg_res = register_farmer(reg_req)
        self.assertEqual(reg_res.farmer.name, "Kisan Dev")
        self.assertEqual(reg_res.farmer.mobile_number, unique_phone)
        self.assertEqual(reg_res.farmer.location, "Pune")
        self.assertEqual(reg_res.farmer.farm_size_acres, 7.5)
        self.assertEqual(reg_res.farmer.upi_id, "kisandev@oksbi")
        self.assertIn("successful", reg_res.message.lower())

        # 2. Duplicate Registration -> 409 Conflict
        with self.assertRaises(HTTPException) as ctx:
            register_farmer(reg_req)
        self.assertEqual(ctx.exception.status_code, 409)

        # 3. Successful Login with Correct Password
        login_req = FarmerLoginRequest(mobile_number=unique_phone, password="securePassword123")
        login_res = login_farmer(login_req)
        self.assertEqual(login_res.farmer.id, reg_res.farmer.id)
        self.assertEqual(login_res.farmer.mobile_number, unique_phone)
        self.assertEqual(login_res.farmer.farm_size_acres, 7.5)
        self.assertIn("welcome", login_res.message.lower())

        # 4. Failed Login with Wrong Password -> 401 Unauthorized
        wrong_login = FarmerLoginRequest(mobile_number=unique_phone, password="wrongPassword456")
        with self.assertRaises(HTTPException) as ctx_wrong:
            login_farmer(wrong_login)
        self.assertEqual(ctx_wrong.exception.status_code, 401)

        # 5. Unknown User Login -> 404 Not Found
        unknown_login = FarmerLoginRequest(mobile_number="9999999999", password="anyPassword")
        with self.assertRaises(HTTPException) as ctx:
            login_farmer(unknown_login)
        self.assertEqual(ctx.exception.status_code, 404)

        # 6. Profile Editing: PUT /farmers/{id}
        update_req = FarmerProfileUpdateRequest(
            name="Kisan Dev Patil",
            location="Nashik",
            farm_size_acres=10.0,
            upi_id="kisanpatil@okhdfc",
            bio="Leading onion & tomato grower in Khandesh region.",
            password="newPassword2026",
        )
        updated = update_farmer_profile(reg_res.farmer.id, update_req)
        self.assertEqual(updated.name, "Kisan Dev Patil")
        self.assertEqual(updated.location, "Nashik")
        self.assertEqual(updated.farm_size_acres, 10.0)
        self.assertEqual(updated.upi_id, "kisanpatil@okhdfc")

        # 7. Login with New Password
        new_login = FarmerLoginRequest(mobile_number=unique_phone, password="newPassword2026")
        new_login_res = login_farmer(new_login)
        self.assertEqual(new_login_res.farmer.name, "Kisan Dev Patil")

    def test_produce_submission_and_persistence(self):
        """Test POST /produce persists submission and computed recommendations."""
        req = ProduceSubmissionRequest(
            farmer_id=1,
            crop="Tomato",
            quantity_kg=600.0,
            location="Pune",
            quality_grade="Grade A",
            vehicle_type="mini_truck",
        )
        res = post_produce_submission(req)
        self.assertIsNotNone(res.submission_id)
        self.assertEqual(res.crop, "Tomato")
        self.assertEqual(len(res.recommendations), 5)
        # Top market has rank 1
        self.assertEqual(res.recommendations[0].rank, 1)

        # Verify persisted in database
        conn = get_connection()
        try:
            sub_count = conn.execute(
                "SELECT COUNT(*) FROM produce_submissions WHERE id = ?", (res.submission_id,)
            ).fetchone()[0]
            self.assertEqual(sub_count, 1)

            recs_count = conn.execute(
                "SELECT COUNT(*) FROM recommendations WHERE produce_submission_id = ?",
                (res.submission_id,),
            ).fetchone()[0]
            self.assertEqual(recs_count, 5)
        finally:
            conn.close()

    def test_produce_history(self):
        """Test GET /produce/history returns submissions with top recommendations."""
        history = get_produce_history(limit=5)
        self.assertGreaterEqual(len(history), 1)
        first = history[0]
        self.assertIn("crop", first)
        self.assertIn("best_market_name", first)
        self.assertIn("expected_net_return", first)

    def test_markets_list_and_detail(self):
        """Test GET /markets and GET /markets/{id}."""
        markets = get_markets(crop="Tomato")
        self.assertEqual(len(markets), 5)
        self.assertIn("name", markets[0])
        self.assertIn("latest_price", markets[0])

        # Market detail
        detail = get_market_detail(market_id=markets[0]["id"], crop="Tomato", farmer_location="Pune")
        self.assertEqual(detail["market_id"], markets[0]["id"])
        self.assertIn("distance_km", detail)
        self.assertIn("predicted_price", detail)
        self.assertIn("price_history", detail)

    def test_buyer_marketplace(self):
        """Test POST and GET /buyers/requirements."""
        # Query existing requirements
        initial = get_buyer_requirements(crop="Tomato")
        self.assertGreaterEqual(len(initial), 1)

        # Get a valid registered buyer id
        conn = get_connection()
        try:
            buyer_row = conn.execute("SELECT id FROM buyers LIMIT 1").fetchone()
            valid_buyer_id = buyer_row[0] if buyer_row else 1
        finally:
            conn.close()

        # Post new requirement
        new_req = BuyerRequirementCreate(
            buyer_id=valid_buyer_id,
            crop="Onion",
            quantity_kg=7500.0,
            offered_price=29.0,
            location="Nashik",
            pickup_available=True,
        )
        posted = post_buyer_requirement(new_req)
        self.assertEqual(posted.crop, "Onion")
        self.assertEqual(posted.quantity_kg, 7500.0)

        # Filter by crop
        filtered = get_buyer_requirements(crop="Onion")
        found = any(r.id == posted.id for r in filtered)
        self.assertTrue(found)

    def test_farmer_crowdsourced_report_validation(self):
        """Test POST /farmer-reports validates price against benchmark."""
        # 1. Normal price (within 20% of modal) -> validated = True, confidence = 0.85
        valid_report = FarmerReportCreate(
            farmer_id=1,
            crop="Tomato",
            market_id=2,  # Pune Market A (modal ~ 22)
            reported_price=22.0,
        )
        res_valid = post_farmer_report(valid_report)
        self.assertTrue(res_valid.validated)
        self.assertEqual(res_valid.confidence_score, 0.85)

        # 2. Outlier price (excessive spike, e.g. Rs. 95/kg) -> validated = False, confidence = 0.35
        outlier_report = FarmerReportCreate(
            farmer_id=1,
            crop="Tomato",
            market_id=2,
            reported_price=95.0,
        )
        res_outlier = post_farmer_report(outlier_report)
        self.assertFalse(res_outlier.validated)
        self.assertEqual(res_outlier.confidence_score, 0.35)
        self.assertIn("Outlier", res_outlier.message)

        # Retrieve recent reports
        reports = get_farmer_reports(crop="Tomato", limit=5)
        self.assertGreaterEqual(len(reports), 1)

    def test_admin_overview_and_regional(self):
        """Test GET /admin/overview and GET /admin/regional."""
        overview = get_admin_overview()
        self.assertGreater(overview["total_markets"], 0)
        self.assertGreater(overview["total_active_buyers"], 0)
        self.assertGreater(overview["total_buyer_demand_kg"], 0)
        self.assertEqual(len(overview["crops_summary"]), 5)

        regional = get_admin_regional_intelligence()
        self.assertEqual(len(regional["regional_intelligence"]), 5)
        for reg in regional["regional_intelligence"]:
            self.assertIn(reg["status"], ["HIGH DEMAND / SHORTAGE", "SURPLUS", "BALANCED"])


if __name__ == "__main__":
    unittest.main()
