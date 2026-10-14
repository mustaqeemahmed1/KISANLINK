"""
alerts.py -- Smart Selling Opportunity and Market Alert Engine for KisanLink AI.

Per PRD.md §6 Post-MVP scope:
Monitors buyer purchase premiums, regional price surges, and arrival gluts
to alert farmers to high-profit selling windows.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SmartAlert:
    id:          str
    type:        str     # "SELLING_OPPORTUNITY" | "PRICE_SURGE" | "DEMAND_WARNING"
    title:       str
    message:     str
    crop:        str
    severity:    str     # "success" | "info" | "warning"
    timestamp:   str


class SmartAlertService:
    """
    Engine evaluating market conditions to generate actionable farmer selling alerts.
    """

    @staticmethod
    def get_alerts(
        conn: sqlite3.Connection,
        crop: Optional[str] = None,
        farmer_location: Optional[str] = None,
    ) -> List[dict]:
        """
        Generate active alerts matching crop and optional regional proximity.
        """
        alerts: List[SmartAlert] = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        # 1. High-Premium Buyer Selling Opportunities
        buyer_query = """
        SELECT br.id, br.crop, br.quantity_kg, br.offered_price, br.location,
               br.pickup_available, b.name as buyer_name, b.verified
        FROM buyer_requirements br
        JOIN buyers b ON br.buyer_id = b.id
        """
        params = []
        if crop:
            buyer_query += " WHERE br.crop = ?"
            params.append(crop.strip().title())

        buyer_rows = conn.execute(buyer_query, params).fetchall()

        for b in buyer_rows:
            # Check regional modal benchmark
            benchmark_row = conn.execute(
                """
                SELECT ROUND(AVG(modal_price), 1) as avg_modal
                FROM price_history
                WHERE crop = ?
                  AND date = (SELECT MAX(date) FROM price_history WHERE crop = ?)
                """,
                (b["crop"], b["crop"]),
            ).fetchone()

            avg_modal = benchmark_row["avg_modal"] if benchmark_row and benchmark_row["avg_modal"] else 20.0
            premium = b["offered_price"] - avg_modal

            if premium >= 1.0:
                pickup_note = "with Farm Pickup" if b["pickup_available"] else "at Sourcing Hub"
                alerts.append(
                    SmartAlert(
                        id=f"alert-buyer-{b['id']}",
                        type="SELLING_OPPORTUNITY",
                        title=f"Premium Buyer Offer: {b['crop']} @ Rs.{b['offered_price']}/kg",
                        message=(
                            f"{b['buyer_name']} ({b['location']}) is offering Rs.{b['offered_price']}/kg "
                            f"(+Rs.{premium:.1f}/kg above mandi average) for {int(b['quantity_kg']):,} kg {pickup_note}."
                        ),
                        crop=b["crop"],
                        severity="success",
                        timestamp=now_str,
                    )
                )

        # 2. Market Price Surge Alerts
        surge_query = """
        SELECT m.name as market_name, ph.crop, ph.modal_price, ph.date
        FROM price_history ph
        JOIN markets m ON ph.market_id = m.id
        WHERE ph.date = (SELECT MAX(date) FROM price_history)
        """
        surge_params = []
        if crop:
            surge_query += " AND ph.crop = ?"
            surge_params.append(crop.strip().title())

        latest_prices = conn.execute(surge_query, surge_params).fetchall()

        for lp in latest_prices:
            # Check previous 3-day average
            hist_row = conn.execute(
                """
                SELECT ROUND(AVG(modal_price), 1) as hist_avg
                FROM price_history ph
                JOIN markets m ON ph.market_id = m.id
                WHERE m.name = ? AND ph.crop = ? AND ph.date < ?
                ORDER BY ph.date DESC LIMIT 3
                """,
                (lp["market_name"], lp["crop"], lp["date"]),
            ).fetchone()

            if hist_row and hist_row["hist_avg"]:
                hist_avg = hist_row["hist_avg"]
                gain = lp["modal_price"] - hist_avg
                gain_pct = (gain / hist_avg) * 100

                if gain_pct >= 8.0:
                    alerts.append(
                        SmartAlert(
                            id=f"alert-surge-{lp['market_name']}-{lp['crop']}",
                            type="PRICE_SURGE",
                            title=f"Price Surge: {lp['crop']} at {lp['market_name']}",
                            message=(
                                f"Modal price at {lp['market_name']} jumped to Rs.{lp['modal_price']}/kg "
                                f"(+{gain_pct:.1f}% vs 3-day average). Consider shipping produce here."
                            ),
                            crop=lp["crop"],
                            severity="info",
                            timestamp=now_str,
                        )
                    )

        # 3. Supply Glut / Demand Drop Warnings
        glut_query = """
        SELECT m.name as market_name, ph.crop, ph.arrival_quantity
        FROM price_history ph
        JOIN markets m ON ph.market_id = m.id
        WHERE ph.date = (SELECT MAX(date) FROM price_history)
        """
        glut_params = []
        if crop:
            glut_query += " AND ph.crop = ?"
            glut_params.append(crop.strip().title())

        glut_rows = conn.execute(glut_query, glut_params).fetchall()
        for gr in glut_rows:
            avg_arr_row = conn.execute(
                """
                SELECT ROUND(AVG(arrival_quantity), 1) as mean_arr
                FROM price_history ph
                JOIN markets m ON ph.market_id = m.id
                WHERE m.name = ? AND ph.crop = ?
                """,
                (gr["market_name"], gr["crop"]),
            ).fetchone()

            if avg_arr_row and avg_arr_row["mean_arr"]:
                mean_arr = avg_arr_row["mean_arr"]
                if gr["arrival_quantity"] > mean_arr * 1.30:
                    alerts.append(
                        SmartAlert(
                            id=f"alert-glut-{gr['market_name']}-{gr['crop']}",
                            type="DEMAND_WARNING",
                            title=f"Supply Influx: {gr['market_name']}",
                            message=(
                                f"Heavy arrivals of {gr['crop']} ({int(gr['arrival_quantity'])} qtl vs "
                                f"avg {int(mean_arr)} qtl). Expect price softening in coming sessions."
                            ),
                            crop=gr["crop"],
                            severity="warning",
                            timestamp=now_str,
                        )
                    )

        return [vars(a) for a in alerts]
