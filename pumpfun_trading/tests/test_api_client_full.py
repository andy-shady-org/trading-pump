from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.api.client import PumpFunApiClient


async def test_api_client_lifecycle_and_helpers():
    client = PumpFunApiClient(base_url="https://api.pump.fun", max_retries=2)
    assert client.base_url == "https://api.pump.fun"

    # Helpers
    assert client._pick_first_mapping({"a": {"k": 1}}, "a") == {"k": 1}
    assert client._pick_first_mapping({"a": 123}, "a") == {}
    assert client._pick_first_mapping(None, "a") == {}

    await client.close()


async def test_api_client_requests_and_retries():
    client = PumpFunApiClient(base_url="https://api.pump.fun", max_retries=1)

    # 1. Successful request
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "ok"})
    mock_resp.text = AsyncMock(return_value='{"status": "ok"}')
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.__aexit__.return_value = None

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.request = MagicMock(return_value=mock_resp)

    client._get_session = AsyncMock(return_value=mock_session)
    res = await client.get("/health")
    assert res == {"status": "ok"}

    # 2. POST request
    res_post = await client.post("/submit", json={"data": 123})
    assert res_post == {"status": "ok"}

    # 3. Failed request with retry then exception
    mock_fail_resp = AsyncMock()
    mock_fail_resp.status = 500
    mock_fail_resp.text = AsyncMock(return_value="Server Error")
    mock_fail_resp.__aenter__.return_value = mock_fail_resp
    mock_fail_resp.__aexit__.return_value = None
    mock_session.request = MagicMock(return_value=mock_fail_resp)

    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(RuntimeError):
            await client.get("/fail")

    await client.close()


async def test_api_client_domain_methods():
    client = PumpFunApiClient()

    mock_coin_data = {
        "name": "FunToken",
        "marketCapSol": 100.0,
        "liquidity": {"usd": 50000},
        "holders": {"count": 120},
        "supply": {"total": 1000000000},
        "age": 3600,
    }

    client.get_coin = AsyncMock(return_value=mock_coin_data)
    client.get = AsyncMock(return_value={"data": []})

    # Liquidity snapshot
    liq = await client.get_liquidity_snapshot("Mint1")
    assert liq == {"usd": 50000}

    # Holder counts
    holders = await client.get_holder_counts("Mint1")
    assert holders == {"count": 120}

    # Token supply
    supply = await client.get_token_supply("Mint1")
    assert supply == {"total": 1000000000}

    # Token age
    age = await client.get_token_age("Mint1")
    assert age == {"value": 3600}

    # Market data snapshot
    snapshot = await client.get_market_data_snapshot("Mint1")
    assert snapshot["mint"] == "Mint1"
    assert snapshot["name"] == "FunToken"
    assert snapshot["market_cap_sol"] == 100.0

    # Domain list endpoints
    await client.get_latest_coins(limit=10, offset=0)
    await client.get_advanced_coins_list(limit=10, offset=0)
    await client.get_coin_info("Mint1")
    await client.get_coins_for_you(limit=10)
    await client.get_coins_featured(limit=10)
    await client.get_coins_search("search_term")
    await client.get_trades_for_mint("Mint1")
    await client.get_trade_count("Mint1")
    await client.get_candlesticks("Mint1")
    await client.get_sol_price()
    await client.get_market_overview()

    # Empty payload edge cases
    client.get_coin = AsyncMock(return_value="non-dict")
    assert await client.get_liquidity_snapshot("Mint2") == {}
    assert await client.get_holder_counts("Mint2") == {}
    assert await client.get_token_supply("Mint2") == {}
    assert await client.get_token_age("Mint2") == {}
    assert (await client.get_market_data_snapshot("Mint2"))["payload"] == {}

    client.get_coin = AsyncMock(return_value={"age": None})
    assert await client.get_token_age("Mint3") == {}

    await client.close()

    # Test fallback in get_coin on fresh client
    fallback_client = PumpFunApiClient()
    fallback_client.get = AsyncMock(side_effect=RuntimeError("HTTP 404 Not Found"))
    fallback_client.post = AsyncMock(
        return_value=[{"name": "FallbackCoin", "mint": "Mint1"}]
    )
    coin_fallback = await fallback_client.get_coin("Mint1")
    assert coin_fallback["name"] == "FallbackCoin"
    await fallback_client.close()
