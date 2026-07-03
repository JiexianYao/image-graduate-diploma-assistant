"""
SQLite 数据层
WAL 模式支持并发读，单用户场景写入串行化足够
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

_DB_PATH: Optional[Path] = None


def set_db_path(path: Path) -> None:
    global _DB_PATH
    _DB_PATH = path
    _init()


@contextmanager
def conn():
    db = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _init() -> None:
    # 数据库初始化（已移除未使用的表定义）
    pass


# ── 通用 helpers ───────────────────────────────────────────────────────────

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def rows_to_list(rows) -> List[Dict[str, Any]]:
    return [row_to_dict(r) for r in rows]
