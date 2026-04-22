"""Run the command-line export entry point."""

from __future__ import annotations
import argparse
import logging
from typing import Optional

from .common.logging_setup import setup_logging
from .config_factory import build_export_config
from .constants import DEFAULT_SOURCE_APP, DEFAULT_TIMEZONE, SOURCE_APPS
from .orchestrator import export_all_conversations


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser for all supported export
        options.
    """
    p = argparse.ArgumentParser(
        description="Export chat data from supported apps to PDFs with media extraction."
    )
    p.add_argument(
        "--source",
        default=DEFAULT_SOURCE_APP,
        choices=SOURCE_APPS,
        help="Source app / importer to use (currently supported: threema, whatsapp)",
    )
    p.add_argument(
        "--input-path",
        default=None,
        help="Generic input path for the selected source (e.g. WhatsApp ZIP or Threema DB)",
    )
    p.add_argument(
        "--db-path",
        default=None,
        help="Legacy alias for the Threema SQLite path",
    )
    p.add_argument(
        "--chat-text-name",
        default=None,
        help="For WhatsApp ZIPs with multiple plausible .txt files: exact chat text filename to use",
    )
    p.add_argument("--out-dir", required=True, help="Output directory")
    p.add_argument(
        "--external-folder",
        default=None,
        help="Folder containing _EXTERNAL_DATA/EXTERNAL binaries (UUID-named files)",
    )
    p.add_argument(
        "--tz",
        default=DEFAULT_TIMEZONE,
        help="Timezone for rendering timestamps (default: Europe/Zurich)",
    )

    p.add_argument("--no-media", action="store_true", help="Disable media export")
    p.add_argument(
        "--no-image-previews",
        action="store_true",
        help="Disable inline image previews in the normal PDF export",
    )
    p.add_argument(
        "--excel",
        action="store_true",
        help="Also export each conversation as an Excel workbook",
    )
    p.add_argument(
        "--max-media-bytes",
        type=int,
        default=0,
        help="Skip media blobs larger than this many bytes (0=disable)",
    )

    p.add_argument(
        "--limit-conversations",
        type=int,
        default=0,
        help="Process only first N conversations (0=all)",
    )
    p.add_argument(
        "--limit-messages",
        type=int,
        default=0,
        help="Process only first N messages per conversation (0=all)",
    )

    p.add_argument(
        "--case-number",
        default=None,
        help="Optional case or reference number for export_summary.txt and manifest.json",
    )
    p.add_argument(
        "--examiner",
        default=None,
        help="Optional examiner name or initials for export_summary.txt and manifest.json",
    )
    p.add_argument(
        "--organization",
        default=None,
        help="Optional organization or unit for export_summary.txt and manifest.json",
    )
    p.add_argument(
        "--case-description",
        default=None,
        help="Optional case notes or description for export_summary.txt and manifest.json",
    )

    return p


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI entry point.

    Args:
        argv (Optional[list[str]]): Optional argument vector. ``None`` uses
            ``sys.argv``.

    Returns:
        int: Process exit code. ``0`` indicates success. ``1`` indicates an
        export failure.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = build_export_config(
            out_dir=args.out_dir,
            source_app=args.source,
            input_path=args.input_path,
            db_path=args.db_path,
            chat_text_name=args.chat_text_name,
            external_folder=args.external_folder,
            tz_name=args.tz,
            export_media=not args.no_media,
            export_image_previews=not args.no_image_previews,
            export_excel=args.excel,
            max_media_bytes=args.max_media_bytes,
            limit_conversations=args.limit_conversations,
            limit_messages=args.limit_messages,
            case_number=args.case_number,
            examiner=args.examiner,
            organization=args.organization,
            case_description=args.case_description,
        )
    except Exception as e:
        setup_logging()
        log = logging.getLogger("chat_export")
        log.exception("Export configuration failed: %s", e)
        return 1

    setup_logging(cfg.log_file)
    log = logging.getLogger("chat_export")
    log.debug("Parsed CLI args: %s", vars(args))
    log.info("Starting export source=%s tz=%s", args.source, args.tz)
    log.debug(
        "Export options source=%s media=%s image_previews=%s excel=%s max_media_bytes=%s limit_conversations=%s limit_messages=%s chat_text_name=%s",
        args.source,
        not args.no_media,
        not args.no_image_previews,
        args.excel,
        args.max_media_bytes,
        args.limit_conversations,
        args.limit_messages,
        args.chat_text_name,
    )
    if args.no_media:
        log.info("Media export disabled by --no-media flag")
    if args.no_image_previews:
        log.info("Inline image previews disabled by --no-image-previews flag")
    if args.excel:
        log.info("Excel export enabled")
    if args.max_media_bytes > 0:
        log.info("Will skip media blobs larger than %d bytes", args.max_media_bytes)

    try:
        res = export_all_conversations(cfg)
    except Exception as e:
        log.exception("Export failed: %s", e)
        return 1

    log.info(
        "Completed export source=%s conversations=%s time_mode=%s status=%s",
        res["source_app"],
        len(res["exported"]),
        res.get("time_mode", "unknown"),
        res.get("status", "Completed"),
    )
    log.debug("Completed export output_dir=%s", res["out_dir"])

    print("Source app:", res["source_app"])
    print("Export status:", res.get("status", "Completed"))
    print("Detected time_mode:", res.get("time_mode", "unknown"))
    print("External index entries:", res.get("external_index_entries", 0))
    print("Conversations exported:", len(res["exported"]))
    print("Output dir:", res["out_dir"])
    if res.get("status") == "Failed":
        return 1
    return 0
