"""
db.py -- SQLite schema for KisanLink (Full MVP Architecture).

Tables follow TRD.md section 2 column names exactly so this can be migrated
to PostgreSQL later without changing any caller code.

Tables:
  - farmers             (id, name, mobile_number, location, lat, lng, created_at)
  - markets             (id, name, lat, lng, region)
  - price_history       (id, market_id, crop, date, min_price, max_price,
                         modal_price, arrival_quantity, source, confidence_score)
  - farmer_reports      (id, farmer_id, crop, market_id, reported_price, date,
                         validated, confidence_score)
  - buyers              (id, name, verified, location, contact)
  - buyer_requirements  (id, buyer_id, crop, quantity_kg, offered_price, location,
                         pickup_available, posted_at)
  - produce_submissions (id, farmer_id, crop, quantity_kg, location, harvest_date,
                         quality_grade, vehicle_type, submitted_at)
  - recommendations     (id, produce_submission_id, market_id, expected_revenue,
                         transport_cost, expected_net_return, price_trend,
                         demand_level, confidence, rank, created_at)
"""

import os
import sqlite3
from pathlib import Path

# Resolve relative to this file so the script works from any working directory.
DB_PATH = Path(__file__).parent / "kisanlink.db"


def load_env_file() -> None:
    """Load key-value pairs from .env file into os.environ if not already set."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


load_env_file()


def get_database_url() -> str | None:
    """Return configured PostgreSQL URL or None."""
    load_env_file()
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def is_postgres_active() -> bool:
    """Check if PostgreSQL engine is configured and active."""
    return bool(get_database_url() and HAS_PSYCOPG2)


class PostgresCursorWrapper:
    """Wraps psycopg2 cursor to provide SQLite-compatible lastrowid and methods."""

    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresConnectionWrapper:
    """
    Wraps psycopg2 connection to ensure complete query-level compatibility with SQLite:
      1. Translates '?' parameter placeholders to '%s'
      2. Appends 'RETURNING id' on INSERT statements to emulate cursor.lastrowid
      3. Provides conn.execute(...) directly on connection object
      4. Implements standard transaction context management
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        pg_sql = sql.replace("?", "%s")
        trimmed = pg_sql.strip()
        is_insert = trimmed.upper().startswith("INSERT INTO") and "RETURNING" not in trimmed.upper()

        if is_insert:
            pg_sql = trimmed.rstrip().rstrip(";") + " RETURNING id;"

        cur.execute(pg_sql, params or ())
        lastrowid = None

        if is_insert:
            try:
                ret = cur.fetchone()
                if ret:
                    lastrowid = ret["id"] if isinstance(ret, dict) or hasattr(ret, "__getitem__") else ret[0]
            except Exception:
                pass

        return PostgresCursorWrapper(cur, lastrowid=lastrowid)

    def executescript(self, sql_script: str):
        with self._conn.cursor() as cur:
            cur.execute(sql_script)
        self._conn.commit()

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection():
    """
    Return a database connection with column-name access.
    Connects to PostgreSQL if DATABASE_URL or POSTGRES_URL is set,
    otherwise connects to local SQLite datastore (TRD.md §6 & ADR-006).
    """
    db_url = get_database_url()
    if db_url and HAS_PSYCOPG2:
        raw_pg = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return PostgresConnectionWrapper(raw_pg)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables() -> None:
    """Create schema tables and indexes (idempotent -- safe to re-run on existing DB)."""
    ddl = """
    -- 1. Farmers
    CREATE TABLE IF NOT EXISTS farmers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        mobile_number   TEXT    NOT NULL UNIQUE,
        password_hash   TEXT,
        location        TEXT    NOT NULL,
        lat             REAL,
        lng             REAL,
        profile_pic     TEXT,
        farm_size_acres REAL    DEFAULT 5.0,
        upi_id          TEXT,
        bio             TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    -- 2. Markets (APMCs)
    CREATE TABLE IF NOT EXISTS markets (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT    NOT NULL UNIQUE,
        lat     REAL,
        lng     REAL,
        region  TEXT
    );

    -- 3. Price History (Official & Historical Data)
    CREATE TABLE IF NOT EXISTS price_history (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        market_id        INTEGER NOT NULL REFERENCES markets(id),
        crop             TEXT    NOT NULL,
        date             TEXT    NOT NULL,
        min_price        REAL    NOT NULL,
        max_price        REAL    NOT NULL,
        modal_price      REAL    NOT NULL,
        arrival_quantity REAL    NOT NULL,
        source           TEXT    NOT NULL DEFAULT 'govt',
        confidence_score REAL    NOT NULL DEFAULT 0.9,
        UNIQUE (market_id, crop, date)
    );

    -- 4. Farmer Crowdsourced Price Reports
    CREATE TABLE IF NOT EXISTS farmer_reports (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id        INTEGER REFERENCES farmers(id),
        crop             TEXT    NOT NULL,
        market_id        INTEGER REFERENCES markets(id),
        reported_price   REAL    NOT NULL,
        date             TEXT    NOT NULL,
        validated        INTEGER NOT NULL DEFAULT 0,
        confidence_score REAL    NOT NULL DEFAULT 0.5
    );

    -- 5. Buyers
    CREATE TABLE IF NOT EXISTS buyers (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT    NOT NULL,
        verified  INTEGER NOT NULL DEFAULT 1,
        location  TEXT    NOT NULL,
        contact   TEXT
    );

    -- 6. Buyer Requirements (Buyer Marketplace)
    CREATE TABLE IF NOT EXISTS buyer_requirements (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer_id         INTEGER NOT NULL REFERENCES buyers(id),
        crop             TEXT    NOT NULL,
        quantity_kg      REAL    NOT NULL,
        offered_price    REAL    NOT NULL,
        location         TEXT    NOT NULL,
        pickup_available INTEGER NOT NULL DEFAULT 1,
        posted_at        TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    -- 7. Produce Submissions (Farmer Add Produce)
    CREATE TABLE IF NOT EXISTS produce_submissions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        farmer_id     INTEGER REFERENCES farmers(id),
        crop          TEXT    NOT NULL,
        quantity_kg   REAL    NOT NULL,
        location      TEXT    NOT NULL,
        harvest_date  TEXT,
        quality_grade TEXT    DEFAULT 'Grade A',
        vehicle_type  TEXT    DEFAULT 'mini_truck',
        submitted_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    -- 8. Stored Recommendations
    CREATE TABLE IF NOT EXISTS recommendations (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        produce_submission_id INTEGER REFERENCES produce_submissions(id),
        market_id             INTEGER NOT NULL REFERENCES markets(id),
        expected_revenue      REAL    NOT NULL,
        transport_cost        REAL    NOT NULL,
        expected_net_return   REAL    NOT NULL,
        price_trend           TEXT    NOT NULL,
        demand_level          TEXT    NOT NULL,
        confidence            REAL    NOT NULL,
        rank                  INTEGER NOT NULL,
        created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    -- Performance Indexes
    CREATE INDEX IF NOT EXISTS idx_price_history_lookup ON price_history(market_id, crop, date DESC);
    CREATE INDEX IF NOT EXISTS idx_price_history_crop ON price_history(crop, date DESC);
    CREATE INDEX IF NOT EXISTS idx_buyer_requirements_crop ON buyer_requirements(crop);
    CREATE INDEX IF NOT EXISTS idx_produce_submissions_farmer ON produce_submissions(farmer_id);
    CREATE INDEX IF NOT EXISTS idx_recommendations_submission ON recommendations(produce_submission_id);
    """

    if is_postgres_active():
        from migrate_postgres import POSTGRES_DDL
        with get_connection() as conn:
            conn.executescript(POSTGRES_DDL)
            print("PostgreSQL schema tables and indexes verified successfully.")
        return

    with get_connection() as conn:
        conn.executescript(ddl)
        # Check and add missing columns to farmers table if migrating
        cursor = conn.cursor()
        existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(farmers)").fetchall()]
        new_columns = [
            ("password_hash", "TEXT"),
            ("profile_pic", "TEXT"),
            ("farm_size_acres", "REAL DEFAULT 5.0"),
            ("upi_id", "TEXT"),
            ("bio", "TEXT"),
        ]
        for col_name, col_type in new_columns:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE farmers ADD COLUMN {col_name} {col_type}")
        conn.commit()


if __name__ == "__main__":
    create_tables()
    if is_postgres_active():
        print(f"Connected to PostgreSQL: {get_database_url().split('@')[-1] if '@' in (get_database_url() or '') else 'PostgreSQL'}")
    else:
        print(f"Schema created at local SQLite datastore: {DB_PATH}")

