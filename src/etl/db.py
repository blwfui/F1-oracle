"""SQLite 连接的唯一入口。

## 为什么需要

`src/etl/ingest.py` 会开 WAL，但 `fetch_official.py` / `build_sprint.py` /
`import_sessions.py` 各自裸 `sqlite3.connect(...)` —— 一旦有两个进程同时写，
就会 `database is locked`，而且**默认只等 0 秒**（busy_timeout=0），
撞上就直接抛异常。这类失败在批处理里经常被 except 吞掉，表现为"数据莫名少了几轮"。

统一走这里：WAL + 10 秒 busy_timeout。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

# 并发写时最多等多久（毫秒）再报 locked。批处理里 0 秒太脆。
BUSY_TIMEOUT_MS = 10_000


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(str(path or DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return db
