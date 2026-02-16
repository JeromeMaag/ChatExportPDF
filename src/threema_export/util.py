from __future__ import annotations
import hashlib
import os
import re
from typing import Any, Optional


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_filename(s: str, max_len: int = 80) -> str:
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
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def bytes_to_hex(b: Optional[bytes]) -> Optional[str]:
    return None if b is None else b.hex()


def blob_prefix_hex(b: Optional[bytes], n_bytes: int = 6) -> str:
    if not b:
        return "NULL"
    hx = b.hex()
    return hx[: n_bytes * 2]


def relpath_for_link(target_abs: str, pdf_abs: str) -> str:
    pdf_dir = os.path.dirname(os.path.abspath(pdf_abs))
    try:
        return os.path.relpath(os.path.abspath(target_abs), start=pdf_dir).replace(
            "\\", "/"
        )
    except Exception:
        return os.path.abspath(target_abs).replace("\\", "/")
