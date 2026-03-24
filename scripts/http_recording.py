from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "payload"


@dataclass
class HttpRecorder:
    output_dir: Path
    prefix: str = "http"
    metadata_file: Path | None = None
    channel: str = "generic"
    counter: int = 0

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.metadata_file:
            self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

    def record(self, url: str, body: str) -> Path:
        self.counter += 1
        parsed = urlparse(url)
        host = _safe_name(parsed.netloc or "host")
        path = _safe_name(parsed.path or "path")
        filename = f"{self.prefix}-{self.counter:03d}-{host}-{path}.txt"
        out_path = self.output_dir / filename
        out_path.write_text(body)
        self._append_metadata(url=url, out_path=out_path, body_size=len(body))
        return out_path

    def _append_metadata(self, *, url: str, out_path: Path, body_size: int) -> None:
        if not self.metadata_file:
            return
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "channel": self.channel,
            "sequence": self.counter,
            "url": url,
            "saved_path": str(out_path),
            "body_size": body_size,
        }
        with self.metadata_file.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
