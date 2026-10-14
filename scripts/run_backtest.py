"""F1 预测回测记分板。

    python scripts/run_backtest.py            # 完整记分板
    python scripts/run_backtest.py --sweep    # 额外跑 Elo 超参敏感性
    python scripts/run_backtest.py --brief    # 只看自检

回答一个问题：**在 2018–2025 的数据里，到底有没有可提取的预测信号？**
做法是先钉死 L0 零假设，再看 L1 Elo 有没有增量，最后验这些增量是不是噪声。

注意：所有预测器都以**工厂**（无参 lambda）形式传入，每次回测重新构造。
预测器是有状态的，复用实例会静默泄漏。
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.backtest import (  # noqa: E402
    format_accuracy, format_table, load_races, make_context, practical_accuracy,
    run_backtest, spearman, summarize,
)
from src.model.predictors import (  # noqa: E402
    AdjustedGridBaseline, CircuitHistoryBaseline, EloPredictor, GridBaseline,
    PointsBaseline, PracticePaceBaseline, PrevFinishBaseline, QualiGapBaseline,
    RandomBaseline, RankBlend, best_post, best_pre,
)

CTX_CN = {"pre_quali": "排位赛前（不知道发车格）", "post_quali": "排位赛后（知道发车格）"}
RULE = "─" * 78


def penalty_subsets(races) -> tuple[set[str], set[str]]:
    """按「发车罚退」切分场次。

    返回 (有罚退场次的 key 集合, 罚退条目列表)。pen = grid − quali_pos > 0 表示
    自己被罚退（grid=0 维修区起步另算，不计入）。只有 pen>=3 才算「实质罚退」——
    实测对 pen=1~2 做修正反而有害。

    用途：best_post 里的 AdjustedGridBaseline 专门修这个偏差，本函数提供验证子集。
    """
    touched, entries = set(), []
    for rc in races:
        hit = False
        for e in rc.entries:
            qp = rc.quali_pos.get(e.driver)
            if qp is None or e.grid is None or e.grid <= 0:
                continue
            pen = e.grid - qp
            if pen >= 3:
                hit = True
                entries.append((rc.key, e.driver, pen))
        if hit:
            touched.add(rc.key)
    return touched, entries



def l0_predictors() -> list[tuple[str, object]]:
    return [
        ("L0 随机（自检用）", lambda: RandomBaseline()),
        ("L0 发车格顺序", lambda: GridBaseline()),
        ("L0 赛前积分榜", lambda: PointsBaseline()),
        ("L0 上一站名次", lambda: PrevFinishBaseline()),
        ("L0 该赛道历史名次", lambda: CircuitHistoryBaseline()),
    ]


def pooled_grid_rho(races) -> float:
    """把发车格基线池化后算一次 Spearman —— 用来和项目既有基准 0.622 对账。

    既有 0.622 是**池化**口径（3413 行一起算），本框架主指标是逐场算 ρ 再平均。
    两者含义不同，这里给出池化值以便可比。
    """
    a, b = [], []
    for race in races:
        ok = sorted((e for e in race.entries if e.grid and e.grid > 0),
                    key=lambda e: e.grid)
        for i, e in enumerate(ok):
            a.append(i + 1)
            b.append(race.truth[e.driver].position)
    return spearman(a, b)


def paired_compare(races, factory_a, factory_b, context: str,
                   col: str = "rho_all") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """逐场配对比较 B 相对 A 的增量。

    只看总均值不够：+0.03 的提升也可能整个来自某一年的运气。
    这里给出逐场差值的 t 统计量与胜负场次，用来判断增益是不是噪声。
    """
    da = run_backtest(races, factory_a, context=context)
    db = run_backtest(races, factory_b, context=context)
    m = da[["key", col]].merge(db[["key", col]], on="key", suffixes=("_a", "_b"))
    diff = (m[f"{col}_b"] - m[f"{col}_a"]).dropna()
    n = len(diff)
    if n < 3:
        return {"n": n}, da, db
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / math.sqrt(n))
    return {
        "n": n, "mean": mean, "se": se,
        "t": mean / se if se else float("nan"),
        "win": float((diff > 0).mean()), "lose": float((diff < 0).mean()),
        "tie": float((diff == 0).mean()),
    }, da, db


def per_year(df_a: pd.DataFrame, df_b: pd.DataFrame, col: str = "rho_all") -> str:
    """逐年对比 A / B 的 ρ，看增益是稳定的还是集中在某一年。"""
    m = df_a.merge(df_b, on="key", suffixes=("_a", "_b"))
    ycol = "year_a" if "year_a" in m.columns else "year"
    g = m.groupby(ycol)[[f"{col}_a", f"{col}_b"]].mean()
    lines = [f"  {'年份':<6}{'A':>9}{'B':>9}{'Δ':>9}   场次"]
    for y, r in g.iterrows():
        cnt = int((m[ycol] == y).sum())
        d = r[f"{col}_b"] - r[f"{col}_a"]
        flag = "  ↑" if d > 0.01 else ("  ↓" if d < -0.01 else "  ·")
        lines.append(f"  {y:<6}{r[f'{col}_a']:>9.4f}{r[f'{col}_b']:>9.4f}"
                     f"{d:>+9.4f}   {cnt:>3}{flag}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true", help="只输出自检")
    ap.add_argument("--sweep", action="store_true", help="额外跑 Elo 超参敏感性")
    args = ap.parse_args()

    t0 = time.time()
    races = load_races()
    years = sorted({r.year for r in races})
    print(f"\n{'=' * 78}")
    print(f" F1 预测回测 · {years[0]}–{years[-1]} · {len(races)} 场正赛")
    print(f"{'=' * 78}")

    # ── L0 零假设 ────────────────────────────────────────────
    boards: dict[str, pd.DataFrame] = {}
    for ctx in ("pre_quali", "post_quali"):
        print(f"\n■ L0 零假设 · {CTX_CN[ctx]}")
        print(RULE)
        rows = []
        for label, factory in l0_predictors():
            df = run_backtest(races, factory, context=ctx)
            boards[f"{ctx}|{label}"] = df
            rows.append(summarize(df, label=label))
        print(format_table(rows))

    # ── 自检 ─────────────────────────────────────────────────
    print(f"\n■ 框架自检（这几条不过，后面所有数字都不可信）")
    print(RULE)
    rnd = boards["pre_quali|L0 随机（自检用）"]
    grid_pre = boards["pre_quali|L0 发车格顺序"]
    grid_post = boards["post_quali|L0 发车格顺序"]
    pool = pooled_grid_rho(races)
    print(f"  随机 ρ = {rnd['rho_all'].mean():+.4f}"
          f"（期望 ≈ 0）{'✅' if abs(rnd['rho_all'].mean()) < 0.02 else '❌'}"
          f"   猜中冠军 {rnd['top1'].mean() * 100:.1f}%（期望 ≈ 5.0%）"
          f"{'✅' if abs(rnd['top1'].mean() - 0.05) < 0.02 else '❌'}")
    print(f"  发车格 池化 ρ = {pool:.4f}（项目既有基准 0.622）"
          f"{'✅' if abs(pool - 0.622) < 0.02 else '❌'}"
          f"   逐场平均口径 {grid_post['rho_all'].mean():.4f}")
    print(f"  剥离生效：排位赛前模式下发车格基线 ρ = {grid_pre['rho_all'].mean():+.4f}"
          f"（退化成按车手名排序）{'✅' if grid_pre['rho_all'].mean() < 0 else '❌'}")
    f_elo = lambda: EloPredictor(use_team=True)  # noqa: E731
    same = run_backtest(races, f_elo, context="pre_quali").equals(
        run_backtest(races, f_elo, context="pre_quali"))
    print(f"  重入一致性：同一工厂跑两遍结果逐行相同 {'✅' if same else '❌'}"
          f"   （预测器有状态，必须每次重建）")
    pre_ctx = [make_context(r, "pre_quali") for r in races]
    post_ctx = [make_context(r, "post_quali") for r in races]
    iso_pre = all(not c.quali_gap and all(e.grid is None for e in c.entries)
                  for c in pre_ctx)
    n_fp = sum(1 for c in pre_ctx if c.fp)
    n_gap = sum(1 for c in post_ctx if c.quali_gap)
    deg = sum(1 for c in pre_ctx if QualiGapBaseline().predict(c) != sorted(c.drivers))
    print(f"  信息隔离：pre_quali 剥掉发车格与排位秒差 {'✅' if iso_pre else '❌'}"
          f"   练习赛保留 {n_fp}/{len(races)} 场（FP 早于排位赛，合法）")
    print(f"            post_quali 暴露排位秒差 {n_gap}/{len(races)} 场"
          f"（2020 R16 Sakhir 上游无成绩）")
    print(f"            排位秒差基线在 pre_quali 下退化为纯车手名排序："
          f"例外 {deg} 场 {'✅' if deg == 0 else '❌'}"
          f"   （证明它确实拿不到秒差数据）")
    # AdjustedGridBaseline 依赖 quali_pos，排位赛前也必须拿不到
    adj = AdjustedGridBaseline(alpha=0.75, min_pen=3)
    deg_adj = sum(1 for c in pre_ctx if adj.predict(c) != sorted(c.drivers))
    n_qpos = sum(1 for c in post_ctx if c.quali_pos)
    iso_qpos = all(not c.quali_pos for c in pre_ctx)
    n_pen = sum(1 for rc in races
                for e in rc.entries
                if rc.quali_pos.get(e.driver) is not None
                and e.grid is not None and e.grid - rc.quali_pos[e.driver] >= 3)
    print(f"            罚退收缩基线在 pre_quali 下同样退化为纯车手名排序："
          f"例外 {deg_adj} 场 {'✅' if deg_adj == 0 else '❌'}"
          f"   （post_quali 暴露 quali_pos {n_qpos}/{len(races)} 场 "
          f"{'✅' if iso_qpos and n_qpos else '❌'}，其中 {n_pen} 条实质罚退）")

    if args.brief:
        print(f"\n（用时 {time.time() - t0:.1f}s）")
        return 0

    # ── L1 Elo ───────────────────────────────────────────────
    print(f"\n■ L1 Elo")
    print(RULE)
    ELO_VARIANTS = [
        ("L1 Elo(车手+车队)", lambda: EloPredictor(use_team=True, driver_share=0.7)),
        ("L1 Elo(仅车手)", lambda: EloPredictor(use_team=False, driver_share=1.0)),
    ]
    for ctx in ("pre_quali", "post_quali"):
        print(f"\n  {CTX_CN[ctx]}")
        rows = []
        for label, factory in ELO_VARIANTS:
            df = run_backtest(races, factory, context=ctx)
            rows.append(summarize(df, label=label))
            rows.append(summarize(df, label=label + "  [2019起]", drop_years={2018}))
        print(format_table(rows))

    # ── L2 新信号 ────────────────────────────────────────────
    print(f"\n■ L2 新信号 · 练习赛与排位赛秒差（数据一直在库里，模型此前从未使用）")
    print(RULE)
    print("\n  排位赛前 · 练习赛合法（FP1–FP3 都在排位赛之前）")
    pre_rows = []
    for label, fac in [
        ("L0 赛前积分榜", lambda: PointsBaseline()),
        ("L2 练习赛最快圈", lambda: PracticePaceBaseline()),
        ("L1 Elo(含退赛)", lambda: EloPredictor(k=192, use_team=True)),
        ("L1 Elo(仅完赛者)", lambda: EloPredictor(k=192, use_team=True,
                                                  dnf_policy="finishers_only")),
        ("积分榜 + 练习赛", lambda: RankBlend(
            [(PointsBaseline(), 0.5), (PracticePaceBaseline(), 0.5)], "b1")),
        ("Elo + 积分榜 + 练习赛", best_pre),
    ]:
        pre_rows.append(summarize(run_backtest(races, fac, context="pre_quali"),
                                  label=label))
    print(format_table(pre_rows))

    print("\n  排位赛后 · 排位秒差合法（发车格看不出的速度差）")
    post_rows = []
    for label, fac in [
        ("L0 发车格顺序", lambda: GridBaseline()),
        ("L2 排位赛秒差", lambda: QualiGapBaseline()),
        ("发车格 + 秒差", lambda: RankBlend(
            [(GridBaseline(), 0.3), (QualiGapBaseline(), 0.7)], "b2")),
        ("发车格 + 秒差 + Elo", best_post),
    ]:
        post_rows.append(summarize(run_backtest(races, fac, context="post_quali"),
                                   label=label))
    print(format_table(post_rows))
    print(f"\n  当前上限：排位赛前 {pre_rows[-1]['rho_all']:.4f}"
          f"（基线 {pre_rows[0]['rho_all']:.4f}，"
          f"Δ {pre_rows[-1]['rho_all'] - pre_rows[0]['rho_all']:+.4f}）"
          f"　排位赛后 {post_rows[-1]['rho_all']:.4f}"
          f"（基线 {post_rows[0]['rho_all']:.4f}，"
          f"Δ {post_rows[-1]['rho_all'] - post_rows[0]['rho_all']:+.4f}）")
    print("  注：Elo 一律用 finishers_only —— 退赛者不参与评分更新，"
          "把可靠性噪声挡在速度之外。")

    # ── 增量检验：Elo 是否带来发车格之外的信息 ───────────────
    print(f"\n■ 增量检验 · 排位赛后：发车格与 Elo 按名次加权融合")
    print(RULE)
    blend_rows = []
    for w in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0):
        factory = (lambda w=w: RankBlend(
            [(GridBaseline(), w), (EloPredictor(use_team=True), 1.0 - w)],
            f"发车格×{w:.1f} + Elo×{1 - w:.1f}"))
        rows = summarize(run_backtest(races, factory, context="post_quali"),
                         label=f"发车格×{w:.1f} + Elo×{1 - w:.1f}")
        blend_rows.append(rows)
    print(format_table(blend_rows))
    base, best = blend_rows[0], max(blend_rows, key=lambda r: r["rho_all"])
    print(f"\n  纯发车格 ρ = {base['rho_all']:.4f}  →  最优 {best['label']} = "
          f"{best['rho_all']:.4f}   Δρ = {best['rho_all'] - base['rho_all']:+.4f}")

    # ── 显著性检验 ───────────────────────────────────────────
    print(f"\n■ 显著性检验 · 这些增益是信号，还是 173 场的运气？")
    print(RULE)
    CASES = [
        ("排位赛前：Elo 仅完赛者更新 vs 含退赛", "pre_quali",
         lambda: EloPredictor(k=192, use_team=True),
         lambda: EloPredictor(k=192, use_team=True, dnf_policy="finishers_only"),
         "L1 Elo(含退赛)", "L1 Elo(仅完赛者)"),
        ("排位赛前：加练习赛 vs 赛前积分榜", "pre_quali",
         lambda: PointsBaseline(),
         lambda: RankBlend([(PointsBaseline(), 0.5), (PracticePaceBaseline(), 0.5)], "b"),
         "L0 赛前积分榜", "积分榜+练习赛"),
        ("排位赛后：加排位秒差 vs 纯发车格", "post_quali",
         lambda: GridBaseline(),
         lambda: RankBlend([(GridBaseline(), 0.3), (QualiGapBaseline(), 0.7)], "b"),
         "L0 发车格顺序", "发车格+秒差"),
        ("排位赛前：Elo(默认 k=24) vs 赛前积分榜", "pre_quali",
         lambda: PointsBaseline(), lambda: EloPredictor(use_team=True, driver_share=0.7),
         "L0 赛前积分榜", "L1 Elo(车手+车队)"),
        ("排位赛前：Elo(k=64, 仅完赛者更新) vs 赛前积分榜", "pre_quali",
         lambda: PointsBaseline(),
         lambda: EloPredictor(k=64, use_team=True, dnf_policy="finishers_only"),
         "L0 赛前积分榜", "L1 Elo(k=64)"),
        ("排位赛后：融合(0.6格+0.4Elo) vs 纯发车格", "post_quali",
         lambda: GridBaseline(),
         lambda: RankBlend([(GridBaseline(), 0.6), (EloPredictor(use_team=True), 0.4)], "b"),
         "L0 发车格顺序", "L1 融合"),
        ("排位赛后：融合(0.6格+0.4Elo k=64) vs 纯发车格", "post_quali",
         lambda: GridBaseline(),
         lambda: RankBlend([(GridBaseline(), 0.6),
                            (EloPredictor(k=64, use_team=True,
                                          dnf_policy="finishers_only"), 0.4)], "b"),
         "L0 发车格顺序", "L1 融合(k=64)"),
    ]
    for title, ctx, fa, fb, na, nb in CASES:
        r, da, db = paired_compare(races, fa, fb, ctx)
        print(f"\n  {title}")
        print(f"    逐场 Δρ = {r['mean']:+.4f}  (SE {r['se']:.4f}, t = {r['t']:+.2f}, n = {r['n']})"
              f"   {'✅ 显著 (|t|>2)' if abs(r['t']) > 2 else '⚠️ 未达显著'}")
        print(f"    胜/负/平 = {r['win'] * 100:.1f}% / {r['lose'] * 100:.1f}%"
              f" / {r['tie'] * 100:.1f}%")
        print(f"    冠军均预测名次  {na} {da['winner_rank'].mean():.2f}"
              f"  →  {nb} {db['winner_rank'].mean():.2f}")
        print(per_year(da, db))

    # ── 罚退场景专项验证 ─────────────────────────────────────
    print(f"\n■ 罚退场景 · 「发车格 = 速度」这个假设在罚退时会失效")
    print(RULE)
    touched, pen_idx = penalty_subsets(races)
    print(f"  有实质罚退（pen≥3）的场次 {len(touched)} / {len(races)} 场，"
          f"罚退条目 {len(pen_idx)} 条")
    print(f"  语义：pen = grid − quali_pos > 0 表示自己被罚退。"
          f"被罚退者实际发车很远，但速度没变。")

    fin_map = {(rc.key, e.driver): rc.truth[e.driver].finished
               for rc in races for e in rc.entries}
    act = {(rc.key, e.driver): rc.truth[e.driver].position
           for rc in races for e in rc.entries}

    def _preds_of(factory) -> dict:
        p = factory()
        out: dict = {}
        for rc in races:
            out[rc.key] = {d: i + 1
                           for i, d in enumerate(p.predict(make_context(rc, "post_quali")))}
            p.observe(rc)
        return out

    def _blend(grid_fac):
        def f():
            return RankBlend([(grid_fac(), 0.4), (QualiGapBaseline(), 0.3),
                              (EloPredictor(k=192, use_team=True,
                                            dnf_policy="finishers_only"), 0.3)], "b")
        return f

    P_plain = _preds_of(_blend(lambda: GridBaseline()))
    P_adj = _preds_of(best_post)

    rows_fin = [(k, d, pen) for k, d, pen in pen_idx if fin_map.get((k, d))]

    def _errs(P, sel):
        e, b = [], []
        for k, d, _p in sel:
            if d not in P.get(k, {}):
                continue
            e.append(abs(P[k][d] - act[(k, d)]))
            b.append(P[k][d] - act[(k, d)])
        return e, b

    print(f"\n  逐条目诊断（罚退≥3 且完赛，n={len(rows_fin)}）")
    print(f"    {'发车格分量':<14}{'平均绝对误差':>14}{'平均偏差':>12}{'重罚≥10误差':>14}")
    for lab, P in (("纯 GridBaseline", P_plain), ("AdjustedGrid", P_adj)):
        e, b = _errs(P, rows_fin)
        eb, _ = _errs(P, [r for r in rows_fin if r[2] >= 10])
        print(f"    {lab:<14}{statistics.mean(e):>12.2f}位"
              f"{statistics.mean(b):>+11.2f}位"
              f"{statistics.mean(eb):>12.2f}位")
    print("    （平均偏差为正 = 模型系统性低估了被罚退者的实力）")

    e0, _ = _errs(P_plain, rows_fin)
    e1, _ = _errs(P_adj, rows_fin)
    diffs = [b - a for a, b in zip(e0, e1) if a == a and b == b]
    if len(diffs) >= 3:
        mean = statistics.mean(diffs)
        se = statistics.stdev(diffs) / math.sqrt(len(diffs))
        t = mean / se if se else float("nan")
        print(f"\n  逐条目配对检验：Δ|误差| = {mean:+.3f} 位  "
              f"t = {t:+.2f}  n = {len(diffs)}  "
              f"{'✅ 显著 (|t|>2)' if abs(t) > 2 else '⚠️ 未达显著'}"
              f"   改善占比 {sum(1 for d in diffs if d < 0) / len(diffs) * 100:.0f}%")

    # 零影响验证：没有实质罚退的场次必须逐行完全一致
    da = run_backtest(races, _blend(lambda: GridBaseline()), context="post_quali")
    db2 = run_backtest(races, best_post, context="post_quali")
    m = da[["key", "rho_all"]].merge(db2[["key", "rho_all"]], on="key",
                                     suffixes=("_a", "_b"))
    m = m[~m["key"].isin(touched)]
    maxdev = float((m["rho_all_a"] - m["rho_all_b"]).abs().max())
    print(f"\n  零影响验证：无实质罚退的 {len(m)} 场中，ρ 最大偏差 = {maxdev:.2e}  "
          f"{'✅ 逐行一致' if maxdev < 1e-12 else '❌ 有影响'}")
    print(f"  全量对比：ρ {da['rho_all'].mean():.4f} → {db2['rho_all'].mean():.4f}"
          f"   冠军入前3 {da['top3'].mean() * 100:.1f}% → {db2['top3'].mean() * 100:.1f}%"
          f"   猜中冠军 {da['top1'].mean() * 100:.1f}% → {db2['top1'].mean() * 100:.1f}%")
    print("  结论：只修「被罚退者被系统性低估」这个偏差，不改变整体排序。")

    # ── ρ 到底意味着什么 ─────────────────────────────────────
    print(f"\n■ ρ 到底意味着什么 · 把抽象相关度翻译成「能对到什么程度」")
    print(RULE)
    ACC = [
        ("排位赛后 · 纯发车格（基线）", "post_quali", lambda: GridBaseline()),
        ("排位赛后 · 发车格+秒差+Elo（当前最佳）", "post_quali", best_post),
        ("排位赛前 · 赛前积分榜（基线）", "pre_quali", lambda: PointsBaseline()),
        ("排位赛前 · Elo+积分榜+练习赛（当前最佳）", "pre_quali", best_pre),
    ]
    for label, ctx, factory in ACC:
        print(format_accuracy(practical_accuracy(races, factory, context=ctx), label))
        print()

    # ── Elo 超参敏感性 ───────────────────────────────────────
    if args.sweep:
        print(f"\n■ Elo 超参敏感性 · 排位赛前（无发车格，最考验 Elo）")
        print(RULE)
        for policy in ("as_position", "finishers_only"):
            rows = []
            for k in (8, 16, 24, 40, 64, 96, 128, 192, 256):
                factory = (lambda k=k, p=policy: EloPredictor(k=k, dnf_policy=p))
                rows.append(summarize(run_backtest(races, factory, context="pre_quali"),
                                      label=f"k={k:<3} {policy}"))
            print(f"\n  dnf_policy = {policy}")
            print(format_table(rows))

    print(f"\n（用时 {time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
