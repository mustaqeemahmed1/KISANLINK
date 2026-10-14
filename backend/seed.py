"""
seed.py -- Complete database seeder for KisanLink AI (Phase 1).

What it does:
  1. Creates all 8 tables and indexes (calls db.create_tables -- idempotent).
  2. Seeds 5 Maharashtra APMC markets.
  3. Seeds historical multi-crop price & arrival data (Tomato, Onion, Potato, Soybean, Wheat).
  4. Seeds sample registered farmers.
  5. Seeds verified wholesale buyers and active buyer requirements (Buyer Marketplace).
  6. Seeds crowdsourced farmer price reports with validation flags and confidence scores.
  7. Seeds a sample produce submission and computed net-return recommendation records.
  8. Prints a comprehensive verification report.

Run from repo root:
    py backend/seed.py
"""

import csv
import sqlite3
import sys
from pathlib import Path

# Ensure backend directory is importable
sys.path.insert(0, str(Path(__file__).parent))
from db import DB_PATH, create_tables, get_connection

REAL_CSV_PATH = Path(__file__).parent.parent / "data" / "agmarknet_real_prices.csv"
CSV_PATH = REAL_CSV_PATH if REAL_CSV_PATH.exists() else (Path(__file__).parent.parent / "data" / "sample_prices.csv")

# ---------------------------------------------------------------------------
# 1. Market Seeds
# ---------------------------------------------------------------------------
MARKETS = [
    {"name": "Nashik APMC",        "lat": 20.0059, "lng": 73.7797, "region": "Nashik"},
    {"name": "Pune Market A",      "lat": 18.5204, "lng": 73.8567, "region": "Pune"},
    {"name": "Aurangabad Market B","lat": 19.8762, "lng": 75.3433, "region": "Aurangabad"},
    {"name": "Nagpur Market C",    "lat": 21.1458, "lng": 79.0882, "region": "Nagpur"},
    {"name": "Solapur Market D",   "lat": 17.6868, "lng": 75.9064, "region": "Solapur"},
]

# ---------------------------------------------------------------------------
# 2. Farmer Seeds
# ---------------------------------------------------------------------------
FARMERS = [
    {"name": "Ramesh Patil",   "mobile_number": "9876543210", "location": "Pune",       "lat": 18.5204, "lng": 73.8567},
    {"name": "Suresh Jadhav",  "mobile_number": "9822012345", "location": "Nashik",     "lat": 20.0059, "lng": 73.7797},
    {"name": "Anil Shinde",    "mobile_number": "9890123456", "location": "Aurangabad", "lat": 19.8762, "lng": 75.3433},
    {"name": "Vikas Deshmukh", "mobile_number": "9765123456", "location": "Nagpur",     "lat": 21.1458, "lng": 79.0882},
    {"name": "Datta Gaikwad",  "mobile_number": "9823123456", "location": "Solapur",    "lat": 17.6868, "lng": 75.9064},
]

# ---------------------------------------------------------------------------
# 3. Buyer Seeds
# ---------------------------------------------------------------------------
BUYERS = [
    {"name": "Sahyadri Agro Processing",     "verified": 1, "location": "Nashik",     "contact": "+91 98220 11223"},
    {"name": "Reliance Fresh Sourcing Hub",  "verified": 1, "location": "Pune",       "contact": "+91 98900 44556"},
    {"name": "Vidarbha Agro Oil Mills",      "verified": 1, "location": "Nagpur",     "contact": "+91 97650 77889"},
    {"name": "Marathwada Food Processors",   "verified": 1, "location": "Aurangabad", "contact": "+91 94220 99001"},
    {"name": "Solapur Flour & Starch Mills", "verified": 1, "location": "Solapur",    "contact": "+91 98230 66778"},
]

# ---------------------------------------------------------------------------
# 4. Buyer Requirement Seeds
# ---------------------------------------------------------------------------
BUYER_REQUIREMENTS = [
    {
        "buyer_name": "Sahyadri Agro Processing",
        "crop": "Tomato",
        "quantity_kg": 5000.0,
        "offered_price": 27.5,
        "location": "Nashik",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Sahyadri Agro Processing",
        "crop": "Onion",
        "quantity_kg": 8000.0,
        "offered_price": 28.0,
        "location": "Nashik",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Reliance Fresh Sourcing Hub",
        "crop": "Tomato",
        "quantity_kg": 3000.0,
        "offered_price": 25.0,
        "location": "Pune",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Reliance Fresh Sourcing Hub",
        "crop": "Potato",
        "quantity_kg": 4000.0,
        "offered_price": 23.5,
        "location": "Pune",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Vidarbha Agro Oil Mills",
        "crop": "Soybean",
        "quantity_kg": 12000.0,
        "offered_price": 53.5,
        "location": "Nagpur",
        "pickup_available": 0,
    },
    {
        "buyer_name": "Marathwada Food Processors",
        "crop": "Wheat",
        "quantity_kg": 6000.0,
        "offered_price": 31.0,
        "location": "Aurangabad",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Marathwada Food Processors",
        "crop": "Onion",
        "quantity_kg": 4000.0,
        "offered_price": 32.0,
        "location": "Aurangabad",
        "pickup_available": 1,
    },
    {
        "buyer_name": "Solapur Flour & Starch Mills",
        "crop": "Wheat",
        "quantity_kg": 5000.0,
        "offered_price": 29.5,
        "location": "Solapur",
        "pickup_available": 1,
    },
]


def seed_markets(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert markets; return {name: id} mapping."""
    market_ids: dict[str, int] = {}
    for m in MARKETS:
        cur = conn.execute(
            """
            INSERT INTO markets (name, lat, lng, region)
            VALUES (:name, :lat, :lng, :region)
            ON CONFLICT(name) DO UPDATE SET
                lat    = excluded.lat,
                lng    = excluded.lng,
                region = excluded.region
            RETURNING id
            """,
            m,
        )
        market_ids[m["name"]] = cur.fetchone()["id"]
    return market_ids


def seed_price_history(conn: sqlite3.Connection, market_ids: dict[str, int]) -> int:
    """Insert multi-crop price_history rows from the CSV."""
    rows_inserted = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            market_name = row["market"].strip()
            if market_name not in market_ids:
                print(f"  [WARN] Unknown market in CSV: '{market_name}' -- skipping")
                continue
            source = row.get("source", "govt_agmarknet_ogd")
            confidence = float(row.get("confidence_score", 0.96))
            conn.execute(
                """
                INSERT INTO price_history
                    (market_id, crop, date, min_price, max_price,
                     modal_price, arrival_quantity, source, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_id, crop, date) DO UPDATE SET
                    min_price        = excluded.min_price,
                    max_price        = excluded.max_price,
                    modal_price      = excluded.modal_price,
                    arrival_quantity = excluded.arrival_quantity,
                    source           = excluded.source,
                    confidence_score = excluded.confidence_score
                """,
                (
                    market_ids[market_name],
                    row["crop"].strip(),
                    row["date"].strip(),
                    float(row["min_price"]),
                    float(row["max_price"]),
                    float(row["modal_price"]),
                    float(row["arrival_quantity"]),
                    source,
                    confidence,
                ),
            )
            rows_inserted += 1
    return rows_inserted


def seed_farmers(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert seed farmers; return {mobile_number: id} mapping."""
    farmer_ids: dict[str, int] = {}
    for f in FARMERS:
        cur = conn.execute(
            """
            INSERT INTO farmers (name, mobile_number, location, lat, lng)
            VALUES (:name, :mobile_number, :location, :lat, :lng)
            ON CONFLICT(mobile_number) DO UPDATE SET
                name     = excluded.name,
                location = excluded.location,
                lat      = excluded.lat,
                lng      = excluded.lng
            RETURNING id
            """,
            f,
        )
        farmer_ids[f["mobile_number"]] = cur.fetchone()["id"]
    return farmer_ids


def seed_buyers(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert seed buyers and buyer requirements."""
    buyer_ids: dict[str, int] = {}
    for b in BUYERS:
        existing = conn.execute("SELECT id FROM buyers WHERE name = ?", (b["name"],)).fetchone()
        if existing:
            buyer_ids[b["name"]] = existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
        else:
            cur = conn.execute(
                """
                INSERT INTO buyers (name, verified, location, contact)
                VALUES (:name, :verified, :location, :contact)
                """,
                b,
            )
            buyer_ids[b["name"]] = cur.lastrowid

    # Seed buyer requirements
    for req in BUYER_REQUIREMENTS:
        b_id = buyer_ids.get(req["buyer_name"])
        if b_id:
            conn.execute(
                """
                INSERT INTO buyer_requirements
                    (buyer_id, crop, quantity_kg, offered_price, location, pickup_available)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    b_id,
                    req["crop"],
                    req["quantity_kg"],
                    req["offered_price"],
                    req["location"],
                    req["pickup_available"],
                ),
            )
    return buyer_ids


def seed_farmer_reports(
    conn: sqlite3.Connection,
    farmer_ids: dict[str, int],
    market_ids: dict[str, int],
) -> int:
    """Seed sample crowdsourced farmer mandi reports."""
    pune_fid = farmer_ids.get("9876543210")
    nashik_fid = farmer_ids.get("9822012345")
    pune_mid = market_ids.get("Pune Market A")
    nashik_mid = market_ids.get("Nashik APMC")

    reports = [
        (pune_fid, "Tomato", pune_mid, 22.5, "2026-08-25", 1, 0.85),
        (nashik_fid, "Onion", nashik_mid, 27.0, "2026-08-25", 1, 0.90),
    ]

    for r in reports:
        conn.execute(
            """
            INSERT INTO farmer_reports
                (farmer_id, crop, market_id, reported_price, date, validated, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            r,
        )
    return len(reports)


def seed_sample_submission_and_recommendation(
    conn: sqlite3.Connection,
    farmer_ids: dict[str, int],
    market_ids: dict[str, int],
) -> None:
    """Insert a sample produce submission and computed recommendation result."""
    pune_fid = farmer_ids.get("9876543210")
    if not pune_fid:
        return

    cur = conn.execute(
        """
        INSERT INTO produce_submissions
            (farmer_id, crop, quantity_kg, location, harvest_date, quality_grade, vehicle_type)
        VALUES (?, 'Tomato', 500.0, 'Pune', '2026-08-25', 'Grade A', 'mini_truck')
        RETURNING id
        """,
        (pune_fid,),
    )
    sub_id = cur.fetchone()["id"]

    # Sample ranked recommendation (Pune Market A as 1st for Pune farmer)
    mid = market_ids.get("Pune Market A")
    if mid:
        conn.execute(
            """
            INSERT INTO recommendations
                (produce_submission_id, market_id, expected_revenue, transport_cost,
                 expected_net_return, price_trend, demand_level, confidence, rank)
            VALUES (?, ?, 11000.0, 846.0, 9404.0, 'up', 'High', 0.85, 1)
            """,
            (sub_id, mid),
        )


def verify(conn: sqlite3.Connection) -> None:
    """Print comprehensive summary of seeded database state."""
    print("\n" + "=" * 60)
    print("KISANLINK AI -- PHASE 1 DATABASE VERIFICATION")
    print("=" * 60)

    tables = [
        "markets",
        "price_history",
        "farmers",
        "buyers",
        "buyer_requirements",
        "farmer_reports",
        "produce_submissions",
        "recommendations",
    ]

    for tbl in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  * {tbl:22}: {count:4} rows")

    print("\n[+] Crops in price_history:")
    crops = conn.execute(
        """
        SELECT crop, COUNT(*) as rows,
               ROUND(MIN(modal_price), 1) as min_p,
               ROUND(MAX(modal_price), 1) as max_p,
               ROUND(AVG(modal_price), 1) as avg_p
        FROM price_history
        GROUP BY crop
        ORDER BY crop
        """
    ).fetchall()

    for c in crops:
        print(
            f"    - {c['crop']:10}: {c['rows']:3} records | "
            f"Price: Rs.{c['min_p']:.1f} - Rs.{c['max_p']:.1f} (avg Rs.{c['avg_p']:.1f}/kg)"
        )

    print("\n[+] Active Buyer Requirements:")
    reqs = conn.execute(
        """
        SELECT b.name, br.crop, br.quantity_kg, br.offered_price, br.location, br.pickup_available
        FROM buyer_requirements br
        JOIN buyers b ON br.buyer_id = b.id
        ORDER BY br.id
        """
    ).fetchall()
    for r in reqs:
        pickup = "Pickup Available" if r["pickup_available"] else "Drop-off Required"
        print(
            f"    - {r['name']} ({r['location']}): "
            f"{r['quantity_kg']}kg {r['crop']} @ Rs.{r['offered_price']}/kg [{pickup}]"
        )

    print("=" * 60 + "\n")


def main() -> None:
    create_tables()
    with get_connection() as conn:
        # Clear existing transient tables for clean idempotent re-seed
        conn.execute("DELETE FROM recommendations")
        conn.execute("DELETE FROM produce_submissions")
        conn.execute("DELETE FROM farmer_reports")
        conn.execute("DELETE FROM buyer_requirements")
        conn.execute("DELETE FROM buyers")
        conn.execute("DELETE FROM price_history")

        market_ids = seed_markets(conn)
        n_prices = seed_price_history(conn, market_ids)
        farmer_ids = seed_farmers(conn)
        seed_buyers(conn)
        seed_farmer_reports(conn, farmer_ids, market_ids)
        seed_sample_submission_and_recommendation(conn, farmer_ids, market_ids)

        verify(conn)


seed_database = main

if __name__ == "__main__":
    main()
