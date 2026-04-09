"""Detect and unwrap exported Threema media payloads by magic bytes.

This module uses a small signature-based heuristic to detect common container
or file formats and to strip one or two leading bytes from wrapped payloads
when the raw blob does not start with the actual file header.
"""

from __future__ import annotations


def detect_file_ext(data: bytes) -> str:
    """Guess a file extension from the leading bytes of a payload.

    Args:
        data (bytes): Raw payload bytes.

    Returns:
        str: Detected extension such as ``.jpg`` or ``.png``. Returns
        ``.bin`` when no known signature matches.
    """
    if len(data) >= 2 and data[:2] == b"\xFF\xD8":
        return ".jpg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".mp4"
    if len(data) >= 4 and data[:4] == b"caff":
        return ".caf"
    if len(data) >= 4 and data[:4] == b"%PDF":
        return ".pdf"
    if len(data) >= 2 and data[:2] == b"PK":
        return ".zip"
    return ".bin"


def unwrap_by_magic(blob: bytes):
    """Strip simple wrapper bytes until a known file signature is found.

    Args:
        blob (bytes): Raw blob payload from the database or external file.

    Returns:
        tuple[bytes, str, str]: Unwrapped payload bytes, detected file
        extension, and unwrap mode label. The unwrap mode is ``none``,
        ``strip_1``, or ``strip_2`` depending on how many leading bytes were
        removed.
    """
    ext0 = detect_file_ext(blob)
    if ext0 != ".bin":
        return blob, ext0, "none"
    if len(blob) >= 2:
        ext1 = detect_file_ext(blob[1:])
        if ext1 != ".bin":
            return blob[1:], ext1, "strip_1"
    if len(blob) >= 3:
        ext2 = detect_file_ext(blob[2:])
        if ext2 != ".bin":
            return blob[2:], ext2, "strip_2"
    return blob, ".bin", "none"
