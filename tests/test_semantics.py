"""完赛 / 退赛语义：SQL 与 Python 两条实现必须逐字一致。

## 为什么这条测试值钱

`src/semantics.py` 自己写着被同一类 bug 咬过两次：

    - 用 status != 'Finished' 当退赛条件 → 把被套圈完赛算成退赛（多报 948 条）
    - 偏差不是常数，各年 15.9–39.0 个百分点 → 31 条赛道的结论符号整个翻转

这个模块的**全部价值**就建立在「`FINISHED_SQL` 与 `is_finished()` 语义严格一致」
之上，而 SQL 和 Python 是两份独立实现 —— 只有测试能把它们锁在一起。
所以这是本仓库的第一条基线测试。
"""

import sqlite3

import pytest

from src.semantics import DNF_SQL, FINISHED_SQL, is_dnf, is_finished

# 覆盖全库出现过的几种形态 + 几个边界
STATUSES = [
    "Finished",
    "Lapped",                     # FastF1 2023 起用它替代 '+N Lap(s)'
    "+1 Lap", "+2 Laps", "+3 Laps", "+16 Laps",
    "+1 Lap(s)",                  # 2023 之前的老写法
    "Accident", "Collision", "Engine", "Gearbox", "Retired",
    "Disqualified", "Excluded", "Did not start", "Withdrawn",
    "Underweight", "Power Unit", "Brakes", "Hydraulics", "Overheating",
    "Puncture", "Not classified",
    "",                           # 空串：既不是完赛也不是 '+…Lap'
    "SomeFutureStatus",           # 未知取值不得被当成完赛
]


def _db_with_statuses():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (driver TEXT, status TEXT)")
    db.executemany("INSERT INTO t VALUES (?,?)",
                   [(f"D{i}", s) for i, s in enumerate(STATUSES)])
    return db


def test_sql_and_python_agree_on_every_status():
    """SQL 的 FINISHED_SQL 与 Python 的 is_finished 必须选中同一批。"""
    db = _db_with_statuses()
    sql_fin = {s for (s,) in db.execute(
        f"SELECT status FROM t WHERE {FINISHED_SQL}")}
    py_fin = {s for s in STATUSES if is_finished(s)}
    assert sql_fin == py_fin, (
        f"SQL 与 Python 口径不一致\n"
        f"  只有 SQL 认为是完赛：{sql_fin - py_fin}\n"
        f"  只有 Python 认为是完赛：{py_fin - sql_fin}")


def test_dnf_sql_is_exact_complement():
    db = _db_with_statuses()
    sql_fin = {s for (s,) in db.execute(f"SELECT status FROM t WHERE {FINISHED_SQL}")}
    sql_dnf = {s for (s,) in db.execute(f"SELECT status FROM t WHERE {DNF_SQL}")}
    assert sql_fin | sql_dnf == set(STATUSES)
    assert sql_fin & sql_dnf == set()


def test_is_dnf_is_negation_of_is_finished():
    for s in STATUSES:
        assert is_dnf(s) is (not is_finished(s))


@pytest.mark.parametrize("s", ["Finished", "Lapped", "+1 Lap", "+16 Laps",
                               "+1 Lap(s)"])
def test_lapped_finishers_count_as_finished(s):
    """被套圈完赛是**完赛**，不是退赛 —— 这条错了会整体低估完赛率。"""
    assert is_finished(s)


@pytest.mark.parametrize("s", ["Accident", "Retired", "Disqualified",
                               "Did not start", "", "SomeFutureStatus"])
def test_retirements_are_not_finished(s):
    assert not is_finished(s)


def test_none_is_not_finished():
    assert is_finished(None) is False
    assert is_dnf(None) is True
