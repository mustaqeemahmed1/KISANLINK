"""
ml_service.py -- Machine Learning & Statistical Intelligence Service for KisanLink AI.

Provides:
  1. MLPriceForecaster:
     Predicts price N-days ahead using Scikit-Learn regression with lagged
     prices, arrival elasticity, and temporal trend. Includes fallback if
     external dependencies are unavailable (ADR-004).
  2. MultiFactorDemandClassifier:
     Multi-factor demand scoring integrating arrival volume scarcity,
     price momentum, and wholesale buyer marketplace demand signals (TRD.md §4.5).
  3. PriceAnomalyDetector:
     Statistical outlier detection (Z-score and median deviation) flagging
     errant market prices or fraudulent crowdsourced reports (TRD.md §4.6).
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

try:
    import numpy as np
    from sklearn.linear_model import Ridge
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class DemandLevel(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


@dataclass
class PricePrediction:
    predicted_price: float   # Rs/kg
    trend:           str     # "up" | "down" | "stable"
    confidence:      float   # 0.0 - 1.0
    model_used:      str = "ml_ridge"


@dataclass
class AnomalyRecord:
    market_name:     str
    crop:            str
    price:           float
    benchmark_price: float
    deviation_pct:   float
    severity:        str     # "HIGH" | "MEDIUM"
    reason:          str


# ---------------------------------------------------------------------------
# 1. ML Price Forecaster
# ---------------------------------------------------------------------------

class MLPriceForecaster:
    """
    Forecasting model for APMC mandi prices.
    Uses Scikit-Learn Ridge regression with lagged prices and arrival ratios,
    with a graceful deterministic fallback.
    """

    @staticmethod
    def predict(
        market_id: int,
        crop:      str,
        conn:      sqlite3.Connection,
        days:      int = 6,
    ) -> PricePrediction:
        """
        Train on historical price sequence and predict next-day modal price.
        Guarantees stable return shape (predicted_price, trend, confidence).
        """
        rows = conn.execute(
            """
            SELECT date, modal_price, min_price, max_price, arrival_quantity
            FROM   price_history
            WHERE  market_id = ? AND crop = ?
            ORDER  BY date ASC
            """,
            (market_id, crop),
        ).fetchall()

        if not rows:
            return PricePrediction(predicted_price=0.0, trend="stable", confidence=0.1, model_used="fallback_empty")

        prices = [float(r["modal_price"]) for r in rows]
        arrivals = [float(r["arrival_quantity"]) for r in rows]
        n = len(prices)
        latest_price = prices[-1]

        # Use Scikit-Learn regression if available and >= 3 data points
        if HAS_SKLEARN and n >= 3:
            try:
                # Feature engineering:
                # X: [time_step, lagged_price, arrival_ratio]
                mean_arr = sum(arrivals) / len(arrivals) if sum(arrivals) > 0 else 1.0
                X = []
                y = []
                for i in range(1, n):
                    arr_ratio = arrivals[i - 1] / mean_arr
                    X.append([i, prices[i - 1], arr_ratio])
                    y.append(prices[i])

                X_mat = np.array(X)
                y_vec = np.array(y)

                # Train Ridge regression model
                model = Ridge(alpha=1.0)
                model.fit(X_mat, y_vec)

                # Next step feature vector
                next_arr_ratio = arrivals[-1] / mean_arr
                next_X = np.array([[n, latest_price, next_arr_ratio]])
                pred_raw = float(model.predict(next_X)[0])

                # Constrain prediction to realistic daily bounds (within +/- 25% of latest)
                pred_price = max(latest_price * 0.75, min(latest_price * 1.25, pred_raw))
                pred_price = round(pred_price, 2)

                # Trend
                delta = pred_price - latest_price
                if delta > 0.5:
                    trend = "up"
                elif delta < -0.5:
                    trend = "down"
                else:
                    trend = "stable"

                # Confidence based on historical window length
                confidence = round(min(0.92, 0.75 + (n / 30.0) * 0.17), 3)

                return PricePrediction(
                    predicted_price=pred_price,
                    trend=trend,
                    confidence=confidence,
                    model_used="sklearn_ridge",
                )
            except Exception:
                pass  # Fall through to deterministic moving-average model

        # Deterministic Momentum Fallback (linear momentum + arrival elasticity)
        if n >= 2:
            momentum = (prices[-1] - prices[0]) / (n - 1)
        else:
            momentum = 0.0

        mean_arr = sum(arrivals) / len(arrivals) if sum(arrivals) > 0 else 1.0
        latest_arr = arrivals[-1]

        # Low arrivals uplift (+2% if arrivals < 80% average)
        uplift = 0.02 if latest_arr < mean_arr * 0.8 else (-0.02 if latest_arr > mean_arr * 1.2 else 0.0)
        pred_price = round((latest_price + momentum * 0.5) * (1 + uplift), 2)

        if prices[-1] - prices[0] > 0.5:
            trend = "up"
        elif prices[-1] - prices[0] < -0.5:
            trend = "down"
        else:
            trend = "stable"

        confidence = round(min(0.85, 0.65 + (n / 10.0) * 0.2), 3)

        return PricePrediction(
            predicted_price=pred_price,
            trend=trend,
            confidence=confidence,
            model_used="linear_momentum",
        )


# ---------------------------------------------------------------------------
# 2. Multi-Factor Demand Classifier
# ---------------------------------------------------------------------------

class MultiFactorDemandClassifier:
    """
    Classifies market demand using a composite index:
      - Arrival scarcity (low arrivals vs historical average)
      - Price momentum (positive price slope over recent window)
      - Wholesale buyer marketplace demand volume in the region
    """

    @staticmethod
    def classify(
        market_id: int,
        crop:      str,
        conn:      sqlite3.Connection,
        days:      int = 6,
    ) -> DemandLevel:
        # 1. Historical market price and arrival trends
        rows = conn.execute(
            """
            SELECT modal_price, arrival_quantity
            FROM   price_history
            WHERE  market_id = ? AND crop = ?
            ORDER  BY date DESC
            LIMIT  ?
            """,
            (market_id, crop, days),
        ).fetchall()

        if not rows:
            return DemandLevel.MEDIUM

        arrivals = [float(r["arrival_quantity"]) for r in rows]
        prices = [float(r["modal_price"]) for r in rows]
        avg_arr = sum(arrivals) / len(arrivals) if sum(arrivals) > 0 else 1.0
        latest_arr = arrivals[0]

        # 2. Regional Buyer Demand Signal (optional table for test DB compatibility)
        buyer_wanted_kg = 0.0
        try:
            market_row = conn.execute("SELECT region FROM markets WHERE id = ?", (market_id,)).fetchone()
            region = market_row["region"] if market_row else ""

            buyer_demand_row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity_kg), 0) as total_wanted
                FROM buyer_requirements
                WHERE crop = ? AND location LIKE ?
                """,
                (crop, f"%{region}%"),
            ).fetchone()
            if buyer_demand_row:
                buyer_wanted_kg = float(buyer_demand_row["total_wanted"])
        except sqlite3.OperationalError:
            pass

        # 3. Composite Demand Scoring
        score = 0.0

        # Scarcity Factor (-0.35 to +0.35)
        if latest_arr < avg_arr * 0.80:
            score += 0.35  # Supply shortage -> high demand pressure
        elif latest_arr > avg_arr * 1.20:
            score -= 0.35  # Supply glut -> low demand pressure

        # Price Momentum Factor (-0.30 to +0.30)
        if len(prices) >= 2:
            momentum = prices[0] - prices[-1]
            if momentum > 0.5:
                score += 0.30  # Rising prices -> strong buying competition
            elif momentum < -0.5:
                score -= 0.30  # Falling prices -> weak buying interest

        # Commercial Buyer Requirement Factor (0.0 to +0.35)
        if buyer_wanted_kg >= 5000.0:
            score += 0.35  # High active institutional buyer volume
        elif buyer_wanted_kg >= 2000.0:
            score += 0.15

        # Classification decision
        if score >= 0.35:
            return DemandLevel.HIGH
        elif score <= -0.35:
            return DemandLevel.LOW
        return DemandLevel.MEDIUM


# ---------------------------------------------------------------------------
# 3. Statistical Anomaly Detection Service
# ---------------------------------------------------------------------------

class PriceAnomalyDetector:
    """
    Detects abnormal market price spikes, crashes, and uncorroborated
    crowdsourced price reports using Z-score and median relative deviation (TRD.md §4.6).
    """

    @staticmethod
    def detect_anomalies(conn: sqlite3.Connection) -> List[AnomalyRecord]:
        """
        Scan latest prices across all markets and crops.
        Flags prices that deviate beyond statistical variance thresholds.
        """
        anomalies: List[AnomalyRecord] = []

        crops_rows = conn.execute("SELECT DISTINCT crop FROM price_history").fetchall()
        crops = [r["crop"] for r in crops_rows]

        for crop in crops:
            # Get latest price for each market
            rows = conn.execute(
                """
                SELECT m.name as market_name, ph.modal_price
                FROM price_history ph
                JOIN markets m ON ph.market_id = m.id
                WHERE ph.crop = ?
                  AND ph.date = (SELECT MAX(date) FROM price_history WHERE crop = ?)
                """,
                (crop, crop),
            ).fetchall()

            if len(rows) < 3:
                continue

            prices = [float(r["modal_price"]) for r in rows]
            mean_p = sum(prices) / len(prices)
            variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
            std_p = math.sqrt(variance) if variance > 0 else 0.0

            sorted_prices = sorted(prices)
            median_p = sorted_prices[len(sorted_prices) // 2]

            for r in rows:
                p = float(r["modal_price"])
                dev_pct = abs(p - median_p) / median_p if median_p > 0 else 0.0
                z_score = abs(p - mean_p) / std_p if std_p > 0 else 0.0

                if z_score > 1.8 or dev_pct > 0.28:
                    severity = "HIGH" if (z_score > 2.2 or dev_pct > 0.38) else "MEDIUM"
                    direction = "above" if p > median_p else "below"
                    anomalies.append(
                        AnomalyRecord(
                            market_name=r["market_name"],
                            crop=crop,
                            price=p,
                            benchmark_price=round(median_p, 1),
                            deviation_pct=round(dev_pct * 100, 1),
                            severity=severity,
                            reason=f"Price is {round(dev_pct * 100, 1)}% {direction} regional benchmark (Z={z_score:.2f})",
                        )
                    )

        return anomalies
