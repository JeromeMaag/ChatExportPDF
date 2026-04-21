"""Build Excel exports from normalized conversations.

This module writes optional `.xlsx` workbooks from the importer-agnostic
normalized conversation model. It does not depend on source-specific importer
objects.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Iterable

import xlsxwriter

from .. import __version__
from ..normalized.models import (
    NormalizedAttachment,
    NormalizedConversation,
    NormalizedMessage,
)

log = logging.getLogger(__name__)

MAX_CELL_TEXT = 32767
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
RENDERED_TZ_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) [A-Z]{2,6}$")
RENDERED_TZ_ANY_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) [A-Z]{2,6}")


def _strip_rendered_timezones(value: str) -> str:
    """Remove rendered timezone abbreviations from timestamp strings."""
    return RENDERED_TZ_ANY_RE.sub(r"\1", value)


def _excel_timestamp(value: str | None) -> datetime | str:
    """Convert rendered timestamps to Excel datetime values without timezone text."""
    if not value or value == "NULL":
        return ""
    parts = value.split()
    if len(parts) < 2:
        return value
    try:
        return datetime.strptime(" ".join(parts[:2]), TIMESTAMP_FORMAT)
    except ValueError:
        return value


def _cell_value(value: object) -> object:
    """Convert one value to an Excel-safe scalar."""
    if value is None:
        return ""
    if isinstance(value, (datetime, int, float, bool)):
        return value
    text = _strip_rendered_timezones(str(value))
    if len(text) > MAX_CELL_TEXT:
        return text[: MAX_CELL_TEXT - 15] + "...[truncated]"
    return text


def _sanitize_metadata(value: object) -> object:
    """Remove local absolute paths from nested metadata before writing Excel."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text.endswith("_path_abs") or key_text == "absolute_path":
                continue
            sanitized[key] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        match = RENDERED_TZ_RE.match(value)
        if match:
            return match.group(1)
    return value


def _json_value(value: object) -> str:
    """Serialize nested metadata into a bounded JSON string."""
    try:
        text = json.dumps(
            _sanitize_metadata(value or {}),
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
    except Exception:
        text = repr(value)
    return str(_cell_value(text))


def _join(values: Iterable[object]) -> str:
    """Join non-empty values into a readable string."""
    return "; ".join(str(value) for value in values if value not in (None, ""))


def _attachment_filename(attachment: NormalizedAttachment) -> str:
    """Resolve one attachment display filename."""
    if attachment.filename:
        return attachment.filename
    if attachment.absolute_path:
        return os.path.basename(attachment.absolute_path)
    return attachment.attachment_id


def _attachment_count_by_kind(conversation: NormalizedConversation) -> dict[str, int]:
    """Count attachments by normalized attachment kind."""
    counts: dict[str, int] = {}
    for message in conversation.messages:
        for attachment in message.attachments:
            counts[attachment.kind] = counts.get(attachment.kind, 0) + 1
    return counts


def _safe_table_name(prefix: str, conversation: NormalizedConversation) -> str:
    """Build an Excel table name from a prefix and conversation id."""
    raw = f"{prefix}_{conversation.conversation_id}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
    if not safe or safe[0].isdigit():
        safe = f"T_{safe}"
    return safe[:240]


def _add_table(
    worksheet,
    table_name: str,
    headers: list[str],
    rows: list[list[object]],
) -> bool:
    """Add a worksheet table around headers and rows."""
    if not headers or not rows:
        return False
    last_row = max(0, len(rows))
    last_col = len(headers) - 1
    columns = [{"header": header} for header in headers]
    worksheet.add_table(
        0,
        0,
        last_row,
        last_col,
        {
            "name": table_name,
            "columns": columns,
            "style": "Table Style Medium 2",
        },
    )
    return True


def _write_sheet(
    workbook,
    worksheet,
    table_name: str,
    headers: list[str],
    rows: list[list[object]],
    *,
    wrap_columns: set[int] | None = None,
    widths: dict[int, int] | None = None,
    datetime_columns: set[int] | None = None,
) -> None:
    """Write one formatted table worksheet."""
    wrap_columns = wrap_columns or set()
    datetime_columns = datetime_columns or set()
    widths = widths or {}
    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "white",
            "bg_color": "#1F4E78",
            "border": 1,
        }
    )
    text_format = workbook.add_format({"valign": "top"})
    wrap_format = workbook.add_format({"valign": "top", "text_wrap": True})
    datetime_format = workbook.add_format(
        {"valign": "top", "num_format": "dd.mm.yyyy hh:mm:ss"}
    )

    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    for row_index, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            if col in datetime_columns:
                fmt = datetime_format
            elif col in wrap_columns:
                fmt = wrap_format
            else:
                fmt = text_format
            worksheet.write(row_index, col, _cell_value(value), fmt)

    has_table = _add_table(worksheet, table_name, headers, rows)
    worksheet.freeze_panes(1, 0)
    if not has_table:
        worksheet.autofilter(0, 0, max(len(rows), 1), len(headers) - 1)

    for col in range(len(headers)):
        width = widths.get(col)
        if width is None:
            samples = [headers[col]] + [
                str(row[col]) for row in rows[:200] if col < len(row)
            ]
            width = min(
                max(max((len(sample) for sample in samples), default=10) + 2, 10), 55
            )
        worksheet.set_column(col, col, width)
    worksheet.set_row(0, 20)


def _overview_rows(conversation: NormalizedConversation) -> list[list[object]]:
    """Build overview rows with aggregate counts."""
    attachment_counts = _attachment_count_by_kind(conversation)
    message_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    reaction_count = 0
    edit_count = 0
    for message in conversation.messages:
        message_counts[message.message_type] = (
            message_counts.get(message.message_type, 0) + 1
        )
        direction_counts[message.direction] = (
            direction_counts.get(message.direction, 0) + 1
        )
        reaction_count += len(message.reactions)
        edit_count += len(message.edits)

    rows = [
        ["Exporter version", __version__],
        ["Source app", conversation.source_app],
        ["Conversation ID", conversation.conversation_id],
        ["Title", conversation.title],
        ["Conversation type", conversation.conversation_type],
        ["Timezone", conversation.timezone],
        ["Time mode", conversation.time_mode],
        ["Participants", len(conversation.participants)],
        ["Messages", len(conversation.messages)],
        ["Attachments", sum(attachment_counts.values())],
        ["Reactions", reaction_count],
        ["Edits", edit_count],
    ]
    for kind in sorted(message_counts):
        rows.append([f"Messages: {kind}", message_counts[kind]])
    for direction in sorted(direction_counts):
        rows.append([f"Directions: {direction}", direction_counts[direction]])
    for kind in sorted(attachment_counts):
        rows.append([f"Attachments: {kind}", attachment_counts[kind]])
    rows.append(["Conversation metadata", _json_value(conversation.metadata)])
    return rows


def _participants_rows(conversation: NormalizedConversation) -> list[list[object]]:
    """Build participant rows."""
    return [
        [
            participant.participant_id,
            participant.display_name,
            participant.identity,
            participant.role,
            _json_value(participant.metadata),
        ]
        for participant in conversation.participants
    ]


def _message_rows(conversation: NormalizedConversation) -> list[list[object]]:
    """Build message rows."""
    rows: list[list[object]] = []
    for index, message in enumerate(conversation.messages, start=1):

        def _json_timestamp(value: str | None) -> str:
            timestamp = _excel_timestamp(value)
            if isinstance(timestamp, datetime):
                return timestamp.isoformat(sep=" ")
            return str(timestamp)

        reactions_json = _json_value(
            [
                {
                    "creator_display": reaction.creator_display,
                    "reaction": reaction.reaction,
                    "timestamp": _json_timestamp(reaction.timestamp),
                    "metadata": reaction.metadata,
                }
                for reaction in message.reactions
            ]
        )
        edits_json = _json_value(
            [
                {
                    "timestamp": _json_timestamp(edit.timestamp),
                    "text": edit.text,
                    "metadata": edit.metadata,
                }
                for edit in message.edits
            ]
        )
        rows.append(
            [
                index,
                _excel_timestamp(message.timestamp),
                message.sender_display,
                message.text,
                message.direction,
                message.sender_id,
                message.message_id,
                message.message_type,
                message.status,
                message.caption,
                message.quoted_message_ref,
                message.quoted_preview,
                len(message.attachments),
                _join(
                    _attachment_filename(attachment)
                    for attachment in message.attachments
                ),
                len(message.reactions),
                _join(
                    f"{reaction.reaction} by {reaction.creator_display}"
                    for reaction in message.reactions
                ),
                reactions_json,
                len(message.edits),
                edits_json,
                _json_value(message.metadata),
            ]
        )
    return rows


def _attachment_rows(conversation: NormalizedConversation) -> list[list[object]]:
    """Build attachment rows."""
    rows: list[list[object]] = []
    for message in conversation.messages:
        for index, attachment in enumerate(message.attachments, start=1):
            rows.append(
                [
                    attachment.attachment_id,
                    message.message_id,
                    index,
                    _excel_timestamp(message.timestamp),
                    message.sender_display,
                    attachment.kind,
                    attachment.filename,
                    attachment.relative_path,
                    attachment.mime_type,
                    attachment.size,
                    attachment.sha256,
                    _json_value(attachment.metadata),
                ]
            )
    return rows


def build_conversation_xlsx(
    conversation: NormalizedConversation,
    xlsx_path: str,
) -> None:
    """Write one Excel workbook for a normalized conversation.

    Args:
        conversation (NormalizedConversation): Normalized conversation.
        xlsx_path (str): Output workbook path.
    """
    log.info(
        "Rendering Excel workbook conversation_id=%s", conversation.conversation_id
    )
    os.makedirs(os.path.dirname(os.path.abspath(xlsx_path)), exist_ok=True)
    workbook = xlsxwriter.Workbook(
        xlsx_path,
        {
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    workbook.set_properties(
        {
            "title": f"ChatExportPDF - {conversation.title}",
            "subject": "Chat export",
            "author": "ChatExportPDF",
            "comments": f"Exported by ChatExportPDF {__version__}",
        }
    )

    try:
        overview = workbook.add_worksheet("Overview")
        participants = workbook.add_worksheet("Participants")
        messages = workbook.add_worksheet("Messages")
        attachments = workbook.add_worksheet("Attachments")

        _write_sheet(
            workbook,
            overview,
            _safe_table_name("Overview", conversation),
            ["Metric", "Value"],
            _overview_rows(conversation),
            wrap_columns={1},
            widths={0: 28, 1: 80},
        )
        _write_sheet(
            workbook,
            participants,
            _safe_table_name("Participants", conversation),
            ["Participant ID", "Display name", "Identity", "Role", "Metadata JSON"],
            _participants_rows(conversation),
            wrap_columns={4},
            widths={0: 35, 1: 26, 2: 24, 3: 16, 4: 80},
        )
        _write_sheet(
            workbook,
            messages,
            _safe_table_name("Messages", conversation),
            [
                "Index",
                "Timestamp",
                "Sender",
                "Text",
                "Direction",
                "Sender ID",
                "Message ID",
                "Message type",
                "Status",
                "Caption",
                "Quoted message ref",
                "Quoted preview",
                "Attachment count",
                "Attachment filenames",
                "Reaction count",
                "Reactions",
                "Reactions JSON",
                "Edit count",
                "Edits JSON",
                "Metadata JSON",
            ],
            _message_rows(conversation),
            wrap_columns={3, 9, 11, 13, 15, 16, 18, 19},
            datetime_columns={1},
            widths={
                0: 10,
                1: 22,
                2: 24,
                3: 55,
                4: 16,
                5: 28,
                6: 28,
                9: 35,
                11: 45,
                13: 35,
                15: 35,
                16: 55,
                18: 55,
                19: 80,
            },
        )
        attachment_rows = _attachment_rows(conversation)
        _write_sheet(
            workbook,
            attachments,
            _safe_table_name("Attachments", conversation),
            [
                "Attachment ID",
                "Message ID",
                "Attachment index",
                "Timestamp",
                "Sender",
                "Kind",
                "Filename",
                "Relative path",
                "MIME type",
                "Size bytes",
                "SHA256",
                "Metadata JSON",
            ],
            attachment_rows,
            wrap_columns={7, 11},
            datetime_columns={3},
            widths={0: 32, 1: 28, 3: 22, 4: 24, 6: 35, 7: 45, 10: 66, 11: 80},
        )
    finally:
        workbook.close()

    log.info("Rendered Excel workbook path=%s", xlsx_path)
