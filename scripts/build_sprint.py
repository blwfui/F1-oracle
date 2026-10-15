"""重建某赛季的冲刺积分（sprint_points）。用法：python -m scripts.build_sprint [year]

## 这个脚本原来的四个隐患（2026-10-15 修）

1. **模块级执行**：`DELETE FROM sprint_points WHERE year=?` 写在模块顶层、没有
   `if __name__ == "__main__"` —— 任何 `import scripts.build_sprint`
   （IDE 批量分析、pytest 收集）都会**删掉一整年的冲刺积分**。
2. **先删后写**：DELETE 之后逐轮抓取，中途失败只 print 不恢复 —— 一次网络抖动就丢一年数据。
   现在改成**先把所有轮次抓到内存、再在一个事务里删+写**；抓取失败整体中止，库不动。
3. **分值口径只有 2022+**：2021 的冲刺积分是 3-2-1，不是 8-1。
   以前重跑 2021 会把正确的历史数据改坏（每轮 6 分 → 36 分）。
4. **用枚举序号当名次**：`seq` 是排序后的序号，遇到缺员（2026 R4 只有 20 行）会让后续
   条目名次整体前移。现在直接用赛果里的 `orig_pos`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fastf1

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.etl.db import CACHE_DIR, connect  # noqa: E402

fastf1.Cache.enable_cache(str(CACHE_DIR))

# 冲刺积分：2021 是 3-2-1，2022 起扩到前 8 名
SPRINT_POINTS_2021 = {1: 3, 2: 2, 3: 1}
SPRINT_POINTS_2022 = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}


def sprint_points_table(year: int) -> dict[int, int]:
    """该赛季的冲刺积分表。2021 只有前三名有分。"""
    return SPRINT_POINTS_2021 if year <= 2021 else SPRINT_POINTS_2022


def sprint_rounds(year: int) -> list[int]:
    """从赛历派生冲刺轮次。

    以 `EventFormat`（FastF1 赛历自带，取值 conventional / sprint_qualifying）为主，
    回退到「某个 SessionN 叫 Sprint」的旧判据 —— 不维护写死的轮次表，
    否则每加一个赛季就得手工补一张（旧实现只到 2024）。
    """
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    out = []
    for _, ev in schedule.iterrows():
        rn = int(ev["RoundNumber"])
        if rn <= 0:
            continue
        fmt = str(ev.get("EventFormat", "")).lower()
        sessions = [str(ev.get(f"Session{i}", "")).strip() for i in range(1, 6)]
        if "sprint" in fmt or "Sprint" in sessions:
            out.append(rn)
    return sorted(out)


def fetch_round(year: int, rn: int, pts_table: dict[int, int]) -> list[tuple]:
    """抓一轮冲刺赛的完整赛果。返回 [(year, round, driver, position, points)]。"""
    s = fastf1.get_session(year, rn, "S")
    s.load(telemetry=False, laps=True, weather=False, messages=True)
    laps = s.laps

    entries = []
    for drv in laps["Driver"].unique():
        # pick_drivers（复数）—— pick_driver 已弃用，上游移除后会直接 AttributeError。
        # 这类"依赖无上界 + 弃用 API"是本项目的一类固定风险（见审查报告 E2）。
        own = laps.pick_drivers(drv)
        finished = own.dropna(subset=["Position"]).sort_values(
            "LapNumber", ascending=False)
        if finished.empty:
            continue
        pos = int(finished.iloc[0]["Position"])
        timed = own.dropna(subset=["LapTime"]).sort_values("LapTime")
        best = timed.iloc[0]["LapTime"].total_seconds() if not timed.empty else 9999
        entries.append((str(drv), pos, best))

    # 名次用 orig_pos（不是排序后的序号）—— 缺员时序号会整体前移
    entries.sort(key=lambda x: (x[1], x[2]))
    return [(year, rn, drv, pos, pts_table.get(pos, 0)) for drv, pos, _ in entries]


def main() -> int:
    ap = argparse.ArgumentParser(description="重建某赛季的冲刺积分")
    ap.add_argument("year", type=int, nargs="?", default=None)
    ap.add_argument("--dry-run", action="store_true", help="只抓取与打印，不写库")
    args = ap.parse_args()

    if args.year is None:
        # 默认：库里已有冲刺数据的最大年份
        db = connect()
        row = db.execute("SELECT MAX(year) FROM sprint_points").fetchone()
        db.close()
        year = int(row[0]) if row and row[0] else 2021
    else:
        year = args.year

    rounds = sprint_rounds(year)
    if not rounds:
        print(f"{year} 没有冲刺轮次")
        return 0

    pts_table = sprint_points_table(year)
    print(f"{year} 冲刺轮次 {rounds}   分值表 {pts_table}")

    # ── 先把所有轮次抓到内存；任何一轮失败就整体中止，绝不动库 ──
    all_rows: list[tuple] = []
    for rn in rounds:
        try:
            rows = fetch_round(year, rn, pts_table)
        except Exception as e:                       # noqa: BLE001
            print(f"R{rn} 抓取失败：{type(e).__name__}: {e}", file=sys.stderr)
            print("→ 已中止，数据库未改动（旧实现会先删后写、失败即丢一年）",
                  file=sys.stderr)
            return 1
        total = sum(r[4] for r in rows)
        print(f"  R{rn}: {len(rows)} 位车手，合计 {total} 分")
        all_rows.extend(rows)

    if args.dry_run:
        print(f"\n--dry-run：{len(all_rows)} 行未写库")
        return 0

    # ── 一个事务里删 + 写：要么全成，要么全不动 ──────────────────
    db = connect()
    try:
        with db:                                     # 提交或回滚，不存在「删了没写」
            db.execute("DELETE FROM sprint_points WHERE year=?", (year,))
            db.executemany(
                "INSERT INTO sprint_points (year, round, driver, position, points)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(year, round, driver) DO UPDATE SET"
                " position=excluded.position, points=excluded.points",
                all_rows,
            )
    finally:
        db.close()

    print(f"\n已写入 {len(all_rows)} 行（{len(rounds)} 轮）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
