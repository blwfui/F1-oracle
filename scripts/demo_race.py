"""一场比赛的完整流程演示：赛前 → 排位赛后 → 逐圈 → 赛后实际。

    python -m scripts.demo_race 2022 16            # 全部四段
    python -m scripts.demo_race 2022 16 --phase 3  # 只看第三段（逐圈）

防泄漏纪律
----------
赛前 / 排位赛后的预测**只喂本场之前的比赛**（`races[:idx]`），
逐圈分析只用「当圈为止」的数据。演示的是流程，不是事后诸葛。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model import cleanlap  # noqa: E402
from src.model.backtest import load_races, make_context, score_round  # noqa: E402
from src.model.lapdata import load_laptimelines  # noqa: E402
from src.model.predictors import best_post, best_pre  # noqa: E402

DB_PATH = ROOT / "data" / "f1_oracle.db"
RULE = "=" * 78

_CN = None


def cn(code: str, full: str = "") -> str:
    global _CN
    if _CN is None:
        sys.path.insert(0, str(ROOT / "src" / "dashboard"))
        try:
            from names_cn import auto_cn_short
            _CN = auto_cn_short
        except Exception:  # noqa: BLE001
            _CN = lambda c, f: c  # noqa: E731
    return _CN(code, full)


def head(title: str) -> None:
    print("\n" + RULE)
    print(f" {title}")
    print(RULE)


def predict_for(races, idx: int, factory, context: str):
    """严格防泄漏：只 observe 本场之前的比赛。"""
    p = factory()
    for r in races[:idx]:
        p.observe(r)
    ctx = make_context(races[idx], context)
    return p.predict(ctx), ctx


def asof_points(db, year: int, rnd: int) -> dict[str, float]:
    """本场之前的车手积分（正赛 + 冲刺），用于展示赛前形势。"""
    pts: dict[str, float] = {}
    for d, p in db.execute(
            "SELECT driver, SUM(points) FROM results WHERE year=? AND round<? GROUP BY driver",
            (year, rnd)):
        pts[d] = pts.get(d, 0) + float(p or 0)
    for d, p in db.execute(
            "SELECT driver, SUM(points) FROM sprint_points WHERE year=? AND round<? GROUP BY driver",
            (year, rnd)):
        pts[d] = pts.get(d, 0) + float(p or 0)
    return pts


def phase1(db, races, idx, target) -> None:
    head(f"① 赛前分析 · {target.year} R{target.round} {target.event_name}")
    pts = asof_points(db, target.year, target.round)
    print(f"\n  【赛前形势】{target.year} 赛季第 {target.round} 站，此前积分榜：")
    for i, (d, p) in enumerate(sorted(pts.items(), key=lambda x: -x[1])[:5], 1):
        full = next((e.full_name for e in target.entries if e.driver == d), "")
        print(f"     {i}. {cn(d, full):<16} {p:>6.1f} 分")

    order, ctx = predict_for(races, idx, best_pre, "pre_quali")
    print("\n  【模型预测】赛前口径（只有赛季数据 + 练习赛，不知道发车格）：")
    print(f"     {'预测名次':<10}{'车手':<18}")
    for i, d in enumerate(order[:10], 1):
        full = next((e.full_name for e in ctx.entries if e.driver == d), "")
        print(f"     P{i:<9}{cn(d, full):<18}")
    print(f"\n  → 模型认为的冠军热门：{cn(order[0])}")


def phase2(db, races, idx, target) -> None:
    head(f"② 排位赛后 · {target.year} R{target.round} {target.event_name}")
    # 注意：sessions 表只存 FP1–FP3，排位赛成绩在 results 表（quali_pos + q1/q2/q3_sec）。
    rows = db.execute(
        "SELECT driver, quali_pos, q1_sec, q2_sec, q3_sec, grid FROM results "
        "WHERE year=? AND round=? AND quali_pos IS NOT NULL ORDER BY quali_pos",
        (target.year, target.round)).fetchall()
    qtime = {r[0]: (r[4] or r[3] or r[2]) for r in rows}
    pole = qtime.get(rows[0][0]) if rows else None

    print("\n  【排位赛成绩】() 内为落后杆位秒数")
    for d, qpos, _q1, _q2, q3, grid in rows[:10]:
        t = qtime.get(d)
        gap = f"({t - pole:+.3f})" if (t and pole) else ""
        pen = f"  ⚠️ 发车 P{grid}（退 {grid - qpos} 位）" if grid and grid > qpos else ""
        mark = "  ← 杆位" if qpos == 1 else ""
        print(f"     Q{qpos:<3} {cn(d):<16} {t if t else 0:>9.3f}s {gap:<11}{pen}{mark}")

    penalized = [(d, qpos, g) for d, qpos, _a, _b, _c, g in rows
                 if g and qpos and g > qpos]
    if penalized:
        print(f"\n  【发车格罚退】共 {len(penalized)} 台车：")
        for d, q, g in sorted(penalized, key=lambda x: x[1]):
            print(f"     {cn(d):<16} 排位 Q{q} → 发车 P{g}   （退 {g - q} 位）")

    order, ctx = predict_for(races, idx, best_post, "post_quali")
    print("\n  【模型预测】排位赛后口径（发车格 + 排位秒差 + Elo）：")
    print(f"     {'预测名次':<10}{'车手':<18}")
    for i, d in enumerate(order[:10], 1):
        full = next((e.full_name for e in ctx.entries if e.driver == d), "")
        print(f"     P{i:<9}{cn(d, full):<18}")
    print(f"\n  → 模型认为的冠军热门：{cn(order[0])}")

    order_pre, _ = predict_for(races, idx, best_pre, "pre_quali")
    shift = {d: order_pre.index(d) + 1 - (order.index(d) + 1)
             for d in order if d in order_pre}
    big = sorted(shift.items(), key=lambda x: -abs(x[1]))[:3]
    print("  排位赛后相对赛前的最大调整：")
    for d, s in big:
        arrow = "↑" if s > 0 else "↓"
        print(f"     {cn(d):<16} {arrow} 调整 {abs(s)} 位（现第 {order.index(d) + 1}）")


def phase3(db, year: int, rnd: int) -> None:
    tl = next((t for t in load_laptimelines(year) if t.round == rnd), None)
    if tl is None:
        print(f"  未找到 {year} R{rnd}")
        return
    head(f"③ 正赛逐圈 · {tl.total_laps} 圈 · 在跑 {len(tl.final)} 人")

    sc = [L for L in sorted(tl.states) if tl.is_neutralized(L)]
    if sc:
        groups, cur = [], [sc[0]]
        for L in sc[1:]:
            if L == cur[-1] + 1:
                cur.append(L)
            else:
                groups.append(cur)
                cur = [L]
        groups.append(cur)
        seg = "  ".join(f"第{g[0]}–{g[-1]}圈" for g in groups)
        print(f"\n  【比赛中断】安全车/虚拟安全车：{seg}")

    print("\n  【领先者变化】")
    prev = None
    for L in sorted(tl.states):
        pos = tl.positions(L)
        if not pos:
            continue
        lead = min(pos, key=lambda d: pos[d])
        if lead != prev:
            g = tl.gaps(L).get(lead, 0.0)
            tag = "  ← 安全车下" if tl.is_neutralized(L) else ""
            print(f"     第 {L:>2} 圈  {cn(lead):<16}{tag}")
            prev = lead

    win = next((d for d in tl.final if tl.final[d].position == 1), None)
    if win:
        print(f"\n  【冠军 {cn(win)} 的位置轨迹】")
        marks = [1, 5, 10, 15, 20, 25, 30, 35, 40, tl.total_laps]
        marks = [m for m in marks if m <= tl.total_laps]
        row = []
        for L in marks:
            p = tl.positions(L).get(win)
            row.append(f"L{L}:P{p if p else '—'}")
        print("     " + "  ".join(row))

    print("\n  【最混乱的圈】单圈名次变动人数最多：")
    swings = []
    laps_sorted = sorted(tl.states)
    for a, b in zip(laps_sorted, laps_sorted[1:]):
        p0, p1 = tl.positions(a), tl.positions(b)
        common = set(p0) & set(p1)
        n = sum(1 for d in common if p0[d] != p1[d])
        swings.append((n, b))
    for n, L in sorted(swings, reverse=True)[:4]:
        tag = "（安全车）" if tl.is_neutralized(L) else ""
        print(f"     第 {L:>2} 圈  {n} 人位置变动 {tag}")

    mid = max(5, tl.total_laps // 2)
    print(f"\n  【第 {mid} 圈状态】领先集团 + 追赶可行性")
    pos, ga, pace = tl.positions(mid), tl.gap_ahead(mid), tl.recent_pace(mid, 6)
    order = sorted(pos, key=lambda d: pos[d])
    remain = tl.total_laps - mid
    print(f"     {'车手':<16}{'名次':>5}{'与前车':>10}{'速度差':>10}{'追上需':>8}   判定")
    for i, d in enumerate(order[:8]):
        # 窗口内进过站的车手，其近 6 圈干净圈来自【旧胎】，速度差会被低估 —— 必须标注
        window_laps = range(max(1, mid - 5), mid + 1)
        pitted = any(tl.states.get(k, {}).get(d, {}).get("is_pit") for k in window_laps)
        mark = "  ⚠️近6圈含进站(节奏取自旧胎)" if pitted else ""
        if i == 0:
            print(f"     {cn(d):<16}{'P1':>5}{'—':>10}{'—':>10}{'—':>8}{mark}")
            continue
        ahead = order[i - 1]
        if d not in ga or d not in pace or ahead not in pace:
            continue
        dp = pace[ahead] - pace[d]
        if dp <= 0.001:
            need, verdict = "—", "追不上"
        else:
            need = f"{ga[d] / dp:.0f}圈"
            verdict = "能追上" if ga[d] / dp <= remain else "来不及"
        print(f"     {cn(d):<16}{'P' + str(pos[d]):>5}{ga[d]:>9.1f}s{dp:>+9.3f}s{need:>8}   {verdict}{mark}")
    print("\n     注：速度差用「干净圈速中位数」（已排安全车/进站/冷胎/交通圈）。"
          "\n         标注 ⚠️ 的车手刚从维修区出来，新胎尚未计入，其速度差偏保守。")


def phase4(db, races, idx, target) -> None:
    order, ctx = predict_for(races, idx, best_post, "post_quali")
    truth = sorted(target.truth.items(), key=lambda x: x[1].position)
    actual = [d for d, _ in truth]
    sc = score_round(order, target)

    head(f"④ 赛后实际 · {target.year} R{target.round} {target.event_name}")
    grids = {e.driver: e.grid for e in target.entries}
    print(f"\n  {'实际名次':<10}{'车手':<18}{'发车':>5}{'预测名次':>10}{'差':>6}")
    for i, (d, t) in enumerate(truth[:10], 1):
        pr = order.index(d) + 1 if d in order else None
        diff = f"{i - pr:+d}" if pr else "—"
        full = next((e.full_name for e in target.entries if e.driver == d), "")
        g = grids.get(d)
        star = "  ← 冠军" if i == 1 else ""
        print(f"     P{i:<9}{cn(d, full):<18}{g if g else '—':>5}{pr or '—':>10}{diff:>6}{star}")

    winner = actual[0]
    print("\n  【评分】")
    print(f"     冠军：预测 {cn(winner)} 在第 {order.index(winner) + 1} 位"
          f"  →  {'命中 ✅' if order[0] == winner else '未命中 ❌'}")
    print(f"     冠军落在预测前 3：{'是 ✅' if winner in order[:3] else '否 ❌'}"
          f"   （前 5：{'是' if winner in order[:5] else '否'}）")
    print(f"     排序相关 ρ（全部 {sc['n']} 人）：{sc['rho_all']:+.4f}")
    print(f"     排序相关 ρ（仅完赛者 {sc['n_fin']} 人）：{sc['rho_fin']:+.4f}")
    print(f"     平均预测名次误差："
          f"{sum(abs(i - (order.index(d) + 1)) for i, (d, _) in enumerate(truth, 1)) / len(truth):.2f} 位")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("round", type=int)
    ap.add_argument("--phase", type=int, default=0, help="只跑某一段（1-4），默认全跑")
    args = ap.parse_args()

    races = load_races()
    idx = next((i for i, r in enumerate(races)
                if r.year == args.year and r.round == args.round), None)
    if idx is None:
        print(f"未找到 {args.year} R{args.round}")
        return 1
    target = races[idx]
    db = sqlite3.connect(str(DB_PATH))

    print(f"\n{'█' * 78}")
    print(f"  {target.year} R{target.round} · {target.event_name} · {target.location}")
    print(f"  完整流程演示：赛前 → 排位赛后 → 逐圈 → 赛后实际")
    print(f"{'█' * 78}")

    if args.phase in (0, 1):
        phase1(db, races, idx, target)
    if args.phase in (0, 2):
        phase2(db, races, idx, target)
    if args.phase in (0, 3):
        phase3(db, args.year, args.round)
    if args.phase in (0, 4):
        phase4(db, races, idx, target)
    db.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
