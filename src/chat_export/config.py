"""Define validated export configuration objects.

This module contains the immutable runtime configuration used by importers,
renderers, and the orchestrator. It also validates input paths and creates
the top-level output directory.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .constants import DEFAULT_SOURCE_APP, DEFAULT_TIMEZONE

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportConfig:
    """Store one export run configuration.

    Attributes:
        out_dir (str): Base output directory path.
        source_app (str): Importer key. Example: ``threema`` or ``whatsapp``.
        input_path (Optional[str]): Generic source input path.
        db_path (Optional[str]): Threema SQLite database path.
        chat_text_name (Optional[str]): Explicit WhatsApp chat text file name.
        external_folder (Optional[str]): Threema external media directory path.
        tz_name (str): IANA timezone name for rendered timestamps.
        export_media (bool): Enable attachment export.
        export_image_previews (bool): Enable inline image previews in the normal PDF.
        export_excel (bool): Enable additional Excel workbook export.
        max_media_bytes (int): Maximum exported media size in bytes. ``0`` disables the limit.
        limit_conversations (int): Maximum number of exported conversations. ``0`` disables the limit.
        limit_messages (int): Maximum number of exported messages per conversation. ``0`` disables the limit.
        log_level (str): Logging level name.
        log_file (Optional[str]): Export log file path. Defaults to ``log.txt`` in the output directory.
    """

    out_dir: str
    source_app: str = DEFAULT_SOURCE_APP
    input_path: Optional[str] = None
    db_path: Optional[str] = None
    chat_text_name: Optional[str] = None
    external_folder: Optional[str] = None
    tz_name: str = DEFAULT_TIMEZONE

    export_media: bool = True
    export_image_previews: bool = True
    export_excel: bool = False
    max_media_bytes: int = 0

    limit_conversations: int = 0
    limit_messages: int = 0

    log_level: str = "INFO"
    log_file: Optional[str] = None

    def resolved_input_path(self) -> str:
        """Return the effective source input file path.

        Returns:
            str: Resolved input file path from ``input_path`` or ``db_path``.

        Raises:
            ValueError: If no valid input path is configured.
        """
        path = self.input_path or self.db_path
        if not path:
            raise ValueError(
                f"source_app={self.source_app} requires --input-path"
                + (" or --db-path" if self.source_app == "threema" else "")
            )
        log.debug(
            "Resolved input path source=%s path=%s",
            self.source_app,
            path,
        )
        return path

    def validate(self) -> None:
        """Validate configuration paths and create the output directory.

        Returns:
            None: This method validates in place.

        Raises:
            ValueError: If ``source_app`` is empty.
            FileNotFoundError: If the input file or external directory is missing.
        """
        if not self.source_app or not self.source_app.strip():
            raise ValueError("source_app must not be empty")
        out = Path(self.out_dir)
        out.mkdir(parents=True, exist_ok=True)

        input_path = Path(self.resolved_input_path())
        log.debug(
            "Validating config source=%s input=%s out_dir=%s external_folder=%s",
            self.source_app,
            input_path,
            self.out_dir,
            self.external_folder,
        )
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Input not found: {input_path}")

        if self.external_folder:
            ext = Path(self.external_folder)
            if not ext.exists() or not ext.is_dir():
                raise FileNotFoundError(f"External folder not found: {ext}")
        log.debug(
            "Validated config source=%s input=%s out_dir=%s",
            self.source_app,
            input_path,
            out,
        )
