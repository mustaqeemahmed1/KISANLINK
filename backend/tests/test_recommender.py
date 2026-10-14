"""
test_recommender.py -- Unit tests for KisanLink net-return and transport-cost
calculations.

Per AGENTS.md: any change to the net-return or transport-cost formulas requires
an accompanying unit test.  Run with:
    py -m pytest backend/tests/          (if pytest installed)
    py -m unittest discover -s backend   (stdlib only)
"""

import sqlite3
import sys
import unittest
from pathlib import Path

# Make sure the backend package is importable from any CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from recommender import (
    VEHICLE_RATES,
    OTHER_COSTS_PER_KG,
    MARKET_DISTANCES_KM,
    DemandLevel,
    PricePrediction,
    calculate_transport_cost,
    compute_net_return,
    get_recommendations,
    haversine_km,
    predict_demand,
    predict_price,
)


# ---------------------------------------------------------------------------
# Helpers to build an in-memory DB with seeded data for isolated tests.
# ---------------------------------------------------------------------------

def _make_db(price_rows: list[tuple]) -> sqlite3.Connection:
    """
    Return an in-memory SQLite connection pre-loaded with one market and the
    given price_history rows.

    price_rows: list of (modal_price, arrival_quantity) tuples, newest first.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, lat REAL, lng REAL, region TEXT
        );
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id INTEGER NOT NULL REFERENCES markets(id),
            crop TEXT NOT NULL, date TEXT NOT NULL,
            min_price REAL NOT NULL, max_price REAL NOT NULL,
            modal_price REAL NOT NULL, arrival_quantity REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'test',
            confidence_score REAL NOT NULL DEFAULT 0.9,
            UNIQUE (market_id, crop, date)
        );
    """)
    conn.execute(
        "INSERT INTO markets (name, lat, lng, region) VALUES (?, ?, ?, ?)",
        ("Test Market", 18.52, 73.85, "TestRegion"),
    )
    market_id = conn.execute("SELECT id FROM markets WHERE name='Test Market'").fetchone()["id"]
    for i, (modal, arrival) in enumerate(reversed(price_rows)):
        date = f"2026-08-{20 + i:02d}"
        conn.execute(
            """INSERT INTO price_history
               (market_id, crop, date, min_price, max_price, modal_price,
                arrival_quantity, source, confidence_score)
               VALUES (?, 'Tomato', ?, ?, ?, ?, ?, 'test', 0.9)""",
            (market_id, date, modal - 3, modal + 3, modal, arrival),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Transport cost tests (TRD.md §4.1)
# ---------------------------------------------------------------------------

class TestTransportCost(unittest.TestCase):

    def test_mini_truck_formula(self):
        """transport_cost = base_fee + dist*rate_per_km + qty*rate_per_kg"""
        rates = VEHICLE_RATES["mini_truck"]
        dist, qty = 100.0, 500.0
        expected = rates["base_fee"] + dist * rates["rate_per_km"] + qty * rates["rate_per_kg"]
        self.assertAlmostEqual(calculate_transport_cost(dist, qty, "mini_truck"), expected)

    def test_large_truck_formula(self):
        rates = VEHICLE_RATES["large_truck"]
        dist, qty = 200.0, 1000.0
        expected = rates["base_fee"] + dist * rates["rate_per_km"] + qty * rates["rate_per_kg"]
        self.assertAlmostEqual(calculate_transport_cost(dist, qty, "large_truck"), expected)

    def test_zero_distance(self):
        """At zero distance, cost = base_fee + qty * rate_per_kg."""
        rates = VEHICLE_RATES["mini_truck"]
        cost = calculate_transport_cost(0.0, 200.0, "mini_truck")
        self.assertAlmostEqual(cost, rates["base_fee"] + 200.0 * rates["rate_per_kg"])

    def test_unknown_vehicle_raises(self):
        with self.assertRaises(ValueError):
            calculate_transport_cost(50.0, 200.0, "spaceship")

    def test_cost_increases_with_distance(self):
        c1 = calculate_transport_cost(50.0,  500.0)
        c2 = calculate_transport_cost(200.0, 500.0)
        self.assertGreater(c2, c1)

    def test_cost_increases_with_quantity(self):
        c1 = calculate_transport_cost(100.0, 100.0)
        c2 = calculate_transport_cost(100.0, 500.0)
        self.assertGreater(c2, c1)


# ---------------------------------------------------------------------------
# Net-return formula tests (TRD.md §4.2)
# ---------------------------------------------------------------------------

class TestNetReturn(unittest.TestCase):
    """
    Verify the net-return formula:
        expected_revenue     = predicted_price * quantity_kg
        expected_net_return  = expected_revenue - transport_cost - other_costs
    These tests work at the formula level, not against a real DB.
    """

    def _net_return(self, price, qty, transport, other_per_kg=OTHER_COSTS_PER_KG):
        revenue     = price * qty
        other_costs = other_per_kg * qty
        return revenue - transport - other_costs

    def test_basic_net_return(self):
        # price=25, qty=500, transport=2750, other=750 -> net=25*500-2750-750=9000
        nr = self._net_return(price=25.0, qty=500.0, transport=2750.0)
        self.assertAlmostEqual(nr, 9000.0)

    def test_high_price_market_not_always_best(self):
        """
        The tomato example from PRD.md §2: Market B has highest price but
        Market C can have higher net return once transport is factored in.
        """
        # Market B: price 30, 300 km away -> transport = 500+300*12+500*0.5 = 4850
        market_b_net = self._net_return(30.0, 500.0, transport=4850.0)
        # Market C: price 27, 80 km away  -> transport = 500+80*12+500*0.5 = 1710
        market_c_net = self._net_return(27.0, 500.0, transport=1710.0)
        self.assertGreater(market_c_net, market_b_net,
            "Market C (lower price, closer) must beat Market B (higher price, farther) "
            "on net return -- this is the core product differentiator.")

    def test_negative_net_return_possible(self):
        """A very distant market can yield negative net return -- that's valid."""
        nr = self._net_return(price=10.0, qty=100.0, transport=5000.0)
        self.assertLess(nr, 0)


# ---------------------------------------------------------------------------
# Price prediction tests (TRD.md §4.4)
# ---------------------------------------------------------------------------

class TestPricePredict(unittest.TestCase):

    def test_returns_moving_average(self):
        """predicted_price should be close to the moving average of modal prices."""
        prices = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]  # newest first
        conn = _make_db([(p, 100) for p in prices])
        result = predict_price(1, "Tomato", conn)
        expected_avg = sum(prices) / len(prices)
        # No uplift (arrivals are constant), so predicted ~ avg
        self.assertAlmostEqual(result.predicted_price, round(expected_avg, 2))

    def test_low_arrival_uplift(self):
        """Low arrivals relative to average should push predicted price up 2%."""
        # _make_db inserts reversed(rows), so index 0 here = newest date.
        # Row 0 (arrivals=50) will be the latest; rows 1-5 (arrivals=100) are older.
        # avg_arrival = (50+100*5)/6 = 91.7; 50 < 91.7*0.8=73.3 -> uplift fires.
        rows = [(20.0, 50), (20.0, 100), (20.0, 100), (20.0, 100), (20.0, 100), (20.0, 100)]
        conn = _make_db(rows)
        result = predict_price(1, "Tomato", conn)
        base_avg = 20.0
        self.assertAlmostEqual(result.predicted_price, round(base_avg * 1.02, 2))

    def test_trend_up(self):
        """Rising prices should give trend='up'."""
        conn = _make_db([(25.0, 100), (24.0, 100), (23.0, 100), (22.0, 100), (21.0, 100), (20.0, 100)])
        result = predict_price(1, "Tomato", conn)
        self.assertEqual(result.trend, "up")

    def test_trend_down(self):
        """Falling prices should give trend='down'."""
        conn = _make_db([(20.0, 100), (21.0, 100), (22.0, 100), (23.0, 100), (24.0, 100), (25.0, 100)])
        result = predict_price(1, "Tomato", conn)
        self.assertEqual(result.trend, "down")

    def test_no_data_fallback(self):
        """Missing price history should return confidence=0.1, not crash."""
        conn = _make_db([])
        result = predict_price(1, "Wheat", conn)  # different crop, no data
        self.assertEqual(result.confidence, 0.1)
        self.assertEqual(result.predicted_price, 0.0)

    def test_confidence_bounded(self):
        result = predict_price(1, "Tomato", _make_db([(20.0, 100)] * 6))
        self.assertLessEqual(result.confidence, 0.9)
        self.assertGreater(result.confidence, 0.0)


# ---------------------------------------------------------------------------
# Demand classification tests (TRD.md §4.5)
# ---------------------------------------------------------------------------

class TestDemandPredict(unittest.TestCase):

    def test_high_demand(self):
        """Low arrivals + rising price -> High demand."""
        # Arrivals drop from 100 to 50 (< 80%), prices rising.
        rows = [(25.0, 50), (24.0, 100), (23.0, 100), (22.0, 100), (21.0, 100), (20.0, 100)]
        conn = _make_db(rows)
        self.assertEqual(predict_demand(1, "Tomato", conn), DemandLevel.HIGH)

    def test_low_demand(self):
        """Very high arrivals -> Low demand (surplus)."""
        rows = [(20.0, 200), (20.0, 200), (20.0, 200), (20.0, 100), (20.0, 80), (20.0, 90)]
        conn = _make_db(rows)
        self.assertEqual(predict_demand(1, "Tomato", conn), DemandLevel.LOW)

    def test_medium_demand(self):
        """Normal arrivals -> Medium demand."""
        rows = [(20.0, 100)] * 6
        conn = _make_db(rows)
        self.assertEqual(predict_demand(1, "Tomato", conn), DemandLevel.MEDIUM)


# ---------------------------------------------------------------------------
# Haversine distance sanity check
# ---------------------------------------------------------------------------

class TestHaversine(unittest.TestCase):

    def test_same_point_is_zero(self):
        self.assertAlmostEqual(haversine_km(18.52, 73.85, 18.52, 73.85), 0.0)

    def test_pune_nashik_approx(self):
        """Pune to Nashik is roughly 210 km by road; straight-line ~195 km."""
        dist = haversine_km(18.5204, 73.8567, 20.0059, 73.7797)
        self.assertGreater(dist, 150)
        self.assertLess(dist, 230)


# ---------------------------------------------------------------------------
# End-to-end recommendation ranking test (AGENTS.md "Definition of Done")
# ---------------------------------------------------------------------------

class TestGetRecommendations(unittest.TestCase):
    """
    Integration test: submit produce -> get ranked list -> top result has the
    highest expected_net_return.
    This is the AGENTS.md definition-of-done check for the recommendation flow.
    """

    def test_top_result_has_highest_net_return(self):
        """Ranked list must be ordered by expected_net_return, not price."""
        from db import get_connection, create_tables
        conn = get_connection()
        recs = get_recommendations(
            crop="Tomato",
            quantity_kg=500.0,
            farmer_lat=18.52,
            farmer_lng=73.85,
            conn=conn,
        )
        conn.close()

        self.assertGreater(len(recs), 0, "Should return at least one market")

        # Verify descending sort by net return.
        net_returns = [r["expected_net_return"] for r in recs]
        self.assertEqual(
            net_returns,
            sorted(net_returns, reverse=True),
            "Recommendations must be sorted by expected_net_return, not by price.",
        )

    def test_rank_field_is_sequential(self):
        from db import get_connection
        conn = get_connection()
        recs = get_recommendations("Tomato", 500.0, 18.52, 73.85, conn=conn)
        conn.close()
        ranks = [r["rank"] for r in recs]
        self.assertEqual(ranks, list(range(1, len(recs) + 1)))

    def test_all_required_fields_present(self):
        from db import get_connection
        conn = get_connection()
        recs = get_recommendations("Tomato", 500.0, 18.52, 73.85, conn=conn)
        conn.close()
        required = {
            "rank", "market_id", "market_name", "region", "distance_km",
            "predicted_price", "trend", "demand_level", "transport_cost",
            "other_costs", "expected_revenue", "expected_net_return", "confidence",
        }
        for rec in recs:
            self.assertTrue(
                required.issubset(rec.keys()),
                f"Missing fields: {required - rec.keys()}",
            )



# ---------------------------------------------------------------------------
# compute_net_return() tests (TRD.md §4.1 + §4.2, hardcoded distances)
# ---------------------------------------------------------------------------

class TestComputeNetReturn(unittest.TestCase):
    """
    Tests for the single testable net-return function (TRD.md §4.1 + §4.2).
    Each test names the formula step it covers.
    """

    def test_all_five_markets_present(self):
        """MARKET_DISTANCES_KM['Pune'] must have exactly the 5 seeded markets."""
        expected = {
            "Nashik APMC", "Pune Market A", "Aurangabad Market B",
            "Nagpur Market C", "Solapur Market D",
        }
        self.assertEqual(set(MARKET_DISTANCES_KM["Pune"].keys()), expected)

    def test_formula_section_4_1_transport(self):
        """Transport cost component matches TRD.md §4.1 formula exactly."""
        result = compute_net_return(
            market_name="Nashik APMC",
            predicted_price_per_kg=26.0,
            quantity_kg=500.0,
        )
        rates = VEHICLE_RATES["mini_truck"]
        dist  = MARKET_DISTANCES_KM["Pune"]["Nashik APMC"]   # 212 km
        expected_transport = (
            rates["base_fee"]
            + dist * rates["rate_per_km"]
            + 500.0 * rates["rate_per_kg"]
        )
        self.assertAlmostEqual(result["transport_cost"], round(expected_transport, 2))

    def test_formula_section_4_2_net_return(self):
        """Net return = revenue - transport_cost - other_costs (TRD.md §4.2)."""
        result = compute_net_return(
            market_name="Pune Market A",
            predicted_price_per_kg=22.0,
            quantity_kg=500.0,
        )
        expected_revenue    = 22.0 * 500.0
        expected_other      = OTHER_COSTS_PER_KG * 500.0
        expected_net        = expected_revenue - result["transport_cost"] - expected_other
        self.assertAlmostEqual(result["expected_net_return"], round(expected_net, 2))
        self.assertAlmostEqual(result["expected_revenue"],    round(expected_revenue, 2))

    def test_closer_market_beats_higher_price_distant_market(self):
        """
        PRD.md §2 tomato example: a closer market with lower price can beat
        a distant market with higher price on net return.
        Nagpur (705 km, price 31) vs Pune (8 km, price 26):
          Nagpur transport = 500 + 705*12 + 500*0.5 = 9110  -> net = 15500-9110-750 = 5640
          Pune   transport = 500 +   8*12 + 500*0.5 =  846  -> net = 13000- 846-750 = 11404
        Pune wins despite lower price because transport wipes out Nagpur's advantage.
        """
        nagpur = compute_net_return("Nagpur Market C", 31.0, 500.0)
        pune   = compute_net_return("Pune Market A",   26.0, 500.0)
        self.assertGreater(
            pune["expected_net_return"],
            nagpur["expected_net_return"],
            "Pune (closer, lower price) must yield higher net return than "
            "Nagpur (farther, higher price) -- core product differentiator.",
        )


    def test_nagpur_highest_distance_highest_transport(self):
        """Nagpur (705 km) must have the highest transport cost of all 5 markets."""
        results = [
            compute_net_return(name, 25.0, 500.0)
            for name in MARKET_DISTANCES_KM["Pune"]
        ]
        nagpur = next(r for r in results if r["market_name"] == "Nagpur Market C")
        max_transport = max(r["transport_cost"] for r in results)
        self.assertAlmostEqual(nagpur["transport_cost"], max_transport)

    def test_output_contains_all_required_fields(self):
        """Return dict must have every field needed to render a breakdown card."""
        result = compute_net_return("Solapur Market D", 21.0, 300.0)
        required = {
            "market_name", "distance_km", "predicted_price_per_kg",
            "quantity_kg", "vehicle_type", "transport_cost",
            "other_costs", "expected_revenue", "expected_net_return",
        }
        self.assertTrue(required.issubset(result.keys()))

    def test_unknown_market_raises_key_error(self):
        with self.assertRaises(KeyError):
            compute_net_return("Imaginary Market Z", 25.0, 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
