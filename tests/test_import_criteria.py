"""入库完整性判据 —— 都踩过坑，锁住别再退回去。

覆盖审查报告 M2 查出的三处：

    · 完整性判据用写死的 MIN_RESULTS = 18
      → 2024 R3、2025 R9 各只有 19 人（其余轮 20）却被判「已完整」而跳过。
    · backfill 待办只看「有 NULL 行」
      → 2018 R14 在 laps 里一行都没有，永远进不了队列；
        另有几场各 1 行 NULL，每次运行都重抓整场、永不收敛。
"""

import sqlite3

import pytest

from scripts.backfill_lap_times import pending_races
from scripts.import_season import coverage, expected_entrants, is_done

SCHEMA = """
CREATE TABLE results (year INT, round INT, driver TEXT, q1_sec REAL);
CREATE TABLE sessions (year INT, round INT, session_type TEXT);
CREATE TABLE laps (year INT, round INT, driver TEXT, lap_time REAL, time_sec REAL);
"""


@pytest.fixture()
def db():
    d = sqlite3.connect(":memory:")
    d.executescript(SCHEMA)
    return d


def _add_round(d, year, rnd, n_drivers, *, laps=200, null_laps=0, quali=True,
               fp=True):
    for i in range(n_drivers):
        d.execute("INSERT INTO results VALUES (?,?,?,?)",
                  (year, rnd, f"D{i}", 80.0 if quali and i < n_drivers else None))
    if fp:
        for st in ("FP1", "FP2", "FP3"):
            d.execute("INSERT INTO sessions VALUES (?,?,?)", (year, rnd, st))
    for i in range(laps):
        d.execute("INSERT INTO laps VALUES (?,?,?,?,?)",
                  (year, rnd, f"D{i % n_drivers}", 80.0,
                   None if i < null_laps else 80.0))
    d.commit()


# ── expected_entrants / is_done ──────────────────────────────

def test_expected_entrants_is_the_season_max(db):
    _add_round(db, 2024, 1, 20)
    _add_round(db, 2024, 2, 20)
    _add_round(db, 2024, 3, 19)
    assert expected_entrants(db, 2024) == 20


def test_short_round_is_flagged_incomplete(db):
    """2024 R3 那个形状：19 人，其余轮 20 人 → 必须判不足。"""
    _add_round(db, 2024, 1, 20)
    _add_round(db, 2024, 2, 20)
    _add_round(db, 2024, 3, 19)
    expect = expected_entrants(db, 2024)
    assert is_done(coverage(db, 2024, 1), expect) is True
    assert is_done(coverage(db, 2024, 3), expect) is False, \
        "19 人的轮次被判成完整了 —— 旧 MIN_RESULTS=18 就是这个毛病"


def test_2026_style_22_car_field(db):
    _add_round(db, 2026, 1, 22)
    _add_round(db, 2026, 2, 22)
    assert expected_entrants(db, 2026) == 22
    assert is_done(coverage(db, 2026, 1), expected_entrants(db, 2026)) is True


def test_missing_laps_is_incomplete(db):
    _add_round(db, 2024, 1, 20, laps=0)
    _add_round(db, 2024, 2, 20)
    assert is_done(coverage(db, 2024, 1), 20) is False


def test_fallback_when_no_expected_given(db):
    """拿不到赛季规模时退回兜底阈值（不炸、也不误判）。"""
    _add_round(db, 2024, 1, 20)
    assert is_done(coverage(db, 2024, 1), 0) is True


# ── pending_races ────────────────────────────────────────────

def test_round_with_zero_lap_rows_is_queued(db):
    """2018 R14 的形状：results 有、laps 一行都没有 → 必须入队。

    旧判据（只看 `time_sec IS NULL`）会漏掉它，于是永远补不上。
    """
    _add_round(db, 2018, 14, 20, laps=0)
    assert (2018, 14) in pending_races(db, None)


def test_single_null_row_does_not_requeue(db):
    """只有 1 行 NULL 的轮次不该反复重抓（旧判据会永不收敛）。"""
    _add_round(db, 2019, 1, 20, laps=200, null_laps=1)
    assert (2019, 1) not in pending_races(db, None)


def test_mostly_null_is_queued(db):
    _add_round(db, 2019, 2, 20, laps=200, null_laps=150)   # 75% NULL
    assert (2019, 2) in pending_races(db, None)


def test_year_filter(db):
    _add_round(db, 2018, 14, 20, laps=0)
    _add_round(db, 2019, 3, 20, laps=0)
    assert pending_races(db, 2019) == [(2019, 3)]
    assert set(pending_races(db, None)) == {(2018, 14), (2019, 3)}


def test_healthy_db_has_no_pending_work(db):
    _add_round(db, 2024, 1, 20)
    _add_round(db, 2024, 2, 20)
    assert pending_races(db, None) == []
