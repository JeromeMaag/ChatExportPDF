"""Provide small SQLite schema inspection helpers for Threema imports."""

import sqlite3
from typing import Any, Set


def row_get(row: sqlite3.Row, col: str) -> Any:
    """Read a column value from a row if the column exists.

    Args:
        row (sqlite3.Row): SQLite row.
        col (str): Column name.

    Returns:
        Any: Column value or ``None`` if the column is absent.
    """
    return row[col] if col in row.keys() else None


def table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    """Load the column names of a SQLite table.

    Args:
        conn (sqlite3.Connection): Open SQLite connection.
        table (str): Table name.

    Returns:
        Set[str]: Column name set.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    return {r[1] for r in cur.fetchall()}
