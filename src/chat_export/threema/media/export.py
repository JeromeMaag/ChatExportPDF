"""Export Threema media blobs to filesystem attachments.

This module loads media blobs from the Threema database, resolves optional
external pointer payloads, unwraps encoded file content, and writes exported
attachments plus optional raw dumps.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from ...common.timeutil import dt_compact
from ...common.util import ensure_dir, safe_filename, sha256_file
from ..external_index import resolve_pointer_if_needed
from ..models import Message
from .magic import unwrap_by_magic

log = logging.getLogger(__name__)


def fetch_media_blobs(
    conn: sqlite3.Connection, msg: Message, table: str, msg_fk_val: Optional[int]
) -> List[Tuple[str, bytes]]:
    """Load candidate media blobs for one message and table.

    Args:
        conn (sqlite3.Connection): Open SQLite connection.
        msg (Message): Threema message model.
        table (str): Media table name.
        msg_fk_val (Optional[int]): Direct foreign-key reference from the
            message row.

    Returns:
        List[Tuple[str, bytes]]: Deduplicated blob payloads with source labels.
    """
    cur = conn.cursor()
    res: List[Tuple[str, bytes]] = []
    if msg_fk_val is not None:
        cur.execute(f"SELECT Z_PK, ZDATA FROM {table} WHERE Z_PK = ?;", (msg_fk_val,))
        r = cur.fetchone()
        if r and r["ZDATA"] is not None:
            res.append((f"{table}:pk={int(r['Z_PK'])} via msgFK", r["ZDATA"]))
    cur.execute(
        f"SELECT Z_PK, ZDATA FROM {table} WHERE ZMESSAGE = ? ORDER BY Z_PK ASC;",
        (msg.pk,),
    )
    for r in cur.fetchall():
        if r["ZDATA"] is not None:
            res.append((f"{table}:pk={int(r['Z_PK'])} via data.ZMESSAGE", r["ZDATA"]))
    dedup: Dict[str, Tuple[str, bytes]] = {}
    for label, data in res:
        h = hashlib.sha256(data).hexdigest()
        if h not in dedup:
            dedup[h] = (label, data)
    if dedup:
        log.debug(
            "Fetched media blobs msg_pk=%s table=%s raw=%s dedup=%s",
            msg.pk,
            table,
            len(res),
            len(dedup),
        )
    return list(dedup.values())


def make_friendly_attachment_name(
    chat_title: str,
    msg: Message,
    sender: str,
    kind: str,
    time_mode: str,
    tz_name: str,
    ext: str,
) -> str:
    """Build a readable exported attachment filename.

    Args:
        chat_title (str): Conversation title.
        msg (Message): Threema message model.
        sender (str): Sender display name.
        kind (str): Generic attachment type.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.
        ext (str): Output file extension.

    Returns:
        str: Filesystem-safe attachment filename.
    """
    ts = dt_compact(msg.date_raw, time_mode, tz_name)
    return (
        f"{safe_filename(chat_title,40)}_{ts}_{safe_filename(sender,30)}_"
        f"{kind.capitalize()}_msg{msg.pk}{ext}"
    )


def export_media_for_message(
    conn: sqlite3.Connection,
    msg: Message,
    chat_title: str,
    conv_media_dir: str,
    external_index: Dict[str, str],
    time_mode: str,
    tz_name: str,
    sender: str,
    max_media_bytes: int = 0,
    keep_raw: bool = True,
) -> List[Dict[str, Any]]:
    """Export all media attachments for one Threema message.

    Args:
        conn (sqlite3.Connection): Open SQLite connection.
        msg (Message): Threema message model.
        chat_title (str): Conversation title.
        conv_media_dir (str): Conversation media output directory.
        external_index (Dict[str, str]): External data index keyed by UUID.
        time_mode (str): Source timestamp mode label.
        tz_name (str): IANA timezone name.
        sender (str): Sender display name.
        max_media_bytes (int): Maximum allowed blob size in bytes. ``0``
            disables the limit.
        keep_raw (bool): Write raw blob dumps in addition to exported files.

    Returns:
        List[Dict[str, Any]]: Export metadata records for all processed media
        items.
    """
    ensure_dir(conv_media_dir)
    items: List[Dict[str, Any]] = []

    exported_count = 0
    skipped_count = 0
    pointer_found = 0
    pointer_resolved = 0
    pointer_missing = 0

    def _write_bytes(path: str, data: bytes) -> None:
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            log.exception("Failed to write file: %s", path)
            raise

    def handle(table: str, kind: str, fk: Optional[int]) -> None:
        nonlocal exported_count, skipped_count, pointer_found, pointer_resolved, pointer_missing

        blobs = fetch_media_blobs(conn, msg, table, fk)
        if not blobs:
            return

        for idx, (source_label, data) in enumerate(blobs):
            if max_media_bytes and len(data) > max_media_bytes:
                skipped_count += 1
                items.append(
                    {
                        "kind": kind,
                        "table": table,
                        "source_label": source_label,
                        "exported_path_abs": None,
                        "exported_size": None,
                        "exported_sha256": None,
                        "skipped_due_to_limit": True,
                        "skip_reason": (
                            f"size={len(data)} exceeds max_media_bytes={max_media_bytes}"
                        ),
                        "note": f"skipped size={len(data)}",
                    }
                )
                log.warning(
                    "Skipped %s blob due to size limit: msg_pk=%s kind=%s size=%s max=%s source=%s",
                    table,
                    msg.pk,
                    kind,
                    len(data),
                    max_media_bytes,
                    source_label,
                )
                continue

            raw_path = None
            if keep_raw:
                raw_path = os.path.join(
                    conv_media_dir,
                    f"msg_{msg.pk}_{kind}_{idx}_raw.bin",
                )
                _write_bytes(raw_path, data)

            payload, pointer_uuid, external_path = resolve_pointer_if_needed(
                data,
                external_index,
            )

            pointer_dump_path = None
            if pointer_uuid:
                pointer_found += 1
                if external_path:
                    pointer_resolved += 1
                else:
                    pointer_missing += 1
                    log.warning(
                        "External pointer not resolved: msg_pk=%s kind=%s uuid=%s (external_folder missing or incomplete?) source=%s",
                        msg.pk,
                        kind,
                        pointer_uuid,
                        source_label,
                    )

                if keep_raw:
                    pointer_dump_path = os.path.join(
                        conv_media_dir,
                        f"msg_{msg.pk}_{kind}_{idx}_pointer_raw.bin",
                    )
                    _write_bytes(pointer_dump_path, data)

            unwrapped, ext, unwrap_mode = unwrap_by_magic(payload)

            friendly = make_friendly_attachment_name(
                chat_title,
                msg,
                sender,
                kind,
                time_mode,
                tz_name,
                ext,
            )
            export_path = os.path.join(conv_media_dir, friendly)
            _write_bytes(export_path, unwrapped)

            exported_count += 1

            info: Dict[str, Any] = {
                "kind": kind,
                "table": table,
                "source_label": source_label,
                "exported_path_abs": os.path.abspath(export_path),
                "exported_size": len(unwrapped),
                "exported_sha256": sha256_file(export_path),
                "unwrap_mode": unwrap_mode,
                "raw_path_abs": os.path.abspath(raw_path) if raw_path else None,
                "raw_sha256": sha256_file(raw_path) if raw_path else None,
                "pointer_uuid": pointer_uuid,
                "external_path": external_path,
                "pointer_dump_path_abs": (
                    os.path.abspath(pointer_dump_path) if pointer_dump_path else None
                ),
            }
            items.append(info)

            log.debug(
                "Exported attachment: msg_pk=%s kind=%s path=%s size=%s unwrap=%s source=%s pointer=%s",
                msg.pk,
                kind,
                os.path.basename(export_path),
                len(unwrapped),
                unwrap_mode,
                source_label,
                pointer_uuid or "-",
            )

    handle("ZIMAGEDATA", "image", msg.zimage_fk)
    handle("ZAUDIODATA", "audio", msg.zaudio_fk)
    handle("ZVIDEODATA", "video", msg.zvideo_fk)
    handle("ZFILEDATA", "file", msg.zdata_fk)

    if exported_count or skipped_count or pointer_found:
        log.debug(
            "Media summary: msg_pk=%s exported=%s skipped=%s pointers=%s resolved=%s missing=%s",
            msg.pk,
            exported_count,
            skipped_count,
            pointer_found,
            pointer_resolved,
            pointer_missing,
        )

    return items
