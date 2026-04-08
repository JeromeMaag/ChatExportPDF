from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import zipfile
from pathlib import Path
from typing import Any, Dict

from ..common.util import ensure_dir, safe_filename
from ..config import ExportConfig
from ..importers.base import ImportRun, ImportedConversation
from .normalize import normalize_whatsapp_conversation, parse_chat_messages
from .zip_reader import load_whatsapp_zip

log = logging.getLogger(__name__)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_attachments(
    export,
    cfg: ExportConfig,
) -> tuple[dict[str, dict[str, object]], str | None]:
    media_lookup: dict[str, dict[str, object]] = {}
    media_dir = None
    if cfg.export_media:
        title = safe_filename(Path(export.chat_text_name).stem)
        media_dir = os.path.join(os.path.abspath(cfg.out_dir), "media", title)
        ensure_dir(media_dir)

    with zipfile.ZipFile(export.zip_path) as archive:
        for filename, attachment in export.attachments.items():
            mime_type, _ = mimetypes.guess_type(filename)
            info: dict[str, object] = {
                "zip_member_name": attachment.name,
                "size": attachment.size,
                "mime_type": mime_type,
                "missing_from_zip": False,
            }
            data = archive.read(attachment.name)
            info["sha256"] = _sha256_bytes(data)
            if media_dir:
                target_path = os.path.join(media_dir, filename)
                with open(target_path, "wb") as handle:
                    handle.write(data)
                info["absolute_path"] = os.path.abspath(target_path)
            else:
                info["absolute_path"] = None
            media_lookup[filename] = info

    return media_lookup, media_dir


class WhatsAppImporter:
    source_app = "whatsapp"

    def load_conversations(self, cfg: ExportConfig) -> ImportRun:
        export = load_whatsapp_zip(
            cfg.resolved_input_path(),
            chat_text_name=cfg.chat_text_name,
        )
        parsed_messages = parse_chat_messages(export.chat_text, cfg.tz_name)
        if cfg.limit_messages and cfg.limit_messages > 0:
            parsed_messages = parsed_messages[: cfg.limit_messages]
        media_lookup, media_dir = _extract_attachments(export, cfg)
        conversation = normalize_whatsapp_conversation(
            export=export,
            parsed_messages=parsed_messages,
            tz_name=cfg.tz_name,
            media_lookup=media_lookup,
        )

        imported = ImportedConversation(
            conversation=conversation,
            tech_payload=None,
            tech_renderer=None,
            metadata={
                "media_dir": media_dir,
                "message_count": len(parsed_messages),
            },
        )

        log.info(
            "Loaded WhatsApp export zip=%s title=%s messages=%s attachments=%s",
            export.zip_path,
            conversation.title,
            len(parsed_messages),
            len(export.attachments),
        )

        return ImportRun(
            source_app=self.source_app,
            conversations=[imported],
            metadata={
                "input_path": str(export.zip_path),
                "timezone": cfg.tz_name,
                "attachments_in_zip": len(export.attachments),
            },
        )
