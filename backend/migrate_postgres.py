"""
migrate_postgres.py -- Database Migration & Initialization tool for PostgreSQL.

Per TRD.md §1 & DECISIONS.md ADR-006:
Initializes the full relational schema in PostgreSQL and migrates all records
from SQLite into PostgreSQL with transactional integrity.

Usage:
    py backend/migrate_postgres.py --url postgresql://user:pass@localhost:5432/kisanlink
    (or set DATABASE_URL environment variable and run: py backend/migrate_postgres.py)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent))
from db import DB_PATH

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


POSTGRES_DDL = """
-- 1. Farmers
CREATE TABLE IF NOT EXISTS farmers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    mobile_number   VARCHAR(32)  NOT NULL UNIQUE,
    password_hash   TEXT,
    location        VARCHAR(128) NOT NULL,
    lat             DOUBLE PRECISION,
    lng             DOUBLE PRECISION,
    profile_pic     TEXT,
    farm_size_acres DOUBLE PRECISION DEFAULT 5.0,
    upi_id          VARCHAR(128),
    bio             TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Markets (APMCs)
CREATE TABLE IF NOT EXISTS markets (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(255) NOT NULL UNIQUE,
    lat     DOUBLE PRECISION,
    lng     DOUBLE PRECISION,
    region  VARCHAR(128)
);

-- 3. Price History (Official & Historical Agmarknet Data)
CREATE TABLE IF NOT EXISTS price_history (
    id               SERIAL PRIMARY KEY,
    market_id        INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    crop             VARCHAR(64) NOT NULL,
    date             DATE NOT NULL,
    min_price        DOUBLE PRECISION NOT NULL,
    max_price        DOUBLE PRECISION NOT NULL,
    modal_price      DOUBLE PRECISION NOT NULL,
    arrival_quantity DOUBLE PRECISION NOT NULL,
    source           VARCHAR(64) NOT NULL DEFAULT 'agmarknet_api',
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.95,
    UNIQUE (market_id, crop, date)
);

-- 4. Farmer Crowdsourced Price Reports
CREATE TABLE IF NOT EXISTS farmer_reports (
    id               SERIAL PRIMARY KEY,
    farmer_id        INTEGER REFERENCES farmers(id) ON DELETE SET NULL,
    crop             VARCHAR(64) NOT NULL,
    market_id        INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    reported_price   DOUBLE PRECISION NOT NULL,
    date             DATE NOT NULL,
    validated        INTEGER NOT NULL DEFAULT 0,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.5
);

-- 5. Buyers
CREATE TABLE IF NOT EXISTS buyers (
    id        SERIAL PRIMARY KEY,
    name      VARCHAR(255) NOT NULL,
    verified  INTEGER NOT NULL DEFAULT 1,
    location  VARCHAR(128) NOT NULL,
    contact   VARCHAR(128)
);

-- 6. Buyer Requirements (Buyer Marketplace)
CREATE TABLE IF NOT EXISTS buyer_requirements (
    id               SERIAL PRIMARY KEY,
    buyer_id         INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
    crop             VARCHAR(64) NOT NULL,
    quantity_kg      DOUBLE PRECISION NOT NULL,
    offered_price    DOUBLE PRECISION NOT NULL,
    location         VARCHAR(128) NOT NULL,
    pickup_available INTEGER NOT NULL DEFAULT 1,
    posted_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Produce Submissions (Farmer Add Produce)
CREATE TABLE IF NOT EXISTS produce_submissions (
    id            SERIAL PRIMARY KEY,
    farmer_id     INTEGER REFERENCES farmers(id) ON DELETE SET NULL,
    crop          VARCHAR(64) NOT NULL,
    quantity_kg   DOUBLE PRECISION NOT NULL,
    location      VARCHAR(128) NOT NULL,
    harvest_date  DATE,
    quality_grade VARCHAR(64) DEFAULT 'Grade A',
    vehicle_type  VARCHAR(64) DEFAULT 'mini_truck',
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Stored Recommendations
CREATE TABLE IF NOT EXISTS recommendations (
    id                    SERIAL PRIMARY KEY,
    produce_submission_id INTEGER REFERENCES produce_submissions(id) ON DELETE CASCADE,
    market_id             INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    expected_revenue      DOUBLE PRECISION NOT NULL,
    transport_cost        DOUBLE PRECISION NOT NULL,
    expected_net_return   DOUBLE PRECISION NOT NULL,
    price_trend           VARCHAR(32) NOT NULL,
    demand_level          VARCHAR(32) NOT NULL,
    confidence            DOUBLE PRECISION NOT NULL,
    rank                  INTEGER NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_pg_price_history_lookup ON price_history(market_id, crop, date DESC);
CREATE INDEX IF NOT EXISTS idx_pg_price_history_crop ON price_history(crop, date DESC);
CREATE INDEX IF NOT EXISTS idx_pg_buyer_requirements_crop ON buyer_requirements(crop);
CREATE INDEX IF NOT EXISTS idx_pg_produce_submissions_farmer ON produce_submissions(farmer_id);
CREATE INDEX IF NOT EXISTS idx_pg_recommendations_submission ON recommendations(produce_submission_id);
"""


def migrate_to_postgres(pg_url: str) -> None:
    """Migrate tables and copy data from SQLite to PostgreSQL."""
    if not HAS_PSYCOPG2:
        print("[!] Error: psycopg2 is required. Install via: pip install psycopg2-binary")
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"[!] Error: SQLite database not found at {DB_PATH}. Run seed.py first.")
        sys.exit(1)

    print("=" * 60)
    print("KISANLINK AI -- POSTGRESQL MIGRATION PIPELINE")
    print(f"  Source: {DB_PATH}")
    print(f"  Target: {pg_url.split('@')[-1] if '@' in pg_url else 'PostgreSQL'}")
    print("=" * 60)

    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    try:
        pg_conn = psycopg2.connect(pg_url)
        pg_conn.autocommit = False
    except Exception as e:
        print(f"[!] Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    try:
        with pg_conn.cursor() as cur:
            print("\n[1/3] Executing PostgreSQL DDL schema...")
            cur.execute(POSTGRES_DDL)
            print("  ✓ Schema tables and indexes created successfully.")

            tables = [
                ("markets", ["id", "name", "lat", "lng", "region"]),
                ("farmers", ["id", "name", "mobile_number", "password_hash", "location", "lat", "lng", "profile_pic", "farm_size_acres", "upi_id", "bio", "created_at"]),
                ("buyers", ["id", "name", "verified", "location", "contact"]),
                ("buyer_requirements", ["id", "buyer_id", "crop", "quantity_kg", "offered_price", "location", "pickup_available", "posted_at"]),
                ("farmer_reports", ["id", "farmer_id", "crop", "market_id", "reported_price", "date", "validated", "confidence_score"]),
                ("price_history", ["id", "market_id", "crop", "date", "min_price", "max_price", "modal_price", "arrival_quantity", "source", "confidence_score"]),
                ("produce_submissions", ["id", "farmer_id", "crop", "quantity_kg", "location", "harvest_date", "quality_grade", "vehicle_type", "submitted_at"]),
                ("recommendations", ["id", "produce_submission_id", "market_id", "expected_revenue", "transport_cost", "expected_net_return", "price_trend", "demand_level", "confidence", "rank", "created_at"]),
            ]

            print("\n[2/3] Migrating data records...")
            for table_name, columns in tables:
                rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table_name}").fetchall()
                if not rows:
                    continue

                col_names = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                insert_sql = f"""
                    INSERT INTO {table_name} ({col_names})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """
                data = [tuple(r[col] for col in columns) for r in rows]
                cur.executemany(insert_sql, data)

                # Reset sequence for primary key
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE(MAX(id), 1)) FROM {table_name};")
                print(f"  ✓ {table_name:<22}: {len(rows):>4} records transferred.")

            pg_conn.commit()
            print("\n[3/3] Verification:")
            for table_name, _ in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cur.fetchone()[0]
                print(f"  * PostgreSQL {table_name:<20}: {count} rows")

        print("\n[+] PostgreSQL migration completed successfully with full integrity!")

    except Exception as e:
        pg_conn.rollback()
        print(f"\n[!] Migration error (rolled back): {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate KisanLink SQLite database to PostgreSQL.")
    parser.add_argument("--url", help="PostgreSQL connection string (e.g. postgresql://user:pass@localhost:5432/kisanlink)")
    args = parser.parse_args()

    target_url = args.url or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not target_url:
        print("[!] No PostgreSQL connection string provided.")
        print("    Usage: py backend/migrate_postgres.py --url postgresql://user:pass@localhost:5432/kisanlink")
        print("    Or set DATABASE_URL environment variable.")
        sys.exit(1)

    migrate_to_postgres(target_url)
