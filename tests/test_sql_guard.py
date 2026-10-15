"""AI 生成 SQL 的守卫：真值表 + 只读连接的第二层防御。

锁的是审查报告 E1/E2 里的两个**方向相反**的缺陷：

    误拦  —— WITH x AS (...) SELECT ...（CTE）不以 SELECT 开头 → 被拒。
             而模型写复杂查询很爱用 CTE，等于把功能直接关掉。
    放行  —— SELECT load_extension('...') / writefile('/tmp/x','y')
             里没有"危险关键字"，顺利通过。load_extension 能加载任意 so/dll。
"""

import sqlite3

import pytest

from src.dashboard.sql_guard import (is_safe_sql, open_readonly_db)

# ── 必须放行 ────────────────────────────────────────────────
ALLOWED = [
    "SELECT 1",
    "select driver, team from results limit 5",
    "SELECT COUNT(*) FROM laps WHERE year = 2024",
    "SELECT * FROM results WHERE status = 'Finished'",
    "  \n  SELECT 1  \n  ",
    "SELECT 1;",                                    # 单个结尾分号，无害
    "-- 注释\nSELECT 1",
    "/* 块注释 */ SELECT 1",
    # CTE —— 旧实现就是死在这一条上
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "with recent as (select * from laps) select count(*) from recent",
    # 字符串字面量里出现危险词，不该误伤
    "SELECT * FROM results WHERE status = 'DELETE me'",
    "SELECT 'insert' AS word",
]

# ── 必须拒绝 ────────────────────────────────────────────────
DENIED = [
    "",
    "   ",
    "INSERT INTO results VALUES (1)",
    "UPDATE results SET points = 0",
    "DELETE FROM results",
    "DROP TABLE laps",
    "ALTER TABLE laps ADD COLUMN x INT",
    "CREATE TABLE x (a INT)",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA table_info(laps)",
    "VACUUM",
    # 危险函数 —— 旧实现全部放行
    "SELECT load_extension('/tmp/evil.so')",
    "SELECT writefile('/tmp/pwn', 'x')",
    "SELECT readfile('/etc/passwd')",
    # 多语句夹带
    "SELECT 1; DROP TABLE laps",
    "SELECT 1;DELETE FROM results",
    # 不以 SELECT/WITH 开头
    "EXPLAIN SELECT 1",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_readonly_queries(sql):
    assert is_safe_sql(sql), f"应放行却被拒：{sql!r}"


@pytest.mark.parametrize("sql", DENIED)
def test_rejects_writes_and_dangerous_funcs(sql):
    assert not is_safe_sql(sql), f"应拒绝却被放行：{sql!r}"


# ── 第二层：只读连接 + authorizer ────────────────────────────

def _seed_db(path):
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE t (a INT)")
    db.execute("INSERT INTO t VALUES (1), (2)")
    db.commit()
    db.close()


def test_readonly_connection_allows_select(tmp_path):
    p = tmp_path / "x.db"
    _seed_db(p)
    db = open_readonly_db(p)
    assert db.execute("SELECT SUM(a) FROM t").fetchone()[0] == 3
    db.close()


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (3)",
    "UPDATE t SET a = 0",
    "DELETE FROM t",
    "DROP TABLE t",
    "CREATE TABLE u (b INT)",
])
def test_readonly_connection_blocks_writes(tmp_path, sql):
    """即使文本守卫被绕过（这里直接调用连接），写操作也必须失败。"""
    p = tmp_path / "x.db"
    _seed_db(p)
    db = open_readonly_db(p)
    with pytest.raises(sqlite3.Error):
        db.execute(sql)
    db.close()


def test_readonly_connection_blocks_load_extension(tmp_path):
    """load_extension 在只读连接上必须报错（第一层之外的第二层）。"""
    p = tmp_path / "x.db"
    _seed_db(p)
    db = open_readonly_db(p)
    with pytest.raises(sqlite3.Error):
        db.execute("SELECT load_extension('/tmp/anything.so')")
    db.close()


def test_readonly_connection_still_allows_cte(tmp_path):
    p = tmp_path / "x.db"
    _seed_db(p)
    db = open_readonly_db(p)
    assert db.execute("WITH c AS (SELECT a FROM t) SELECT COUNT(*) FROM c"
                      ).fetchone()[0] == 2
    db.close()
