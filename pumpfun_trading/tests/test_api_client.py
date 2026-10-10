import asyncio

import pytest

from pumpfun_trading.api.client import PumpFunApiClient


@pytest.mark.asyncio
async def test_build_url_and_headers():
    client = PumpFunApiClient(base_url="https://frontend-api-v3.pump.fun")
    assert client._build_url("/coins/latest").startswith("https://frontend-api-v3.pump.fun")
    assert client.headers["Accept"] == "application/json"
    await client.close()


@pytest.mark.asyncio
async def test_market_overview_wrapper():
    client = PumpFunApiClient()
    assert callable(client.get_market_overview)
    await client.close()

