from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote


from importlib.metadata import PackageNotFoundError, version as pkg_version
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..db.queries import load_history, load_reactions
from ..models import ENT_MAP, Contact, Conversation, GroupInfo, Message
from ..textutil import esc_xml, normalize_for_pdf
from ..timeutil import format_dt
from ..util import blob_prefix_hex, relpath_for_link
from .styles import build_styles

log = logging.getLogger(__name__)


def exporter_version() -> str:
    try:
        return pkg_version("threema-chat-export")
    except PackageNotFoundError:
        return "dev"
    except Exception:
        return "unknown"


def conv_type(conv: Conversation) -> str:
    if conv.group_id_hex:
        return "GROUP"
    if conv.contact_pk:
        return "DIRECT"
    return "UNKNOWN"


def determine_sender(
    msg: Message, conv: Conversation, contacts: Dict[int, Contact]
) -> str:
    if msg.is_own == 1:
        return "Me"
    if msg.sender_pk is not None and int(msg.sender_pk) in contacts:
        return contacts[int(msg.sender_pk)].display_name()
    if conv.contact_pk is not None and int(conv.contact_pk) in contacts:
        return contacts[int(conv.contact_pk)].display_name()
    return "Unknown"


def conv_date_range(
    messages: List[Message], time_mode: str, tz_name: str
) -> Tuple[str, str]:
    if not messages:
        return ("NULL", "NULL")
    return (
        format_dt(messages[0].date_raw, time_mode, tz_name, 1900),
        format_dt(messages[-1].date_raw, time_mode, tz_name, 1900),
    )


def build_zid_index(messages: List[Message]) -> Dict[str, Message]:
    idx: Dict[str, Message] = {}
    for m in messages:
        if m.zid:
            idx[m.zid.hex()] = m
    return idx


def quote_summary(
    msg: Message,
    zid_index: Dict[str, Message],
    time_mode: str,
    tz_name: str,
    conv: Conversation,
    contacts: Dict[int, Contact],
) -> Optional[str]:
    if not msg.quoted_message_id:
        return None

    q = msg.quoted_message_id.hex()
    ref = zid_index.get(q)
    if not ref:
        return "↩ Reply to: (unknown message)"

    sender = determine_sender(ref, conv, contacts)
    dt_s = format_dt(ref.date_raw, time_mode, tz_name, 1900)

    if ref.text:
        t, _ = normalize_for_pdf(ref.text.strip().replace("\n", " "))
        t = (t[:120] + "…") if len(t) > 120 else t
        excerpt = t
    else:
        excerpt = ENT_MAP.get(ref.ent, f"ENT_{ref.ent}")

    return f"↩ Reply to: {sender} {dt_s} — “{excerpt}”"


def compute_case_summary(
    messages: List[Message], media_index: Dict[int, List[Dict[str, Any]]]
) -> Dict[str, int]:
    counts: Dict[str, int] = {
        "messages": len(messages),
        "system": 0,
        "text": 0,
        "image": 0,
        "audio": 0,
        "video": 0,
        "file": 0,
    }

    for m in messages:
        k = ENT_MAP.get(m.ent, "")
        if k == "System":
            counts["system"] += 1
        if k == "Text":
            counts["text"] += 1

    # Count only exported attachments (exported_path_abs exists)
    for items in media_index.values():
        for it in items:
            if not it.get("exported_path_abs"):
                continue
            kind = it.get("kind")
            if kind in counts:
                counts[kind] += 1

    return counts


def participant_rows(
    conv: Conversation,
    groupinfo: Optional[GroupInfo],
    contacts: Dict[int, Contact],
    member_pks: List[int],
) -> List[Dict[str, str]]:
    creator_id = groupinfo.creator if groupinfo else None
    my_id = conv.group_my_identity if conv.group_id_hex else None

    rows: List[Dict[str, str]] = []
    seen_identities = set()

    for pk in member_pks:
        c = contacts.get(pk)
        disp = c.display_name() if c else f"Contact#{pk}"
        ident = (c.identity if c else None) or "NULL"

        role = "Member"
        if my_id and ident == my_id:
            role = "Me"
        if creator_id and ident == creator_id:
            role = "Admin (Creator)"

        rows.append({"role": role, "display": disp, "identity": ident})
        if ident != "NULL":
            seen_identities.add(ident)

    # Direct chat participant
    if not conv.group_id_hex and conv.contact_pk and int(conv.contact_pk) in contacts:
        c = contacts[int(conv.contact_pk)]
        ident = c.identity or "NULL"
        rows.append(
            {"role": "Chat partner", "display": c.display_name(), "identity": ident}
        )

    # Ensure creator/my id appear even if not in member list
    if creator_id and creator_id not in seen_identities:
        rows.append(
            {"role": "Admin (Creator)", "display": creator_id, "identity": creator_id}
        )
    if my_id and my_id not in seen_identities:
        rows.append({"role": "Me", "display": my_id, "identity": my_id})

    return rows


def fmt_bool(v: Any) -> str:
    if v is None:
        return "NULL"
    try:
        return "yes" if int(v) == 1 else "no"
    except Exception:
        return str(v)


def contact_detail_kv(
    c: Contact, time_mode: str, tz_name: str
) -> List[Tuple[str, str]]:
    kv: List[Tuple[str, str]] = []
    kv.append(("ContactPK", str(c.pk)))
    kv.append(("ThreemaID", c.identity or "NULL"))
    kv.append(
        (
            "Name",
            " ".join(
                [x for x in [(c.first or "").strip(), (c.last or "").strip()] if x]
            )
            or "NULL",
        )
    )
    kv.append(("PublicNick", c.public_nick or "NULL"))
    kv.append(("Nickname (DB)", c.nick or "NULL"))
    kv.append(("VerifiedEmail", c.verifiedemail or "NULL"))
    kv.append(("VerifiedMobile", c.verifiedmobileno or "NULL"))
    kv.append(("Department", c.department or "NULL"))
    kv.append(("JobTitle", c.jobtitle or "NULL"))
    kv.append(("CNContactID", c.cncontactid or "NULL"))
    kv.append(("CSI", c.csi or "NULL"))
    kv.append(("CreatedAt", format_dt(c.createdat_raw, time_mode, tz_name, 1900)))
    kv.append(
        (
            "ProfilePictureUpload",
            format_dt(c.profilepictureupload_raw, time_mode, tz_name, 1900),
        )
    )
    kv.append(("ProfilePictureBlobID", c.profilepictureblobid or "NULL"))
    kv.append(
        (
            "VerificationLevel",
            "NULL" if c.verificationlevel is None else str(c.verificationlevel),
        )
    )
    kv.append(("State", "NULL" if c.state is None else str(c.state)))
    kv.append(("Hidden", fmt_bool(c.hidden)))
    kv.append(("WorkContact", fmt_bool(c.workcontact)))
    kv.append(("FeatureMask", "NULL" if c.featuremask is None else str(c.featuremask)))
    kv.append(
        (
            "ForwardSecurityState",
            "NULL" if c.forwardsecuritystate is None else str(c.forwardsecuritystate),
        )
    )
    kv.append(("ReadReceipts", fmt_bool(c.readreceipts)))
    kv.append(("TypingIndicators", fmt_bool(c.typingindicators)))
    kv.append(
        ("ImportStatus", "NULL" if c.importstatus is None else str(c.importstatus))
    )
    kv.append(("ProfilePictureSent", fmt_bool(c.profilepicturesended)))
    kv.append(("SortIndex", "NULL" if c.sortindex is None else str(c.sortindex)))
    kv.append(
        (
            "PublicKey",
            (
                "len=0"
                if not c.publickey
                else f"len={len(c.publickey)} hex_prefix={c.publickey.hex()[:24]}"
            ),
        )
    )
    return kv


def build_pdfs_for_conversation(
    conn,
    conv: Conversation,
    chat_title: str,
    pdf_path: str,
    pdf_tech_path: str,
    contacts: Dict[int, Contact],
    groups: Dict[str, GroupInfo],
    members: List[int],
    messages: List[Message],
    media_index: Dict[int, List[Dict[str, Any]]],
    time_mode: str,
    tz_name: str,
) -> None:
    styles = build_styles()
    normal = styles["normal"]
    h1 = styles["h1"]
    h2 = styles["h2"]
    h3 = styles["h3"]
    mono = styles["mono"]

    zid_idx = build_zid_index(messages)
    start_dt, end_dt = conv_date_range(messages, time_mode, tz_name)
    counts = compute_case_summary(messages, media_index)

    groupinfo = groups.get(conv.group_id_hex) if conv.group_id_hex else None
    part_rows = participant_rows(conv, groupinfo, contacts, members)

    # Fast lookup for participant identity -> Contact
    contacts_by_identity: Dict[str, Contact] = {}
    for c in contacts.values():
        if c.identity and c.identity.strip():
            contacts_by_identity[c.identity.strip()] = c

    def p(txt: str, style=normal):
        return Paragraph(txt.replace("\n", "<br/>"), style)

    def link(label: str, rel_path: str, style=normal):
        rel_path = rel_path.replace("\\", "/")
        href = quote(rel_path)
        return Paragraph(
            f'{esc_xml(label)}: <a href="{href}">{esc_xml(rel_path)}</a>', style
        )

    def rel(target_abs: str, pdf_abs: str) -> str:
        return relpath_for_link(target_abs, pdf_abs)

    def small_participant_table():
        data = [[p("<b>Role</b>"), p("<b>Display</b>"), p("<b>Threema ID</b>")]]
        for r in part_rows:
            data.append(
                [
                    p(esc_xml(r["role"])),
                    p(esc_xml(r["display"])),
                    p(esc_xml(r["identity"])),
                ]
            )

        t = Table(data, colWidths=[30 * mm, 70 * mm, 70 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return t

    def kv_table(kv: List[Tuple[str, str]], col_widths=None, font_size=6.8):
        data = [[p("<b>Field</b>"), p("<b>Value</b>")]] + [
            [p(esc_xml(k)), p(esc_xml(v), mono)] for k, v in kv
        ]
        t = Table(data, colWidths=col_widths or [50 * mm, 125 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ]
            )
        )
        return t

    def compact_meta_table(is_tech: bool):
        rows: List[Tuple[str, str]] = []
        rows.append(("ConversationPK", str(conv.pk)))
        rows.append(("ChatType", conv_type(conv)))
        rows.append(("DateRange", f"{start_dt} → {end_dt}"))
        rows.append(("Messages", str(counts["messages"])))
        rows.append(("SystemEvents", str(counts["system"])))
        rows.append(
            (
                "Attachments",
                f"Images={counts['image']}, Audio={counts['audio']}, Video={counts['video']}, Files={counts['file']}",
            )
        )
        rows.append(("Timezone", tz_name))
        rows.append(("TimeMode", time_mode))
        rows.append(
            (
                "UnreadCount",
                "NULL" if conv.unread_count is None else str(conv.unread_count),
            )
        )
        rows.append(
            ("Visibility", "NULL" if conv.visibility is None else str(conv.visibility))
        )
        rows.append(("Marked", "NULL" if conv.marked is None else str(conv.marked)))

        if conv.group_id_hex:
            rows.append(("GroupName", conv.group_name or "NULL"))
            rows.append(("GroupID(hex)", conv.group_id_hex))
            rows.append(("MyIdentity", conv.group_my_identity or "NULL"))
            if groupinfo:
                rows.append(("GroupCreator", groupinfo.creator or "NULL"))
                rows.append(
                    (
                        "GroupState",
                        "NULL" if groupinfo.state is None else str(groupinfo.state),
                    )
                )
                rows.append(
                    (
                        "GroupLastPeriodicSync",
                        format_dt(
                            groupinfo.last_periodic_sync_raw, time_mode, tz_name, 1900
                        ),
                    )
                )

        data = [[p("<b>Field</b>"), p("<b>Value</b>")]] + [
            [p(esc_xml(k)), p(esc_xml(v), mono if is_tech else normal)] for k, v in rows
        ]
        t = Table(data, colWidths=[45 * mm, 130 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return t

    def attachment_index_table(pdf_path_for_links: str):
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

        for m in messages:
            if m.pk not in media_index:
                continue
            sender = determine_sender(m, conv, contacts)
            dt_s = format_dt(m.date_raw, time_mode, tz_name, 1900)

            for it in media_index[m.pk]:
                if not it.get("exported_path_abs"):
                    continue
                abs_p = it["exported_path_abs"]
                relp = rel(abs_p, pdf_path_for_links)

                data.append(
                    [
                        p(esc_xml(dt_s)),
                        p(esc_xml(sender)),
                        p(esc_xml(it.get("kind", ""))),
                        p(esc_xml(os.path.basename(abs_p))),
                        link("open", relp, normal),
                        p(esc_xml(it.get("exported_sha256", "")), mono),
                    ]
                )

        tbl = Table(
            data, colWidths=[32 * mm, 25 * mm, 13 * mm, 45 * mm, 55 * mm, 45 * mm]
        )
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return tbl

    def tech_msg_footer(m: Message) -> List[Any]:
        lines: List[str] = []
        lines.append(
            f"msg_pk={m.pk} ent={m.ent} type={ENT_MAP.get(m.ent,'?')} is_own={m.is_own} sender_pk={m.sender_pk}"
        )
        lines.append(
            f"status: sent={m.sent} delivered={m.delivered} read={m.read} userack={m.userack} sendfailed={m.sendfailed}"
        )
        lines.append(
            f"ids: zid_prefix={blob_prefix_hex(m.zid)} quoted_prefix={blob_prefix_hex(m.quoted_message_id)} flags={m.zflags} origin={m.zorigin} ztype={m.ztype}"
        )
        lines.append(
            f"timestamps: date={format_dt(m.date_raw,time_mode,tz_name,1900)} remoteSent={format_dt(m.remotesentdate_raw,time_mode,tz_name,1900)}"
        )
        lines.append(
            f"           delivery={format_dt(m.deliverydate_raw,time_mode,tz_name,1900)} read={format_dt(m.readdate_raw,time_mode,tz_name,1900)} edit={format_dt(m.lasteditedat_raw,time_mode,tz_name,1900)} deleted={format_dt(m.deletedat_raw,time_mode,tz_name,1900)}"
        )
        return [p(esc_xml("\n".join(lines)), mono)]

    def build_doc(path: str, is_tech: bool):
        # Minimal high-value logging
        try:
            attachment_count = sum(
                1
                for items in media_index.values()
                for it in items
                if it.get("exported_path_abs")
            )
            log.debug(
                "Building PDF (tech=%s) path=%s conv_pk=%s title=%s messages=%s attachments=%s",
                is_tech,
                path,
                conv.pk,
                chat_title,
                len(messages),
                attachment_count,
            )
        except Exception:
            pass

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        story: List[Any] = []

        # Cover
        story.append(p(f"CHAT EXPORT — {esc_xml(chat_title)}", h1))
        story.append(
            p(
                f"<font color='#666666'>Exporter: threema-chat-export v{esc_xml(exporter_version())}</font>",
                normal,
            )
        )
        story.append(Spacer(1, 6))
        story.append(compact_meta_table(is_tech=is_tech))
        story.append(Spacer(1, 10))

        # Participants
        story.append(p("Participants", h2))
        story.append(Spacer(1, 6))
        story.append(small_participant_table())

        # TECH-only participant details
        if is_tech:
            story.append(Spacer(1, 10))
            story.append(p("Participant details (TECH)", h3))
            story.append(
                p("Source: ZCONTACT (if available for the participant).", normal)
            )
            story.append(Spacer(1, 6))

            seen = set()
            for r in part_rows:
                ident = (r["identity"] or "NULL").strip()
                disp = r["display"]
                role = r["role"]
                key = (role, ident, disp)
                if key in seen:
                    continue
                seen.add(key)

                story.append(
                    p(
                        f"<b>{esc_xml(role)}</b> — <b>{esc_xml(disp)}</b> <font color='#666666'>({esc_xml(ident)})</font>",
                        normal,
                    )
                )

                c = contacts_by_identity.get(ident)
                if c:
                    story.append(kv_table(contact_detail_kv(c, time_mode, tz_name)))
                else:
                    story.append(
                        p(
                            "<i>No ZCONTACT details available (only identity from group/conversation metadata).</i>",
                            normal,
                        )
                    )
                story.append(Spacer(1, 8))

        story.append(PageBreak())

        # Messages
        story.append(p("Messages", h1))
        story.append(Spacer(1, 8))

        for m in messages:
            sender = determine_sender(m, conv, contacts)
            dt_s = format_dt(m.date_raw, time_mode, tz_name, 1900)
            kind = ENT_MAP.get(m.ent, f"ENT_{m.ent}")

            status = (
                "failed"
                if m.sendfailed in (1, True)
                else (
                    "read"
                    if m.read in (1, True)
                    else (
                        "delivered"
                        if m.delivered in (1, True)
                        else "sent" if m.sent in (1, True) else "unknown"
                    )
                )
            )

            story.append(
                p(
                    f"<b>{esc_xml(dt_s)}</b> — <b>{esc_xml(sender)}</b> <font color='#666666'>({esc_xml(kind)}, {esc_xml(status)})</font>",
                    normal,
                )
            )

            qs = quote_summary(m, zid_idx, time_mode, tz_name, conv, contacts)
            if qs:
                qn, _ = normalize_for_pdf(qs)
                story.append(p(f"<font color='#444444'>{esc_xml(qn)}</font>", normal))

            if kind == "Text" and m.text:
                t_norm, cps = normalize_for_pdf(m.text)
                story.append(p(esc_xml(t_norm).replace("\n", "<br/>"), normal))
                if is_tech and cps:
                    story.append(
                        p("Unicode/Emoji codepoints: " + esc_xml(", ".join(cps)), mono)
                    )

            if m.caption:
                cap_norm, cps = normalize_for_pdf(m.caption)
                story.append(p(f"<i>Caption:</i> {esc_xml(cap_norm)}", normal))
                if is_tech and cps:
                    story.append(
                        p("Caption codepoints: " + esc_xml(", ".join(cps)), mono)
                    )

            # Attachments (links)
            if m.pk in media_index:
                for it in media_index[m.pk]:
                    if not it.get("exported_path_abs"):
                        continue

                    relp = rel(it["exported_path_abs"], path)
                    fname = os.path.basename(it["exported_path_abs"])
                    story.append(
                        link(
                            f"Attachment ({it.get('kind','')}) [{fname}]", relp, normal
                        )
                    )

                    if is_tech:
                        story.append(
                            p(
                                f"sha256={it.get('exported_sha256')} size={it.get('exported_size')} "
                                f"unwrap={it.get('unwrap_mode')} source={esc_xml(it.get('source_label',''))}",
                                mono,
                            )
                        )
                        if it.get("pointer_uuid"):
                            story.append(
                                p(
                                    f"external_uuid={it.get('pointer_uuid')}  external_path={esc_xml(it.get('external_path') or 'NULL')}",
                                    mono,
                                )
                            )
                        if it.get("raw_path_abs"):
                            story.append(
                                link("raw_dump", rel(it["raw_path_abs"], path), mono)
                            )
                        if it.get("pointer_dump_path_abs"):
                            story.append(
                                link(
                                    "pointer_dump",
                                    rel(it["pointer_dump_path_abs"], path),
                                    mono,
                                )
                            )

            # Reactions (compact)
            reactions = load_reactions(conn, m.pk)
            if reactions:
                parts: List[str] = []
                for r in reactions[:20]:
                    creator_pk = r["ZCREATOR"]
                    creator = (
                        contacts[int(creator_pk)].display_name()
                        if creator_pk is not None and int(creator_pk) in contacts
                        else f"Contact#{creator_pk}"
                    )
                    rx_txt, _ = normalize_for_pdf(str(r["ZREACTION"]))
                    parts.append(f"{rx_txt} by {creator}")
                suffix = "" if len(reactions) <= 20 else f" …(+{len(reactions)-20})"
                story.append(
                    p("Reactions: " + esc_xml(", ".join(parts) + suffix), normal)
                )

            # Edits (compact)
            hist = load_history(conn, m.pk)
            if hist:
                story.append(p(f"Edited: yes ({len(hist)}x)", normal))
                if is_tech:
                    first = hist[0]
                    last = hist[-1]
                    entries = (
                        [("first", first), ("last", last)]
                        if len(hist) > 1
                        else [("edit", first)]
                    )
                    for tag, r in entries:
                        edit_dt = format_dt(r["ZEDITDATE"], time_mode, tz_name, 1900)
                        txt_norm, cps = normalize_for_pdf(r["ZTEXT"] or "")
                        story.append(
                            p(
                                f"{tag}: {esc_xml(edit_dt)} — {esc_xml(txt_norm[:200])}{'…' if len(txt_norm)>200 else ''}",
                                mono,
                            )
                        )
                        if cps:
                            story.append(
                                p("Edit codepoints: " + esc_xml(", ".join(cps)), mono)
                            )

            if is_tech:
                story.extend(tech_msg_footer(m))

            story.append(Spacer(1, 10))

        # Attachment index
        story.append(PageBreak())
        story.append(p("Attachment Index", h1))
        story.append(Spacer(1, 8))
        story.append(attachment_index_table(path))

        try:
            doc.build(story)
            log.debug("Built PDF (tech=%s) path=%s", is_tech, path)
        except Exception:
            log.exception(
                "PDF build failed (tech=%s) conv_pk=%s title=%s path=%s",
                is_tech,
                conv.pk,
                chat_title,
                path,
            )
            raise

    build_doc(pdf_path, is_tech=False)
    build_doc(pdf_tech_path, is_tech=True)
