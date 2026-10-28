"""Unit tests for ``infra/rpc_pool.py`` telemetry redaction (BUG-102)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.infra.rpc_pool import (
    CircuitState,
    RpcConnectionPool,
    RpcEndpoint,
    RpcPoolConfig,
    RpcPoolUnavailableError,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient

KEY = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
HELIUS = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
BASIC_AUTH = "https://user:hunter2@rpc.example.com/"


def test_endpoint_to_dict_masks_api_key_but_keeps_raw_url_in_memory() -> None:
    endpoint = RpcEndpoint(url=HELIUS)

    data = endpoint.to_dict()

    assert data["url"] == "https://mainnet.helius-rpc.com/?api-key=***"
    assert data["label"] == "mainnet.helius-rpc.com"
    assert endpoint.url == HELIUS


@pytest.mark.parametrize(
    ("url", "label"),
    [
        (BASIC_AUTH, "rpc.example.com"),
        ("https://rpc.example.com?token=abc", "rpc.example.com"),
    ],
)
def test_endpoint_label_never_contains_credentials(url: str, label: str) -> None:
    assert RpcEndpoint(url=url).label == label


def test_pool_config_to_dict_masks_endpoints() -> None:
    config = RpcPoolConfig(endpoints=(HELIUS, RpcEndpoint(url=BASIC_AUTH)))

    assert config.to_dict()["endpoints"] == [
        "https://mainnet.helius-rpc.com/?api-key=***",
        "https://***@rpc.example.com/",
    ]


def test_pool_telemetry_contains_no_secret() -> None:
    pool = RpcConnectionPool(endpoints=(HELIUS, BASIC_AUTH))

    text = json.dumps(pool.get_telemetry())

    assert KEY not in text
    assert "hunter2" not in text
    assert pool.get_telemetry()["total_endpoints"] == 2


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
    best_ep = pool.get_best_endpoint()
    assert best_ep is not None
    assert best_ep.url == ep_fast.url


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


async def test_execution_client_with_rpc_pool_and_builder() -> None:
    from pumpfun_trading.execution.builder import (
        ExecutionBuilder,
        build_execution_client,
    )

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


def _pool_with_responses(*bodies):
    pool = RpcConnectionPool(endpoints=["https://a.invalid", "https://b.invalid"])
    responses = []
    for body in bodies:
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value=json.dumps(body))
        responses.append(resp)

    class Ctx:
        def __init__(self, resp):
            self.resp = resp

        async def __aenter__(self):
            return self.resp

        async def __aexit__(self, *exc):
            return None

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(side_effect=[Ctx(r) for r in responses])
    pool._session = session
    return pool


@pytest.mark.regression("BUG-67")
async def test_rpc_pool_node_error_records_failure_and_fails_over():
    pool = _pool_with_responses(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32005, "message": "Node is behind"},
        },
        {"jsonrpc": "2.0", "id": 1, "result": 42},
    )
    parsed = await pool.request({"method": "getSlot"}, max_retries=2)
    assert parsed["result"] == 42
    assert sum(ep.consecutive_failures for ep in pool._endpoints) == 1


@pytest.mark.regression("BUG-67")
async def test_rpc_pool_deterministic_error_returned_without_failover():
    pool = _pool_with_responses(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32002, "message": "compute unit limit exceeded"},
        },
    )
    parsed = await pool.request({"method": "sendTransaction"}, max_retries=2)
    assert parsed["error"]["code"] == -32002
    assert all(ep.consecutive_failures == 0 for ep in pool._endpoints)


async def test_rpc_pool_broadcast_and_health_branches():
    ep1 = RpcEndpoint(url="https://rpc1.solana.com", label="RPC 1")
    ep2 = RpcEndpoint(url="https://rpc2.solana.com", label="RPC 2")
    cfg = RpcPoolConfig(
        endpoints=[ep1, ep2],
        broadcast_concurrency=2,
        circuit_breaker_threshold=2,
    )
    pool = RpcConnectionPool(endpoints=[ep1, ep2], config=cfg)

    # Mock session post responses for broadcast errors
    mock_session = MagicMock()

    # Case 1: HTTP 429
    resp_429 = AsyncMock()
    resp_429.status = 429
    resp_429.text = AsyncMock(return_value="Rate limited")

    mock_session.post.return_value.__aenter__.return_value = resp_429
    pool._session = mock_session

    with pytest.raises(RuntimeError, match="Multi-RPC transaction broadcast failed"):
        await pool.broadcast_transaction("base64_tx_payload")

    assert ep1.state in {CircuitState.DEGRADED, CircuitState.OPEN}

    # Case 2: HTTP 500
    resp_500 = AsyncMock()
    resp_500.status = 500
    resp_500.text = AsyncMock(return_value="Internal Server Error")
    mock_session.post.return_value.__aenter__.return_value = resp_500

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 3: Invalid JSON type (returns string instead of dict)
    resp_str = AsyncMock()
    resp_str.status = 200
    resp_str.text = AsyncMock(return_value="not_a_json_dict")
    resp_str.json = AsyncMock(side_effect=ValueError("json err"))
    mock_session.post.return_value.__aenter__.return_value = resp_str

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 4: JSON contains "error"
    resp_err = AsyncMock()
    resp_err.status = 200
    resp_err.text = AsyncMock(return_value=json.dumps({"error": "Blockhash expired"}))
    resp_err.json = AsyncMock(return_value={"error": "Blockhash expired"})
    mock_session.post.return_value.__aenter__.return_value = resp_err

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 5: Invalid signature (short string)
    resp_bad_sig = AsyncMock()
    resp_bad_sig.status = 200
    resp_bad_sig.text = AsyncMock(return_value=json.dumps({"result": "too_short"}))
    resp_bad_sig.json = AsyncMock(return_value={"result": "too_short"})
    mock_session.post.return_value.__aenter__.return_value = resp_bad_sig

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Check health probes
    resp_health_ok = AsyncMock()
    resp_health_ok.status = 200
    mock_session.post.return_value.__aenter__.return_value = resp_health_ok
    assert await pool.check_endpoint_health(ep1) is True

    resp_health_429 = AsyncMock()
    resp_health_429.status = 429
    mock_session.post.return_value.__aenter__.return_value = resp_health_429
    assert await pool.check_endpoint_health(ep1) is False

    resp_health_500 = AsyncMock()
    resp_health_500.status = 500
    mock_session.post.return_value.__aenter__.return_value = resp_health_500
    assert await pool.check_endpoint_health(ep1) is False

    await pool.close()


async def test_rpc_pool_extended_coverage():
    # RpcEndpoint metrics & score
    ep = RpcEndpoint(url="http://solana.node.internal:8899/rpc")
    assert ep.label == "solana.node.internal:8899"
    assert ep.p50_latency_ms == 0.0
    assert ep.mean_latency_ms == 0.0

    # Add single sample
    ep.record_success(0.05)
    assert ep.p50_latency_ms == 50.0
    assert ep.p95_latency_ms == 50.0
    assert ep.p99_latency_ms == 50.0
    assert ep.mean_latency_ms == 50.0

    # Multiple samples
    for lat in [0.01, 0.02, 0.03, 0.04, 0.10]:
        ep.record_success(lat)
    assert ep.p50_latency_ms > 0.0

    # Score penalties
    ep.state = CircuitState.DEGRADED
    assert ep.get_score() > ep.p50_latency_ms

    ep.state = CircuitState.HALF_OPEN
    assert ep.get_score() > ep.p50_latency_ms

    # Empty URL validation
    pool = RpcConnectionPool()
    with pytest.raises(ValueError, match="Endpoint URL cannot be empty"):
        pool.add_endpoint("")

    # Add duplicate endpoint
    ep_dup = pool.add_endpoint(ep.url, label="Dup")
    assert pool.endpoint_count == 1
    assert pool.add_endpoint(ep) == ep_dup

    # Remove endpoint
    assert pool.remove_endpoint(ep.url) is True
    assert pool.remove_endpoint("non_existent") is False
    assert pool.endpoint_count == 0

    # Requests on empty pool
    with pytest.raises(
        RuntimeError, match="No RPC endpoints configured in connection pool"
    ):
        await pool.request({"jsonrpc": "2.0", "method": "getVersion"})

    with pytest.raises(RuntimeError, match="No RPC endpoints configured for broadcast"):
        await pool.broadcast_transaction("tx_bytes")

    # Request with JSON-RPC error containing 429
    ep_active = pool.add_endpoint("https://rpc.active.solana.com", label="Active")
    mock_session = MagicMock()
    resp_rate_limit = AsyncMock()
    resp_rate_limit.status = 200
    resp_rate_limit.text = AsyncMock(
        return_value=json.dumps(
            {"error": {"code": 429, "message": "Too many requests"}}
        )
    )
    resp_rate_limit.json = AsyncMock(
        return_value={"error": {"code": 429, "message": "Too many requests"}}
    )
    mock_session.post.return_value.__aenter__.return_value = resp_rate_limit
    pool._session = mock_session

    with pytest.raises(RuntimeError, match="All RPC pool query attempts failed"):
        await pool.request({"method": "getBalance"}, max_retries=1)

    assert ep_active.state == CircuitState.OPEN

    # Health check cycle
    resp_ok = AsyncMock()
    resp_ok.status = 200
    mock_session.post.return_value.__aenter__.return_value = resp_ok
    results = await pool.check_all_health()
    assert results.get("https://rpc.active.solana.com") is True
    assert ep_active.state == CircuitState.HEALTHY

    telemetry = pool.get_telemetry()
    assert telemetry["total_endpoints"] == 1
    assert telemetry["healthy_endpoints"] == 1

    await pool.close()


async def test_rpc_pool_factories_and_error_edges():
    # Health loop lifecycle
    ep = RpcEndpoint(url="https://rpc.err.solana.com")
    pool = RpcConnectionPool(
        endpoints=[ep], config=RpcPoolConfig(health_check_interval_seconds=0.01)
    )
    await pool.start_health_loop()
    await pool.start_health_loop()  # idempotent
    await asyncio.sleep(0.05)
    await pool.stop_health_loop()

    # request() with status != 200 and text() exception
    mock_session = MagicMock()
    resp_err = AsyncMock()
    resp_err.status = 502
    resp_err.text = AsyncMock(side_effect=RuntimeError("Text read error"))
    mock_session.post.return_value.__aenter__.return_value = resp_err
    pool._session = mock_session

    with pytest.raises(RuntimeError):
        await pool.request({"method": "getVersion"}, max_retries=1)

    assert ep.state in {CircuitState.DEGRADED, CircuitState.OPEN}

    # broadcast_transaction with status 500 and text() exception
    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("tx_data")

    # broadcast_transaction with status 200 but non-dict json
    resp_200_non_dict = AsyncMock()
    resp_200_non_dict.status = 200
    resp_200_non_dict.json = AsyncMock(return_value="not_a_dict")
    mock_session.post.return_value.__aenter__.return_value = resp_200_non_dict
    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("tx_data")

    # check_endpoint_health with exception
    mock_session.post.side_effect = RuntimeError("Socket dropped")
    assert await pool.check_endpoint_health(ep) is False

    await pool.close()


async def test_multi_rpc_pool_branches():
    from pumpfun_trading.infra.rpc_pool import (
        CircuitState,
        RpcConnectionPool,
        RpcEndpoint,
    )

    ep = RpcEndpoint("https://mainnet.helius-rpc.com/?api-key=test")
    assert ep.label == "mainnet.helius-rpc.com"

    # Empty latency percentile
    assert ep.p50_latency_ms == 0.0

    # Record successes and compute percentiles
    for val in [0.05, 0.08, 0.12, 0.15, 0.20]:
        ep.record_success(val)
    assert ep.p50_latency_ms > 0.0
    assert ep.p95_latency_ms > 0.0
    assert ep.p99_latency_ms > 0.0
    assert ep.mean_latency_ms > 0.0
    assert ep.get_score() > 0.0

    # Record 429 rate limit error
    ep.record_failure("429 Too Many Requests", cooldown_seconds=0.1)
    assert ep.state == CircuitState.OPEN
    assert ep.rate_limited_count == 1
    assert ep.is_available() is False

    # Half open probe transition
    await asyncio.sleep(0.12)
    assert ep.check_health_and_cooldown() == CircuitState.HALF_OPEN
    assert ep.is_available() is True

    # Failed probe in half open restores to open
    ep.record_failure("timeout", cooldown_seconds=10.0)
    assert ep.state == CircuitState.OPEN

    # Pool initialization with endpoints
    pool = RpcConnectionPool(
        [
            "https://rpc1.solana.com",
            "https://rpc2.solana.com",
        ]
    )
    assert pool.endpoint_count == 2
    fastest = pool.get_best_endpoint()
    assert fastest is not None

    # Pool endpoints and healthy
    assert len(pool.endpoints) == 2
    assert len(pool.get_healthy_endpoints()) == 2

    await pool.close()


async def test_rpc_pool_request_and_broadcast_errors():
    from pumpfun_trading.infra.rpc_pool import (
        RpcConnectionPool,
        RpcPoolConfig,
    )

    cfg = RpcPoolConfig(
        circuit_breaker_threshold=1, circuit_breaker_cooldown_seconds=1.0
    )
    pool = RpcConnectionPool(
        endpoints=["https://rpc1.solana.com", "https://rpc2.solana.com"],
        config=cfg,
    )

    mock_resp_429 = AsyncMock()
    mock_resp_429.status = 429
    mock_resp_ok = AsyncMock()
    mock_resp_ok.status = 200
    mock_resp_ok.text = AsyncMock(return_value=json.dumps({"result": {"value": 12345}}))

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__.side_effect = [
        mock_resp_429,
        mock_resp_ok,
    ]
    pool._session = mock_session

    res = await pool.request(
        payload={"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": []},
        max_retries=2,
        timeout_seconds=1.0,
    )
    assert res == {"result": {"value": 12345}}

    empty_pool = RpcConnectionPool([])
    with pytest.raises(RuntimeError, match="No RPC endpoints configured"):
        await empty_pool.broadcast_transaction("base64_tx")

    valid_sig = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    mock_broadcast_session = MagicMock()
    mock_broadcast_resp = AsyncMock()
    mock_broadcast_resp.status = 200
    mock_broadcast_resp.text = AsyncMock(return_value=json.dumps({"result": valid_sig}))
    mock_broadcast_session.post.return_value.__aenter__.return_value = (
        mock_broadcast_resp
    )
    pool._session = mock_broadcast_session

    sig = await pool.broadcast_transaction("base64_tx", max_concurrency=2)
    assert sig == valid_sig

    mock_health_resp = AsyncMock()
    mock_health_resp.status = 200
    mock_health_resp.text = AsyncMock(
        return_value=json.dumps({"result": {"value": 10000}})
    )
    mock_broadcast_session.post.return_value.__aenter__.return_value = mock_health_resp
    is_healthy = await pool.check_endpoint_health(pool.endpoints[0])
    assert is_healthy is True

    await pool.close()


# --- BUG-151: a breaker that actually stops traffic -------------------------------


def _scripted_pool(*statuses: int, endpoints: int = 1, **config: Any) -> tuple:
    """A pool whose POSTs answer with ``statuses`` in order (200 = a result)."""
    urls = [f"https://rpc{i}.invalid/?api-key={KEY}" for i in range(endpoints)]
    pool = RpcConnectionPool(
        endpoints=urls, config=RpcPoolConfig(endpoints=tuple(urls), **config)
    )
    answers = list(statuses)
    posts: list[str] = []

    class Ctx:
        def __init__(self, url: str) -> None:
            posts.append(url)
            status = answers.pop(0) if len(answers) > 1 else answers[0]
            self.resp = MagicMock()
            self.resp.status = status
            body = (
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": 7})
                if status == 200
                else f"max usage reached for api-key={KEY}"
            )
            self.resp.text = AsyncMock(return_value=body)

        async def __aenter__(self):
            return self.resp

        async def __aexit__(self, *exc):
            return None

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(side_effect=lambda url, **_k: Ctx(url))
    pool._session = session
    return pool, posts


@pytest.mark.regression("BUG-151")
async def test_open_breaker_fails_fast_without_sending() -> None:
    # rc.5: with its only endpoint open, the pool still sent every request
    # to it (28,789 failures in a row), so the rate limit never lifted.
    pool, posts = _scripted_pool(429)
    with patch("pumpfun_trading.infra.rpc_pool.asyncio.sleep", AsyncMock()):
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await pool.request({"method": "getAccountInfo"}, max_retries=3)
    assert len(posts) == 1  # the retries saw no available endpoint

    for _ in range(50):
        with pytest.raises(RpcPoolUnavailableError, match="circuit breaker is open"):
            await pool.request({"method": "getAccountInfo"})
    assert len(posts) == 1
    telemetry = pool.get_telemetry()
    assert telemetry["rejected_requests"] == 50
    assert telemetry["requests_by_method"] == {"getAccountInfo": 51}


@pytest.mark.regression("BUG-151")
async def test_rate_limit_error_names_the_cause_without_the_key() -> None:
    pool, _ = _scripted_pool(429)
    with pytest.raises(RuntimeError) as err:
        await pool.request({"method": "getSlot"}, max_retries=0)
    assert "max usage reached" in str(err.value)
    assert KEY not in str(err.value)


@pytest.mark.regression("BUG-151")
def test_cooldown_doubles_per_opening_and_resets_on_success() -> None:
    ep = RpcEndpoint(url="https://rpc.invalid")
    waits = []
    for _ in range(9):
        with patch("pumpfun_trading.infra.rpc_pool.time.time", return_value=1000.0):
            ep.record_failure(
                "429", cooldown_seconds=60.0, initial_cooldown_seconds=1.0
            )
        waits.append(ep.cooldown_until - 1000.0)
    assert waits == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]
    assert ep.last_rate_limited_time == 1000.0
    ep.record_success(0.05)
    assert ep.open_streak == 0
    # Without an initial wait every opening waits the full cooldown, as before.
    ep.record_failure("429", cooldown_seconds=60.0)
    assert ep.cooldown_until - (ep.last_error_time or 0.0) == pytest.approx(60.0)


@pytest.mark.regression("BUG-151")
async def test_half_open_endpoint_takes_one_probe_at_a_time() -> None:
    pool, posts = _scripted_pool(200)
    ep = pool.endpoints[0]
    ep.state = CircuitState.HALF_OPEN
    gate = asyncio.Event()
    original = pool._send

    async def slow_send(*args, **kwargs):
        await gate.wait()
        return await original(*args, **kwargs)

    with patch.object(pool, "_send", slow_send):
        probe = asyncio.create_task(pool.request({"method": "getSlot"}))
        await asyncio.sleep(0)
        assert ep.probe_in_flight is True
        assert not ep.is_available()
        with pytest.raises(RpcPoolUnavailableError):
            await pool.request({"method": "getSlot"})
        gate.set()
        assert (await probe)["result"] == 7
    assert ep.state == CircuitState.HEALTHY
    assert ep.probe_in_flight is False


@pytest.mark.regression("BUG-151")
async def test_cancelled_probe_frees_the_endpoint() -> None:
    pool, _ = _scripted_pool(200)
    ep = pool.endpoints[0]
    ep.state = CircuitState.HALF_OPEN

    async def hang(*_a, **_k):
        await asyncio.Event().wait()

    with patch.object(pool, "_send", hang):
        task = asyncio.create_task(pool.request({"method": "getSlot"}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert ep.probe_in_flight is False and ep.is_available()


@pytest.mark.regression("BUG-151")
async def test_pool_backs_off_then_recovers_after_the_cooldown() -> None:
    pool, posts = _scripted_pool(429, 200, circuit_breaker_initial_cooldown_seconds=1.0)
    clock = [1000.0]
    with patch(
        "pumpfun_trading.infra.rpc_pool.time.time", side_effect=lambda: clock[0]
    ):
        with pytest.raises(RuntimeError):
            await pool.request({"method": "getSlot"}, max_retries=0)
        with pytest.raises(RpcPoolUnavailableError, match=r"next probe in 1\.0s"):
            await pool.request({"method": "getSlot"})
        clock[0] += 1.0
        assert (await pool.request({"method": "getSlot"}))["result"] == 7
    assert len(posts) == 2
    assert pool.endpoints[0].state == CircuitState.HEALTHY


@pytest.mark.regression("BUG-151")
def test_under_pressure_after_a_recent_rate_limit() -> None:
    pool = RpcConnectionPool(endpoints=["https://a.invalid", "https://b.invalid"])
    assert pool.under_pressure(30.0) is False
    a, b = pool.endpoints
    a.last_rate_limited_time = 1000.0
    assert pool.under_pressure(30.0, now=1010.0) is True
    assert pool.under_pressure(30.0, now=1031.0) is False
    for ep in (a, b):
        ep.state = CircuitState.OPEN
        ep.cooldown_until = 2000.0
    assert pool.under_pressure(30.0, now=1100.0) is True


@pytest.mark.regression("BUG-151")
async def test_failed_simulation_does_not_open_the_breaker() -> None:
    # A transaction's own error must not stop every read for a cooldown.
    pool = _pool_with_responses(
        *[
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32002, "message": "slippage"},
            }
            for _ in range(4)
        ]
    )
    for _ in range(4):
        with pytest.raises(RuntimeError):
            await pool.broadcast_transaction("dHg=", max_concurrency=1)
    assert all(ep.state == CircuitState.HEALTHY for ep in pool.endpoints)


def test_pool_config_round_trips_the_initial_cooldown() -> None:
    cfg = RpcPoolConfig.from_dict({"circuit_breaker_initial_cooldown_seconds": 0.5})
    assert cfg.circuit_breaker_initial_cooldown_seconds == 0.5
    assert cfg.to_dict()["circuit_breaker_initial_cooldown_seconds"] == 0.5
