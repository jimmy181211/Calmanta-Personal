from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from .store import LocalStore


class LocalObjectStore:
    def __init__(self, root: Path, store: LocalStore, max_bytes: int = 50 * 1024 * 1024):
        self.root = root.resolve()
        self.store = store
        self.max_bytes = max_bytes

    def put_file(self, source: Path, created_at: str, content_type: str = "") -> dict[str, Any]:
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"Object source is not a file: {source}")
        size = source.stat().st_size
        if size > self.max_bytes:
            raise ValueError(f"Object exceeds the {self.max_bytes}-byte local limit")
        digest = _sha256(source)
        suffix = source.suffix.lower()[:20]
        relative = Path(digest[:2]) / f"{digest}{suffix}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        metadata = {
            "object_key": relative.as_posix(),
            "size_bytes": size,
            "sha256": digest,
            "content_type": (
                content_type
                or mimetypes.guess_type(source.name)[0]
                or "application/octet-stream"
            ),
            "source_name": source.name,
            "created_at": created_at,
        }
        self.store.record_object(metadata)
        return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
