"""ETL pipeline: FastF1 → SQLite data warehouse."""

import sqlite3
import logging
from pathlib import Path

import fastf1
import pandas as pd

from src.etl.schema import SCHEMA_SQL

F1_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

fastf1.Cache.enable_cache(str(CACHE_DIR))

START_YEAR, END_YEAR = 2018, 2025


def _connect():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=OFF")
    return db


def init_db():
    db = _connect()
    db.executescript(SCHEMA_SQL)
    db.commit()
    db.close()
    log.info("Database initialized at %s", DB_PATH)


def _safe_float(val):
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _timedelta_seconds(td):
    if pd.isna(td):
        return None
    try:
        return td.total_seconds()
    except AttributeError:
        return None


def ingest_events(db, year):
    schedule = fastf1.get_event_schedule(year)
    if schedule is None or schedule.empty:
        log.warning("No schedule for %d", year)
        return 0

    rows = []
    for _, ev in schedule.iterrows():
        if ev.get("EventFormat") == "conference":
            continue
        date = ev.get("EventDate")
        date_str = str(date.date()) if hasattr(date, "date") else str(date)[:10]
        rows.append((
            year, int(ev["RoundNumber"]),
            str(ev.get("EventName", "")),
            str(ev.get("Country", "")),
            str(ev.get("Location", "")),
            date_str,
        ))

    db.executemany(
        "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?)",
        rows,
    )
    db.commit()
    log.info("  Events: %d races", len(rows))
    return len(rows)


def ingest_session(db, year, round_number, session_type):
    try:
        s = fastf1.get_session(year, round_number, session_type)
        s.load(telemetry=False, laps=True, weather=False, messages=False)
    except Exception as e:
        log.warning("  Skip %s R%d: %s", session_type, round_number, e)
        return
    lp = s.laps
    if lp is None or lp.empty:
        log.info("    R%d %s: no laps", round_number, session_type)
        return
    lp_valid = lp.dropna(subset=["LapTime"])
    all_laps_drv = lp.groupby("Driver").size()
    res = s.results
    all_drv = res["Abbreviation"].tolist() if res is not None and not res.empty else lp["Driver"].unique()
    drivers = []
    for drv in all_drv:
        drv_str = str(drv)
        dl = lp_valid.pick_driver(drv_str)
        best = dl["LapTime"].min().total_seconds() if not dl.empty else None
        laps = int(all_laps_drv.get(drv_str, 0))
        drivers.append((drv_str, best, laps))
    drivers.sort(key=lambda x: (0 if x[1] else 1, x[1] or 99999))
    for seq, (drv, best, laps) in enumerate(drivers, 1):
        pos = seq if best else None
        db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?)",
            (year, round_number, drv, session_type, best, laps, pos))
    db.commit()
    n_timed = sum(1 for d in drivers if d[1])
    log.info("    R%d %s: %d drivers (%d timed)", round_number, session_type, len(drivers), n_timed)

    if res is not None and not res.empty:
        name_rows = []
        for _, r in res.iterrows():
            abbr = str(r.get("Abbreviation", ""))
            full = str(r.get("FullName", ""))
            if abbr:
                name_rows.append((abbr, full, year))
        if name_rows:
            db.executemany(
                "INSERT OR IGNORE INTO driver_names VALUES (?,?,?)",
                name_rows,
            )
            db.commit()


def ingest_qualifying(db, year, round_number):
    try:
        session = fastf1.get_session(year, round_number, "Q")
        session.load(telemetry=False, laps=False, weather=False, messages=False)
    except Exception as e:
        log.warning("  Skip Q%d: %s", round_number, e)
        return

    res = session.results
    if res is None or res.empty:
        log.warning("    Q%d: no results", round_number)
        return

    updated = 0
    for _, r in res.iterrows():
        drv = str(r.get("Abbreviation", ""))
        if not drv:
            continue
        q1 = _timedelta_seconds(r.get("Q1"))
        q2 = _timedelta_seconds(r.get("Q2"))
        q3 = _timedelta_seconds(r.get("Q3"))
        quali_pos = _safe_int(r.get("Position"))
        db.execute(
            "UPDATE results SET q1_sec=?, q2_sec=?, q3_sec=?, quali_pos=? WHERE year=? AND round=? AND driver=?",
            (q1, q2, q3, quali_pos, year, round_number, drv),
        )
        updated += 1
    db.commit()
    timed_count = sum(1 for _, r in res.iterrows() if not pd.isna(r.get("Q1")))
    log.info("    Q%d: %d drivers (%d timed)", round_number, updated, timed_count)


def ingest_race(db, year, round_number):
    try:
        session = fastf1.get_session(year, round_number, "R")
        session.load(telemetry=False, laps=True, weather=True, messages=False)
    except Exception as e:
        log.warning("  Skip R%d: %s", round_number, e)
        return

    # --- results (compute positions from laps if API results are NaN) ---
    res = session.results
    try:
        laps_df = session.laps
    except Exception:
        log.warning("    R%d: lap data not loaded, skipping laps", round_number)
        laps_df = None
    positions_from_laps = {}
    fastest_lap_driver = None
    status_map = {}
    grid_map = {}
    name_map = {}
    team_map = {}

    if res is not None and not res.empty:
        for _, r in res.iterrows():
            drv = str(r.get("Abbreviation", ""))
            status_map[drv] = str(r.get("Status", ""))
            grid_map[drv] = _safe_int(r.get("GridPosition"))
            name_map[drv] = str(r.get("FullName", ""))
            team_map[drv] = str(r.get("TeamName", ""))

    if laps_df is not None and not laps_df.empty:
        last_laps = laps_df.sort_values("LapNumber").groupby("Driver").last()
        for drv, row in last_laps.iterrows():
            positions_from_laps[drv] = _safe_int(row.get("Position"))

        try:
            fastest = laps_df.pick_fastest()
            if fastest is not None:
                fastest_lap_driver = str(fastest["Driver"])
        except Exception:
            pass

    all_drivers = set(list(status_map.keys()) + list(positions_from_laps.keys()))
    result_rows = []
    for drv in all_drivers:
        pos = _safe_int(res[res["Abbreviation"] == drv]["Position"].iloc[0]) if drv in status_map and res is not None else None
        if pos is None or pd.isna(pos):
            pos = positions_from_laps.get(drv)

        pts = F1_POINTS.get(pos, 0) if pos else 0
        if fastest_lap_driver and drv == fastest_lap_driver and pos and pos <= 10:
            pts += 1

        result_rows.append((
            year, round_number,
            drv,
            name_map.get(drv, drv),
            team_map.get(drv, ""),
            pos,
            grid_map.get(drv),
            pts,
            status_map.get(drv, ""),
            None,
            None,
            None, None, None, None,
        ))

    if result_rows:
        db.executemany(
            "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            result_rows,
        )

    # --- laps ---
    try:
        lp = session.laps
    except Exception:
        lp = None
    if lp is not None and not lp.empty:
        lap_rows = []
        for _, l in lp.iterrows():
            pit_in = l.get("PitInTime")
            pit_out = l.get("PitOutTime")
            is_pit = 0 if (pd.isna(pit_in) and pd.isna(pit_out)) else 1
            is_best = 1 if l.get("IsPersonalBest") else 0

            lap_rows.append((
                year, round_number,
                str(l.get("Driver", "")),
                _safe_int(l.get("LapNumber")),
                _safe_int(l.get("Position")),
                _timedelta_seconds(l.get("LapTime")),
                _timedelta_seconds(l.get("Sector1Time")),
                _timedelta_seconds(l.get("Sector2Time")),
                _timedelta_seconds(l.get("Sector3Time")),
                str(l.get("Compound", "")),
                _safe_float(l.get("TyreLife")),
                _safe_int(l.get("Stint")),
                is_pit, is_best,
                _safe_float(l.get("SpeedFL")),
            ))
        db.executemany(
            "INSERT OR REPLACE INTO laps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            lap_rows,
        )

    # --- weather ---
    wd = session.weather_data
    if wd is not None and not wd.empty:
        w = wd.mean(numeric_only=True)
        weather_row = (
            year, round_number,
            _safe_float(w.get("AirTemp")),
            _safe_float(w.get("TrackTemp")),
            _safe_float(w.get("Humidity")),
            _safe_float(w.get("Pressure")),
            1 if wd.get("Rainfall", pd.Series([0])).any() else 0,
            _safe_float(wd.get("WindSpeed", pd.Series([0])).max()),
        )
        db.execute(
            "INSERT OR REPLACE INTO weather VALUES (?,?,?,?,?,?,?,?)",
            weather_row,
        )

    db.commit()
    n_res = len(res) if res is not None and not res.empty else 0
    n_lap = len(lp) if lp is not None and not lp.empty else 0
    log.info("    R%d: %d results, %d laps", round_number, n_res, n_lap)


def run(years=None):
    if years is None:
        years = list(range(START_YEAR, END_YEAR + 1))

    init_db()
    db = _connect()

    for year in sorted(years, reverse=True):
        log.info("=" * 50)
        log.info("Season %d", year)

        try:
            n_events = ingest_events(db, year)
        except Exception as e:
            log.warning("  Cannot load schedule for %d: %s", year, e)
            continue

        if n_events == 0:
            continue

        for rn in range(1, n_events + 1):
            try:
                ingest_race(db, year, rn)
                for st in ("FP1", "FP2", "FP3"):
                    try:
                        ingest_session(db, year, rn, st)
                    except Exception as e:
                        log.warning("    R%d %s error: %s", rn, st, e)
            except Exception as e:
                log.warning("    R%d error: %s", rn, e)

    db.close()
    log.info("ETL complete. DB: %s", DB_PATH)


if __name__ == "__main__":
    run()
