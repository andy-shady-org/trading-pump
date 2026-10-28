import asyncio

import pytest

from trading_pump.services.market_data import MarketDataService, ResilienceState


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


@pytest.mark.regression("BUG-80")
async def test_missing_market_cap_is_zero_not_thirty():
    # BUG-80
    assert await MarketDataService().get_market_cap_sol({}) == 0.0


async def test_market_data_service_fallback_and_resilience_paths():
    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def get_coin(self, mint: str):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")
            return {"displayName": "Recovered Token", "marketCapSol": 21.5}

        async def get_coin_info(self, mint: str):
            return {"displayName": "Recovered Token"}

    service = MarketDataService(AsyncClient())
    assert await service.get_market_cap_sol({"market_cap": "8.25"}) == 8.25
    assert await service.get_market_cap_sol({}) == 0.0
    assert await service.get_token_name({"name": "  Token  "}) == "Token"
    assert await service.get_token_name({}) is None

    fallback_result = await service.fetch_with_fallback(
        [("get_coin", [("mint", "abc")]), ("get_coin_info", [("mint", "abc")])],
        timeout=0.1,
        fallback_value={"name": "fallback"},
    )
    assert fallback_result == {"displayName": "Recovered Token"}

    resilience = ResilienceState()
    resilience.record_failure("temporary")
    assert resilience.last_error == "temporary"
    assert resilience.consecutive_failures == 1
    resilience.record_success()
    assert resilience.last_error is None
    assert resilience.consecutive_failures == 0

    assert (
        service.is_data_fresh(
            last_seen_at=asyncio.get_running_loop().time(), max_age_seconds=0
        )
        is False
    )
    assert service.is_data_fresh(last_seen_at=None, max_age_seconds=30) is False


async def test_market_data_service_handles_missing_client_and_invalid_data():
    service = MarketDataService(api_client=None)
    assert await service.fetch_with_fallback(
        [], fallback_value={"name": "fallback"}
    ) == {"name": "fallback"}

    class BrokenClient:
        async def nope(self):
            return {}

    broken = MarketDataService(BrokenClient())
    assert await broken.fetch_with_fallback(
        [("missing_method", None)],
        fallback_value={"name": "fallback"},
    ) == {"name": "fallback"}

    assert await service.get_market_cap_sol({"marketCapSol": "bad"}) == 0.0
    assert await service.get_token_name({"tokenName": "  "}) is None
