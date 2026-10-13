"""Unit tests for multi-provider RPC connection pool, latency tracking, and circuit breakers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.infra.rpc_pool import (
    CircuitState,
    RpcConnectionPool,
    RpcEndpoint,
    RpcPoolConfig,
)


def test_rpc_endpoint_initialization() -> None:
    ep = RpcEndpoint(url="https://mainnet.helius-rpc.com/?api-key=123", weight=1.5)
    assert ep.url == "https://mainnet.helius-rpc.com/?api-key=123"
    assert ep.label == "mainnet.helius-rpc.com"
    assert ep.weight == 1.5
    assert ep.state == CircuitState.HEALTHY
    assert ep.is_available() is True
    assert ep.consecutive_failures == 0
    assert ep.total_requests == 0


def test_rpc_endpoint_latency_percentiles() -> None:
    ep = RpcEndpoint(url="https://rpc.solana.com")
    assert ep.p50_latency_ms == 0.0
    assert ep.p95_latency_ms == 0.0
    assert ep.p99_latency_ms == 0.0
    assert ep.mean_latency_ms == 0.0

    # Single sample: 50ms = 0.05s
    ep.record_success(0.050)
    assert ep.total_requests == 1
    assert ep.p50_latency_ms == 50.0
    assert ep.mean_latency_ms == 50.0

    # Multiple samples: 10ms, 20ms, 30ms, 40ms, 50ms, 60ms, 70ms, 80ms, 90ms, 100ms
    ep.latency_samples.clear()
    for s in [0.010, 0.020, 0.030, 0.040, 0.050, 0.060, 0.070, 0.080, 0.090, 0.100]:
        ep.record_success(s)

    assert ep.p50_latency_ms == 55.0  # Median between 50 and 60
    assert ep.mean_latency_ms == 55.0
    assert ep.p95_latency_ms >= 90.0
    assert ep.p99_latency_ms >= 95.0


def test_rpc_endpoint_circuit_breaker_transitions() -> None:
    ep = RpcEndpoint(url="https://rpc.solana.com")
    now = 1000.0

    # 1st failure -> DEGRADED
    with patch("time.time", return_value=now):
        ep.record_failure(
            "HTTP_500", cooldown_seconds=60.0, circuit_breaker_threshold=3
        )
    assert ep.state == CircuitState.DEGRADED
    assert ep.consecutive_failures == 1
    assert ep.is_available(now) is True

    # 2nd failure -> still DEGRADED
    with patch("time.time", return_value=now + 1.0):
        ep.record_failure(
            "HTTP_502", cooldown_seconds=60.0, circuit_breaker_threshold=3
        )
    assert ep.state == CircuitState.DEGRADED
    assert ep.consecutive_failures == 2

    # 3rd failure reaches threshold -> OPEN
    with patch("time.time", return_value=now + 2.0):
        ep.record_failure(
            "HTTP_503", cooldown_seconds=60.0, circuit_breaker_threshold=3
        )
    assert ep.state == CircuitState.OPEN
    assert ep.consecutive_failures == 3
    assert ep.cooldown_until == now + 2.0 + 60.0
    assert ep.is_available(now + 10.0) is False

    # Check cooldown before expiry
    assert ep.check_health_and_cooldown(now + 50.0) == CircuitState.OPEN
    assert ep.is_available(now + 50.0) is False

    # Check cooldown after expiry -> HALF_OPEN
    assert ep.check_health_and_cooldown(now + 65.0) == CircuitState.HALF_OPEN
    assert ep.is_available(now + 65.0) is True

    # Failed probe in HALF_OPEN -> back to OPEN with new cooldown
    with patch("time.time", return_value=now + 65.0):
        ep.record_failure(
            "HTTP_500", cooldown_seconds=60.0, circuit_breaker_threshold=3
        )
    assert ep.state == CircuitState.OPEN
    assert ep.cooldown_until == now + 65.0 + 60.0

    # Transition to HALF_OPEN again after second cooldown
    assert ep.check_health_and_cooldown(now + 130.0) == CircuitState.HALF_OPEN

    # Success in HALF_OPEN -> HEALTHY
    with patch("time.time", return_value=now + 131.0):
        ep.record_success(0.040)
    assert ep.state == CircuitState.HEALTHY
    assert ep.consecutive_failures == 0


def test_rpc_endpoint_rate_limit_immediate_trip() -> None:
    ep = RpcEndpoint(url="https://rpc.solana.com")
    now = 1000.0

    with patch("time.time", return_value=now):
        ep.record_failure("429 Too Many Requests", cooldown_seconds=90.0)

    assert ep.state == CircuitState.OPEN
    assert ep.rate_limited_count == 1
    assert ep.cooldown_until == now + 90.0
    assert ep.is_available(now + 10.0) is False


def test_rpc_pool_config_serialization() -> None:
    cfg = RpcPoolConfig(
        endpoints=("https://rpc1.com", "https://rpc2.com"),
        health_check_interval_seconds=15.0,
        circuit_breaker_threshold=2,
        circuit_breaker_cooldown_seconds=45.0,
        broadcast_concurrency=4,
        request_timeout_seconds=10.0,
        max_retries_per_query=2,
    )
    data = cfg.to_dict()
    assert data["endpoints"] == ["https://rpc1.com", "https://rpc2.com"]
    assert data["circuit_breaker_threshold"] == 2

    restored = RpcPoolConfig.from_dict(data)
    assert restored.endpoints == ("https://rpc1.com", "https://rpc2.com")
    assert restored.health_check_interval_seconds == 15.0
    assert restored.circuit_breaker_threshold == 2

    # Parse comma-separated string
    str_cfg = RpcPoolConfig.from_dict(
        {"endpoints": "https://rpc1.com, https://rpc2.com, https://rpc3.com"}
    )
    assert str_cfg.endpoints == (
        "https://rpc1.com",
        "https://rpc2.com",
        "https://rpc3.com",
    )


def test_rpc_connection_pool_endpoint_management() -> None:
    pool = RpcConnectionPool(endpoints=["https://rpc1.com", "https://rpc2.com"])
    assert pool.endpoint_count == 2

    # Add duplicate endpoint (ignored)
    pool.add_endpoint("https://rpc1.com")
    assert pool.endpoint_count == 2

    # Add new endpoint
    ep3 = pool.add_endpoint("https://rpc3.com", label="backup_rpc", weight=2.0)
    assert pool.endpoint_count == 3
    assert ep3.label == "backup_rpc"
    assert ep3.weight == 2.0

    # Remove endpoint
    assert pool.remove_endpoint("https://rpc2.com") is True
    assert pool.endpoint_count == 2
    assert pool.remove_endpoint("https://nonexistent.com") is False


def test_rpc_connection_pool_scoring_and_selection() -> None:
    ep_fast = RpcEndpoint(url="https://fast.rpc.com")
    ep_slow = RpcEndpoint(url="https://slow.rpc.com")
    ep_degraded = RpcEndpoint(url="https://degraded.rpc.com")

    for _ in range(5):
        ep_fast.record_success(0.020)  # 20ms
        ep_slow.record_success(0.120)  # 120ms
        ep_degraded.record_success(0.015)  # 15ms base

    ep_degraded.record_failure("HTTP_500")  # Degraded state adds penalty

    pool = RpcConnectionPool(endpoints=[ep_slow, ep_degraded, ep_fast])
    healthy = pool.get_healthy_endpoints()
    assert healthy[0].url == ep_fast.url
    assert pool.get_best_endpoint().url == ep_fast.url


@pytest.mark.asyncio
async def test_rpc_connection_pool_query_success_and_failover() -> None:
    ep1 = RpcEndpoint(url="https://primary.rpc.com", label="primary")
    ep2 = RpcEndpoint(url="https://secondary.rpc.com", label="secondary")
    pool = RpcConnectionPool(endpoints=[ep1, ep2])

    mock_resp_fail = MagicMock()
    mock_resp_fail.status = 503
    mock_resp_fail.text = AsyncMock(return_value="Service Unavailable")

    mock_resp_success = MagicMock()
    mock_resp_success.status = 200
    mock_resp_success.text = AsyncMock(
        return_value=json.dumps({"jsonrpc": "2.0", "result": {"value": 12345}, "id": 1})
    )

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    class MockPostContext:
        def __init__(self, url: str) -> None:
            self.url = url

        async def __aenter__(self):
            if "primary" in self.url:
                return mock_resp_fail
            return mock_resp_success

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.post = MagicMock(
        side_effect=lambda url, **kwargs: MockPostContext(url)
    )
    pool._session = mock_session

    res = await pool.request(
        {"jsonrpc": "2.0", "method": "getSlot", "params": [], "id": 1}
    )
    assert res["result"]["value"] == 12345
    assert ep1.state == CircuitState.DEGRADED
    assert ep2.state == CircuitState.HEALTHY
    assert ep2.total_requests >= 1


@pytest.mark.asyncio
async def test_rpc_connection_pool_broadcast_transaction() -> None:
    ep1 = RpcEndpoint(url="https://rpc1.com", label="rpc1")
    ep2 = RpcEndpoint(url="https://rpc2.com", label="rpc2")
    ep3 = RpcEndpoint(url="https://rpc3.com", label="rpc3")
    pool = RpcConnectionPool(endpoints=[ep1, ep2, ep3])

    valid_sig = "5Ver7TJg34zoxVGzb9Vq59dYn8r7yQk9k4XgE2bM9g4F3nN1K8q7R6"

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    class MockPostContext:
        def __init__(self, url: str) -> None:
            self.url = url

        async def __aenter__(self):
            mock_resp = MagicMock()
            if "rpc2" in self.url:
                mock_resp.status = 429
                mock_resp.text = AsyncMock(return_value="Too Many Requests")
            else:
                mock_resp.status = 200
                mock_resp.text = AsyncMock(
                    return_value=json.dumps(
                        {"jsonrpc": "2.0", "result": valid_sig, "id": 1}
                    )
                )
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.post = MagicMock(
        side_effect=lambda url, **kwargs: MockPostContext(url)
    )
    pool._session = mock_session

    sig = await pool.broadcast_transaction("fake_base64_tx_payload")
    assert sig == valid_sig
    assert ep2.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_rpc_connection_pool_telemetry_and_health_probes() -> None:
    ep1 = RpcEndpoint(url="https://rpc1.com")
    ep2 = RpcEndpoint(url="https://rpc2.com")
    pool = RpcConnectionPool(endpoints=[ep1, ep2])

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    class MockPostContext:
        async def __aenter__(self):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(
                return_value=json.dumps({"jsonrpc": "2.0", "result": "ok", "id": 1})
            )
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.post = MagicMock(return_value=MockPostContext())
    pool._session = mock_session

    health_map = await pool.check_all_health()
    assert health_map["https://rpc1.com"] is True
    assert health_map["https://rpc2.com"] is True

    telemetry = pool.get_telemetry()
    assert telemetry["total_endpoints"] == 2
    assert telemetry["healthy_endpoints"] == 2
    assert len(telemetry["endpoints"]) == 2

    # Clean close
    await pool.close()


@pytest.mark.asyncio
async def test_execution_client_with_rpc_pool_and_builder() -> None:
    from pumpfun_trading.execution.builder import (
        ExecutionBuilder,
        build_execution_client,
    )
    from pumpfun_trading.sdk.execution import PumpFunExecutionClient

    dummy_key = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4JjaxnjfCebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"

    # Single URL
    c1 = PumpFunExecutionClient(dummy_key, "https://api.mainnet-beta.solana.com")
    assert c1.rpc_pool.endpoint_count == 1
    assert c1.rpc_url == "https://api.mainnet-beta.solana.com"
    await c1.close()

    # Multi-endpoint list
    c2 = PumpFunExecutionClient(
        dummy_key,
        rpc_urls=["https://helius.rpc.com", "https://quicknode.rpc.com"],
    )
    assert c2.rpc_pool.endpoint_count == 2
    assert c2.rpc_pool.endpoints[0].url == "https://helius.rpc.com"
    assert c2.rpc_pool.endpoints[1].url == "https://quicknode.rpc.com"
    await c2.close()

    # Builder support
    builder = ExecutionBuilder(
        dummy_key,
        rpc_urls=["https://rpc1.com", "https://rpc2.com"],
    )
    c3 = builder.build()
    assert c3.rpc_pool.endpoint_count == 2
    await c3.close()

    # Functional helper
    c4 = build_execution_client(
        dummy_key,
        rpc_url="https://primary.rpc.com",
    )
    assert c4.rpc_pool.endpoint_count == 1
    await c4.close()
