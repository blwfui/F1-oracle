"""积分规则：(year) → 规则。这是全仓唯一一处定义「一分是多少」的地方。

## 为什么单独成模块

史上只有一条规则变过 —— **最快圈 +1 分**（要求本人进前 10）：2019 年启用，
**2024 年是最后一年**，2025 年起废止。

`ingest.py` 早期版本**无条件**加这一分（没有年份分支），而
`scripts/fetch_official.py` 又会用官方 `points` 覆盖 `results.points` ——
所以这个错误被官方对账**掩盖了七年**：2019–2024 本来就有这一分，看不出；
2025 被覆盖，也看不出。直到第 9 季（2026）才暴露，因为该脚本默认
`YEAR = 2025`，**从未对 2026 执行过**。

实测（每轮正赛积分合计）：
    2018 21/21 = 101  （该年本就无此分）
    2019 19/21 = 102  （**正确**，该年有这一分）
    2024 19/24 = 102  （**正确**）
    2025  0/24 ≠ 期望  （被官方覆盖掩盖，实际是对的）
    2026 16/17 = 102  ← **错误**，赛季总分虚高 16 分（1733 → 对账后 1717）

⚠️ 所以"每轮合计 = 101"这个判据**本身是错的** —— 2019–2024 就该是 102。
   要判异常请用 `expected_round_points(year)`。

## 口径

**官方值为准，缺失才回退公式**：`fetch_official.py` 覆盖 `results.points` 之后，
本模块只在「没有官方值」时才需要发力。两条路都必须拿到同一个答案。
"""

from __future__ import annotations

# 正赛名次 → 积分（2010 年起未变）
RACE_POINTS: dict[int, float] = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1,
}

# 最快圈 +1 分的生效区间（含两端）。2019 启用、2024 年后废止。
FASTEST_LAP_FROM, FASTEST_LAP_TO = 2019, 2024

# 拿这 1 分的前提：本人必须在前 10 名完赛
FASTEST_LAP_MAX_POS = 10


def fastest_lap_point_applies(year: int) -> bool:
    """该赛季是否给最快圈 +1 分。"""
    return FASTEST_LAP_FROM <= year <= FASTEST_LAP_TO


def expected_round_points(year: int) -> float:
    """一场正赛的积分合计应为多少 —— 自检判异常用。

    前 10 名给满 = 101；该年若还有最快圈分，则最快圈得主又多 1 分 = 102。
    直接用「是否等于 101」判异常会误报 2019–2024（那几年本来就该是 102）。
    """
    return 101.0 + (1.0 if FASTEST_LAP_FROM <= year <= FASTEST_LAP_TO else 0.0)


def race_points(position: int | None, *, year: int,
                is_fastest_lap: bool = False) -> float:
    """完赛名次 → 积分。

    position 为 None（退赛无分类名次）时得 0 分。
    is_fastest_lap 只在该年规则生效、且名次在前 10 时才会真的加分。
    """
    pts = float(RACE_POINTS.get(position, 0)) if position else 0.0
    if (is_fastest_lap and fastest_lap_point_applies(year)
            and position and position <= FASTEST_LAP_MAX_POS):
        pts += 1.0
    return pts


def _selfcheck() -> None:
    # 2018 无此分；2019–2024 有；2025 起废止
    assert not fastest_lap_point_applies(2018)
    assert fastest_lap_point_applies(2019)
    assert fastest_lap_point_applies(2024)
    assert not fastest_lap_point_applies(2025)
    assert not fastest_lap_point_applies(2026)
    # 前 10 之外不给
    assert race_points(11, year=2020, is_fastest_lap=True) == 0
    assert race_points(6, year=2024, is_fastest_lap=True) == 9
    assert race_points(6, year=2026, is_fastest_lap=True) == 8
    assert race_points(None, year=2020, is_fastest_lap=True) == 0
    # 每轮合计的期望值：2019–2024 = 102，其余 = 101
    assert expected_round_points(2018) == 101
    assert expected_round_points(2024) == 102
    assert expected_round_points(2026) == 101


_selfcheck()
