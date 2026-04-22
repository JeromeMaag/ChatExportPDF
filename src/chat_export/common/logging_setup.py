"""Configure shared application logging."""

import logging
import re
from pathlib import Path
from typing import Iterable, Optional

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
WINDOWS_LOCAL_PATH_IN_QUOTES_RE = re.compile(
    r'(?<=")(?:[A-Za-z]:\\[^"\r\n]*|\\\\[^"\r\n]*)'
)
WINDOWS_LOCAL_PATH_AFTER_EQUALS_RE = re.compile(
    r'(?<==)(?:[A-Za-z]:\\[^"\r\n,)]*|\\\\[^"\r\n,)]*)'
)
WINDOWS_LOCAL_PATH_RE = re.compile(
    r'(?:[A-Za-z]:\\[^"\s\r\n,)]*|\\\\[^"\s\r\n,)]*)'
)


def sanitize_local_paths(text: str) -> str:
    """Redact local Windows paths in text."""
    sanitized = WINDOWS_LOCAL_PATH_IN_QUOTES_RE.sub("<local-path>", text)
    sanitized = WINDOWS_LOCAL_PATH_AFTER_EQUALS_RE.sub("<local-path>", sanitized)
    return WINDOWS_LOCAL_PATH_RE.sub("<local-path>", sanitized)


class LocalPathSanitizingFormatter(logging.Formatter):
    """Format log records with local path redaction."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one record and redact local paths."""
        return sanitize_local_paths(super().format(record))


def build_file_handler(log_file: str, level: str | int = "INFO") -> logging.FileHandler:
    """Create a file log handler with path redaction."""
    lvl = getattr(logging, str(level).upper(), level)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(lvl)
    handler.setFormatter(LocalPathSanitizingFormatter(LOG_FORMAT))
    return handler


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
        managed_handlers.append(build_file_handler(log_file, lvl))

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in managed_handlers:
        handler.setLevel(lvl)
        if not isinstance(handler, logging.FileHandler):
            handler.setFormatter(formatter)

    root_logger.setLevel(lvl)
    for handler in managed_handlers:
        root_logger.addHandler(handler)
    if extra_handlers:
        for handler in extra_handlers:
            root_logger.addHandler(handler)
