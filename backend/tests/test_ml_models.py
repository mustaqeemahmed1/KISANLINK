"""
test_ml_models.py -- Unit tests for Phase 4 Machine Learning & Intelligence Services.
Tests:
  - MLPriceForecaster (Ridge regression & arrival elasticity)
  - MultiFactorDemandClassifier (Scarcity + Momentum + Commercial buyer requirements)
  - PriceAnomalyDetector (Statistical Z-score & IQR outlier detection)
"""

import sqlite3
import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection
from ml_service import (
    DemandLevel,
    MLPriceForecaster,
    MultiFactorDemandClassifier,
    PriceAnomalyDetector,
    PricePrediction,
)
from recommender import predict_demand, predict_price


class TestMLModelsAndIntelligence(unittest.TestCase):
    """Test suite for ML models and statistical detection."""

    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_ml_price_forecaster_output(self):
        """Test MLPriceForecaster produces bounded prediction and valid confidence score."""
        pred = MLPriceForecaster.predict(market_id=1, crop="Tomato", conn=self.conn)
        self.assertIsInstance(pred, PricePrediction)
        self.assertGreater(pred.predicted_price, 10.0)
        self.assertLess(pred.predicted_price, 50.0)
        self.assertIn(pred.trend, ["up", "down", "stable"])
        self.assertGreaterEqual(pred.confidence, 0.6)
        self.assertLessEqual(pred.confidence, 1.0)
        self.assertIn(pred.model_used, ["sklearn_ridge", "linear_momentum"])

    def test_ml_forecaster_trend_direction(self):
        """Test that synthetic upward prices yield 'up' trend."""
        # Create in-memory DB with known upward slope
        mem_conn = sqlite3.connect(":memory:")
        mem_conn.row_factory = sqlite3.Row
        mem_conn.execute("CREATE TABLE price_history (date TEXT, modal_price REAL, min_price REAL, max_price REAL, arrival_quantity REAL, market_id INT, crop TEXT)")
        for i, p in enumerate([20.0, 22.0, 25.0, 28.0, 31.0]):
            mem_conn.execute(
                "INSERT INTO price_history VALUES (?, ?, ?, ?, 100.0, 1, 'Tomato')",
                (f"2026-08-0{i+1}", p, p-2, p+2),
            )
        pred = MLPriceForecaster.predict(market_id=1, crop="Tomato", conn=mem_conn)
        self.assertEqual(pred.trend, "up")
        self.assertGreater(pred.predicted_price, 28.0)
        mem_conn.close()

    def test_multifactor_demand_classifier(self):
        """Test that demand classification evaluates multi-factor signals."""
        demand = MultiFactorDemandClassifier.classify(market_id=1, crop="Tomato", conn=self.conn)
        self.assertIn(demand, [DemandLevel.HIGH, DemandLevel.MEDIUM, DemandLevel.LOW])

    def test_recommender_delegation_to_ml(self):
        """Test that recommender.predict_price and predict_demand seamlessly delegate to ML."""
        p = predict_price(market_id=2, crop="Onion", conn=self.conn)
        self.assertGreater(p.predicted_price, 0)
        self.assertIn(p.trend, ["up", "down", "stable"])

        d = predict_demand(market_id=2, crop="Onion", conn=self.conn)
        self.assertIn(d, [DemandLevel.HIGH, DemandLevel.MEDIUM, DemandLevel.LOW])

    def test_anomaly_detection_with_synthetic_outlier(self):
        """Test that PriceAnomalyDetector flags severe outlier prices."""
        # Clean baseline
        anomalies_before = PriceAnomalyDetector.detect_anomalies(self.conn)

        # Inject synthetic extreme outlier in in-memory copy
        mem_conn = sqlite3.connect(":memory:")
        mem_conn.row_factory = sqlite3.Row
        mem_conn.execute("CREATE TABLE markets (id INT, name TEXT, region TEXT)")
        mem_conn.execute("CREATE TABLE price_history (date TEXT, modal_price REAL, min_price REAL, max_price REAL, arrival_quantity REAL, market_id INT, crop TEXT)")

        # Normal markets
        for m_id, name in [(1, "Market A"), (2, "Market B"), (3, "Market C"), (4, "Market D")]:
            mem_conn.execute("INSERT INTO markets VALUES (?, ?, 'Region')", (m_id, name))
            mem_conn.execute("INSERT INTO price_history VALUES ('2026-08-25', 25.0, 23.0, 27.0, 100.0, ?, 'Tomato')", (m_id,))

        # Inject extreme outlier in Market E (e.g. Rs. 140/kg vs normal 25/kg)
        mem_conn.execute("INSERT INTO markets VALUES (5, 'Market Anomaly', 'Region')")
        mem_conn.execute("INSERT INTO price_history VALUES ('2026-08-25', 140.0, 130.0, 150.0, 10.0, 5, 'Tomato')")

        anomalies = PriceAnomalyDetector.detect_anomalies(mem_conn)
        mem_conn.close()

        self.assertGreaterEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].market_name, "Market Anomaly")
        self.assertEqual(anomalies[0].severity, "HIGH")
        self.assertGreater(anomalies[0].deviation_pct, 100.0)


if __name__ == "__main__":
    unittest.main()
