"""Run importer-based export orchestration.

This module selects the configured importer, creates the output directory
structure, and writes one normal PDF plus one TECH PDF per imported
conversation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from .common.logging_setup import sanitize_local_paths
from .common.util import ensure_dir, safe_filename
from .config import ExportConfig
from .constants import SOURCE_APP_THREEMA, SOURCE_APP_WHATSAPP
from .export_summary import (
    EXPORT_SUMMARY_FILENAME,
    MANIFEST_FILENAME,
    utc_now,
    write_traceability_files,
)
from .importers.base import ConversationImporter, ImportedConversation
from .render.excel_builder import build_conversation_xlsx
from .render.pdf_builder import build_conversation_pdf, build_fallback_tech_pdf
from .threema.importer import ThreemaImporter
from .threema.tech_pdf import build_threema_tech_pdf
from .whatsapp.importer import WhatsAppImporter

log = logging.getLogger(__name__)


IMPORTERS: Dict[str, ConversationImporter] = {
    SOURCE_APP_THREEMA: ThreemaImporter(),
    SOURCE_APP_WHATSAPP: WhatsAppImporter(),
}


class _ExportLogCaptureHandler(logging.Handler):
    """Collect warning and error log records for the export manifest."""

    def __init__(self) -> None:
        """Initialize the capture handler."""
        super().__init__(level=logging.WARNING)
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Store one sanitized warning or error log record."""
        try:
            message = sanitize_local_paths(self.format(record))
            if record.levelno >= logging.ERROR:
                self.errors.append(message)
            else:
                self.warnings.append(message)
        except Exception:
            self.handleError(record)


def _unique_messages(messages: list[str]) -> list[str]:
    """Return unique messages while preserving their original order."""
    unique: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if not message or message in seen:
            continue
        unique.append(message)
        seen.add(message)
    return unique


def _derive_status(errors: list[str], warnings: list[str]) -> str:
    """Derive the final export status from collected errors and warnings."""
    if errors:
        return "Failed"
    if warnings:
        return "Completed with warnings"
    return "Completed"


def _apply_export_status(
    results: Dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> str:
    """Store the derived export status plus collected warnings/errors."""
    status = _derive_status(errors, warnings)
    results["status"] = status
    results["warnings"] = warnings
    results["errors"] = [sanitize_local_paths(error) for error in errors]
    return status


def _record_existing_traceability_paths(results: Dict[str, Any], out_dir: str) -> None:
    """Record traceability artifact paths that already exist on disk."""
    summary_path = os.path.join(out_dir, EXPORT_SUMMARY_FILENAME)
    manifest_path = os.path.join(out_dir, MANIFEST_FILENAME)
    if os.path.isfile(summary_path):
        results["export_summary_path"] = summary_path
    if os.path.isfile(manifest_path):
        results["manifest_path"] = manifest_path


def get_importer(source_app: str) -> ConversationImporter:
    """Resolve an importer for a source key.

    Args:
        source_app (str): Registered importer key.

    Returns:
        ConversationImporter: Importer instance for the source key.

    Raises:
        ValueError: If the source key is not registered.
    """
    try:
        return IMPORTERS[source_app]
    except KeyError as exc:
        raise ValueError(f"Unsupported source app: {source_app}") from exc


def _source_identifier(exported: ImportedConversation) -> str:
    """Build a filename-safe identifier for one conversation.

    Args:
        exported (ImportedConversation): Imported conversation bundle.

    Returns:
        str: Source primary key if available. Otherwise a sanitized
        conversation id.
    """
    source_pk = exported.conversation.metadata.get("threema_conversation_pk")
    if source_pk is not None:
        return str(source_pk)
    return safe_filename(exported.conversation.conversation_id, 32)


def _build_tech_pdf(exported: ImportedConversation, pdf_tech_path: str) -> None:
    """Write one TECH PDF file.

    Args:
        exported (ImportedConversation): Imported conversation bundle.
        pdf_tech_path (str): Output PDF file path.
    """
    if exported.tech_renderer == "threema" and exported.tech_payload is not None:
        build_threema_tech_pdf(exported.tech_payload, pdf_tech_path)
        return
    build_fallback_tech_pdf(exported.conversation, pdf_tech_path)


def export_all_conversations(cfg: ExportConfig) -> Dict[str, Any]:
    """Execute one export run.

    Args:
        cfg (ExportConfig): Export configuration.

    Returns:
        Dict[str, Any]: Run metadata and per-conversation output file paths.
    """
    started_at = utc_now()
    errors: list[str] = []
    warnings: list[str] = []
    root_logger = logging.getLogger()
    original_root_level = root_logger.level
    if original_root_level > logging.WARNING:
        root_logger.setLevel(logging.WARNING)
    capture_handler = _ExportLogCaptureHandler()
    root_logger.addHandler(capture_handler)
    out_dir = os.path.abspath(cfg.out_dir) if cfg.out_dir and cfg.out_dir.strip() else ""
    results: Dict[str, Any] = {
        "source_app": cfg.source_app,
        "out_dir": out_dir,
        "exported": [],
    }

    try:
        cfg.validate()
        input_path = cfg.resolved_input_path()
        log.info("Starting orchestration source=%s", cfg.source_app)

        conv_out = os.path.join(out_dir, "conversations")
        ensure_dir(conv_out)

        media_out = None
        if cfg.export_media:
            media_out = os.path.join(out_dir, "media")
            ensure_dir(media_out)

        excel_out = None
        if cfg.export_excel:
            excel_out = os.path.join(out_dir, "excel")
            ensure_dir(excel_out)

        if (
            cfg.source_app == SOURCE_APP_THREEMA
            and cfg.export_media
            and not cfg.external_folder
        ):
            log.warning("No external_folder specified; media export may be incomplete")

        log.debug(
            "Ensured output directories source=%s input=%s conversations=%s media=%s excel=%s",
            cfg.source_app,
            input_path,
            conv_out,
            media_out,
            excel_out,
        )

        importer = get_importer(cfg.source_app)
        log.info(
            "Selected importer source=%s importer=%s",
            cfg.source_app,
            importer.__class__.__name__,
        )
        import_run = importer.load_conversations(cfg)

        results.update(import_run.metadata)
        if import_run.conversations:
            first_conversation = import_run.conversations[0].conversation
            results.setdefault("time_mode", first_conversation.time_mode)
            results.setdefault("timezone", first_conversation.timezone)

        total_conversations = len(import_run.conversations)
        for index, exported in enumerate(import_run.conversations, start=1):
            participant_count = len(exported.conversation.participants)
            participant_ids = [
                participant.participant_id
                for participant in exported.conversation.participants
                if participant.participant_id
            ]
            attachment_count = sum(
                len(message.attachments) for message in exported.conversation.messages
            )
            log.info(
                "Rendering conversation source=%s index=%s/%s messages=%s",
                cfg.source_app,
                index,
                total_conversations,
                len(exported.conversation.messages),
            )
            if log.isEnabledFor(logging.DEBUG):
                log.debug(
                    "Rendering conversation details source=%s index=%s/%s conversation_id=%s title=%s participants=%s attachments=%s",
                    cfg.source_app,
                    index,
                    total_conversations,
                    exported.conversation.conversation_id,
                    exported.conversation.title,
                    participant_count,
                    attachment_count,
                )
            safe_title = safe_filename(exported.conversation.title)
            source_identifier = _source_identifier(exported)
            pdf_path = os.path.join(conv_out, f"conv_{source_identifier}_{safe_title}.pdf")
            pdf_tech_path = os.path.join(
                conv_out,
                f"conv_{source_identifier}_{safe_title}_TECH.pdf",
            )
            xlsx_path = (
                os.path.join(excel_out, f"conv_{source_identifier}_{safe_title}.xlsx")
                if excel_out
                else None
            )

            build_conversation_pdf(
                exported.conversation,
                pdf_path,
                include_image_previews=cfg.export_image_previews,
            )
            log.debug(
                "Rendered conversation PDF conversation_id=%s path=%s",
                exported.conversation.conversation_id,
                pdf_path,
            )
            _build_tech_pdf(exported, pdf_tech_path)
            log.debug(
                "Rendered TECH PDF conversation_id=%s path=%s renderer=%s",
                exported.conversation.conversation_id,
                pdf_tech_path,
                exported.tech_renderer or "fallback",
            )
            if xlsx_path:
                build_conversation_xlsx(exported.conversation, xlsx_path)
                log.debug(
                    "Rendered Excel workbook conversation_id=%s path=%s",
                    exported.conversation.conversation_id,
                    xlsx_path,
                )

            results["exported"].append(
                {
                    "conversation_id": exported.conversation.conversation_id,
                    "title": exported.conversation.title,
                    "conversation_type": exported.conversation.conversation_type,
                    "participant_count": participant_count,
                    "participant_ids": participant_ids,
                    "attachment_count": attachment_count,
                    "pdf_path": pdf_path,
                    "pdf_tech_path": pdf_tech_path,
                    "xlsx_path": xlsx_path,
                    "media_dir": exported.metadata.get("media_dir"),
                    "message_count": exported.metadata.get(
                        "message_count", len(exported.conversation.messages)
                    ),
                    "missing_media_count": exported.metadata.get(
                        "missing_media_count", 0
                    ),
                    "skipped_media_count": exported.metadata.get(
                        "skipped_media_count", 0
                    ),
                    "unparseable_message_count": exported.metadata.get(
                        "unparseable_message_count", 0
                    ),
                }
            )

            log.info(
                "Exported conversation source=%s index=%s/%s",
                cfg.source_app,
                index,
                total_conversations,
            )

        log.info(
            "Completed orchestration source=%s exported=%s",
            cfg.source_app,
            len(results["exported"]),
        )
        log.debug("Completed orchestration output_dir=%s", out_dir)
        return results
    except Exception as exc:
        errors.append(str(exc) or exc.__class__.__name__)
        raise
    finally:
        finished_at = utc_now()
        root_logger.removeHandler(capture_handler)
        root_logger.setLevel(original_root_level)
        warnings = _unique_messages(warnings + capture_handler.warnings)
        errors = _unique_messages(errors + capture_handler.errors)
        status = _apply_export_status(results, errors, warnings)
        if out_dir:
            try:
                trace_paths = write_traceability_files(
                    cfg,
                    results=results,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=status,
                    errors=errors,
                    warnings=warnings,
                )
                results.update(trace_paths)
            except Exception as exc:
                _record_existing_traceability_paths(results, out_dir)
                traceability_error = sanitize_local_paths(
                    str(exc) or exc.__class__.__name__
                )
                errors = _unique_messages(
                    errors
                    + [f"Failed to write traceability files: {traceability_error}"]
                )
                status = _apply_export_status(results, errors, warnings)
                log.exception(
                    "Failed to write traceability files output_dir=%s",
                    out_dir,
                )
        else:
            log.error("Skipping traceability files because output directory is empty")
        log.info(
            "Resolved export status status=%s warnings=%s errors=%s",
            status,
            len(warnings),
            len(errors),
        )
