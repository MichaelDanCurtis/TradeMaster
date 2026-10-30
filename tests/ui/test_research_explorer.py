from fastapi.testclient import TestClient

from tradingagents.ui.research_explorer import explore_market


class Provider:
    def stock_movers(self, *, top):
        assert top == 25
        return {"last_updated": "2026-09-04T20:00:00Z", "gainers": [
            {"symbol": "AAA", "price": 10, "percent_change": 5},
            {"symbol": "BBB", "price": "nan", "percent_change": "inf"},
            {"symbol": "bad/path", "price": 2},
        ], "losers": [{"symbol": "CCC", "price": 2, "percent_change": -20}]}

    def most_active_stocks(self, *, by, top):
        assert (by, top) == ("volume", 25)
        return {"most_actives": [{"symbol": "AAA", "volume": 120000}, {"symbol": "DDD", "volume": -4}]}


def test_source_evidence_merge_and_unknown_values():
    result = explore_market(Provider())
    assert [row.symbol for row in result.candidates] == ["AAA", "CCC", "BBB", "DDD"]
    first = result.candidates[0]
    assert first.sources == ["gainer", "most_active"]
    assert (first.price, first.volume) == (10, 120000)
    assert result.candidates[2].price is None
    assert result.candidates[2].change_pct is None
    assert result.candidates[3].volume is None
    assert result.sources[0].provider_updated_at == "2026-09-04T20:00:00Z"
    assert result.sources[1].provider_updated_at is None
    assert result.observed_at != result.sources[0].provider_updated_at


def test_partial_failure_keeps_other_source_without_exposing_exception():
    class Partial(Provider):
        def stock_movers(self, **kwargs):
            raise RuntimeError("secret-provider-token")
    result = explore_market(Partial())
    assert [row.symbol for row in result.candidates] == ["AAA", "DDD"]
    assert [row.status for row in result.sources] == ["unavailable", "available"]
    assert "secret-provider-token" not in result.model_dump_json()


def test_malformed_and_empty_sources_are_distinguished():
    class Empty(Provider):
        def stock_movers(self, **kwargs):
            return {"gainers": [], "losers": []}
        def most_active_stocks(self, **kwargs):
            return {"error": "unexpected"}
    result = explore_market(Empty())
    assert result.candidates == []
    assert [row.status for row in result.sources] == ["available", "unavailable"]


def test_explorer_route_is_read_only_and_returns_provider_observations(tmp_path):
    from tradingagents.ui.api import create_app
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'explorer.db'}",
                                  market_data_providers={"alpaca-market-data": Provider()}))
    response = client.get("/api/discover/explorer")
    assert response.status_code == 200
    assert response.json()["candidates"][0]["symbol"] == "AAA"
    assert client.post("/api/discover/explorer").status_code == 405
