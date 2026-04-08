"""Configure application logging handlers and formatting.

This module exposes the shared logging setup used by the CLI entry point. It
supports console logging and optional file logging.
"""

import logging
from pathlib import Path
from typing import Optional


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Configure root logging for one process run.

    Args:
        level (str): Log level name.
        log_file (Optional[str]): Optional log file path.
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
