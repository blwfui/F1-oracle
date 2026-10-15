"""车队身份：把「同一支车队的历史名字」收敛成一个名字。

## 为什么需要

`results.team` 存的是**当时的队名**（FastF1 原样透传）。2018–2026 一共出现过
19 个名字，但物理上只有 11 支车队 —— 另外 8 个都是改名或接手：

    Force India ─→ Racing Point ─→ Aston Martin     （银石同一支队）
    Renault ───────────────────→ Alpine            （恩斯通）
    Toro Rosso ─→ AlphaTauri ───→ Racing Bulls      （法恩扎）
    Sauber ─→ Alfa Romeo ─→ Kick Sauber ─→ Audi     （欣维尔）

车队评分**必须按物理车队累计**。不归并的后果是：每改一次名就等于新开一支车队、
从 base 重新学，历史被一笔勾销 —— 实测 `elo.team` 会攒出 19 条，前十名里挂着
Racing Point 1668.2、Renault 1548.7、Sauber 1483.7、Force India 1462.4
四个已经一辆车都没在跑的名字；同时 Audi（2026 才改名）只有 1453.2，
因为它只学到了 2026 这一年。

## ⚠️ 展示层不要用这里的名字

图上仍应显示**当时的队名** —— 2020 年那台车是 Racing Point，不是 Aston Martin。
本模块只服务于「按实体累计 / 查询」这类场景（车队评分、跨年对比）。
仪表板的展示名在 `src/dashboard/common.py` 的 `TEAM_CN`，那是另一件事。

## 边界

Cadillac 是 2026 年新加入的第 11 支车队，没有前身，不参与归并。
"""

from __future__ import annotations

# 历史队名 → 现在的名字（2026 发车名单口径）
TEAM_ALIAS: dict[str, str] = {
    "Force India": "Aston Martin",
    "Racing Point": "Aston Martin",
    "Renault": "Alpine",
    "Toro Rosso": "Racing Bulls",
    "AlphaTauri": "Racing Bulls",
    "Sauber": "Audi",
    "Alfa Romeo": "Audi",
    "Kick Sauber": "Audi",
}

# 归并后的全集 = 2026 发车名单上的 11 支车队
CANONICAL_TEAMS: tuple[str, ...] = (
    "Mercedes", "Ferrari", "Red Bull Racing", "McLaren", "Williams",
    "Haas F1 Team", "Aston Martin", "Alpine", "Racing Bulls", "Audi", "Cadillac",
)

# 归并目标必须都落在全集里，否则车队评分会出现「归并到一个已不存在的名字」
assert set(TEAM_ALIAS.values()) <= set(CANONICAL_TEAMS), "TEAM_ALIAS 的目标必须是规范队名"


def canonical_team(name: str) -> str:
    """把历史队名收敛到现在的名字；未改名或未知的队名原样返回。"""
    return TEAM_ALIAS.get(name, name)


def lineage(name: str) -> tuple[str, ...]:
    """某个规范队名继承过的历史名字（不含自身）。用于展示时说明血缘。"""
    return tuple(n for n, c in TEAM_ALIAS.items() if c == name)
