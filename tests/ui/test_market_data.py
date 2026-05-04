from datetime import datetime, timezone

import pytest

from tradingagents.ui.market_data.alpaca import AlpacaMarketDataProvider
from tradingagents.ui.secrets import EnvSecretStore, SecretNotFoundError


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get(self, url: str, *, headers: dict, params: dict, timeout: float) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "timeout": timeout,
            }
        )
        if url.endswith("/bars"):
            return FakeResponse(
                {
                    "bars": [
                        {
                            "t": "2026-04-30T13:30:00Z",
                            "o": 838.12,
                            "h": 841.0,
                            "l": 836.5,
                            "c": 839.05,
                            "v": 6601542,
                            "vw": 838.71,
                            "n": 9342,
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "quote": {
                    "t": "2026-04-30T13:30:01Z",
                    "bp": 838.95,
                    "bs": 200,
                    "ap": 839.1,
                    "as": 300,
                }
            }
        )


def test_alpaca_provider_fetches_and_normalizes_historical_bars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    provider = AlpacaMarketDataProvider(
        secret_store=EnvSecretStore(),
        secret_ref="env:TRADEMASTER_ALPACA_CREDS",
        http_client=http_client,
        base_url="https://data.alpaca.test",
    )

    bars = provider.historical_bars(
        symbol="nvda",
        start=datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc),
        end=datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc),
        timeframe="1Min",
        limit=100,
        feed="iex",
    )

    assert http_client.calls[0]["url"] == "https://data.alpaca.test/v2/stocks/NVDA/bars"
    assert http_client.calls[0]["headers"] == {
        "APCA-API-KEY-ID": "paper-key",
        "APCA-API-SECRET-KEY": "paper-secret",
    }
    assert http_client.calls[0]["params"]["timeframe"] == "1Min"
    assert http_client.calls[0]["params"]["feed"] == "iex"
    assert bars[0].symbol == "NVDA"
    assert bars[0].timestamp == datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc)
    assert bars[0].open == 838.12
    assert bars[0].vwap == 838.71
    assert bars[0].trade_count == 9342


def test_alpaca_provider_fetches_and_normalizes_latest_quote(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    provider = AlpacaMarketDataProvider(
        secret_store=EnvSecretStore(),
        secret_ref="env:TRADEMASTER_ALPACA_CREDS",
        http_client=http_client,
        base_url="https://data.alpaca.test",
    )

    quote = provider.latest_quote("nvda", feed="iex")

    assert http_client.calls[0]["url"] == "https://data.alpaca.test/v2/stocks/NVDA/quotes/latest"
    assert http_client.calls[0]["params"] == {"feed": "iex"}
    assert quote.symbol == "NVDA"
    assert quote.timestamp == datetime(2026, 4, 30, 13, 30, 1, tzinfo=timezone.utc)
    assert quote.bid_price == 838.95
    assert quote.ask_size == 300


def test_alpaca_provider_requires_configured_secret_ref():
    provider = AlpacaMarketDataProvider(
        secret_store=EnvSecretStore(),
        secret_ref="env:MISSING_TRADEMASTER_ALPACA_CREDS",
        http_client=RecordingHttpClient(),
    )

    with pytest.raises(SecretNotFoundError):
        provider.latest_quote("NVDA")
