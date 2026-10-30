"""Content-addressed artifacts; callers never supply filesystem paths."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path

from tradingagents.research.contracts import SnapshotManifest, canonical_json
from tradingagents.research.data.contracts import DatasetBundle


class ArtifactIntegrityError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()

    def path(self, digest: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("artifact identity must be a SHA-256 hash")
        return self.root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self.path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write and fsync privately, then atomically publish without replacing an
        # existing immutable artifact. Readers cannot observe partial writes.
        import tempfile
        fd, temp = tempfile.mkstemp(prefix=".artifact-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if self.get(digest) != data:
                    raise ArtifactIntegrityError("existing artifact content differs")
        finally:
            os.unlink(temp)
        return digest

    def get(self, digest: str) -> bytes:
        data = self.path(digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ArtifactIntegrityError("artifact content no longer matches its manifest")
        return data

    def put_json(self, value) -> str:
        return self.put(canonical_json(value).encode("utf-8"))

    def json(self, digest: str):
        return json.loads(self.get(digest))

    def put_dataset(self, dataset: DatasetBundle) -> dict[str, str]:
        artifacts = {"dataset": self.put_json(dataset)}
        # Original values remain in canonical JSON; Parquet is a typed tabular
        # export with price strings to preserve exact decimal representations.
        if dataset.bars:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pylist([b.model_dump(mode="json") for b in dataset.bars])
            sink = io.BytesIO()
            pq.write_table(table, sink, compression="zstd")
            artifacts["bars_parquet"] = self.put(sink.getvalue())
        return artifacts

    def dataset(self, manifest: SnapshotManifest) -> DatasetBundle:
        for digest in manifest.artifacts.values():
            self.get(digest)
        if "dataset" not in manifest.artifacts:
            raise ArtifactIntegrityError("snapshot has no dataset artifact")
        bundle = DatasetBundle.model_validate(self.json(manifest.artifacts["dataset"]))
        instruments = {mapping.instrument_id for mapping in bundle.mappings}
        if set(manifest.instrument_ids) != instruments:
            raise ArtifactIntegrityError("manifest and dataset instruments differ")
        if bundle.timezone != manifest.timezone:
            raise ArtifactIntegrityError("manifest and dataset timezones differ")
        if bundle.sessions[0].date != manifest.coverage_start or bundle.sessions[-1].date != manifest.coverage_end:
            raise ArtifactIntegrityError("manifest coverage must match the actual session range")
        modes = {d.availability.mode for d in bundle.documents} | {o.availability.mode for o in bundle.financials} | {n.availability.mode for n in bundle.guidance_notices} | {e.availability.mode for e in bundle.evidence}
        if manifest.evidence_kind != "fixture" and "synthetic" in modes:
            raise ArtifactIntegrityError("synthetic observations cannot be promoted to real evidence")
        if manifest.evidence_kind == "prospective" and modes - {"observed"}:
            raise ArtifactIntegrityError("prospective observations require actual receipt timestamps")
        return bundle
