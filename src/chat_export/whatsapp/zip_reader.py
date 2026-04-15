"""Read raw WhatsApp ZIP exports.

This module selects the chat text file from a ZIP export, loads the raw text,
and exposes ZIP attachment members for later extraction and normalization.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class WhatsAppZipAttachment:
    """Store one ZIP attachment member reference.

    Attributes:
        name (str): ZIP member path.
        size (int): ZIP member size in bytes.
    """

    name: str
    size: int


@dataclass(slots=True)
class WhatsAppZipExport:
    """Store loaded WhatsApp ZIP export data.

    Attributes:
        zip_path (Path): ZIP file path.
        chat_text_name (str): Selected chat text member name.
        chat_text (str): Decoded chat text content.
        attachments (dict[str, WhatsAppZipAttachment]): Attachment members by filename.
    """

    zip_path: Path
    chat_text_name: str
    chat_text: str
    attachments: dict[str, WhatsAppZipAttachment]


MESSAGE_HINT_RE = re.compile(
    r"^\u200e?(?:\[\d{2}\.\d{2}\.\d{2}, \d{2}:\d{2}(?::\d{2})?\] |\d{2}\.\d{2}\.\d{2}, \d{2}:\d{2}(?::\d{2})? - )"
)


def _score_chat_text(text: str) -> tuple[int, int]:
    """Score one text file for WhatsApp chat-likeness.

    Args:
        text (str): Decoded text file content.

    Returns:
        tuple[int, int]: Matched message-line count and total line count.
    """
    lines = text.splitlines()
    matched = sum(1 for line in lines if MESSAGE_HINT_RE.match(line))
    return matched, len(lines)


def load_whatsapp_zip(
    zip_path: str,
    *,
    chat_text_name: str | None = None,
) -> WhatsAppZipExport:
    """Load a WhatsApp ZIP export and select the chat text file.

    Args:
        zip_path (str): ZIP file path.
        chat_text_name (str | None): Explicit chat text member name.

    Returns:
        WhatsAppZipExport: Loaded ZIP export data.

    Raises:
        ValueError: If no chat text exists, multiple plausible chat texts exist,
            or the requested text member is missing.
    """
    archive_path = Path(zip_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        text_candidates = [name for name in names if name.lower().endswith(".txt")]
        if not text_candidates:
            raise ValueError(f"No .txt chat export found in ZIP: {archive_path}")

        scored_candidates: list[tuple[tuple[int, int], str, str]] = []
        for name in text_candidates:
            text = archive.read(name).decode("utf-8", errors="replace")
            scored_candidates.append((_score_chat_text(text), name, text))

        if chat_text_name:
            selected = next((item for item in scored_candidates if item[1] == chat_text_name), None)
            if selected is None:
                available = ", ".join(sorted(text_candidates))
                raise ValueError(
                    f"Requested WhatsApp chat text file not found in ZIP: {chat_text_name}. "
                    f"Available .txt files: {available}"
                )
            _, selected_chat_text_name, chat_text = selected
            chat_text_name = selected_chat_text_name
        else:
            plausible = [item for item in scored_candidates if item[0][0] > 0]
            if len(plausible) > 1:
                candidates = ", ".join(
                    f"{name} (matched_lines={score[0]}, total_lines={score[1]})"
                    for score, name, _ in plausible
                )
                raise ValueError(
                    "Multiple plausible WhatsApp chat text files found in ZIP. "
                    "Please specify --chat-text-name explicitly. "
                    f"Candidates: {candidates}"
                )
            selected_pool = plausible if plausible else scored_candidates
            selected_pool.sort(key=lambda item: (item[0][0], item[0][1]), reverse=True)
            _, chat_text_name, chat_text = selected_pool[0]

        attachments = {}
        for name in names:
            if name == chat_text_name or name.endswith("/"):
                continue
            info = archive.getinfo(name)
            filename = Path(name).name
            attachments[filename] = WhatsAppZipAttachment(
                name=name,
                size=info.file_size,
            )

    return WhatsAppZipExport(
        zip_path=archive_path,
        chat_text_name=chat_text_name,
        chat_text=chat_text,
        attachments=attachments,
    )


def iter_attachment_names(export: WhatsAppZipExport) -> Iterable[str]:
    """Iterate attachment filenames (ZIP basenames) from a loaded ZIP export.

    Returns the dict keys from ``export.attachments``, which are the bare
    filenames (``Path(name).name``) of each ZIP member — no further
    normalization or sanitization is applied.

    Args:
        export (WhatsAppZipExport): Loaded ZIP export data.

    Returns:
        Iterable[str]: Attachment filenames (ZIP basenames).
    """
    return export.attachments.keys()
