"""干净圈速管线 —— 把「不可比的圈」系统地剔除，再谈速度。

为什么必须做
------------
`recent_pace` 早期只排除了进站圈，漏了安全车圈。实测 2021 R22 第 40 圈：
SAI 的近 6 圈里混进 3 个安全车圈（93.8 / 115.4 / 101.6s），中位数被从真实的
88.3s 拉到 91.1s —— **凭空造出 3 秒/圈的假差距，让「追得上吗」的结论反向**。

所以「赛事分析」的成败在地基，不在模型。本模块把所有已知的「不可比」来源
集中定义成一处，任何要算速度差的地方都必须经过它。

五类不可比的圈
--------------
======== ====================================================
无圈速    lap_time 缺失（第 1 圈恒缺失）
进站圈    is_pit=1（含 in-lap 与 out-lap），含 20+ 秒维修区停顿
冷胎圈    换胎后的第一圈飞行圈，轮胎未达工作温度
安全车圈  安全车/虚拟安全车，整场被压缩，圈速失去可比性
交通受损  被慢车/蓝旗拖慢，用 stint 内稳健离群判定
======== ====================================================

燃油效应 —— 它其实会自动抵消
------------------------------
车越跑越轻（约 2 kg/圈），所以圈速随时间系统性变快，量级约 0.03–0.06 s/圈。
但 **同圈比较两个车手时，两人的燃油负荷完全相同，效应自动抵消** ——
它只在「跨时间比较」时才需要修正（例如拿第 1 段 stint 的节奏去比第 3 段）。
所以它不该被无差别地施加到所有圈速上。
"""

from __future__ import annotations

import statistics
from typing import Iterable

# ── 不可比原因（同时也是 flag 的名字）────────────────────────
NO_TIME = "无圈速"
PIT = "进站圈"
COLD = "冷胎/起步圈"
NEUTRALIZED = "安全车"
TRAFFIC = "交通受损"

ALL_REASONS = (NO_TIME, PIT, COLD, NEUTRALIZED, TRAFFIC)

# ── 参数（由全库 184,395 条圈速实测确定，见 §实测依据）────────
COLD_TYRE_LAPS = 2        # 换胎后前 N 圈视为冷胎
TRAFFIC_MAD_K = 3.0       # 慢于 stint 中位数 k 个 MAD 视为异常
TRAFFIC_MIN_S = 0.7       # 且至少慢这么多秒（避免把正常波动当交通）
MIN_STINT_CLEAN = 4       # stint 干净圈少于这么多就不做离群判定（样本太小）
FUEL_EFFECT_S_PER_LAP = 0.023   # 燃油效应：每跑一圈变轻带来的圈速收益（秒）
TYRE_DEG_S_PER_LAP = 0.014      # 燃油修正后的纯轮胎衰竭（秒/圈），仅作参考

# ── 实测依据（184,395 条圈速，2018–2025）────────────────────
# 冷胎惩罚（观察值 − 该 stint 自身趋势，彻底剥离燃油与衰竭）：
#     距上次进站    SOFT     MEDIUM   HARD     全部
#        1 圈     +1.393s  +0.705s  +0.037s  +0.312s
#        2 圈     +0.284s  +0.275s  +0.065s  +0.203s
#        3 圈     −0.019s  −0.001s  +0.013s    ≈0
#   → 第 3 圈起全部归零，故 COLD_TYRE_LAPS = 2。
#   → 硬胎几乎不受影响（对温度不敏感），软胎第 1 圈要慢 1.4 秒。
#
# 燃油效应（同车手同场、同配方、跨 stint 比「同胎龄基准圈速」）：
#   n=1,374 对 → 0.023 s/圈；用该值修正后残差归零，自洽。
#   ⚠️ 同圈比较两个车手时**不要**修正 —— 两人燃油相同，效应本就抵消。
#
# 轮胎衰竭（燃油修正后的 stint 内斜率）：
#   SOFT +0.0141 / MEDIUM +0.0135 / HARD +0.0154 s/圈
#   （修正前斜率是 −0.013 s/圈，为负 —— 燃油收益盖过衰竭，这正是必须修正的原因）


def stint_key(driver: str, state: dict) -> tuple[str, int]:
    st = state.get("stint")
    return (driver, int(st) if st is not None else -1)


def stint_stats(tl) -> dict[tuple[str, int], tuple[float, float, int]]:
    """按 (车手, stint) 统计**初步干净圈**（仅排除无圈速/进站/安全车）的中位数与 MAD。

    交通判定必须基于一个尚未被交通污染的基线，所以这一层只做「结构性」排除。
    """
    groups: dict[tuple[str, int], list[float]] = {}
    for lap, drivers in tl.states.items():
        neutral = tl.is_neutralized(lap)
        for d, st in drivers.items():
            if not st["lap_time"] or st["is_pit"] or neutral:
                continue
            groups.setdefault(stint_key(d, st), []).append(st["lap_time"])

    stats: dict[tuple[str, int], tuple[float, float, int]] = {}
    for key, times in groups.items():
        med = statistics.median(times)
        mad = statistics.median([abs(t - med) for t in times])
        stats[key] = (med, mad, len(times))
    return stats


def is_cold_tyre(tl, driver: str, lap: int, lookback: int | None = None) -> bool:
    """该圈是否属于「轮胎未进入工作状态」的圈 —— 换胎后前几圈，或比赛起跑的前几圈。

    两种情形合并处理，因为圈速同样不可比：
      - 换胎后：往前数 lookback 圈内出现过进站（out-lap 本身已被 is_pit 排除，
        这里覆盖的是出站后的第 1、2 个飞行圈）
      - 起跑后：lap 号本身就在前 lookback 圈内（静态起步 + 车阵密集 + 油最满）

    实测（见模块顶部）两种情形都在第 3 圈恢复，故 lookback = COLD_TYRE_LAPS = 2。
    """
    n = COLD_TYRE_LAPS if lookback is None else lookback
    if lap <= n:
        return True
    for k in range(lap - 1, lap - 1 - n, -1):
        if k < 1:
            break
        prev = tl.states.get(k, {}).get(driver)
        if prev and prev.get("is_pit"):
            return True
    return False


def flag_lap(tl, driver: str, lap: int, stats: dict,
             check_traffic: bool = True) -> set[str]:
    """返回该圈「不可比」的原因集合。空集表示这是一条干净圈。"""
    st = tl.states.get(lap, {}).get(driver)
    if st is None:
        return {NO_TIME}

    reasons: set[str] = set()
    if not st["lap_time"]:
        reasons.add(NO_TIME)
    if st["is_pit"]:
        reasons.add(PIT)
    if tl.is_neutralized(lap):
        reasons.add(NEUTRALIZED)
    if is_cold_tyre(tl, driver, lap):
        reasons.add(COLD)

    if check_traffic and not reasons:
        med, mad, n = stats.get(stint_key(driver, st), (None, None, 0))
        if med is not None and n >= MIN_STINT_CLEAN:
            slow = st["lap_time"] - med
            if slow >= TRAFFIC_MIN_S and (mad <= 0 or slow > TRAFFIC_MAD_K * mad):
                reasons.add(TRAFFIC)
    return reasons


def clean_pace(tl, lap: int, window: int = 5,
               stats: dict | None = None) -> dict[str, float]:
    """最近 window 圈的**干净**圈速中位数（秒）。只返回有干净圈的车手。

    与旧 recent_pace 的差别：额外剔除冷胎圈与交通受损圈。
    """
    stats = stint_stats(tl) if stats is None else stats
    out: dict[str, float] = {}
    lo = max(1, lap - window + 1)
    for d in tl.states.get(lap, {}):
        vals = []
        for k in range(lo, lap + 1):
            st = tl.states.get(k, {}).get(d)
            if st is None:
                continue
            if flag_lap(tl, d, k, stats):
                continue
            vals.append(st["lap_time"])
        if vals:
            out[d] = statistics.median(vals)
    return out


def fuel_correct(lap_time: float, lap_number: int, total_laps: int,
                 per_lap: float = FUEL_EFFECT_S_PER_LAP) -> float:
    """把某个圈速修正到「满油（第 1 圈）」口径。

    只在**跨时间比较**时使用。同圈比较两个车手时别用 —— 两人燃油相同，效应会抵消，
    强行修正反而引入偏差。
    """
    laps_to_go = max(0, lap_number - 1)
    return lap_time + per_lap * laps_to_go


def reason_summary(tl, driver: str, lap: int, stats: dict) -> str:
    r = flag_lap(tl, driver, lap, stats)
    return "干净" if not r else " + ".join(sorted(r))


def iter_laps_unique(tl) -> Iterable[tuple[int, list[str]]]:
    for lap in sorted(tl.states):
        yield lap, list(tl.states[lap])
