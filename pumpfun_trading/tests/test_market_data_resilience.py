import pytest

from pumpfun_trading.services.market_data import MarketDataService


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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_market_data_service_detects_stale_data():
    service = MarketDataService()
    assert not service.is_data_fresh(last_seen_at=None, max_age_seconds=30)
    assert not service.is_data_fresh(last_seen_at=0.0, max_age_seconds=30)


def test_market_data_service_extracts_market_cap_and_name():
    service = MarketDataService()
    assert asyncio_run(service.get_market_cap_sol({"marketCapSol": 25.0})) == 25.0
    assert (
        asyncio_run(service.get_token_name({"displayName": " Token A "})) == "Token A"
    )


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
