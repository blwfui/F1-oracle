"""展示某一场比赛、某一圈的完整排名与秒差。

    python -m scripts.show_lap 2021 22        # 默认最后一圈
    python -m scripts.show_lap 2024 8 40      # 2024 摩纳哥第 40 圈
    python -m scripts.show_lap 2021 22 58 --top 10

秒差口径
--------
「与领跑」= 该车手与本圈领跑者的会话累计时间之差（真实秒差，不是名次差）。
「与前车」= 与正前方那位的秒差。
两者都依赖 laps.time_sec（已回填 100%）。
注意：安全车 / 虚拟安全车期间所有差距会被压缩，此时秒差不可比。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.model.lapdata import load_laptimelines  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"

FLAG_CN = {"1": "绿旗", "2": "黄旗", "3": "黄旗", "4": "安全车",
           "5": "红旗", "6": "虚拟安全车", "7": "VSC结束"}


def _cn():
    """加载中文名生成器（独立模块，不依赖 streamlit）。"""
    sys.path.insert(0, str(ROOT / "src" / "dashboard"))
    try:
        from names_cn import auto_cn_short
        return auto_cn_short
    except Exception:  # noqa: BLE001
        return lambda code, full: code


def driver_meta(db: sqlite3.Connection, year: int, rnd: int) -> dict[str, dict]:
    return {
        r[0]: {"team": r[1] or "", "full": r[2] or ""}
        for r in db.execute(
            "SELECT driver, team, full_name FROM results WHERE year=? AND round=?",
            (year, rnd))
    }


def show(year: int, rnd: int, lap: int | None, top: int | None, use_cn: bool) -> None:
    cn = _cn() if use_cn else (lambda code, full: code)
    db = sqlite3.connect(str(DB_PATH))
    meta = driver_meta(db, year, rnd)
    ev = db.execute("SELECT event_name, location FROM events WHERE year=? AND round=?",
                    (year, rnd)).fetchone()
    db.close()

    tls = load_laptimelines(year)
    tl = next((t for t in tls if t.round == rnd), None)
    if tl is None:
        print(f"未找到 {year} R{rnd}")
        return

    lap = lap or tl.total_laps
    if lap not in tl.states:
        print(f"{year} R{rnd} 第 {lap} 圈无数据（共 {tl.total_laps} 圈）")
        return

    event = (ev[0] if ev else "?")
    loc = (ev[1] if ev else "?")
    running = tl.positions(lap)
    gaps = tl.gaps(lap)
    ahead = tl.gap_ahead(lap)
    times = tl.times(lap)
    sc = tl.is_neutralized(lap)
    flags = tl.track_status(lap)

    total_drivers = len(tl.final)
    retired = sorted(d for d in tl.final if d not in running)

    print("=" * 82)
    print(f" {year} R{rnd} · {event} · {loc}")
    line = (f" 第 {lap} 圈 / 共 {tl.total_laps} 圈"
            f" · 比赛进度 {lap / tl.total_laps * 100:.0f}%")
    if times:
        line += f" · 会话时间 {max(times.values()):.1f}s"
    print(line)
    flag_txt = " / ".join(FLAG_CN.get(f, f) for f in sorted(flags)) or "—"
    neutral = "   ⚠️ 差距已被压缩，秒差不可比" if sc else ""
    print(f" 赛道状态：{flag_txt}{neutral}")
    print(f" 在跑 {len(running)} 人 / 共 {total_drivers} 人"
          + (f"   已退赛 {len(retired)} 人：{' '.join(retired)}" if retired else ""))
    print("=" * 82)

    header = (f" {'名次':<5}{'车手':<18}{'车队':<16}{'与领跑':>9}{'与前车':>9}"
              f"{'轮胎':>10}{'胎龄':>5}{'进站':>5}")
    print(header)
    print("-" * 82)

    order = sorted(running, key=lambda d: running[d])
    if top:
        order = order[:top]

    for d in order:
        st = tl.states[lap][d]
        m = meta.get(d, {})
        name = cn(d, m.get("full", ""))
        gap = f"+{gaps[d]:.3f}" if d in gaps else "—"
        if d in ahead and ahead[d] == 0:
            gap = "—"
        ins = f"+{ahead[d]:.3f}" if d in ahead and ahead[d] > 0 else "—"
        tyre = (st.get("compound") or "")[:9]
        life = st.get("tyre_life")
        life = int(life) if life is not None else ""
        pit = "进站" if st.get("is_pit") else ""
        print(f" P{running[d]:<4}{name:<18}{m.get('team',''):<16}"
              f"{gap:>9}{ins:>9}{tyre:>10}{str(life):>5}{pit:>5}")

    if top and len(running) > top:
        print(f" …（其余 {len(running) - top} 人略）")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("round", type=int)
    ap.add_argument("lap", type=int, nargs="?", default=None, help="圈号，默认最后一圈")
    ap.add_argument("--top", type=int, default=None, help="只显示前 N 名")
    ap.add_argument("--no-cn", action="store_true", help="不显示中文名")
    args = ap.parse_args()
    show(args.year, args.round, args.lap, args.top, not args.no_cn)


if __name__ == "__main__":
    main()
