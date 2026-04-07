from __future__ import annotations

import re
from typing import List, Tuple

try:
    import emoji as emoji_pkg

    HAS_EMOJI = True
except Exception:
    emoji_pkg = None
    HAS_EMOJI = False

_CTRL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def strip_controls(s: str) -> str:
    return _CTRL_RE.sub("", s or "")


def esc_xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def demojize_text(s: str) -> Tuple[str, List[str]]:
    s = strip_controls(s)
    cps: List[str] = []
    if not s:
        return s, cps

    if HAS_EMOJI:
        for ch in s:
            o = ord(ch)
            if o > 0xFFFF or (0x2600 <= o <= 0x27BF) or (0x1F000 <= o <= 0x1FAFF):
                cps.append(f"U+{o:04X}")
        out = emoji_pkg.demojize(s, language="en").replace("::", ":")
        return out, sorted(set(cps))

    out_chars: List[str] = []
    for ch in s:
        o = ord(ch)
        if o <= 0x7E:
            out_chars.append(ch)
        else:
            cps.append(f"U+{o:04X}")
            out_chars.append(f"[U+{o:04X}]")
    return "".join(out_chars), sorted(set(cps))


def normalize_for_pdf(text: str) -> Tuple[str, List[str]]:
    t, cps = demojize_text(text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return t, cps
