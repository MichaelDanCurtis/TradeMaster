from pathlib import Path
import sqlite3
import io
import tarfile

import pytest

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
    with sqlite3.connect(database_path) as db:
        db.execute("CREATE TABLE audit (value TEXT)")
        db.execute("INSERT INTO audit VALUES (?)", ("sqlite bytes",))
    notes_path = tmp_path / "notes.md"
    notes_path.write_text("advisor note", encoding="utf-8")

    manifest = create_snapshot_manifest(
        database_path=database_path,
        include_paths=[notes_path],
        encryption_mode="age",
        offsite_target="backblaze-b2",
    )

    assert manifest["storage_profile"] == "sqlite-local"
    assert manifest["encryption_mode"] == "none"
    assert manifest["encrypted"] is False
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
    with sqlite3.connect(database_path) as db:
        db.execute("CREATE TABLE audit (value TEXT)")
        db.execute("INSERT INTO audit VALUES (?)", ("sqlite bytes",))
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
    with sqlite3.connect(database_path) as db:
        db.execute("CREATE TABLE audit (value TEXT)")
        db.execute("INSERT INTO audit VALUES (?)", ("sqlite bytes",))
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


def test_backup_includes_committed_wal_and_is_a_readable_database(tmp_path):
    source = tmp_path / 'wal.db'
    with sqlite3.connect(source) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE evidence (value TEXT)')
        connection.execute("INSERT INTO evidence VALUES ('committed in WAL')")
        connection.commit()
        manifest = create_encrypted_snapshot_bundle(database_path=source, output_dir=tmp_path/'backups', key_material='audit key')
        result = verify_encrypted_snapshot_bundle(artifact_path=Path(manifest['backup_artifact']['path']), key_material='audit key')
    assert result['valid']
    # Independently decrypt and restore the archived database for a real SQLite check.
    from tradingagents.ui.snapshots import _read_backup_payload, _derive_key, _unb64, _read_snapshot_archive
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import json
    header, ciphertext = _read_backup_payload(Path(manifest['backup_artifact']['path']).read_bytes())
    plaintext = AESGCM(_derive_key('audit key', _unb64(header['salt']), header['iterations'])).decrypt(_unb64(header['nonce']),ciphertext,json.dumps(header,sort_keys=True,separators=(',', ':')).encode())
    archived, files = _read_snapshot_archive(plaintext)
    restored = tmp_path/'restored.db'
    restored.write_bytes(files[archived['files'][0]['archive_name']])
    with sqlite3.connect(restored) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert connection.execute('SELECT value FROM evidence').fetchone() == ('committed in WAL',)


@pytest.mark.parametrize('payload', [b'', b'TRDMASTER-BACKUP-1\n', b'TRDMASTER-BACKUP-1\n\x00\x00\x00\xff{}'])
def test_corrupt_backup_is_a_verification_failure_not_an_exception(tmp_path, payload):
    artifact = tmp_path/'bad.tmbackup'
    artifact.write_bytes(payload)
    assert verify_encrypted_snapshot_bundle(artifact_path=artifact,key_material='key')['valid'] is False


def test_missing_backup_is_a_verification_failure(tmp_path):
    assert verify_encrypted_snapshot_bundle(artifact_path=tmp_path/'gone.tmbackup',key_material='key') == {'valid':False,'reason':'artifact_unavailable'}


def test_database_and_artifacts_recover_to_new_directory_without_overwrite(tmp_path):
    from tradingagents.research.data.store import ArtifactStore
    from tradingagents.ui.restore_backup import restore_backup
    database = tmp_path / "source.db"
    store = ArtifactStore(tmp_path / "artifacts")
    digest = store.put(b"research evidence")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence (digest TEXT)")
        connection.execute("INSERT INTO evidence VALUES (?)", (digest,))
    manifest = create_encrypted_snapshot_bundle(database_path=database, artifact_root=store.root,
        output_dir=tmp_path / "backups", key_material="test-only-key")
    artifact = Path(manifest["backup_artifact"]["path"])
    assert verify_encrypted_snapshot_bundle(artifact_path=artifact, key_material="test-only-key")["valid"]
    destination = tmp_path / "recovered"
    result = restore_backup(artifact, destination, "test-only-key")
    assert result["files_restored"] == 2 and not result["credentials_restored"]
    with sqlite3.connect(destination / "database.sqlite") as connection:
        recovered_digest = connection.execute("SELECT digest FROM evidence").fetchone()[0]
    assert ArtifactStore(destination / ".research-artifacts").get(recovered_digest) == b"research evidence"
    with pytest.raises(ValueError, match="must not exist"):
        restore_backup(artifact, destination, "test-only-key")
    with pytest.raises(Exception):
        restore_backup(artifact, tmp_path / "wrong-key", "incorrect")
    assert not (tmp_path / "wrong-key").exists()


def test_backup_rejects_corrupted_content_addressed_artifact(tmp_path):
    from tradingagents.research.data.store import ArtifactStore
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence (digest TEXT)")
    store = ArtifactStore(tmp_path / "artifacts")
    digest = store.put(b"original")
    store.path(digest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="content hash"):
        create_encrypted_snapshot_bundle(database_path=database, artifact_root=store.root,
            output_dir=tmp_path / "backups", key_material="test-only-key")
