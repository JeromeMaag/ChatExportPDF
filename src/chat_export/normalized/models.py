from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class NormalizedAttachment:
    attachment_id: str
    kind: str
    filename: Optional[str]
    absolute_path: Optional[str]
    relative_path: Optional[str]
    mime_type: Optional[str]
    size: Optional[int]
    sha256: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedReaction:
    creator_display: str
    reaction: str
    timestamp: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedEdit:
    timestamp: Optional[str]
    text: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedParticipant:
    participant_id: str
    display_name: str
    identity: Optional[str]
    role: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedMessage:
    message_id: str
    timestamp: Optional[str]
    sender_id: Optional[str]
    sender_display: str
    direction: str
    message_type: str
    text: Optional[str]
    caption: Optional[str]
    quoted_message_ref: Optional[str]
    quoted_preview: Optional[str]
    status: Optional[str]
    attachments: list[NormalizedAttachment] = field(default_factory=list)
    reactions: list[NormalizedReaction] = field(default_factory=list)
    edits: list[NormalizedEdit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedConversation:
    source_app: str
    conversation_id: str
    title: str
    conversation_type: str
    participants: list[NormalizedParticipant]
    messages: list[NormalizedMessage]
    timezone: str
    time_mode: str
    metadata: dict[str, Any] = field(default_factory=dict)
