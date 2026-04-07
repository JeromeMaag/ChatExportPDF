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


class ThreemaImporter:
    source_app = "threema"

    def load_conversations(self, cfg: ExportConfig) -> ImportRun:
        if not cfg.db_path:
            raise ValueError("Threema importer requires db_path")

        conn = connect_db(cfg.db_path)
        try:
            time_mode = auto_detect_time_mode(conn)
            log.info("Auto-detected time mode: %s", time_mode)

            contacts = load_contacts(conn)
            groups = load_groups(conn)
            conversations = load_conversations(conn)
            group_members_map = load_group_members(conn)

            if cfg.limit_conversations and cfg.limit_conversations > 0:
                conversations = conversations[: cfg.limit_conversations]

            external_index = build_external_index(cfg.external_folder)
            media_root = os.path.join(os.path.abspath(cfg.out_dir), "media")

            imported: List[ImportedConversation] = []
            for conv in conversations:
                chat_title = build_conversation_title(conv, contacts)
                messages = load_messages_for_conversation(conn, conv.pk)
                if cfg.limit_messages and cfg.limit_messages > 0:
                    messages = messages[: cfg.limit_messages]

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

                reactions_by_message = {
                    message.pk: [dict(row) for row in load_reactions(conn, message.pk)]
                    for message in messages
                }
                history_by_message = {
                    message.pk: [dict(row) for row in load_history(conn, message.pk)]
                    for message in messages
                }

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
                        },
                    )
                )

            return ImportRun(
                source_app=self.source_app,
                conversations=imported,
                metadata={
                    "db_path": cfg.db_path,
                    "time_mode": time_mode,
                    "timezone": cfg.tz_name,
                    "external_folder": os.path.abspath(cfg.external_folder)
                    if cfg.external_folder
                    else None,
                    "external_index_entries": len(external_index),
                },
            )
        finally:
            conn.close()
