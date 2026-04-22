"""Build validated export configuration objects from user-facing inputs.

This module contains shared conversion helpers used by multiple entry points.
It maps raw values from CLI or GUI layers into ``ExportConfig`` and centralizes
source-specific field rules.
"""

from __future__ import annotations

from typing import Optional

from .config import ExportConfig
from .constants import DEFAULT_TIMEZONE, SOURCE_APP_THREEMA
from .export_summary import default_log_file


def _optional_text(raw_value: Optional[str]) -> Optional[str]:
    """Return stripped optional text or ``None`` for empty values."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def parse_non_negative_int(raw_value: str, field_name: str) -> int:
    """Parse a non-negative integer field.

    Args:
        raw_value (str): Raw field value.
        field_name (str): Field name for error messages.

    Returns:
        int: Parsed integer value.

    Raises:
        ValueError: If the value is not a non-negative integer.
    """
    value = raw_value.strip() or "0"
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a non-negative integer."
        ) from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be 0 or a positive integer.")
    return parsed


def build_export_config(
    *,
    out_dir: str,
    source_app: str,
    input_path: Optional[str],
    db_path: Optional[str] = None,
    chat_text_name: Optional[str] = None,
    external_folder: Optional[str] = None,
    tz_name: Optional[str] = None,
    export_media: bool = True,
    export_image_previews: bool = True,
    export_excel: bool = False,
    max_media_bytes: int = 0,
    limit_conversations: int = 0,
    limit_messages: int = 0,
    log_level: str = "INFO",
    case_number: Optional[str] = None,
    examiner: Optional[str] = None,
    organization: Optional[str] = None,
    case_description: Optional[str] = None,
) -> ExportConfig:
    """Build one ``ExportConfig`` from normalized raw values.

    Args:
        out_dir (str): Output directory path.
        source_app (str): Importer key.
        input_path (Optional[str]): Generic source input path.
        db_path (Optional[str]): Explicit database path override.
        chat_text_name (Optional[str]): Explicit WhatsApp chat text file name.
        external_folder (Optional[str]): Optional Threema external folder path.
        tz_name (Optional[str]): Optional timezone override.
        export_media (bool): Enable media export.
        export_image_previews (bool): Enable inline image previews.
        export_excel (bool): Enable additional Excel workbook export.
        max_media_bytes (int): Maximum media size in bytes. ``0`` disables the limit.
        limit_conversations (int): Conversation limit. ``0`` disables the limit.
        limit_messages (int): Message limit per conversation. ``0`` disables the limit.
        log_level (str): Logging level name.
        case_number (Optional[str]): Optional case/reference number.
        examiner (Optional[str]): Optional examiner name or initials.
        organization (Optional[str]): Optional organization or unit.
        case_description (Optional[str]): Optional case notes or description.

    Returns:
        ExportConfig: Runtime export configuration.
    """
    effective_input_path = _optional_text(input_path)
    effective_source = source_app.strip()
    effective_chat_text_name = _optional_text(chat_text_name)
    effective_external_folder = _optional_text(external_folder)
    effective_log_level = log_level.strip() or "INFO"
    effective_tz_name = (tz_name or "").strip() or DEFAULT_TIMEZONE
    effective_db_path = _optional_text(db_path)

    if effective_source == SOURCE_APP_THREEMA and not effective_db_path:
        effective_db_path = effective_input_path

    if effective_source != SOURCE_APP_THREEMA:
        effective_external_folder = None
        effective_db_path = None
        if not effective_input_path:
            raise ValueError("input_path must not be empty for non-Threema sources.")

    effective_out_dir = out_dir.strip()
    if not effective_out_dir:
        raise ValueError("out_dir must not be empty or whitespace-only.")
    effective_log_file = default_log_file(effective_out_dir)

    return ExportConfig(
        out_dir=effective_out_dir,
        source_app=effective_source,
        input_path=effective_input_path,
        db_path=effective_db_path,
        chat_text_name=effective_chat_text_name,
        external_folder=effective_external_folder,
        tz_name=effective_tz_name,
        export_media=export_media,
        export_image_previews=export_image_previews,
        export_excel=export_excel,
        max_media_bytes=max_media_bytes,
        limit_conversations=limit_conversations,
        limit_messages=limit_messages,
        log_level=effective_log_level,
        log_file=effective_log_file,
        case_number=_optional_text(case_number),
        examiner=_optional_text(examiner),
        organization=_optional_text(organization),
        case_description=_optional_text(case_description),
    )
