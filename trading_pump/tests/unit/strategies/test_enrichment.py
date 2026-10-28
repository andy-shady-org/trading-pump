"""Unit tests for ``bot/enrichment.py`` stream-payload enrichment (BUG-95)."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from trading_pump.api.client import PumpFunApiClient
from trading_pump.strategies.enrichment import (
    SCREENING_EVENT,
    TokenEnricher,
    count_launches_last_24h,
    creator_initial_buy_pct,
    merge_token_data,
    mayhem_mode_reason,
    non_pump_launch_reason,
    resolve_creator,
    screening_snapshot,
)
from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.strategies.filters import (
    DevWalletProfile,
    HolderDistribution,
    ScreeningCache,
    ScreeningSettings,
    TokenMetadata,
    TokenScreeningVerdict,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_screening

CREATOR = str(Pubkey.new_unique())
METADATA_URI = "https://ipfs.io/ipfs/QmTestMetadata"


def _strict_config() -> ScreeningSettings:
    """Matches the `conservative` screening thresholds used by the canary."""
    return make_screening(
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


@pytest.mark.regression("BUG-95")
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


async def test_token_enricher_disabled():
    config = make_screening(
        enable_anti_rug_filters=False)
    enricher = TokenEnricher(config=config)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert verdict.passed
    assert verdict.risk_score == 0.0


async def test_token_enricher_cache_hit():
    cache = ScreeningCache(default_ttl=60)
    cached = TokenScreeningVerdict(mint="Mint111", passed=True, risk_score=10.0)
    cache.set("Mint111", cached)

    config = make_screening(
        enable_anti_rug_filters=True)
    enricher = TokenEnricher(config=config, screening_cache=cache)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert verdict is cached


async def test_token_enricher_with_mock_api():
    mock_api = MagicMock(spec=PumpFunApiClient)
    mock_api.get_coin = AsyncMock(
        return_value={
            "mint": "Mint111",
            "name": "TestToken",
            "creator": "Creator111",
            "creatorHoldingPct": 0.05,
            "holders": [
                {"address": "Holder1", "amount": 100_000},
                {"address": "Holder2", "amount": 50_000},
            ],
            "totalSupply": 1_000_000_000,
        }
    )
    mock_api.get_creator_coins = AsyncMock(
        return_value=[
            {"mint": "Past1", "created_timestamp": 1_000_000_000_000},
        ]
    )

    config = make_screening(
        enable_anti_rug_filters=True, max_acceptable_risk_score=50.0
    )
    enricher = TokenEnricher(api_client=mock_api, config=config)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert isinstance(verdict, TokenScreeningVerdict)
    assert verdict.passed


@pytest.mark.regression("BUG-58")
def test_24h_launch_count_keeps_zero_and_handles_seconds():
    # BUG-58
    now = 2_000_000_000.0
    old = [{"created_timestamp": (now - 5 * 86400) * 1000}] * 7
    assert count_launches_last_24h(old, now=now) == 0
    recent = [{"createdAt": now - 60}, {"created_timestamp": (now - 120) * 1000}]
    assert count_launches_last_24h(recent + old, now=now) == 2


# --- BUG-107: holder lookups that flap between data and [] ------------------------

_EMPTY_HOLDERS: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}


def _socials_api() -> MagicMock:
    return _api(coin={"twitter": "https://x.com/a", "telegram": "https://t.me/aaa"})


@pytest.mark.regression("BUG-107")
async def test_enrich_retries_empty_holder_answer_until_the_node_has_it() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    enricher = TokenEnricher(
        api_client=_socials_api(), execution_client=client, config=_strict_config()
    )
    request = AsyncMock(
        side_effect=[_EMPTY_HOLDERS, _EMPTY_HOLDERS, _rpc_holders(client, mint)]
    )

    with patch.object(client.rpc_pool, "request", request):
        verdict = await enricher.enrich_and_screen(mint, _stream_payload(mint))

    assert request.await_count == 3
    assert "Holder distribution data unavailable" not in verdict.reasons
    assert verdict.holder_distribution is not None
    assert len(verdict.holder_distribution.top_holders) == 6
    assert enricher.holder_lookup_stats == {"ok_after_retry": 1}


@pytest.mark.parametrize(
    "side_effect, outcome",
    [
        (lambda *_a, **_k: _EMPTY_HOLDERS, "empty"),
        (RuntimeError("HTTP 429"), "error"),
    ],
)
async def test_fetch_largest_holders_gives_up_after_bounded_attempts(
    side_effect: Any, outcome: str
) -> None:
    client = _execution_client()
    enricher = TokenEnricher(execution_client=client, config=_strict_config())
    request = AsyncMock(side_effect=side_effect)

    with patch.object(client.rpc_pool, "request", request):
        holders = await enricher._fetch_largest_holders(str(Pubkey.new_unique()))

    assert holders == []
    assert request.await_count == 4
    assert enricher.holder_lookup_stats == {outcome: 1}


async def test_fetch_largest_holders_counts_a_timeout() -> None:
    async def _slow(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(5)

    execution = MagicMock()
    execution.get_token_largest_accounts = AsyncMock(side_effect=_slow)
    enricher = TokenEnricher(
        execution_client=execution,
        config=_strict_config(),
        lookup_timeout_seconds=0.01,
    )

    assert await enricher._fetch_largest_holders("Mint111") == []
    assert enricher.holder_lookup_stats == {"timeout": 1}


@pytest.mark.regression("BUG-107")
@pytest.mark.parametrize("require_holder_data, passes", [(False, True), (True, False)])
async def test_require_holder_data_turns_missing_holders_into_a_reject(
    require_holder_data: bool, passes: bool
) -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    config = make_screening(
        enable_anti_rug_filters=True,
        enable_cluster_analysis=False,
        require_social_links=True,
        min_social_links_count=2,
        max_acceptable_risk_score=30.0,
        require_holder_data=require_holder_data,
    )
    enricher = TokenEnricher(
        api_client=_socials_api(), execution_client=client, config=config
    )

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_EMPTY_HOLDERS)
    ):
        verdict = await enricher.enrich_and_screen(mint, _stream_payload(mint))

    # Missing holders scores exactly the 30-point threshold (Stage 0 pattern).
    assert verdict.risk_score == pytest.approx(30.0)
    assert "Holder distribution data unavailable" in verdict.reasons
    assert verdict.passed is passes


# --- BUG-108: only Pump.fun launches --------------------------------------------


@pytest.mark.regression("BUG-108")
@pytest.mark.parametrize(
    "mint, data, require_suffix, expected",
    [
        (SAMPLE_PUMP_MINT, {"pool": "pump"}, True, None),
        (SAMPLE_PUMP_MINT, {}, True, None),
        (SAMPLE_PUMP_MINT, {"pool": "bonk"}, True, "launched on 'bonk', not Pump.fun"),
        (SAMPLE_MINT, {"pool": "bonk"}, False, "launched on 'bonk', not Pump.fun"),
        (SAMPLE_MINT, {}, True, "mint does not end in 'pump'"),
        (SAMPLE_MINT, None, False, None),
        (SAMPLE_MINT, {"pool": "  "}, False, None),
    ],
)
def test_non_pump_launch_reason_table(
    mint: str,
    data: dict[str, Any] | None,
    require_suffix: bool,
    expected: str | None,
) -> None:
    assert non_pump_launch_reason(mint, data, require_suffix=require_suffix) == expected


# --- Screening data in the replay capture ----------------------------------------


def test_screening_snapshot_records_what_the_screener_saw() -> None:
    curve = str(Pubkey.new_unique())
    verdict = TokenScreeningVerdict(
        mint=SAMPLE_PUMP_MINT,
        passed=False,
        risk_score=60.0,
        reasons=["Insufficient social links: found 1, required at least 2"],
        flags={"missing_holder_data": False, "nested": {"x": 1}},
        dev_profile=DevWalletProfile(
            creator_address=CREATOR, tokens_launched_24h=3, total_tokens_launched=9
        ),
        holder_distribution=HolderDistribution(
            creator_initial_pct=0.04,
            top_holders=[(curve, 800_000_000_000_000), ("A", 100_000_000_000_000)],
            bonding_curve_address=curve,
        ),
        metadata=TokenMetadata(twitter="https://x.com/token"),
    )

    record = screening_snapshot(
        verdict, name="Tok", market_cap_sol=27.96, latency_ms=812.34, timestamp=5.0
    )

    assert record["event"] == SCREENING_EVENT
    assert {"price", "market_cap_sol", "signal"}.isdisjoint(record)
    assert record["mint"] == SAMPLE_PUMP_MINT and record["timestamp"] == 5.0
    screening = record["screening"]
    assert screening["passed"] is False
    assert screening["social_links"] == 1 and screening["twitter"] is True
    assert screening["holders_available"] is True and screening["holder_count"] == 2
    assert screening["top5_pct"] == pytest.approx(0.1)
    # FEAT-61 bundle proxy: the 10% account (not the creator's 4%), curve left out.
    assert screening["early_holders"] == 1
    assert screening["early_holder_pct"] == pytest.approx(0.1)
    assert screening["creator"] == CREATOR
    assert screening["creator_launches_24h"] == 3
    assert screening["latency_ms"] == 812.3
    assert screening["flags"] == {"missing_holder_data": False}


def test_screening_snapshot_without_enrichment_data_has_nulls() -> None:
    verdict = TokenScreeningVerdict(mint=SAMPLE_PUMP_MINT, passed=True, risk_score=0.0)

    screening = screening_snapshot(verdict)["screening"]

    assert screening["social_links"] is None
    assert screening["holders_available"] is False
    assert screening["holder_count"] == 0
    assert screening["top5_pct"] is None and screening["creator"] is None
    assert "early_holders" not in screening


SYSTEM_PROGRAM = "11111111111111111111111111111111"


@pytest.mark.regression("BUG-113")
@pytest.mark.parametrize(
    "stream, record, expected",
    [
        (
            {"txType": "create", "traderPublicKey": CREATOR},
            {"creator": SYSTEM_PROGRAM},
            CREATOR,
        ),
        ({"traderPublicKey": CREATOR}, {"creator": "ApiCreator"}, CREATOR),
        (None, {"creator": SYSTEM_PROGRAM, "dev_wallet": "DevWallet"}, "DevWallet"),
        (
            {"txType": "create", "traderPublicKey": SYSTEM_PROGRAM},
            {"creator": " "},
            None,
        ),
        # On a copied buy the signer is the trader; the record names the creator.
        (
            {"txType": "buy", "traderPublicKey": "Trader"},
            {"creator": "ApiCreator"},
            "ApiCreator",
        ),
        ({"txType": "buy", "creator": CREATOR}, {"creator": "ApiCreator"}, CREATOR),
        ({}, {"creator": 42}, None),
    ],
)
def test_resolve_creator_skips_placeholders_and_prefers_stream_signer(
    stream: dict[str, Any] | None, record: dict[str, Any], expected: str | None
) -> None:
    assert resolve_creator(stream, record) == expected


@pytest.mark.regression("BUG-113")
async def test_enrich_system_program_creator_uses_stream_signer() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    api = _api(coin={"mint": mint, "creator": SYSTEM_PROGRAM})
    serial = [{"created_timestamp": time.time() * 1000} for _ in range(9)]
    api.get_creator_coins = AsyncMock(return_value=serial)
    enricher = TokenEnricher(
        api_client=api, execution_client=client, config=_strict_config()
    )

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_holders(client, mint))
    ):
        verdict = await enricher.enrich_and_screen(mint, _stream_payload(mint))

    api.get_creator_coins.assert_awaited_once_with(CREATOR, limit=20)
    assert verdict.dev_profile is not None
    assert verdict.dev_profile.creator_address == CREATOR
    assert not verdict.passed
    assert any("Serial launcher" in reason for reason in verdict.reasons)


@pytest.mark.regression("BUG-113")
async def test_enrich_unresolved_creator_adds_missing_dev_penalty() -> None:
    mint = str(Pubkey.new_unique())
    client = _execution_client()
    api = _api(coin={"mint": mint, "creator": SYSTEM_PROGRAM})
    enricher = TokenEnricher(
        api_client=api, execution_client=client, config=_strict_config()
    )
    payload = {**_stream_payload(mint), "traderPublicKey": SYSTEM_PROGRAM}

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_holders(client, mint))
    ):
        verdict = await enricher.enrich_and_screen(mint, payload)

    api.get_creator_coins.assert_not_awaited()
    assert verdict.dev_profile is None
    assert "Dev wallet data unavailable" in verdict.reasons


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"is_mayhem_mode": True}, "mayhem-mode launch"),
        ({"is_mayhem_mode": "true"}, "mayhem-mode launch"),
        ({"is_mayhem_mode": False}, None),
        ({}, None),
        (None, None),
    ],
)
def test_mayhem_mode_reason_table(
    data: dict[str, Any] | None, expected: str | None
) -> None:
    assert mayhem_mode_reason(data) == expected
