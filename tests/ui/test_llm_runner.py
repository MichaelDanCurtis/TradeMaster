import pytest

from tradingagents.ui.llm_runner import _confidence_value, _extract_json_payload


def test_extract_json_payload_accepts_surrounded_local_model_output():
    payload = _extract_json_payload(
        'Here is the JSON:\n{"rating":"Neutral","action":"Hold","confidence":0.5}\nDone.'
    )

    assert payload["rating"] == "Neutral"
    assert payload["action"] == "Hold"


def test_extract_json_payload_accepts_fenced_json():
    payload = _extract_json_payload(
        '```json\n{"rating":"Overweight","action":"Buy","confidence":0.7}\n```'
    )

    assert payload["rating"] == "Overweight"
    assert payload["action"] == "Buy"


def test_extract_json_payload_rejects_non_json_text():
    with pytest.raises(ValueError):
        _extract_json_payload("I would hold this stock.")


def test_extract_json_payload_recovers_required_fields_from_near_json():
    payload = _extract_json_payload(
        '{\n'
        '  "rating": "Buy",\n'
        '  "action": "Buy",\n'
        '  "thesis": "Strong setup."",\n'
        '  "risk_notes": "Review sizing.",\n'
        '  "confidence": "Moderate to High",\n'
        '  "extra": {"ignored": true}\n'
        '}'
    )

    assert payload["rating"] == "Buy"
    assert payload["action"] == "Buy"
    assert payload["thesis"] == "Strong setup."
    assert payload["confidence"] == "Moderate to High"


def test_confidence_value_normalizes_local_model_words():
    assert _confidence_value("Moderate to High") == 0.75
    assert _confidence_value("medium") == 0.55
    assert _confidence_value("low") == 0.3
    assert _confidence_value(1.4) == 1.0
