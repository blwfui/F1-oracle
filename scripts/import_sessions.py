"""Import practice sessions, sprint qualifying, and qualifying data for a given year.
Usage: python -m scripts.import_sessions <year> [fp|sq|q|all]

⚠️ 顺序：`sq` 依赖 sprint_points 里已经有该轮的**行**（它只 UPDATE `sq_pos`），
   所以新赛季要先跑 `python -m scripts.build_sprint <year>`。
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.etl.db import CACHE_DIR, connect as _connect  # noqa: E402

FP_TYPES = ("FP1", "FP2", "FP3")

# 任一步骤失败就把退出码置为 1 —— 以前一律返回 0，调度方看不出这次导入是残的
FAILURES = 0


def sprint_rounds(year):
    """冲刺轮次：从赛历派生（FastF1 的 EventFormat），不再维护写死的轮次表。

    旧实现优先读库里的 sprint_points，读不到就查一张只到 2024 的硬编码表 ——
    于是 2025/2026 恒为空集，SQ 静默跳过。
    """
    try:
        import fastf1
        fastf1.Cache.enable_cache(str(CACHE_DIR))
        sch = fastf1.get_event_schedule(year, include_testing=False)
        out = set()
        for _, ev in sch.iterrows():
            rn = int(ev["RoundNumber"])
            if rn <= 0:
                continue
            fmt = str(ev.get("EventFormat", "")).lower()
            sessions = [str(ev.get(f"Session{i}", "")).strip() for i in range(1, 6)]
            if "sprint" in fmt or "Sprint" in sessions:
                out.add(rn)
        if out:
            return out
    except Exception as e:                            # noqa: BLE001
        print(f"  （赛历读取失败，回退到库里的 sprint_points：{e}）", file=sys.stderr)
    db = _connect()
    rows = db.execute(
        "SELECT DISTINCT round FROM sprint_points WHERE year=?", (year,)).fetchall()
    db.close()
    return {r[0] for r in rows}


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
            except Exception as e:                    # noqa: BLE001
                global FAILURES
                FAILURES += 1
                print(f"FAIL: {type(e).__name__}: {e}")
            time.sleep(0.3)

    db.close()
    print(f"\nPractice import done. {total} sessions processed.")


# ── Sprint Qualifying SQ ───────────────────────────────────────────

def import_sq(year):
    """回填冲刺发车位 `sprint_points.sq_pos`。

    ⚠️ 修掉的两个 bug（2026-10-15）：
      · INSERT 有 **4 个占位符却只传了 3 个参数** → sqlite3.ProgrammingError，
        而它被外层宽 except 吞成一行 "FAIL:" 继续跑 —— 于是 `sq_pos` **永远写不进**，
        同时第 112 行算出来的 `pos` 根本没被使用。
      · 入口硬拦 `year > 2024`，2026 的冲刺排位无法导入。
        加上旧 `_get_sprint_rounds` 的硬编码表只到 2024，2025/2026 恒为空集。

    2021/2022 没有独立的冲刺排位会话：那年冲刺赛的发车位就是**周五排位赛**成绩，
    所以 `sq_pos` 直接取该轮的 `results.quali_pos`（实测与库里 2021/2022 的
    既有值 60/60 完全一致）。2023 用 "SS"（Sprint Shootout），2024+ 用 "SQ"。
    """
    import fastf1
    fastf1.Cache.enable_cache(str(CACHE_DIR))

    rounds = sprint_rounds(year)
    if not rounds:
        print(f"{year} 没有冲刺轮次，跳过 SQ")
        return 0

    db = _connect()
    total = 0

    for rn in sorted(rounds):
        print(f"  R{rn} SQ ...", end=" ", flush=True)
        try:
            if year <= 2022:
                # 冲刺发车位 = 周五排位赛成绩
                cur = db.execute(
                    "UPDATE sprint_points SET sq_pos = ("
                    "  SELECT q.quali_pos FROM results q WHERE"
                    "    q.year = sprint_points.year AND q.round = sprint_points.round"
                    "    AND q.driver COLLATE NOCASE = sprint_points.driver)"
                    " WHERE year=? AND round=? AND EXISTS ("
                    "  SELECT 1 FROM results q WHERE q.year = sprint_points.year"
                    "    AND q.round = sprint_points.round"
                    "    AND q.driver COLLATE NOCASE = sprint_points.driver"
                    "    AND q.quali_pos IS NOT NULL)",
                    (year, rn),
                )
            else:
                import pandas as pd
                # 2023 用 "SS"（Sprint Shootout），2024+ 用 "SQ"
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
                    cur = db.execute(
                        "UPDATE sprint_points SET sq_pos=?"
                        " WHERE year=? AND round=? AND driver COLLATE NOCASE=?",
                        (pos, year, rn, drv),
                    )
                    updated += cur.rowcount
                db.commit()
                print(f"{updated} 条 OK")
                total += updated
                time.sleep(0.5)
                continue

            db.commit()
            print(f"{cur.rowcount} 条 OK（口径：周五排位赛）")
            total += cur.rowcount
        except Exception as e:                        # noqa: BLE001
            global FAILURES
            FAILURES += 1
            print(f"FAIL: {type(e).__name__}: {e}")

    db.close()
    print(f"\nSQ import done. {total} entries updated.")
    return total


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
        except (ValueError, TypeError):
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
        except Exception as e:                        # noqa: BLE001
            global FAILURES
            FAILURES += 1
            print(f"FAIL: {type(e).__name__}: {e}")
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
        print("Usage: python -m scripts.import_sessions <year> [fp|sq|q|all]")
        print("  year: 2018 起")
        print("  step: fp (practice), sq (sprint qualifying), q (qualifying), all (default)")
        sys.exit(1)

    year = int(sys.argv[1])
    step = sys.argv[2] if len(sys.argv) > 2 else "all"

    # 原来硬拦 year > 2024（"2025 has its own script"）—— 那条脚本已经不在了，
    # 于是 2025/2026 的练习赛与冲刺排位无法用本脚本导入。上界跟着"今年"走。
    import datetime
    if year < 2018 or year > datetime.date.today().year:
        print(f"年份 {year} 超出范围（2018–{datetime.date.today().year}）")
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
    if FAILURES:
        print(f"\n⚠️ {FAILURES} 个步骤失败", file=sys.stderr)
        sys.exit(1)
    print("\nDONE")
