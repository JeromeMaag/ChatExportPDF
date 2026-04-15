"""Configure application logging handlers and formatting.

This module exposes the shared logging setup used by application entry points.
It supports console logging, optional file logging, optional extra handlers,
and full handler replacement for repeated setup calls.
"""

import logging
from pathlib import Path
from typing import Iterable, Optional

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    *,
    console: bool = True,
    extra_handlers: Optional[Iterable[logging.Handler]] = None,
    replace_existing: bool = True,
) -> None:
    """Configure root logging for one process run.

    Args:
        level (str): Log level name.
        log_file (Optional[str]): Optional log file path.
        console (bool): Add a console stream handler.
        extra_handlers (Optional[Iterable[logging.Handler]]): Extra configured
            handlers to attach.
        replace_existing (bool): Remove existing root handlers before setup.
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    if replace_existing:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    managed_handlers: list[logging.Handler] = []
    if console:
        managed_handlers.append(logging.StreamHandler())
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        managed_handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in managed_handlers:
        handler.setLevel(lvl)
        handler.setFormatter(formatter)

    root_logger.setLevel(lvl)
    for handler in managed_handlers:
        root_logger.addHandler(handler)
    if extra_handlers:
        for handler in extra_handlers:
            root_logger.addHandler(handler)
