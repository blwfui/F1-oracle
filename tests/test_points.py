"""积分规则：最快圈 +1 分只在 2019–2024 有效。

这条测试锁的是审查报告 H1 —— 一个**被官方对账掩盖了七年**的 bug：
`ingest.py` 无条件给最快圈 +1 分，而 `fetch_official.py` 又会用官方 points 覆盖，
于是直到 2026 才暴露（每轮积分合计 102 而不是 101）。

顺带锁住一处判据陷阱：**「每轮合计 = 101」本身是错的** —— 2019–2024 就该是 102。
"""

import pytest

from src.etl.points import (FASTEST_LAP_FROM, FASTEST_LAP_TO, RACE_POINTS,
                            expected_round_points, fastest_lap_point_applies,
                            race_points)


@pytest.mark.parametrize("year,expected", [
    (2018, False),           # 该规则 2019 才启用
    (2019, True), (2020, True), (2021, True), (2022, True),
    (2023, True), (2024, True),
    (2025, False), (2026, False),   # 2025 起废止
])
def test_fastest_lap_rule_by_year(year, expected):
    assert fastest_lap_point_applies(year) is expected


def test_window_matches_constants():
    assert FASTEST_LAP_FROM == 2019 and FASTEST_LAP_TO == 2024


def test_race_points_basic():
    assert race_points(1, year=2026) == 25
    assert race_points(10, year=2026) == 1
    assert race_points(11, year=2026) == 0
    assert race_points(None, year=2026) == 0       # 退赛无分类名次 → 0 分


def test_fastest_lap_bonus_only_in_window_and_top10():
    # 2019–2024：前 10 名的最快圈得主 +1
    assert race_points(6, year=2024, is_fastest_lap=True) == 9
    assert race_points(1, year=2019, is_fastest_lap=True) == 26
    # 2025+：不再加分
    assert race_points(6, year=2025, is_fastest_lap=True) == 8
    assert race_points(6, year=2026, is_fastest_lap=True) == 8
    # 2018：该年也没有这一分
    assert race_points(6, year=2018, is_fastest_lap=True) == 8
    # 前 10 之外不给
    assert race_points(11, year=2020, is_fastest_lap=True) == 0
    assert race_points(None, year=2020, is_fastest_lap=True) == 0


def test_expected_round_points_is_not_always_101():
    """判据陷阱：2019–2024 的每轮合计**应当**是 102。"""
    assert expected_round_points(2018) == 101
    assert expected_round_points(2019) == 102
    assert expected_round_points(2024) == 102
    assert expected_round_points(2025) == 101
    assert expected_round_points(2026) == 101


def test_full_top10_sums_to_expected():
    """前 10 名给满 → 该年期望值（2024 有最快圈分，则再加 1）。"""
    base = sum(RACE_POINTS[i] for i in range(1, 11))
    assert base == 101
    assert expected_round_points(2024) == base + 1
    assert expected_round_points(2026) == base
