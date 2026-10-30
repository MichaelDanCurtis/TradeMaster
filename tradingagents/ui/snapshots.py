from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from struct import error as StructError, pack, unpack
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from tradingagents.ui.models import new_id


_BACKUP_MAGIC = b"TRDMASTER-BACKUP-1\n"
_KDF_ITERATIONS = 390_000


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
        "encryption_mode": "none",
        "encrypted": False,
        "offsite_target": offsite_target,
        "files": [_file_entry(path) for path in paths],
    }


def create_encrypted_snapshot_bundle(
    *,
    database_path: Path,
    output_dir: Path,
    key_material: str,
    artifact_root: Path | None = None,
    include_paths: list[Path] | None = None,
    offsite_target: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    manifest = create_snapshot_manifest(
        database_path=database_path,
        include_paths=include_paths,
        encryption_mode="local-aes-256-gcm",
        offsite_target=offsite_target,
        created_at=created_at,
    )
    if artifact_root is not None:
        manifest["research_artifact_root"] = str(Path(artifact_root).resolve())
        manifest["scope"] = "database_and_research_artifacts"
    archive_bytes = _snapshot_archive(manifest)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": _KDF_ITERATIONS,
        "salt": _b64(salt),
        "nonce": _b64(nonce),
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = _derive_key(key_material, salt, _KDF_ITERATIONS)
    ciphertext = AESGCM(key).encrypt(nonce, archive_bytes, header_bytes)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"{manifest['snapshot_id']}.tmbackup"
    artifact_path.write_bytes(_BACKUP_MAGIC + pack(">I", len(header_bytes)) + header_bytes + ciphertext)
    artifact_entry = _file_entry(artifact_path)
    manifest["backup_artifact"] = {
        **artifact_entry,
        "algorithm": header["algorithm"],
        "kdf": header["kdf"],
        "verification": "pending",
    }
    manifest["encryption_mode"] = "local-aes-256-gcm"
    manifest["encrypted"] = True
    manifest["files"].append(artifact_entry)
    return manifest


def verify_encrypted_snapshot_bundle(*, artifact_path: Path, key_material: str) -> dict[str, Any]:
    try:
        payload = Path(artifact_path).read_bytes()
    except OSError:
        return {"valid": False, "reason": "artifact_unavailable"}
    try:
        header, ciphertext = _read_backup_payload(payload)
        salt = _unb64(str(header["salt"]))
        nonce = _unb64(str(header["nonce"]))
        iterations = int(header["iterations"])
        header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        plaintext = AESGCM(_derive_key(key_material, salt, iterations)).decrypt(
            nonce,
            ciphertext,
            header_bytes,
        )
    except (InvalidTag, KeyError, ValueError, StructError, TypeError):
        return {"valid": False, "reason": "decrypt_failed"}

    try:
        manifest, files = _read_snapshot_archive(plaintext)
    except (tarfile.TarError, KeyError, ValueError, TypeError, OSError):
        return {"valid": False, "reason": "invalid_archive"}
    verified_files = []
    for entry in manifest["files"]:
        archive_name = entry["archive_name"]
        actual_hash = _sha256_bytes(files[archive_name])
        verified_files.append(
            {
                "path": entry["path"],
                "archive_name": archive_name,
                "expected_sha256": entry["sha256"],
                "actual_sha256": actual_hash,
                "verified": actual_hash == entry["sha256"],
            }
        )
    return {
        "valid": all(item["verified"] for item in verified_files),
        "manifest": manifest,
        "files": verified_files,
    }


def _file_entry(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _snapshot_archive(manifest: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    contents = []
    for entry in manifest["files"]:
        path = Path(entry["path"])
        if str(path) == manifest["database_path"]:
            # SQLite's backup API includes committed WAL pages and gives a consistent image.
            with tempfile.TemporaryDirectory(prefix="trademaster-backup-") as folder:
                target = Path(folder) / "database.sqlite"
                with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
                    if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
                        raise ValueError("Database integrity check failed")
                data = target.read_bytes()
            entry["restore_path"] = "database.sqlite"
            # Enumerate immutable artifacts AFTER the database image. Artifacts
            # are atomically published before their references enter the DB.
            if manifest.get("research_artifact_root"):
                root = Path(manifest["research_artifact_root"])
                for artifact in sorted(root.glob("*/*")):
                    if re.fullmatch(r"[0-9a-f]{64}", artifact.name) is None:
                        continue
                    relative = artifact.relative_to(root)
                    if relative.parts[0] != artifact.name[:2] or artifact.is_symlink() or artifact.parent.is_symlink() or not artifact.is_file():
                        raise ValueError("Invalid research artifact path")
                    artifact_entry = _file_entry(artifact)
                    if artifact_entry["sha256"] != artifact.name:
                        raise ValueError("Research artifact failed its content hash")
                    artifact_entry["restore_path"] = ".research-artifacts/" + relative.as_posix()
                    manifest["files"].append(artifact_entry)
        else:
            data = path.read_bytes()
        if entry.get("restore_path", "").startswith(".research-artifacts/") and _sha256_bytes(data) != path.name:
            raise ValueError("Research artifact changed while reading backup")
        contents.append(data)
        entry.update(size_bytes=len(data), sha256=_sha256_bytes(data))
    archive_manifest = {
        **manifest,
        "encrypted": True,
        "encryption_mode": "local-aes-256-gcm",
        "files": [
            {
                **entry,
                "archive_name": f"files/{index:03d}-{Path(entry['path']).name}",
            }
            for index, entry in enumerate(manifest["files"], start=1)
        ],
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        _add_bytes_to_tar(
            tar,
            "manifest.json",
            json.dumps(archive_manifest, sort_keys=True, indent=2).encode("utf-8"),
        )
        for entry, data in zip(archive_manifest["files"], contents):
            _add_bytes_to_tar(tar, entry["archive_name"], data)
    return buffer.getvalue()


def _read_snapshot_archive(payload: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        manifest_member = tar.getmember("manifest.json")
        manifest_handle = tar.extractfile(manifest_member)
        if manifest_handle is None:
            raise ValueError("snapshot archive missing manifest")
        manifest = json.loads(manifest_handle.read().decode("utf-8"))
        for entry in manifest["files"]:
            member = tar.getmember(entry["archive_name"])
            file_handle = tar.extractfile(member)
            if file_handle is None:
                raise ValueError(f"snapshot archive missing {entry['archive_name']}")
            files[entry["archive_name"]] = file_handle.read()
    return manifest, files


def _add_file_to_tar(tar: tarfile.TarFile, path: Path, archive_name: str) -> None:
    data = Path(path).read_bytes()
    _add_bytes_to_tar(tar, archive_name, data)


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def _read_backup_payload(payload: bytes) -> tuple[dict[str, Any], bytes]:
    if not payload.startswith(_BACKUP_MAGIC):
        raise ValueError("not a TradeMaster backup")
    offset = len(_BACKUP_MAGIC)
    if len(payload) < offset + 4:
        raise ValueError("truncated backup")
    (header_size,) = unpack(">I", payload[offset : offset + 4])
    header_start = offset + 4
    header_end = header_start + header_size
    if header_size > 65536 or header_end >= len(payload):
        raise ValueError("invalid backup header")
    header = json.loads(payload[header_start:header_end].decode("utf-8"))
    if not isinstance(header, dict) or header.get("iterations") != _KDF_ITERATIONS:
        raise ValueError("unsupported backup format")
    return header, payload[header_end:]


def _derive_key(key_material: str, salt: bytes, iterations: int) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    ).derive(key_material.encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
