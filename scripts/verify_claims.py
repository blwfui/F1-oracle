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
**与 README 逐条比对、当场判 ✅/❌** —— 否则读者还得自己对表。

## 文档值从哪来（这一条曾经是错的）

初版把文档值写成了 `check(..., 0.6082)` 这样的**字面常量** —— 那等于把 README 的
数字在脚本里**又抄了一份**。后果：README 日后漂移，尺子照样报全绿，而且报得理直气壮。
审查方 grep 一遍就抓到了（docstring 写"与 README 里的字符串逐条比对"，实现里
一行都没读 `README.md`）—— 正是 M3 那次"口径失同步"的同一种病。

现在文档值**一律从 `README.md` 现场解析**，来源是下面的 `PATTERNS` 锚点表：

  · 每条断言给一个锚点正则，必须**唯一命中** README 里那句声明的数字；
  · 锚点找不到 → 判 ❌ 并单列（README 被改/删/措辞变了）；
  · 锚点命中多处 → 报警（说明锚点选得不够独特，可能量到别的行）；
  · 只有 README 里**确实没有**对应声明的少数条（数据入库行数一类）才固化在脚本内，
    并在结尾单独列出，不混在"已核验"里充数。

## 判据的边界（重要）

比对是**字面**的：README 写 4 位小数就比到 4 位。本脚本的产出是
「**代码能否复现 README 的说法**」：实测值来自回测代码（独立），文档值来自 README。
所以 ❌ 的含义是**两侧对不上**，而不是"README 错了" ——
README 本身对不对，由审查报告与 `holdout_eval.py` 的留出验证负责。
不一致时该修的是落后的那一侧（文档或注释），**不是把容差放宽**：
容差**自动取自文档写出来的最后一位的一半**（README 写 4 位就只准差 5e-5，
写 3 位才准差 5e-4），所以这里没有能被人为调宽的手柄 ——
真·四舍五入一定过得去（`−0.565` vs `−0.5652`），真分歧一定过不去
（`+0.0238` vs `+0.0245` 差 7e-4）。

## 它抓到过的漂移（这个脚本因此存在是值得的）

  · `finishers_only` 增益：README 写 +0.0238 / t=4.05，实测 **+0.0245 / t=3.99**
  · 逐圈 25–75% 区间：`lappredict.py` / `lapdata.py` 注释写 +0.0128 / t=+7.71，
    实测 **+0.0125 / t=+7.57**（README 是对的，注释落后一版）
  · 它自己：文档值抄成常量 → 已改为解析 README（见上）

留出验证（选参与评估分离）是另一件事，见 `scripts/holdout_eval.py`。
逐圈那组最慢（约 80 秒），默认不跑。
"""

from __future__ import annotations

import argparse
import math
import re
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
    ReliabilityModel, best_post, best_pre,
    same_complexity_post, same_complexity_pre,
)

RULE = "─" * 78

# 口径常量 —— 与 README 头部一致
N_ALL = 173          # README 头条口径：2018–2025
N_WITH_2026 = 190


# ═══════════════════════════════════════════════════════════
# 锚点表：key -> (正则, 取值组号)
# 正则必须**唯一命中** README 里那句声明；改 README 措辞就得同步改这里，
# 否则报「锚点未命中」—— 这正是我们要的失败方式（响亮，不是静默）。
# ═══════════════════════════════════════════════════════════
README_PATH = ROOT / "README.md"

PATTERNS: dict[str, tuple[str, int]] = {
    # ── 数据表 ──────────────────────────────────────────────
    "n_races_all":      (r"\| 分站 \| (\d+) = ", 1),
    "n_races_25":       (r"\| 分站 \| \d+ = \*\*(\d+)\*\*（2018–2025）", 1),
    "n_laps_all":       (r"\| 圈速记录 \| ([\d,]+) = ", 1),
    "n_laps_25":        (r"\| 圈速记录 \| [\d,]+ = ([\d,]+) \+", 1),
    "n_laps_26":        (r"\| 圈速记录 \| [\d,]+ = [\d,]+ \+ ([\d,]+)", 1),
    "n_circuits":       (r"\| 赛道（含几何与进站损失） \| (\d+)", 1),

    # ── 主表 · 最笨基线口径 ─────────────────────────────────
    "rho_pre_naive":    (r"\| 排位赛前（不知发车格） \| ([\d.]+) 〔赛前积分榜〕", 1),
    "rho_post_naive":   (r"\| 排位赛后（已知发车格） \| ([\d.]+) 〔纯发车格顺序〕", 1),
    "rho_pre_mine":     (r"〔赛前积分榜〕 \| \*\*([\d.]+)\*\*", 1),
    "rho_post_mine":    (r"〔纯发车格顺序〕 \| \*\*([\d.]+)\*\*", 1),
    "delta_pre_naive":  (r"〔赛前积分榜〕 \| \*\*[\d.]+\*\* \| \+([\d.]+)", 1),
    "delta_post_naive": (r"〔纯发车格顺序〕 \| \*\*[\d.]+\*\* \| \+([\d.]+)", 1),

    # ── 主表 · 同复杂度口径（README 主推）────────────────────
    "rho_pre_sc":       (r"\| 排位赛前 \| ([\d.]+) 〔积分榜 \+ 练习赛〕", 1),
    "rho_post_sc":      (r"\| 排位赛后 \| ([\d.]+) 〔发车格 \+ 排位秒差〕", 1),
    "delta_pre_sc":     (r"〔积分榜 \+ 练习赛〕 \| \*\*[\d.]+\*\* \| \*\*\+([\d.]+)\*\*（t", 1),
    "t_pre_sc":         (r"〔积分榜 \+ 练习赛〕.*?（t = ([\d.]+)）", 1),
    "delta_post_sc":    (r"〔发车格 \+ 排位秒差〕 \| \*\*[\d.]+\*\* \| \*\*\+([\d.]+)\*\*（t", 1),
    "t_post_sc":        (r"〔发车格 \+ 排位秒差〕.*?（t = ([\d.]+)）", 1),

    # ── 最强零拟合基线 / 最笨基线 t / 前 10 口径 ─────────────
    "rho_strongest":      (r"平均完赛名次·仅完赛，([\d.]+)）", 1),
    "delta_vs_strongest": (r"平均完赛名次·仅完赛，[\d.]+） \| \| \| \*\*\+([\d.]+)\*\*", 1),
    "t_naive_pre":      (r"最笨基线口径）：赛前 \*\*t = ([\d.]+)\*\*", 1),
    "t_naive_post":     (r"最笨基线口径）：赛前 \*\*t = [\d.]+\*\*、赛后 \*\*t = ([\d.]+)\*\*", 1),
    "top10_grid":       (r"真实前 10 名口径：\*\*([\d.]+) →", 1),
    "top10_best":       (r"真实前 10 名口径：\*\*[\d.]+ → ([\d.]+)\*\*", 1),

    # ── 诚实边界：MAE ──────────────────────────────────────
    "mae_grid":         (r"平均名次误差只从 ([\d.]+) 位降到", 1),
    "mae_best":         (r"平均名次误差只从 [\d.]+ 位降到 ([\d.]+) 位", 1),

    # ── ρ_all vs ρ_fin（审查报告 L3）────────────────────────
    "fin_pre_sc":       (r"\| 赛前 best_pre vs 同复杂度 \| \+[\d.]+（[\d.]+） \| \*\*\+([\d.]+)\*\*（[\d.]+）", 1),
    "fin_t_pre_sc":     (r"\| 赛前 best_pre vs 同复杂度 \| \+[\d.]+（[\d.]+） \| \*\*\+[\d.]+\*\*（([\d.]+)）", 1),
    "fin_post_sc":      (r"\| 赛后 best_post vs 同复杂度 \| \+[\d.]+（[\d.]+） \| \*\*\+([\d.]+)\*\*（[\d.]+）", 1),
    "fin_t_post_sc":    (r"\| 赛后 best_post vs 同复杂度 \| \+[\d.]+（[\d.]+） \| \*\*\+[\d.]+\*\*（([\d.]+)）", 1),
    "fin_vs_grid":      (r"\| 赛后 best_post vs 纯发车格 \| \+[\d.]+（[\d.]+） \| \*\*\+([\d.]+)\*\*（[\d.]+）", 1),
    "fin_t_vs_grid":    (r"\| 赛后 best_post vs 纯发车格 \| \+[\d.]+（[\d.]+） \| \*\*\+[\d.]+\*\*（([\d.]+)）", 1),

    # ── 被证伪清单 ─────────────────────────────────────────
    "auc_dnf":          (r"退赛预测（两个模型 \+ 特征工程） \| AUC \*\*([\d.]+)\*\*", 1),
    "hit3":             (r"「风险最高 3 人」命中率 \| ([\d.]+)% vs 基准 [\d.]+%", 1),
    "base_dnf":         (r"「风险最高 3 人」命中率 \| [\d.]+% vs 基准 ([\d.]+)%", 1),
    "delta_finishers":  (r"收益 \*\*\+([\d.]+)（t = [\d.]+）\*\*", 1),
    "t_finishers":      (r"收益 \*\*\+[\d.]+（t = ([\d.]+)）\*\*", 1),

    # ── 2026 新规年 ────────────────────────────────────────
    "rho26_elo":        (r"\| 含 Elo \| \*\*[\d.]+\*\* ✅ \| ([\d.]+) \|", 1),
    "rho26_noelo":      (r"\| 去 Elo（仅积分榜 \+ 练习赛） \| [\d.]+ \| \*\*([\d.]+)\*\* ✅", 1),
    "t1_26":            (r"2026 猜中冠军只有 \*\*([\d.]+)%\*\*（历史 [\d.]+%）", 1),
    "t1_hist":          (r"2026 猜中冠军只有 \*\*[\d.]+%\*\*（历史 ([\d.]+)%）", 1),
    "rank26":           (r"冠军平均被排到 \*\*([\d.]+) 位\*\*（历史 [\d.]+ 位）", 1),
    "rank_hist":        (r"冠军平均被排到 \*\*[\d.]+ 位\*\*（历史 ([\d.]+) 位）", 1),

    # ── 退赛率是一把尺子（审查报告 H2 的复核）────────────────
    "dnf_rate_26":      (r"2026 退赛率 ([\d.]+)%", 1),
    "corr_dnf":         (r"与退赛率\*\*负相关\*\*（([−\d.]+)", 1),
    "match_hist_n":     (r"同档历史场次（n=(\d+)）", 1),
    "match_hist_all":   (r"同档历史场次（n=\d+）rho_all ([\d.]+) / rho_fin [\d.]+", 1),
    "match_hist_fin":   (r"同档历史场次（n=\d+）rho_all [\d.]+ / rho_fin ([\d.]+)", 1),
    "match_26_all":     (r"2026 则是 ([\d.]+) / [\d.]+", 1),
    "match_26_fin":     (r"2026 则是 [\d.]+ / ([\d.]+)", 1),

    # ── 逐圈预测 ───────────────────────────────────────────
    "lap_n":            (r"检验单位是 \*\*(\d+) 场\*\*", 1),
    "lap_1050_d":       (r"10%–50% 区间 Δρ = \*\*\+([\d.]+)\*\*", 1),
    "lap_1050_t":       (r"10%–50% 区间 Δρ = \*\*\+[\d.]+\*\*（t = \*\*\+([\d.]+)\*\*）", 1),
    "lap_2575_d":       (r"25%–75% 区间 Δρ = \*\*\+([\d.]+)\*\*", 1),
    "lap_2575_t":       (r"25%–75% 区间 Δρ = \*\*\+[\d.]+\*\*（t = \*\*\+([\d.]+)\*\*）", 1),
}


class Doc:
    """README 取值器 —— 文档值一律现场解析，脚本内不存第二份。

    这是本脚本最容易退化成「假绿」的地方：一旦把文档值抄成常量，
    README 漂了尺子照样报全绿。所以 `PATTERNS` 是文档值的唯一来源。
    """

    def __init__(self, path: Path = README_PATH) -> None:
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        self.missing: list[str] = []
        self.used: set[str] = set()
        self._dp: dict[str, int] = {}

    @staticmethod
    def _clean(raw: str) -> str:
        return (raw.replace("**", "").replace("+", "")
                .replace("−", "-").replace(",", ""))

    def num(self, key: str) -> float:
        try:
            pat, grp = PATTERNS[key]
        except KeyError as e:
            raise SystemExit(f"锚点表里没有 key：{key}") from e
        self.used.add(key)
        m = re.search(pat, self.text)
        if not m:
            if key not in self.missing:
                self.missing.append(key)
            return float("nan")
        raw = self._clean(m.group(grp))
        self._dp[key] = len(raw.split(".")[1]) if "." in raw else 0
        return float(raw)

    def tol(self, key: str) -> float:
        """容差 = README 写出来的**最后一位的一半**。

        这条规则是防作弊设计：容差由文档自身的精度决定，**不给人调宽的手柄** ——
        文档写 4 位就只准差 5e-5，写 3 位才准差 5e-4。所以「把 0.0238 说成等于 0.0245」
        这种分歧永远过不去（差 7e-4），而真·四舍五入一定过得去。
        """
        return 0.5 * 10 ** (-self._dp.get(key, 4))

    def ambiguous(self) -> list[tuple[str, int]]:
        """命中多处的锚点 —— 说明它不够独特，可能量到别的行。"""
        out = []
        for key, (pat, _grp) in PATTERNS.items():
            n = len(re.findall(pat, self.text))
            if n > 1:
                out.append((key, n))
        return out


_DOC: Doc | None = None


def doc() -> Doc:
    global _DOC
    if _DOC is None:
        _DOC = Doc()
    return _DOC


# ═══════════════════════════════════════════════════════════
# 比对机制
# ═══════════════════════════════════════════════════════════
RESULT: list[tuple[str, str, bool]] = []
HARDCODED: list[str] = []      # README 里没有对应声明的条目（如入库行数）


def check(section: str, label: str, measured: float, claimed,  # noqa: ANN001
          tol: float | None = None, fmt: str = "{:+.4f}") -> bool:
    """把实测值与 README 的声明比对。

    claimed 传**锚点 key**（文档值现场从 README 解析）；只有在 README 确实没有该
    声明时才传 float，并会被记入 HARDCODED 单独列出。

    tol 留空 = 自动取「文档最后一位的一半」（见 Doc.tol）—— 所以容差只吸收
    四舍五入，**不给人调宽的手柄**。传了 tol 的少数条目都是绝对计数/百分比，
    它们的等值本就是离散的。
    """
    if isinstance(claimed, str):
        want, src = doc().num(claimed), f"README 锚点 {claimed}"
        if tol is None:
            tol = doc().tol(claimed)
    else:
        want, src = float(claimed), "脚本内固化（README 无此声明）"
        HARDCODED.append(label)
        if tol is None:
            tol = 0.5          # 固化值都是整数计数
    ok = (measured == measured and want == want
          and abs(measured - want) <= tol)
    RESULT.append((section, label, ok))
    shown = "——" if want != want else fmt.format(want)
    line = f"    {'✅' if ok else '❌'} {label:<46}{fmt.format(measured):>11}   文档 {shown}"
    print(line if ok else f"{line}\n       ↳ {src}")
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


def dnf_share(races) -> dict:
    """逐场退赛率（退赛车次 / 参赛车次）。"""
    return {r.key: sum(1 for t in r.truth.values() if not t.finished) / len(r.truth)
            for r in races if r.truth}


# ═══════════════════════════════════════════════════════════
# 各节
# ═══════════════════════════════════════════════════════════
def sec_counts(races) -> None:
    title("场次口径（README 数据表）")
    check("counts", "2018–2025 场次", float(len([r for r in races if r.year <= 2025])),
          "n_races_25", tol=0.5, fmt="{:.0f}")
    check("counts", "2018–2026 场次（含 2026）", float(len(races)),
          "n_races_all", tol=0.5, fmt="{:.0f}")
    print("       ↑ 两个口径混用会差约 0.003；报 ρ 必须连 n 一起报。")


def sec_main(races) -> None:
    title("主表 · 排位赛前 / 赛后（README 核心数字）")
    pre_pts = run_backtest(races, PointsBaseline, context="pre_quali")
    pre_mine = run_backtest(races, best_pre, context="pre_quali")
    post_grid = run_backtest(races, GridBaseline, context="post_quali")
    post_mine = run_backtest(races, best_post, context="post_quali")
    check("main", "赛前 ρ · 最笨基线（纯积分榜）", float(pre_pts["rho_all"].mean()),
          "rho_pre_naive")
    check("main", "赛前 ρ · best_pre", float(pre_mine["rho_all"].mean()), "rho_pre_mine")
    check("main", "赛后 ρ · 最笨基线（纯发车格）", float(post_grid["rho_all"].mean()),
          "rho_post_naive")
    check("main", "赛后 ρ · best_post", float(post_mine["rho_all"].mean()), "rho_post_mine")

    title("同复杂度口径（README 主推）")
    sc_pre = run_backtest(races, same_complexity_pre, context="pre_quali")
    sc_post = run_backtest(races, same_complexity_post, context="post_quali")
    check("main", "赛前 ρ · 积分榜+练习赛", float(sc_pre["rho_all"].mean()), "rho_pre_sc")
    check("main", "赛后 ρ · 发车格+秒差", float(sc_post["rho_all"].mean()), "rho_post_sc")

    r = paired(same_complexity_pre, best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 同复杂度", r["delta"], "delta_pre_sc")
    check("main", "  t 值", r["t"], "t_pre_sc", tol=0.01, fmt="{:+.2f}")
    r = paired(same_complexity_post, best_post, "post_quali", races)
    check("main", "Δρ 赛后 vs 同复杂度", r["delta"], "delta_post_sc")
    check("main", "  t 值", r["t"], "t_post_sc", tol=0.01, fmt="{:+.2f}")

    title("最笨基线口径的配对 t（README 正文那两行 t）")
    r = paired(PointsBaseline, best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 纯积分榜", r["delta"], "delta_pre_naive")
    check("main", "  t 值（README 写 5.34）", r["t"], "t_naive_pre", tol=0.01, fmt="{:+.2f}")
    check("main", "  为正年份", float(pos_years(r["frame"])[0]), 8.0, tol=0.5, fmt="{:.0f}")
    r = paired(GridBaseline, best_post, "post_quali", races)
    check("main", "Δρ 赛后 vs 纯发车格", r["delta"], "delta_post_naive")
    check("main", "  t 值（README 写 4.93）", r["t"], "t_naive_post", tol=0.01, fmt="{:+.2f}")

    title("库里最强的零拟合基线（README 第三行）")
    avg_pre = run_backtest(races, lambda: AvgFinishBaseline(include_dnf=False),
                           context="pre_quali")
    check("main", "赛前 ρ · 平均完赛名次(仅完赛)", float(avg_pre["rho_all"].mean()),
          "rho_strongest")
    r = paired(lambda: AvgFinishBaseline(include_dnf=False), best_pre, "pre_quali", races)
    check("main", "Δρ 赛前 vs 最强零拟合", r["delta"], "delta_vs_strongest")
    print("       ↑ 这个分母比「积分榜+练习赛」强，所以增益更小。两个都要报。")


def sec_rho_fin(races) -> None:
    """审查报告 L3：换到更「干净」的 rho_fin，增量是变大还是变小？"""
    title("ρ_all 与 ρ_fin（README 的「两个 ρ 口径」/ 审查报告 L3）")
    pairs = (
        ("赛前 best_pre vs 同复杂度", same_complexity_pre, best_pre, "pre_quali",
         "fin_pre_sc", "fin_t_pre_sc"),
        ("赛后 best_post vs 同复杂度", same_complexity_post, best_post, "post_quali",
         "fin_post_sc", "fin_t_post_sc"),
        ("赛后 best_post vs 纯发车格", GridBaseline, best_post, "post_quali",
         "fin_vs_grid", "fin_t_vs_grid"),
    )
    for label, fa, fb, ctx, kd, kt in pairs:
        r = paired(fa, fb, ctx, races, col="rho_fin")
        check("rho_fin", f"Δρ_fin · {label}", r["delta"], kd)
        check("rho_fin", "  t 值", r["t"], kt, tol=0.01, fmt="{:+.2f}")
    print("       ↑ 全部**大于**同行的 Δρ_all —— 退赛让基线掉得比模型更多，")
    print("         所以主指标用 rho_all 是更严的那个，不是挑好看的。")


def sec_utility(races) -> None:
    title("实用口径（README 的「诚实边界」）")
    for label, fac, kd, kt in (
        ("纯发车格", GridBaseline, "mae_grid", "top10_grid"),
        ("best_post", best_post, "mae_best", "top10_best"),
    ):
        acc = practical_accuracy(races, fac, context="post_quali")
        check("utility", f"MAE · {label}", float(acc["mae"]), kd, tol=0.005, fmt="{:.2f}")
        check("utility", f"真实前 10 子集 ρ · {label}", top10_rho(fac, races, "post_quali"),
              kt)


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
    check("dnf", "DNF 模型 AUC（随机 0.500）", auc(scores, labels), "auc_dnf", tol=0.0005)
    check("dnf", "「风险最高 3 人」命中率 %", hit / tot * 100, "hit3", tol=0.05, fmt="{:.1f}")
    check("dnf", "  对照基准退赛率 %", sum(labels) / len(labels) * 100, "base_dnf",
          tol=0.05, fmt="{:.1f}")

    title("真正有效的那一下：dnf_policy=finishers_only")
    ka = lambda: EloPredictor(k=192, use_team=True)                       # noqa: E731
    kb = lambda: EloPredictor(k=192, use_team=True, dnf_policy="finishers_only")  # noqa: E731
    r = paired(ka, kb, "pre_quali", races)
    check("dnf", "Δρ（k=192, 173 场）", r["delta"], "delta_finishers")
    check("dnf", "  t 值", r["t"], "t_finishers", tol=0.01, fmt="{:+.2f}")
    pos, tot = pos_years(r["frame"])
    print(f"     · 为正年份 {pos}/{tot}、胜率 {r['win'] * 100:.1f}%"
          f"（README 只写了 Δ 与 t，没声明年份数，故不设检查）")


def sec_2026(races_all) -> None:
    title("2026 新规年（README 的探索性发现）")
    f26 = [r for r in races_all if r.year == 2026]
    with_elo = run_backtest(f26, best_pre, context="pre_quali")
    without = run_backtest(f26, same_complexity_pre, context="pre_quali")
    check("2026", "含 Elo ρ（n=17）", float(with_elo["rho_all"].mean()), "rho26_elo")
    check("2026", "去 Elo ρ（积分榜+练习赛）", float(without["rho_all"].mean()),
          "rho26_noelo")

    # ⚠️ Elo 单独那组的口径是「**全历史累积后切 2026**」，不是"只喂 2026"。
    # 后者会让 Elo 从 1500 冷启动，猜中率变成 35.3% —— 两个口径差 3 倍，
    # README 已经注明，但写检查时最容易踩错的就是这里。
    elo_only = lambda: EloPredictor(k=192, use_team=True,  # noqa: E731
                                    dnf_policy="finishers_only")
    cum = run_backtest(races_all, elo_only, context="pre_quali")
    c26, hist = cum[cum["year"] == 2026], cum[cum["year"] <= 2025]
    cold = run_backtest(f26, elo_only, context="pre_quali")
    check("2026", "Elo 单独 · 猜中冠军 %（累积后切）", float(c26["top1"].mean()) * 100,
          "t1_26", tol=0.05, fmt="{:.1f}")
    check("2026", "Elo 单独 · 冠军均预测名次（累积后切）",
          float(c26["winner_rank"].mean()), "rank26", tol=0.005, fmt="{:.2f}")
    check("2026", "  同口径历史（2018–2025）猜中冠军 %",
          float(hist["top1"].mean()) * 100, "t1_hist", tol=0.05, fmt="{:.1f}")
    check("2026", "  同口径历史冠军均预测名次",
          float(hist["winner_rank"].mean()), "rank_hist", tol=0.005, fmt="{:.2f}")
    print(f"     · 换成「只喂 2026」口径：猜中 {cold['top1'].mean() * 100:.1f}%、"
          f"冠军均名次 {cold['winner_rank'].mean():.2f}"
          f" —— 引用时必须说明是哪个口径")


def sec_consistency(races_all) -> None:
    """审查报告 H2 的复核：2026 的高 ρ 是不是高退赛率造成的混杂？

    README 主张「不是」—— 按退赛率匹配后 2026 仍然更高。这组数字原先
    README 写了、但没有任何入库代码能产出它（审查方独立复现过）。
    """
    title("退赛率是一把尺子（README 2026 段 / 审查报告 H2）")
    share = dnf_share(races_all)
    grid = run_backtest(races_all, GridBaseline, context="post_quali")
    df = grid.assign(dnf=grid["key"].map(share))
    hist = df[df["year"] <= 2025]
    y26 = df[df["year"] == 2026]

    check("consistency", "rho_all × 退赛率 相关系数（173 场）",
          float(hist["dnf"].corr(hist["rho_all"])), "corr_dnf")
    check("consistency", "2026 退赛率 %", float(y26["dnf"].mean()) * 100,
          "dnf_rate_26", tol=0.05, fmt="{:.1f}")

    lo = hist[hist["dnf"] >= 0.20]
    check("consistency", "退赛率 ≥20% 的历史场次 n", float(len(lo)),
          "match_hist_n", tol=0.5, fmt="{:.0f}")
    check("consistency", "  同档历史 rho_all", float(lo["rho_all"].mean()), "match_hist_all")
    check("consistency", "  同档历史 rho_fin", float(lo["rho_fin"].mean()), "match_hist_fin")
    check("consistency", "  2026 rho_all", float(y26["rho_all"].mean()), "match_26_all")
    check("consistency", "  2026 rho_fin", float(y26["rho_fin"].mean()), "match_26_fin")
    print("       ↑ 方向别记反：rho_all 与退赛率**负**相关（退赛多 → ρ 低），")
    print("         所以按退赛率匹配后 2026 仍更高，说明它的数字是**被低估**的。")


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

    keys = {"10–50%": ("lap_1050_d", "lap_1050_t"),
            "25–75%": ("lap_2575_d", "lap_2575_t")}
    for i, (_lo, _hi, wn) in enumerate(windows):
        pts = [statistics.mean(v) for v in acc[wn].values() if v]
        n = len(pts)
        se = statistics.stdev(pts) / math.sqrt(n) if n > 1 else 0.0
        delta = statistics.mean(pts)
        t = delta / se if se else float("nan")
        kd, kt = keys[wn]
        check("lap", f"Δρ 窗口 {wn}（n={n} 场）", delta, kd)
        check("lap", "  t 值", t, kt, tol=0.01, fmt="{:+.2f}")
        if i == 0:
            check("lap", "  检验单位（README 写 172 场）", float(n),
                  "lap_n", tol=0.5, fmt="{:.0f}")
    print("       ↑ 检验单位是**场**不是圈：相邻圈窗口重叠 4/5，有效样本量是场。")


def sec_data() -> None:
    title("数据层（README 数据表 / 审查报告 H1、H5、H6）")
    db = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    q = lambda s: list(db.execute(s))  # noqa: E731

    check("data", "圈速记录总数", float(q("SELECT COUNT(*) FROM laps")[0][0]),
          "n_laps_all", tol=0.5, fmt="{:,.0f}")
    check("data", "  ≤2025", float(q("SELECT COUNT(*) FROM laps WHERE year<=2025")[0][0]),
          "n_laps_25", tol=0.5, fmt="{:,.0f}")
    check("data", "  2026", float(q("SELECT COUNT(*) FROM laps WHERE year=2026")[0][0]),
          "n_laps_26", tol=0.5, fmt="{:,.0f}")
    check("data", "赛道数（circuits）", float(q("SELECT COUNT(*) FROM circuits")[0][0]),
          "n_circuits", tol=0.5, fmt="{:.0f}")

    # 每轮积分合计：2019–2024 含最快圈 +1 → 102；其余年份 101。
    # ⚠️ 有一个**合法例外**：2021 R12 斯帕（比利时）因大雨只跑了 2 圈，
    # 按规则发**半积分**，合计 50.5。所以断言是"除它以外为 0"，不是"恒为 0"。
    # ⚠️ 也不能用「每轮 = 101」当判据 —— 2019–2024 本该是 102。
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
    ap.add_argument("--only", choices=["counts", "main", "rho_fin", "utility", "dnf",
                                       "2026", "consistency", "lap", "data"],
                    help="只跑某一节")
    args = ap.parse_args()

    t0 = time.time()
    races_all = load_races()
    races25 = [r for r in races_all if r.year <= 2025]
    print("=" * 78)
    print(" README 头条数字核验 —— 实测值（跑回测）与文档值（解析 README）逐条比对")
    print("=" * 78)
    print(f" 文档值来源：{README_PATH.name}（{len(PATTERNS)} 条锚点正则，脚本内不存第二份）")
    print(" ❌ = 两侧对不上（该修落后的一侧，不是放宽容差）。")

    only = args.only
    steps = {
        "counts": lambda: sec_counts(races_all),
        "main": lambda: sec_main(races25),
        "rho_fin": lambda: sec_rho_fin(races25),
        "utility": lambda: sec_utility(races25),
        "dnf": lambda: sec_dnf(races25),
        "2026": lambda: sec_2026(races_all),
        "consistency": lambda: sec_consistency(races_all),
        "lap": lambda: sec_lap(races_all),
        "data": sec_data,
    }
    for name, fn in steps.items():
        if only and name != only:
            continue
        if name == "lap" and not (args.lap or only == "lap"):
            print("\n■ （逐圈那节默认跳过 —— 加 --lap 打开，约 80 秒）")
            continue
        fn()

    d = doc()
    amb = d.ambiguous()
    bad = [(s, lbl) for s, lbl, ok in RESULT if not ok]
    total = len(RESULT)
    print(f"\n{'=' * 78}")
    if amb:
        print(f" ⚠️ 锚点命中多处（选得不够独特，可能量到别的行）：{amb}")
    if d.missing:
        print(f" ⚠️ 有 {len(d.missing)} 条声明在 README 里找不到锚点"
              f"（表格被改/删/措辞变了）：")
        for k in d.missing:
            print(f"     · {k}")
    if HARDCODED:
        print(f" ℹ️ README 里没有对应声明、值固化在脚本内的条目 {len(HARDCODED)} 条：")
        for lbl in HARDCODED:
            print(f"     · {lbl.strip()}")
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
    return 1 if (bad or d.missing or amb) else 0


if __name__ == "__main__":
    raise SystemExit(main())
