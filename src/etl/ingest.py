"""ETL pipeline: FastF1 → SQLite data warehouse."""

import sqlite3
import logging
import datetime
from pathlib import Path

import fastf1
import pandas as pd

from src.etl.points import race_points
from src.etl.schema import SCHEMA_SQL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

fastf1.Cache.enable_cache(str(CACHE_DIR))

# 起始年固定 2018（数据覆盖起点）；结束年跟着"今年"走 ——
# 写死 2025 会让 README「快速开始」的第一步建不出第 9 季，而 import_season
# 又依赖 events 表，空库时会打印"没有可导入的轮次"然后正常退出（退出码 0）。
START_YEAR = 2018
END_YEAR = datetime.date.today().year


def _connect():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=OFF")
    return db


# 记录「这次到底怎么了」，让调用方分得清两种情况：
#   SKIPPED —— 赛季里**根本没有这个会话**（冲刺周末没有 FP3、测试日没有正赛），正常
#   FAILED  —— 网络/解析等真失败，必须让调用方看见（以前它们都被 log.warning 后
#              静默 return，调用方无从区分，于是"数据莫名少了几轮"）
SKIPPED: list[str] = []
FAILED: list[str] = []


def _note_skip(year: int, rn: int, sess: str, e: Exception) -> None:
    tag = f"{year} R{rn} {sess}"
    if isinstance(e, (ValueError, KeyError)):
        SKIPPED.append(tag)
        log.info("    跳过 %s：赛季里没有这个会话", tag)
    else:
        FAILED.append(f"{tag}: {type(e).__name__}: {e}")
        log.warning("    **失败** %s：%s: %s", tag, type(e).__name__, e)


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
        _note_skip(year, round_number, session_type, e)
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
        _note_skip(year, round_number, "Q", e)
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
        _note_skip(year, round_number, "R", e)
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
        except Exception as e:                        # noqa: BLE001
            # 拿不到最快圈 → 该年规则下会少那 1 分。绝不能静默：记一笔。
            FAILED.append(f"{year} R{round_number} 最快圈识别: "
                          f"{type(e).__name__}: {e}")
            log.warning("    R%d: 最快圈识别失败（%s），本场不做最快圈记分",
                        round_number, type(e).__name__)

    all_drivers = set(list(status_map.keys()) + list(positions_from_laps.keys()))
    result_rows = []
    for drv in all_drivers:
        pos = _safe_int(res[res["Abbreviation"] == drv]["Position"].iloc[0]) if drv in status_map and res is not None else None
        if pos is None or pd.isna(pos):
            pos = positions_from_laps.get(drv)

        pts = race_points(pos, year=year, is_fastest_lap=(drv == fastest_lap_driver))

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
    except Exception as e:                        # noqa: BLE001
        FAILED.append(f"{year} R{round_number} laps: {type(e).__name__}: {e}")
        log.warning("    R%d: 圈速读取失败（%s），该轮将没有圈速",
                    round_number, type(e).__name__)
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
                _timedelta_seconds(l.get("Time")),
                _timedelta_seconds(l.get("LapStartTime")),
                str(l.get("TrackStatus", "")),
            ))
        db.executemany(
            "INSERT OR REPLACE INTO laps (year, round, driver, lap_number, position,"
            " lap_time, sector1, sector2, sector3, compound, tyre_life, stint,"
            " is_pit, is_best, speed_fl, time_sec, lap_start_sec, track_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            ingest_events(db, year)
        except Exception as e:
            log.warning("  Cannot load schedule for %d: %s", year, e)
            continue

        # 轮次以 events 里**真实存在的正数轮次**为准，不能拿行数当上限：
        # ingest_events 会把测试日（round=0）也写进来，行数因此比实际轮次多 1，
        # 于是每个赛季都会去请求一个不存在的轮次（get_session 直接抛 ValueError）。
        rounds = [r for (r,) in db.execute(
            "SELECT round FROM events WHERE year=? AND round > 0 ORDER BY round",
            (year,))]
        if not rounds:
            continue

        for rn in rounds:
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
    if SKIPPED:
        log.info("跳过的会话 %d 个（赛季里没有该会话，正常）", len(SKIPPED))
    if FAILED:
        log.error("**失败 %d 处**（这些不是「没数据」，是真出错）：", len(FAILED))
        for item in FAILED[:10]:
            log.error("  %s", item)
    return len(FAILED)


if __name__ == "__main__":
    # 有真失败就非零退出 —— 以前一律退出 0，调度方看不出这次导入是残的
    raise SystemExit(1 if run() else 0)
