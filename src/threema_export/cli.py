from __future__ import annotations
import argparse
import logging
from typing import Optional

from .common.logging_setup import setup_logging
from .config import ExportConfig
from .orchestrator import export_all_conversations


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export chat data from supported apps to PDFs with media extraction."
    )
    p.add_argument(
        "--source",
        default="threema",
        help="Source app / importer to use (currently supported: threema)",
    )
    p.add_argument(
        "--db-path",
        required=True,
        help="Path to ThreemaData.sqlite (for source=threema)",
    )
    p.add_argument("--out-dir", required=True, help="Output directory")
    p.add_argument(
        "--external-folder",
        default=None,
        help="Folder containing _EXTERNAL_DATA/EXTERNAL binaries (UUID-named files)",
    )
    p.add_argument(
        "--tz",
        default="Europe/Zurich",
        help="Timezone for rendering timestamps (default: Europe/Zurich)",
    )

    p.add_argument("--no-media", action="store_true", help="Disable media export")
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
        "--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)"
    )
    p.add_argument("--log-file", default=None, help="Optional log file path")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.log_level, args.log_file)
    log = logging.getLogger("threema_export")
    log.info("Starting export with config: %s", vars(args))
    if not args.external_folder:
        log.warning("No --external-folder specified, media export may be incomplete")
    if args.no_media:
        log.info("Media export disabled by --no-media flag")
    if args.max_media_bytes > 0:
        log.info("Will skip media blobs larger than %d bytes", args.max_media_bytes)

    cfg = ExportConfig(
        source_app=args.source,
        db_path=args.db_path,
        out_dir=args.out_dir,
        external_folder=args.external_folder,
        tz_name=args.tz,
        export_media=not args.no_media,
        max_media_bytes=args.max_media_bytes,
        limit_conversations=args.limit_conversations,
        limit_messages=args.limit_messages,
        log_level=args.log_level,
        log_file=args.log_file,
    )

    try:
        res = export_all_conversations(cfg)
    except Exception as e:
        log.exception("Export failed: %s", e)
        return 1

    print("Source app:", res["source_app"])
    print("Detected time_mode:", res.get("time_mode", "unknown"))
    print("External index entries:", res.get("external_index_entries", 0))
    print("Conversations exported:", len(res["exported"]))
    print("Output dir:", res["out_dir"])
    return 0
