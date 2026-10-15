"""回测框架的结构性保证 —— 这几条不过，README 上所有结论都不可信。

审查报告 §3 把「赛周内会话泄漏」「entries 顺序泄漏」「第 1 站虚高」等怀疑逐一
实测排除，并指出：这些目前靠"没人写错"侥幸成立，而全仓零测试。
这里把它们固化成回归测试。
"""

import pytest

from src.model.backtest import (Entry, Race, Truth, make_context, run_backtest,
                                score_round, spearman)
from src.model.predictors import EloPredictor, GridBaseline, QualiGapBaseline


def _race(year: int = 2024) -> Race:
    entries = [
        Entry("A", "A A", "Team1", grid=1),
        Entry("B", "B B", "Team1", grid=2),
        Entry("C", "C C", "Team2", grid=3),
        Entry("D", "D D", "Team2", grid=4),
    ]
    truth = {
        "A": Truth(1, "Finished", 25, True),
        "B": Truth(2, "Finished", 18, True),
        "C": Truth(3, "Lapped", 15, True),
        "D": Truth(4, "Engine", 0, False),      # 退赛，但有分类名次
    }
    return Race(year, 1, "Test GP", "Test", "Test", entries, truth, {},
                fp={"FP1": {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}},
                quali_gap={"A": 0.0, "B": 0.1, "C": 0.2, "D": 0.3},
                quali_pos={"A": 1, "B": 2, "C": 3, "D": 4})


# ── 防泄漏：pre_quali 必须看不到发车格与排位信息 ─────────────

def test_pre_quali_strips_grid_and_quali():
    ctx = make_context(_race(), "pre_quali")
    assert all(e.grid is None for e in ctx.entries), "pre_quali 还看得见发车格"
    assert not ctx.quali_gap, "pre_quali 还看得见排位秒差"
    assert not ctx.quali_pos, "pre_quali 还看得见排位名次"


def test_post_quali_exposes_grid_and_quali():
    ctx = make_context(_race(), "post_quali")
    assert [e.grid for e in ctx.entries] == [1, 2, 3, 4]
    assert ctx.quali_gap and ctx.quali_pos


def test_qualigap_baseline_degrades_to_alphabetical_before_quali():
    """拿不到秒差时必须退化成"按车手名排序"，而不是偷偷用上真值。"""
    ctx = make_context(_race(), "pre_quali")
    assert QualiGapBaseline().predict(ctx) == sorted(ctx.drivers)


def test_fp_is_kept_before_quali():
    """练习赛早于排位赛，属合法信号，不该被剥掉。"""
    assert make_context(_race(), "pre_quali").fp


# ── 打分口径 ─────────────────────────────────────────────────

def test_spearman_extremes():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_needs_at_least_three_points():
    assert spearman([1, 2], [1, 2]) != spearman([1, 2], [1, 2])   # NaN


def test_score_round_counts_dnf_in_rho_all_but_not_rho_fin():
    s = score_round(["A", "B", "C", "D"], _race())
    assert s["rho_all"] == pytest.approx(1.0)
    assert s["n"] == 4 and s["n_fin"] == 3
    assert s["top1"] == 1.0 and s["winner_rank"] == 1


def test_ranks_put_omitted_drivers_last():
    """预测里漏掉的车手一律排在最后 —— 不能因为"没提到"就白拿好名次。"""
    s = score_round(["A"], _race())
    assert s["winner_rank"] == 1
    assert s["n"] == 4


# ── 工厂隔离：有状态预测器不得跨次泄漏 ────────────────────────

def test_predictor_state_does_not_leak_between_runs():
    races = [_race(2023), _race(2024)]
    a = run_backtest(races, lambda: EloPredictor(use_team=True), context="pre_quali")
    b = run_backtest(races, lambda: EloPredictor(use_team=True), context="pre_quali")
    assert a.equals(b), "同一工厂跑两遍结果不同 —— 预测器状态泄漏了"


def test_grid_baseline_is_useless_before_quali():
    """pre_quali 下拿不到发车格 → 只能退化成按车手名排序。"""
    ctx = make_context(_race(), "pre_quali")
    assert GridBaseline().predict(ctx) == sorted(ctx.drivers)
