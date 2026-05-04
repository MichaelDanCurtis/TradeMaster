from datetime import date

import pytest

from tradingagents.ui.portfolio_data.plaid import PlaidPortfolioProvider
from tradingagents.ui.secrets import EnvSecretStore


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

    def post(self, url: str, *, json: dict, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if url.endswith("/accounts/balance/get"):
            return FakeResponse(
                {
                    "accounts": [
                        {
                            "account_id": "acc_1",
                            "name": "Brokerage",
                            "official_name": "Michael Brokerage",
                            "type": "investment",
                            "subtype": "brokerage",
                            "mask": "1234",
                            "balances": {
                                "current": 125000.25,
                                "iso_currency_code": "USD",
                            },
                        }
                    ]
                }
            )
        if url.endswith("/investments/holdings/get"):
            return FakeResponse(
                {
                    "holdings": [
                        {
                            "account_id": "acc_1",
                            "security_id": "sec_nvda",
                            "quantity": 12.5,
                            "institution_price": 839.05,
                            "institution_value": 10488.125,
                            "cost_basis": 8000.0,
                        }
                    ],
                    "securities": [
                        {
                            "security_id": "sec_nvda",
                            "ticker_symbol": "NVDA",
                            "name": "NVIDIA Corporation",
                        }
                    ],
                }
            )
        return FakeResponse(
            {
                "transactions": [
                    {
                        "transaction_id": "txn_1",
                        "account_id": "acc_1",
                        "date": "2026-04-30",
                        "name": "Deposit",
                        "amount": -5000.0,
                        "iso_currency_code": "USD",
                        "category": ["Transfer", "Deposit"],
                    }
                ]
            }
        )


def test_plaid_provider_fetches_read_only_accounts_holdings_and_transactions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "TRADEMASTER_PLAID_CREDS",
        '{"client_id":"client","secret":"sandbox-secret","access_token":"access-sandbox"}',
    )
    http_client = RecordingHttpClient()
    provider = PlaidPortfolioProvider(
        secret_store=EnvSecretStore(),
        secret_ref="env:TRADEMASTER_PLAID_CREDS",
        http_client=http_client,
        base_url="https://plaid.test",
    )

    accounts = provider.accounts()
    holdings = provider.holdings()
    transactions = provider.transactions(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )

    assert http_client.calls[0]["url"] == "https://plaid.test/accounts/balance/get"
    assert http_client.calls[0]["json"] == {
        "client_id": "client",
        "secret": "sandbox-secret",
        "access_token": "access-sandbox",
    }
    assert accounts[0].account_id == "acc_1"
    assert accounts[0].current_balance == 125000.25
    assert holdings[0].symbol == "NVDA"
    assert holdings[0].value == 10488.125
    assert transactions[0].transaction_id == "txn_1"
    assert transactions[0].categories == ["Transfer", "Deposit"]
