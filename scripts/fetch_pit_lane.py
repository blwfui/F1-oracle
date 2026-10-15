"""从实跑遥测中抽取「真实维修区」几何，写入 circuits.pit_lane_json。

思路
----
FastF1 不提供维修区几何。但**进站车自己会开过维修区** —— 于是：

  维修区行驶时间窗 = 该车 in-lap 的 `PitInTime` → 下一个 out-lap 的 `PitOutTime`

在这个窗口里切 `pos_data` 的连续位置流，得到的就是**真实维修区轨迹**（含进站口、
车库段、出站口）。取一个时窗正常（25–150 s，滤掉红旗/长时间停车）、采样最密的
窗口作为代表，降采样成折线，并把它投影回赛道轮廓求出进/出站口所在的圈内比例。

坐标系
------
- `circuits.outline_json` 单位是**米**；
- FastF1 `pos_data` 的 X/Y 单位是 **1/10 米**（与 circuit_info 同原点、同朝向）。
  → 抽取时 /10 即可与 outline 对齐（已实测：corners/10 与 outline 中位偏差 0.7 m）。

用法
----
    python -m scripts.fetch_pit_lane 2023 3            # 只跑、打印 + 出校验图
    python -m scripts.fetch_pit_lane 2023 3 --commit   # 写入数据库
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

# 只保留「正常进站」的时窗：太短是数据缺口，太长是红旗/长时间停车
DUR_MIN_S, DUR_MAX_S = 25.0, 150.0
# 降采样后相邻点的目标间距（米）
SAMPLE_STEP_M = 4.0


def _load_db():
    db = sqlite3.connect(DB_PATH)
    return db


def _circuit_for(db, year: int, rnd: int) -> tuple[str, np.ndarray]:
    """返回 (circuit_id, outline 点集[米])。"""
    loc = db.execute(
        "SELECT location FROM events WHERE year=? AND round=?", (year, rnd)
    ).fetchone()
    if not loc:
        raise SystemExit(f"events 表里没有 {year} R{rnd}")
    location = loc[0]
    row = db.execute(
        "SELECT circuit_id, outline_json FROM circuits "
        "WHERE circuit_id IN (SELECT circuit_id FROM circuit_aliases WHERE location=?) "
        "   OR name = ?",
        (location, location),
    ).fetchone()
    if not row or not row[1]:
        raise SystemExit(f"找不到 {location} 的赛道几何")
    return row[0], np.asarray(json.loads(row[1]), float)


def _pit_windows(laps, driver: str):
    """该车手的 (PitInTime, PitOutTime, in_lap_number) 列表。"""
    L = laps[laps["Driver"] == driver].sort_values("LapNumber").reset_index(drop=True)
    out = []
    for i in range(len(L) - 1):
        a, b = L.iloc[i], L.iloc[i + 1]
        if a["PitInTime"] != a["PitInTime"] or b["PitOutTime"] != b["PitOutTime"]:
            continue  # NaN
        dur = b["PitOutTime"].total_seconds() - a["PitInTime"].total_seconds()
        if DUR_MIN_S <= dur <= DUR_MAX_S:
            out.append((a["PitInTime"].total_seconds(),
                        b["PitOutTime"].total_seconds(),
                        int(a["LapNumber"]), dur))
    return out


def extract(year: int, rnd: int):
    """抽维修区，返回 (circuit_id, outline, lane[[x,y]], entry_frac, exit_frac, meta)。"""
    import fastf1

    fastf1.Cache.enable_cache(str(CACHE_DIR))
    db = _load_db()
    circuit_id, outline = _circuit_for(db, year, rnd)

    session = fastf1.get_session(year, rnd, "R")
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    laps = session.laps

    # 收集每个车手的正常进站时窗：挑采样最密的当维修区代表，
    # 并用「窗口中段的静止位置」定出该车手的车库点（真实停车位置）。
    best = None
    box_pts: dict[str, list[float]] = {}
    for drv in laps["Driver"].unique():
        wins = _pit_windows(laps, drv)
        if not wins:
            continue
        dn = str(laps[laps["Driver"] == drv]["DriverNumber"].iloc[0])
        pos = session.pos_data[dn]
        tt = pos["SessionTime"].dt.total_seconds().to_numpy()
        Xr = pos["X"].to_numpy(float) / 10.0
        Yr = pos["Y"].to_numpy(float) / 10.0
        mine = []
        for tin, tout, ln, dur in wins:
            m = (tt >= tin) & (tt <= tout)
            n = int(m.sum())
            if n > 30:
                mine.append((n, ln, dur, Xr[m], Yr[m]))
        if not mine:
            continue
        n, ln, dur, Xw, Yw = max(mine, key=lambda z: z[0])
        if best is None or n > best["n"]:
            best = {"drv": drv, "lap": ln, "n": n, "dur": dur, "X": Xw, "Y": Yw}
        lo, hi = int(len(Xw) * 0.3), int(len(Xw) * 0.7)
        if hi - lo > 3:
            box_pts[drv] = [float(np.median(Xw[lo:hi])), float(np.median(Yw[lo:hi]))]

    if best is None:
        raise SystemExit("没找到可用的正常进站时窗")

    pts = np.c_[best["X"], best["Y"]]

    # 降采样：按累计弧长每 SAMPLE_STEP_M 米取一点（保留首尾）
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.r_[0.0, np.cumsum(seg)]
    keep = [0]
    for target in np.arange(SAMPLE_STEP_M, cum[-1], SAMPLE_STEP_M):
        keep.append(int(np.argmin(np.abs(cum - target))))
    keep.append(len(pts) - 1)
    lane = pts[sorted(set(keep))]

    # 进/出站口 → 圈内比例（投影到闭合赛道轮廓）
    entry_frac, entry_off = _project(outline, lane[0], closed=True)
    exit_frac, exit_off = _project(outline, lane[-1], closed=True)

    # 车库点 → 维修区弧长比例（投影到开放维修区折线）
    boxes: dict[str, float] = {}
    for drv, p in box_pts.items():
        s, _off = _project(lane, p, closed=False)
        boxes[drv] = round(float(s), 4)

    meta = {
        "source": f"{year} R{rnd} · {best['drv']} lap {best['lap']}",
        "samples": best["n"], "duration_s": round(best["dur"], 1),
        "entry_off_m": round(entry_off, 1), "exit_off_m": round(exit_off, 1),
        "boxes_n": len(boxes),
    }
    return circuit_id, outline, lane, entry_frac, exit_frac, boxes, meta


def _project(poly: np.ndarray, p, closed: bool = True) -> tuple[float, float]:
    """把点 p 投影到折线 poly 上，返回 (累计弧长比例, 垂距米)。

    closed=True 时把 poly 当作闭合环（首尾相连）；False 时按开放折线处理。
    """
    a = poly if closed else poly[:-1]
    b = np.roll(poly, -1, axis=0) if closed else poly[1:]
    ab = b - a
    ap = np.asarray(p, float) - a
    L2 = np.einsum("ij,ij->i", ab, ab)
    L2[L2 == 0] = 1e-9
    t = np.clip(np.einsum("ij,ij->i", ap, ab) / L2, 0, 1)
    proj = a + t[:, None] * ab
    dist = np.hypot(*(proj - np.asarray(p, float)).T)
    i = int(np.argmin(dist))
    seglen = np.hypot(ab[:, 0], ab[:, 1])
    total = seglen.sum()
    cumlen = np.r_[0.0, np.cumsum(seglen)]
    frac = (cumlen[i] + t[i] * seglen[i]) / total
    return float(frac), float(dist[i])


def _overlay_svg(outline, lane, path_out: Path):
    W = H = 1000
    pad = 40
    allp = np.vstack([outline, lane])
    minx, maxx = allp[:, 0].min(), allp[:, 0].max()
    miny, maxy = allp[:, 1].min(), allp[:, 1].max()
    sc = min((W - 2 * pad) / (maxx - minx), (H - 2 * pad) / (maxy - miny))
    ox, oy = (W - (maxx - minx) * sc) / 2, (H - (maxy - miny) * sc) / 2

    def pr(x, y):
        return ox + (x - minx) * sc, oy + (maxy - y) * sc

    def d_of(A):
        out = ""
        for i, (x, y) in enumerate(A):
            X, Y = pr(x, y)
            out += ("L" if i else "M") + f"{X:.1f} {Y:.1f}"
        return out

    e = pr(*lane[0]); x = pr(*lane[-1])
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="0 0 1000 1000">
<rect width="1000" height="1000" fill="#0d1117"/>
<path d="{d_of(outline)}Z" fill="none" stroke="#6e7681" stroke-width="7"/>
<path d="{d_of(lane)}" fill="none" stroke="#ff5d5d" stroke-width="3.5"/>
<circle cx="{e[0]:.1f}" cy="{e[1]:.1f}" r="7" fill="#2fbf71"/>
<circle cx="{x[0]:.1f}" cy="{x[1]:.1f}" r="7" fill="#f0883e"/>
<text x="18" y="28" fill="#e6edf3" font-size="19">灰=赛道 红=维修区 绿=进站口 橙=出站口</text>
</svg>'''
    path_out.write_text(svg, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("round", type=int)
    ap.add_argument("--commit", action="store_true", help="写入 circuits.pit_lane_json")
    args = ap.parse_args()

    circuit_id, outline, lane, ef, xf, boxes, meta = extract(args.year, args.round)

    print(f"circuit_id = {circuit_id}")
    print(f"维修区折线: {len(lane)} 点  进站口 frac={ef:.4f}  出站口 frac={xf:.4f}")
    print(f"来源: {meta['source']}  n={meta['samples']} dur={meta['duration_s']}s")
    print(f"进站口离赛道 {meta['entry_off_m']} m / 出站口离赛道 {meta['exit_off_m']} m")
    print(f"车库点: {len(boxes)} 个 -> " +
          ", ".join(f"{d}:{s:.2f}" for d, s in sorted(boxes.items())))

    out_svg = ROOT / "outputs" / "_pitlane_check.svg"
    _overlay_svg(outline, lane, out_svg)
    print(f"校验图: {out_svg}")

    if args.commit:
        payload = {
            "path": [[round(float(x), 1), round(float(y), 1)] for x, y in lane],
            "entry": round(ef, 5),
            "exit": round(xf, 5),
            "boxes": boxes,
            "meta": meta,
        }
        db = _load_db()
        db.execute("UPDATE circuits SET pit_lane_json=? WHERE circuit_id=?",
                   (json.dumps(payload, ensure_ascii=False), circuit_id))
        db.commit()
        print(f"已写入 circuits.pit_lane_json（{circuit_id}）")
    else:
        print("（未写入；加 --commit 落地）")


if __name__ == "__main__":
    main()
