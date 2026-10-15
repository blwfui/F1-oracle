"""H4 · 选参与评估分离（留出集 / 前向滚动 / 留一赛季）。

    python -m scripts.holdout_eval             # 主切分 + 前向滚动（约 3 分钟）
    python -m scripts.holdout_eval --loso      # 额外做留一赛季（非前瞻，仅稳健性）
    python -m scripts.holdout_eval --write     # 落档 docs/留出集验证.md

## 这个脚本要解决的问题

审查报告 H4：项目里**每一个**"显著增益"背后都有一个在**同一批 173 场**上取
argmax 的选择 —— Elo 的 `k` × `dnf_policy`（18 组）、融合权重（每组 6 档）、
罚退收缩 `α`（3 档）、逐圈 `gain`（4+ 档）。于是那些 p 值都没有扣除
"从几十组里挑最好"这件事，名义显著性偏乐观。

本脚本把调参面搬到一个**看不见的年份区间**上重选一遍，再在被"锁起来"的年份上
评估 —— 也就是报告 §62 建议的 P1。

## 三个协议

| 协议 | 训练 | 测试 | 回答的问题 |
|---|---|---|---|
| 主切分 | 2018–2022 | 2023–2025 | "拿着头五季调参，后三季还灵吗" |
| 前向滚动 | 逐年扩张，只用 test 年**之前**的赛季 | 2021–2025 逐年 | "回到那一年当下，能前瞻吗"（时间序列唯一严格的协议） |
| 留一赛季 | 其余 7 年（**含未来赛季**） | 每年 | "跨赛季可迁移吗"（非前瞻，只作稳健性对照） |

三个都跑是有意的：**主切分**是报告点名要的，**前向滚动**才是无泄漏的，
而**留一赛季**是报告原文的字面建议。三者结论一致才说明结论不靠协议挑选。

## 两个实现上的坑

1. **评估时必须跑完整时间轴再切年份。** Elo 是顺序学习的（`observe` 累积评分）。
   若只把测试年喂进预测器，每一折都从 base=1500 冷启动，留出年会被系统性低估 ——
   那不是"泛化差"，是"没给模型热车"。`Board` 就是为这件事存在的。

2. **2026 完全不参与。** 本脚本的赛道只有 2018–2025 的 173 场；2026 是"当下赛季"，
   既不当训练集也不当测试集，避免任何形式的逆向影响（README 里 2026 单列）。

## 预注册判据

`KILL` 常量在**看到任何结果之前**写死。留出结论必须同时满足三条，
否则一律标注"未通过留出验证"，不得进入 README 头条。
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 中文 Windows 默认 cp936，本脚本输出含「ρ / Δ / ✅」—— 与 run_backtest.py 同理兜底
for _s in (sys.stdout, sys.stderr):
    if _s.encoding and _s.encoding.lower().replace("-", "") not in ("utf8", "utf8mb4"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

import pandas as pd  # noqa: E402

from src.model.backtest import load_races, run_backtest  # noqa: E402
from src.model.predictors import (  # noqa: E402
    AdjustedGridBaseline, EloPredictor, GridBaseline, PointsBaseline,
    PracticePaceBaseline, QualiGapBaseline, RankBlend, best_post, best_pre,
)

RULE = "─" * 78

# ── 调参面 ──────────────────────────────────────────────────
K_GRID = (8, 16, 24, 40, 64, 96, 128, 192, 256)
POLICIES = ("as_position", "finishers_only")
ALPHAS = (0.5, 0.75, 1.0)
# ⚠️ min_pen 的网格上边界：初版取 (3, 5, 10)，结果**每一折都选中 10** ——
# 命中网格边界等于调参器在说"再往外还有更优的"。扩到 20 再确认一次：
# 若仍命中 20，说明这个自由度对目标函数几乎无差别（扁平），那就不该当作
# 一个"选出来的超参"对外报告；若落回内部，说明原来的网格确实卡住了。
MIN_PENS = (3, 5, 10, 15, 20)
W_STEP = 0.2

# 冻结权重 —— 只用于「选 α / min_pen」那一阶段，与 best_post 的现状一致
FROZEN_PRE_W = (0.4, 0.3, 0.3)
FROZEN_POST_W = (0.4, 0.3, 0.3)

# ── 预注册判据（写在看到任何结果之前，不许事后调）──────────────
KILL = {
    "min_delta": 0.0,        # 留出平均 Δρ 必须为正
    "min_t": 2.0,            # 配对 t 必须过项目自己的 |t|>2 门槛
    "min_pos_year_frac": 0.5,  # 正向年份占比 ≥ 半数（跨赛季稳定性）
}

HEADLINE_YEARS = tuple(range(2018, 2026))


# ═══════════════════════════════════════════════════════════
# 工厂。全部无参可调用 —— 预测器有状态，复用实例会静默泄漏。
# ═══════════════════════════════════════════════════════════
def elo_factory(k: float, policy: str):
    return lambda: EloPredictor(k=k, use_team=True, dnf_policy=policy)


def pre_factory(k: float, policy: str, w: tuple[float, float, float]):
    """赛前组合：w = (Elo, 赛前积分榜, 练习赛)。权重为 0 的分量直接不构造。"""
    we, wp, wf = w
    def build():
        parts = []
        if we:
            parts.append((EloPredictor(k=k, use_team=True, dnf_policy=policy), we))
        if wp:
            parts.append((PointsBaseline(), wp))
        if wf:
            parts.append((PracticePaceBaseline(), wf))
        return RankBlend(parts, "pre")
    return build


def post_factory(k: float, policy: str, alpha: float, min_pen: int,
                 w: tuple[float, float, float]):
    """赛后组合：w = (罚退收缩发车格, 排位秒差, Elo)。"""
    wg, wq, we = w
    def build():
        parts = []
        if wg:
            parts.append((AdjustedGridBaseline(alpha=alpha, min_pen=min_pen), wg))
        if wq:
            parts.append((QualiGapBaseline(), wq))
        if we:
            parts.append((EloPredictor(k=k, use_team=True, dnf_policy=policy), we))
        return RankBlend(parts, "post")
    return build


# ── 对照组：与 README「同复杂度」口径逐字一致 ────────────────
def cmp_pre():
    return RankBlend([(PointsBaseline(), 0.5), (PracticePaceBaseline(), 0.5)],
                     "积分榜+练习赛")


def cmp_post():
    return RankBlend([(GridBaseline(), 0.3), (QualiGapBaseline(), 0.7)],
                     "发车格+秒差")


def simplex(step: float = W_STEP):
    """三点单纯形网格（权重和 = 1）。"""
    n = round(1.0 / step)
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            yield (round(i * step, 10), round(j * step, 10), round(k * step, 10))


# ═══════════════════════════════════════════════════════════
# Board —— 跑完整时间轴，只对指定年份取分
# ═══════════════════════════════════════════════════════════
class Board:
    """按时间顺序跑一遍全量回测，计分时按年份裁剪。

    ⚠️ **这是本脚本最要紧的一处。** 若改成"只把测试年喂进预测器"，
    Elo 每折都从 1500 冷启动，留出年的 ρ 会被系统性压低 —— 那不是泛化能力，
    那是没给模型热车。用缓存是为了让同一个配置在多个折之间只跑一次。
    """

    def __init__(self, races, context: str) -> None:
        self.races = races
        self.context = context
        self._cache: dict[str, pd.DataFrame] = {}

    def df(self, tag: str, factory) -> pd.DataFrame:
        if tag not in self._cache:
            self._cache[tag] = run_backtest(self.races, factory,
                                            context=self.context)
        return self._cache[tag]

    def mean_rho(self, tag: str, factory, years) -> float:
        d = self.df(tag, factory)
        d = d[d["year"].isin(years)]
        return float(d["rho_all"].mean()) if len(d) else float("nan")

    @property
    def n_evals(self) -> int:
        return len(self._cache)


# ═══════════════════════════════════════════════════════════
# 统计
# ═══════════════════════════════════════════════════════════
def paired_delta(a: pd.DataFrame, b: pd.DataFrame, years) -> dict:
    """逐场配对：b − a，只在 years 上算。a 是对照，b 是被检验方。"""
    aa = a[a["year"].isin(years)][["key", "year", "rho_all"]]
    bb = b[b["year"].isin(years)][["key", "rho_all"]]
    m = aa.merge(bb, on="key", suffixes=("_a", "_b"))
    d = (m["rho_all_b"] - m["rho_all_a"]).dropna()
    n = len(d)
    if n < 2:
        return {"delta": float("nan"), "t": float("nan"), "n": n,
                "pos": 0, "years": {}, "frame": m}
    se = float(d.std(ddof=1)) / math.sqrt(n)
    per_year = (m.assign(d=m["rho_all_b"] - m["rho_all_a"])
                .dropna(subset=["d"]).groupby("year")["d"].mean().to_dict())
    return {
        "delta": float(d.mean()),
        "t": float(d.mean() / se) if se else float("nan"),
        "n": n,
        "pos": sum(1 for v in per_year.values() if v > 0),
        "years": {int(k): float(v) for k, v in per_year.items()},
        "frame": m,
    }


def fmt_delta(r: dict) -> str:
    # t 保留三位小数：预注册判据是 t>2，卡在线上时两位小数看不出是 1.998 还是 2.004
    return (f"Δρ={r['delta']:+.4f}  t={r['t']:+.3f}  n={r['n']:>3}  "
            f"年为正 {r['pos']}/{len(r['years'])}")


# ═══════════════════════════════════════════════════════════
# 调参：在训练年份上重新选一遍全部超参
# ═══════════════════════════════════════════════════════════
N_CONFIGS = len(K_GRID) * len(POLICIES) + len(ALPHAS) * len(MIN_PENS) \
    + len(list(simplex())) * 2


def tune(train_years, pre: Board, post: Board, trace: list[str]) -> dict:
    """在 train_years 上选超参。返回选点与各自的训练分。

    顺序是**分阶段**的（Elo → 罚退收缩 → 权重），不是联合网格 ——
    联合网格是 18×9×21×21 ≈ 7 万组，跑不动；分阶段调参的调参面更小，
    对留出集是**更保守**的做法（可选的组数少 → 挑到噪声的机会少）。
    实际评估过的组数记在 N_CONFIGS 里，一并落档。
    """
    # ── 阶段 A1：Elo k × dnf_policy（用赛前口径的裸 Elo 选）
    best_elo = None
    for k in K_GRID:
        for pol in POLICIES:
            r = pre.mean_rho(f"elo|{k}|{pol}", elo_factory(k, pol), train_years)
            if best_elo is None or r > best_elo[0]:
                best_elo = (r, k, pol)
    train_elo, K, POL = best_elo
    trace.append(f"    A1 Elo        k={K} {POL:<15} 训练裸 Elo ρ={train_elo:.4f}"
                 f"  （{len(K_GRID) * len(POLICIES)} 组）")

    # ── 阶段 A2：罚退收缩 α × min_pen（冻结权重 0.4/0.3/0.3）
    best_adj = None
    for a in ALPHAS:
        for mp in MIN_PENS:
            r = post.mean_rho(f"adj|{K}|{POL}|{a}|{mp}",
                              post_factory(K, POL, a, mp, FROZEN_POST_W),
                              train_years)
            if best_adj is None or r > best_adj[0]:
                best_adj = (r, a, mp)
    train_adj, ALPHA, MIN_PEN = best_adj
    trace.append(f"    A2 罚退收缩    α={ALPHA:g} min_pen={MIN_PEN:<9} "
                 f"训练 ρ={train_adj:.4f}  （{len(ALPHAS) * len(MIN_PENS)} 组）")

    # ── 阶段 B1/B2：融合权重
    best_w_pre = None
    for w in simplex():
        r = pre.mean_rho(f"pre|{K}|{POL}|{w}", pre_factory(K, POL, w), train_years)
        if best_w_pre is None or r > best_w_pre[0]:
            best_w_pre = (r, w)
    train_pre, W_PRE = best_w_pre

    best_w_post = None
    for w in simplex():
        r = post.mean_rho(f"post|{K}|{POL}|{ALPHA}|{MIN_PEN}|{w}",
                          post_factory(K, POL, ALPHA, MIN_PEN, w), train_years)
        if best_w_post is None or r > best_w_post[0]:
            best_w_post = (r, w)
    train_post, W_POST = best_w_post
    trace.append(f"    B1 赛前权重    {w_pre_txt(W_PRE)}  训练 ρ={train_pre:.4f}"
                 f"  （{len(list(simplex()))} 组）")
    trace.append(f"    B2 赛后权重    {w_post_txt(W_POST)}  训练 ρ={train_post:.4f}"
                 f"  （{len(list(simplex()))} 组）")

    return {
        "k": K, "policy": POL, "alpha": ALPHA, "min_pen": MIN_PEN,
        "w_pre": W_PRE, "w_post": W_POST,
        "train_pre": train_pre, "train_post": train_post,
    }


def w_pre_txt(w) -> str:
    return f"{w[0]:.1f}+榜{w[1]:.1f}+练{w[2]:.1f}"


def w_post_txt(w) -> str:
    return f"{w[0]:.1f}+差{w[1]:.1f}+Elo{w[2]:.1f}"


def _pad(text: str, width: int) -> str:
    """按**显示宽度**补空格。中文一字占两列，用 len() 补必然错位。"""
    import unicodedata
    cur = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(1, width - cur)


# ═══════════════════════════════════════════════════════════
# 协议
# ═══════════════════════════════════════════════════════════
def run_protocol(name: str, folds, pre: Board, post: Board, out: list[str],
                 note: list[str] | None = None):
    """跑一个协议的若干折，返回逐场留出差（用于汇总 OOF）与各折选点。

    note 是紧随标题之后的原样说明 —— 用来写清这个协议的**读法陷阱**
    （例如留一赛季的各折训练集几乎相同，选点必然一致）。
    """
    out.append(f"\n■ {name}")
    out.append(RULE)
    for line in (note or []):
        out.append(f"  ⚠️ {line}")
    oof_pre, oof_post, cfgs = [], [], []

    for train_years, test_years, label in folds:
        trace = [f"\n  ▸ {label}"]
        cfg = tune(train_years, pre, post, trace)
        cfgs.append((label, cfg))

        fpre = pre_factory(cfg["k"], cfg["policy"], cfg["w_pre"])
        fpost = post_factory(cfg["k"], cfg["policy"], cfg["alpha"],
                             cfg["min_pen"], cfg["w_post"])

        d_pre = paired_delta(pre.df("cmp_pre", cmp_pre),
                             pre.df(f"pre|{cfg['k']}|{cfg['policy']}|{cfg['w_pre']}", fpre),
                             test_years)
        d_post = paired_delta(post.df("cmp_post", cmp_post),
                              post.df(f"post|{cfg['k']}|{cfg['policy']}|{cfg['alpha']}"
                                      f"|{cfg['min_pen']}|{cfg['w_post']}", fpost),
                              test_years)

        for r in trace:
            out.append(r)
        out.append(f"    选点           Elo k={cfg['k']}/{cfg['policy']}"
                   f" | 收缩 α={cfg['alpha']:g},≥{cfg['min_pen']}"
                   f" | 赛前 {w_pre_txt(cfg['w_pre'])}"
                   f" | 赛后 {w_post_txt(cfg['w_post'])}")
        out.append(f"    训练 ρ         赛前 {cfg['train_pre']:.4f}"
                   f"   赛后 {cfg['train_post']:.4f}")
        out.append(f"    留出（赛前 vs 同复杂度）  {fmt_delta(d_pre)}")
        out.append(f"    留出（赛后 vs 同复杂度）  {fmt_delta(d_post)}")
        if d_pre["years"]:
            out.append("      赛前逐年：" + "  ".join(
                "%d %+.4f" % (y, v) for y, v in sorted(d_pre["years"].items())))
        if d_post["years"]:
            out.append("      赛后逐年：" + "  ".join(
                "%d %+.4f" % (y, v) for y, v in sorted(d_post["years"].items())))

        oof_pre.append(d_pre["frame"].assign(protocol=name))
        oof_post.append(d_post["frame"].assign(protocol=name))

    stability(cfgs, out)
    return pd.concat(oof_pre, ignore_index=True), pd.concat(oof_post, ignore_index=True)


def stability(cfgs: list, out: list[str]) -> None:
    """各折选点的一致性统计。

    这一段是留出验证的**副产品，但可能比主结论更重要**：如果同一个超参在各折
    选出完全不同的值，那它在报告里就不该被写成"调出来的最优值" —— 它只是噪声。
    命中网格边界（取到两端）也要点名，那说明网格卡住了调参器。
    """
    from collections import Counter

    if not cfgs:
        return
    n = len(cfgs)
    out.append(f"\n  选点稳定性（{n} 折）")
    out.append(f"    {'自由度':<16}{'各折选点':<44}{'判断'}")

    def line(name: str, values: list, edges: tuple | None = None) -> None:
        cnt = Counter(values)
        txt = ", ".join(f"{k}×{v}" for k, v in cnt.most_common())
        if len(cnt) == 1:
            note = "✅ 一致"
        else:
            note = f"⚠️ 不稳定（{len(cnt)} 种）"
        if edges and any(v in edges for v in values):
            note += "  ⚠️ 命中网格边界"
        out.append(f"    {_pad(name, 16)}{_pad(txt, 44)}{note}")

    line("Elo dnf_policy", [c["policy"] for _, c in cfgs])
    line("Elo k", [c["k"] for _, c in cfgs])
    line("α（罚退收缩）", [c["alpha"] for _, c in cfgs])
    line("min_pen", [c["min_pen"] for _, c in cfgs], edges=(MIN_PENS[0], MIN_PENS[-1]))
    line("赛前权重", [w_pre_txt(c["w_pre"]) for _, c in cfgs])
    line("赛后权重", [w_post_txt(c["w_post"]) for _, c in cfgs])
    out.append("    （一致 = 该自由度被数据识别出来；不稳定 = 它在噪声里，")
    out.append("      不应被当作「调出来的最优值」对外引用。）")


def summarize_oof(name: str, oof: pd.DataFrame, out: list[str]) -> dict:
    """把各折的留出逐场差拼成一条 OOF 序列（每场恰好出现一次）再算总 t。

    逐折 t 单独看样本量太小（单赛季 ~22 场）；拼起来才是留出集的完整证据。
    """
    d = (oof["rho_all_b"] - oof["rho_all_a"]).dropna()
    n = len(d)
    if n < 2:
        out.append(f"  {name:<10} 样本不足")
        return {"delta": float("nan"), "t": float("nan"), "n": n,
                "pos": 0, "years": {}}
    se = float(d.std(ddof=1)) / math.sqrt(n)
    per_year = (oof.assign(d=oof["rho_all_b"] - oof["rho_all_a"])
                .dropna(subset=["d"]).groupby("year")["d"].mean().to_dict())
    r = {"delta": float(d.mean()), "t": float(d.mean() / se) if se else float("nan"),
         "n": n, "pos": sum(1 for v in per_year.values() if v > 0),
         "years": per_year}
    out.append(f"  {name:<10} {fmt_delta(r)}   "
               f"[预注册门槛：Δρ>{KILL['min_delta']:g} 且 t>{KILL['min_t']:g} "
               f"且 年为正≥{KILL['min_pos_year_frac']:.0%}]")
    return r


# ═══════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loso", action="store_true",
                    help="额外做留一赛季（训练含未来赛季，非前瞻，仅稳健性对照）")
    ap.add_argument("--write", action="store_true",
                    help="落档到 docs/留出集验证.md")
    args = ap.parse_args()

    t0 = time.time()
    races = [r for r in load_races() if r.year <= 2025]
    years = sorted({r.year for r in races})
    assert years == list(HEADLINE_YEARS), years
    assert len(races) == 173, len(races)   # README 头条口径

    out: list[str] = []
    def emit(line: str = "") -> None:
        out.append(line)

    emit("=" * 78)
    emit(f" H4 · 留出集验证 · 2018–2025，{len(races)} 场（2026 不参与）")
    emit("=" * 78)
    emit("")
    emit(" 调参面（每折独立重选，顺序分阶段）：")
    emit(f"   A1 Elo k × dnf_policy        {len(K_GRID)} × {len(POLICIES)}"
         f" = {len(K_GRID) * len(POLICIES)} 组   （赛前口径的裸 Elo）")
    emit(f"   A2 罚退收缩 α × min_pen       {len(ALPHAS)} × {len(MIN_PENS)}"
         f" = {len(ALPHAS) * len(MIN_PENS)} 组   （冻结权重）")
    emit(f"   B1 赛前融合权重（单纯形 {W_STEP}）  {len(list(simplex()))} 组")
    emit(f"   B2 赛后融合权重（单纯形 {W_STEP}）  {len(list(simplex()))} 组")
    emit(f"   —— 每折实评估 {N_CONFIGS} 组；选点是**顺序**做的，不是联合网格，")
    emit("      调参面比 18×9×21×21 小得多 —— 对留出集是更保守的做法。")

    pre = Board(races, "pre_quali")
    post = Board(races, "post_quali")

    # ── 协议 1：主切分 ───────────────────────────────────────
    tr1 = (2018, 2019, 2020, 2021, 2022)
    te1 = (2023, 2024, 2025)
    folds_split = [(tr1, te1,
                    f"主切分 · train {tr1[0]}–{tr1[-1]}"
                    f"（{sum(1 for r in races if r.year in tr1)} 场）"
                    f" → test {te1[0]}–{te1[-1]}"
                    f"（{sum(1 for r in races if r.year in te1)} 场）")]
    oof_pre_s, oof_post_s = run_protocol("协议 1 · 主切分（报告 §62 的 P1）",
                                         folds_split, pre, post, out,
                                         note=["超参只在 2018–2022 上选，2023–2025 完全没看过。",
                                               "这是报告点名要的那个切分。"])

    # ── 协议 2：前向滚动（唯一无泄漏的协议）──────────────────
    folds_walk = []
    for y in (2021, 2022, 2023, 2024, 2025):
        tr = tuple(v for v in HEADLINE_YEARS if v < y)
        folds_walk.append((tr, (y,),
                           f"前向滚动 · train {tr[0]}–{tr[-1]}"
                           f"（{sum(1 for r in races if r.year in tr)} 场）"
                           f" → test {y}（{sum(1 for r in races if r.year == y)} 场）"))
    oof_pre_w, oof_post_w = run_protocol(
        "协议 2 · 前向滚动（test 年只用它之前的赛季调参）",
        folds_walk, pre, post, out,
        note=[f"没有泄漏：每一折的训练集严格早于测试年。代价是前几折训练样本少"
              f"（2018–2020 只有 59 场），选参本身噪声大 —— 这正是协议 1 存在的理由。",
              f"OOF 汇总里每场恰好出现一次，所以 n={sum(1 for r in races if r.year >= 2021)}。"])

    # ── 协议 3：留一赛季（可选）─────────────────────────────
    if args.loso:
        folds_loso = [((v for v in HEADLINE_YEARS if v != y), (y,),
                       f"留一赛季 · train 除 {y} 外 7 年 → test {y}")
                      for y in HEADLINE_YEARS]
        folds_loso = [(tuple(t), te, lab) for t, te, lab in folds_loso]
        from collections import Counter as _C
        per_year = _C(r.year for r in races)
        sizes = {y: len(races) - per_year[y] for y in HEADLINE_YEARS}
        lo = min(sizes.values())
        # 两折训练集交集 = 173 − 被测两年之和；取最坏（两场最大的年份）
        two_big = sum(sorted(per_year.values())[-2:])
        worst = len(races) - two_big
        oof_pre_l, oof_post_l = run_protocol(
            "协议 3 · 留一赛季（⚠️ 训练含未来赛季，非严格前瞻）",
            folds_loso, pre, post, out,
            note=[f"**这个协议的 8 折训练集几乎同一份**（{lo}–{max(sizes.values())} 场，"
                  f"任意两折交集最少 {worst} 场 ≈ 最坏情况下仍重叠 {worst / lo:.0%}）。",
                  "所以各折选点必然一致、OOF 序列也不是 8 次独立泛化检验 —— "
                  "它等价于「一个配置在 173 场上的配对 t」。",
                  "本协议的作用只有一条：确认结论**不依赖**协议 1/2 那种时间切法。"])
    else:
        oof_pre_l = oof_post_l = None

    # ── 汇总 ─────────────────────────────────────────────────
    emit("")
    emit("=" * 78)
    emit(" 汇总 · 留出集上的增量（对照一律是 README 的「同复杂度」口径）")
    emit("=" * 78)

    emit("\n 协议 1 · 主切分（test = 2023–2025）")
    s_pre = summarize_oof("赛前", oof_pre_s, out)
    s_post = summarize_oof("赛后", oof_post_s, out)

    emit("\n 协议 2 · 前向滚动 OOF（test = 2021–2025，每场恰好一次）")
    w_pre = summarize_oof("赛前", oof_pre_w, out)
    w_post = summarize_oof("赛后", oof_post_w, out)

    if oof_pre_l is not None:
        emit("\n 协议 3 · 留一赛季 OOF（非前瞻，仅稳健性）")
        l_pre = summarize_oof("赛前", oof_pre_l, out)
        l_post = summarize_oof("赛后", oof_post_l, out)
    else:
        l_pre = l_post = None

    # ── 样本内 vs 留出：缩水多少 ────────────────────────────
    emit("\n" + RULE)
    emit(" 样本内选点（在全 173 场上调出来的 best_pre / best_post）")
    emit(RULE)
    in_pre = paired_delta(pre.df("cmp_pre", cmp_pre), pre.df("best_pre", best_pre),
                          HEADLINE_YEARS)
    in_post = paired_delta(post.df("cmp_post", cmp_post), post.df("best_post", best_post),
                           HEADLINE_YEARS)
    emit(f"   全 173 场   赛前 {fmt_delta(in_pre)}")
    emit(f"   全 173 场   赛后 {fmt_delta(in_post)}")
    emit(f"   仅 2023–2025（与协议 1 同一批 test 场）")
    in_pre_t = paired_delta(pre.df("cmp_pre", cmp_pre), pre.df("best_pre", best_pre),
                            (2023, 2024, 2025))
    in_post_t = paired_delta(post.df("cmp_post", cmp_post), post.df("best_post", best_post),
                             (2023, 2024, 2025))
    emit(f"     赛前 {fmt_delta(in_pre_t)}")
    emit(f"     赛后 {fmt_delta(in_post_t)}")
    emit("")
    emit("   → 「样本内」= 超参在全 173 场上挑过；同一批 test 场上的 Δρ 与之相比")
    emit("     的缩水，就是 H4 指控的那部分乐观。留出协议的 Δρ 才是可对外引用的数字。")

    # ── 预注册判据裁决 ──────────────────────────────────────
    emit("\n" + RULE)
    emit(" 预注册判据裁决（判据写在看到任何结果之前，见本脚本 KILL）")
    emit(RULE)

    def verdict(tag: str, r: dict) -> str:
        ok = (r["delta"] > KILL["min_delta"] and r["t"] > KILL["min_t"]
              and r["pos"] >= KILL["min_pos_year_frac"] * len(r["years"]))
        return f"   {_pad(tag, 38)}{'✅ 通过' if ok else '❌ 未通过'}"

    emit(verdict("协议 1 赛前（主切分）", s_pre))
    emit(verdict("协议 1 赛后（主切分）", s_post))
    emit(verdict("协议 2 赛前（前向滚动 OOF）", w_pre))
    emit(verdict("协议 2 赛后（前向滚动 OOF）", w_post))
    if l_pre is not None:
        emit(verdict("协议 3 赛前（留一赛季，非前瞻）", l_pre))
        emit(verdict("协议 3 赛后（留一赛季，非前瞻）", l_post))

    emit(f"\n（用时 {time.time() - t0:.1f}s；"
         f"赛前口径跑过 {pre.n_evals} 个配置，赛后 {post.n_evals} 个）")

    text = "\n".join(out)
    print(text)

    if args.write:
        dst = ROOT / "docs" / "留出集验证.md"
        head = (
            "# H4 · 留出集验证记录\n\n"
            "> 本文件由 `python -m scripts.holdout_eval --write` 生成，请勿手改。\n"
            "> 对应 `docs/审查报告-缺点清单.md` 的 **H4（无留出集）**。\n"
            "> 表头说明见 `scripts/holdout_eval.py` 的模块 docstring。\n\n"
            "```text\n"
        )
        dst.write_text(head + text + "\n```\n", encoding="utf-8")
        print(f"\n已落档：{dst}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
