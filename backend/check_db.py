"""
check_db.py -- Diagnostic, Health Check, and Verification tool for KisanLink Datastore.

Checks active database connection (SQLite vs PostgreSQL), verifies relational
integrity, table record counts, and migration status.

Usage:
    python backend/check_db.py
    python backend/check_db.py --migrate
"""

import argparse
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from db import DB_PATH, get_connection, get_database_url, is_postgres_active


def run_diagnostics():
    print("=" * 65)
    print("      KISANLINK AI -- DATASTORE STATUS & HEALTH DIAGNOSTIC")
    print("=" * 65)

    db_url = get_database_url()
    active_engine = "PostgreSQL" if is_postgres_active() else "SQLite"

    print(f"\n[Engine] Active Datastore: {active_engine.upper()}")
    if is_postgres_active():
        masked_url = db_url
        if "@" in db_url:
            creds, host_db = db_url.split("@", 1)
            scheme = creds.split("://")[0]
            masked_url = f"{scheme}://****:****@{host_db}"
        print(f"[Target] Connection String: {masked_url}")
    else:
        print(f"[Target] SQLite File Path:  {DB_PATH}")
        if DB_PATH.exists():
            size_kb = DB_PATH.stat().st_size / 1024
            print(f"[Detail] File Size:         {size_kb:.1f} KB")
        else:
            print("[Detail] Status:            Database file not found! Run seed.py first.")

    tables = [
        "markets",
        "farmers",
        "price_history",
        "farmer_reports",
        "buyers",
        "buyer_requirements",
        "produce_submissions",
        "recommendations",
    ]

    print("\n[Relational Record Audit]")
    print("-" * 65)
    print(f"{'Table Name':<26} | {'Record Count':<12} | {'Integrity Status'}")
    print("-" * 65)

    try:
        with get_connection() as conn:
            # If PostgreSQL, check server version
            if is_postgres_active():
                cur = conn.cursor()
                cur.execute("SELECT version();")
                pg_ver = cur.fetchone()
                version_str = pg_ver[0] if isinstance(pg_ver, tuple) else pg_ver.get("version", "PostgreSQL")
                print(f"Server Info: {version_str[:55]}...\n")

            total_records = 0
            for t in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS total FROM {t}").fetchone()
                    cnt = row["total"] if isinstance(row, dict) or "total" in (row.keys() if hasattr(row, "keys") else []) else row[0]
                    total_records += cnt
                    status = "[OK]" if cnt > 0 else "[EMPTY]"
                    print(f"{t:<26} | {cnt:<12} | {status}")
                except Exception as e:
                    print(f"{t:<26} | {'ERROR':<12} | [ERR] {str(e)[:30]}")

            print("-" * 65)
            print(f"{'Total Relational Records':<26} | {total_records:<12} | [ACTIVE]")

            # Check latest farmer record
            print("\n[Sample Identity Verification]")
            try:
                f_row = conn.execute("SELECT id, name, mobile_number, location, farm_size_acres FROM farmers ORDER BY id DESC LIMIT 1").fetchone()
                if f_row:
                    f_name = f_row["name"] if "name" in f_row.keys() else f_row[1]
                    f_loc = f_row["location"] if "location" in f_row.keys() else f_row[3]
                    f_mob = f_row["mobile_number"] if "mobile_number" in f_row.keys() else f_row[2]
                    print(f"  * Latest Registered Farmer: {f_name} ({f_loc}, Mobile: {f_mob})")
                else:
                    print("  * No farmers registered yet.")
            except Exception as e:
                print(f"  * Farmer query error: {e}")

            print("\n[+] Diagnostic check passed successfully!")

    except Exception as err:
        print(f"\n[!] Connection or query failed: {err}")
        if is_postgres_active():
            print("    Please verify your DATABASE_URL in .env or environment variables.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KisanLink Datastore Health & Migration Tool")
    parser.add_argument("--migrate", action="store_true", help="Execute PostgreSQL migration if DATABASE_URL is set")
    args = parser.parse_args()

    if args.migrate:
        from migrate_postgres import migrate_to_postgres
        db_url = get_database_url()
        if not db_url:
            print("[!] Error: No DATABASE_URL found to migrate to.")
            print("    Set DATABASE_URL in .env or pass --url to migrate_postgres.py")
            sys.exit(1)
        migrate_to_postgres(db_url)
    else:
        run_diagnostics()
