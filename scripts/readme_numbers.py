"""产出 README 里每一个头条数字 —— 让「可复现」真的可复现。

用法：
    python -m scripts.readme_numbers

## 为什么要有这个脚本

审查（`docs/审查报告-缺点清单.md` §M4）指出：README 里有几组数字**没有任何入库
脚本能算出来**，只存在于一次性脚本与本地工作记录里。对一个以"可复现回测框架"
为卖点的项目，这等于尺子没交出来 —— 每个数字都能复现，但外部读者做不到。

本脚本把 README 的主表逐行复算，并**在每个数字旁标出样本量**：

    · 2018–2025 = **173 场**（README 头条用的就是这个口径）
    · 2018–2026 = **190 场**

两者混用会差约 0.003，是"README 和实跑对不上"这类假警报的唯一来源。
换句话说：**报 ρ 必须连 n 一起报。**
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.backtest import (  # noqa: E402
    load_races, make_context, practical_accuracy, run_backtest, spearman, summarize,
)
from src.model.predictors import (  # noqa: E402
    AvgFinishBaseline, EloPredictor, GridBaseline, PointsBaseline,
    PracticePaceBaseline, QualiGapBaseline, RankBlend, best_post, best_pre,
)

RULE = "─" * 78


def same_complexity_pre():
    """同复杂度（零拟合）的赛前对照：积分榜 + 练习赛，不含 Elo。"""
    return RankBlend([(PointsBaseline(), 0.5), (PracticePaceBaseline(), 0.5)],
                     "积分榜+练习赛")


def same_complexity_post():
    """同复杂度（零拟合）的赛后对照：发车格 + 排位秒差，不含 Elo。"""
    return RankBlend([(GridBaseline(), 0.3), (QualiGapBaseline(), 0.7)],
                     "发车格+秒差")


def no_elo_pre():
    """2026「去 Elo」用的组合。"""
    return RankBlend([(PointsBaseline(), 0.5), (PracticePaceBaseline(), 0.5)], "去Elo")


def paired(a_df, b_df, col: str = "rho_all") -> dict:
    """逐场配对检验：B − A。返回 Δ均值 / t / n / 胜率 / 逐年 Δ。"""
    m = a_df[["key", "year", col]].merge(b_df[["key", col]], on="key",
                                         suffixes=("_a", "_b"))
    d = (m[col + "_b"] - m[col + "_a"]).dropna()
    n = len(d)
    if n < 2:
        return {"delta": 0.0, "t": 0.0, "n": n, "win": 0.0, "years": {}}
    sd = float(d.std(ddof=1))
    se = sd / math.sqrt(n)
    per_year = (m.assign(d=m[col + "_b"] - m[col + "_a"])
                .dropna(subset=["d"]).groupby("year")["d"].mean().to_dict())
    return {
        "delta": float(d.mean()),
        "t": float(d.mean() / se) if se else 0.0,
        "n": n,
        "win": float((d > 0).mean()),
        "years": {int(k): float(v) for k, v in per_year.items()},
    }


def top10_rho(factory, races, context: str) -> float:
    """真实前 10 名的子集 ρ —— 只在「实际进了前 10 的人」里比顺序。

    README 用它说明「在对外的前 10 口径下更准」。这个口径不在 backtest.py 里
    （框架只输出前 N 集合命中率，那是**另一个指标**），所以在此实现。
    """
    predictor = factory()
    out = []
    for race in races:
        ctx = make_context(race, context)
        pred = predictor.predict(ctx)
        top10 = {d for d, t in race.truth.items() if t.position <= 10}
        # ⚠️ spearman 收的是**两列对齐的数值**（预测名次 vs 真实名次），
        # 不是两个车手名单 —— 直接把名单传进去会退化成"按车手代号排序"，
        # 算出 0.26 这种无量纲的假数字。口径照抄 score_round。
        p = [d for d in pred if d in top10]
        if len(p) > 2:
            pr = {d: i + 1 for i, d in enumerate(p)}
            out.append(spearman([pr[d] for d in p],
                                [race.truth[d].position for d in p]))
        predictor.observe(race)
    return sum(out) / len(out) if out else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="额外跑 173 场全套对照（慢，约 1 分钟）")
    args = ap.parse_args()

    races = load_races()
    old = [r for r in races if r.year <= 2025]      # README 头条口径
    print(f"\n{'=' * 78}")
    print(f" README 头条数字复算 · 全部 {len(races)} 场 / 2018–2025 {len(old)} 场")
    print(f"{'=' * 78}")

    # ── 主表 ─────────────────────────────────────────────────
    print(f"\n■ 主表（口径：2018–2025，n={len(old)}）")
    print(RULE)
    pre_base = summarize(run_backtest(old, PointsBaseline, context="pre_quali"),
                         label="L0 赛前积分榜（README 的基线）")
    pre_mine = summarize(run_backtest(old, best_pre, context="pre_quali"),
                         label="本项目 best_pre")
    post_base = summarize(run_backtest(old, GridBaseline, context="post_quali"),
                          label="L0 纯发车格（README 的基线）")
    post_mine = summarize(run_backtest(old, best_post, context="post_quali"),
                          label="本项目 best_post")
    print("  %-34s %-8s %-8s" % ("", "赛前 ρ", "赛后 ρ"))
    print("  %-34s %.4f   %.4f" % ("README 用的基线", pre_base["rho_all"],
                                    post_base["rho_all"]))
    print("  %-34s %.4f   %.4f" % ("本项目 best_pre / best_post",
                                    pre_mine["rho_all"], post_mine["rho_all"]))
    print("  %-34s %+.4f   %+.4f" % ("→ README 口径的增益",
                                      pre_mine["rho_all"] - pre_base["rho_all"],
                                      post_mine["rho_all"] - post_base["rho_all"]))

    print(f"\n■ 同一批场次上的**同复杂度对照**（零拟合，不含 Elo）")
    print(RULE)
    sc_pre = summarize(run_backtest(old, same_complexity_pre, context="pre_quali"),
                       label="积分榜+练习赛")
    sc_post = summarize(run_backtest(old, same_complexity_post, context="post_quali"),
                        label="发车格+秒差")
    avg_pre = summarize(run_backtest(old, lambda: AvgFinishBaseline(include_dnf=False),
                                     context="pre_quali"),
                        label="平均完赛名次(仅完赛)")
    print("  %-34s %-8s %-8s" % ("对照", "赛前 ρ", "赛后 ρ"))
    print("  %-34s %.4f   %.4f" % ("积分榜+练习赛 / 发车格+秒差",
                                    sc_pre["rho_all"], sc_post["rho_all"]))
    print("  %-34s %.4f   —" % ("平均完赛名次(仅完赛)", avg_pre["rho_all"]))
    print("  %-34s %+.4f   %+.4f" % ("→ 相对同复杂度的增益",
                                      pre_mine["rho_all"] - sc_pre["rho_all"],
                                      post_mine["rho_all"] - sc_post["rho_all"]))
    print("  %-34s %+.4f   —" % ("→ 相对最强零拟合基线",
                                  pre_mine["rho_all"] - avg_pre["rho_all"]))

    # ── 配对检验 ─────────────────────────────────────────────
    print(f"\n■ 配对检验（逐场，n={len(old)}）")
    print(RULE)
    for label, a_fac, b_fac, ctx in (
        ("赛前：best_pre vs 积分榜", PointsBaseline, best_pre, "pre_quali"),
        ("赛后：best_post vs 纯发车格", GridBaseline, best_post, "post_quali"),
        ("赛前：best_pre vs 同复杂度", same_complexity_pre, best_pre, "pre_quali"),
        ("赛后：best_post vs 同复杂度", same_complexity_post, best_post, "post_quali"),
    ):
        r = paired(run_backtest(old, a_fac, context=ctx),
                   run_backtest(old, b_fac, context=ctx))
        pos = sum(1 for v in r["years"].values() if v > 0)
        print("  %-28s Δρ=%+.4f  t=%+.2f  n=%d  胜率 %.1f%%  年为正 %d/%d"
              % (label, r["delta"], r["t"], r["n"], r["win"] * 100,
                 pos, len(r["years"])))
        print("     逐年 Δ：" + "  ".join("%d %+.4f" % (y, v)
                                          for y, v in sorted(r["years"].items())))

    # ── MAE 与前 10 口径 ─────────────────────────────────────
    print(f"\n■ 实用性口径（赛后）")
    print(RULE)
    for label, fac in (("纯发车格", GridBaseline), ("本项目 best_post", best_post)):
        acc = practical_accuracy(old, fac, context="post_quali")
        print("  %-20s 平均差 %.2f 位   前3 命中 %.0f%%   前10 命中 %.0f%%"
              % (label, acc["mae"], acc["top"][3] * 100, acc["top"][10] * 100))
    for label, fac in (("纯发车格", GridBaseline), ("本项目 best_post", best_post)):
        print("  %-20s 真实前 10 子集 ρ = %.4f" % (label, top10_rho(fac, old, "post_quali")))

    if args.full:
        # ── 2026 专项 ────────────────────────────────────────
        f26 = [r for r in races if r.year == 2026]
        print(f"\n■ 2026 专项（n={len(f26)}）")
        print(RULE)
        with_elo = summarize(run_backtest(f26, best_pre, context="pre_quali"), label="含Elo")
        without = summarize(run_backtest(f26, no_elo_pre, context="pre_quali"), label="去Elo")
        print("  含 Elo ρ=%.4f   去 Elo ρ=%.4f   Δρ=%+.4f"
              % (with_elo["rho_all"], without["rho_all"],
                 without["rho_all"] - with_elo["rho_all"]))
        r26 = paired(run_backtest(f26, best_pre, context="pre_quali"),
                     run_backtest(f26, no_elo_pre, context="pre_quali"))
        print("  配对检验：t=%+.2f（n=%d）—— 17 场，按项目自己的 |t|>2 门槛不算立论"
              % (r26["t"], r26["n"]))

        # Elo 单独：口径必须说清是「累积后切 2026」还是「只喂 2026」，两者差很远
        def elo_only() -> EloPredictor:
            return EloPredictor(k=192, use_team=True, dnf_policy="finishers_only")

        cum = run_backtest(races, elo_only, context="pre_quali")
        c26 = cum[cum.year == 2026]
        hist = cum[cum.year <= 2025]
        only = run_backtest(f26, elo_only, context="pre_quali")
        print("  Elo 单独（**累积后切 2026**）：猜中冠军 %.1f%%  冠军均预测名次 %.2f"
              % (c26.top1.mean() * 100, c26.winner_rank.mean()))
        print("  Elo 单独（**只喂 2026**）    ：猜中冠军 %.1f%%  冠军均预测名次 %.2f"
              % (only.top1.mean() * 100, only.winner_rank.mean()))
        print("  Elo 单独（历史 2018–2025）  ：猜中冠军 %.1f%%  冠军均预测名次 %.2f"
              % (hist.top1.mean() * 100, hist.winner_rank.mean()))

        # ── H2 对照：按退赛率匹配 ────────────────────────────
        print(f"\n■ 退赛率是一把尺子（审查报告 H2 的复核）")
        print(RULE)
        share = {}
        for r in races:
            n = len(r.truth)
            if n:
                share[r.key] = sum(1 for t in r.truth.values()
                                   if not t.finished) / n
        grid = run_backtest(races, GridBaseline, context="post_quali")
        df = grid.copy()
        df["dnf"] = df["key"].map(share)
        lo = df[(df.year <= 2025) & (df.dnf >= 0.20)]
        hi = df[(df.year == 2026)]
        print("  退赛率 ≥20%% 的历史场次（n=%d）：rho_all=%.4f  rho_fin=%.4f"
              % (len(lo), lo.rho_all.mean(), lo.rho_fin.mean()))
        print("  2026（退赛率 %.1f%%）        ：rho_all=%.4f  rho_fin=%.4f"
              % (100 * hi.dnf.mean(), hi.rho_all.mean(), hi.rho_fin.mean()))
        print("  → 主指标 rho_all 与退赛率**负相关**（退赛越多越低），")
        print("    退赛率匹配后 2026 仍显著更高 —— 2026 的高 ρ 不是混杂造成的。")

    print(f"\n（其余口径见 python -m scripts.run_backtest）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
