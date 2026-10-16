from pumpfun_trading.services.market_data import MarketDataService, ResilienceState


class _FailingClient:
    def __init__(self):
        self.calls = 0

    async def get_coin(self, mint: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return {"name": "RecoveredToken", "marketCapSol": 12.5}

    async def get_coin_info(self, mint: str):
        return {"name": "RecoveredToken", "marketCapSol": 12.5}


async def test_market_data_service_falls_back_after_failure():
    client = _FailingClient()
    service = MarketDataService(client)

    result = await service.fetch_with_fallback(
        [
            ("get_coin", [("mint", "abc")]),
            ("get_coin_info", [("mint", "abc")]),
        ],
        timeout=0.1,
        fallback_value={"name": "FallbackToken", "marketCapSol": 7.5},
    )

    assert result == {"name": "RecoveredToken", "marketCapSol": 12.5}
    assert service.resilience.consecutive_failures == 0


async def test_market_data_service_detects_stale_data():
    service = MarketDataService()
    assert not service.is_data_fresh(last_seen_at=None, max_age_seconds=30)
    assert not service.is_data_fresh(last_seen_at=0.0, max_age_seconds=30)


async def test_market_data_service_extracts_market_cap_and_name():
    service = MarketDataService()
    assert await service.get_market_cap_sol({"marketCapSol": 25.0}) == 25.0
    assert await service.get_token_name({"displayName": " Token A "}) == "Token A"


async def test_market_data_service_handles_failures_and_fallbacks():
    class FakeClient:
        async def get_coin(self, mint: str):
            return {"displayName": "  Alpha  ", "marketCapSol": 12.5}

        async def get_coin_info(self, mint: str):
            return {"displayName": "Alpha"}

        async def flaky(self, mint: str):
            raise RuntimeError("temporary failure")

    service = MarketDataService(FakeClient())
    assert await service.get_market_cap_sol({"marketCap": 7.25}) == 7.25
    assert await service.get_market_cap_sol({"market_cap_sol": "9.5"}) == 9.5
    assert await service.get_token_name({"tokenName": " Beta "}) == "Beta"
    assert await service.get_token_name({}) is None
    assert await service.fetch_with_fallback(
        [("flaky", [("mint", "abc")])],
        timeout=0.1,
        fallback_value={"name": "fallback"},
    ) == {"name": "fallback"}
    assert service.is_data_fresh(last_seen_at=0.0, max_age_seconds=1) is False
    assert service.is_data_fresh(last_seen_at=0.0, max_age_seconds=0) is False

    resilience = ResilienceState()
    resilience.record_failure("temporary")
    assert resilience.consecutive_failures == 1
    resilience.record_success()
    assert resilience.last_error is None
