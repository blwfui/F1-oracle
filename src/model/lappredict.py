"""逐圈预测器 —— 比赛**进行中**的「接下来会发生什么」。

与 `predictors.py` 的区别：

    predictors.py      赛前 / 排位赛后各调用一次，输入是横截面（Round）
    lappredict.py      每一圈都调用一次，输入是时间序列（LapTimeline + 当前圈）

协议（鸭子类型）：
    predict(tl: LapTimeline, lap: int) -> list[str]   按预测的最终完赛顺序
"""

from __future__ import annotations

import statistics
from typing import Protocol

from .lapdata import LapTimeline

# ── 已验证的最优配置（全库 172 场 × 每圈，中段 25–75% 配对检验）──────
#   g=0.25  ρ 0.8017 (Δ+0.0128 vs 基线, t=+7.71, 8/8 年为正)
#   g=0     ρ 0.7890 (基线：按累计时间 = 近似「当前名次」)
#   g=1.0   ρ 0.7800 (Δ-0.0089, t=-2.48 —— 完全相信节奏反而显著变差)
# gain 有内部峰值（0.2–0.3），不是边界解；且 8/8 年为正，不是靠某一年。
DEFAULT_WINDOW = 5
DEFAULT_GAIN = 0.25


class LapPredictor(Protocol):
    name: str

    def predict(self, tl: LapTimeline, lap: int) -> list[str]: ...


class CurrentOrder:
    """基线：**当前名次 = 最终名次**。

    它不知道速度、轮胎、策略，只知道现在谁在前面 —— 是逐圈预测的下界。
    实测整场平均 ρ ≈ 0.85（越高越好），任何「更聪明」的模型都必须超过它。
    """

    name = "当前名次（基线）"

    def predict(self, tl: LapTimeline, lap: int) -> list[str]:
        pos = tl.positions(lap)
        return sorted(pos, key=lambda d: pos[d])


class PaceProjection:
    """按「累计时间 + 近期干净节奏 × 剩余圈数」预估完赛时间。

    直觉：名次告诉你**谁在前面**，节奏告诉你**他能不能守住**。

        落后 2.0 秒、每圈快 0.50 秒、还剩 20 圈  →  预计反超
        落后 2.0 秒、每圈快 0.10 秒、只剩  5 圈  →  预计守住

    `gain` 是唯一参数，含义是「节奏优势里有多大比例真的会兑现」：
        gain = 0  → proj = 当前累计时间 → 退化成「按当前顺序」= CurrentOrder
        gain = 1  → 完全相信近期节奏会持续到终点

    用 `gain` 而不是直接融名次，是为了让 0 正好等于基线，扫描时能看出净增量。

    三项已知失真（方向都是保守）：
      - 刚进站的车手：累计时间含 20+ 秒停顿，且新胎圈被冷胎规则排除，
        节奏取自旧胎 → 会被低估（**保守**，宁可低估不虚高）
      - 还没进站的车手：预计时间不含未来的进站损失 → 会被高估（不保守）
      - 轮胎衰竭 / 燃油变轻：假设节奏恒定，忽略两者的时间趋势
    """

    def __init__(self, window: int = 5, gain: float = 1.0) -> None:
        self.window = window
        self.gain = gain
        self.name = f"节奏外推(gain={gain:g})"

    def predict(self, tl: LapTimeline, lap: int) -> list[str]:
        t = tl.times(lap)
        if not t:
            return []
        pace = tl.recent_pace(lap, self.window)
        vals = list(pace.values())
        fallback = statistics.median(vals) if vals else 90.0
        remaining = max(0, tl.total_laps - lap)
        proj = {d: t[d] + pace.get(d, fallback) * remaining * self.gain
                for d in t}
        return sorted(proj, key=lambda d: (proj[d], d))


def cached_pace(tl: LapTimeline, window: int = 5) -> dict[int, dict[str, float]]:
    """一次性算出全场的干净节奏表，供多个预测器复用。

    `recent_pace` 是逐圈预测里最贵的一步（要过清洗规则），而所有基于节奏的
    预测器都共用同一份 —— 不预计算的话，每加一个变体就重算一遍全场。
    """
    return {lap: tl.recent_pace(lap, window) for lap in sorted(tl.states)}


class PaceProjectionCached(PaceProjection):
    """`PaceProjection` 的预计算版本：节奏表由外部传入。"""

    def __init__(self, pace_table: dict, window: int = 5, gain: float = 1.0) -> None:
        super().__init__(window, gain)
        self._table = pace_table

    def predict(self, tl: LapTimeline, lap: int) -> list[str]:
        t = tl.times(lap)
        if not t:
            return []
        pace = self._table.get(lap, {})
        vals = list(pace.values())
        fallback = statistics.median(vals) if vals else 90.0
        remaining = max(0, tl.total_laps - lap)
        proj = {d: t[d] + pace.get(d, fallback) * remaining * self.gain
                for d in t}
        return sorted(proj, key=lambda d: (proj[d], d))


class PaceProjectionPit(PaceProjectionCached):
    """⚠️ 已证伪，勿用于生产路径 —— 保留是为了以后不再重走这条路。

    想法：`PaceProjection` 假设所有人保持当前节奏跑到终点，但还没进站的车手
    迟早要损失一次 ~20 秒，所以在 proj 上加一个未来进站惩罚。

    全库实测（172 场 × 每圈，61,884 个样本，中段 25–75% 进度的配对检验）：

        g=0.25 无补偿        Δρ = +0.0128   t = +7.71   为正年份 8/8   ← 最优
        g=0.25 + 进站补偿     Δρ = +0.0098   t = +2.80   为正年份 6/8
        g=0.6  + 进站补偿     Δρ = -0.0016   t = -0.42   为正年份 4/8
        g=1.0  + 进站补偿     Δρ = -0.0157   t = -3.56   为正年份 2/8

    **加了补偿反而全线变差**，且有剧烈的年代分裂：
        2018–2021 补偿大幅改善（+0.0211 vs 无补偿 +0.0125）
        2022–2025 补偿大幅恶化（-0.003 ~ -0.043）

    根因（概念错误，不是调参问题）：
        **进站损失是「迟早要付」的，不是「额外」的。**
        两车实力与位置相同、一个已停一个未停时，数学上 `t + 22` 对两者相等
        （已停者的 t 里已经含了那 22 秒），所以补偿本应中性。但现实中
        「早期就进过站」的车手多是被迫进站（换鼻翼、事故、被罚），他们
        **通常还要再停一次**；`target_stops=1` 让他们 future=0 而免于惩罚，
        于是被系统性抬高。早期桶 ρ 因此掉 0.023。

        2022 年后轮胎策略多样性大增（0 停/1 停/2 停混合），单一 target 更不成立。

    教训：**「已经付过的成本」不等于「优势」。** 想建模进站影响，要建模的是
    「战术位置」（会不会掉进慢车堆、会不会被 undercut），而不是一个绝对秒数。
    """

    def __init__(self, pace_table: dict, window: int = 5, gain: float = 1.0,
                 pit_loss: float = 22.0, target_stops: int = 1,
                 coef: float = 1.0) -> None:
        super().__init__(pace_table, window, gain)
        self.pit_loss = pit_loss
        self.target_stops = target_stops
        self.coef = coef
        self.name = f"节奏外推(g={gain:g})+进站补偿({coef:g})"

    def predict(self, tl: LapTimeline, lap: int) -> list[str]:
        t = tl.times(lap)
        if not t:
            return []
        pace = self._table.get(lap, {})
        vals = list(pace.values())
        fallback = statistics.median(vals) if vals else 90.0
        remaining = max(0, tl.total_laps - lap)
        st = tl.states.get(lap, {})
        proj = {}
        for d in t:
            stint = st.get(d, {}).get("stint") or 1
            future = max(0, self.target_stops - (stint - 1))
            proj[d] = (t[d] + pace.get(d, fallback) * remaining * self.gain
                       + self.pit_loss * future * self.coef)
        return sorted(proj, key=lambda d: (proj[d], d))
