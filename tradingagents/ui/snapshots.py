from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.ui.models import new_id


def create_snapshot_manifest(
    *,
    database_path: Path,
    include_paths: list[Path] | None = None,
    encryption_mode: str = "none",
    offsite_target: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    created = created_at or datetime.now(timezone.utc)
    paths = [database_path, *(include_paths or [])]

    return {
        "snapshot_id": new_id("snapshot"),
        "created_at": created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "storage_profile": "sqlite-local",
        "database_path": str(database_path),
        "encryption_mode": encryption_mode,
        "encrypted": encryption_mode != "none",
        "offsite_target": offsite_target,
        "files": [_file_entry(path) for path in paths],
    }


def _file_entry(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
