"""Integration tests for multi-provider RPC connection pool within TradingBot runtime."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.infra.rpc_pool import CircuitState
from pumpfun_trading.strategies.base import TradingBotConfig

SAMPLE_PRIVATE_KEY = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4JjaxnjfCebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"


@pytest.mark.asyncio
async def test_bot_rpc_pool_initialization_and_status_snapshot() -> None:
    config = TradingBotConfig(
        strategy_preset="balanced",
        enable_rpc_pool=True,
        rpc_endpoints=(
            "https://primary.rpc.com",
            "https://secondary.rpc.com",
            "https://fallback.rpc.com",
        ),
        rpc_pool_circuit_breaker_threshold=3,
        rpc_pool_circuit_breaker_cooldown_seconds=45.0,
        rpc_pool_broadcast_concurrency=3,
    )

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://primary.rpc.com",
        config=config,
    )

    assert bot.rpc_pool is not None
    assert bot.rpc_pool.endpoint_count == 3
    assert bot.rpc_pool.config.circuit_breaker_threshold == 3
    assert bot.rpc_pool.config.circuit_breaker_cooldown_seconds == 45.0

    snapshot = bot.get_status_snapshot()
    assert snapshot["enable_rpc_pool"] is True
    assert "rpc_pool_telemetry" in snapshot
    telemetry = snapshot["rpc_pool_telemetry"]
    assert telemetry["total_endpoints"] == 3
    assert telemetry["healthy_endpoints"] == 3

    await bot.close()


@pytest.mark.asyncio
async def test_bot_rpc_pool_transparent_query_failover() -> None:
    config = TradingBotConfig(
        enable_rpc_pool=True,
        rpc_endpoints=(
            "https://rpc-node1.solana.com",
            "https://rpc-node2.solana.com",
        ),
    )

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://rpc-node1.solana.com",
        config=config,
    )

    # Mock session where node1 fails (503) and node2 succeeds
    mock_resp_fail = MagicMock()
    mock_resp_fail.status = 503
    mock_resp_fail.text = AsyncMock(return_value="503 Service Unavailable")

    mock_resp_ok = MagicMock()
    mock_resp_ok.status = 200
    mock_resp_ok.text = AsyncMock(
        return_value=json.dumps(
            {
                "jsonrpc": "2.0",
                "result": {
                    "value": {
                        "blockhash": "GHtXQBsoZHVnNFa9YevAzFr17DJjgHXk3ycTKD5xD3Zi"
                    }
                },
                "id": 1,
            }
        )
    )

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    class MockPostContext:
        def __init__(self, url: str) -> None:
            self.url = url

        async def __aenter__(self):
            if "node1" in self.url:
                return mock_resp_fail
            return mock_resp_ok

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.post = MagicMock(
        side_effect=lambda url, **kwargs: MockPostContext(url)
    )
    bot.rpc_pool._session = mock_session

    blockhash = await bot.execution.get_latest_blockhash()
    assert blockhash == "GHtXQBsoZHVnNFa9YevAzFr17DJjgHXk3ycTKD5xD3Zi"

    # Verify node1 degraded and node2 healthy
    node1 = bot.rpc_pool.endpoints[0]
    node2 = bot.rpc_pool.endpoints[1]
    assert node1.state == CircuitState.DEGRADED
    assert node2.state == CircuitState.HEALTHY

    await bot.close()


@pytest.mark.asyncio
async def test_bot_rpc_pool_lifecycle_and_health_loop() -> None:
    config = TradingBotConfig(
        enable_rpc_pool=True,
        rpc_endpoints=(
            "https://rpc1.solana.com",
            "https://rpc2.solana.com",
        ),
        rpc_pool_health_check_interval_seconds=0.1,
    )

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://rpc1.solana.com",
        config=config,
    )

    # Mock health probe response
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(
        return_value=json.dumps({"jsonrpc": "2.0", "result": "ok", "id": 1})
    )

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    class MockPostContext:
        async def __aenter__(self):
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.post = MagicMock(return_value=MockPostContext())
    bot.rpc_pool._session = mock_session

    # Start health loop
    await bot.rpc_pool.start_health_loop()
    assert bot.rpc_pool._running is True
    assert bot.rpc_pool._health_check_task is not None

    # Allow one background tick
    await asyncio.sleep(0.15)

    # Stop health loop
    await bot.rpc_pool.stop_health_loop()
    assert bot.rpc_pool._running is False
    assert bot.rpc_pool._health_check_task is None

    await bot.close()
