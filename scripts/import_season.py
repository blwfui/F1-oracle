"""通用赛季导入器：FastF1 → SQLite（可断点续跑，逐轮打印进度）。

复用 src/etl/ingest.py 的既有链路，不重写任何取数逻辑：
    ingest_race       → results / laps / weather
    ingest_qualifying → q1_sec / q2_sec / q3_sec / quali_pos
    ingest_session    → 练习赛 sessions（FP1/FP2/FP3）

用法：
    python -m scripts.import_season 2026            # 导入截至今天已完成的轮次
    python -m scripts.import_season 2026 --upto 17  # 指定最大轮次
    python -m scripts.import_season 2026 --force    # 忽略已有数据强制重导

设计要点：
- 幂等：底层全是 INSERT OR REPLACE / UPDATE，重复跑不会造重复行。
- 可续跑：已完成轮次直接跳过（--force 可关闭），中断后重跑只补缺失的。
- 只导「已发生」的轮次：按 events.event_date 与今天比较，未来的轮次不去请求。
- FastF1 的 INFO 日志压掉，只留自己的进度输出（便于后台跑时观察）。
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
sys.path.insert(0, str(ROOT))

logging.getLogger("fastf1").setLevel(logging.WARNING)
logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("req").setLevel(logging.WARNING)
logging.getLogger("api").setLevel(logging.WARNING)
logging.getLogger("_api").setLevel(logging.WARNING)

FP_TYPES = ("FP1", "FP2", "FP3")

# 一轮算「已完成」的最低门槛（22 车阵容下的宽松下界）
MIN_RESULTS = 18
MIN_QUALI = 15
MIN_LAPS = 100


def _connect():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    return db


def completed_rounds(db, year):
    """events 里日期已过、且不是季前测试（round>0）的轮次。"""
    today = date.today().isoformat()
    rows = db.execute(
        "SELECT round, event_name, location, event_date FROM events"
        " WHERE year=? AND round>0 AND event_date<=? ORDER BY round",
        (year, today),
    ).fetchall()
    return rows


def coverage(db, year, rn):
    """一轮的四个覆盖指标：成绩 / 排位 / 练习赛种类 / 圈数。"""
    q = lambda sql: db.execute(sql, (year, rn)).fetchone()[0]  # noqa: E731
    return {
        "res": q("SELECT COUNT(*) FROM results WHERE year=? AND round=?"),
        "quali": q("SELECT COUNT(*) FROM results WHERE year=? AND round=? AND q1_sec IS NOT NULL"),
        "fp": q("SELECT COUNT(DISTINCT session_type) FROM sessions WHERE year=? AND round=?"),
        "laps": q("SELECT COUNT(*) FROM laps WHERE year=? AND round=?"),
    }


def is_done(cov):
    return (cov["res"] >= MIN_RESULTS and cov["quali"] >= MIN_QUALI
            and cov["fp"] >= 1 and cov["laps"] >= MIN_LAPS)


def import_round(db, year, rn):
    """导入一轮的全部会话。返回各步骤是否成功。"""
    from src.etl.ingest import ingest_qualifying, ingest_race, ingest_session

    step = {}
    t0 = time.perf_counter()
    try:
        ingest_race(db, year, rn)
        step["R"] = True
    except Exception as e:
        step["R"] = f"{type(e).__name__}: {str(e)[:80]}"
    t_race = time.perf_counter() - t0

    try:
        ingest_qualifying(db, year, rn)
        step["Q"] = True
    except Exception as e:
        step["Q"] = f"{type(e).__name__}: {str(e)[:80]}"

    fp_ok = 0
    for st in FP_TYPES:
        try:
            ingest_session(db, year, rn, st)
            fp_ok += 1
        except Exception as e:
            step[st] = f"{type(e).__name__}: {str(e)[:60]}"
    step["FP"] = fp_ok
    step["secs"] = t_race + (time.perf_counter() - t0 - t_race)
    return step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("--upto", type=int, default=None, help="最大轮次（默认今天之前全部）")
    ap.add_argument("--from-round", type=int, default=1, dest="from_round")
    ap.add_argument("--force", action="store_true", help="忽略已有数据，强制重导")
    args = ap.parse_args()

    year = args.year
    db = _connect()

    from src.etl.schema import SCHEMA_SQL
    db.executescript(SCHEMA_SQL)
    db.commit()

    from src.etl.ingest import ingest_events
    n_ev = ingest_events(db, year)
    print(f"[{year}] 赛程 {n_ev} 条", flush=True)

    rounds = completed_rounds(db, year)
    if args.upto:
        rounds = [r for r in rounds if r[0] <= args.upto]
    rounds = [r for r in rounds if r[0] >= args.from_round]
    if not rounds:
        # ⚠️ 这里以前是 return（退出码 0）—— 空库时会打印一句"没有可导入的轮次"
        # 然后**正常退出**，调用方（脚本/CI/人）无法区分「赛季已跑完」和「events
        # 表是空的」。空库恰恰是最需要报错的场景，所以改成非零退出。
        print(f"[{year}] 没有可导入的轮次 —— events 表里没有该赛季的已完赛轮次。"
              f"空库请先跑 python -m src.etl.ingest", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[{year}] 待处理 {len(rounds)} 轮："
          f"R{rounds[0][0]}–R{rounds[-1][0]}", flush=True)
    print("-" * 78, flush=True)

    t_all = time.perf_counter()
    skipped = 0
    failed = []
    for i, (rn, name, loc, dt) in enumerate(rounds, 1):
        cov = coverage(db, year, rn)
        if is_done(cov) and not args.force:
            skipped += 1
            print(f"[{i:2}/{len(rounds)}] R{rn:<2} {loc:<20} 已完整，跳过 "
                  f"(res={cov['res']} q={cov['quali']} fp={cov['fp']} lap={cov['laps']})",
                  flush=True)
            continue

        print(f"[{i:2}/{len(rounds)}] R{rn:<2} {loc:<20} {dt}  导入中...", flush=True)
        step = import_round(db, year, rn)
        cov = coverage(db, year, rn)
        flag = "OK " if is_done(cov) else "!! "
        print(f"          {flag}{step['secs']:5.1f}s  "
              f"res={cov['res']:>2} q={cov['quali']:>2} fp={cov['fp']} lap={cov['laps']:>4}"
              f"   [R={step['R']} Q={step['Q']} FP={step['FP']}]", flush=True)
        if not is_done(cov):
            failed.append((rn, cov))

    dur = time.perf_counter() - t_all
    print("-" * 78, flush=True)
    print(f"完成：{len(rounds) - skipped} 轮导入 / {skipped} 轮跳过 / 耗时 {dur/60:.1f} 分钟",
          flush=True)
    if failed:
        print("⚠️ 覆盖不足的轮次：", flush=True)
        for rn, cov in failed:
            print(f"   R{rn}: {cov}", flush=True)
    db.close()
    # 有轮次覆盖不足就非零退出 —— 以前一律返回 0，调度方看不出这次导入是残的
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
