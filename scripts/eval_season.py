"""在指定赛季上评估现有预测模型 —— 默认把最新赛季当作 out-of-sample 新规年来看。

用法：
    python -m scripts.eval_season 2026                 # 两种预测时点都跑
    python -m scripts.eval_season 2026 --context post_quali

为什么必须跑全历史而不是只跑目标年：
    Elo / 积分榜都是**累积型**预测器，只喂 2026 等于让它们从零开始，
    分数会毫无意义地偏低。正确做法是在全部历史上推进，
    再把评分结果按年份切片 —— 预测器到 2026 第 1 站时已经吃过 2025 的信息，
    这与实盘一致。
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.model.backtest import (  # noqa: E402
    format_accuracy,
    format_table,
    load_races,
    practical_accuracy,
    run_backtest,
    summarize,
)
from src.model.predictors import (  # noqa: E402
    AdjustedGridBaseline,
    EloPredictor,
    GridBaseline,
    PointsBaseline,
    PracticePaceBaseline,
    QualiGapBaseline,
    RandomBaseline,
    best_post,
    best_pre,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("focus_year", type=int)
    ap.add_argument("--context", choices=["pre_quali", "post_quali", "both"], default="both")
    args = ap.parse_args()

    year = args.focus_year
    races = load_races()
    all_years = sorted({r.year for r in races})
    hist = sorted({r.year for r in races if r.year < year})
    print(f"载入 {len(races)} 场：{all_years[0]}–{all_years[-1]}"
          f"｜历史期 {hist[0]}–{hist[-1]}（{len(hist)} 年）｜观察期 {year}", flush=True)

    contexts = ["pre_quali", "post_quali"] if args.context == "both" else [args.context]

    for ctx in contexts:
        if ctx == "pre_quali":
            preds = [
                ("L0 随机", RandomBaseline),
                ("L0 赛前积分榜（基线）", PointsBaseline),
                ("L0 练习赛配速", PracticePaceBaseline),
                ("L1 Elo(车手+车队,finishers)", lambda: EloPredictor(
                    k=192, use_team=True, dnf_policy="finishers_only")),
                ("★ best_pre 当前组合", best_pre),
            ]
        else:
            preds = [
                ("L0 随机", RandomBaseline),
                ("L0 纯发车格（基线）", GridBaseline),
                ("L0 罚退收缩发车格", AdjustedGridBaseline),
                ("L0 排位秒差", QualiGapBaseline),
                ("L1 Elo(车手+车队,finishers)", lambda: EloPredictor(
                    k=192, use_team=True, dnf_policy="finishers_only")),
                ("★ best_post 当前组合", best_post),
            ]

        print("\n" + "═" * 84, flush=True)
        print(f"  预测时点：{ctx}", flush=True)
        print("═" * 84, flush=True)

        rows = []
        cache = {}
        for label, factory in preds:
            df = run_backtest(races, factory, context=ctx)
            cache[label] = df
            rows.append(summarize(df[df["year"] < year], label=f"{label} ‹历史›"))
            rows.append(summarize(df[df["year"] == year], label=f"{label} ‹{year}›"))
        print(format_table(rows), flush=True)

        # 焦点年逐场明细（只用最佳组合）
        factory = best_pre if ctx == "pre_quali" else best_post
        d = cache["★ best_pre 当前组合" if ctx == "pre_quali"
                  else "★ best_post 当前组合"]
        f = d[d["year"] == year]
        if not f.empty:
            print(f"\n  {year} 逐场明细 · {factory.__name__}", flush=True)
            print(f"    {'场次':<10}{'ρ(全部)':>9}{'ρ(完赛)':>9}{'猜中':>7}"
                  f"{'入前3':>8}{'冠军预测名次':>13}", flush=True)
            for _, r in f.iterrows():
                print(f"    {r['key']:<10}{r['rho_all']:>9.4f}{r['rho_fin']:>9.4f}"
                      f"{'✅' if r['top1'] else '❌':>6}"
                      f"{'✅' if r['top3'] else '❌':>7}{r['winner_rank']:>11.1f}", flush=True)

            acc = practical_accuracy([r for r in races if r.year == year], factory, context=ctx)
            print(f"\n  {year} 实用准确度 · {factory.__name__}", flush=True)
            print(format_accuracy(acc, f"{year} 赛季"), flush=True)


if __name__ == "__main__":
    main()
