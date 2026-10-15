"""README 头条数字的核验入口 —— 一条命令，自己验。

    python -m scripts.verify_claims              # 除逐圈外全部（约 25 秒）
    python -m scripts.verify_claims --lap        # 含逐圈 Δρ（多约 80 秒）
    python -m scripts.verify_claims --only data  # 只跑某一节

## 为什么要有这个脚本

审查报告 M4：「5 组关键数字没有可产出它们的入库代码」—— README 的数字都是真的，
但产出它们的脚本是若干一次性文件，散在一个**被 gitignore 的目录**里
（`outputs/_verify_*.py`，见审查报告 M4 与 `.gitignore` 的 `outputs/` 规则）。
对一个以"可复现回测框架"为卖点的项目，那等于**尺子造了却没放进工具箱**。

本脚本把那批一次性核验并成**一个入口**，并把"打印数字"升级为
**与 README 里的字符串逐条比对、当场判 ✅/❌** —— 否则读者还得自己对表。

它已经抓到的两处漂移（本脚本因此存在是值得的）：
  · `finishers_only` 增益：README 写 +0.0238 / t=4.05，实测 **+0.0245 / t=3.99**
  · 逐圈 25–75% 区间：`lappredict.py` / `lapdata.py` 注释写 +0.0128 / t=+7.71，
    实测 **+0.0125 / t=+7.57**（README 是对的，注释落后一版）

## 判据的边界（重要）

比对是**字面**的：README 写 4 位小数就比到 4 位。所以本脚本的产出是
「README 说的和我算的一致 / 不一致」，**不是**「谁对」。
不一致时该修的是落后的那一侧（文档或注释），**不是把容差放宽** ——
容差只用来吸收四舍五入，不用来吸收分歧。

留出验证（选参与评估分离）是另一件事，见 `scripts/holdout_eval.py`。
逐圈那组最慢（约 80 秒），默认不跑。
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 中文 Windows 默认 cp936，本脚本输出含「✅/ρ/Δ」—— 与 run_backtest.py 同理兜底
for _s in (sys.stdout, sys.stderr):
    if _s.encoding and _s.encoding.lower().replace("-", "") not in ("utf8", "utf8mb4"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from src.model.backtest import (  # noqa: E402
    DB_PATH, load_races, make_context, practical_accuracy, run_backtest, spearman,
)
from src.model.predictors import (  # noqa: E402
    AvgFinishBaseline, EloPredictor, GridBaseline, PointsBaseline,
    PracticePaceBaseline, ReliabilityModel, best_post, best_pre,
    same_complexity_post, same_complexity_pre,
)

RULE = "─" * 78

# 口径常量 —— 与 README 头部一致
Y_ALL = list(range(2018, 2026))          # README 头条口径：173 场
N_ALL = 173
N_WITH_2026 = 190


# ═══════════════════════════════════════════════════════════
# 比对机制
# ═══════════════════════════════════════════════════════════
RESULT: list[tuple[str, str, bool]] = []


def check(section: str, label: str, measured: float, claimed: float,
          tol: float = 1e-4, fmt: str = "{:+.4f}") -> bool:
    """把实测值与文档值比对。tol 只吸收四舍五入，不用来吸收分歧。"""
    ok = measured == measured and abs(measured - claimed) <= tol
    RESULT.append((section, label, ok))
    mark = "✅" if ok else "❌"
    print(f"    {mark} {label:<46}{fmt.format(measured):>11}   文档 {fmt.format(claimed)}")
    return ok


def title(text: str) -> None:
    print(f"\n■ {text}")
    print(RULE)


# ═══════════════════════════════════════════════════════════
# 统计小工具（原先在 5 个一次性脚本里各有一份，口径已经漂过）
# ═══════════════════════════════════════════════════════════
def paired(fa, fb, ctx: str, races, col: str = "rho_all") -> dict:
    """逐场配对：B − A。一只返回 Δ / t / n / 胜率 / 逐场帧。"""
    a = run_backtest(races, fa, context=ctx)
    b = run_backtest(races, fb, context=ctx)
    m = a[["key", "year", col]].merge(b[["key", col]], on="key",
                                      suffixes=("_a", "_b"))
    d = (m[f"{col}_b"] - m[f"{col}_a"]).dropna()
    n = len(d)
    if n < 2:
        return {"delta": float("nan"), "t": float("nan"), "n": n, "frame": m}
    se = float(d.std(ddof=1)) / math.sqrt(n)
    return {
        "delta": float(d.mean()),
        "t": float(d.mean() / se) if se else float("nan"),
        "n": n,
        "win": float((d > 0).mean()),
        "frame": m,
    }


def pos_years(m, col: str = "rho_all") -> tuple[int, int]:
    sub = m.dropna(subset=[f"{col}_b"])
    tot = sub["year"].nunique()
    pos = sum(1 for _y, g in sub.groupby("year")
              if (g[f"{col}_b"] - g[f"{col}_a"]).mean() > 0)
    return pos, tot


def top10_rho(fac, races, ctx: str) -> float:
    """真实前 10 名的子集 ρ —— 只在「实际进了前 10 的人」里比顺序。

    ⚠️ `spearman` 收的是**两列对齐的数值**（预测名次 vs 真实名次），不是两个车手
    名单。口径照抄 `readme_numbers.top10_rho`。
    """
    p = fac()
    vals = []
    for rc in races:
        pred = p.predict(make_context(rc, ctx))
        top10 = {d for d, t in rc.truth.items() if t.position <= 10}
        kept = [d for d in pred if d in top10]
        if len(kept) > 2:
            pr = {d: i + 1 for i, d in enumerate(kept)}
            vals.append(spearman([pr[d] for d in kept],
                                 [rc.truth[d].position for d in kept]))
        p.observe(rc)
    return statistics.mean(vals) if vals else float("nan")


def auc(scores: list[float], labels: list[int]) -> float:
    """Mann-Whitney AUC（并列计 0.5）。"""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for a in pos:
        for b in neg:
            wins += 1.0 if a > b else (0.5 if a == b else 0.0)
    return wins / (len(pos) * len(neg))


# ═══════════════════════════════════════════════════════════
# 各节
# ═══════════════════════════════════════════════════════════
def sec_counts(races) -> None:
    title("场次口径（README 数据表）")
    check("counts", "2018–2025 场次", float(len([r for r in races if r.year <= 2025])),
          float(N_ALL), tol=0.5, fmt="{:.0f}")
    check("counts", "2018–2026 场次（含 2026）", float(len(races)),
          float(N_WITH_2026), tol=0.5, fmt="{:.0f}")
    print("       ↑ 两个口径混用会差约 0.003；报 ρ 必须连 n 一起报。")
    races25 = [r for r in races if r.year <= 2025]
    return races25


def sec_main(races) -> None:
    title("主表 · 排位赛前 / 赛后（README 核心数字）")
    pre_pts = run_backtest(races, PointsBaseline, context="pre_quali")
    pre_mine = run_backtest(races, best_pre, context="pre_quali")
    post_grid = run_backtest(races, GridBaseline, context="post_quali")
    post_mine = run_backtest(races, best_post, context="post_quali")
    check("main", "赛前 ρ · 最笨基线（纯积分榜）", float(pre_pts["rho_all"].mean()), 0.5501)
    check("main", "赛前 ρ · best_pre", float(pre_mine["rho_all"].mean()), 0.6082)
    check("main", "赛后 ρ · 最笨基线（纯发车格）", float(post_grid["rho_all"].mean()), 0.6204)
    check("main", "赛后 ρ · best_post", float(post_mine["rho_all"].mean()), 0.6543)

    title("同复杂度口径（README 主推）")
    sc_pre = run_backtest(races, same_complexity_pre, context="pre_quali")
    sc_post = run_backtest(races, same_complexity_post, context="post_quali")
    check("main", "赛前 ρ · 积分榜+练习赛", float(sc_pre["rho_all"].mean()), 0.5768)
    check("main", "赛后 ρ · 发车格+秒差", float(sc_post["rho_all"].mean()), 0.6355)

    r = paired(same_complexity_pre, best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 同复杂度", r["delta"], 0.0314)
    check("main", "  t 值", r["t"], 4.94, tol=0.01, fmt="{:+.2f}")
    r = paired(same_complexity_post, best_post, "post_quali", races)
    check("main", "Δρ 赛后 vs 同复杂度", r["delta"], 0.0188)
    check("main", "  t 值", r["t"], 4.16, tol=0.01, fmt="{:+.2f}")

    title("最笨基线口径的配对 t（README 正文那两行 t）")
    r = paired(PointsBaseline, best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 纯积分榜", r["delta"], 0.0582)
    check("main", "  t 值（README 写 5.34）", r["t"], 5.34, tol=0.01, fmt="{:+.2f}")
    check("main", "  为正年份", float(pos_years(r["frame"])[0]), 8.0, tol=0.5, fmt="{:.0f}")
    r = paired(GridBaseline, best_post, "post_quali", races)
    check("main", "Δρ 赛后 vs 纯发车格", r["delta"], 0.0339)
    check("main", "  t 值（README 写 4.93）", r["t"], 4.93, tol=0.01, fmt="{:+.2f}")

    title("库里最强的零拟合基线（README 第三行）")
    avg_pre = run_backtest(races, lambda: AvgFinishBaseline(include_dnf=False),
                           context="pre_quali")
    check("main", "赛前 ρ · 平均完赛名次(仅完赛)", float(avg_pre["rho_all"].mean()), 0.5849)
    r = paired(lambda: AvgFinishBaseline(include_dnf=False), best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 最强零拟合", r["delta"], 0.0234)
    print("       ↑ 这个分母比「积分榜+练习赛」强，所以增益更小。两个都要报。")


def sec_utility(races) -> None:
    title("实用口径（README 的「诚实边界」）")
    for label, fac, mae, t10 in (
        ("纯发车格", GridBaseline, 3.51, 0.7230),
        ("best_post", best_post, 3.36, 0.7690),
    ):
        acc = practical_accuracy(races, fac, context="post_quali")
        check("utility", f"MAE · {label}", float(acc["mae"]), mae, tol=0.005,
              fmt="{:.2f}")
        check("utility", f"真实前 10 子集 ρ · {label}", top10_rho(fac, races, "post_quali"),
              t10)


def sec_dnf(races) -> None:
    title("被证伪清单 · 退赛预测（README 说 AUC 0.5351）")
    rel = ReliabilityModel()
    scores, labels, hit, tot = [], [], 0, 0
    for rc in races:
        ctx = make_context(rc, "pre_quali")
        p = rel.prob(ctx)
        top3 = sorted(p, key=lambda d: -p[d])[:3]
        for d in ctx.drivers:
            scores.append(p[d])
            labels.append(0 if rc.truth[d].finished else 1)
        hit += sum(1 for d in top3 if not rc.truth[d].finished)
        tot += 3
        rel.observe(rc)
    check("dnf", "DNF 模型 AUC（随机 0.500）", auc(scores, labels), 0.5351, tol=0.0005)
    base = sum(labels) / len(labels) * 100
    check("dnf", "「风险最高 3 人」命中率 %", hit / tot * 100, 15.8, tol=0.05,
          fmt="{:.1f}")
    check("dnf", "  对照基准退赛率 %", base, 14.9, tol=0.05, fmt="{:.1f}")

    title("真正有效的那一下：dnf_policy=finishers_only")
    # ⚠️ 这组数字 README 原先写 +0.0238 / t=4.05，本脚本复核后是 +0.0245 / t=3.99
    # —— 文档落后一版，已按实测值更正（README 中英两处）。
    ka = lambda: EloPredictor(k=192, use_team=True)                       # noqa: E731
    kb = lambda: EloPredictor(k=192, use_team=True, dnf_policy="finishers_only")  # noqa: E731
    r = paired(ka, kb, "pre_quali", races)
    check("dnf", "Δρ（k=192, 173 场）", r["delta"], 0.0245)
    check("dnf", "  t 值", r["t"], 3.99, tol=0.01, fmt="{:+.2f}")
    pos, tot = pos_years(r["frame"])
    print(f"     · 为正年份 {pos}/{tot}、胜率 {r['win'] * 100:.1f}%"
          f"（README 只写了 Δ 与 t，没声明年份数，故不设检查）")


def sec_2026(races_all) -> None:
    title("2026 新规年（README 的探索性发现）")
    f26 = [r for r in races_all if r.year == 2026]
    with_elo = run_backtest(f26, best_pre, context="pre_quali")
    without = run_backtest(f26, same_complexity_pre, context="pre_quali")
    check("2026", "含 Elo ρ（n=17）", float(with_elo["rho_all"].mean()), 0.6318)
    check("2026", "去 Elo ρ（积分榜+练习赛）", float(without["rho_all"].mean()), 0.6495)

    # ⚠️ Elo 单独那组的口径是「**全历史累积后切 2026**」，不是"只喂 2026"。
    # 后者会让 Elo 从 1500 冷启动，猜中率变成 35.3% —— 两个口径差 3 倍，
    # README 已经注明，但写检查时最容易踩错的就是这里。
    elo_only = lambda: EloPredictor(k=192, use_team=True,  # noqa: E731
                                    dnf_policy="finishers_only")
    cum = run_backtest(races_all, elo_only, context="pre_quali")
    c26, hist = cum[cum["year"] == 2026], cum[cum["year"] <= 2025]
    cold = run_backtest(f26, elo_only, context="pre_quali")
    check("2026", "Elo 单独 · 猜中冠军 %（累积后切）", float(c26["top1"].mean()) * 100,
          11.8, tol=0.05, fmt="{:.1f}")
    check("2026", "Elo 单独 · 冠军均预测名次（累积后切）",
          float(c26["winner_rank"].mean()), 4.53, tol=0.005, fmt="{:.2f}")
    check("2026", "  同口径历史（2018–2025）猜中冠军 %",
          float(hist["top1"].mean()) * 100, 54.3, tol=0.05, fmt="{:.1f}")
    check("2026", "  同口径历史冠军均预测名次",
          float(hist["winner_rank"].mean()), 2.37, tol=0.005, fmt="{:.2f}")
    print(f"     · 换成「只喂 2026」口径：猜中 {cold['top1'].mean() * 100:.1f}%、"
          f"冠军均名次 {cold['winner_rank'].mean():.2f}"
          f" —— 引用时必须说明是哪个口径")

    title("Elo 的 k 在 2026 是否越大越好（README 的因果解释）")
    print(f"    {'k':>6}{'2018–2025 ρ':>14}{'2026 ρ':>10}{'2026 猜中':>12}")
    for k in (8, 24, 64, 192, 512, 2048):
        df = run_backtest(races_all, lambda k=k: EloPredictor(
            k=k, use_team=True, dnf_policy="finishers_only"), context="pre_quali")
        h = df[df["year"] <= 2025]
        y = df[df["year"] == 2026]
        print(f"    {k:>6}{h['rho_all'].mean():>14.4f}{y['rho_all'].mean():>10.4f}"
              f"{y['top1'].mean() * 100:>11.1f}%")
    print("       ↑ README 的解释：k 越大越能把 2026 的旧信息冲掉。看这张表的单调性。")


def sec_lap(races_all) -> None:
    """逐圈 Δρ —— 最慢的一节（约 80 秒）。"""
    from collections import defaultdict

    from src.model.lapdata import load_laptimelines
    from src.model.lappredict import (DEFAULT_GAIN, DEFAULT_WINDOW,
                                      PaceProjectionCached, cached_pace)

    title(f"逐圈预测（gain={DEFAULT_GAIN}, window={DEFAULT_WINDOW}）")
    windows = ((0.10, 0.50, "10–50%"), (0.25, 0.75, "25–75%"))
    acc = {w[2]: defaultdict(list) for w in windows}
    for y in sorted({r.year for r in races_all if r.year <= 2025}):
        for tl in load_laptimelines(y):
            table = cached_pace(tl, DEFAULT_WINDOW)
            base = tl.convergence()
            model = tl.convergence(
                PaceProjectionCached(table, DEFAULT_WINDOW, DEFAULT_GAIN).predict)
            bmap = {r["lap"]: r for r in base}
            for r in model:
                b = bmap.get(r["lap"])
                if b is None:
                    continue
                for lo, hi, wn in windows:
                    if lo <= r["progress"] <= hi:
                        d = r["rho_all"] - b["rho_all"]
                        if d == d:
                            acc[wn][tl.key].append(d)

    claims = {"10–50%": (0.0179, 6.45), "25–75%": (0.0125, 7.57)}
    for _lo, _hi, wn in windows:
        pts = [statistics.mean(v) for v in acc[wn].values() if v]
        n = len(pts)
        se = statistics.stdev(pts) / math.sqrt(n) if n > 1 else 0.0
        delta = statistics.mean(pts)
        t = delta / se if se else float("nan")
        c_d, c_t = claims[wn]
        check("lap", f"Δρ 窗口 {wn}（n={n} 场）", delta, c_d)
        check("lap", "  t 值", t, c_t, tol=0.01, fmt="{:+.2f}")
    print("       ↑ 检验单位是**场**不是圈：相邻圈窗口重叠 4/5，有效样本量是场。")


def sec_data() -> None:
    title("数据层（README 数据表 / 审查报告 H1、H5、H6）")
    db = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    q = lambda s: list(db.execute(s))  # noqa: E731

    # 每轮积分合计：2019–2024 含最快圈 +1 → 102；其余年份 101。
    # ⚠️ 有一个**合法例外**：2021 R12 斯帕（比利时）因大雨只跑了 2 圈，
    # 按规则发**半积分**，合计 50.5。所以断言是"除它以外为 0"，不是"恒为 0"。
    odd = q("""SELECT year, round, SUM(points) s FROM results
               WHERE year<=2025 AND round>0 GROUP BY year, round
               HAVING s NOT IN (101.0, 102.0, 0.0)""")
    check("data", "2018–2025 每轮积分合计异常轮次", float(len(odd)), 1.0, tol=0.5,
          fmt="{:.0f}")
    for y, r, s in odd:
        name = q(f"SELECT event_name FROM events WHERE year={y} AND round={r}")
        tag = "（半积分，合法例外）" if (y, r) == (2021, 12) else "⚠️ 需核查"
        print(f"     · 例外：{y} R{r} {name[0][0] if name else '?'} 合计 {s:g} {tag}")
    tot26 = q("SELECT SUM(points) FROM results WHERE year=2026")[0][0]
    print(f"     · 2026 赛季总分 = {tot26:.0f}（审查报告 H1：修正最快圈口径后应为 1717）")

    n, lc, rt = q("SELECT COUNT(*), COUNT(laps_completed), COUNT(race_time_sec) "
                  "FROM results WHERE year=2026")[0]
    check("data", "2026 laps_completed 非空行数", float(lc), float(n), tol=0.5,
          fmt="{:.0f}")
    print(f"     · 2026 race_time_sec 非空 {rt} 行（只有完赛者有成绩，正常）")

    n26, sq26 = q("SELECT COUNT(*), COUNT(sq_pos) FROM sprint_points "
                  "WHERE year=2026")[0]
    check("data", "2026 冲刺排位 sq_pos 非空行数", float(sq26), 129.0, tol=0.5,
          fmt="{:.0f}")
    miss = q("SELECT round, driver FROM sprint_points "
             "WHERE year=2026 AND sq_pos IS NULL ORDER BY round")
    print(f"     · 共 {n26} 行，缺 {len(miss)} 行："
          + "、".join(f"R{r} {d}" for r, d in miss)
          + "（均 P19 / 0 分 —— 未参加 SQ 或未发车，属上游缺失）")

    empty = q("""SELECT COUNT(*) FROM events e WHERE e.round>0
                   AND EXISTS(SELECT 1 FROM results r
                              WHERE r.year=e.year AND r.round=e.round)
                   AND NOT EXISTS(SELECT 1 FROM laps l
                              WHERE l.year=e.year AND l.round=e.round)""")[0][0]
    print(f"     · 有成绩但完全没有圈速的轮次 = {empty}"
          f"（已知 2018 R14 Monza，FastF1 上游 IndexError，补不回来）")
    db.close()


# ═══════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lap", action="store_true", help="含逐圈 Δρ（慢约 80 秒）")
    ap.add_argument("--only", choices=["counts", "main", "utility", "dnf",
                                       "2026", "lap", "data"],
                    help="只跑某一节")
    args = ap.parse_args()

    t0 = time.time()
    races_all = load_races()
    print("=" * 78)
    print(" README 头条数字核验 —— 实测值与文档值逐条比对")
    print("=" * 78)
    print(" 判据是字面比对（README 写 4 位就比到 4 位）。❌ = 某处落后了，")
    print(" 该修的是落后的那一侧，不是把容差放宽。")

    only = args.only
    races25 = [r for r in races_all if r.year <= 2025]
    steps = {
        "counts": lambda: sec_counts(races_all),
        "main": lambda: sec_main(races25),
        "utility": lambda: sec_utility(races25),
        "dnf": lambda: sec_dnf(races25),
        "2026": lambda: sec_2026(races_all),
        "lap": lambda: sec_lap(races_all),
        "data": sec_data,
    }
    for name, fn in steps.items():
        if only and name != only:
            continue
        if name == "lap" and not (args.lap or only == "lap"):
            print(f"\n■ （逐圈那节默认跳过 —— 加 --lap 打开，约 80 秒）")
            continue
        fn()

    bad = [(s, lbl) for s, lbl, ok in RESULT if not ok]
    total = len(RESULT)
    print(f"\n{'=' * 78}")
    if bad:
        print(f" 结果：{total - len(bad)}/{total} 条与文档一致，{len(bad)} 条**对不上**")
        print(RULE)
        for s, lbl in bad:
            print(f"   ❌ [{s}] {lbl.strip()}")
        print(" 处置：核对是哪一侧落后了。若文档错 → 改文档；若代码错 → 改代码。")
        print(" 不要放宽容差 —— 容差只吸收四舍五入，不用来吸收分歧。")
    else:
        print(f" 结果：{total}/{total} 条与文档一致 ✅")
    print(f" （用时 {time.time() - t0:.1f}s）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
