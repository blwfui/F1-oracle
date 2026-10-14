"""Elo vs 平均完赛名次 —— 两代「强度信号」的对照实验。

用法：
    python -m scripts.compare_strength_signals

为什么这个比较值得认真做：
    「平均完赛名次」是最直觉的强度代理（谁平均名次靠前谁强），也是最容易
    被当成"已经够好"的信号。但它有一堆隐含假设，要用数据检验而不是辩论：
      · 赛季初没数据 → 年初几站等于瞎猜（Elo 靠跨赛季延续避开了这点）
      · 退赛算不算 → 退赛者的 position 是「分类名次」11–20，含进来会把
        "运气差"记成"速度慢"
      · 没有时间衰减 → 一场两年前的比赛和上周的比赛同权

检验口径：既看整场 ρ（配对 t），也看 **per-entry** 的名次误差配对检验
—— 项目已有教训：只影响少数条目的差异，用整场 ρ 检验力不够会误判为"无效"。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.model.backtest import (  # noqa: E402
    format_table,
    load_races,
    make_context,
    run_backtest,
    summarize,
)
from src.model.predictors import (  # noqa: E402
    AvgFinishBaseline,
    EloPredictor,
    PointsBaseline,
    PracticePaceBaseline,
    RankBlend,
)

FOCUS = 2026


def elo():
    return EloPredictor(k=192, use_team=True, dnf_policy="finishers_only")


def build():
    return {
        # 待检验的主角
        "★ Elo(车手+车队)": elo,
        "平均名次·本季·含退赛": lambda: AvgFinishBaseline(window=0, include_dnf=True),
        "平均名次·本季·仅完赛": lambda: AvgFinishBaseline(window=0, include_dnf=False),
        "平均名次·近10场·含退赛": lambda: AvgFinishBaseline(window=10, include_dnf=True),
        "平均名次·近10场·仅完赛": lambda: AvgFinishBaseline(window=10, include_dnf=False),
        "平均名次·近3场·含退赛": lambda: AvgFinishBaseline(window=3, include_dnf=True),
        # 对照：两者融合、以及已知上限
        "Elo + 平均名次(近10仅完赛)": lambda: RankBlend(
            [(elo(), 0.5), (AvgFinishBaseline(window=10, include_dnf=False), 0.5)], "Elo+AF"),
        "known 上限 best_pre": lambda: RankBlend(
            [(elo(), 0.4), (PointsBaseline(), 0.3), (PracticePaceBaseline(), 0.3)], "best_pre"),
        "best_pre 换成平均名次(去Elo)": lambda: RankBlend(
            [(AvgFinishBaseline(window=10, include_dnf=False), 0.4),
             (PointsBaseline(), 0.3), (PracticePaceBaseline(), 0.3)], "AF+P+FP"),
    }


def paired_t(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """配对 t 检验：返回 (均值差, t, 胜率)。a、b 长度相同、逐元素配对。"""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    d = d[~np.isnan(d)]
    if len(d) < 3 or d.std(ddof=1) == 0:
        return float("nan"), float("nan"), float("nan")
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    return float(d.mean()), float(t), float((d > 0).mean())


def per_entry_error(pred_orders_by_key, races):
    """逐条目（场 × 车手）的绝对名次误差。"""
    recs = []
    for race in races:
        order = pred_orders_by_key.get(race.key)
        if order is None:
            continue
        rank = {d: i + 1 for i, d in enumerate(order)}
        for d, t in race.truth.items():
            if d in rank:
                recs.append((race.key, d, abs(rank[d] - t.position)))
    return pd.DataFrame(recs, columns=["key", "driver", "err"])


def main():
    races = load_races()
    hist = [r for r in races if r.year < FOCUS]
    focus = [r for r in races if r.year == FOCUS]
    print(f"载入 {len(races)} 场｜历史期 {len(hist)} 场｜观察期 {FOCUS} {len(focus)} 场")
    print("预测时点：pre_quali（排位赛前，两者都只能靠历史）\n")

    cands = build()
    rows, per_race, orders = [], {}, {}

    for label, factory in cands.items():
        df = run_backtest(races, factory, context="pre_quali")
        per_race[label] = df.set_index("key")["rho_all"].to_dict()
        rows.append(summarize(df[df.year < FOCUS], label=f"{label} ‹历史›"))
        rows.append(summarize(df[df.year == FOCUS], label=f"{label} ‹{FOCUS}›"))

        # 重跑一遍只为了留逐场预测顺序（per-entry 检验要用）
        p = factory()
        ords = {}
        for r in races:
            ords[r.key] = p.predict(make_context(r, "pre_quali"))
            p.observe(r)
        orders[label] = ords

    print(format_table(rows))

    # ── 逐场 ρ 的配对检验：Elo 作为基准 ────────────────────────
    keys_all = [r.key for r in races]
    keys_hist = [r.key for r in hist]
    keys_focus = [r.key for r in focus]

    def arr(label, keys):
        d = per_race[label]
        return np.array([d.get(k, np.nan) for k in keys])

    print("\n" + "═" * 84)
    print("  配对 t 检验：Δρ 相对于 Elo（正 = 比 Elo 好）")
    print("═" * 84)
    print(f"  {'对照组':<28}{'Δρ 历史':>10}{'t':>7}{'Δρ 2026':>10}{'t':>7}")
    print("  " + "─" * 80)
    for label in cands:
        if label.startswith("★"):
            continue
        mh, th, _ = paired_t(arr(label, keys_hist), arr("★ Elo(车手+车队)", keys_hist))
        mf, tf, _ = paired_t(arr(label, keys_focus), arr("★ Elo(车手+车队)", keys_focus))
        print(f"  {label:<28}{mh:>+10.4f}{th:>7.2f}{mf:>+10.4f}{tf:>7.2f}")

    # ── per-entry 名次误差检验（检验力更强） ───────────────────
    print("\n" + "═" * 84)
    print("  per-entry 名次误差检验（Elo 为基准；正 = 误差更小 = 更好）")
    print("═" * 84)
    e_elo_h = per_entry_error(orders["★ Elo(车手+车队)"], hist)
    e_elo_f = per_entry_error(orders["★ Elo(车手+车队)"], focus)
    print(f"  参与条目：历史 {len(e_elo_h)} ｜ {FOCUS} {len(e_elo_f)}")
    print(f"  {'对照组':<28}{'Δ|误差| 历史':>13}{'t':>7}{'Δ|误差| 2026':>14}{'t':>7}")
    print("  " + "─" * 80)
    for label in cands:
        if label.startswith("★"):
            continue
        e = per_entry_error(orders[label], hist)
        m = e_elo_h.merge(e, on=["key", "driver"], suffixes=("_a", "_b"))
        mh, th, _ = paired_t(m["err_a"].values, m["err_b"].values)
        ef = per_entry_error(orders[label], focus)
        mf = e_elo_f.merge(ef, on=["key", "driver"], suffixes=("_a", "_b"))
        m2, t2, _ = paired_t(mf["err_a"].values, mf["err_b"].values)
        print(f"  {label:<28}{mh:>+13.3f}{th:>7.2f}{m2:>+14.3f}{t2:>7.2f}")
    print("\n  注：Δ|误差| > 0 表示该信号预测的名次离真实名次更近。")


if __name__ == "__main__":
    main()
