from pathlib import Path

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.snapshots import create_snapshot_manifest


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
