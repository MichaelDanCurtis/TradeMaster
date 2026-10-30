import pytest

from tradingagents.ui.brokers.alpaca import AlpacaPaperBroker
from tradingagents.ui.secrets import EnvSecretStore, SecretNotFoundError


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class RecordingHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse({"id": "alpaca_order_1", "status": "accepted"})


def test_alpaca_paper_broker_submits_market_notional_order(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_BROKER_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    broker = AlpacaPaperBroker(
        secret_store=EnvSecretStore(),
        secret_ref="env:TRADEMASTER_ALPACA_BROKER_CREDS",
        http_client=http_client,
        price_estimator=lambda symbol: 839.05,
        base_url="https://paper-api.alpaca.test",
    )

    assert broker.estimate_price("nvda") == 839.05
    order = broker.submit_order(
        intent_id="intent_1",
        symbol="nvda",
        side="buy",
        notional=1000,
    )

    assert http_client.calls[0]["url"] == "https://paper-api.alpaca.test/v2/orders"
    assert http_client.calls[0]["headers"] == {
        "APCA-API-KEY-ID": "paper-key",
        "APCA-API-SECRET-KEY": "paper-secret",
    }
    assert http_client.calls[0]["json"] == {
        "symbol": "NVDA",
        "notional": "1000.00",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "client_order_id": "intent_1",
    }
    assert order.broker == "alpaca"
    assert order.environment == "paper"
    assert order.status == "accepted"
    assert order.broker_order_id == "alpaca_order_1"


def test_alpaca_paper_broker_accepts_versioned_paper_api_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_BROKER_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    broker = AlpacaPaperBroker(
        secret_store=EnvSecretStore(),
        secret_ref="env:TRADEMASTER_ALPACA_BROKER_CREDS",
        http_client=http_client,
        price_estimator=lambda symbol: 839.05,
        base_url="https://paper-api.alpaca.test/v2",
    )

    broker.submit_order(
        intent_id="intent_1",
        symbol="nvda",
        side="buy",
        notional=25,
    )

    assert http_client.calls[0]["url"] == "https://paper-api.alpaca.test/v2/orders"


def test_alpaca_paper_broker_requires_secret_ref():
    broker = AlpacaPaperBroker(
        secret_store=EnvSecretStore(),
        secret_ref="env:MISSING_TRADEMASTER_ALPACA_BROKER_CREDS",
        http_client=RecordingHttpClient(),
        price_estimator=lambda symbol: 100,
    )

    with pytest.raises(SecretNotFoundError):
        broker.submit_order(
            intent_id="intent_1",
            symbol="NVDA",
            side="buy",
            notional=1000,
        )


@pytest.mark.parametrize("price,budget", [(100, 99.99), (100, .01), (float("nan"), 100), (float("inf"), 100), (0, 100)])
def test_invalid_bracket_size_or_quote_fails_before_credentials_or_http(price, budget):
    client = RecordingHttpClient()
    broker = AlpacaPaperBroker(secret_store=EnvSecretStore(), secret_ref="env:MISSING_TEST_SECRET", http_client=client, price_estimator=lambda _: price)
    with pytest.raises(ValueError):
        broker.submit_order("subshare", "AAA", "buy", budget, take_profit=200)
    assert not client.calls


@pytest.mark.parametrize("field,value", [("notional", float("nan")), ("notional", float("inf")), ("notional", -.01), ("notional", .009), ("stop_loss", float("nan")), ("take_profit", 0)])
def test_nonfinite_or_nonpositive_order_values_fail_before_dispatch(field, value):
    client = RecordingHttpClient()
    broker = AlpacaPaperBroker(secret_store=EnvSecretStore(), secret_ref="env:MISSING_TEST_SECRET", http_client=client, price_estimator=lambda _: 100)
    args = {"intent_id": "invalid", "symbol": "AAA", "side": "buy", "notional": 200, field: value}
    with pytest.raises(ValueError):
        broker.submit_order(**args)
    assert not client.calls


def test_decimal_share_boundary_and_notional_rounding_do_not_increase_budget(monkeypatch):
    monkeypatch.setenv("TRADEMASTER_ALPACA_BROKER_CREDS", '{"key_id":"paper-key","secret_key":"paper-secret"}')
    client = RecordingHttpClient()
    broker = AlpacaPaperBroker(secret_store=EnvSecretStore(), secret_ref="env:TRADEMASTER_ALPACA_BROKER_CREDS", http_client=client, price_estimator=lambda _: .1)
    broker.submit_order("whole", "AAA", "buy", .3, take_profit=.2)
    assert client.calls[-1]["json"]["qty"] == "3"
    broker.submit_order("cents", "AAA", "buy", 10.999)
    assert client.calls[-1]["json"]["notional"] == "10.99"
