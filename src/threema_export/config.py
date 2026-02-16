from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ExportConfig:
    db_path: str
    out_dir: str
    external_folder: Optional[str] = None
    tz_name: str = "Europe/Zurich"

    export_media: bool = True
    max_media_bytes: int = 0

    limit_conversations: int = 0
    limit_messages: int = 0

    log_level: str = "INFO"
    log_file: Optional[str] = None

    def validate(self) -> None:
        db = Path(self.db_path)
        if not db.exists() or not db.is_file():
            raise FileNotFoundError(f"DB not found: {db}")
        out = Path(self.out_dir)
        out.mkdir(parents=True, exist_ok=True)

        if self.external_folder:
            ext = Path(self.external_folder)
            if not ext.exists() or not ext.is_dir():
                raise FileNotFoundError(f"External folder not found: {ext}")
