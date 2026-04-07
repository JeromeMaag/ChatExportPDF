import sqlite3
from typing import Any, Set


def row_get(row: sqlite3.Row, col: str) -> Any:
    return row[col] if col in row.keys() else None


def table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    return {r[1] for r in cur.fetchall()}
