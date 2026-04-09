"""Build the Threema-specific TECH PDF report.

This module renders the detailed Threema TECH report from importer-side models
and raw metadata. It is source-specific and independent from the generic PDF
builder used for normalized conversations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from importlib.metadata import PackageNotFoundError, version as pkg_version
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..common.textutil import esc_xml, normalize_for_pdf
from ..common.timeutil import format_dt
from ..common.util import blob_prefix_hex, relpath_for_link
from ..render.pdf_styles import build_styles
from .models import ENT_MAP, Contact, Conversation, GroupInfo, Message

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ThreemaTechnicalConversation:
    """Store Threema-specific TECH report input data.

    Attributes:
        conv (Conversation): Threema conversation model.
        chat_title (str): Render title.
        contacts (Dict[int, Contact]): Contacts indexed by primary key.
        groupinfo (Optional[GroupInfo]): Group metadata model.
        members (List[int]): Group member contact primary keys.
        messages (List[Message]): Conversation messages.
        media_index (Dict[int, List[Dict[str, Any]]]): Media export records by message primary key.
        reactions_by_message (Dict[int, List[Dict[str, Any]]]): Raw reactions by message primary key.
        history_by_message (Dict[int, List[Dict[str, Any]]]): Raw edit history by message primary key.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.
    """

    conv: Conversation
    chat_title: str
    contacts: Dict[int, Contact]
    groupinfo: Optional[GroupInfo]
    members: List[int]
    messages: List[Message]
    media_index: Dict[int, List[Dict[str, Any]]]
    reactions_by_message: Dict[int, List[Dict[str, Any]]]
    history_by_message: Dict[int, List[Dict[str, Any]]]
    time_mode: str
    tz_name: str


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


def conv_type(conv: Conversation) -> str:
    """Resolve a compact TECH conversation type label.

    Args:
        conv (Conversation): Threema conversation model.

    Returns:
        str: ``GROUP``, ``DIRECT``, or ``UNKNOWN``.
    """
    if conv.group_id_hex:
        return "GROUP"
    if conv.contact_pk:
        return "DIRECT"
    return "UNKNOWN"


def determine_sender(msg: Message, conv: Conversation, contacts: Dict[int, Contact]) -> str:
    """Resolve the sender display name for one Threema message.

    Args:
        msg (Message): Threema message model.
        conv (Conversation): Parent conversation model.
        contacts (Dict[int, Contact]): Contacts indexed by primary key.

    Returns:
        str: Sender display name or fallback label.
    """
    if msg.is_own == 1:
        return "Me"
    if msg.sender_pk is not None and int(msg.sender_pk) in contacts:
        return contacts[int(msg.sender_pk)].display_name()
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        return contacts[int(conv.contact_pk)].display_name()
    return "Unknown"


def conv_date_range(messages: List[Message], time_mode: str, tz_name: str) -> Tuple[str, str]:
    """Resolve the first and last message timestamps for a conversation.

    Args:
        messages (List[Message]): Conversation messages.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.

    Returns:
        Tuple[str, str]: Start and end timestamps.
    """
    if not messages:
        return ("NULL", "NULL")
    return (
        format_dt(messages[0].date_raw, time_mode, tz_name, 1900),
        format_dt(messages[-1].date_raw, time_mode, tz_name, 1900),
    )


def build_zid_index(messages: List[Message]) -> Dict[str, Message]:
    """Index Threema messages by ZID hex string.

    Args:
        messages (List[Message]): Conversation messages.

    Returns:
        Dict[str, Message]: Messages keyed by ZID hex string.
    """
    idx: Dict[str, Message] = {}
    for message in messages:
        if message.zid:
            idx[message.zid.hex()] = message
    return idx


def quote_summary(
    msg: Message,
    zid_index: Dict[str, Message],
    time_mode: str,
    tz_name: str,
    conv: Conversation,
    contacts: Dict[int, Contact],
) -> Optional[str]:
    """Build a short quoted-message summary string.

    Args:
        msg (Message): Threema message model.
        zid_index (Dict[str, Message]): Message index keyed by ZID hex string.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.
        conv (Conversation): Parent conversation model.
        contacts (Dict[int, Contact]): Contacts indexed by primary key.

    Returns:
        Optional[str]: Quoted summary text or ``None``.
    """
    if not msg.quoted_message_id:
        return None

    quoted_hex = msg.quoted_message_id.hex()
    ref = zid_index.get(quoted_hex)
    if not ref:
        return "Reply to: (unknown message)"

    sender = determine_sender(ref, conv, contacts)
    dt_s = format_dt(ref.date_raw, time_mode, tz_name, 1900)
    if ref.text:
        excerpt, _ = normalize_for_pdf(ref.text.strip().replace("\n", " "))
        excerpt = excerpt[:120] + "..." if len(excerpt) > 120 else excerpt
    else:
        excerpt = ENT_MAP.get(ref.ent, f"ENT_{ref.ent}")
    return f"Reply to: {sender} {dt_s} - {excerpt}"


def compute_case_summary(
    messages: List[Message],
    media_index: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, int]:
    """Compute aggregate message and attachment counts.

    Args:
        messages (List[Message]): Conversation messages.
        media_index (Dict[int, List[Dict[str, Any]]]): Media export records by message primary key.

    Returns:
        Dict[str, int]: Summary counts keyed by message or attachment type.
    """
    counts = {
        "messages": len(messages),
        "system": 0,
        "text": 0,
        "image": 0,
        "audio": 0,
        "video": 0,
        "file": 0,
    }

    for message in messages:
        kind = ENT_MAP.get(message.ent, "")
        if kind == "System":
            counts["system"] += 1
        if kind == "Text":
            counts["text"] += 1

    for items in media_index.values():
        for item in items:
            if not item.get("exported_path_abs"):
                continue
            kind = item.get("kind")
            if kind in counts:
                counts[kind] += 1

    return counts


def participant_rows(
    conv: Conversation,
    groupinfo: Optional[GroupInfo],
    contacts: Dict[int, Contact],
    member_pks: List[int],
) -> List[Dict[str, str]]:
    """Build participant rows for the TECH participant tables.

    Args:
        conv (Conversation): Threema conversation model.
        groupinfo (Optional[GroupInfo]): Group metadata model.
        contacts (Dict[int, Contact]): Contacts indexed by primary key.
        member_pks (List[int]): Group member contact primary keys.

    Returns:
        List[Dict[str, str]]: Participant rows with role, display, and identity.
    """
    creator_id = groupinfo.creator if groupinfo else None
    my_id = conv.group_my_identity if conv.group_id_hex else None

    rows: List[Dict[str, str]] = []
    seen_identities: set[str] = set()

    for pk in member_pks:
        contact = contacts.get(pk)
        display = contact.display_name() if contact else f"Contact#{pk}"
        identity = (contact.identity if contact else None) or "NULL"

        role = "Member"
        if my_id and identity == my_id:
            role = "Me"
        if creator_id and identity == creator_id:
            role = "Admin (Creator)"

        rows.append({"role": role, "display": display, "identity": identity})
        if identity != "NULL":
            seen_identities.add(identity)

    if not conv.group_id_hex and conv.contact_pk and int(conv.contact_pk) in contacts:
        contact = contacts[int(conv.contact_pk)]
        rows.append(
            {
                "role": "Chat partner",
                "display": contact.display_name(),
                "identity": contact.identity or "NULL",
            }
        )

    if creator_id and creator_id not in seen_identities:
        rows.append({"role": "Admin (Creator)", "display": creator_id, "identity": creator_id})
    if my_id and my_id not in seen_identities:
        rows.append({"role": "Me", "display": my_id, "identity": my_id})

    return rows


def fmt_bool(value: Any) -> str:
    """Format a nullable boolean-like value for TECH output.

    Args:
        value (Any): Input value.

    Returns:
        str: ``yes``, ``no``, ``NULL``, or fallback string.
    """
    if value is None:
        return "NULL"
    try:
        return "yes" if int(value) == 1 else "no"
    except Exception:
        return str(value)


def contact_detail_kv(contact: Contact, time_mode: str, tz_name: str) -> List[Tuple[str, str]]:
    """Build detailed key-value rows for one Threema contact.

    Args:
        contact (Contact): Threema contact model.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.

    Returns:
        List[Tuple[str, str]]: Contact detail rows for table rendering.
    """
    return [
        ("ContactPK", str(contact.pk)),
        ("ThreemaID", contact.identity or "NULL"),
        (
            "Name",
            " ".join(
                [x for x in [(contact.first or "").strip(), (contact.last or "").strip()] if x]
            )
            or "NULL",
        ),
        ("PublicNick", contact.public_nick or "NULL"),
        ("Nickname (DB)", contact.nick or "NULL"),
        ("VerifiedEmail", contact.verifiedemail or "NULL"),
        ("VerifiedMobile", contact.verifiedmobileno or "NULL"),
        ("Department", contact.department or "NULL"),
        ("JobTitle", contact.jobtitle or "NULL"),
        ("CNContactID", contact.cncontactid or "NULL"),
        ("CSI", contact.csi or "NULL"),
        ("CreatedAt", format_dt(contact.createdat_raw, time_mode, tz_name, 1900)),
        (
            "ProfilePictureUpload",
            format_dt(contact.profilepictureupload_raw, time_mode, tz_name, 1900),
        ),
        ("ProfilePictureBlobID", contact.profilepictureblobid or "NULL"),
        (
            "VerificationLevel",
            "NULL" if contact.verificationlevel is None else str(contact.verificationlevel),
        ),
        ("State", "NULL" if contact.state is None else str(contact.state)),
        ("Hidden", fmt_bool(contact.hidden)),
        ("WorkContact", fmt_bool(contact.workcontact)),
        ("FeatureMask", "NULL" if contact.featuremask is None else str(contact.featuremask)),
        (
            "ForwardSecurityState",
            "NULL"
            if contact.forwardsecuritystate is None
            else str(contact.forwardsecuritystate),
        ),
        ("ReadReceipts", fmt_bool(contact.readreceipts)),
        ("TypingIndicators", fmt_bool(contact.typingindicators)),
        ("ImportStatus", "NULL" if contact.importstatus is None else str(contact.importstatus)),
        ("ProfilePictureSent", fmt_bool(contact.profilepicturesended)),
        ("SortIndex", "NULL" if contact.sortindex is None else str(contact.sortindex)),
        (
            "PublicKey",
            "len=0"
            if not contact.publickey
            else f"len={len(contact.publickey)} hex_prefix={contact.publickey.hex()[:24]}",
        ),
    ]


def build_threema_tech_pdf(tech: ThreemaTechnicalConversation, pdf_path: str) -> None:
    """Write one Threema TECH PDF file.

    Args:
        tech (ThreemaTechnicalConversation): TECH report input bundle.
        pdf_path (str): Output PDF file path.
    """
    styles = build_styles()
    normal = styles["normal"]
    h1 = styles["h1"]
    h2 = styles["h2"]
    h3 = styles["h3"]
    mono = styles["mono"]

    zid_idx = build_zid_index(tech.messages)
    start_dt, end_dt = conv_date_range(tech.messages, tech.time_mode, tech.tz_name)
    counts = compute_case_summary(tech.messages, tech.media_index)
    part_rows = participant_rows(tech.conv, tech.groupinfo, tech.contacts, tech.members)
    log.info(
        "Rendering Threema TECH PDF conv_pk=%s title=%s path=%s",
        tech.conv.pk,
        tech.chat_title,
        pdf_path,
    )
    log.debug(
        "Rendering Threema TECH PDF details conv_pk=%s participants=%s messages=%s attachments=%s timezone=%s time_mode=%s",
        tech.conv.pk,
        len(part_rows),
        counts["messages"],
        counts["image"] + counts["audio"] + counts["video"] + counts["file"],
        tech.tz_name,
        tech.time_mode,
    )

    contacts_by_identity: Dict[str, Contact] = {}
    for contact in tech.contacts.values():
        if contact.identity and contact.identity.strip():
            contacts_by_identity[contact.identity.strip()] = contact

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

    def kv_table(rows: List[Tuple[str, str]], col_widths=None, font_size=6.8):
        data = [[p("<b>Field</b>"), p("<b>Value</b>")]] + [
            [p(esc_xml(key)), p(esc_xml(value), mono)] for key, value in rows
        ]
        table = Table(data, colWidths=col_widths or [50 * mm, 125 * mm])
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

    def small_participant_table():
        data = [[p("<b>Role</b>"), p("<b>Display</b>"), p("<b>Threema ID</b>")]]
        for row in part_rows:
            data.append(
                [
                    p(esc_xml(row["role"])),
                    p(esc_xml(row["display"])),
                    p(esc_xml(row["identity"])),
                ]
            )

        table = Table(data, colWidths=[30 * mm, 70 * mm, 70 * mm])
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

    def compact_meta_table():
        rows: List[Tuple[str, str]] = [
            ("ConversationPK", str(tech.conv.pk)),
            ("ChatType", conv_type(tech.conv)),
            ("DateRange", f"{start_dt} -> {end_dt}"),
            ("Messages", str(counts["messages"])),
            ("SystemEvents", str(counts["system"])),
            (
                "Attachments",
                f"Images={counts['image']}, Audio={counts['audio']}, Video={counts['video']}, Files={counts['file']}",
            ),
            ("Timezone", tech.tz_name),
            ("TimeMode", tech.time_mode),
            ("UnreadCount", "NULL" if tech.conv.unread_count is None else str(tech.conv.unread_count)),
            ("Visibility", "NULL" if tech.conv.visibility is None else str(tech.conv.visibility)),
            ("Marked", "NULL" if tech.conv.marked is None else str(tech.conv.marked)),
        ]

        if tech.conv.group_id_hex:
            rows.extend(
                [
                    ("GroupName", tech.conv.group_name or "NULL"),
                    ("GroupID(hex)", tech.conv.group_id_hex),
                    ("MyIdentity", tech.conv.group_my_identity or "NULL"),
                ]
            )
            if tech.groupinfo:
                rows.extend(
                    [
                        ("GroupCreator", tech.groupinfo.creator or "NULL"),
                        (
                            "GroupState",
                            "NULL" if tech.groupinfo.state is None else str(tech.groupinfo.state),
                        ),
                        (
                            "GroupLastPeriodicSync",
                            format_dt(
                                tech.groupinfo.last_periodic_sync_raw,
                                tech.time_mode,
                                tech.tz_name,
                                1900,
                            ),
                        ),
                    ]
                )

        return kv_table(rows, col_widths=[45 * mm, 130 * mm], font_size=8)

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

        for message in tech.messages:
            if message.pk not in tech.media_index:
                continue
            sender = determine_sender(message, tech.conv, tech.contacts)
            dt_s = format_dt(message.date_raw, tech.time_mode, tech.tz_name, 1900)

            for item in tech.media_index[message.pk]:
                if not item.get("exported_path_abs"):
                    continue
                abs_path = item["exported_path_abs"]
                data.append(
                    [
                        p(esc_xml(dt_s)),
                        p(esc_xml(sender)),
                        p(esc_xml(item.get("kind", ""))),
                        p(esc_xml(os.path.basename(abs_path))),
                        link("open", rel(abs_path), normal),
                        p(esc_xml(item.get("exported_sha256", "")), mono),
                    ]
                )

        table = Table(
            data,
            colWidths=[32 * mm, 25 * mm, 13 * mm, 45 * mm, 55 * mm, 45 * mm],
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

    def tech_msg_footer(message: Message) -> List[Any]:
        lines = [
            f"msg_pk={message.pk} ent={message.ent} type={ENT_MAP.get(message.ent, '?')} is_own={message.is_own} sender_pk={message.sender_pk}",
            f"status: sent={message.sent} delivered={message.delivered} read={message.read} userack={message.userack} sendfailed={message.sendfailed}",
            f"ids: zid_prefix={blob_prefix_hex(message.zid)} quoted_prefix={blob_prefix_hex(message.quoted_message_id)} flags={message.zflags} origin={message.zorigin} ztype={message.ztype}",
            f"timestamps: date={format_dt(message.date_raw, tech.time_mode, tech.tz_name, 1900)} remoteSent={format_dt(message.remotesentdate_raw, tech.time_mode, tech.tz_name, 1900)}",
            f"           delivery={format_dt(message.deliverydate_raw, tech.time_mode, tech.tz_name, 1900)} read={format_dt(message.readdate_raw, tech.time_mode, tech.tz_name, 1900)} edit={format_dt(message.lasteditedat_raw, tech.time_mode, tech.tz_name, 1900)} deleted={format_dt(message.deletedat_raw, tech.time_mode, tech.tz_name, 1900)}",
        ]
        return [p(esc_xml("\n".join(lines)), mono)]

    story: List[Any] = []
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story.append(p(f"ChatExportPDF - {esc_xml(tech.chat_title)}", h1))
    story.append(
        p(
            f"<font color='#666666'>Exporter: ChatExportPDF v{esc_xml(exporter_version())}</font>",
            normal,
        )
    )
    story.append(Spacer(1, 6))
    story.append(compact_meta_table())
    story.append(Spacer(1, 10))

    story.append(p("Participants", h2))
    story.append(Spacer(1, 6))
    story.append(small_participant_table())

    story.append(Spacer(1, 10))
    story.append(p("Participant details (TECH)", h3))
    story.append(p("Source: ZCONTACT (if available for the participant).", normal))
    story.append(Spacer(1, 6))

    seen = set()
    for row in part_rows:
        identity = (row["identity"] or "NULL").strip()
        display = row["display"]
        role = row["role"]
        key = (role, identity, display)
        if key in seen:
            continue
        seen.add(key)

        story.append(
            p(
                f"<b>{esc_xml(role)}</b> - <b>{esc_xml(display)}</b> <font color='#666666'>({esc_xml(identity)})</font>",
                normal,
            )
        )

        contact = contacts_by_identity.get(identity)
        if contact:
            story.append(kv_table(contact_detail_kv(contact, tech.time_mode, tech.tz_name)))
        else:
            story.append(
                p(
                    "<i>No ZCONTACT details available (only identity from group/conversation metadata).</i>",
                    normal,
                )
            )
        story.append(Spacer(1, 8))

    story.append(PageBreak())
    story.append(p("Messages", h1))
    story.append(Spacer(1, 8))

    for message in tech.messages:
        sender = determine_sender(message, tech.conv, tech.contacts)
        dt_s = format_dt(message.date_raw, tech.time_mode, tech.tz_name, 1900)
        kind = ENT_MAP.get(message.ent, f"ENT_{message.ent}")
        status = (
            "failed"
            if message.sendfailed in (1, True)
            else (
                "read"
                if message.read in (1, True)
                else (
                    "delivered"
                    if message.delivered in (1, True)
                    else "sent" if message.sent in (1, True) else "unknown"
                )
            )
        )

        story.append(
            p(
                f"<b>{esc_xml(dt_s)}</b> - <b>{esc_xml(sender)}</b> <font color='#666666'>({esc_xml(kind)}, {esc_xml(status)})</font>",
                normal,
            )
        )

        quoted = quote_summary(
            message,
            zid_idx,
            tech.time_mode,
            tech.tz_name,
            tech.conv,
            tech.contacts,
        )
        if quoted:
            normalized_quoted, _ = normalize_for_pdf(quoted)
            story.append(p(f"<font color='#444444'>{esc_xml(normalized_quoted)}</font>", normal))

        if kind == "Text" and message.text:
            text_norm, codepoints = normalize_for_pdf(message.text)
            story.append(p(esc_xml(text_norm).replace("\n", "<br/>"), normal))
            if codepoints:
                story.append(p("Unicode/Emoji codepoints: " + esc_xml(", ".join(codepoints)), mono))

        if message.caption:
            caption_norm, codepoints = normalize_for_pdf(message.caption)
            story.append(p(f"<i>Caption:</i> {esc_xml(caption_norm)}", normal))
            if codepoints:
                story.append(p("Caption codepoints: " + esc_xml(", ".join(codepoints)), mono))

        for item in tech.media_index.get(message.pk, []):
            if not item.get("exported_path_abs"):
                continue
            abs_path = item["exported_path_abs"]
            filename = os.path.basename(abs_path)
            story.append(link(f"Attachment ({item.get('kind', '')}) [{filename}]", rel(abs_path), normal))
            story.append(
                p(
                    f"sha256={item.get('exported_sha256')} size={item.get('exported_size')} unwrap={item.get('unwrap_mode')} source={esc_xml(item.get('source_label', ''))}",
                    mono,
                )
            )
            if item.get("pointer_uuid"):
                story.append(
                    p(
                        f"external_uuid={item.get('pointer_uuid')}  external_path={esc_xml(item.get('external_path') or 'NULL')}",
                        mono,
                    )
                )
            if item.get("raw_path_abs"):
                story.append(link("raw_dump", rel(item["raw_path_abs"]), mono))
            if item.get("pointer_dump_path_abs"):
                story.append(link("pointer_dump", rel(item["pointer_dump_path_abs"]), mono))

        reactions = tech.reactions_by_message.get(message.pk, [])
        if reactions:
            parts: List[str] = []
            for reaction in reactions[:20]:
                creator_pk = reaction["ZCREATOR"]
                creator = (
                    tech.contacts[int(creator_pk)].display_name()
                    if creator_pk is not None and int(creator_pk) in tech.contacts
                    else f"Contact#{creator_pk}"
                )
                reaction_text, _ = normalize_for_pdf(str(reaction["ZREACTION"]))
                parts.append(f"{reaction_text} by {creator}")
            suffix = "" if len(reactions) <= 20 else f" ...(+{len(reactions) - 20})"
            story.append(p("Reactions: " + esc_xml(", ".join(parts) + suffix), normal))

        history = tech.history_by_message.get(message.pk, [])
        if history:
            story.append(p(f"Edited: yes ({len(history)}x)", normal))
            first = history[0]
            last = history[-1]
            entries = [("first", first), ("last", last)] if len(history) > 1 else [("edit", first)]
            for tag, row in entries:
                edit_dt = format_dt(row["ZEDITDATE"], tech.time_mode, tech.tz_name, 1900)
                text_norm, codepoints = normalize_for_pdf(row["ZTEXT"] or "")
                preview = text_norm[:200] + "..." if len(text_norm) > 200 else text_norm
                story.append(p(f"{esc_xml(tag)}: {esc_xml(edit_dt)} - {esc_xml(preview)}", mono))
                if codepoints:
                    story.append(p("Edit codepoints: " + esc_xml(", ".join(codepoints)), mono))

        story.extend(tech_msg_footer(message))
        story.append(Spacer(1, 10))

    story.append(PageBreak())
    story.append(p("Attachment Index", h1))
    story.append(Spacer(1, 8))
    story.append(attachment_index_table())

    log.debug(
        "Building Threema TECH PDF story path=%s conv_pk=%s title=%s messages=%s",
        pdf_path,
        tech.conv.pk,
        tech.chat_title,
        len(tech.messages),
    )
    doc.build(story)
    log.info(
        "Rendered Threema TECH PDF conv_pk=%s path=%s",
        tech.conv.pk,
        pdf_path,
    )
