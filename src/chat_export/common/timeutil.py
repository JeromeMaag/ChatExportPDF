"""Convert and format source timestamps.

This module converts raw timestamp values from supported source formats into
UNIX seconds and formatted strings. It also auto-detects the Threema timestamp
mode from database samples.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

COCOA_OFFSET = 978307200


class TimeMode:
    """Define supported raw timestamp modes."""

    UNIX_S = "unix_s"
    UNIX_MS = "unix_ms"
    COCOA_S = "cocoa_s"
    COCOA_MS = "cocoa_ms"


def _to_timestamp_seconds(val: Any, mode: str) -> Optional[float]:
    """Convert one raw timestamp value to UNIX seconds.

    Args:
        val (Any): Raw timestamp value.
        mode (str): Timestamp mode label.

    Returns:
        Optional[float]: UNIX timestamp in seconds or ``None``.
    """
    if val is None:
        return None
    try:
        x = float(val)
    except Exception:
        try:
            x = float(str(val))
        except Exception:
            return None

    if mode == TimeMode.UNIX_S:
        return x
    if mode == TimeMode.UNIX_MS:
        return x / 1000.0
    if mode == TimeMode.COCOA_S:
        return x + COCOA_OFFSET
    if mode == TimeMode.COCOA_MS:
        return (x / 1000.0) + COCOA_OFFSET
    return None


def auto_detect_time_mode(conn) -> str:
    """Detect the most plausible Threema timestamp mode.

    Args:
        conn: Open SQLite connection.

    Returns:
        str: Detected timestamp mode label.
    """
    cur = conn.cursor()
    cur.execute("SELECT ZDATE FROM ZMESSAGE WHERE ZDATE IS NOT NULL ORDER BY ZDATE DESC LIMIT 50;")
    vals = [r[0] for r in cur.fetchall()]
    if not vals:
        return TimeMode.UNIX_S

    def score(mode: str) -> int:
        s = 0
        for v in vals:
            ts = _to_timestamp_seconds(v, mode)
            if ts is None:
                continue
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if 2008 <= dt.year <= 2035:
                    s += 1
            except Exception:
                pass
        return s

    modes = [TimeMode.UNIX_S, TimeMode.UNIX_MS, TimeMode.COCOA_S, TimeMode.COCOA_MS]
    best, best_score = sorted(
        [(m, score(m)) for m in modes],
        key=lambda x: x[1],
        reverse=True,
    )[0]
    return best if best_score > 0 else TimeMode.COCOA_S


def format_dt(val: Any, mode: str, tz_name: str, null_if_early_year: int = 2005) -> str:
    """Format one raw timestamp value as render text.

    Args:
        val (Any): Raw timestamp value.
        mode (str): Timestamp mode label.
        tz_name (str): IANA timezone name.
        null_if_early_year (int): Minimum accepted year.

    Returns:
        str: Formatted timestamp string or ``NULL``.
    """
    ts = _to_timestamp_seconds(val, mode)
    if ts is None:
        return "NULL"
    try:
        tz = ZoneInfo(tz_name) if ZoneInfo is not None else timezone.utc
        dt = datetime.fromtimestamp(ts, tz=tz)
        if dt.year < null_if_early_year:
            return "NULL"
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return "NULL"


def dt_compact(val: Any, mode: str, tz_name: str) -> str:
    """Format one raw timestamp value as a compact filename-safe string.

    Args:
        val (Any): Raw timestamp value.
        mode (str): Timestamp mode label.
        tz_name (str): IANA timezone name.

    Returns:
        str: Compact timestamp string or ``NULL``.
    """
    ts = _to_timestamp_seconds(val, mode)
    if ts is None:
        return "NULL"
    tz = ZoneInfo(tz_name) if ZoneInfo is not None else timezone.utc
    dt = datetime.fromtimestamp(ts, tz=tz)
    return dt.strftime("%Y-%m-%d_%H%M%S")
