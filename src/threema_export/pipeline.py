from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

from .config import ExportConfig
from .db.connect import connect_db
from .db.queries import (
    load_contacts,
    load_groups,
    load_conversations,
    load_group_members,
    load_messages_for_conversation,
)
from .external_index import build_external_index
from .media.export import export_media_for_message
from .models import Contact, Conversation
from .timeutil import auto_detect_time_mode
from .util import ensure_dir, safe_filename
from .pdf.builder import build_pdfs_for_conversation

log = logging.getLogger(__name__)


def build_conversation_title(conv: Conversation, contacts: Dict[int, Contact]) -> str:
    if conv.group_id_hex:
        return (
            conv.group_name.strip()
            if (conv.group_name and conv.group_name.strip())
            else f"Group_{conv.group_id_hex[:12]}"
        )
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        return contacts[int(conv.contact_pk)].display_name()
    return f"Conversation_{conv.pk}"


def export_all_conversations(cfg: ExportConfig) -> Dict[str, Any]:
    cfg.validate()

    out_dir = os.path.abspath(cfg.out_dir)
    conv_out = os.path.join(out_dir, "conversations")
    ensure_dir(conv_out)

    if cfg.export_media:
        media_out = os.path.join(out_dir, "media")
        ensure_dir(media_out)

    conn = connect_db(cfg.db_path)
    try:
        time_mode = auto_detect_time_mode(conn)
        log.info("Auto-detected time mode: %s", time_mode)

        contacts = load_contacts(conn)
        log.info("Loaded %d contacts", len(contacts))
        log.debug("Contacts: %s", contacts)

        groups = load_groups(conn)
        log.info("Loaded %d groups", len(groups))
        log.debug("Groups: %s", groups)

        conversations = load_conversations(conn)
        log.info("Loaded %d conversations", len(conversations))

        group_members_map = load_group_members(conn)
        log.info("Loaded group members for %d groups", len(group_members_map))
        log.debug("Group members map: %s", group_members_map)

        if cfg.limit_conversations and cfg.limit_conversations > 0:
            conversations = conversations[: cfg.limit_conversations]
            log.info("Limiting to first %d conversations", len(conversations))
        log.debug("Conversations: %s", conversations)

        external_index = build_external_index(cfg.external_folder)
        log.info(
            "External index entries: %s (external_folder=%s)",
            len(external_index),
            cfg.external_folder,
        )

        results: Dict[str, Any] = {
            "db_path": cfg.db_path,
            "out_dir": out_dir,
            "time_mode": time_mode,
            "timezone": cfg.tz_name,
            "external_folder": (
                os.path.abspath(cfg.external_folder) if cfg.external_folder else None
            ),
            "external_index_entries": len(external_index),
            "exported": [],
        }

        for conv in conversations:
            chat_title = build_conversation_title(conv, contacts)
            safe_title = safe_filename(chat_title)

            pdf_path = os.path.join(conv_out, f"conv_{conv.pk}_{safe_title}.pdf")
            pdf_tech_path = os.path.join(
                conv_out, f"conv_{conv.pk}_{safe_title}_TECH.pdf"
            )

            conv_media_dir = (
                os.path.join(media_out, f"conv_{conv.pk}_{safe_title}")
                if cfg.export_media
                else None
            )
            if conv_media_dir:
                ensure_dir(conv_media_dir)

            members = group_members_map.get(conv.pk, [])
            messages = load_messages_for_conversation(conn, conv.pk)
            if cfg.limit_messages and cfg.limit_messages > 0:
                messages = messages[: cfg.limit_messages]

            media_index: Dict[int, List[Dict[str, Any]]] = {}
            if cfg.export_media and conv_media_dir:
                for m in messages:
                    sender = (
                        "Me"
                        if m.is_own == 1
                        else (
                            contacts[int(m.sender_pk)].display_name()
                            if (
                                m.sender_pk is not None and int(m.sender_pk) in contacts
                            )
                            else "Unknown"
                        )
                    )
                    items = export_media_for_message(
                        conn=conn,
                        msg=m,
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
                        media_index[m.pk] = items

            build_pdfs_for_conversation(
                conn=conn,
                conv=conv,
                chat_title=chat_title,
                pdf_path=pdf_path,
                pdf_tech_path=pdf_tech_path,
                contacts=contacts,
                groups=groups,
                members=members,
                messages=messages,
                media_index=media_index,
                time_mode=time_mode,
                tz_name=cfg.tz_name,
            )

            results["exported"].append(
                {
                    "conv_pk": conv.pk,
                    "title": chat_title,
                    "pdf_path": pdf_path,
                    "pdf_tech_path": pdf_tech_path,
                    "media_dir": conv_media_dir,
                    "message_count": len(messages),
                }
            )

            log.info("Exported conv_pk=%s title=%s", conv.pk, chat_title)

        return results
    finally:
        conn.close()
