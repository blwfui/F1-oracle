"""车队身份：历史队名必须收敛到物理车队。

锁的是「队名没做别名归并」那个 bug：`results.team` 存的是**当时的队名**，
2018–2026 共 19 个名字 = 11 支车队。不归并时 `elo.team` 会攒出 19 条，
前十里挂着 Racing Point / Renault / Sauber / Force India 四个一辆车都没在跑的名字。
"""

from src.model.teams import (CANONICAL_TEAMS, TEAM_ALIAS, canonical_team,
                             lineage)

# 2018–2026 实际出现过的全部队名（从 results.team 取 DISTINCT 得到）
ALL_NAMES_SEEN = {
    "Ferrari", "Force India", "Haas F1 Team", "Kick Sauber", "McLaren",
    "Mercedes", "Racing Point", "Red Bull Racing", "Renault", "Sauber",
    "Toro Rosso", "Williams", "Alfa Romeo", "AlphaTauri", "Alpine",
    "Aston Martin", "Racing Bulls", "Audi", "Cadillac",
}


def test_all_seen_names_collapse_to_the_eleven_teams():
    collapsed = {canonical_team(n) for n in ALL_NAMES_SEEN}
    assert collapsed == set(CANONICAL_TEAMS)
    assert len(ALL_NAMES_SEEN) == 19 and len(CANONICAL_TEAMS) == 11


def test_alias_targets_are_known_canonical_names():
    """归并目标必须是规范队名 —— 否则等于归并到一个已不存在的车队。"""
    assert set(TEAM_ALIAS.values()) <= set(CANONICAL_TEAMS)


def test_no_alias_chain():
    """别名不许指向另一个别名（只允许一跳到底）。"""
    for old, new in TEAM_ALIAS.items():
        assert new not in TEAM_ALIAS, f"{old} → {new} 是二级跳"


def test_canonical_team_is_idempotent():
    for n in ALL_NAMES_SEEN:
        assert canonical_team(canonical_team(n)) == canonical_team(n)


def test_unknown_name_passes_through():
    assert canonical_team("Some New Team") == "Some New Team"


def test_lineage():
    assert set(lineage("Aston Martin")) == {"Force India", "Racing Point"}
    assert set(lineage("Audi")) == {"Sauber", "Alfa Romeo", "Kick Sauber"}
    assert set(lineage("Racing Bulls")) == {"Toro Rosso", "AlphaTauri"}
    assert lineage("Alpine") == ("Renault",)
    # 没改过名的车队没有血缘
    assert lineage("Williams") == ()
    assert lineage("Cadillac") == ()
