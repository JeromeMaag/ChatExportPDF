from __future__ import annotations

import json
import logging
import os
from io import BytesIO
from urllib.parse import quote

from importlib.metadata import PackageNotFoundError, version as pkg_version
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError

from ..common.textutil import esc_xml, normalize_for_pdf
from ..common.util import relpath_for_link
from ..normalized.models import NormalizedConversation, NormalizedMessage
from .pdf_styles import build_styles

log = logging.getLogger(__name__)

IMAGE_PREVIEW_MAX_WIDTH = 85 * mm
IMAGE_PREVIEW_MAX_HEIGHT = 60 * mm
IMAGE_PREVIEW_DPI = 144
CHAT_BUBBLE_MAX_WIDTH = 118 * mm
CHAT_SYSTEM_MAX_WIDTH = 94 * mm
CHAT_BUBBLE_LEFT_BG = colors.HexColor("#F1F1F1")
CHAT_BUBBLE_RIGHT_BG = colors.HexColor("#DCF8C6")
CHAT_SYSTEM_BG = colors.HexColor("#E9E9E9")


def exporter_version() -> str:
    try:
        return pkg_version("chat-export-pdf")
    except PackageNotFoundError:
        return "dev"
    except Exception:
        return "unknown"


def _metadata_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _is_large_metadata_value(value: str) -> bool:
    return len(value) > 600 or value.count("\n") > 12


def _chunk_metadata_value(value: str, chunk_size: int = 900) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    current = ""
    for line in normalized.split("\n"):
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = line
            continue
        start = 0
        while start < len(line):
            chunks.append(line[start : start + chunk_size])
            start += chunk_size
        current = ""
    if current:
        chunks.append(current)
    return chunks or [normalized]


def _right_side_participant_id(
    conversation: NormalizedConversation,
) -> Optional[str]:
    if conversation.self_participant_id:
        return conversation.self_participant_id
    if conversation.conversation_type != "direct":
        return None
    for message in conversation.messages:
        if message.sender_id and message.message_type != "system":
            return message.sender_id
    if len(conversation.participants) == 2:
        return conversation.participants[0].participant_id
    return None


def _conversation_date_range(conversation: NormalizedConversation) -> tuple[str, str]:
    timestamps = [
        message.timestamp for message in conversation.messages if message.timestamp
    ]
    if not timestamps:
        return ("NULL", "NULL")
    return (timestamps[0], timestamps[-1])


def _case_summary(conversation: NormalizedConversation) -> dict[str, int]:
    counts = {
        "messages": len(conversation.messages),
        "system": 0,
        "text": 0,
        "image": 0,
        "audio": 0,
        "video": 0,
        "file": 0,
    }

    for message in conversation.messages:
        if message.message_type == "system":
            counts["system"] += 1
        if message.message_type == "text":
            counts["text"] += 1
        for attachment in message.attachments:
            if attachment.absolute_path and attachment.kind in counts:
                counts[attachment.kind] += 1

    return counts


def _image_preview_pixel_bounds() -> tuple[int, int]:
    max_width_px = int((IMAGE_PREVIEW_MAX_WIDTH / 72.0) * IMAGE_PREVIEW_DPI)
    max_height_px = int((IMAGE_PREVIEW_MAX_HEIGHT / 72.0) * IMAGE_PREVIEW_DPI)
    return max_width_px, max_height_px


def _build_image_preview_flowable(image_path: str) -> RLImage:
    max_width_px, max_height_px = _image_preview_pixel_bounds()
    with PILImage.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        original_width, original_height = image.size
        if original_width <= 0 or original_height <= 0:
            raise ValueError("image has invalid dimensions")

        image.thumbnail((max_width_px, max_height_px), PILImage.Resampling.LANCZOS)
        preview_width_px, preview_height_px = image.size
        if preview_width_px <= 0 or preview_height_px <= 0:
            raise ValueError("thumbnail generation produced invalid dimensions")

        display_width = preview_width_px * 72.0 / IMAGE_PREVIEW_DPI
        display_height = preview_height_px * 72.0 / IMAGE_PREVIEW_DPI
        if (
            display_width > IMAGE_PREVIEW_MAX_WIDTH
            or display_height > IMAGE_PREVIEW_MAX_HEIGHT
        ):
            display_scale = min(
                IMAGE_PREVIEW_MAX_WIDTH / display_width,
                IMAGE_PREVIEW_MAX_HEIGHT / display_height,
            )
            display_width *= display_scale
            display_height *= display_scale

        preview_buffer = BytesIO()
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            image.save(preview_buffer, format="PNG")
        else:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(preview_buffer, format="JPEG", quality=85, optimize=True)
        preview_buffer.seek(0)

    preview = RLImage(preview_buffer, width=display_width, height=display_height)
    preview.hAlign = "LEFT"
    return preview


def _build_doc(
    conversation: NormalizedConversation,
    pdf_path: str,
    *,
    include_metadata_dump: bool,
    include_image_previews: bool,
) -> None:
    styles = build_styles()
    normal = styles["normal"]
    h1 = styles["h1"]
    h2 = styles["h2"]
    h3 = styles["h3"]
    mono = styles["mono"]
    bubble_header = ParagraphStyle(
        "bubble_header",
        parent=normal,
        fontSize=8.0,
        leading=9.5,
        textColor=colors.HexColor("#666666"),
        spaceAfter=1,
    )
    bubble_body = ParagraphStyle(
        "bubble_body",
        parent=normal,
        fontSize=9.2,
        leading=11.8,
    )
    bubble_aux = ParagraphStyle(
        "bubble_aux",
        parent=normal,
        fontSize=8.0,
        leading=9.5,
        textColor=colors.HexColor("#555555"),
    )
    system_style = ParagraphStyle(
        "system_message",
        parent=normal,
        fontSize=8.2,
        leading=10.0,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
    )

    start_dt, end_dt = _conversation_date_range(conversation)
    counts = _case_summary(conversation)
    right_side_id = _right_side_participant_id(conversation)

    def p(text: str, style=normal):
        return Paragraph(text.replace("\n", "<br/>"), style)

    def link(label: str, rel_path: str, style=normal):
        rel_path = rel_path.replace("\\", "/")
        href = quote(rel_path)
        return Paragraph(
            f'{esc_xml(label)}: <a href="{href}">{esc_xml(rel_path)}</a>',
            style,
        )

    def rel(target_abs: str) -> str:
        return relpath_for_link(target_abs, pdf_path)

    def _message_chunks(text: str, *, chunk_size: int = 450) -> list[str]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parts: list[str] = []
        for paragraph in normalized.split("\n"):
            if not paragraph:
                parts.append("")
                continue
            for chunk in _chunk_metadata_value(paragraph, chunk_size=chunk_size):
                parts.append(chunk)
        return parts or [normalized]

    def kv_table(rows: list[tuple[str, str]], *, col_widths=None, font_size=7.0):
        data = [[p("<b>Field</b>"), p("<b>Value</b>")]] + [
            [
                p(esc_xml(key)),
                p(esc_xml(value), mono if include_metadata_dump else normal),
            ]
            for key, value in rows
        ]
        table = Table(data, colWidths=col_widths or [45 * mm, 130 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ]
            )
        )
        return table

    def participant_table():
        data = [[p("<b>Role</b>"), p("<b>Display</b>"), p("<b>Identity</b>")]]
        for participant in conversation.participants:
            data.append(
                [
                    p(esc_xml(participant.role)),
                    p(esc_xml(participant.display_name)),
                    p(esc_xml(participant.identity or "NULL")),
                ]
            )

        table = Table(data, colWidths=[35 * mm, 65 * mm, 70 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def attachment_index_table():
        data = [
            [
                p("<b>Time</b>"),
                p("<b>Sender</b>"),
                p("<b>Type</b>"),
                p("<b>Filename</b>"),
                p("<b>Path</b>"),
                p("<b>SHA256</b>"),
            ]
        ]

        for message in conversation.messages:
            for attachment in message.attachments:
                if not attachment.absolute_path:
                    continue
                filename = attachment.filename or os.path.basename(
                    attachment.absolute_path
                )
                data.append(
                    [
                        p(esc_xml(message.timestamp or "NULL")),
                        p(esc_xml(message.sender_display)),
                        p(esc_xml(attachment.kind)),
                        p(esc_xml(filename)),
                        link("open", rel(attachment.absolute_path), normal),
                        p(esc_xml(attachment.sha256 or "NULL"), mono),
                    ]
                )

        table = Table(
            data,
            colWidths=[32 * mm, 25 * mm, 15 * mm, 40 * mm, 60 * mm, 40 * mm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return table

    def metadata_rows(title: str, metadata: dict[str, object]):
        if not metadata:
            return [p(f"{esc_xml(title)}: <i>no metadata</i>", normal)]
        story_parts: list[object] = [p(esc_xml(title), h3)]
        compact_rows: list[tuple[str, str]] = []

        for key in sorted(metadata):
            value = _metadata_value(metadata[key])
            if _is_large_metadata_value(value):
                if compact_rows:
                    story_parts.append(kv_table(compact_rows))
                    compact_rows = []
                story_parts.append(p(f"<b>{esc_xml(key)}</b>", normal))
                for chunk in _chunk_metadata_value(value):
                    story_parts.append(p(esc_xml(chunk), mono))
                story_parts.append(Spacer(1, 4))
            else:
                compact_rows.append((key, value))

        if compact_rows:
            story_parts.append(kv_table(compact_rows))

        return story_parts

    def append_message_linear(story: list[object], message: NormalizedMessage):
        label = f"<b>{esc_xml(message.timestamp or 'NULL')}</b> - <b>{esc_xml(message.sender_display)}</b>"
        tail = f" <font color='#666666'>({esc_xml(message.message_type)}, {esc_xml(message.status or 'unknown')})</font>"
        story.append(p(label + tail, normal))

        if message.quoted_preview:
            quoted, _ = normalize_for_pdf(message.quoted_preview)
            story.append(p(f"<font color='#444444'>{esc_xml(quoted)}</font>", normal))

        if message.text:
            text_norm, _ = normalize_for_pdf(message.text)
            story.append(p(esc_xml(text_norm).replace("\n", "<br/>"), normal))

        if message.caption:
            caption_norm, _ = normalize_for_pdf(message.caption)
            story.append(p(f"<i>Caption:</i> {esc_xml(caption_norm)}", normal))

        for attachment in message.attachments:
            if not attachment.absolute_path:
                continue
            filename = attachment.filename or os.path.basename(attachment.absolute_path)
            story.append(
                link(
                    f"Attachment ({attachment.kind}) [{filename}]",
                    rel(attachment.absolute_path),
                    normal,
                )
            )
            if (
                include_image_previews
                and attachment.kind == "image"
                and attachment.absolute_path
            ):
                try:
                    story.append(_build_image_preview_flowable(attachment.absolute_path))
                    story.append(Spacer(1, 6))
                except (
                    FileNotFoundError,
                    OSError,
                    UnidentifiedImageError,
                    ValueError,
                    PILImage.DecompressionBombError,
                ) as exc:
                    log.warning(
                        "Image preview failed for %s in conversation=%s message=%s: %s",
                        attachment.absolute_path,
                        conversation.conversation_id,
                        message.message_id,
                        exc,
                    )
            if include_metadata_dump:
                attachment_rows = [
                    ("attachment_id", attachment.attachment_id),
                    ("mime_type", attachment.mime_type or "NULL"),
                    ("size", _metadata_value(attachment.size)),
                    ("sha256", attachment.sha256 or "NULL"),
                ]
                attachment_rows.extend(
                    (f"meta.{key}", _metadata_value(value))
                    for key, value in sorted(attachment.metadata.items())
                )
                story.append(kv_table(attachment_rows, font_size=6.6))

        if message.reactions:
            parts = [
                f"{reaction.reaction} by {reaction.creator_display}"
                for reaction in message.reactions[:20]
            ]
            suffix = (
                ""
                if len(message.reactions) <= 20
                else f" ...(+{len(message.reactions) - 20})"
            )
            story.append(p("Reactions: " + esc_xml(", ".join(parts) + suffix), normal))

        if message.edits:
            story.append(p(f"Edited: yes ({len(message.edits)}x)", normal))
            if include_metadata_dump:
                for edit in message.edits:
                    edit_text, _ = normalize_for_pdf(edit.text or "")
                    story.append(
                        p(
                            esc_xml(f"{edit.timestamp or 'NULL'} - {edit_text[:200]}"),
                            mono,
                        )
                    )

        if include_metadata_dump and message.metadata:
            story.extend(metadata_rows("Message metadata", message.metadata))

        story.append(Spacer(1, 10))

    def _bubble_table(
        rows: list[list[object]],
        *,
        h_align: str,
        background: colors.Color,
        max_width: float = CHAT_BUBBLE_MAX_WIDTH,
    ) -> Table:
        bubble = Table(rows, colWidths=[max_width], hAlign=h_align)
        bubble.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), background),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return bubble

    def _aligned_block(flowable: object, *, alignment: str) -> Table:
        if alignment == "right":
            data = [["", flowable]]
        else:
            data = [[flowable, ""]]
        block = Table(data, colWidths=[56 * mm, 118 * mm])
        block.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return block

    def _message_alignment(message: NormalizedMessage) -> str:
        if message.message_type == "system":
            return "center"
        if right_side_id and message.sender_id == right_side_id:
            return "right"
        return "left"

    def append_message_bubble(story: list[object], message: NormalizedMessage):
        alignment = _message_alignment(message)
        attachment_links: list[object] = []

        if alignment == "center":
            system_bits: list[str] = []
            if message.timestamp:
                system_bits.append(message.timestamp)
            if message.text:
                text_norm, _ = normalize_for_pdf(message.text)
                system_bits.append(text_norm)
            elif message.caption:
                caption_norm, _ = normalize_for_pdf(message.caption)
                system_bits.append(caption_norm)
            elif message.sender_display and message.sender_display != "System":
                system_bits.append(message.sender_display)
            body = " - ".join(bit for bit in system_bits if bit) or "System event"
            story.append(
                _bubble_table(
                    [[p(esc_xml(body), system_style)]],
                    h_align="CENTER",
                    background=CHAT_SYSTEM_BG,
                    max_width=CHAT_SYSTEM_MAX_WIDTH,
                )
            )
            story.append(Spacer(1, 8))
            return

        bubble_rows: list[list[object]] = []
        if conversation.conversation_type == "group":
            header_bits = [f"<b>{esc_xml(message.sender_display)}</b>"]
            if message.timestamp:
                header_bits.append(esc_xml(message.timestamp))
            bubble_rows.append([p(" - ".join(header_bits), bubble_header)])
        elif message.timestamp:
            bubble_rows.append([p(esc_xml(message.timestamp), bubble_header)])

        if message.quoted_preview:
            quoted, _ = normalize_for_pdf(message.quoted_preview)
            for chunk in _message_chunks(quoted, chunk_size=260):
                bubble_rows.append([p(esc_xml(chunk).replace("\n", "<br/>"), bubble_aux)])

        if message.text:
            text_norm, _ = normalize_for_pdf(message.text)
            for chunk in _message_chunks(text_norm):
                bubble_rows.append([p(esc_xml(chunk).replace("\n", "<br/>"), bubble_body)])

        if message.caption:
            caption_norm, _ = normalize_for_pdf(message.caption)
            for chunk in _message_chunks(f"Caption: {caption_norm}", chunk_size=320):
                bubble_rows.append([p(f"<i>{esc_xml(chunk).replace('\n', '<br/>')}</i>", bubble_aux)])

        for attachment in message.attachments:
            filename = attachment.filename or (
                os.path.basename(attachment.absolute_path)
                if attachment.absolute_path
                else "attachment"
            )
            if (
                include_image_previews
                and attachment.kind == "image"
                and attachment.absolute_path
            ):
                try:
                    bubble_rows.append([_build_image_preview_flowable(attachment.absolute_path)])
                except (
                    FileNotFoundError,
                    OSError,
                    UnidentifiedImageError,
                    ValueError,
                    PILImage.DecompressionBombError,
                ) as exc:
                    log.warning(
                        "Image preview failed for %s in conversation=%s message=%s: %s",
                        attachment.absolute_path,
                        conversation.conversation_id,
                        message.message_id,
                        exc,
                    )
            if attachment.absolute_path:
                attachment_links.append(
                    link(
                        f"Attachment ({attachment.kind}) [{filename}]",
                        rel(attachment.absolute_path),
                        bubble_aux,
                    )
                )

        if message.reactions:
            parts = [
                f"{reaction.reaction} by {reaction.creator_display}"
                for reaction in message.reactions[:20]
            ]
            suffix = (
                ""
                if len(message.reactions) <= 20
                else f" ...(+{len(message.reactions) - 20})"
            )
            bubble_rows.append(
                [p("Reactions: " + esc_xml(", ".join(parts) + suffix), bubble_aux)]
            )

        if message.edits:
            bubble_rows.append([p(f"Edited: yes ({len(message.edits)}x)", bubble_aux)])

        if not bubble_rows:
            bubble_rows.append([p("<i>Empty message</i>", bubble_aux)])

        story.append(
            _aligned_block(
                _bubble_table(
                    bubble_rows,
                    h_align="RIGHT" if alignment == "right" else "LEFT",
                    background=CHAT_BUBBLE_RIGHT_BG if alignment == "right" else CHAT_BUBBLE_LEFT_BG,
                ),
                alignment=alignment,
            )
        )
        for attachment_link in attachment_links:
            story.append(_aligned_block(attachment_link, alignment=alignment))
        story.append(Spacer(1, 8))

    story: list[object] = []
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    conversation_rows = [
        ("SourceApp", conversation.source_app),
        ("ConversationID", conversation.conversation_id),
        ("ChatType", conversation.conversation_type),
        ("DateRange", f"{start_dt} -> {end_dt}"),
        ("Messages", str(counts["messages"])),
        ("SystemEvents", str(counts["system"])),
        (
            "Attachments",
            f"Images={counts['image']}, Audio={counts['audio']}, Video={counts['video']}, Files={counts['file']}",
        ),
        ("Timezone", conversation.timezone),
        ("TimeMode", conversation.time_mode),
    ]

    story.append(p(f"ChatExportPDF - {esc_xml(conversation.title)}", h1))
    story.append(
        p(
            f"<font color='#666666'>Exporter: ChatExportPDF v{esc_xml(exporter_version())}</font>",
            normal,
        )
    )
    story.append(Spacer(1, 6))
    story.append(kv_table(conversation_rows, font_size=8))
    story.append(Spacer(1, 10))

    story.append(p("Participants", h2))
    story.append(Spacer(1, 6))
    story.append(participant_table())

    if include_metadata_dump:
        for participant in conversation.participants:
            story.append(Spacer(1, 10))
            story.append(
                p(
                    f"<b>{esc_xml(participant.role)}</b> - <b>{esc_xml(participant.display_name)}</b> <font color='#666666'>({esc_xml(participant.identity or 'NULL')})</font>",
                    normal,
                )
            )
            story.extend(metadata_rows("Participant metadata", participant.metadata))

        story.append(Spacer(1, 10))
        story.extend(metadata_rows("Conversation metadata", conversation.metadata))

    story.append(PageBreak())
    story.append(p("Messages", h1))
    story.append(Spacer(1, 8))

    for message in conversation.messages:
        if include_metadata_dump:
            append_message_linear(story, message)
        else:
            append_message_bubble(story, message)

    story.append(PageBreak())
    story.append(p("Attachment Index", h1))
    story.append(Spacer(1, 8))
    story.append(attachment_index_table())

    log.debug(
        "Building generic PDF path=%s source=%s conv_id=%s tech=%s",
        pdf_path,
        conversation.source_app,
        conversation.conversation_id,
        include_metadata_dump,
    )
    doc.build(story)


def build_conversation_pdf(
    conversation: NormalizedConversation,
    pdf_path: str,
    *,
    include_image_previews: bool = True,
) -> None:
    _build_doc(
        conversation,
        pdf_path,
        include_metadata_dump=False,
        include_image_previews=include_image_previews,
    )


def build_fallback_tech_pdf(
    conversation: NormalizedConversation, pdf_path: str
) -> None:
    _build_doc(
        conversation,
        pdf_path,
        include_metadata_dump=True,
        include_image_previews=False,
    )
