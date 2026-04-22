"""Load Threema SQLite data and normalize it for export.

This module reads Threema conversations, messages, reactions, edit history,
and media references from the source database. It then normalizes the data and
builds the Threema-specific TECH payload.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from ..common.timeutil import auto_detect_time_mode
from ..common.util import safe_filename
from ..config import ExportConfig
from ..importers.base import ImportRun, ImportedConversation
from .db.connect import connect_db
from .db.queries import (
    load_contacts,
    load_conversations,
    load_group_members,
    load_groups,
    load_history,
    load_messages_for_conversation,
    load_reactions,
)
from .external_index import build_external_index
from .media.export import export_media_for_message
from .normalize import build_conversation_title, determine_sender_display, normalize_threema_conversation
from .tech_pdf import ThreemaTechnicalConversation

log = logging.getLogger(__name__)


def _count_missing_media(media_index: Dict[int, List[Dict[str, Any]]]) -> int:
    """Count media records whose external pointer could not be resolved."""
    return sum(
        1
        for items in media_index.values()
        for item in items
        if item.get("pointer_uuid") and not item.get("external_path")
    )


def _count_skipped_media(media_index: Dict[int, List[Dict[str, Any]]]) -> int:
    """Count media records skipped because of configured limits."""
    return sum(
        1
        for items in media_index.values()
        for item in items
        if item.get("skipped_due_to_limit")
    )


class ThreemaImporter:
    """Implement the importer contract for Threema SQLite exports."""

    source_app = "threema"

    def load_conversations(self, cfg: ExportConfig) -> ImportRun:
        """Load and normalize all selected Threema conversations.

        Args:
            cfg (ExportConfig): Export configuration.

        Returns:
            ImportRun: Import result with normalized conversations and Threema
            TECH payloads.
        """
        input_path = cfg.resolved_input_path()
        log.info("Loading Threema export")
        log.debug("Loading Threema export db=%s", input_path)
        conn = connect_db(input_path)
        try:
            time_mode = auto_detect_time_mode(conn)
            log.info("Auto-detected time mode: %s", time_mode)

            contacts = load_contacts(conn)
            groups = load_groups(conn)
            conversations = load_conversations(conn)
            group_members_map = load_group_members(conn)
            log.debug(
                "Loaded Threema base data contacts=%s groups=%s conversations=%s group_member_mappings=%s",
                len(contacts),
                len(groups),
                len(conversations),
                len(group_members_map),
            )

            if cfg.limit_conversations and cfg.limit_conversations > 0:
                conversations = conversations[: cfg.limit_conversations]
                log.debug(
                    "Applied Threema conversation limit limit=%s resulting=%s",
                    cfg.limit_conversations,
                    len(conversations),
                )

            external_index = build_external_index(cfg.external_folder)
            log.debug("Prepared external index entries=%s", len(external_index))
            media_root = os.path.join(os.path.abspath(cfg.out_dir), "media")

            imported: List[ImportedConversation] = []
            total_missing_media_count = 0
            total_skipped_media_count = 0
            for conv in conversations:
                chat_title = build_conversation_title(conv, contacts)
                log.info("Processing Threema conversation conv_pk=%s", conv.pk)
                log.debug(
                    "Processing Threema conversation details conv_pk=%s title=%s",
                    conv.pk,
                    chat_title,
                )
                messages = load_messages_for_conversation(conn, conv.pk)
                log.debug(
                    "Loaded Threema messages conv_pk=%s count=%s",
                    conv.pk,
                    len(messages),
                )
                if cfg.limit_messages and cfg.limit_messages > 0:
                    messages = messages[: cfg.limit_messages]
                    log.debug(
                        "Applied Threema message limit conv_pk=%s limit=%s resulting=%s",
                        conv.pk,
                        cfg.limit_messages,
                        len(messages),
                    )

                conv_media_dir = None
                if cfg.export_media:
                    conv_media_dir = os.path.join(
                        media_root,
                        f"conv_{conv.pk}_{safe_filename(chat_title)}",
                    )

                media_index: Dict[int, List[Dict[str, Any]]] = {}
                if cfg.export_media and conv_media_dir:
                    for message in messages:
                        sender = determine_sender_display(message, conv, contacts)
                        items = export_media_for_message(
                            conn=conn,
                            msg=message,
                            chat_title=chat_title,
                            conv_media_dir=conv_media_dir,
                            external_index=external_index,
                            time_mode=time_mode,
                            tz_name=cfg.tz_name,
                            sender=sender,
                            max_media_bytes=cfg.max_media_bytes,
                            keep_raw=True,
                        )
                        if items:
                            media_index[message.pk] = items
                if cfg.export_media:
                    if log.isEnabledFor(logging.DEBUG):
                        media_item_count = sum(len(items) for items in media_index.values())
                        log.debug(
                            "Collected Threema media conv_pk=%s messages_with_media=%s media_items=%s media_dir=%s",
                            conv.pk,
                            len(media_index),
                            media_item_count,
                            conv_media_dir,
                        )
                missing_media_count = _count_missing_media(media_index)
                skipped_media_count = _count_skipped_media(media_index)
                total_missing_media_count += missing_media_count
                total_skipped_media_count += skipped_media_count

                reactions_by_message = {
                    message.pk: [dict(row) for row in load_reactions(conn, message.pk)]
                    for message in messages
                }
                history_by_message = {
                    message.pk: [dict(row) for row in load_history(conn, message.pk)]
                    for message in messages
                }
                if log.isEnabledFor(logging.DEBUG):
                    reaction_count = sum(len(rows) for rows in reactions_by_message.values())
                    history_count = sum(len(rows) for rows in history_by_message.values())
                    log.debug(
                        "Collected Threema metadata conv_pk=%s reactions=%s histories=%s",
                        conv.pk,
                        reaction_count,
                        history_count,
                    )

                groupinfo = groups.get(conv.group_id_hex) if conv.group_id_hex else None
                members = group_members_map.get(conv.pk, [])
                normalized = normalize_threema_conversation(
                    conv=conv,
                    contacts=contacts,
                    groupinfo=groupinfo,
                    member_pks=members,
                    messages=messages,
                    media_index=media_index,
                    reactions_by_message=reactions_by_message,
                    history_by_message=history_by_message,
                    time_mode=time_mode,
                    tz_name=cfg.tz_name,
                )
                tech_payload = ThreemaTechnicalConversation(
                    conv=conv,
                    chat_title=chat_title,
                    contacts=contacts,
                    groupinfo=groupinfo,
                    members=members,
                    messages=messages,
                    media_index=media_index,
                    reactions_by_message=reactions_by_message,
                    history_by_message=history_by_message,
                    time_mode=time_mode,
                    tz_name=cfg.tz_name,
                )

                imported.append(
                    ImportedConversation(
                        conversation=normalized,
                        tech_payload=tech_payload,
                        tech_renderer="threema",
                        metadata={
                            "conv_pk": conv.pk,
                            "message_count": len(messages),
                            "media_dir": os.path.abspath(conv_media_dir) if conv_media_dir else None,
                            "missing_media_count": missing_media_count,
                            "skipped_media_count": skipped_media_count,
                            "unparseable_message_count": 0,
                        },
                    )
                )
                log.info(
                    "Prepared Threema conversation conv_pk=%s conversation_id=%s messages=%s participants=%s",
                    conv.pk,
                    normalized.conversation_id,
                    len(normalized.messages),
                    len(normalized.participants),
                )

            run = ImportRun(
                source_app=self.source_app,
                conversations=imported,
                metadata={
                    "input_path": input_path,
                    "time_mode": time_mode,
                    "timezone": cfg.tz_name,
                    "external_folder": os.path.abspath(cfg.external_folder)
                    if cfg.external_folder
                    else None,
                    "external_index_entries": len(external_index),
                    "missing_media_count": total_missing_media_count,
                    "skipped_media_count": total_skipped_media_count,
                    "unparseable_message_count": 0,
                },
            )
            log.info(
                "Completed Threema import conversations=%s time_mode=%s external_index_entries=%s",
                len(run.conversations),
                time_mode,
                len(external_index),
            )
            return run
        finally:
            conn.close()
            log.debug("Closed Threema database connection db=%s", input_path)
