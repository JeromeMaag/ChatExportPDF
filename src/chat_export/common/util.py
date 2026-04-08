"""Provide small filesystem, hashing, and path helpers.

This module contains utility functions shared across importers and renderers
for directory creation, safe filenames, hashing, binary formatting, and PDF
link path generation.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Optional


def ensure_dir(path: str) -> None:
    """Create a directory if it does not exist.

    Args:
        path (str): Directory path.
    """
    os.makedirs(path, exist_ok=True)


def safe_filename(s: str, max_len: int = 80) -> str:
    """Convert text to a filesystem-safe filename.

    Args:
        s (str): Input text.
        max_len (int): Maximum filename length.

    Returns:
        str: Sanitized filename.
    """
    s = (s or "").strip().replace(os.sep, "_")
    s = re.sub(r"[^\w\-. ]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "untitled"
    if len(s) > max_len:
        h = hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:8]
        s = s[: max_len - 9].rstrip() + "_" + h
    return s


def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    """Hash a file with SHA-256.

    Args:
        path (str): File path.
        chunk (int): Read chunk size in bytes.

    Returns:
        str: Lowercase SHA-256 hex digest.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def bytes_to_hex(b: Optional[bytes]) -> Optional[str]:
    """Convert nullable binary data to a hex string.

    Args:
        b (Optional[bytes]): Binary input value.

    Returns:
        Optional[str]: Hex string or ``None``.
    """
    return None if b is None else b.hex()


def blob_prefix_hex(b: Optional[bytes], n_bytes: int = 6) -> str:
    """Return a short hex prefix for binary data.

    Args:
        b (Optional[bytes]): Binary input value.
        n_bytes (int): Prefix length in bytes.

    Returns:
        str: Hex prefix or ``NULL``.
    """
    if not b:
        return "NULL"
    hx = b.hex()
    return hx[: n_bytes * 2]


def relpath_for_link(target_abs: str, pdf_abs: str) -> str:
    """Build a PDF-relative link path.

    Args:
        target_abs (str): Absolute target path.
        pdf_abs (str): Absolute PDF file path.

    Returns:
        str: Relative link path if possible. Otherwise an absolute path.
    """
    pdf_dir = os.path.dirname(os.path.abspath(pdf_abs))
    try:
        return os.path.relpath(os.path.abspath(target_abs), start=pdf_dir).replace(
            "\\",
            "/",
        )
    except Exception:
        return os.path.abspath(target_abs).replace("\\", "/")
