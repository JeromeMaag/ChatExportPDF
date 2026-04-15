"""Normalize WhatsApp ZIP exports into shared export models.

This module parses WhatsApp text exports into intermediate message records and
maps them plus extracted media into the normalized conversation model used by
the generic renderers.
"""

from __future__ import annotations

import mimetypes
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..common.util import safe_filename
from ..normalized.models import (
    NormalizedAttachment,
    NormalizedConversation,
    NormalizedMessage,
    NormalizedParticipant,
)
from .zip_reader import WhatsAppZipExport

PLAIN_MESSAGE_RE = re.compile(
    r"^\u200e?(?P<date>\d{2}\.\d{2}\.\d{2}), (?P<time>\d{2}:\d{2}(?::\d{2})?) - (?P<body>.*)$"
)
BRACKETED_MESSAGE_RE = re.compile(
    r"^\u200e?\[(?P<date>\d{2}\.\d{2}\.\d{2}), (?P<time>\d{2}:\d{2}(?::\d{2})?)\] (?P<body>.*)$"
)
PLAIN_ATTACHMENT_RE = re.compile(r"^(?P<filename>.+?) \((?P<label>[^)]+angehängt)\)$")
BRACKETED_ATTACHMENT_RE = re.compile(
    r"^(?P<label>.*?)\s*\u200e?<Anhang: (?P<filename>[^>]+)>$"
)


@dataclass(slots=True)
class ParsedWhatsAppMessage:
    """Store one parsed WhatsApp text-export message.

    Attributes:
        timestamp (str): Render-ready message timestamp.
        sender (Optional[str]): Parsed sender display name.
        text (str): Parsed message text without attachment marker syntax.
        raw_text (str): Original raw text line block.
        attachment_name (Optional[str]): Attachment filename from the export text.
        metadata (dict[str, object]): Parser metadata.
    """

    timestamp: str
    sender: Optional[str]
    text: str
    raw_text: str
    attachment_name: Optional[str]
    metadata: dict[str, object] = field(default_factory=dict)


def _normalize_title(raw_stem: str) -> str:
    """Normalize a WhatsApp ZIP filename stem to a chat title.

    Args:
        raw_stem (str): ZIP filename stem.

    Returns:
        str: Normalized chat title.
    """
    if raw_stem.startswith("WhatsApp-Chat mit "):
        return raw_stem.removeprefix("WhatsApp-Chat mit ").strip()
    if raw_stem.startswith("WhatsApp Chat - "):
        return raw_stem.removeprefix("WhatsApp Chat - ").strip()
    return raw_stem.strip()


def _parse_timestamp(date_part: str, time_part: str, tz_name: str) -> str:
    """Parse a WhatsApp export timestamp string.

    Args:
        date_part (str): Date string in export format.
        time_part (str): Time string in export format.
        tz_name (str): IANA timezone name.

    Returns:
        str: Render-ready timestamp string.
    """
    fmt = "%d.%m.%y, %H:%M:%S" if len(time_part) == 8 else "%d.%m.%y, %H:%M"
    dt = datetime.strptime(f"{date_part}, {time_part}", fmt)
    dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def _match_message_start(raw_line: str):
    """Match one export line against supported WhatsApp message prefixes.

    Args:
        raw_line (str): Raw chat-export line.

    Returns:
        re.Match[str] | None: Regex match object or ``None``.
    """
    for pattern in (BRACKETED_MESSAGE_RE, PLAIN_MESSAGE_RE):
        match = pattern.match(raw_line)
        if match:
            return match
    return None


def _extract_attachment(text: str) -> tuple[str, Optional[str], Optional[str]]:
    """Extract attachment data from one WhatsApp message body.

    Args:
        text (str): Parsed message body.

    Returns:
        tuple[str, Optional[str], Optional[str]]: Cleaned text, attachment
        filename, and attachment label.
    """
    text = text.lstrip("\u200e").strip()
    bracketed_match = BRACKETED_ATTACHMENT_RE.match(text)
    if bracketed_match:
        label = bracketed_match.group("label").strip().lstrip("\u200e").strip()
        return label, bracketed_match.group("filename").strip(), "Anhang"

    plain_match = PLAIN_ATTACHMENT_RE.match(text)
    if plain_match:
        return (
            "",
            plain_match.group("filename").strip(),
            plain_match.group("label").strip(),
        )

    return text, None, None


def parse_chat_messages(chat_text: str, tz_name: str) -> list[ParsedWhatsAppMessage]:
    """Parse a WhatsApp chat text file into intermediate message records.

    Args:
        chat_text (str): Full chat-export text.
        tz_name (str): IANA timezone name.

    Returns:
        list[ParsedWhatsAppMessage]: Parsed messages in source order.
    """
    messages: list[ParsedWhatsAppMessage] = []
    current: ParsedWhatsAppMessage | None = None

    for raw_line in chat_text.splitlines():
        match = _match_message_start(raw_line)
        if not match:
            if current is not None:
                current.text = (
                    f"{current.text}\n{raw_line}" if current.text else raw_line
                )
                current.raw_text = f"{current.raw_text}\n{raw_line}"
            continue

        body = match.group("body")
        sender: Optional[str] = None
        text = body
        if ": " in body:
            sender, text = body.split(": ", 1)

        text, attachment_name, attachment_label = _extract_attachment(text)

        current = ParsedWhatsAppMessage(
            timestamp=_parse_timestamp(
                match.group("date"), match.group("time"), tz_name
            ),
            sender=sender.strip() if sender else None,
            text=text,
            raw_text=raw_line,
            attachment_name=attachment_name,
            metadata={
                "raw_date": match.group("date"),
                "raw_time": match.group("time"),
                "attachment_label": attachment_label,
            },
        )
        messages.append(current)

    return messages


def _infer_conversation_type(
    title: str,
    senders: list[str],
) -> tuple[str, Optional[str], Optional[str]]:
    """Infer conversation type and role candidates from sender names.

    Args:
        title (str): Normalized chat title.
        senders (list[str]): Sender display names from parsed messages.

    Returns:
        tuple[str, Optional[str], Optional[str]]: Conversation type, direct-chat
        partner name, and self sender name.
    """
    unique_senders = [sender for sender in sorted(set(senders)) if sender]
    partner = next((sender for sender in unique_senders if sender == title), None)
    if len(unique_senders) == 2:
        me = next((sender for sender in unique_senders if sender != partner), None)
        return ("direct", partner, me if partner else None)
    return ("group" if len(unique_senders) > 2 else "unknown", partner, None)


def _participant_id_for_sender(sender: str) -> str:
    """Build a normalized participant id for one sender name.

    Args:
        sender (str): Sender display name.

    Returns:
        str: Normalized participant id.
    """
    return f"whatsapp-participant:{safe_filename(sender, 60)}"


def _build_participants(
    senders: list[str],
    conversation_type: str,
    chat_partner: Optional[str],
    me_sender: Optional[str],
) -> list[NormalizedParticipant]:
    """Build normalized participants from parsed sender names.

    Args:
        senders (list[str]): Sender display names.
        conversation_type (str): Inferred conversation type.
        chat_partner (Optional[str]): Direct-chat partner name.
        me_sender (Optional[str]): Inferred self sender name.

    Returns:
        list[NormalizedParticipant]: Normalized participants.
    """
    participants: list[NormalizedParticipant] = []
    for sender in sorted(set(senders)):
        role = "member"
        if sender == me_sender:
            role = "me"
        elif sender == chat_partner and conversation_type == "direct":
            role = "chat_partner"
        participants.append(
            NormalizedParticipant(
                participant_id=_participant_id_for_sender(sender),
                display_name=sender,
                identity=None,
                role=role,
                metadata={},
            )
        )
    return participants


def _guess_attachment_kind(filename: str) -> str:
    """Guess a normalized attachment type from a filename.

    Args:
        filename (str): Attachment filename.

    Returns:
        str: Attachment type label.
    """
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type.startswith("video/"):
            return "video"
    return "file"


def _normalized_message_text(message: ParsedWhatsAppMessage) -> Optional[str]:
    """Resolve normalized text content for one parsed message.

    Args:
        message (ParsedWhatsAppMessage): Parsed message.

    Returns:
        Optional[str]: Normalized message text or ``None``.
    """
    if not message.attachment_name:
        return message.text
    if not message.text:
        return None
    return message.text


def normalize_whatsapp_conversation(
    export: WhatsAppZipExport,
    parsed_messages: list[ParsedWhatsAppMessage],
    tz_name: str,
    media_lookup: dict[str, dict[str, object]],
) -> NormalizedConversation:
    """Convert one WhatsApp ZIP export to the normalized export model.

    Args:
        export (WhatsAppZipExport): ZIP-level export data.
        parsed_messages (list[ParsedWhatsAppMessage]): Parsed chat messages.
        tz_name (str): IANA timezone name.
        media_lookup (dict[str, dict[str, object]]): Extracted media records by filename.

    Returns:
        NormalizedConversation: Normalized conversation record.
    """
    title = _normalize_title(export.zip_path.stem)
    senders = [message.sender for message in parsed_messages if message.sender]
    conversation_type, chat_partner, me_sender = _infer_conversation_type(
        title, senders
    )
    participants = _build_participants(
        senders, conversation_type, chat_partner, me_sender
    )
    self_participant_id = (
        _participant_id_for_sender(me_sender) if me_sender else None
    )

    sender_counts = Counter(senders)
    normalized_messages: list[NormalizedMessage] = []
    for index, message in enumerate(parsed_messages, start=1):
        direction = "system"
        sender_display = "System"
        sender_id = None
        if message.sender:
            sender_display = message.sender
            sender_id = _participant_id_for_sender(message.sender)
            if me_sender and message.sender == me_sender:
                direction = "outgoing"
            elif me_sender:
                direction = "incoming"
            else:
                direction = "incoming"

        attachments = []
        if message.attachment_name:
            media = media_lookup.get(message.attachment_name, {})
            attachments.append(
                NormalizedAttachment(
                    attachment_id=f"whatsapp-attachment:{index}",
                    kind=_guess_attachment_kind(message.attachment_name),
                    filename=message.attachment_name,
                    absolute_path=media.get("absolute_path"),
                    relative_path=None,
                    mime_type=media.get("mime_type"),
                    size=media.get("size"),
                    sha256=media.get("sha256"),
                    metadata={
                        "zip_member_name": media.get("zip_member_name"),
                        "missing_from_zip": media.get("missing_from_zip", False),
                        "attachment_label": message.metadata.get("attachment_label"),
                    },
                )
            )

        message_type = "text"
        if attachments:
            message_type = attachments[0].kind
        elif message.sender is None:
            message_type = "system"

        normalized_messages.append(
            NormalizedMessage(
                message_id=f"whatsapp-message:{index}",
                timestamp=message.timestamp,
                sender_id=sender_id,
                sender_display=sender_display,
                direction=direction,
                message_type=message_type,
                text=_normalized_message_text(message),
                caption=None,
                quoted_message_ref=None,
                quoted_preview=None,
                status="unknown",
                attachments=attachments,
                reactions=[],
                edits=[],
                metadata={
                    "raw_text": message.raw_text,
                    "attachment_name": message.attachment_name,
                },
            )
        )

    return NormalizedConversation(
        source_app="whatsapp",
        conversation_id=f"whatsapp-conversation:{safe_filename(title, 80)}",
        title=title,
        conversation_type=conversation_type,
        participants=participants,
        messages=normalized_messages,
        timezone=tz_name,
        time_mode="whatsapp_text",
        self_participant_id=self_participant_id,
        metadata={
            "input_filename": export.zip_path.name,
            "chat_text_name": export.chat_text_name,
            "sender_counts": dict(sender_counts),
            "chat_partner": chat_partner,
            "me_sender": me_sender,
        },
    )
