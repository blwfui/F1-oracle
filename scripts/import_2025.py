"""Import 2025 practice + qualifying data with self-check retry loop.
Usage: python scripts/import_2025.py"""

import logging
import queue
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
LOG_PATH = ROOT / "data" / "import_2025.log"

sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("import_2025")

TARGET_YEAR = 2025
CHECK_INTERVAL = 1800
ALL_ROUNDS = None
FP_TYPES = ("FP1", "FP2", "FP3")


def _connect():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    return db


# ── completeness checks ────────────────────────────────────────────


def check_practice(db):
    rows = db.execute(
        f"SELECT DISTINCT round FROM sessions WHERE year={TARGET_YEAR}"
    ).fetchall()
    return {r[0] for r in rows}


def check_quali(db):
    rows = db.execute(
        f"SELECT DISTINCT round FROM results WHERE year={TARGET_YEAR} AND q1_sec IS NOT NULL"
    ).fetchall()
    return {r[0] for r in rows}


def report_practice_detail(db):
    rows = db.execute(
        f"""SELECT round, session_type, COUNT(*) as drivers
            FROM sessions WHERE year={TARGET_YEAR}
            GROUP BY round, session_type ORDER BY round, session_type"""
    ).fetchall()
    for r in rows:
        log.info(f"  R{r[0]:>2} {r[1]:<4} {r[2]} drivers")
    done = {r[0] for r in rows}
    missing = ALL_ROUNDS - done
    if missing:
        log.warning(f"  Missing rounds: {sorted(missing)}")
    return missing


def report_quali_detail(db):
    rows = db.execute(
        f"""SELECT round, COUNT(*) as drivers
            FROM results WHERE year={TARGET_YEAR} AND q1_sec IS NOT NULL
            GROUP BY round ORDER BY round"""
    ).fetchall()
    for r in rows:
        log.info(f"  R{r[0]:>2} {r[1]} drivers with Q1")
    done = {r[0] for r in rows}
    missing = ALL_ROUNDS - done
    if missing:
        log.warning(f"  Missing rounds: {sorted(missing)}")
    return missing


# ── importers ───────────────────────────────────────────────────────


def import_fp_rounds(db, rounds):
    import fastf1
    fastf1.Cache.enable_cache(str(ROOT / "data" / "cache"))
    from src.etl.ingest import ingest_session

    def _run_one(rn, st):
        result = []
        def worker():
            local_db = _connect()
            try:
                ingest_session(local_db, TARGET_YEAR, rn, st)
                result.append("ok")
            except Exception as e:
                result.append(e)
            finally:
                local_db.close()
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=120)
        if t.is_alive():
            log.warning("  R%d %s TIMEOUT 120s, skipped", rn, st)
            return False
        if result and isinstance(result[0], Exception):
            log.warning("  R%d %s FAIL: %s", rn, st, result[0])
            return False
        log.info("  R%d %s OK", rn, st)
        return True

    for rn in sorted(rounds):
        for st in FP_TYPES:
            _run_one(rn, st)
            time.sleep(0.5)


def import_q_rounds(db, rounds):
    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_official
    fetch_official.YEAR = TARGET_YEAR
    for rn in sorted(rounds):
        try:
            results = fetch_official.fetch_qualifying_results(rn)
            if not results:
                log.warning("  R%d Q: no data from API", rn)
                continue
            for res in results:
                db.execute(
                    "UPDATE results SET q1_sec=?, q2_sec=?, q3_sec=?, quali_pos=?"
                    " WHERE year=? AND round=? AND driver COLLATE NOCASE=?",
                    (res["q1_sec"], res["q2_sec"], res["q3_sec"], res["position"],
                     TARGET_YEAR, rn, res["driver"]),
                )
            db.commit()
            log.info("  R%d Q OK (%d drivers)", rn, len(results))
        except Exception as e:
            log.warning("  R%d Q FAIL: %s", rn, e)
        time.sleep(0.5)


# ── main loop ───────────────────────────────────────────────────────


def main():
    log.info("=" * 50)
    log.info("2025 Import Loop Started")
    log.info("=" * 50)

    db = _connect()
    max_rn = db.execute("SELECT MAX(round) FROM events WHERE year=? AND round>0", (TARGET_YEAR,)).fetchone()[0]
    if not max_rn:
        log.error("No rounds found for %d", TARGET_YEAR)
        db.close()
        return
    global ALL_ROUNDS
    ALL_ROUNDS = set(range(1, max_rn + 1))
    TOTAL_ROUNDS = len(ALL_ROUNDS)
    log.info("Season %d: %d rounds (R1-R%d)", TARGET_YEAR, TOTAL_ROUNDS, max_rn)

    for iteration in range(1, 9999):
        log.info("─── Iteration %d ───", iteration)

        # Check + import practice
        fp_done_before = check_practice(db)
        fp_missing = ALL_ROUNDS - fp_done_before
        if fp_missing:
            log.warning("Practice missing: %s", sorted(fp_missing))
            import_fp_rounds(db, fp_missing)
            fp_done_after = check_practice(db)
            fp_still_missing = ALL_ROUNDS - fp_done_after
            if fp_still_missing:
                log.warning("Practice STILL missing after retry: %s", sorted(fp_still_missing))
            else:
                log.info("Practice: ALL %d rounds imported", TOTAL_ROUNDS)
        else:
            log.info("Practice: ALL %d rounds OK", TOTAL_ROUNDS)

        # Check + import qualifying
        q_done_before = check_quali(db)
        q_missing = ALL_ROUNDS - q_done_before
        if q_missing:
            log.warning("Qualifying missing: %s", sorted(q_missing))
            import_q_rounds(db, q_missing)
            q_done_after = check_quali(db)
            q_still_missing = ALL_ROUNDS - q_done_after
            if q_still_missing:
                log.warning("Qualifying STILL missing after retry: %s", sorted(q_still_missing))
            else:
                log.info("Qualifying: ALL %d rounds imported", TOTAL_ROUNDS)
        else:
            log.info("Qualifying: ALL %d rounds OK", TOTAL_ROUNDS)

        # Final verdict
        fp_final = ALL_ROUNDS - check_practice(db)
        q_final = ALL_ROUNDS - check_quali(db)

        if not fp_final and not q_final:
            log.info("=" * 50)
            log.info("ALL COMPLETE — Practice: OK, Qualifying: OK")
            log.info("=" * 50)
            break

        # Detail report
        log.info("─── Status after iteration %d ───", iteration)
        report_practice_detail(db)
        report_quali_detail(db)

        log.info("Waiting %ds before retry #%d ...", CHECK_INTERVAL, iteration + 1)
        time.sleep(CHECK_INTERVAL)

    db.close()
    log.info("DONE")


if __name__ == "__main__":
    main()
