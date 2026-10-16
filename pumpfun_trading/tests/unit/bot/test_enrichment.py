"""Unit tests for ``bot/enrichment.py`` stream-payload enrichment (BUG-95)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.enrichment import (
    TokenEnricher,
    creator_initial_buy_pct,
    merge_token_data,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.strategies.base import TradingBotConfig

CREATOR = str(Pubkey.new_unique())
METADATA_URI = "https://ipfs.io/ipfs/QmTestMetadata"


def _strict_config() -> TradingBotConfig:
    """Matches the `conservative` screening thresholds used by the canary."""
    return TradingBotConfig(
        enable_anti_rug_filters=True,
        enable_cluster_analysis=False,
        require_social_links=True,
        min_social_links_count=2,
        max_acceptable_risk_score=30.0,
    )


def _stream_payload(mint: str, *, initial_buy: float = 30_000_000.0) -> dict[str, Any]:
    """PumpPortal `newToken` shape: no socials, no holders."""
    return {
        "mint": mint,
        "traderPublicKey": CREATOR,
        "txType": "create",
        "initialBuy": initial_buy,
        "name": "Stream Token",
        "symbol": "STRM",
        "uri": METADATA_URI,
        "marketCapSol": 30.0,
    }


def _execution_client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


def _rpc_holders(client: PumpFunExecutionClient, mint: str) -> dict[str, Any]:
    _, curve_account = client.get_bonding_curve_pda(mint)
    holders = [
        {"address": curve_account, "amount": str(800_000_000_000_000)},
        {"address": str(Pubkey.new_unique()), "amount": str(30_000_000_000_000)},
    ] + [
        {"address": str(Pubkey.new_unique()), "amount": str(10_000_000_000_000)}
        for _ in range(4)
    ]
    return {"jsonrpc": "2.0", "id": 1, "result": {"value": holders}}


def _api(
    *, coin: Any = None, coin_error: Exception | None = None, uri_json: Any = None
) -> MagicMock:
    api = MagicMock(spec=PumpFunApiClient)
    api.get_coin = AsyncMock(return_value=coin, side_effect=coin_error)
    api.get_creator_coins = AsyncMock(return_value=[])
    api.fetch_token_metadata = AsyncMock(return_value=uri_json or {})
    return api


async def test_enrich_stream_payload_fetches_socials_and_chain_holders() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    api = _api(
        coin={
            "mint": mint,
            "twitter": "https://x.com/streamtoken",
            "telegram": "https://t.me/streamtoken",
        }
    )
    enricher = TokenEnricher(
        api_client=api, execution_client=client, config=_strict_config()
    )

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_holders(client, mint))
    ):
        verdict = await enricher.enrich_and_screen(mint, _stream_payload(mint))

    api.get_coin.assert_awaited_once_with(mint)
    api.fetch_token_metadata.assert_not_awaited()
    assert verdict.passed, verdict.reasons
    assert "Holder distribution data unavailable" not in verdict.reasons
    assert verdict.metadata is not None
    assert verdict.metadata.social_links_count() == 2
    distribution = verdict.holder_distribution
    assert distribution is not None
    curve_pda, _ = client.get_bonding_curve_pda(mint)
    assert distribution.top_holders[0][0] == curve_pda
    assert distribution.compute_top5_non_curve_pct(curve_pda) == pytest.approx(0.07)
    assert distribution.creator_initial_pct == pytest.approx(0.03)


async def test_enrich_falls_back_to_metadata_uri_when_api_has_no_record() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    api = _api(
        coin_error=RuntimeError("HTTP 404"),
        uri_json={
            "name": "ignored",
            "uri": "https://example.invalid/other",
            "twitter": "https://x.com/streamtoken",
            "website": "https://streamtoken.io",
        },
    )
    enricher = TokenEnricher(
        api_client=api, execution_client=client, config=_strict_config()
    )

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_holders(client, mint))
    ):
        verdict = await enricher.enrich_and_screen(mint, _stream_payload(mint))

    api.fetch_token_metadata.assert_awaited_once_with(METADATA_URI)
    assert verdict.passed, verdict.reasons
    assert verdict.metadata is not None
    assert verdict.metadata.name == "Stream Token"
    assert verdict.metadata.metadata_uri == METADATA_URI


async def test_enrich_lookups_time_out_and_report_missing_data() -> None:
    mint = str(Pubkey.new_unique())

    async def _slow(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(5)

    api = _api()
    api.get_coin = AsyncMock(side_effect=_slow)
    api.fetch_token_metadata = AsyncMock(side_effect=_slow)
    execution = MagicMock()
    execution.get_token_largest_accounts = AsyncMock(side_effect=_slow)
    enricher = TokenEnricher(
        api_client=api,
        execution_client=execution,
        config=_strict_config(),
        lookup_timeout_seconds=0.01,
    )

    verdict = await asyncio.wait_for(
        enricher.enrich_and_screen(mint, _stream_payload(mint)), timeout=1.0
    )

    assert not verdict.passed
    assert "Holder distribution data unavailable" in verdict.reasons
    assert any("Insufficient social links" in r for r in verdict.reasons)


async def test_enrich_rejects_creator_initial_buy_over_cap() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    api = _api(
        coin={"twitter": "https://x.com/a", "telegram": "https://t.me/aaa"},
    )
    enricher = TokenEnricher(
        api_client=api, execution_client=client, config=_strict_config()
    )

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_holders(client, mint))
    ):
        verdict = await enricher.enrich_and_screen(
            mint, _stream_payload(mint, initial_buy=150_000_000.0)
        )

    assert not verdict.passed
    assert verdict.flags.get("creator_excess_holding") is True


async def test_fetch_offchain_metadata_ignores_missing_uri_and_bad_payloads() -> None:
    api = _api()
    enricher = TokenEnricher(api_client=api, config=_strict_config())

    assert await enricher._fetch_offchain_metadata({"name": "no uri"}) == {}
    api.fetch_token_metadata = AsyncMock(return_value=["not", "a", "dict"])
    assert await enricher._fetch_offchain_metadata({"uri": METADATA_URI}) == {}


async def test_fetch_largest_holders_without_execution_or_bad_result() -> None:
    assert (
        await TokenEnricher(config=_strict_config())._fetch_largest_holders("M") == []
    )

    execution = MagicMock()
    execution.get_token_largest_accounts = AsyncMock(return_value="garbage")
    enricher = TokenEnricher(execution_client=execution, config=_strict_config())
    assert await enricher._fetch_largest_holders("M") == []


async def test_fetch_coin_without_api_or_non_dict_payload() -> None:
    assert await TokenEnricher(config=_strict_config())._fetch_coin("M") == {}
    api = _api(coin=["not", "a", "dict"])
    enricher = TokenEnricher(api_client=api, config=_strict_config())
    assert await enricher._fetch_coin("M") == {}


def test_label_curve_account_keeps_holders_when_pda_derivation_fails() -> None:
    execution = MagicMock()
    execution.get_bonding_curve_pda.side_effect = ValueError("bad mint")
    enricher = TokenEnricher(execution_client=execution, config=_strict_config())
    holders = [("A", 1), ("B", 2)]

    assert enricher._label_curve_account("bad", holders) == holders


def test_merge_token_data_prefers_non_empty_overlay_values() -> None:
    merged = merge_token_data(
        {"name": "api", "twitter": "https://x.com/a", "uri": "api-uri"},
        {"name": "stream", "twitter": "", "uri": None, "mint": "M"},
    )

    assert merged == {
        "name": "stream",
        "twitter": "https://x.com/a",
        "uri": "api-uri",
        "mint": "M",
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"initialBuy": 50_000_000.0}, 0.05),
        ({"initialBuy": 50_000_000_000_000}, 0.05),
        ({"initialBuy": "20000000"}, 0.02),
        ({}, None),
        ({"initialBuy": 0}, None),
        ({"initialBuy": "n/a"}, None),
    ],
)
def test_creator_initial_buy_pct(
    payload: dict[str, Any], expected: float | None
) -> None:
    result = creator_initial_buy_pct(payload)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)
