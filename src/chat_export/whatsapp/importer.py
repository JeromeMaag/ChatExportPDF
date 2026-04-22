"""Load WhatsApp ZIP exports and normalize them for export.

This module reads the selected WhatsApp ZIP export, extracts attachments,
parses the chat text, and converts the result into the shared normalized
conversation model.
"""

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
from .normalize import (
    normalize_whatsapp_conversation,
    parse_chat_messages_with_stats,
)
from .zip_reader import load_whatsapp_zip

log = logging.getLogger(__name__)


def _sha256_bytes(data: bytes) -> str:
    """Hash binary content with SHA-256.

    Args:
        data (bytes): Binary input data.

    Returns:
        str: Lowercase SHA-256 hex digest.
    """
    return hashlib.sha256(data).hexdigest()


def _extract_attachments(
    export,
    cfg: ExportConfig,
) -> tuple[dict[str, dict[str, object]], str | None]:
    """Extract WhatsApp ZIP attachments to the media output directory.

    Args:
        export: Loaded WhatsApp ZIP export data.
        cfg (ExportConfig): Export configuration.

    Returns:
        tuple[dict[str, dict[str, object]], str | None]: Media lookup by
        filename and the media output directory path.
    """
    media_lookup: dict[str, dict[str, object]] = {}
    media_dir = None
    if cfg.export_media:
        title = safe_filename(Path(export.chat_text_name).stem)
        media_dir = os.path.join(os.path.abspath(cfg.out_dir), "media", title)
        ensure_dir(media_dir)
    else:
        log.debug("WhatsApp media export disabled zip=%s", export.zip_path)

    with zipfile.ZipFile(export.zip_path) as archive:
        for filename, attachment in export.attachments.items():
            mime_type, _ = mimetypes.guess_type(filename)
            info: dict[str, object] = {
                "zip_member_name": attachment.name,
                "size": attachment.size,
                "mime_type": mime_type,
                "missing_from_zip": False,
                "skipped_due_to_limit": False,
                "skip_reason": None,
            }
            if cfg.max_media_bytes and attachment.size > cfg.max_media_bytes:
                info["sha256"] = None
                info["absolute_path"] = None
                info["skipped_due_to_limit"] = True
                info["skip_reason"] = (
                    f"size={attachment.size} exceeds max_media_bytes={cfg.max_media_bytes}"
                )
                media_lookup[filename] = info
                log.warning(
                    "Skipped WhatsApp attachment due to size limit zip=%s filename=%s size=%s max=%s",
                    export.zip_path,
                    filename,
                    attachment.size,
                    cfg.max_media_bytes,
                )
                continue

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

    log.debug(
        "Prepared WhatsApp attachments zip=%s attachments=%s media_dir=%s",
        export.zip_path,
        len(media_lookup),
        media_dir,
    )

    return media_lookup, media_dir


class WhatsAppImporter:
    """Implement the importer contract for WhatsApp ZIP exports."""

    source_app = "whatsapp"

    def load_conversations(self, cfg: ExportConfig) -> ImportRun:
        """Load and normalize one WhatsApp ZIP export.

        Args:
            cfg (ExportConfig): Export configuration.

        Returns:
            ImportRun: Import result with one normalized conversation.
        """
        input_path = cfg.resolved_input_path()
        log.info("Loading WhatsApp export")
        log.debug("Loading WhatsApp export zip=%s", input_path)
        export = load_whatsapp_zip(
            input_path,
            chat_text_name=cfg.chat_text_name,
        )
        parse_result = parse_chat_messages_with_stats(export.chat_text, cfg.tz_name)
        parsed_messages = parse_result.messages
        log.debug(
            "Parsed WhatsApp messages zip=%s count=%s",
            export.zip_path,
            len(parsed_messages),
        )
        if cfg.limit_messages and cfg.limit_messages > 0:
            parsed_messages = parsed_messages[: cfg.limit_messages]
            log.debug(
                "Applied WhatsApp message limit zip=%s limit=%s resulting=%s",
                export.zip_path,
                cfg.limit_messages,
                len(parsed_messages),
            )
        media_lookup, media_dir = _extract_attachments(export, cfg)
        exported_attachment_count = sum(
            1 for media in media_lookup.values() if media.get("absolute_path")
        )
        referenced_attachment_names = [
            message.attachment_name
            for message in parsed_messages
            if message.attachment_name
        ]
        missing_media_count = sum(
            1
            for attachment_name in referenced_attachment_names
            if attachment_name not in media_lookup
        )
        skipped_media_count = sum(
            1
            for attachment_name in referenced_attachment_names
            if media_lookup.get(attachment_name, {}).get("skipped_due_to_limit")
        )
        if missing_media_count:
            log.warning(
                "WhatsApp messages reference attachments missing from ZIP count=%s",
                missing_media_count,
            )
        log.debug(
            "Prepared WhatsApp media lookup zip=%s entries=%s exported=%s missing=%s skipped=%s media_dir=%s",
            export.zip_path,
            len(media_lookup),
            exported_attachment_count,
            missing_media_count,
            skipped_media_count,
            media_dir,
        )
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
                "missing_media_count": missing_media_count,
                "skipped_media_count": skipped_media_count,
                "unparseable_message_count": parse_result.unparseable_line_count,
            },
        )

        log.info(
            "Loaded WhatsApp export messages=%s attachments=%s media_exported=%s",
            len(parsed_messages),
            len(export.attachments),
            exported_attachment_count,
        )
        log.debug(
            "Loaded WhatsApp export details zip=%s title=%s",
            export.zip_path,
            conversation.title,
        )

        run = ImportRun(
            source_app=self.source_app,
            conversations=[imported],
            metadata={
                "input_path": str(export.zip_path),
                "timezone": cfg.tz_name,
                "attachments_in_zip": len(export.attachments),
                "missing_media_count": missing_media_count,
                "skipped_media_count": skipped_media_count,
                "unparseable_message_count": parse_result.unparseable_line_count,
                "whatsapp_line_count": parse_result.line_count,
                "whatsapp_continuation_line_count": parse_result.continuation_line_count,
            },
        )
        log.info(
            "Completed WhatsApp import conversations=%s attachments_in_zip=%s timezone=%s",
            len(run.conversations),
            len(export.attachments),
            cfg.tz_name,
        )
        return run
