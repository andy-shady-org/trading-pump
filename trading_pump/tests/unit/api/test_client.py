"""Unit tests for ``api/client.py`` token metadata fetching (BUG-95)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_pump.api.client import (
    IPFS_GATEWAY,
    PumpFunApiClient,
    PumpFunApiHttpError,
    resolve_metadata_uri,
)
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_config

CID = "bafkreientcdd2rvizwb3ww42kx6uslbaqglpxph26cpwqoys552wtsj4ti"


async def test_fetch_token_metadata_rewrites_ipfs_scheme() -> None:
    client = PumpFunApiClient()
    request = AsyncMock(return_value={"twitter": "https://x.com/a"})

    with patch.object(client, "_request_once", request):
        result = await client.fetch_token_metadata("ipfs://QmHash")

    request.assert_awaited_once_with("GET", IPFS_GATEWAY + "QmHash")
    assert result == {"twitter": "https://x.com/a"}


async def test_fetch_token_metadata_non_dict_payload_returns_empty() -> None:
    client = PumpFunApiClient()

    with patch.object(client, "_request_once", AsyncMock(return_value="<html>")):
        assert await client.fetch_token_metadata("https://cdn.example/meta") == {}


async def test_scan_active_coins_is_one_attempt_outside_the_breaker() -> None:
    client = PumpFunApiClient(circuit_breaker_threshold=1)
    request = AsyncMock(return_value=[{"mint": "M"}])
    with patch.object(client, "_request_once", request):
        assert await client.scan_active_coins(limit=50) == [{"mint": "M"}]
    request.assert_awaited_once_with(
        "GET",
        "/coins",
        params={
            "limit": 50,
            "offset": 0,
            "sort": "last_trade_timestamp",
            "order": "DESC",
            "includeNsfw": "true",
            "complete": "false",
        },
    )

    failing = AsyncMock(side_effect=RuntimeError("HTTP 429"))
    with patch.object(client, "_request_once", failing):
        with pytest.raises(RuntimeError):
            await client.scan_active_coins()
    # A failed scan never opens the breaker screening depends on.
    assert failing.await_count == 1
    assert client._circuit_failures == 0


async def test_fetch_token_metadata_bypasses_circuit_breaker() -> None:
    client = PumpFunApiClient(circuit_breaker_threshold=1)
    request = AsyncMock(side_effect=RuntimeError("HTTP 504"))

    with patch.object(client, "_request_once", request):
        with pytest.raises(RuntimeError):
            await client.fetch_token_metadata("https://cdn.example/meta")

    assert request.await_count == 1
    assert client._circuit_failures == 0


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (f"ipfs://{CID}", IPFS_GATEWAY + CID),
        (f"https://ipfs.io/ipfs/{CID}", IPFS_GATEWAY + CID),
        (f" https://dweb.link/ipfs/{CID} ", IPFS_GATEWAY + CID),
        ("https://arweave.net/abc", "https://arweave.net/abc"),
    ],
)
def test_resolve_metadata_uri_avoids_rate_limited_gateways(
    uri: str, expected: str
) -> None:
    assert resolve_metadata_uri(uri) == expected


@pytest.mark.parametrize(
    ("status", "calls", "circuit_failures"), [(404, 1, 0), (429, 3, 1), (503, 3, 1)]
)
async def test_request_retries_only_transient_http_errors(
    status: int, calls: int, circuit_failures: int
) -> None:
    client = PumpFunApiClient(max_retries=2, retry_backoff_seconds=0.0)
    request = AsyncMock(side_effect=PumpFunApiHttpError(f"HTTP {status}", status))

    with patch.object(client, "_request_once", request):
        with pytest.raises(PumpFunApiHttpError):
            await client.get("/coins/Mint111")

    assert request.await_count == calls
    assert client._circuit_failures == circuit_failures


@pytest.mark.parametrize("uri", ["", "ar://abc", "file:///etc/passwd"])
async def test_fetch_token_metadata_rejects_unsupported_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        await PumpFunApiClient().fetch_token_metadata(uri)


class _FakeResponse:
    def __init__(self, status: int, payload: str):
        self.status = status
        self._payload = payload

    async def text(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _RetrySession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            return _FakeResponse(500, '{"error": "temporary"}')
        return _FakeResponse(200, '{"ok": true}')


class _FailingSession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return _FakeResponse(500, '{"error": "down"}')


async def test_build_url_and_headers():
    client = PumpFunApiClient(base_url="https://frontend-api-v3.pump.fun")
    assert client._build_url("/coins/latest").startswith(
        "https://frontend-api-v3.pump.fun"
    )
    assert client.headers["Accept"] == "application/json"
    await client.close()


async def test_market_overview_wrapper():
    client = PumpFunApiClient()
    assert callable(client.get_market_overview)
    await client.close()


async def test_request_retries_and_recovers():
    session = _RetrySession()
    client = PumpFunApiClient(
        session=session,
        max_retries=3,
        retry_backoff_seconds=0.01,
    )

    result = await client.request("GET", "/health")

    assert result == {"ok": True}
    assert session.calls == 3
    await client.close()


async def test_request_opens_circuit_after_failures():
    session = _FailingSession()
    client = PumpFunApiClient(
        session=session,
        max_retries=0,
        circuit_breaker_threshold=1,
        circuit_cooldown_seconds=30.0,
    )

    with pytest.raises(RuntimeError, match="HTTP 500"):
        await client.request("GET", "/health")

    with pytest.raises(RuntimeError, match="circuit open"):
        await client.request("GET", "/health")

    assert session.calls == 1
    await client.close()


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


MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.mark.regression("BUG-74", "BUG-93")
async def test_get_coins_by_mints_reuses_own_session():
    api = PumpFunApiClient()
    api.post = AsyncMock(return_value=[{"mint": MINT}])
    assert await api.get_coins_by_mints([MINT]) == [{"mint": MINT}]
    api.post.assert_awaited_once_with(
        "https://frontend-api-v3.pump.fun/coins-v2/mints", json={"mints": [MINT]}
    )


async def test_api_client_all_methods_and_options():
    client = PumpFunApiClient(base_url="https://api.pump.fun")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": []})
    mock_resp.text = AsyncMock(return_value='{"data": []}')
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.__aexit__.return_value = None

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.request = MagicMock(return_value=mock_resp)
    client._get_session = AsyncMock(return_value=mock_session)

    # Call with options
    await client.get("/test", params={"q": "sol"}, headers={"X-Custom": "val"})
    await client.get_latest_coins(limit=50, offset=10)
    await client.get_advanced_coins_list(
        limit=20, offset=5, sort="market_cap", order="desc", include_nsfw=True
    )
    await client.get_coins_for_you(limit=15, offset=5)
    await client.get_coins_featured(limit=5)
    await client.get_coins_search("pepe", limit=10, offset=0)
    await client.get_trades_for_mint(SAMPLE_MINT, limit=25, offset=0)
    await client.get_trade_count(SAMPLE_MINT)
    await client.get_candlesticks(SAMPLE_MINT, interval="5m", limit=50)
    await client.get_sol_price()
    await client.get_market_overview()

    # Error handling on non-200 text vs json
    mock_err_resp = AsyncMock()
    mock_err_resp.status = 400
    mock_err_resp.text = AsyncMock(return_value="Bad Request Message")
    mock_err_resp.__aenter__.return_value = mock_err_resp
    mock_err_resp.__aexit__.return_value = None
    mock_session.request = MagicMock(return_value=mock_err_resp)

    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="Bad Request Message"):
            await client.get("/error")

    await client.close()


async def test_api_client_snapshot_fallbacks():
    client = PumpFunApiClient()

    client.get_coin = AsyncMock(
        return_value={"name": "NestedCoin", "marketCapSol": 42.0}
    )
    snap = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap["name"] == "NestedCoin"
    assert snap["market_cap_sol"] == 42.0

    client.get_coin = AsyncMock(
        return_value={"displayName": "ItemCoin", "marketCap": 50.0}
    )
    snap2 = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap2["name"] == "ItemCoin"

    client.get_coin = AsyncMock(
        return_value={"tokenName": "ResultCoin", "marketCap": 1000.0}
    )
    snap3 = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap3["name"] == "ResultCoin"

    # get_token_age variants
    client.get_coin = AsyncMock(return_value={"age": {"days": 10}})
    assert await client.get_token_age(SAMPLE_MINT) == {"days": 10}

    # get_coin 500 error not caught
    err_client = PumpFunApiClient()
    err_client.get = AsyncMock(side_effect=RuntimeError("HTTP 500 Internal Error"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await err_client.get_coin(SAMPLE_MINT)
    await err_client.close()

    # get_session creation and close
    await client.close()
    session = await client._get_session()
    assert session is not None
    await client.close()


async def test_api_client_missing_branches():
    client = PumpFunApiClient(base_url="https://api.pump.fun")

    # get_coins_by_mints
    client.post = AsyncMock(return_value=[{"mint": SAMPLE_MINT}])
    coins_by_mints = await client.get_coins_by_mints([SAMPLE_MINT])
    assert coins_by_mints is not None

    # get_coin with fallback payload having 'data' or 'items'
    fallback_client = PumpFunApiClient()
    fallback_client.get = AsyncMock(side_effect=RuntimeError("HTTP 404"))
    fallback_client.post = AsyncMock(
        return_value={"data": [{"mint": SAMPLE_MINT, "name": "CoinData"}]}
    )
    coin_data = await fallback_client.get_coin(SAMPLE_MINT)
    assert coin_data["name"] == "CoinData"

    fallback_client.post = AsyncMock(
        return_value={"items": [{"mint": SAMPLE_MINT, "name": "CoinItems"}]}
    )
    coin_items = await fallback_client.get_coin(SAMPLE_MINT)
    assert coin_items["name"] == "CoinItems"

    # get_coin not found after post
    fallback_client.post = AsyncMock(return_value={"other": []})
    with pytest.raises(
        RuntimeError, match="not found via the public Pump.fun metadata"
    ):
        await fallback_client.get_coin(SAMPLE_MINT)

    # get_coin_info invalid type
    client.get_coin = AsyncMock(return_value="string_not_dict")
    with pytest.raises(ValueError):
        await client.get_coin_info(SAMPLE_MINT)

    await client.close()
    await fallback_client.close()


async def test_api_client_context_manager_and_text_response():
    from trading_pump.api.client import PumpFunApiClient

    async with PumpFunApiClient() as client:
        # Mock _get_session request returning non-json string
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="plain non-json response text")

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock()
            )
        )
        client._session = mock_session

        res = await client.request("GET", "/health")
        assert res == "plain non-json response text"


async def test_api_client_and_replay_and_main_branches():
    from trading_pump.api.client import PumpFunApiClient
    from trading_pump.cli.main import main
    from trading_pump.engines.replay import (
        PaperTradingEngine,
        render_replay_dashboard,
        render_replay_summary,
        render_replay_trades,
    )

    # 1. ApiClient retries and error branches
    api = PumpFunApiClient(max_retries=2, retry_backoff_seconds=0.01)
    mock_session = MagicMock()
    # A MagicMock ``closed`` is truthy, which made the client open a real
    # session and call the live API; the client also uses ``request``, not ``get``.
    mock_session.closed = False
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Server error")
    mock_session.request.return_value.__aenter__.return_value = mock_resp
    api._session = mock_session

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await api.get(f"/coins/{SAMPLE_MINT}")
    assert mock_session.request.call_count == 3

    # get_coin fallback parsing branches
    api.get = AsyncMock(side_effect=RuntimeError("HTTP 404 Not Found"))
    api.post = AsyncMock(return_value=[{"mint": SAMPLE_MINT, "name": "CoinList"}])
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinList"

    api.post = AsyncMock(
        return_value={"data": [{"mint": SAMPLE_MINT, "name": "CoinData"}]}
    )
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinData"

    api.post = AsyncMock(
        return_value={"items": [{"mint": SAMPLE_MINT, "name": "CoinItems"}]}
    )
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinItems"

    api.post = AsyncMock(return_value={"data": []})
    with pytest.raises(
        RuntimeError, match="not found via the public Pump.fun metadata endpoints"
    ):
        await api.get_coin(SAMPLE_MINT)

    # get_holder_counts when get_coin returns non-dict
    api.get_coin = AsyncMock(return_value=None)
    assert await api.get_holder_counts(SAMPLE_MINT) == {}

    await api.close()

    # 2. ReplayEngine with momentum and graduation simulation
    cfg = make_config(
        dry_run=True,
        buy_amount_sol=0.02,
        enable_momentum_signals=True,
        enable_raydium_migration_sniping=True,
    )
    paper = PaperTradingEngine(
        initial_cash=10.0,
        strategy_config=cfg,
    )

    # Feed snapshots that trigger buy, trailing stop, take profit, and graduation
    snapshots = [
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1000.0,
            "market_cap_sol": 30.0,
            "price_sol": 0.00003,
            "is_buy": True,
            "sol_amount": 1.0,
            "user": "Trader1",
            "trade_records": [
                {"is_buy": True, "sol_amount": 1.0, "user": "T1", "timestamp": 1000.0},
                {"is_buy": True, "sol_amount": 1.0, "user": "T2", "timestamp": 1000.0},
                {"is_buy": True, "sol_amount": 1.0, "user": "T3", "timestamp": 1000.0},
            ],
            "real_sol_reserves": 82.0,
            "virtual_sol_reserves": 112.0,
            "complete": False,
        },
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1020.0,
            "market_cap_sol": 65.0,  # 2x+ take profit trigger
            "price_sol": 0.000065,
            "is_buy": True,
            "sol_amount": 1.0,
            "user": "Trader2",
            "real_sol_reserves": 85.0,
            "virtual_sol_reserves": 115.0,
            "complete": True,
        },
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1030.0,
            "market_cap_sol": 85.0,
            "price_sol": 0.000085,
            "sell_signal": True,
        },
    ]
    summary = paper.run(snapshots)
    assert summary is not None

    render_replay_summary(summary)
    render_replay_trades(summary.get("trades", []))
    render_replay_dashboard(summary)

    # 3. Main CLI parser with --help / replay --help
    with patch("sys.argv", ["trading_pump", "--help"]), pytest.raises(SystemExit):
        main()

    with (
        patch("sys.argv", ["trading_pump", "replay", "--help"]),
        pytest.raises(SystemExit),
    ):
        main()
