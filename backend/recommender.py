"""
recommender.py -- Net-return recommendation engine for KisanLink.

Public interface (stable -- callers should not break if ML swaps in later):
    predict_price(market_id, crop, conn)              -> PricePrediction
    predict_demand(market_id, crop, conn)             -> DemandLevel
    calculate_transport_cost(distance_km,
                             vehicle_type,
                             quantity_kg)             -> float
    get_recommendations(crop, quantity_kg,
                        farmer_lat, farmer_lng, conn) -> list[dict]

Formulas (TRD.md §4.1, §4.2) -- treat as load-bearing, never simplify:
    transport_cost   = base_fee + (distance_km * rate_per_km)
                       + (quantity_kg * rate_per_kg)
    expected_revenue = predicted_price_per_kg * quantity_kg
    expected_net_return = expected_revenue - transport_cost
                          - other_estimated_costs
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent))
from db import get_connection
from ml_service import MLPriceForecaster, MultiFactorDemandClassifier


# ---------------------------------------------------------------------------
# Constants & configuration
# ---------------------------------------------------------------------------

# Vehicle transport rates (Rs).  Configurable without touching callers.
VEHICLE_RATES: dict[str, dict[str, float]] = {
    "mini_truck":  {"base_fee": 500.0, "rate_per_km": 12.0,  "rate_per_kg": 0.50},
    "large_truck": {"base_fee": 800.0, "rate_per_km": 15.0,  "rate_per_kg": 0.30},
    "auto":        {"base_fee": 200.0, "rate_per_km":  8.0,  "rate_per_kg": 1.00},
}

DEFAULT_VEHICLE = "mini_truck"

# Flat market/handling cost per kg (mandi fees, loading, misc).
OTHER_COSTS_PER_KG: float = 1.5

# How many days of history to use for the moving-average price prediction.
HISTORY_DAYS: int = 6

# Demand thresholds (fraction of historical mean arrival).
DEMAND_LOW_THRESHOLD  = 0.80   # arrivals < 80 % of avg  -> demand is High
DEMAND_HIGH_THRESHOLD = 1.20   # arrivals > 120 % of avg -> demand is Low

# Low-arrival price uplift (+2 % if arrivals are significantly low).
LOW_ARRIVAL_UPLIFT = 0.02

# ---------------------------------------------------------------------------
# Hardcoded road distances (km) for all farmer-location → market pairs.
# Keyed as MARKET_DISTANCES_KM[farmer_location][market_name].
# Source: approximate NH-route distances; replace with Maps API post-MVP.
# ---------------------------------------------------------------------------
MARKET_DISTANCES_KM: dict[str, dict[str, float]] = {
    "Pune": {
        "Nashik APMC":         212.0,
        "Pune Market A":         8.0,
        "Aurangabad Market B": 235.0,
        "Nagpur Market C":     705.0,
        "Solapur Market D":    255.0,
    },
    "Nashik": {
        "Nashik APMC":           5.0,
        "Pune Market A":       212.0,
        "Aurangabad Market B": 185.0,
        "Nagpur Market C":     650.0,
        "Solapur Market D":    430.0,
    },
    "Aurangabad": {
        "Nashik APMC":         185.0,
        "Pune Market A":       235.0,
        "Aurangabad Market B":   6.0,
        "Nagpur Market C":     520.0,
        "Solapur Market D":    290.0,
    },
    "Nagpur": {
        "Nashik APMC":         650.0,
        "Pune Market A":       705.0,
        "Aurangabad Market B": 520.0,
        "Nagpur Market C":       8.0,
        "Solapur Market D":    570.0,
    },
    "Solapur": {
        "Nashik APMC":         430.0,
        "Pune Market A":       255.0,
        "Aurangabad Market B": 290.0,
        "Nagpur Market C":     570.0,
        "Solapur Market D":      7.0,
    },
}

# Convenience: Pune distances for compute_net_return() (single-location helper).
_PUNE_DISTANCES: dict[str, float] = MARKET_DISTANCES_KM["Pune"]


# ---------------------------------------------------------------------------
# Return-type definitions
# ---------------------------------------------------------------------------

class DemandLevel(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


@dataclass
class PricePrediction:
    predicted_price: float   # Rs/kg
    trend:           str     # "up" | "down" | "stable"
    confidence:      float   # 0.0 – 1.0


@dataclass
class RecommendationResult:
    rank:               int
    market_id:          int
    market_name:        str
    region:             str
    distance_km:        float
    predicted_price:    float
    trend:              str
    demand_level:       str
    transport_cost:     float
    other_costs:        float
    expected_revenue:   float
    expected_net_return: float
    confidence:          float   # 0.0 – 1.0
    lat:                 float
    lng:                 float
    price_history:       list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres between two (lat, lng) points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Transport-cost formula (TRD.md §4.1)
# ---------------------------------------------------------------------------

def calculate_transport_cost(
    distance_km:  float,
    quantity_kg:  float,
    vehicle_type: str = DEFAULT_VEHICLE,
) -> float:
    """
    transport_cost = base_fee + (distance_km * rate_per_km)
                     + (quantity_kg * rate_per_kg)

    Rates are per-vehicle-type; defaults to mini_truck.
    Raises ValueError for unknown vehicle types.
    """
    if vehicle_type not in VEHICLE_RATES:
        raise ValueError(
            f"Unknown vehicle type '{vehicle_type}'. "
            f"Valid options: {list(VEHICLE_RATES)}"
        )
    rates = VEHICLE_RATES[vehicle_type]
    return (
        rates["base_fee"]
        + distance_km * rates["rate_per_km"]
        + quantity_kg * rates["rate_per_kg"]
    )


# ---------------------------------------------------------------------------
# Price prediction  (TRD.md §4.4) -- rule-based; swap for ML without changing
# the signature.
# ---------------------------------------------------------------------------

def predict_price(
    market_id: int,
    crop:      str,
    conn:      sqlite3.Connection,
    days:      int = HISTORY_DAYS,
    use_ml:    bool = False,
) -> PricePrediction:
    """
    Price prediction function (TRD.md §4.4, ADR-004).
    If use_ml=True, applies Scikit-Learn regression with lagged features.
    If use_ml=False, applies the verified moving average + 2% arrival uplift baseline.
    Output shape is stable: PricePrediction(predicted_price, trend, confidence).
    """
    if use_ml:
        ml_pred = MLPriceForecaster.predict(market_id, crop, conn, days)
        return PricePrediction(
            predicted_price=ml_pred.predicted_price,
            trend=ml_pred.trend,
            confidence=ml_pred.confidence,
        )

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
        return PricePrediction(predicted_price=0.0, trend="stable", confidence=0.1)

    prices    = [r["modal_price"] for r in rows]
    arrivals  = [r["arrival_quantity"] for r in rows]

    avg_price   = sum(prices) / len(prices)
    avg_arrival = sum(arrivals) / len(arrivals)
    latest_arrival = arrivals[0]

    if len(prices) >= 2:
        delta = prices[0] - prices[-1]
        if delta > 0.5:
            trend = "up"
        elif delta < -0.5:
            trend = "down"
        else:
            trend = "stable"
    else:
        trend = "stable"

    uplift = LOW_ARRIVAL_UPLIFT if latest_arrival < avg_arrival * DEMAND_LOW_THRESHOLD else 0.0
    predicted_price = round(avg_price * (1 + uplift), 2)
    confidence = round(0.85 * len(prices) / days, 3)

    return PricePrediction(
        predicted_price=predicted_price,
        trend=trend,
        confidence=min(confidence, 0.9),
    )


def predict_price_ml(
    market_id: int,
    crop:      str,
    conn:      sqlite3.Connection,
    days:      int = HISTORY_DAYS,
) -> PricePrediction:
    """Direct ML price prediction using Scikit-Learn regression."""
    return predict_price(market_id, crop, conn, days=days, use_ml=True)


# ---------------------------------------------------------------------------
# Price history helper (for trend charts/tables)
# ---------------------------------------------------------------------------

def get_price_history(
    market_id: int,
    crop:      str,
    conn:      sqlite3.Connection,
    limit:     int = 5,
) -> list[dict]:
    """
    Return the last `limit` days of price history, ordered chronologically (oldest first).
    """
    rows = conn.execute(
        """
        SELECT date, min_price, max_price, modal_price, arrival_quantity
        FROM   price_history
        WHERE  market_id = ? AND crop = ?
        ORDER  BY date DESC
        LIMIT  ?
        """,
        (market_id, crop, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Demand classification (TRD.md §4.5) -- rule-based & ML multi-factor
# ---------------------------------------------------------------------------

def predict_demand(
    market_id: int,
    crop:      str,
    conn:      sqlite3.Connection,
    days:      int = HISTORY_DAYS,
    use_ml:    bool = False,
) -> DemandLevel:
    """
    Demand classification (TRD.md §4.5).
    If use_ml=True, integrates arrival scarcity, price momentum, and regional buyer volume.
    If use_ml=False, applies the verified arrival thresholds + price trend baseline.
    """
    if use_ml:
        return MultiFactorDemandClassifier.classify(market_id, crop, conn, days)

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

    arrivals    = [r["arrival_quantity"] for r in rows]
    avg_arrival = sum(arrivals) / len(arrivals)
    latest      = arrivals[0]

    prices = [r["modal_price"] for r in rows]
    trend_up = len(prices) >= 2 and prices[0] > prices[-1]

    if latest < avg_arrival * DEMAND_LOW_THRESHOLD and trend_up:
        return DemandLevel.HIGH
    if latest > avg_arrival * DEMAND_HIGH_THRESHOLD:
        return DemandLevel.LOW
    return DemandLevel.MEDIUM


def predict_demand_ml(
    market_id: int,
    crop:      str,
    conn:      sqlite3.Connection,
    days:      int = HISTORY_DAYS,
) -> DemandLevel:
    """Direct multi-factor demand classification."""
    return predict_demand(market_id, crop, conn, days=days, use_ml=True)


# ---------------------------------------------------------------------------
# Single testable net-return calculation helper (TRD.md §4.1 + §4.2)
# ---------------------------------------------------------------------------

def compute_net_return(
    market_name:  str,
    predicted_price_per_kg: float,
    quantity_kg:  float,
    vehicle_type: str = DEFAULT_VEHICLE,
    other_costs_per_kg: float = OTHER_COSTS_PER_KG,
) -> dict:
    """
    Single, self-contained function implementing TRD.md §4.1 and §4.2.

    Uses MARKET_DISTANCES_KM for distance lookup (hardcoded for the 5 demo
    markets; raises KeyError for unknown names).

    §4.1  transport_cost = base_fee
                         + (distance_km * rate_per_km)
                         + (quantity_kg * rate_per_kg)

    §4.2  expected_revenue     = predicted_price_per_kg * quantity_kg
          expected_net_return  = expected_revenue
                               - transport_cost
                               - other_estimated_costs

    Returns a plain dict with every intermediate value so callers can render
    a full breakdown card without extra queries.
    """
    if market_name not in _PUNE_DISTANCES:
        raise KeyError(
            f"No hardcoded distance for '{market_name}'. "
            f"Known markets: {list(_PUNE_DISTANCES)}"
        )

    distance_km    = _PUNE_DISTANCES[market_name]
    transport_cost = calculate_transport_cost(distance_km, quantity_kg, vehicle_type)
    other_costs    = round(other_costs_per_kg * quantity_kg, 2)
    revenue        = round(predicted_price_per_kg * quantity_kg, 2)
    net_return     = round(revenue - transport_cost - other_costs, 2)

    return {
        "market_name":           market_name,
        "distance_km":           distance_km,
        "predicted_price_per_kg": predicted_price_per_kg,
        "quantity_kg":           quantity_kg,
        "vehicle_type":          vehicle_type,
        # §4.1
        "transport_cost":        round(transport_cost, 2),
        # §4.2
        "other_costs":           other_costs,
        "expected_revenue":      revenue,
        "expected_net_return":   net_return,
    }


# ---------------------------------------------------------------------------
# Core recommendation function
# ---------------------------------------------------------------------------

def get_recommendations(
    crop:             str,
    quantity_kg:      float,
    farmer_lat:       float,
    farmer_lng:       float,
    farmer_location:  str = "Pune",
    vehicle_type:     str = DEFAULT_VEHICLE,
    conn:             Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    Return markets ranked by expected_net_return (highest first).

    Each dict contains all fields needed to render a recommendation card:
      market_id, market_name, region, distance_km,
      predicted_price, trend, demand_level,
      transport_cost, other_costs, expected_revenue,
      expected_net_return, confidence, lat, lng, rank

    This is the load-bearing function -- the ranking must always be by
    expected_net_return, never by raw price alone (AGENTS.md core rule).
    """
    _close_conn = conn is None
    if conn is None:
        conn = get_connection()

    try:
        markets = conn.execute(
            "SELECT id, name, lat, lng, region FROM markets ORDER BY id"
        ).fetchall()

        results: list[RecommendationResult] = []

        for m in markets:
            # Use per-location hardcoded distance table when available;
            # fall back to haversine for unknown locations or markets.
            loc_table = MARKET_DISTANCES_KM.get(farmer_location, {})
            distance_km = loc_table.get(
                m["name"],
                haversine_km(farmer_lat, farmer_lng, m["lat"], m["lng"]),
            )

            price_pred  = predict_price(m["id"], crop, conn)
            demand_lvl  = predict_demand(m["id"], crop, conn)
            history     = get_price_history(m["id"], crop, conn, limit=5)

            transport   = calculate_transport_cost(distance_km, quantity_kg, vehicle_type)
            other_costs = round(OTHER_COSTS_PER_KG * quantity_kg, 2)
            revenue     = round(price_pred.predicted_price * quantity_kg, 2)
            net_return  = round(revenue - transport - other_costs, 2)

            results.append(RecommendationResult(
                rank=0,  # filled in after sort
                market_id=m["id"],
                market_name=m["name"],
                region=m["region"],
                distance_km=round(distance_km, 1),
                predicted_price=price_pred.predicted_price,
                trend=price_pred.trend,
                demand_level=demand_lvl.value,
                transport_cost=round(transport, 2),
                other_costs=other_costs,
                expected_revenue=revenue,
                expected_net_return=net_return,
                confidence=price_pred.confidence,
                lat=m["lat"],
                lng=m["lng"],
                price_history=history,
            ))

        # Primary sort: expected_net_return descending (AGENTS.md core rule).
        results.sort(key=lambda r: r.expected_net_return, reverse=True)
        for i, r in enumerate(results, start=1):
            r.rank = i

        return [vars(r) for r in results]

    finally:
        if _close_conn:
            conn.close()
