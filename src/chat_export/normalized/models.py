"""Define importer-agnostic normalized export models.

This module contains the shared data structures used between importers and
renderers. Importers map source-specific data into these classes. Generic PDF
rendering only depends on this model layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class NormalizedAttachment:
    """Store one normalized attachment record.

    Attributes:
        attachment_id (str): Stable attachment identifier.
        kind (str): Generic attachment type. Example: ``image`` or ``file``.
        filename (Optional[str]): Source filename.
        absolute_path (Optional[str]): Absolute exported file path.
        relative_path (Optional[str]): Relative exported file path.
        mime_type (Optional[str]): MIME type string.
        size (Optional[int]): File size in bytes.
        sha256 (Optional[str]): File hash.
        metadata (dict[str, Any]): Importer-specific attachment metadata.
    """

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
    """Store one normalized reaction record.

    Attributes:
        creator_display (str): Display name of the reacting participant.
        reaction (str): Reaction payload. Example: emoji text.
        timestamp (Optional[str]): Render-ready reaction timestamp.
        metadata (dict[str, Any]): Importer-specific reaction metadata.
    """

    creator_display: str
    reaction: str
    timestamp: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedEdit:
    """Store one normalized edit history entry.

    Attributes:
        timestamp (Optional[str]): Render-ready edit timestamp.
        text (Optional[str]): Edited text snapshot.
        metadata (dict[str, Any]): Importer-specific edit metadata.
    """

    timestamp: Optional[str]
    text: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedParticipant:
    """Store one normalized participant record.

    Attributes:
        participant_id (str): Stable participant identifier.
        display_name (str): Render display name.
        identity (Optional[str]): Source identity or address.
        role (str): Generic role. Example: ``me`` or ``member``.
        metadata (dict[str, Any]): Importer-specific participant metadata.
    """

    participant_id: str
    display_name: str
    identity: Optional[str]
    role: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedMessage:
    """Store one normalized message record.

    Attributes:
        message_id (str): Stable message identifier.
        timestamp (Optional[str]): Render-ready message timestamp.
        sender_id (Optional[str]): Sender participant identifier.
        sender_display (str): Render sender display name.
        direction (str): Generic direction label.
        message_type (str): Generic message type. Example: ``text`` or ``system``.
        text (Optional[str]): Main message text.
        caption (Optional[str]): Attachment caption text.
        quoted_message_ref (Optional[str]): Quoted message identifier.
        quoted_preview (Optional[str]): Short quoted text preview.
        status (Optional[str]): Delivery or state label.
        attachments (list[NormalizedAttachment]): Normalized attachments.
        reactions (list[NormalizedReaction]): Normalized reactions.
        edits (list[NormalizedEdit]): Edit history entries.
        metadata (dict[str, Any]): Importer-specific message metadata.
    """

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
    """Store one normalized conversation record.

    Attributes:
        source_app (str): Importer key of the source application.
        conversation_id (str): Stable conversation identifier.
        title (str): Render title.
        conversation_type (str): Generic type. Example: ``direct`` or ``group``.
        participants (list[NormalizedParticipant]): Conversation participants.
        messages (list[NormalizedMessage]): Conversation messages.
        timezone (str): IANA timezone name used for rendering.
        time_mode (str): Source timestamp mode label.
        self_participant_id (Optional[str]): Participant id rendered on the right side.
        metadata (dict[str, Any]): Importer-specific conversation metadata.
    """

    source_app: str
    conversation_id: str
    title: str
    conversation_type: str
    participants: list[NormalizedParticipant]
    messages: list[NormalizedMessage]
    timezone: str
    time_mode: str
    self_participant_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
