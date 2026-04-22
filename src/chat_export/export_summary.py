"""Build export summary artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .common.logging_setup import sanitize_local_paths
from .config import ExportConfig

TOOL_NAME = "ChatExportPDF"
REPOSITORY_URL = "https://github.com/JeromeMaag/ChatExportPDF"
EXPORT_SUMMARY_FILENAME = "export_summary.txt"
MANIFEST_FILENAME = "manifest.json"
LOG_FILENAME = "log.txt"
HASH_CHUNK_SIZE = 1024 * 1024


def _create_md5_fingerprint_hasher() -> Any | None:
    """Create an MD5 hasher for non-security file fingerprinting."""
    try:
        return hashlib.md5(usedforsecurity=False)
    except TypeError:
        try:
            return hashlib.md5()
        except Exception:
            return None
    except Exception:
        return None


def _update_optional_hasher(hasher: Any | None, chunk: bytes) -> Any | None:
    """Update one optional hasher and disable it on hashing errors."""
    if hasher is None:
        return None
    try:
        hasher.update(chunk)
    except Exception:
        return None
    return hasher


def default_log_file(out_dir: str) -> str:
    """Return the default `log.txt` path."""
    return os.path.join(out_dir, LOG_FILENAME)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    """Convert a timestamp to ISO-8601 text."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    """Return elapsed seconds between two timestamps."""
    return round((finished_at - started_at).total_seconds(), 3)


def _hash_file(path: str) -> tuple[str | None, str]:
    """Return optional MD5 and SHA-256 hashes for one file."""
    md5 = _create_md5_fingerprint_hasher()
    sha256 = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            md5 = _update_optional_hasher(md5, chunk)
            sha256.update(chunk)
    return md5.hexdigest() if md5 is not None else None, sha256.hexdigest()


def _file_metadata(path: str | None) -> dict[str, Any]:
    """Return filename, size, and hashes for one file."""
    if not path:
        return {
            "filename": None,
            "size_bytes": None,
            "md5": None,
            "sha256": None,
        }

    metadata: dict[str, Any] = {
        "filename": os.path.basename(path),
        "size_bytes": None,
        "md5": None,
        "sha256": None,
    }
    if not os.path.isfile(path):
        return metadata

    try:
        metadata["size_bytes"] = os.path.getsize(path)
    except OSError:
        return metadata

    try:
        metadata["md5"], metadata["sha256"] = _hash_file(path)
    except Exception:
        pass
    return metadata


def _relpath(path: str | None, out_dir: str) -> str | None:
    """Return a path relative to the export directory."""
    if not path:
        return None
    abs_out = os.path.abspath(out_dir)
    abs_path = os.path.abspath(path)
    try:
        common = os.path.commonpath([abs_out, abs_path])
    except ValueError:
        return os.path.basename(path)
    if common != abs_out:
        return os.path.basename(path)
    return os.path.relpath(abs_path, abs_out).replace(os.sep, "/")


def _input_file_info(cfg: ExportConfig) -> dict[str, Any]:
    """Build input file metadata."""
    try:
        path = cfg.resolved_input_path()
    except Exception:
        path = None
    return _file_metadata(path)


def _conversation_entries(
    results: dict[str, Any] | None,
    out_dir: str,
) -> list[dict[str, Any]]:
    """Build conversation summary entries."""
    entries: list[dict[str, Any]] = []
    for item in (results or {}).get("exported", []):
        generated_files = [
            _relpath(item.get("pdf_path"), out_dir),
            _relpath(item.get("pdf_tech_path"), out_dir),
            _relpath(item.get("xlsx_path"), out_dir),
        ]
        entries.append(
            {
                "title": item.get("title"),
                "conversation_id": item.get("conversation_id"),
                "conversation_type": item.get("conversation_type"),
                "participant_count": item.get("participant_count"),
                "message_count": item.get("message_count"),
                "attachment_count": item.get("attachment_count"),
                "generated_files": [path for path in generated_files if path],
            }
        )
    return entries


def _iter_files(root: str | None) -> list[str]:
    """Return all files below a directory in deterministic order."""
    if not root or not os.path.isdir(root):
        return []
    paths: list[str] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            paths.append(os.path.join(current_root, filename))
    return paths


def _append_generated_file(
    entries: list[dict[str, Any]],
    seen_paths: set[str],
    *,
    file_type: str,
    path: str | None,
    out_dir: str,
) -> None:
    """Append one generated file entry if it exists and was not seen before."""
    if not path or not os.path.isfile(path):
        return
    rel_path = _relpath(path, out_dir)
    if not rel_path or rel_path in seen_paths:
        return
    metadata = _file_metadata(path)
    entries.append(
        {
            "type": file_type,
            "path": rel_path,
            "filename": metadata["filename"],
            "size_bytes": metadata["size_bytes"],
            "md5": metadata["md5"],
            "sha256": metadata["sha256"],
            "hash_note": None,
        }
    )
    seen_paths.add(rel_path)


def _append_unhashed_file(
    entries: list[dict[str, Any]],
    seen_paths: set[str],
    *,
    file_type: str,
    path: str,
    out_dir: str,
    hash_note: str,
    include_size: bool = True,
) -> None:
    """Append one file entry where hashes are intentionally not recorded."""
    rel_path = _relpath(path, out_dir)
    if not rel_path or rel_path in seen_paths:
        return
    size_bytes = None
    if include_size and os.path.isfile(path):
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = None
    entries.append(
        {
            "type": file_type,
            "path": rel_path,
            "filename": os.path.basename(path),
            "size_bytes": size_bytes,
            "md5": None,
            "sha256": None,
            "hash_note": hash_note,
        }
    )
    seen_paths.add(rel_path)


def _generated_file_entries(
    results: dict[str, Any] | None,
    out_dir: str,
) -> list[dict[str, Any]]:
    """Build the generated file inventory."""
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    file_fields = (
        ("normal_pdf", "pdf_path"),
        ("tech_pdf", "pdf_tech_path"),
        ("excel_workbook", "xlsx_path"),
    )
    for item in (results or {}).get("exported", []):
        for file_type, key in file_fields:
            _append_generated_file(
                entries,
                seen_paths,
                file_type=file_type,
                path=item.get(key),
                out_dir=out_dir,
            )

        for path in _iter_files(item.get("media_dir")):
            _append_generated_file(
                entries,
                seen_paths,
                file_type="media_file",
                path=path,
                out_dir=out_dir,
            )
    return entries


def _append_traceability_file_entries(
    manifest: dict[str, Any],
    *,
    out_dir: str,
    summary_path: str,
    manifest_path: str,
) -> None:
    """Add summary, log, and manifest entries to the file inventory."""
    entries = manifest["files"]
    seen_paths = {entry.get("path") for entry in entries if entry.get("path")}
    _append_generated_file(
        entries,
        seen_paths,
        file_type="export_summary",
        path=summary_path,
        out_dir=out_dir,
    )
    log_path = default_log_file(out_dir)
    if os.path.isfile(log_path):
        _append_unhashed_file(
            entries,
            seen_paths,
            file_type="log",
            path=log_path,
            out_dir=out_dir,
            hash_note="log may receive entries after manifest generation; size and hash not recorded",
            include_size=False,
        )
    _append_unhashed_file(
        entries,
        seen_paths,
        file_type="manifest",
        path=manifest_path,
        out_dir=out_dir,
        hash_note="self-referential manifest; size and hash not recorded",
        include_size=False,
    )


def _overall_counts(results: dict[str, Any] | None) -> dict[str, Any]:
    """Build overall count values."""
    exported = (results or {}).get("exported", [])
    participant_ids = {
        participant_id
        for item in exported
        for participant_id in (item.get("participant_ids") or [])
    }
    participant_count = (
        len(participant_ids)
        if participant_ids
        else sum(item.get("participant_count") or 0 for item in exported)
    )

    def _count(key: str) -> int:
        def _as_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        raw_value = (results or {}).get(key)
        if raw_value is not None:
            return _as_int(raw_value)
        return sum(_as_int(item.get(key)) for item in exported)

    return {
        "conversation_count": len(exported),
        "message_count": sum(item.get("message_count") or 0 for item in exported),
        "participant_count": participant_count,
        "attachment_count": sum(item.get("attachment_count") or 0 for item in exported),
        "missing_media_count": _count("missing_media_count"),
        "skipped_media_count": _count("skipped_media_count"),
        "unparseable_line_count": _count("unparseable_line_count"),
    }


def _settings(cfg: ExportConfig, results: dict[str, Any] | None) -> dict[str, Any]:
    """Build export settings."""
    return {
        "selected_source": cfg.source_app,
        "timezone": cfg.tz_name,
        "time_mode": (results or {}).get("time_mode", "unknown"),
        "media_export_enabled": cfg.export_media,
        "image_previews_enabled": cfg.export_image_previews,
        "excel_export_enabled": cfg.export_excel,
        "conversation_limit": cfg.limit_conversations,
        "message_limit": cfg.limit_messages,
        "max_media_bytes": cfg.max_media_bytes,
        "log_file": LOG_FILENAME,
        "console_and_gui_log_level": "INFO",
        "log_file_level": "DEBUG",
        "chat_text_name": cfg.chat_text_name or "auto",
        "external_folder_provided": bool(cfg.external_folder),
    }


def _case_info(cfg: ExportConfig) -> dict[str, str | None]:
    """Build case metadata."""
    return {
        "case_number": cfg.case_number,
        "examiner": cfg.examiner,
        "organization": cfg.organization,
        "description": cfg.case_description,
    }


def build_manifest(
    cfg: ExportConfig,
    *,
    results: dict[str, Any] | None,
    started_at: datetime,
    finished_at: datetime,
    generated_at: datetime,
    status: str,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build the manifest dictionary."""
    out_dir = os.path.abspath(cfg.out_dir)
    return {
        "tool": {
            "name": TOOL_NAME,
            "version": __version__,
            "repository_url": REPOSITORY_URL,
        },
        "case": _case_info(cfg),
        "export": {
            "generated_at": _iso(generated_at),
            "started_at": _iso(started_at),
            "finished_at": _iso(finished_at),
            "duration_seconds": _duration_seconds(started_at, finished_at),
            "timestamp_timezone": "UTC",
            "status": status,
        },
        "input": _input_file_info(cfg),
        "settings": _settings(cfg, results),
        "results": _overall_counts(results),
        "conversations": _conversation_entries(results, out_dir),
        "files": _generated_file_entries(results, out_dir),
        "warnings": [sanitize_local_paths(warning) for warning in (warnings or [])],
        "errors": [sanitize_local_paths(error) for error in (errors or [])],
    }


def _line(label: str, value: Any) -> str:
    """Format one summary line."""
    return f"{label}: {value if value not in (None, '') else '-'}"


def build_summary_text(manifest: dict[str, Any]) -> str:
    """Build `export_summary.txt` content."""
    settings = manifest["settings"]
    counts = manifest["results"]
    output_counts = {
        "normal_pdf": 0,
        "tech_pdf": 0,
        "excel_workbook": 0,
        "media_file": 0,
    }
    for entry in manifest["files"]:
        file_type = entry.get("type")
        if file_type in output_counts:
            output_counts[file_type] += 1

    lines = [
        "ChatExportPDF Export Summary",
        "============================",
        "",
        "Tool Information",
        "----------------",
        _line("Tool name", manifest["tool"]["name"]),
        _line("Tool version", manifest["tool"]["version"]),
        _line("Repository URL", manifest["tool"]["repository_url"]),
        "",
        "Export Information",
        "------------------",
        _line("Generated at", manifest["export"]["generated_at"]),
        _line("Export start time", manifest["export"]["started_at"]),
        _line("Export end time", manifest["export"]["finished_at"]),
        _line("Export duration seconds", manifest["export"]["duration_seconds"]),
        _line("Timestamp timezone", manifest["export"]["timestamp_timezone"]),
        _line("Export status", manifest["export"]["status"]),
        "",
        "Case Information",
        "----------------",
        _line("Case number", manifest["case"]["case_number"]),
        _line("Examiner", manifest["case"]["examiner"]),
        _line("Organization / unit", manifest["case"]["organization"]),
        _line("Description / notes", manifest["case"]["description"]),
        "",
        "Input Information",
        "-----------------",
        _line("Input filename", manifest["input"]["filename"]),
        _line("Input file size", manifest["input"]["size_bytes"]),
        _line("Input MD5", manifest["input"]["md5"]),
        _line("Input SHA256", manifest["input"]["sha256"]),
        "",
        "Export Settings",
        "---------------",
        _line("Selected source", settings["selected_source"]),
        _line("Timezone", settings["timezone"]),
        _line("Time mode", settings["time_mode"]),
        _line("Media export enabled", settings["media_export_enabled"]),
        _line("Image previews enabled", settings["image_previews_enabled"]),
        _line("Excel export enabled", settings["excel_export_enabled"]),
        _line("Conversation limit", settings["conversation_limit"]),
        _line("Message limit", settings["message_limit"]),
        _line("Max media bytes", settings["max_media_bytes"]),
        _line("Log file", settings["log_file"]),
        _line("Console / GUI log level", settings["console_and_gui_log_level"]),
        _line("log.txt level", settings["log_file_level"]),
        _line("Chat text name", settings["chat_text_name"]),
        _line("External folder provided", settings["external_folder_provided"]),
        "",
        "Overall Result Counts",
        "---------------------",
        _line("Number of conversations", counts["conversation_count"]),
        _line("Number of messages", counts["message_count"]),
        _line("Number of participants", counts["participant_count"]),
        _line("Number of attachments", counts["attachment_count"]),
        _line("Number of missing media references", counts["missing_media_count"]),
        _line("Number of skipped media references", counts["skipped_media_count"]),
        _line(
            "Number of unparseable lines",
            counts["unparseable_line_count"],
        ),
        "",
        "Generated Output",
        "----------------",
        _line("Number of normal PDFs", output_counts["normal_pdf"]),
        _line("Number of TECH PDFs", output_counts["tech_pdf"]),
        _line("Number of Excel workbooks", output_counts["excel_workbook"]),
        _line("Number of exported media files", output_counts["media_file"]),
        _line("Generated file inventory", f"{MANIFEST_FILENAME} -> files"),
    ]

    lines.extend(
        [
            "",
            "Conversation Summaries",
            "----------------------",
        ]
    )

    if manifest["conversations"]:
        for index, conversation in enumerate(manifest["conversations"], start=1):
            lines.extend(
                [
                    f"{index}. {conversation.get('title') or '-'}",
                    f"   Conversation ID: {conversation.get('conversation_id') or '-'}",
                    f"   Conversation type: {conversation.get('conversation_type') or '-'}",
                    f"   Participants: {conversation.get('participant_count') or '-'}",
                    f"   Messages: {conversation.get('message_count') or '-'}",
                    f"   Attachments: {conversation.get('attachment_count') or '-'}",
                    "   Generated files:",
                ]
            )
            generated_files = conversation.get("generated_files") or []
            if generated_files:
                lines.extend(f"   - {path}" for path in generated_files)
            else:
                lines.append("   - none")
            lines.append("")
    else:
        lines.append("No conversations exported.")
        lines.append("")

    lines.extend(
        [
            "Warnings and Errors",
            "-------------------",
            "Warnings:",
        ]
    )
    warnings = manifest.get("warnings") or []
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none recorded")
    lines.append("Errors:")
    errors = manifest.get("errors") or []
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- none recorded")

    lines.extend(
        [
            "",
            "Log",
            "---",
            f"Full export log: {LOG_FILENAME}",
            "",
        ]
    )
    return "\n".join(lines)


def write_traceability_files(
    cfg: ExportConfig,
    *,
    results: dict[str, Any] | None,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, str]:
    """Write export_summary.txt and manifest.json for one export run."""
    out_dir = os.path.abspath(cfg.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    manifest = build_manifest(
        cfg,
        results=results,
        started_at=started_at,
        finished_at=finished_at,
        generated_at=utc_now(),
        status=status,
        errors=errors,
        warnings=warnings,
    )
    summary_path = os.path.join(out_dir, EXPORT_SUMMARY_FILENAME)
    manifest_path = os.path.join(out_dir, MANIFEST_FILENAME)
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write(build_summary_text(manifest))
    _append_traceability_file_entries(
        manifest,
        out_dir=out_dir,
        summary_path=summary_path,
        manifest_path=manifest_path,
    )
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "export_summary_path": summary_path,
        "manifest_path": manifest_path,
    }
