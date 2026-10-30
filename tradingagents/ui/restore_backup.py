"""Recover a verified backup into a new directory; never replace a running workspace."""
import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tradingagents.ui.snapshots import (
    _derive_key, _read_backup_payload, _read_snapshot_archive, _sha256_bytes, _unb64,
)


def restore_backup(artifact_path: Path, destination: Path, key_material: str) -> dict:
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Recovery destination must not exist; existing workspaces are never overwritten")
    header, ciphertext = _read_backup_payload(Path(artifact_path).read_bytes())
    authenticated = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    plaintext = AESGCM(_derive_key(key_material, _unb64(header["salt"]), header["iterations"])).decrypt(
        _unb64(header["nonce"]), ciphertext, authenticated)
    manifest, files = _read_snapshot_archive(plaintext)
    names = set()
    with tempfile.TemporaryDirectory(prefix=".trademaster-restore-", dir=destination.parent) as folder:
        staging = Path(folder) / "workspace"
        staging.mkdir()
        for index, entry in enumerate(manifest["files"]):
            data = files[entry["archive_name"]]
            if _sha256_bytes(data) != entry["sha256"]:
                raise ValueError("Backup file failed its content hash")
            relative = entry.get("restore_path") or ("database.sqlite" if entry["path"] == manifest["database_path"] else f"extras/{index:03d}-{Path(entry['path']).name}")
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or not path.parts or relative in names:
                raise ValueError("Backup contains an invalid recovery path")
            names.add(relative)
            target = staging.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        database = staging / "database.sqlite"
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Recovered database failed integrity check")
        # mkdir is exclusive, including against symlink races. Publish files
        # only after all content and database checks pass.
        destination.mkdir()
        for child in staging.iterdir():
            child.rename(destination / child.name)
    return {"destination": str(destination), "snapshot_id": manifest["snapshot_id"],
            "files_restored": len(names), "credentials_restored": False,
            "scope": manifest.get("scope", "database_and_listed_files")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--key-ref", default="env:TRADEMASTER_BACKUP_KEY")
    args = parser.parse_args()
    from dotenv import load_dotenv
    from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore
    load_dotenv()
    if not args.key_ref.startswith(("env:", "keychain:")):
        parser.error("key reference must use env: or keychain:")
    store = EnvSecretStore() if args.key_ref.startswith("env:") else MacKeychainSecretStore()
    try:
        result = restore_backup(args.artifact, args.destination, store.get_secret(args.key_ref))
    except Exception as exc:
        parser.exit(1, f"Recovery failed ({type(exc).__name__}); the running workspace was not changed.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
