"""回填 laps 表的时间轴字段：time_sec / lap_start_sec / track_status。

待办判据（2026-10-15 修）
------------------------
原判据是「laps 里存在 `time_sec IS NULL` 的行」，两头都错：
  · **2018 R14（Monza）在 laps 里一行都没有** → 永远进不了队列，于是永远补不上；
  · 有几场各只有 1 行 NULL → **每次运行都重抓整场**，永不收敛。
现在以 `results` 为准枚举轮次，只把「完全没有圈速行」或「NULL 占比 > 10%」的入队。

⚠️ 2018 R14 是**补不回来的**：FastF1 加载该场计时数据时内部抛
`IndexError: list index out of range`（上游解析失败，报 `Failed to load timing data!`
后静默留下未加载的 laps）。这不是本项目的缺陷，本脚本每次都会正确点名它 ——
别去追这个，等上游修。

背景
----
原 ETL 把 laps 当成「每圈一行」来存，丢了时间轴 —— 只有 lap_time（单圈耗时），
没有累计时间，因此**算不出两车之间几秒的差距**（gap）。而 gap 是赛中分析的核心：
名次只告诉你谁在前面，gap 才告诉你他稳不稳。

这三个字段都来自 FastF1 的 laps 数据（**不是遥测**），所以不需要重新下载
position/car 那几十 MB 的大包，直接从已有缓存读即可。

字段口径
--------
time_sec       该圈完成时刻的「会话累计时间」（秒）。含赛前等待（约 1 小时），
               故绝对值无意义；同场车手共享同一起点，gap = 同圈两人 time_sec 之差。
lap_start_sec  该圈开始时刻（秒，同为会话累计）。
track_status   赛道状态标志串，用于识别安全车/黄旗/红旗窗口。

用法
----
    python -m scripts.backfill_lap_times              # 回填全部缺失场次
    python -m scripts.backfill_lap_times --year 2024  # 只回填某年
    python -m scripts.backfill_lap_times --limit 3    # 试跑 3 场
    python -m scripts.backfill_lap_times --report     # 只看覆盖率，不抓取
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import fastf1
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.etl.ingest import _timedelta_seconds  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

fastf1.Cache.enable_cache(str(CACHE_DIR))
# ci_mode：请求优先「只用缓存」。命中即不发网络请求，避免代理超时重试拖慢
# （实测从 45s/场 降到 2.5s/场）。未命中时才走正常请求，所以仍能补充新数据。
# 用 --online 可关闭。
fastf1.Cache.ci_mode = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill")

# 新增列：列名 -> SQLite 类型
NEW_COLUMNS = {
    "time_sec": "REAL",
    "lap_start_sec": "REAL",
    "track_status": "TEXT",
}


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    return db


def ensure_columns(db: sqlite3.Connection) -> list[str]:
    """幂等地补齐缺失列，返回本次新增的列名。"""
    have = {r[1] for r in db.execute("PRAGMA table_info(laps)")}
    added = []
    for col, typ in NEW_COLUMNS.items():
        if col not in have:
            db.execute(f"ALTER TABLE laps ADD COLUMN {col} {typ}")
            added.append(col)
    if added:
        db.commit()
        log.info("已新增列：%s", ", ".join(added))
    return added


def pending_races(db: sqlite3.Connection, year: int | None) -> list[tuple[int, int]]:
    """待回填的 (year, round)。

    ⚠️ 原判据只有「laps 里存在 time_sec IS NULL 的行」，两头都错：

      · **2018 R14（Monza）在 laps 里一行都没有** —— 永远进不了队列，于是永远补不上
        （实测：results 覆盖 190 轮，laps 只覆盖 189 轮，缺的正是这一站）；
      · 反过来，有几场各只有 1 行 NULL，**每次运行都会重抓整场**，永不收敛。

    改成以 `results` 为准枚举所有轮次：**完全没有圈速行**、或 **NULL 占比 > 10%**
    的才入队。一两行的噪声不再触发整场重抓。
    """
    sql = """
    SELECT r.year, r.round,
           (SELECT COUNT(*) FROM laps l
             WHERE l.year = r.year AND l.round = r.round) AS n,
           (SELECT COUNT(*) FROM laps l
             WHERE l.year = r.year AND l.round = r.round
               AND l.time_sec IS NOT NULL) AS ok
      FROM (SELECT DISTINCT year, round FROM results WHERE round > 0) r
    """
    params: list = []
    if year is not None:
        sql = (sql.replace("WHERE round > 0) r",
                           "WHERE round > 0 AND year = ?) r"))
        params.append(year)
    sql += " ORDER BY r.year, r.round"

    out = []
    for y, r, n, ok in db.execute(sql, params):
        n, ok = int(n), int(ok)
        if n == 0 or (n - ok) / n > 0.10:
            out.append((int(y), int(r)))
    return out


def coverage(db: sqlite3.Connection) -> None:
    print("\n=== 覆盖率 ===")
    total = db.execute("SELECT COUNT(*) FROM laps").fetchone()[0]
    if not total:
        # 审查报告 E6：空库上这里会 ZeroDivisionError —— 恰好在**最需要诊断**
        # 的时候（库还没建好）崩掉。空就是空，说明白就行。
        print("  laps 表为空 —— 还没导入任何圈速数据（先跑 scripts/import_season.py）")
        return
    for col in NEW_COLUMNS:
        n = db.execute(f"SELECT COUNT({col}) FROM laps").fetchone()[0]
        print(f"  {col:16s} {n:>7,} / {total:>7,}  = {n / total * 100:5.1f}%")
    print("\n  按年（有 time_sec 的场次数 / 总场次数）：")
    for y in [r[0] for r in db.execute("SELECT DISTINCT year FROM laps ORDER BY year")]:
        tot = db.execute("SELECT COUNT(DISTINCT round) FROM laps WHERE year=?", (y,)).fetchone()[0]
        done = db.execute(
            "SELECT COUNT(DISTINCT round) FROM laps WHERE year=? AND time_sec IS NOT NULL",
            (y,)).fetchone()[0]
        mark = "✅" if done == tot else ("⚠️" if done else "❌")
        print(f"    {y}  {done:>3}/{tot:<3} {mark}")


def backfill_one(db: sqlite3.Connection, year: int, rnd: int) -> tuple[int, int]:
    """回填一场比赛。返回 (更新行数, 该场总行数)。"""
    session = fastf1.get_session(year, rnd, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    lp = session.laps
    if lp is None or lp.empty:
        log.warning("  %d R%d：无 laps 数据", year, rnd)
        return 0, 0

    rows = []
    for _, l in lp.iterrows():
        rows.append((
            _timedelta_seconds(l.get("Time")),
            _timedelta_seconds(l.get("LapStartTime")),
            str(l.get("TrackStatus", "")),
            year, rnd,
            str(l.get("Driver", "")),
            _safe_lap_number(l.get("LapNumber")),
        ))
    rows = [r for r in rows if r[6] is not None]

    before = db.execute(
        "SELECT COUNT(*) FROM laps WHERE year=? AND round=?", (year, rnd)).fetchone()[0]
    db.executemany(
        "UPDATE laps SET time_sec=?, lap_start_sec=?, track_status=?"
        " WHERE year=? AND round=? AND driver=? AND lap_number=?",
        rows,
    )
    db.commit()
    after = db.execute(
        "SELECT COUNT(*) FROM laps WHERE year=? AND round=? AND time_sec IS NOT NULL",
        (year, rnd)).fetchone()[0]
    return after, before


def _safe_lap_number(val):
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=None, help="只处理某一年")
    ap.add_argument("--limit", type=int, default=None, help="最多处理多少场（试跑用）")
    ap.add_argument("--report", action="store_true", help="只打印覆盖率，不抓取")
    ap.add_argument("--online", action="store_true", help="允许联网（默认仅用缓存）")
    args = ap.parse_args()

    if args.online:
        fastf1.Cache.ci_mode = False
        log.info("已关闭缓存优先模式（允许正常联网）")

    db = connect()
    ensure_columns(db)

    if args.report:
        coverage(db)
        db.close()
        return

    todo = pending_races(db, args.year)
    if args.limit:
        todo = todo[: args.limit]

    print(f"待回填 {len(todo)} 场")
    if args.year:
        print(f"（限定年份 {args.year}）")
    print()

    t0 = time.time()
    ok = fail = 0
    failed: list[tuple[int, int, str]] = []
    for i, (y, r) in enumerate(todo, 1):
        ts = time.time()
        try:
            after, before = backfill_one(db, y, r)
            ok += 1
            flag = "✅" if after == before else f"⚠️ {after}/{before}"
            print(f"  [{i:>3}/{len(todo)}] {y} R{r:<3} {after:>4} 行  {flag}"
                  f"  ({time.time() - ts:.1f}s)")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            failed.append((y, r, f"{type(exc).__name__}: {exc}"))
            print(f"  [{i:>3}/{len(todo)}] {y} R{r:<3} ❌ {type(exc).__name__}: {exc}")

    print(f"\n完成：成功 {ok} 场，失败 {fail} 场，用时 {time.time() - t0:.0f}s")
    if failed:
        print("失败明细：")
        for y, r, msg in failed:
            print(f"  {y} R{r}: {msg}")

    coverage(db)
    db.close()


if __name__ == "__main__":
    main()
