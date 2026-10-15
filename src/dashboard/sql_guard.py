"""AI 生成 SQL 的守卫 —— 独立成模块，好被测试直接覆盖（不拖进 streamlit / openai）。

## 原来那个版本的两个真问题（审查报告 E1/E2）

    cleaned = sql.strip().upper()
    if not cleaned.startswith("SELECT"): return False

1. **误拦合法查询**：`WITH x AS (...) SELECT ...`（CTE）不以 SELECT 开头 → 被拒。
   而模型写复杂查询时**很爱用 CTE**，等于把功能直接关掉。
2. **放行危险函数**：`SELECT load_extension('...')` / `SELECT writefile('/tmp/x','y')`
   里没有任何"危险关键字"，于是顺利通过。`load_extension` 可以加载任意 so/dll ——
   这是**能直接拿 shell 的口子**。

## 现在是两层

第一层 `is_safe_sql()` —— 文本守卫（便宜，挡大多数）。
第二层 `open_readonly_db()` —— **只读连接 + SQLite authorizer**。
    就算文本守卫被绕过，SQLite 层面也写不进去、也调不了危险函数。
    单靠正则去堵 SQL 是不可靠的，所以关键是第二层。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "f1_oracle.db"

# 允许出现在语句开头的关键字：普通查询与 CTE
_LEADING_OK = ("SELECT", "WITH")

# 任何位置都不许出现的 DDL/DML/管理语句
_DANGEROUS_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "TRIGGER", "GRANT",
)

# SQLite 里能读写文件系统 / 加载本地库的函数 —— 名字出现即拒
_DANGEROUS_FUNCS = (
    "load_extension", "writefile", "readfile", "fts3_tokenizer", "edit",
)


def is_safe_sql(sql: str) -> bool:
    """粗筛：只放行单条只读查询（SELECT / WITH…SELECT）。"""
    if not sql or not sql.strip():
        return False

    cleaned = re.sub(r"--.*?\n", "\n", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip().rstrip(";").strip()

    # ⚠️ 先把**字符串字面量**挖空再做关键字扫描 —— 否则
    # `WHERE status = 'DELETE me'` 这种完全合法的查询会被误拒
    # （F1 的 status 字段真的会出现这类词）。这个坑是测试抓出来的。
    body = re.sub(r"'(?:[^']|'')*'", "''", cleaned)
    upper = body.upper()

    if not upper.startswith(_LEADING_OK):
        return False

    # 多语句：挖空字面量后还出现分号，就是想在后面接第二条
    if ";" in body:
        return False

    for word in _DANGEROUS_KEYWORDS:
        if re.search(rf"\b{word}\b", upper):
            return False

    low = body.lower()
    for fn in _DANGEROUS_FUNCS:
        if fn in low:
            return False

    return True


def _authorizer(action: int, arg1, arg2, dbname, source) -> int:
    """只读白名单。SQLite 在 prepare 阶段逐个动作问一遍。

    ⚠️ 不能简单地把所有 SQLITE_FUNCTION 都拒掉 —— 那会连 count/avg 一起封掉。
    所以函数按**名字**拒（arg2 就是函数名），其余非读动作一律 DENY。
    """
    if action == sqlite3.SQLITE_FUNCTION:
        name = str(arg2 or "").lower()
        return sqlite3.SQLITE_DENY if name in _DANGEROUS_FUNCS else sqlite3.SQLITE_OK

    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_RECURSIVE,
        sqlite3.SQLITE_TRANSACTION,   # pandas / sqlite3 可能自己开个只读事务
        sqlite3.SQLITE_SAVEPOINT,
    }
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def open_readonly_db(path: Path | str | None = None) -> sqlite3.Connection:
    """打开只读连接并挂上 authorizer。写操作在 SQLite 层面就不可能成功。"""
    uri = f"file:{path or DB_PATH}?mode=ro"
    db = sqlite3.connect(uri, uri=True, check_same_thread=False)
    db.set_authorizer(_authorizer)
    return db
