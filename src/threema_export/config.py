from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ExportConfig:
    out_dir: str
    source_app: str = "threema"
    input_path: Optional[str] = None
    db_path: Optional[str] = None
    chat_text_name: Optional[str] = None
    external_folder: Optional[str] = None
    tz_name: str = "Europe/Zurich"

    export_media: bool = True
    max_media_bytes: int = 0

    limit_conversations: int = 0
    limit_messages: int = 0

    log_level: str = "INFO"
    log_file: Optional[str] = None

    def resolved_input_path(self) -> str:
        path = self.input_path or self.db_path
        if not path:
            raise ValueError(
                f"source_app={self.source_app} requires --input-path"
                + (" or --db-path" if self.source_app == "threema" else "")
            )
        return path

    def validate(self) -> None:
        if not self.source_app or not self.source_app.strip():
            raise ValueError("source_app must not be empty")
        out = Path(self.out_dir)
        out.mkdir(parents=True, exist_ok=True)

        input_path = Path(self.resolved_input_path())
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Input not found: {input_path}")

        if self.external_folder:
            ext = Path(self.external_folder)
            if not ext.exists() or not ext.is_dir():
                raise FileNotFoundError(f"External folder not found: {ext}")
