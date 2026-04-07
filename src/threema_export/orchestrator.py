from __future__ import annotations

import logging
import os
from typing import Any, Dict

from .config import ExportConfig
from .importers.base import ConversationImporter, ImportedConversation
from .render.pdf_builder import build_conversation_pdf, build_fallback_tech_pdf
from .threema.importer import ThreemaImporter
from .threema.tech_pdf import build_threema_tech_pdf
from .util import ensure_dir, safe_filename

log = logging.getLogger(__name__)


IMPORTERS: Dict[str, ConversationImporter] = {
    "threema": ThreemaImporter(),
}


def get_importer(source_app: str) -> ConversationImporter:
    try:
        return IMPORTERS[source_app]
    except KeyError as exc:
        raise ValueError(f"Unsupported source app: {source_app}") from exc


def _source_identifier(exported: ImportedConversation) -> str:
    source_pk = exported.conversation.metadata.get("threema_conversation_pk")
    if source_pk is not None:
        return str(source_pk)
    return safe_filename(exported.conversation.conversation_id, 32)


def _build_tech_pdf(exported: ImportedConversation, pdf_tech_path: str) -> None:
    if exported.tech_renderer == "threema" and exported.tech_payload is not None:
        build_threema_tech_pdf(exported.tech_payload, pdf_tech_path)
        return
    build_fallback_tech_pdf(exported.conversation, pdf_tech_path)


def export_all_conversations(cfg: ExportConfig) -> Dict[str, Any]:
    cfg.validate()

    out_dir = os.path.abspath(cfg.out_dir)
    conv_out = os.path.join(out_dir, "conversations")
    ensure_dir(conv_out)

    if cfg.export_media:
        ensure_dir(os.path.join(out_dir, "media"))

    importer = get_importer(cfg.source_app)
    import_run = importer.load_conversations(cfg)

    results: Dict[str, Any] = {
        "source_app": cfg.source_app,
        "out_dir": out_dir,
        "exported": [],
    }
    results.update(import_run.metadata)

    for exported in import_run.conversations:
        safe_title = safe_filename(exported.conversation.title)
        source_identifier = _source_identifier(exported)
        pdf_path = os.path.join(conv_out, f"conv_{source_identifier}_{safe_title}.pdf")
        pdf_tech_path = os.path.join(
            conv_out,
            f"conv_{source_identifier}_{safe_title}_TECH.pdf",
        )

        build_conversation_pdf(exported.conversation, pdf_path)
        _build_tech_pdf(exported, pdf_tech_path)

        results["exported"].append(
            {
                "conversation_id": exported.conversation.conversation_id,
                "title": exported.conversation.title,
                "pdf_path": pdf_path,
                "pdf_tech_path": pdf_tech_path,
                "media_dir": exported.metadata.get("media_dir"),
                "message_count": exported.metadata.get("message_count", len(exported.conversation.messages)),
            }
        )

        log.info(
            "Exported source=%s conversation_id=%s title=%s",
            cfg.source_app,
            exported.conversation.conversation_id,
            exported.conversation.title,
        )

    return results
