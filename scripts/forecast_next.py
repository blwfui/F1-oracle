"""对「下一站」做赛前预测（该站尚未发生，库里没有它的成绩）。

用法：
    python -m scripts.forecast_next 2026

⚠️ 与回测最大的区别：练习赛与排位赛**都还没发生**，所以本站可用的合法信号
   只有【Elo(车手+车队) + 赛前积分榜】。绝不能把 PracticePaceBaseline 混进来
   —— 它拿不到数据时会退化成「按车手名排序」，等于用一个噪声信号稀释真实信号。
   （best_pre() 是三信号融合，专供「周六练习赛已跑完」的场景。）

阵容来自最近一场正赛的参赛名单（假设车手/车队不变），这是本站唯一可得的阵容信息。
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.model.backtest import Entry, Race, load_races, make_context  # noqa: E402
from src.model.predictors import EloPredictor, PointsBaseline, RankBlend  # noqa: E402
from src.model.teams import canonical_team  # noqa: E402

sys.path.insert(0, str(ROOT / "src" / "dashboard"))
from names_cn import auto_cn_short  # noqa: E402

DB_PATH = ROOT / "data" / "f1_oracle.db"


def next_round(year: int):
    """该赛季「有赛程但还没有成绩」的最小轮次。"""
    db = sqlite3.connect(str(DB_PATH))
    have = {r for (r,) in db.execute(
        "SELECT DISTINCT round FROM results WHERE year=?", (year,))}
    sched = db.execute(
        "SELECT round, event_name, location, event_date FROM events"
        " WHERE year=? AND round>0 ORDER BY round", (year,)).fetchall()
    db.close()
    for rn, name, loc, dt in sched:
        if rn not in have:
            return rn, name, loc, dt
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    args = ap.parse_args()

    year = args.year
    nxt = next_round(year)
    if not nxt:
        print(f"{year} 赛季已全部完成，没有可预测的下一站")
        return
    rn, name, loc, dt = nxt

    races = load_races()
    done = [r for r in races if r.year == year]
    last = max(done, key=lambda r: r.round)
    print(f"赛季：{year}｜已完赛 {len(done)} 站（最新 {last.key} {last.location}）")
    print(f"本次预测：R{rn} {name} · {loc} · {dt}")
    print("预测时点：排位赛前（练习赛与排位赛均未发生）")
    print(f"阵容来源：{last.key} 的参赛名单，共 {len(last.entries)} 位车手（假设不变）")
    print("可用信号：Elo(车手+车队, finishers_only) 50% + 赛前积分榜 50%")
    print("⚠️ 不能加练习赛：本站 FP 还没跑，拿不到数据会退化成按车手名排序")

    # ── 用全历史（含本赛季已完成站）喂养两个信号 ──────────────
    elo = EloPredictor(k=192, use_team=True, dnf_policy="finishers_only")
    pts = PointsBaseline()
    blend = RankBlend([(elo, 0.5), (pts, 0.5)], "Elo+积分榜")
    for r in races:
        elo.observe(r)
        pts.observe(r)

    # ── 构造下一站的上下文（无 fp / 无排位成绩） ───────────────
    entries = [Entry(e.driver, e.full_name, e.team, None) for e in last.entries]
    synth = Race(year=year, round=rn, event_name=name, location=loc,
                 circuit_id=loc, entries=entries, truth={}, sprint_points={})
    ctx = make_context(synth, "pre_quali")

    order_elo = elo.predict(ctx)
    order_pts = pts.predict(ctx)
    order = blend.predict(ctx)

    r_elo = {d: i + 1 for i, d in enumerate(order_elo)}
    r_pts = {d: i + 1 for i, d in enumerate(order_pts)}

    name_of = {e.driver: e.full_name for e in entries}
    team_of = {e.driver: e.team for e in entries}

    print("\n" + "═" * 88)
    print(f"  {year} R{rn} 赛前预测 · {name}（{loc}）")
    print("═" * 88)
    print(f"  {'#':>3}  {'车手':<20}{'车队':<20}{'Elo强度':>9}{'积分':>7}"
          f"{'Elo名次':>9}{'积分名次':>9}")
    print("  " + "─" * 84)
    for i, d in enumerate(order, 1):
        cn = auto_cn_short(d, name_of[d])
        print(f"  {i:>3}  {cn:<20}{team_of[d]:<20}"
              f"{elo.strength(d, team_of[d]):>9.1f}{pts.pts.get((year, d), 0.0):>7.0f}"
              f"{r_elo[d]:>9}{r_pts[d]:>9}")

    # ── 两个信号分歧最大的车手 = 最值得关注的地方 ───────────────
    gaps = sorted((abs(r_elo[d] - r_pts[d]), d) for d in order)[::-1][:5]
    print("\n  两个信号分歧最大的 5 位（Elo 看法 vs 积分榜看法）")
    for g, d in gaps:
        print(f"    {auto_cn_short(d, name_of[d]):<20} Elo 第 {r_elo[d]:>2} 名"
              f" ｜ 积分榜第 {r_pts[d]:>2} 名 ｜ 差 {g} 位")

    # ── 车队 Elo ─────────────────────────────────────────────────
    # ⚠️ 这是**相对车手的残差**，不是赛车的纯速度：一队两台车，车手与赛车的贡献
    #    无法分离，driver_share 决定这两份账怎么记（0.7 → 车手七成、车队三成）。
    #    它不该被拿来论证某位车手「该排第几」（详见 predictors.EloPredictor）。
    teams = sorted({canonical_team(e.team) for e in entries},
                   key=lambda t: -elo.team.get(t, elo.base))
    print("\n  车队 Elo（按**物理车队**累计：Force India → Racing Point → Aston Martin 是一支队）")
    for t in teams:
        v = elo.team.get(t, elo.base)
        bar = "█" * max(0, int((v - 1400) / 8))
        print(f"    {t:<20}{v:>7.1f}  {bar}")

    print("\n  ⚠️ 上面「Elo强度」= 车手分 +（车队分 − 1500）。两个分量出自同一模型、")
    print("     互相补偿，**不可相加来论证名次** —— 车队分是相对车手的残差：")
    print("     车手分越高，同样的成绩越会被算作「车不行」。实测 driver_share")
    print("     对预测几乎无影响（k=192 下 0.5→0.9，ρ 跨度仅 0.0035），它决定的是")
    print("     哪张表更忠实，不是谁更强。")


if __name__ == "__main__":
    main()
