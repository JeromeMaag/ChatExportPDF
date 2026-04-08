"""Open read-only SQLite connections for the Threema importer."""

import sqlite3


def connect_db(db_path: str) -> sqlite3.Connection:
    """Open a read-only SQLite connection with row access by column name.

    Args:
        db_path (str): SQLite database file path.

    Returns:
        sqlite3.Connection: Open read-only connection with ``sqlite3.Row``
        row factory.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
