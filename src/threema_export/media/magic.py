from __future__ import annotations

def detect_file_ext(data: bytes) -> str:
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
