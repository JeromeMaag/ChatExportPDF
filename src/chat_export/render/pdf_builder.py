"""Build generic PDF exports from normalized conversations.

This module renders the normal conversation PDF and the fallback TECH PDF. It
operates on normalized models only and does not depend on source-specific
database objects.
"""

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
from ..normalized.models import (
    NormalizedAttachment,
    NormalizedConversation,
    NormalizedMessage,
)
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
IMAGE_PREVIEW_EXCEPTIONS = (
    FileNotFoundError,
    OSError,
    UnidentifiedImageError,
    ValueError,
    PILImage.DecompressionBombError,
)


def exporter_version() -> str:
    """Return the installed exporter package version.

    Returns:
        str: Installed package version, ``dev`` for editable local runs, or
        ``unknown`` on unexpected lookup errors.
    """
    try:
        return pkg_version("chat-export-pdf")
    except PackageNotFoundError:
        return "dev"
    except Exception:
        return "unknown"


def _metadata_value(value: object) -> str:
    """Convert one metadata value to printable text.

    Args:
        value (object): Metadata value.

    Returns:
        str: Scalar string, JSON string, or ``repr`` fallback.
    """
    if value is None:
        return "NULL"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def _is_large_metadata_value(value: str) -> bool:
    """Check whether a metadata value should be split into blocks.

    Args:
        value (str): Serialized metadata value.

    Returns:
        bool: ``True`` if the value is large enough for chunked rendering.
    """
    return len(value) > 600 or value.count("\n") > 12


def _chunk_metadata_value(value: str, chunk_size: int = 900) -> list[str]:
    """Split long metadata text into render-sized chunks.

    Args:
        value (str): Serialized metadata value.
        chunk_size (int): Maximum chunk size in characters.

    Returns:
        list[str]: Chunked metadata text.
    """
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
    """Resolve the participant rendered on the right side.

    Args:
        conversation (NormalizedConversation): Normalized conversation.

    Returns:
        Optional[str]: Right-side participant id. ``None`` if no right-side
        participant can be resolved.
    """
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
    """Extract the first and last non-empty message timestamp.

    Args:
        conversation (NormalizedConversation): Normalized conversation.

    Returns:
        tuple[str, str]: Start and end timestamps. ``NULL`` placeholders if no
        timestamps are present.
    """
    timestamps = [
        message.timestamp for message in conversation.messages if message.timestamp
    ]
    if not timestamps:
        return ("NULL", "NULL")
    return (timestamps[0], timestamps[-1])


def _case_summary(conversation: NormalizedConversation) -> dict[str, int]:
    """Compute aggregate message and attachment counts.

    Args:
        conversation (NormalizedConversation): Normalized conversation.

    Returns:
        dict[str, int]: Summary counts keyed by message or attachment type.
    """
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
    """Convert preview size limits from points to pixels.

    Returns:
        tuple[int, int]: Maximum preview width and height in pixels.
    """
    max_width_px = int((IMAGE_PREVIEW_MAX_WIDTH / 72.0) * IMAGE_PREVIEW_DPI)
    max_height_px = int((IMAGE_PREVIEW_MAX_HEIGHT / 72.0) * IMAGE_PREVIEW_DPI)
    return max_width_px, max_height_px


def _build_image_preview_flowable(image_path: str) -> RLImage:
    """Build one ReportLab image preview flowable.

    Args:
        image_path (str): Absolute image file path.

    Returns:
        RLImage: Sized image flowable for inline PDF rendering.

    Raises:
        FileNotFoundError: If the input file is missing.
        OSError: If the file cannot be decoded.
        ValueError: If the source or thumbnail has invalid dimensions.
        PILImage.DecompressionBombError: If Pillow rejects the image size.
    """
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
    """Build one generic PDF document.

    Args:
        conversation (NormalizedConversation): Normalized conversation.
        pdf_path (str): Output PDF file path.
        include_metadata_dump (bool): Enable fallback TECH-style metadata output.
        include_image_previews (bool): Enable inline image previews.
    """
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
        """Build one paragraph flowable.

        Args:
            text (str): Paragraph text with newline support.
            style: ReportLab paragraph style.

        Returns:
            Paragraph: Paragraph flowable.
        """
        return Paragraph(text.replace("\n", "<br/>"), style)

    def link(label: str, rel_path: str, style=normal):
        """Build one clickable relative-path link paragraph.

        Args:
            label (str): Visible link label.
            rel_path (str): Relative file path from the PDF output.
            style: ReportLab paragraph style.

        Returns:
            Paragraph: Link paragraph flowable.
        """
        rel_path = rel_path.replace("\\", "/")
        href = quote(rel_path)
        return Paragraph(
            f'{esc_xml(label)}: <a href="{href}">{esc_xml(rel_path)}</a>',
            style,
        )

    def rel(target_abs: str) -> str:
        """Build a PDF-relative file link path.

        Args:
            target_abs (str): Absolute target file path.

        Returns:
            str: Relative path from the PDF file.
        """
        return relpath_for_link(target_abs, pdf_path)

    def _message_chunks(text: str, *, chunk_size: int = 450) -> list[str]:
        """Split long message text into render-sized chunks.

        Args:
            text (str): Message text.
            chunk_size (int): Maximum chunk size in characters.

        Returns:
            list[str]: Chunked message text.
        """
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parts: list[str] = []
        for paragraph in normalized.split("\n"):
            if not paragraph:
                parts.append("")
                continue
            for chunk in _chunk_metadata_value(paragraph, chunk_size=chunk_size):
                parts.append(chunk)
        return parts or [normalized]

    def _attachment_filename(attachment: NormalizedAttachment) -> str:
        """Resolve one display filename for an attachment.

        Args:
            attachment (NormalizedAttachment): Normalized attachment.

        Returns:
            str: Attachment filename or fallback label.
        """
        if attachment.filename:
            return attachment.filename
        if attachment.absolute_path:
            return os.path.basename(attachment.absolute_path)
        return "attachment"

    def _attachment_link(
        attachment: NormalizedAttachment,
        *,
        style=normal,
    ) -> Paragraph | None:
        """Build one attachment link paragraph.

        Args:
            attachment (NormalizedAttachment): Normalized attachment.
            style: ReportLab paragraph style.

        Returns:
            Paragraph | None: Link paragraph if the attachment has a file path.
        """
        if not attachment.absolute_path:
            return None
        return link(
            f"Attachment ({attachment.kind}) [{_attachment_filename(attachment)}]",
            rel(attachment.absolute_path),
            style,
        )

    def _image_preview_or_none(
        message: NormalizedMessage,
        attachment: NormalizedAttachment,
    ) -> RLImage | None:
        """Build one image preview if preview rendering is enabled.

        Args:
            message (NormalizedMessage): Parent message.
            attachment (NormalizedAttachment): Normalized attachment.

        Returns:
            RLImage | None: Image preview flowable or ``None``.
        """
        if not (
            include_image_previews
            and attachment.kind == "image"
            and attachment.absolute_path
        ):
            return None
        try:
            return _build_image_preview_flowable(attachment.absolute_path)
        except IMAGE_PREVIEW_EXCEPTIONS as exc:
            log.warning(
                "Image preview failed for %s in conversation=%s message=%s: %s",
                attachment.absolute_path,
                conversation.conversation_id,
                message.message_id,
                exc,
            )
            return None

    def _reaction_summary(message: NormalizedMessage) -> str | None:
        """Build a compact reaction summary string.

        Args:
            message (NormalizedMessage): Normalized message.

        Returns:
            str | None: Reaction summary text or ``None``.
        """
        if not message.reactions:
            return None
        parts = [
            f"{reaction.reaction} by {reaction.creator_display}"
            for reaction in message.reactions[:20]
        ]
        suffix = (
            ""
            if len(message.reactions) <= 20
            else f" ...(+{len(message.reactions) - 20})"
        )
        return ", ".join(parts) + suffix

    def kv_table(rows: list[tuple[str, str]], *, col_widths=None, font_size=7.0):
        """Build a two-column key-value table.

        Args:
            rows (list[tuple[str, str]]): Table rows without header.
            col_widths: Optional ReportLab column widths.
            font_size (float): Table font size.

        Returns:
            Table: Styled key-value table.
        """
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
        """Build the participant overview table.

        Returns:
            Table: Participant table.
        """
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
        """Build the attachment index table.

        Returns:
            Table: Attachment index table.
        """
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
        """Build flowables for one metadata section.

        Args:
            title (str): Section title.
            metadata (dict[str, object]): Metadata mapping.

        Returns:
            list[object]: Flowables for the metadata section.
        """
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
        """Append one message in fallback TECH layout.

        Args:
            story (list[object]): Output story list.
            message (NormalizedMessage): Normalized message.
        """
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
            attachment_link = _attachment_link(attachment, style=normal)
            if attachment_link is None:
                continue
            story.append(attachment_link)
            preview = _image_preview_or_none(message, attachment)
            if preview is not None:
                story.append(preview)
                story.append(Spacer(1, 6))
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

        reaction_summary = _reaction_summary(message)
        if reaction_summary:
            story.append(p("Reactions: " + esc_xml(reaction_summary), normal))

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
        """Build one chat bubble table.

        Args:
            rows (list[list[object]]): Bubble row flowables.
            h_align (str): ReportLab horizontal alignment.
            background (colors.Color): Bubble background color.
            max_width (float): Maximum bubble width in points.

        Returns:
            Table: Styled bubble table.
        """
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
        """Wrap one flowable in a left or right aligned block.

        Args:
            flowable (object): ReportLab flowable.
            alignment (str): ``left`` or ``right``.

        Returns:
            Table: Alignment wrapper table.
        """
        if alignment == "right":
            data = [["", flowable]]
            col_widths = [56 * mm, 118 * mm]
        else:
            data = [[flowable, ""]]
            col_widths = [118 * mm, 56 * mm]
        block = Table(data, colWidths=col_widths)
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
        """Resolve bubble alignment for one message.

        Args:
            message (NormalizedMessage): Normalized message.

        Returns:
            str: ``left``, ``right``, or ``center``.
        """
        if message.message_type == "system":
            return "center"
        if right_side_id and message.sender_id == right_side_id:
            return "right"
        return "left"

    def append_message_bubble(story: list[object], message: NormalizedMessage):
        """Append one message in normal chat bubble layout.

        Args:
            story (list[object]): Output story list.
            message (NormalizedMessage): Normalized message.
        """
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
        header_bits = [f"<b>{esc_xml(message.sender_display)}</b>"]
        if message.timestamp:
            header_bits.append(esc_xml(message.timestamp))
        bubble_rows.append([p(" - ".join(header_bits), bubble_header)])
        bubble_rows.append(
            [
                p(
                    f"Type: {esc_xml(message.message_type)} | Status: {esc_xml(message.status or 'unknown')}",
                    bubble_aux,
                )
            ]
        )

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
            preview = _image_preview_or_none(message, attachment)
            if preview is not None:
                bubble_rows.append([preview])
            attachment_link = _attachment_link(attachment, style=bubble_aux)
            if attachment_link is not None:
                attachment_links.append(attachment_link)

        reaction_summary = _reaction_summary(message)
        if reaction_summary:
            bubble_rows.append([p("Reactions: " + esc_xml(reaction_summary), bubble_aux)])

        if message.edits:
            bubble_rows.append([p(f"Edited: yes ({len(message.edits)}x)", bubble_aux)])

        if not bubble_rows:
            bubble_rows.append([p("<i>Empty message</i>", bubble_aux)])

        story.append(
            _bubble_table(
                bubble_rows,
                h_align="RIGHT" if alignment == "right" else "LEFT",
                background=CHAT_BUBBLE_RIGHT_BG if alignment == "right" else CHAT_BUBBLE_LEFT_BG,
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
    """Write the normal conversation PDF.

    Args:
        conversation (NormalizedConversation): Normalized conversation.
        pdf_path (str): Output PDF file path.
        include_image_previews (bool): Enable inline image previews.
    """
    _build_doc(
        conversation,
        pdf_path,
        include_metadata_dump=False,
        include_image_previews=include_image_previews,
    )


def build_fallback_tech_pdf(
    conversation: NormalizedConversation, pdf_path: str
) -> None:
    """Write the generic fallback TECH PDF.

    Args:
        conversation (NormalizedConversation): Normalized conversation.
        pdf_path (str): Output PDF file path.
    """
    _build_doc(
        conversation,
        pdf_path,
        include_metadata_dump=True,
        include_image_previews=False,
    )
