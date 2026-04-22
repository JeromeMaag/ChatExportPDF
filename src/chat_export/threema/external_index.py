"""Resolve Threema external media payloads."""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


def build_external_index(external_folder: Optional[str]) -> Dict[str, str]:
    """Index external data files by UUID.

    Args:
        external_folder (Optional[str]): Root `_EXTERNAL_DATA` directory.

    Returns:
        Dict[str, str]: Absolute file paths keyed by lowercase UUID.
    """
    idx: Dict[str, str] = {}
    if not external_folder:
        log.info("External folder not set -> external index disabled.")
        return idx
    root = os.path.abspath(external_folder)
    if not os.path.exists(root):
        log.warning("External folder does not exist: %s", root)
        return idx

    log.info("Building external index")

    uuid_anywhere = re.compile(
        r"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
    )
    scanned_files = 0
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            scanned_files += 1
            m = uuid_anywhere.search(fn)
            if m:
                idx.setdefault(m.group(1).lower(), os.path.join(dirpath, fn))
            else:
                stem = os.path.splitext(fn)[0]
                if UUID_RE.match(stem):
                    idx.setdefault(stem.lower(), os.path.join(dirpath, fn))

    log.info("External index built: %s entries", len(idx))
    log.debug("External index root=%s scanned_files=%s", root, scanned_files)
    return idx


def parse_external_pointer(blob: bytes) -> Optional[str]:
    """Parse a Threema external pointer blob.

    Args:
        blob (bytes): Raw blob payload.

    Returns:
        Optional[str]: UUID string if the blob is a valid pointer. Otherwise
        ``None``.
    """
    if not blob or len(blob) < 10 or blob[0] != 0x02:
        return None
    payload = blob[1:-1] if blob.endswith(b"\x00") else blob[1:]
    try:
        s = payload.decode("ascii", errors="strict")
    except Exception:
        return None
    return s if UUID_RE.match(s) else None


def resolve_pointer_if_needed(
    blob: bytes, external_index: Dict[str, str]
) -> Tuple[bytes, Optional[str], Optional[str]]:
    """Resolve external pointer payloads to file content.

    Args:
        blob (bytes): Raw blob payload.
        external_index (Dict[str, str]): External data index keyed by UUID.

    Returns:
        Tuple[bytes, Optional[str], Optional[str]]: Resolved payload bytes,
        parsed UUID, and resolved absolute file path.
    """
    uuid = parse_external_pointer(blob)
    if not uuid:
        return blob, None, None
    p = external_index.get(uuid.lower())
    if not p:
        log.debug("External pointer UUID not in index: %s", uuid)
        return blob, uuid, None

    if not os.path.exists(p):
        log.warning("External pointer UUID found but file missing: %s -> %s", uuid, p)
        return blob, uuid, None

    try:
        with open(p, "rb") as f:
            payload = f.read()
    except Exception as exc:
        log.warning(
            "Failed to read external data file for UUID %s: %s (%s)",
            uuid,
            p,
            exc,
        )
        return blob, uuid, None

    log.debug(
        "Resolved external pointer UUID %s -> %s (size=%s)", uuid, p, len(payload)
    )
    return payload, uuid, os.path.abspath(p)
