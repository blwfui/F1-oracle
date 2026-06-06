"""Import practice sessions, sprint qualifying, and qualifying data for a given year.
Usage: python scripts/import_sessions.py <year> [fp|sq|q|all]

Replaces import_2018.py ~ import_2024_fp.py.
2025 has its own self-check loop (import_2025.py).
"""

import sys
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "f1_oracle.db"

FP_TYPES = ("FP1", "FP2", "FP3")


def _connect():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _get_sprint_rounds(year):
    """Detect sprint rounds from the events table."""
    db = _connect()
    rows = db.execute(
        "SELECT DISTINCT round FROM sprint_points WHERE year=?", (year,)
    ).fetchall()
    db.close()
    if rows:
        return {r[0] for r in rows}
    # Fallback: known sprint rounds by year
    fallback = {
        2021: {10, 12, 19},
        2022: {4, 11, 21},
        2023: {4, 9, 12, 17, 18, 20},
        2024: {5, 6, 11, 19, 21, 23},
    }
    return fallback.get(year, set())


# ── Practice Sessions ──────────────────────────────────────────────

def import_practice(year):
    import fastf1
    fastf1.Cache.enable_cache(str(ROOT / "data" / "cache"))
    from src.etl.ingest import ingest_session

    db = _connect()
    max_round = db.execute(
        "SELECT MAX(round) FROM events WHERE year=? AND round>0", (year,)
    ).fetchone()[0]
    if not max_round:
        print(f"No rounds found for {year}")
        db.close()
        return
    print(f"{year}: {max_round} rounds (R1-R{max_round})")
    total = 0

    for rn in range(1, max_round + 1):
        for st in FP_TYPES:
            print(f"  R{rn} {st} ...", end=" ", flush=True)
            try:
                ingest_session(db, year, rn, st)
                total += 1
            except Exception as e:
                print(f"FAIL: {e}")
            time.sleep(0.3)

    db.close()
    print(f"\nPractice import done. {total} sessions processed.")


# ── Sprint Qualifying SQ ───────────────────────────────────────────

def import_sq(year):
    import fastf1
    import pandas as pd
    fastf1.Cache.enable_cache(str(ROOT / "data" / "cache"))

    sprint_rounds = _get_sprint_rounds(year)
    if not sprint_rounds:
        print(f"No sprint rounds found for {year}, skipping SQ")
        return

    db = _connect()
    total = 0

    for rn in sorted(sprint_rounds):
        print(f"  R{rn} SQ ...", end=" ", flush=True)
        try:
            # 2023 uses "SS" (Sprint Shootout), 2024+ uses "SQ"
            session_type = "SS" if year == 2023 else "SQ"
            s = fastf1.get_session(year, rn, session_type)
            s.load(telemetry=False, laps=True, weather=False, messages=True)
            res = s.results
            if res is None or res.empty:
                print("no results, skip")
                continue

            updated = 0
            for _, r in res.iterrows():
                drv = str(r.get("Abbreviation", ""))
                if not drv:
                    continue
                pval = r.get("Position")
                if pd.isna(pval):
                    continue
                pos = int(float(pval))
                db.execute(
                    "INSERT INTO sprint_points (year, round, driver, position, points, sq_pos)"
                    " VALUES (?,?,?,NULL,NULL,?)"
                    " ON CONFLICT(year, round, driver)"
                    " DO UPDATE SET sq_pos=excluded.sq_pos",
                    (year, rn, drv),
                )
                updated += 1
            db.commit()
            print(f"{updated} drivers OK")
            total += updated
        except Exception as e:
            print(f"FAIL: {e}")
        time.sleep(0.5)

    db.close()
    print(f"\nSQ import done. {total} entries updated.")


# ── Qualifying Q1/Q2/Q3 from Jolpi API ─────────────────────────────

def import_qualifying(year):
    import requests

    db = _connect()
    max_round = db.execute(
        "SELECT MAX(round) FROM events WHERE year=? AND round>0", (year,)
    ).fetchone()[0]
    if not max_round:
        print(f"No rounds found for {year}")
        db.close()
        return
    total = 0

    def _qtime_to_sec(t):
        if not t:
            return None
        try:
            parts = str(t).split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except Exception:
            pass
        return None

    for rn in range(1, max_round + 1):
        print(f"  Q{rn} ...", end=" ", flush=True)
        try:
            url = f"https://api.jolpi.ca/ergast/f1/{year}/{rn}/qualifying.json"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                print(f"HTTP {r.status_code}")
                continue
            data = r.json()
            races = data["MRData"]["RaceTable"]["Races"]
            if not races:
                print("no data, skip")
                continue

            results = races[0].get("QualifyingResults", [])
            if not results:
                print("no qualifying results, skip")
                continue

            for res in results:
                drv = res["Driver"]["code"]
                db.execute(
                    "UPDATE results SET q1_sec=?, q2_sec=?, q3_sec=?, quali_pos=?"
                    " WHERE year=? AND round=? AND driver COLLATE NOCASE=?",
                    (
                        _qtime_to_sec(res.get("Q1")),
                        _qtime_to_sec(res.get("Q2")),
                        _qtime_to_sec(res.get("Q3")),
                        int(res["position"]),
                        year, rn, drv,
                    ),
                )
            db.commit()
            print(f"{len(results)} drivers OK")
            total += len(results)
        except Exception as e:
            print(f"FAIL: {e}")
        time.sleep(0.3)

    db.close()
    print(f"\nQualifying import done. {total} entries updated.")


# ── Stats ───────────────────────────────────────────────────────────

def show_stats(year):
    db = _connect()
    fp = db.execute(
        "SELECT session_type, COUNT(DISTINCT round) FROM sessions WHERE year=? GROUP BY session_type",
        (year,),
    ).fetchall()
    print(f"\n=== {year} sessions (practice) ===")
    for st, cnt in fp:
        print(f"  {st}: {cnt} rounds")

    sq = db.execute(
        "SELECT COUNT(*) FROM sprint_points WHERE year=? AND sq_pos IS NOT NULL", (year,)
    ).fetchone()[0]
    sp_total = db.execute(
        "SELECT COUNT(*) FROM sprint_points WHERE year=?", (year,)
    ).fetchone()[0]
    if sp_total > 0:
        print(f"\n=== {year} sprint_points ===")
        print(f"  sq_pos: {sq}/{sp_total}")

    q = db.execute(
        "SELECT COUNT(*) FROM results WHERE year=? AND q1_sec IS NOT NULL", (year,)
    ).fetchone()[0]
    q2 = db.execute(
        "SELECT COUNT(*) FROM results WHERE year=? AND q2_sec IS NOT NULL", (year,)
    ).fetchone()[0]
    q3 = db.execute(
        "SELECT COUNT(*) FROM results WHERE year=? AND q3_sec IS NOT NULL", (year,)
    ).fetchone()[0]
    r_total = db.execute(
        "SELECT COUNT(*) FROM results WHERE year=?", (year,)
    ).fetchone()[0]
    print(f"\n=== {year} qualifying ===")
    print(f"  Q1: {q}/{r_total}, Q2: {q2}/{r_total}, Q3: {q3}/{r_total}")
    db.close()


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_sessions.py <year> [fp|sq|q|all]")
        print("  year: 2018-2024")
        print("  step: fp (practice), sq (sprint qualifying), q (qualifying), all (default)")
        sys.exit(1)

    year = int(sys.argv[1])
    step = sys.argv[2] if len(sys.argv) > 2 else "all"

    if year < 2018 or year > 2024:
        print(f"Year {year} out of range. Use 2018-2024 (2025 has its own script).")
        sys.exit(1)

    has_sprint = year >= 2021

    if step in ("all", "fp"):
        print("=" * 40)
        print(f"STEP 1: {year} Practice Sessions (FP1/FP2/FP3)")
        print("=" * 40)
        import_practice(year)

    if has_sprint and step in ("all", "sq"):
        print("\n" + "=" * 40)
        print(f"STEP 2: {year} Sprint Qualifying (SQ)")
        print("=" * 40)
        import_sq(year)

    if step in ("all", "q"):
        print("\n" + "=" * 40)
        print(f"STEP 3: {year} Qualifying Q1/Q2/Q3 (Jolpi API)")
        print("=" * 40)
        import_qualifying(year)

    show_stats(year)
    print("\nDONE")
