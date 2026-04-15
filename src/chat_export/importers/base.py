"""Define shared importer contracts and result containers.

This module contains the protocol used by the orchestrator to call importers
and the result dataclasses returned by importer implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from ..normalized.models import NormalizedConversation

if TYPE_CHECKING:
    from ..config import ExportConfig


@dataclass(slots=True)
class ImportedConversation:
    """Store one imported conversation bundle.

    Attributes:
        conversation (NormalizedConversation): Normalized conversation data.
        tech_payload (Any): Importer-specific TECH payload.
        tech_renderer (str | None): TECH renderer key.
        metadata (dict[str, Any]): Importer-side metadata for the run result.
    """

    conversation: NormalizedConversation
    tech_payload: Any = None
    tech_renderer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportRun:
    """Store one importer execution result.

    Attributes:
        source_app (str): Importer key.
        conversations (list[ImportedConversation]): Imported conversations.
        metadata (dict[str, Any]): Run-level importer metadata.
    """

    source_app: str
    conversations: list[ImportedConversation]
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationImporter(Protocol):
    """Define the importer interface used by the orchestrator."""

    source_app: str

    def load_conversations(self, cfg: "ExportConfig") -> ImportRun:
        """Load and normalize source conversations.

        Args:
            cfg (ExportConfig): Export configuration.

        Returns:
            ImportRun: Import result with normalized conversations.
        """
        ...
