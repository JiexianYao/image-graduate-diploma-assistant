"""
SQLite 数据层
WAL 模式支持并发读，单用户场景写入串行化足够
"""
import json
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
    with conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS semesters (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS courses (
                id          TEXT PRIMARY KEY,
                semester_id TEXT,
                name        TEXT NOT NULL,
                credits     REAL DEFAULT 3,
                color       TEXT DEFAULT 'color-blue',
                notes       TEXT DEFAULT '',
                deadline    TEXT DEFAULT '',
                assignments TEXT DEFAULT '[]'   -- JSON 数组
            );

            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                name        TEXT,
                category    TEXT DEFAULT 'other',
                semester_id TEXT DEFAULT '',
                date        TEXT,
                size        INTEGER DEFAULT 0,
                path        TEXT,
                doc_type    TEXT DEFAULT 'longterm'
            );

            CREATE TABLE IF NOT EXISTS exam_materials (
                id             TEXT PRIMARY KEY,
                name           TEXT,
                mtype          TEXT DEFAULT 'other',
                course_id      TEXT DEFAULT '',
                semester_id    TEXT DEFAULT '',
                date           TEXT,
                size           INTEGER DEFAULT 0,
                path           TEXT,
                ai_summary     TEXT DEFAULT '',
                extracted_text TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS admin_items (
                id        TEXT PRIMARY KEY,
                item_type TEXT DEFAULT 'link',
                name      TEXT,
                category  TEXT DEFAULT 'other',
                url       TEXT DEFAULT '',
                notes     TEXT DEFAULT '',
                date      TEXT,
                size      INTEGER DEFAULT 0,
                path      TEXT DEFAULT ''
            );
        """)


# ── 通用 helpers ───────────────────────────────────────────────────────────

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    # 反序列化 JSON 字段
    for key in ("assignments",):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (ValueError, TypeError):
                d[key] = []
    return d


def rows_to_list(rows) -> List[Dict[str, Any]]:
    return [row_to_dict(r) for r in rows]
