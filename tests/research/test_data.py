from datetime import datetime, timezone
import hashlib

import pytest
from pydantic import ValidationError

from tradingagents.research.contracts import SnapshotManifest
from tradingagents.research.data.contracts import Availability, DatasetBundle, MarketBar
from tradingagents.research.data.store import ArtifactIntegrityError, ArtifactStore


def stamp(day, hour=20):
    return f"2020-{day}T{hour:02}:00:00+00:00"


def availability(published, *, revision="original", mode="historical"):
    return {"mode": mode, "event_time": stamp("03-31"), "published_at": published,
            "ingested_at": "2026-01-01T00:00:00Z", "processed_at": "2026-01-01T00:01:00Z",
            "available_at": published, "revision": revision, "latency_assumption": "Fixture historical publication plus zero modeled delay"}


def dataset_payload():
    text = "Quarterly revenue was 100 million USD."
    amended = "Amended quarterly revenue was 90 million USD."
    def doc(identifier, body, published):
        return {"document_id": identifier, "text": body, "text_hash": hashlib.sha256(body.encode()).hexdigest(), "source_url": "https://example.invalid/fixture", "availability": availability(published, revision=identifier)}
    def obs(identifier, doc_id, value, published):
        return {"observation_id": identifier, "instrument_id": "company", "metric": "revenue", "period_start": "2020-01-01", "period_end": "2020-03-31", "period_type": "quarter", "value": value, "original_value": value, "unit": "USD_millions", "reporting_basis": "GAAP", "document_id": doc_id, "availability": availability(published, revision=identifier)}
    return {
        "timezone": "America/New_York",
        "sessions": [{"date": "2020-05-01", "opens_at": stamp("05-01", 13).replace(":00:00", ":30:00"), "closes_at": stamp("05-01")}, {"date": "2020-05-04", "opens_at": stamp("05-04", 13).replace(":00:00", ":30:00"), "closes_at": stamp("05-04")}],
        "bars": [{"instrument_id": "company", "session": "2020-05-01", "open": "100", "high": "101", "low": "99", "close": "100", "volume": 1000, "available_at": stamp("05-01")}, {"instrument_id": "company", "session": "2020-05-04", "open": "50", "high": "51", "low": "49", "close": "50", "volume": 2000, "available_at": stamp("05-04")}],
        "actions": [{"action_id": "split", "instrument_id": "company", "kind": "split", "effective_session": "2020-05-04", "available_at": stamp("05-01"), "split_ratio": "2"}],
        "mappings": [{"instrument_id": "company", "symbol": "OLD", "valid_from": "2010-01-01", "valid_to": "2020-05-01", "known_at": "2010-01-01T00:00:00Z"}, {"instrument_id": "company", "symbol": "NEW", "valid_from": "2020-05-02", "known_at": stamp("05-01")}],
        "documents": [doc("release", text, stamp("05-01", 21)), doc("amendment", amended, stamp("05-04", 21))],
        "financials": [obs("original", "release", "100", stamp("05-01", 21)), obs("revised", "amendment", "90", stamp("05-04", 21))],
    }


def test_fiscal_end_and_later_amendment_do_not_leak():
    data = DatasetBundle.model_validate(dataset_payload())
    assert data.as_of(datetime(2020, 3, 31, tzinfo=timezone.utc)) == []
    assert data.as_of(datetime(2020, 5, 1, 20, tzinfo=timezone.utc)) == []
    assert data.as_of(datetime(2020, 5, 1, 22, tzinfo=timezone.utc))[0].value_usd == 100000000
    assert data.as_of(datetime(2020, 5, 4, 22, tzinfo=timezone.utc))[0].value_usd == 90000000
    assert data.symbol_at("company", datetime(2020, 5, 1, 18, tzinfo=timezone.utc)) == "OLD"
    assert data.symbol_at("company", datetime(2020, 5, 4, 18, tzinfo=timezone.utc)) == "NEW"


def test_observed_availability_includes_actual_receipt_and_processing():
    with pytest.raises(ValidationError, match="receipt"):
        Availability.model_validate(availability(stamp("05-01", 21), mode="observed"))
    with pytest.raises(ValidationError):
        Availability.model_validate({**availability(stamp("05-01")), "available_at": "2020-05-01T20:00:00"})


def test_duplicate_identical_bars_are_idempotent_but_conflicts_fail():
    payload = dataset_payload()
    payload["bars"].append(dict(payload["bars"][0]))
    assert len(DatasetBundle.model_validate(payload).bars) == 2
    payload["bars"][-1]["close"] = "100.5"
    with pytest.raises(ValidationError, match="conflicting"):
        DatasetBundle.model_validate(payload)


def test_missing_bar_is_preserved_and_early_bar_rejected():
    payload = dataset_payload()
    payload["bars"].pop()
    assert len(DatasetBundle.model_validate(payload).bars) == 1
    payload["bars"][0]["available_at"] = stamp("05-01", 19)
    with pytest.raises(ValidationError, match="session closes"):
        DatasetBundle.model_validate(payload)


def test_original_values_units_and_source_integrity_are_validated():
    payload = dataset_payload()
    payload["financials"][0]["original_value"] = "100000000"
    with pytest.raises(ValidationError, match="unscaled"):
        DatasetBundle.model_validate(payload)
    payload = dataset_payload()
    payload["documents"][0]["text"] += " tampered"
    with pytest.raises(ValidationError, match="hash"):
        DatasetBundle.model_validate(payload)


def test_content_addressed_parquet_roundtrip_and_tamper_detection(tmp_path):
    dataset = DatasetBundle.model_validate(dataset_payload())
    store = ArtifactStore(tmp_path)
    artifacts = store.put_dataset(dataset)
    assert artifacts == store.put_dataset(dataset)
    assert store.get(artifacts["bars_parquet"])[:4] == b"PAR1"
    manifest = SnapshotManifest(provider="test", evidence_kind="historical", provenance="Hand-labelled timing fixture", entitlement="test", calendar="test", timezone=dataset.timezone, coverage_start="2020-05-01", coverage_end="2020-05-04", instrument_ids=["company"], artifacts=artifacts, availability="verified_publication")
    assert store.dataset(manifest) == dataset
    with pytest.raises(ValueError):
        store.get("../../secrets")
    store.path(artifacts["dataset"]).write_bytes(b"changed")
    with pytest.raises(ArtifactIntegrityError, match="manifest"):
        store.dataset(manifest)
