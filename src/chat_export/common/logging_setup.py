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


def build_file_handler(log_file: str, level: str | int = "DEBUG") -> logging.FileHandler:
    """Create a file log handler with path redaction."""
    lvl = getattr(logging, str(level).upper(), level)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(lvl)
    handler.setFormatter(LocalPathSanitizingFormatter(LOG_FORMAT))
    return handler


def setup_logging(
    log_file: Optional[str] = None,
    *,
    console: bool = True,
    extra_handlers: Optional[Iterable[logging.Handler]] = None,
    replace_existing: bool = True,
    console_level: str | int = "INFO",
    file_level: str | int = "DEBUG",
) -> None:
    """Configure root logging for one process run."""
    console_lvl = getattr(logging, str(console_level).upper(), console_level)
    file_lvl = getattr(logging, str(file_level).upper(), file_level)
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
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_lvl)
        managed_handlers.append(console_handler)
    if log_file:
        managed_handlers.append(build_file_handler(log_file, file_lvl))

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in managed_handlers:
        if not isinstance(handler, logging.FileHandler):
            handler.setFormatter(formatter)

    root_logger.setLevel(logging.DEBUG)
    for handler in managed_handlers:
        root_logger.addHandler(handler)
    if extra_handlers:
        for handler in extra_handlers:
            root_logger.addHandler(handler)
