"""H4 留出集脚本的回归测试。

这一批测试**不碰数据库、不联网**，只钉住三类容易悄悄变形的东西：

1. **预注册判据本身。** `KILL` 是"写在看到结果之前"的判据；如果有人事后把它
   从 `t > 2` 放松成 `t > 1`，留出验证就变成了走过场。这里把数值钉死 ——
   要改判据就必须显式改测试，改不动就是好事。
2. **单纯形网格。** 权重网格漏掉某个组合或者权重和不为 1，选出来的"最优权重"
   就是假的。
3. **`paired_delta` 的年份裁剪。** 它必须只对被点名的那几年算差 —— 一旦漏裁，
   留出年就会混进训练年，留出集验证整个失效。
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import holdout_eval as H  # noqa: E402


# ── 1. 预注册判据不许被悄悄放松 ─────────────────────────────
def test_kill_criteria_are_preregistered_values():
    assert H.KILL == {"min_delta": 0.0, "min_t": 2.0, "min_pos_year_frac": 0.5}


def test_verdict_rejects_boundary_t():
    """t 恰好等于 2.0 **不算**通过（判据是严格大于）—— 这就是主切分赛后那一条。

    竞速项目里没有"踩线算过"这回事：判据写的是 >2，t=1.998 就是没过。
    留下这条测试是为了让这个判断保持可追溯。
    """
    r = {"delta": 0.01, "t": 1.998, "n": 70, "pos": 3,
         "years": {2023: 1.0, 2024: 1.0, 2025: 1.0}}
    ok = (r["delta"] > H.KILL["min_delta"] and r["t"] > H.KILL["min_t"]
          and r["pos"] >= H.KILL["min_pos_year_frac"] * len(r["years"]))
    assert ok is False

    r["t"] = 2.001
    ok = (r["delta"] > H.KILL["min_delta"] and r["t"] > H.KILL["min_t"]
          and r["pos"] >= H.KILL["min_pos_year_frac"] * len(r["years"]))
    assert ok is True


def test_verdict_needs_majority_of_positive_years():
    """平均 Δρ 为正、t 也够大，但只在 1 年里赚钱 → 不算稳。"""
    bad = {"delta": 0.05, "t": 5.0, "n": 100, "pos": 1,
           "years": {y: 0.0 for y in range(2018, 2026)}}
    assert bad["pos"] < H.KILL["min_pos_year_frac"] * len(bad["years"])


# ── 2. 单纯形网格 ───────────────────────────────────────────
def test_simplex_is_a_complete_weight_grid():
    pts = list(H.simplex(0.2))
    assert len(pts) == 21                       # C(5+2,2)
    assert len(set(pts)) == 21                  # 无重复
    for w in pts:
        assert abs(sum(w) - 1.0) < 1e-9
        assert all(0.0 <= x <= 1.0 for x in w)
    assert (1.0, 0.0, 0.0) in pts and (0.0, 0.0, 1.0) in pts


def test_config_count_matches_the_documented_tuning_surface():
    """每折 75 组 = 18（Elo）+ 15（罚退收缩）+ 21 + 21。

    这个数字被写进 `docs/留出集验证.md` 与审查报告，所以改动网格必须同步改这里 ——
    它是一条 change-detector，故意不是恒等式。
    """
    surface = (len(H.K_GRID) * len(H.POLICIES)
               + len(H.ALPHAS) * len(H.MIN_PENS)
               + 2 * len(list(H.simplex(H.W_STEP))))
    assert H.N_CONFIGS == surface == 75


def test_min_pen_grid_extends_past_the_value_that_matters():
    """min_pen 网格必须越过 =10。

    初版网格 (3,5,10) 里 min_pen=10 **每一折都命中上边界** —— 边界命中说明
    网格卡住了调参器，不能拿"选了 10"当结论。扩到 20 才能判断这是真选点还是
    只是一条扁平的边界。留下这条测试防止有人把网格改窄回去。
    """
    assert max(H.MIN_PENS) >= 20
    assert H.MIN_PENS == tuple(sorted(H.MIN_PENS))
    assert 3 in H.MIN_PENS          # 项目既有的 min_pen=3 要在待选集合里


# ── 3. paired_delta 的年份裁剪 ──────────────────────────────
def _frame(rows):
    return pd.DataFrame(rows, columns=["key", "year", "rho_all"])


def test_paired_delta_only_uses_the_named_years():
    a = _frame([("2023|1", 2023, 0.50), ("2024|1", 2024, 0.50),
                ("2022|1", 2022, 0.90)])          # 2022 是训练年，必须被裁掉
    b = _frame([("2023|1", 2023, 0.55), ("2024|1", 2024, 0.45),
                ("2022|1", 2022, 0.10)])          # 若不裁剪，2022 会把结果拖垮
    r = H.paired_delta(a, b, (2023, 2024))
    assert r["n"] == 2
    assert r["delta"] == pytest.approx(0.0)       # (+0.05 − 0.05) / 2
    assert set(r["years"]) == {2023, 2024}


def test_paired_delta_sign_and_t_direction():
    a = _frame([(f"k{i}", 2023, 0.50) for i in range(5)])
    b = _frame([(f"k{i}", 2023, 0.50 + 0.01 * (i + 1)) for i in range(5)])
    r = H.paired_delta(a, b, (2023,))
    assert r["delta"] == pytest.approx(0.03)
    assert r["t"] > 0
    assert r["pos"] == 1


def test_paired_delta_merges_on_key_not_row_order():
    """两边行序不同但 key 相同时，差值必须按 key 对齐。"""
    a = _frame([("x", 2023, 0.10), ("y", 2023, 0.90)])
    b = _frame([("y", 2023, 0.95), ("x", 2023, 0.15)])
    r = H.paired_delta(a, b, (2023,))
    assert r["delta"] == pytest.approx(0.05)


def test_paired_delta_survives_too_few_rows():
    a = _frame([("x", 2023, 0.10)])
    b = _frame([("x", 2023, 0.90)])
    r = H.paired_delta(a, b, (2023,))
    assert r["n"] == 1
    assert r["delta"] != r["delta"]               # nan，不是崩溃


# ── 4. Board 缓存与年份裁剪 ─────────────────────────────────
def test_board_caches_by_tag_and_never_reruns(monkeypatch):
    calls = []

    def fake_run(races, factory, *, context):
        calls.append(context)
        return _frame([("k", 2023, 0.5)])

    monkeypatch.setattr(H, "run_backtest", fake_run)
    board = H.Board([object()], "pre_quali")
    board.df("same", lambda: None)
    board.df("same", lambda: None)
    assert calls == ["pre_quali"]                 # 第二次命中缓存
    assert board.n_evals == 1

    board.df("other", lambda: None)
    assert len(calls) == 2
    assert board.n_evals == 2


def test_board_mean_rho_filters_years(monkeypatch):
    def fake_run(races, factory, *, context):
        return _frame([("a", 2022, 0.10), ("b", 2023, 0.60), ("c", 2023, 0.80)])

    monkeypatch.setattr(H, "run_backtest", fake_run)
    board = H.Board([object()], "pre_quali")
    assert board.mean_rho("t", lambda: None, (2023,)) == pytest.approx(0.70)
    assert board.mean_rho("t", lambda: None, (2022,)) == pytest.approx(0.10)
    nan = board.mean_rho("t", lambda: None, (1999,))
    assert nan != nan                              # 空年份返回 nan 而不是 0


# ── 5. 显示宽度补齐 ─────────────────────────────────────────
def test_pad_counts_cjk_as_two_columns():
    assert H._pad("abc", 6) == "abc   "
    assert H._pad("中文", 6) == "中文  "            # 2 个字 = 4 列
    assert H._pad("很长很长很长的中文标签", 6).endswith(" ")  # 超宽也留一个空格


# ── 6. 对照口径必须与 README 逐字一致 ───────────────────────
def test_comparators_match_readme_same_complexity_weights():
    """留出验证的对照就是 README 的「同复杂度」口径；权重漂了就不可比。"""
    pre = H.cmp_pre()
    post = H.cmp_post()
    assert [w for _, w in pre.parts] == [0.5, 0.5]
    assert [w for _, w in post.parts] == [0.3, 0.7]


def test_headline_years_exclude_2026():
    """2026 是「当下赛季」，既不进训练也不进测试 —— 否则等于拿未来调参。"""
    assert 2026 not in H.HEADLINE_YEARS
    assert H.HEADLINE_YEARS == tuple(range(2018, 2026))
