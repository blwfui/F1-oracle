"""实时监控 laps 时间轴回填进度。

用途
----
回填脚本（scripts.backfill_lap_times）跑起来后，另开一个终端运行本脚本，
即可看到「下到哪了」——总体进度、按年细分、当前速度与预计剩余时间。

    # 终端 A：跑回填
    python -m scripts.backfill_lap_times

    # 终端 B：看进度（每秒刷新）
    python -m scripts.watch_backfill

    # 只看一次快照后退出
    python -m scripts.watch_backfill --once

它不依赖回填进程，直接读数据库统计，所以随便什么时候开都行。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "f1_oracle.db"


def snapshot(db: sqlite3.Connection) -> tuple[int, int, dict[int, tuple[int, int]]]:
    total = db.execute("SELECT COUNT(DISTINCT year||'-'||round) FROM laps").fetchone()[0]
    done = db.execute(
        "SELECT COUNT(DISTINCT year||'-'||round) FROM laps WHERE time_sec IS NOT NULL"
    ).fetchone()[0]
    years: dict[int, tuple[int, int]] = {}
    for y, tot, dn in db.execute(
            """SELECT year, COUNT(DISTINCT round),
                      COUNT(DISTINCT CASE WHEN time_sec IS NOT NULL THEN round END)
               FROM laps GROUP BY year ORDER BY year"""):
        years[int(y)] = (int(dn), int(tot))
    return done, total, years


def bar(frac: float, width: int = 32) -> str:
    n = int(round(frac * width))
    return "█" * n + "░" * (width - n)


def fmt_eta(sec: float) -> str:
    if sec <= 0 or sec != sec:
        return "—"
    m, s = divmod(int(sec), 60)
    return f"{m}分{s:02d}秒" if m else f"{s}秒"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只打印一次快照")
    ap.add_argument("--interval", type=float, default=1.0, help="刷新间隔（秒）")
    args = ap.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    prev_done, prev_t = None, time.time()
    last_rate = float("nan")

    while True:
        done, total, years = snapshot(db)
        now = time.time()

        if prev_done is not None and done > prev_done:
            last_rate = (done - prev_done) / max(now - prev_t, 1e-9)   # 场/秒
        rate = last_rate
        eta = (total - done) / rate if rate and rate == rate and rate > 0 else float("nan")
        prev_done, prev_t = done, now

        frac = done / total if total else 0
        year_str = "  ".join(
            f"{y}:{dn}/{tt}" for y, (dn, tt) in years.items())
        line = (f"[{bar(frac)}] {done:>3}/{total} 场 {frac*100:5.1f}%  "
                f"速度 {rate:.2f} 场/秒  ETA {fmt_eta(eta)}")

        if args.once:
            print(line)
            print(f"  按年：{year_str}")
            break

        end = "" if sys.stdout.isatty() else "\n"
        sys.stdout.write("\r" + line.ljust(110) + end)
        sys.stdout.flush()

        if done >= total:
            print()
            print("✅ 全部完成")
            print(f"  按年：{year_str}")
            break
        time.sleep(args.interval)

    db.close()


if __name__ == "__main__":
    main()
