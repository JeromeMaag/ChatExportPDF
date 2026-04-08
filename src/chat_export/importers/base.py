from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..normalized.models import NormalizedConversation

if TYPE_CHECKING:
    from ..config import ExportConfig


@dataclass(slots=True)
class ImportedConversation:
    conversation: NormalizedConversation
    tech_payload: Any = None
    tech_renderer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportRun:
    source_app: str
    conversations: list[ImportedConversation]
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationImporter(Protocol):
    source_app: str

    def load_conversations(self, cfg: "ExportConfig") -> ImportRun:
        ...
