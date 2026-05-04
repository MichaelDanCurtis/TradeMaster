from pathlib import Path

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.snapshots import (
    create_encrypted_snapshot_bundle,
    create_snapshot_manifest,
    verify_encrypted_snapshot_bundle,
)


def _repo(tmp_path: Path) -> UiRepository:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return UiRepository(session_factory)


def test_snapshot_manifest_hashes_database_and_extra_files(tmp_path: Path):
    database_path = tmp_path / "ui.db"
    database_path.write_text("sqlite bytes", encoding="utf-8")
    notes_path = tmp_path / "notes.md"
    notes_path.write_text("advisor note", encoding="utf-8")

    manifest = create_snapshot_manifest(
        database_path=database_path,
        include_paths=[notes_path],
        encryption_mode="age",
        offsite_target="backblaze-b2",
    )

    assert manifest["storage_profile"] == "sqlite-local"
    assert manifest["encryption_mode"] == "age"
    assert manifest["offsite_target"] == "backblaze-b2"
    assert [item["path"] for item in manifest["files"]] == [
        str(database_path),
        str(notes_path),
    ]
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert "secret" not in str(manifest).lower()


def test_snapshot_manifest_can_be_persisted(tmp_path: Path):
    repo = _repo(tmp_path)
    database_path = tmp_path / "ui.db"
    manifest = create_snapshot_manifest(database_path=database_path)

    record = repo.store_snapshot_manifest(
        snapshot_id=manifest["snapshot_id"],
        storage_profile=manifest["storage_profile"],
        encryption_mode=manifest["encryption_mode"],
        offsite_target=manifest["offsite_target"],
        manifest=manifest,
    )
    records = repo.list_snapshot_manifests()

    assert records[0].snapshot_id == record.snapshot_id
    assert records[0].manifest["files"][0]["path"] == str(database_path)


def test_encrypted_snapshot_bundle_writes_ciphertext_and_verifies_manifest(tmp_path: Path):
    database_path = tmp_path / "ui.db"
    database_path.write_text("sqlite bytes", encoding="utf-8")
    notes_path = tmp_path / "notes.md"
    notes_path.write_text("advisor note", encoding="utf-8")

    manifest = create_encrypted_snapshot_bundle(
        database_path=database_path,
        include_paths=[notes_path],
        output_dir=tmp_path / "backups",
        key_material="local backup passphrase",
        offsite_target="manual-offsite",
    )
    artifact_path = Path(manifest["backup_artifact"]["path"])
    raw_artifact = artifact_path.read_bytes()

    assert artifact_path.exists()
    assert b"sqlite bytes" not in raw_artifact
    assert b"advisor note" not in raw_artifact
    assert manifest["encrypted"] is True
    assert manifest["encryption_mode"] == "local-aes-256-gcm"
    assert manifest["backup_artifact"]["algorithm"] == "AES-256-GCM"
    assert manifest["backup_artifact"]["sha256"] == manifest["files"][-1]["sha256"]

    verification = verify_encrypted_snapshot_bundle(
        artifact_path=artifact_path,
        key_material="local backup passphrase",
    )

    assert verification["valid"] is True
    assert verification["manifest"]["snapshot_id"] == manifest["snapshot_id"]
    assert [item["verified"] for item in verification["files"]] == [True, True]


def test_encrypted_snapshot_bundle_rejects_wrong_key(tmp_path: Path):
    database_path = tmp_path / "ui.db"
    database_path.write_text("sqlite bytes", encoding="utf-8")
    manifest = create_encrypted_snapshot_bundle(
        database_path=database_path,
        output_dir=tmp_path / "backups",
        key_material="correct key",
    )

    verification = verify_encrypted_snapshot_bundle(
        artifact_path=Path(manifest["backup_artifact"]["path"]),
        key_material="wrong key",
    )

    assert verification["valid"] is False
    assert verification["reason"] == "decrypt_failed"
