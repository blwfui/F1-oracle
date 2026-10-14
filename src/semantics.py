"""F1 数据语义的【唯一定义】—— 不依赖任何第三方库，可被各层复用。

这里只有一件事：把 `results` 表里那些「看起来显然、实际极易弄错」的语义
定义清楚，并且**只在一个地方定义**。dashboard / etl / model 三层都从这里引用，
不要再各自实现一遍。

历史上这个语义被复制到 10 处并各自漂移，导致过两个真实 bug：
    ① 完赛率被系统性低估 27 个百分点（各年偏差 15.9–39.0 pp）
    ② 超车分析把「退赛」当成「掉 6.8 位」，31 条赛道结论全部符号翻转
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════
# 一、results.status —— 完赛 / 退赛
# ═══════════════════════════════════════════════════════════
# 只有 "Finished" 表示【领先圈完赛】，但被套圈完赛同样是完赛：
#
#     Finished                     -> 领先圈完赛
#     Lapped                       -> 被套圈完赛（Ergast 旧写法）
#     +1 Lap / +2 Laps / +? Lap    -> 被套圈完赛（现代写法）
#
# 其余全部是退赛：Retired / Collision / Accident / Engine / Gearbox /
# Disqualified / Did not start / ...（全库共 47 个不同取值）
#
# ⚠️ 踩坑记录
#     - 只判 status='Finished' 会把完赛率从 85.1% 误压到 57.7%
#     - 用 status != 'Finished' 当退赛条件，会把被套圈完赛算成退赛（多报 948 条）
#     - 偏差不是常数：各年 15.9–39.0 个百分点，随被套圈车辆数波动，
#       所以不能靠"看起来差不多"蒙混过去
#
# 用法（SQL）：直接嵌进 CASE / WHERE
#     SUM(CASE WHEN {FINISHED_SQL} THEN 1 ELSE 0 END)   -- 完赛场次
#     WHERE {DNF_SQL}                                   -- 只看退赛
FINISHED_STATUSES = ("Finished", "Lapped")
FINISHED_SQL = "(status = 'Finished' OR status = 'Lapped' OR status LIKE '+%Lap%')"
DNF_SQL = f"NOT {FINISHED_SQL}"


def is_finished(status) -> bool:
    """Python 侧判定，语义与 FINISHED_SQL 严格一致（已对全库 54 个取值穷举验证）。"""
    s = "" if status is None else str(status)
    if s in FINISHED_STATUSES:
        return True
    return s.startswith("+") and "Lap" in s


def is_dnf(status) -> bool:
    return not is_finished(status)


# ═══════════════════════════════════════════════════════════
# 二、results.position —— 名次，永不为 NULL
# ═══════════════════════════════════════════════════════════
# 实测：3458/3458 行 position 全部非空，退赛者也都有值。
# FastF1 按行驶距离给退赛者分配「分类名次」（全历史范围 11–20，均值 18.4），
# 与完赛者同处一个 1..N 的不重复排列（173 场无一撞号）。
# 值本身是准确的（与官方成绩单一致），但语义不是「完赛名次」。
#
# ⚠️ 由此产生两个坑
#     1. `position IS NULL` 永远不成立。筛退赛只能用 status（DNF_SQL / is_dnf），
#        写 `WHERE position IS NULL` 的查询必然返回空表。
#     2. 拿退赛者的 position 算「位置变化」会得到假信号：实测退赛者平均 -6.82 位、
#        完赛者 +1.13 位。混在一起算会把「有没有超车」的结论整个反过来
#        （31 条赛道全部由正翻负）。涉及位置变化必须先按 FINISHED_SQL 过滤。
POSITION_IS_NEVER_NULL = True

__all__ = [
    "FINISHED_STATUSES", "FINISHED_SQL", "DNF_SQL",
    "is_finished", "is_dnf", "POSITION_IS_NEVER_NULL",
]
