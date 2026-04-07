from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ..normalized.models import (
    NormalizedAttachment,
    NormalizedConversation,
    NormalizedEdit,
    NormalizedMessage,
    NormalizedParticipant,
    NormalizedReaction,
)
from ..textutil import normalize_for_pdf
from ..timeutil import format_dt
from ..util import blob_prefix_hex
from .models import ENT_MAP, Contact, Conversation, GroupInfo, Message


def build_conversation_title(conv: Conversation, contacts: Dict[int, Contact]) -> str:
    if conv.group_id_hex:
        return (
            conv.group_name.strip()
            if conv.group_name and conv.group_name.strip()
            else f"Group_{conv.group_id_hex[:12]}"
        )
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        return contacts[int(conv.contact_pk)].display_name()
    return f"Conversation_{conv.pk}"


def determine_sender_display(
    msg: Message,
    conv: Conversation,
    contacts: Dict[int, Contact],
) -> str:
    if msg.is_own == 1:
        return "Me"
    if msg.sender_pk is not None and int(msg.sender_pk) in contacts:
        return contacts[int(msg.sender_pk)].display_name()
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        return contacts[int(conv.contact_pk)].display_name()
    return "Unknown"


def determine_sender_id(
    msg: Message,
    conv: Conversation,
    contacts: Dict[int, Contact],
) -> Optional[str]:
    if msg.is_own == 1:
        if conv.group_my_identity:
            return f"threema-id:{conv.group_my_identity}"
        return "threema:self"
    if msg.sender_pk is not None and int(msg.sender_pk) in contacts:
        contact = contacts[int(msg.sender_pk)]
        if contact.identity:
            return f"threema-id:{contact.identity}"
        return f"threema-contact:{contact.pk}"
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        contact = contacts[int(conv.contact_pk)]
        if contact.identity:
            return f"threema-id:{contact.identity}"
        return f"threema-contact:{contact.pk}"
    return None


def message_type_from_ent(ent: int) -> str:
    return ENT_MAP.get(ent, f"ENT_{ent}").lower()


def build_status(msg: Message) -> str:
    if msg.sendfailed in (1, True):
        return "failed"
    if msg.read in (1, True):
        return "read"
    if msg.delivered in (1, True):
        return "delivered"
    if msg.sent in (1, True):
        return "sent"
    return "unknown"


def build_direction(msg: Message) -> str:
    if msg.ent == 20:
        return "system"
    return "outgoing" if msg.is_own == 1 else "incoming"


def build_zid_index(messages: List[Message]) -> Dict[str, Message]:
    idx: Dict[str, Message] = {}
    for message in messages:
        if message.zid:
            idx[message.zid.hex()] = message
    return idx


def build_quote_preview(
    msg: Message,
    zid_index: Dict[str, Message],
    time_mode: str,
    tz_name: str,
    conv: Conversation,
    contacts: Dict[int, Contact],
) -> Optional[str]:
    if not msg.quoted_message_id:
        return None

    quoted_hex = msg.quoted_message_id.hex()
    ref = zid_index.get(quoted_hex)
    if not ref:
        return "Reply to: (unknown message)"

    sender = determine_sender_display(ref, conv, contacts)
    dt_s = format_dt(ref.date_raw, time_mode, tz_name, 1900)
    if ref.text:
        excerpt, _ = normalize_for_pdf(ref.text.strip().replace("\n", " "))
        excerpt = excerpt[:120] + "..." if len(excerpt) > 120 else excerpt
    else:
        excerpt = ENT_MAP.get(ref.ent, f"ENT_{ref.ent}")
    return f"Reply to: {sender} {dt_s} - {excerpt}"


def normalize_attachment(
    message_id: int,
    index: int,
    item: Dict[str, Any],
) -> NormalizedAttachment:
    absolute_path = item.get("exported_path_abs")
    return NormalizedAttachment(
        attachment_id=f"threema-attachment:{message_id}:{index}",
        kind=str(item.get("kind") or "file"),
        filename=os.path.basename(absolute_path) if absolute_path else None,
        absolute_path=absolute_path,
        relative_path=None,
        mime_type=None,
        size=item.get("exported_size"),
        sha256=item.get("exported_sha256"),
        metadata={
            "table": item.get("table"),
            "source_label": item.get("source_label"),
            "unwrap_mode": item.get("unwrap_mode"),
            "raw_path_abs": item.get("raw_path_abs"),
            "raw_sha256": item.get("raw_sha256"),
            "pointer_uuid": item.get("pointer_uuid"),
            "external_path": item.get("external_path"),
            "pointer_dump_path_abs": item.get("pointer_dump_path_abs"),
            "note": item.get("note"),
        },
    )


def normalize_reactions(
    reactions: List[Dict[str, Any]],
    contacts: Dict[int, Contact],
    time_mode: str,
    tz_name: str,
) -> List[NormalizedReaction]:
    out: List[NormalizedReaction] = []
    for reaction in reactions:
        creator_pk = reaction.get("ZCREATOR")
        if creator_pk is not None and int(creator_pk) in contacts:
            creator_display = contacts[int(creator_pk)].display_name()
        else:
            creator_display = f"Contact#{creator_pk}"
        reaction_text, _ = normalize_for_pdf(str(reaction.get("ZREACTION") or ""))
        out.append(
            NormalizedReaction(
                creator_display=creator_display,
                reaction=reaction_text,
                timestamp=format_dt(reaction.get("ZDATE"), time_mode, tz_name, 1900),
                metadata={"creator_pk": creator_pk},
            )
        )
    return out


def normalize_edits(
    history: List[Dict[str, Any]],
    time_mode: str,
    tz_name: str,
) -> List[NormalizedEdit]:
    out: List[NormalizedEdit] = []
    for entry in history:
        out.append(
            NormalizedEdit(
                timestamp=format_dt(entry.get("ZEDITDATE"), time_mode, tz_name, 1900),
                text=entry.get("ZTEXT"),
                metadata={},
            )
        )
    return out


def build_participants(
    conv: Conversation,
    contacts: Dict[int, Contact],
    groupinfo: Optional[GroupInfo],
    member_pks: List[int],
    time_mode: str,
    tz_name: str,
) -> List[NormalizedParticipant]:
    creator_id = groupinfo.creator if groupinfo else None
    my_id = conv.group_my_identity if conv.group_id_hex else None

    participants: List[NormalizedParticipant] = []
    seen_ids: set[str] = set()

    for pk in member_pks:
        contact = contacts.get(pk)
        display = contact.display_name() if contact else f"Contact#{pk}"
        identity = contact.identity if contact else None
        role = "member"
        if my_id and identity == my_id:
            role = "me"
        if creator_id and identity == creator_id:
            role = "admin"
        participant_id = (
            f"threema-id:{identity}"
            if identity
            else f"threema-contact:{pk}"
        )
        participants.append(
            NormalizedParticipant(
                participant_id=participant_id,
                display_name=display,
                identity=identity,
                role=role,
                metadata={
                    "contact_pk": pk,
                    "created_at": format_dt(
                        contact.createdat_raw if contact else None,
                        time_mode,
                        tz_name,
                        1900,
                    ),
                    "verification_level": contact.verificationlevel if contact else None,
                    "state": contact.state if contact else None,
                },
            )
        )
        seen_ids.add(identity or participant_id)

    if not conv.group_id_hex and conv.contact_pk and int(conv.contact_pk) in contacts:
        contact = contacts[int(conv.contact_pk)]
        participant_id = (
            f"threema-id:{contact.identity}"
            if contact.identity
            else f"threema-contact:{contact.pk}"
        )
        if participant_id not in seen_ids:
            participants.append(
                NormalizedParticipant(
                    participant_id=participant_id,
                    display_name=contact.display_name(),
                    identity=contact.identity,
                    role="chat_partner",
                    metadata={
                        "contact_pk": contact.pk,
                        "verification_level": contact.verificationlevel,
                        "state": contact.state,
                    },
                )
            )
            seen_ids.add(participant_id)

    if creator_id and creator_id not in seen_ids:
        participants.append(
            NormalizedParticipant(
                participant_id=f"threema-id:{creator_id}",
                display_name=creator_id,
                identity=creator_id,
                role="admin",
                metadata={},
            )
        )
        seen_ids.add(creator_id)

    if my_id and my_id not in seen_ids:
        participants.append(
            NormalizedParticipant(
                participant_id=f"threema-id:{my_id}",
                display_name=my_id,
                identity=my_id,
                role="me",
                metadata={},
            )
        )

    return participants


def normalize_threema_conversation(
    conv: Conversation,
    contacts: Dict[int, Contact],
    groupinfo: Optional[GroupInfo],
    member_pks: List[int],
    messages: List[Message],
    media_index: Dict[int, List[Dict[str, Any]]],
    reactions_by_message: Dict[int, List[Dict[str, Any]]],
    history_by_message: Dict[int, List[Dict[str, Any]]],
    time_mode: str,
    tz_name: str,
) -> NormalizedConversation:
    chat_title = build_conversation_title(conv, contacts)
    zid_index = build_zid_index(messages)
    participants = build_participants(
        conv,
        contacts,
        groupinfo,
        member_pks,
        time_mode,
        tz_name,
    )

    normalized_messages: List[NormalizedMessage] = []
    for message in messages:
        attachments = [
            normalize_attachment(message.pk, index, item)
            for index, item in enumerate(media_index.get(message.pk, []), start=1)
        ]
        reactions = normalize_reactions(
            reactions_by_message.get(message.pk, []),
            contacts,
            time_mode,
            tz_name,
        )
        edits = normalize_edits(history_by_message.get(message.pk, []), time_mode, tz_name)
        text_codepoints = normalize_for_pdf(message.text or "")[1] if message.text else []
        caption_codepoints = (
            normalize_for_pdf(message.caption or "")[1] if message.caption else []
        )
        normalized_messages.append(
            NormalizedMessage(
                message_id=f"threema-message:{message.pk}",
                timestamp=format_dt(message.date_raw, time_mode, tz_name, 1900),
                sender_id=determine_sender_id(message, conv, contacts),
                sender_display=determine_sender_display(message, conv, contacts),
                direction=build_direction(message),
                message_type=message_type_from_ent(message.ent),
                text=message.text,
                caption=message.caption,
                quoted_message_ref=(
                    f"threema-zid:{message.quoted_message_id.hex()}"
                    if message.quoted_message_id
                    else None
                ),
                quoted_preview=build_quote_preview(
                    message,
                    zid_index,
                    time_mode,
                    tz_name,
                    conv,
                    contacts,
                ),
                status=build_status(message),
                attachments=attachments,
                reactions=reactions,
                edits=edits,
                metadata={
                    "threema_message_pk": message.pk,
                    "ent": message.ent,
                    "filename": message.filename,
                    "mimetype": message.mimetype,
                    "json": message.json,
                    "zid_prefix": blob_prefix_hex(message.zid),
                    "quoted_message_id_prefix": blob_prefix_hex(message.quoted_message_id),
                    "zflags": message.zflags,
                    "zorigin": message.zorigin,
                    "ztype": message.ztype,
                    "delivery_timestamp": format_dt(
                        message.deliverydate_raw,
                        time_mode,
                        tz_name,
                        1900,
                    ),
                    "read_timestamp": format_dt(message.readdate_raw, time_mode, tz_name, 1900),
                    "remote_sent_timestamp": format_dt(
                        message.remotesentdate_raw,
                        time_mode,
                        tz_name,
                        1900,
                    ),
                    "last_edited_timestamp": format_dt(
                        message.lasteditedat_raw,
                        time_mode,
                        tz_name,
                        1900,
                    ),
                    "deleted_timestamp": format_dt(
                        message.deletedat_raw,
                        time_mode,
                        tz_name,
                        1900,
                    ),
                    "text_codepoints": text_codepoints,
                    "caption_codepoints": caption_codepoints,
                },
            )
        )

    return NormalizedConversation(
        source_app="threema",
        conversation_id=f"threema-conversation:{conv.pk}",
        title=chat_title,
        conversation_type="group" if conv.group_id_hex else "direct" if conv.contact_pk else "unknown",
        participants=participants,
        messages=normalized_messages,
        timezone=tz_name,
        time_mode=time_mode,
        metadata={
            "threema_conversation_pk": conv.pk,
            "category": conv.category,
            "contact_pk": conv.contact_pk,
            "group_name": conv.group_name,
            "group_id_hex": conv.group_id_hex,
            "group_my_identity": conv.group_my_identity,
            "group_creator": groupinfo.creator if groupinfo else None,
            "group_state": groupinfo.state if groupinfo else None,
            "group_last_periodic_sync": format_dt(
                groupinfo.last_periodic_sync_raw if groupinfo else None,
                time_mode,
                tz_name,
                1900,
            ),
            "unread_count": conv.unread_count,
            "last_update": format_dt(conv.last_update_raw, time_mode, tz_name, 1900),
            "visibility": conv.visibility,
            "marked": conv.marked,
        },
    )
