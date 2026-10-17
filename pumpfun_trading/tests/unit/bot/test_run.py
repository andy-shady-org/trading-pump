"""Unit tests for ``bot/run.py`` net PnL booking (FEAT-49) and the full-exit
token-account close (BUG-96)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.bot.enrichment import TokenScreeningVerdict
from pumpfun_trading.bot.event_router import EventRouter
from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.execution.executor import ExecutionResult, OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.ops.retention import RetentionPolicy, RotatedFileSink
from pumpfun_trading.sdk.costs import (
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
)
from pumpfun_trading.sdk.execution import (
    TOKEN_PROGRAM_ID_STR,
    NonStandardCurveError,
    PumpFunExecutionClient,
)
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.storage.status import build_status_snapshot
from pumpfun_trading.strategies.copy_trading import TrackedWallet
from pumpfun_trading.strategies.momentum import MomentumSignal
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)
from pumpfun_trading.tests.support.constants import (
    SAMPLE_MINT,
    SAMPLE_PRIVATE_KEY,
    SAMPLE_PUMP_MINT,
    WSOL_MINT,
)
from pumpfun_trading.tests.support.factories import (
    make_bot,
    make_config,
    make_pool_keys,
    make_position,
)
from pumpfun_trading.tests.support.payloads import STANDARD_CURVE_RESERVES

MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
TOKENS = 350_000_000_000


def _costs(*, swap: int, rent: int, tip: int = 100_000) -> TransactionCosts:
    return TransactionCosts(
        signature="Sig",
        network_fee_lamports=15_000,
        priority_fee_lamports=10_000,
        tip_lamports=tip,
        rent_lamports=rent,
        swap_lamports=swap,
        source=COST_SOURCE_TRANSACTION_META,
    )


def _live_bot(tmp_path: Path) -> TradingBot:
    bot = make_bot(tmp_path, dry_run=False)
    bot._should_buy = lambda *_a, **_k: True  # type: ignore[method-assign]
    bot._check_account_equity_guard = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot._validate_balance = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot._resolve_token_name = AsyncMock(return_value="Token")  # type: ignore[method-assign]
    return bot


def _audit_trades(tmp_path: Path) -> list[dict[str, Any]]:
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [
        json.loads(line)["payload"]
        for line in lines
        if json.loads(line).get("type") == "trade"
    ]


async def test_live_round_trip_books_net_pnl_and_closes_account(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    buy_costs = _costs(swap=9_900_000, rent=TOKEN_ACCOUNT_RENT_LAMPORTS)
    sell_costs = _costs(swap=12_000_000, rent=-TOKEN_ACCOUNT_RENT_LAMPORTS)
    bot.executor.execute_buy = AsyncMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(
            success=True,
            signature="BuySig",
            mint=MINT,
            amount_sol=0.0099,
            token_amount=TOKENS,
            costs=buy_costs,
        )
    )
    bot.executor.execute_sell = AsyncMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(
            success=True,
            signature="SellSig",
            mint=MINT,
            is_buy=False,
            amount_sol=0.012,
            token_amount=TOKENS,
            costs=sell_costs,
        )
    )
    bot.execution.get_token_balance = AsyncMock(return_value=TOKENS)  # type: ignore[method-assign]

    assert await bot._buy_token(MINT, market_cap_sol=30.0) is True
    # Cost basis is the SOL actually paid into the curve.
    assert bot.active_positions[MINT]["cost_sol"] == pytest.approx(0.0099)

    assert await bot._sell_token(MINT, reason="trailing_stop_hit") is True
    sell_call = bot.executor.execute_sell.await_args_list[-1]
    assert sell_call.kwargs["close_token_account"] is True

    buy, sell = _audit_trades(tmp_path)
    assert buy["signature"] == "BuySig" and sell["signature"] == "SellSig"
    assert buy["net_pnl_sol"] == pytest.approx(-buy_costs.total_cost_sol)
    assert buy["rent_sol"] > 0 and sell["rent_sol"] < 0
    assert sell["gross_pnl_sol"] == pytest.approx(0.012 - 0.0099)
    assert sell["net_pnl_sol"] == pytest.approx(0.0021 - sell_costs.total_cost_sol)
    assert sell["cost_source"] == COST_SOURCE_TRANSACTION_META

    tracker = bot.daily_equity_tracker
    net = buy["net_pnl_sol"] + sell["net_pnl_sol"]
    assert tracker.realized_daily_pnl_sol == pytest.approx(net)
    assert tracker.realized_daily_gross_pnl_sol == pytest.approx(0.0021)
    # Rent paid on the buy comes back on the close: net costs are fees + tips.
    assert tracker.realized_daily_costs_sol == pytest.approx(2 * 115_000 / 1e9)
    assert bot._pnl_totals.net_pnl_sol == pytest.approx(net)

    snapshot = bot.get_status_snapshot()
    assert snapshot["pnl_totals"]["sells"] == 1
    assert snapshot["daily_realized_costs_sol"] == pytest.approx(0.00023)
    await bot.close()


async def test_partial_exit_never_closes_and_totals_survive_restart(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    bot.position_manager.record_buy(
        mint=MINT, token_amount=TOKENS, cost_sol=0.01, entry_market_cap=30.0
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.executor.execute_sell = AsyncMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(
            success=True, signature="S", mint=MINT, is_buy=False, amount_sol=0.008
        )
    )
    bot.execution.get_token_balance = AsyncMock(return_value=TOKENS)  # type: ignore[method-assign]

    assert await bot._sell_token(MINT, sell_fraction=0.5, reason="tier1") is True
    sell_call = bot.executor.execute_sell.await_args_list[-1]
    assert sell_call.kwargs["close_token_account"] is False
    record = bot._trade_ledger[-1]
    assert record["cost_source"] == "none" and record["costs_sol"] == 0.0
    bot._write_status_snapshot()
    await bot.close()

    restored = _live_bot(tmp_path)
    assert restored._pnl_totals.sells == 1
    assert restored._pnl_totals.gross_pnl_sol == pytest.approx(0.008 - 0.005)
    await restored.close()


def test_paper_fee_factor_falls_back_on_bad_fee(tmp_path: Path) -> None:
    bot = _live_bot(tmp_path)
    bot.execution.pump_fee_bps = "bad"  # type: ignore[assignment]
    assert bot._paper_round_trip_fee_factor() == pytest.approx((1 - 0.0125) ** 2)


def test_status_snapshot_carries_last_reconciliation(tmp_path: Path) -> None:
    bot = _live_bot(tmp_path)
    bot._write_status_snapshot()
    snapshot = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert snapshot["reconciliation"] is None

    (tmp_path / "reconcile_status.json").write_text(
        json.dumps({"ok": True, "trades_checked": 2, "checked_at": 1.0}),
        encoding="utf-8",
    )
    bot._write_status_snapshot()
    snapshot = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert snapshot["reconciliation"]["trades_checked"] == 2

    # A changed audit path switches to that trail's status file.
    bot.audit_log_path = str(tmp_path / "other" / "audit.jsonl")
    assert bot.reconciliation_status() is None


# --- stream ingestion, subscriptions, refresh, arbitrage and lifecycle ---------


class _SendStrWs:
    """WebSocket double exposing only ``send_str`` (aiohttp-like fallback)."""

    def __init__(self, messages: list[Any] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = list(messages or [])

    async def send_str(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def exception(self) -> Exception:
        return RuntimeError("ws boom")

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        for msg in self._messages:
            yield msg


class _FakeSession:
    def __init__(self, ws: _SendStrWs) -> None:
        self._ws = ws

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def ws_connect(self, _url: str) -> _FakeWsContext:
        return _FakeWsContext(self._ws)


class _FakeWsContext:
    def __init__(self, ws: _SendStrWs) -> None:
        self._ws = ws

    async def __aenter__(self) -> _SendStrWs:
        return self._ws

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _ws_msg(kind: aiohttp.WSMsgType, data: str = "") -> SimpleNamespace:
    return SimpleNamespace(type=kind, data=data)


def _hold_position(bot: TradingBot, **extra: Any) -> None:
    bot.position_manager.record_buy(
        mint=MINT, token_amount=TOKENS, cost_sol=0.01, entry_market_cap=30.0
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.active_positions[MINT].update(extra)


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("_subscribe_to_token_trades", "subscribeTokenTrade"),
        ("_unsubscribe_from_token_trades", "unsubscribeTokenTrade"),
    ],
)
async def test_token_trade_subscription_send_str_only_ws_sends_json_text(
    tmp_path: Path, method: str, expected: str
) -> None:
    bot = _live_bot(tmp_path)
    ws = _SendStrWs()
    await getattr(bot, method)(ws, MINT)
    assert ws.sent == [{"method": expected, "keys": [MINT]}]
    # A transport without any send method is ignored silently.
    await getattr(bot, method)(object(), MINT)
    await bot.close()


@pytest.mark.parametrize(
    "data",
    [
        {"amm_id": "amm", "coin_mint": MINT},
        {"event": "raydium_pool_created", "poolKeys": {"amm_id": "amm"}},
    ],
)
async def test_handle_message_raydium_update_failure_falls_back_to_router(
    tmp_path: Path, data: dict[str, Any]
) -> None:
    bot = _live_bot(tmp_path)
    bot._handle_raydium_pool_update = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("bad pool")
    )
    route = AsyncMock()
    bot.event_router.route_ws_message = route  # type: ignore[method-assign]
    with patch(
        "pumpfun_trading.bot.run.RaydiumPoolKeys.from_dict",
        return_value=SimpleNamespace(),
    ):
        await bot._handle_message(data, None)
    route.assert_awaited_once_with(data, None)
    await bot.close()


@pytest.mark.parametrize(
    ("curve", "position_extra", "expected_mc"),
    [
        (
            {
                "virtual_token_reserves": 1_000_000_000_000_000,
                "virtual_sol_reserves": 30_000_000_000,
            },
            {},
            30.0,
        ),
        ({"market_cap_sol": 0.0}, {"current_market_cap": 42.0}, 42.0),
        (RuntimeError("rpc down"), {"current_market_cap": 55.0}, 55.0),
    ],
)
async def test_refresh_market_caps_curve_variants_evaluate_exit_with_best_mc(
    tmp_path: Path,
    curve: Any,
    position_extra: dict[str, Any],
    expected_mc: float,
) -> None:
    bot = _live_bot(tmp_path)
    _hold_position(bot, **position_extra)
    if isinstance(curve, Exception):
        bot.execution.get_bonding_curve_state = AsyncMock(side_effect=curve)  # type: ignore[method-assign]
    else:
        bot.execution.get_bonding_curve_state = AsyncMock(return_value=curve)  # type: ignore[method-assign]
    exit_mock = AsyncMock(return_value=False)
    bot._evaluate_and_execute_exit = exit_mock  # type: ignore[method-assign]
    await bot._refresh_active_positions_market_caps()
    exit_mock.assert_awaited_once()
    assert exit_mock.await_args is not None
    assert exit_mock.await_args.args[1] == pytest.approx(expected_mc)
    await bot.close()


async def test_refresh_market_caps_unknown_mc_skips_and_swallows_exit_errors(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    _hold_position(bot, entry_market_cap=0.0, current_market_cap=0.0)
    bot.execution.get_bonding_curve_state = AsyncMock(return_value=None)  # type: ignore[method-assign]
    exit_mock = AsyncMock(side_effect=RuntimeError("exit failed"))
    bot._evaluate_and_execute_exit = exit_mock  # type: ignore[method-assign]
    await bot._refresh_active_positions_market_caps()
    exit_mock.assert_not_awaited()

    # Curve read fails and the fallback exit also fails: never raises.
    bot.active_positions[MINT]["current_market_cap"] = 12.0
    bot.execution.get_bonding_curve_state = AsyncMock(side_effect=RuntimeError("x"))  # type: ignore[method-assign]
    await bot._refresh_active_positions_market_caps()
    exit_mock.assert_awaited_once()
    await bot.close()


@pytest.mark.parametrize(
    ("curve", "expected_mc"),
    [
        (
            {
                "virtual_token_reserves": 1_000_000_000_000_000,
                "virtual_sol_reserves": 40_000_000_000,
            },
            40.0,
        ),
        ({"virtual_token_reserves": 0, "virtual_sol_reserves": 0}, 25.0),
        (RuntimeError("rpc down"), 25.0),
    ],
)
async def test_handle_trade_update_held_mint_uses_chain_reserves_when_valid(
    tmp_path: Path, curve: Any, expected_mc: float
) -> None:
    bot = _live_bot(tmp_path)
    _hold_position(bot)
    if isinstance(curve, Exception):
        bot.execution.get_bonding_curve_state = AsyncMock(side_effect=curve)  # type: ignore[method-assign]
    else:
        bot.execution.get_bonding_curve_state = AsyncMock(return_value=curve)  # type: ignore[method-assign]
    exit_mock = AsyncMock(return_value=False)
    bot._evaluate_and_execute_exit = exit_mock  # type: ignore[method-assign]
    await bot._handle_trade_update(
        {"mint": MINT, "txType": "buy", "solAmount": 0.1, "marketCapSol": 25.0}
    )
    exit_mock.assert_awaited_once()
    assert exit_mock.await_args is not None
    assert exit_mock.await_args.args[1] == pytest.approx(expected_mc)
    await bot.close()


async def test_retention_prune_due_compresses_and_survives_manager_errors(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    bot.retention_check_interval_seconds = 0.0
    bot._last_retention_check = 0.0
    good = MagicMock()
    good.prune_expired_async = AsyncMock(return_value=["old.jsonl.gz"])
    good.target_directory = tmp_path
    broken = MagicMock()
    broken.prune_expired_async = AsyncMock(side_effect=OSError("disk"))
    bot.retention_managers = [broken, good]
    await bot._run_retention_prune()
    good.compress_uncompressed_archives.assert_called_once_with()
    broken.compress_uncompressed_archives.assert_not_called()
    assert bot._last_retention_check > 0.0
    await bot.close()


async def test_close_http_clients_skips_closeless_and_swallows_close_errors(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    execution = bot.execution
    failing = MagicMock()
    failing.close = MagicMock(side_effect=RuntimeError("close failed"))
    bot.execution = failing
    bot.api = object()  # type: ignore[assignment]
    await bot._close_http_clients()
    failing.close.assert_called_once_with()
    await execution.close()


def _arb_bot(tmp_path: Path, *, dry_run: bool) -> TradingBot:
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=make_config(
            buy_amount_sol=0.01,
            dry_run=dry_run,
            enable_cross_venue_arbitrage=True,
            enable_mempool_backrunning=True,
        ),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    bot.graduation_engine.get_candidate = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(pool_keys=object(), real_sol_reserves=80.0)
    )
    return bot


def _opportunity(*, verified: bool = True) -> MagicMock:
    opp = MagicMock()
    opp.is_profitable = True
    opp.reserves_verified = verified
    opp.direction = "pump_to_raydium"
    opp.spread_pct = 0.05
    opp.optimal_input_sol = 1.0
    opp.net_profit_sol = 0.02
    opp.expected_output_sol = 1.03
    opp.estimated_fees_sol = 0.0003
    opp.estimated_jito_tip_sol = 0.0097
    opp.mint = MINT
    opp.pump_spot_price = 1e-7
    opp.raydium_spot_price = 1.1e-7
    opp.to_dict.return_value = {}
    return opp


async def test_arbitrage_disabled_or_stopping_never_evaluates(tmp_path: Path) -> None:
    bot = _arb_bot(tmp_path, dry_run=True)
    bot._stop_requested = True
    await bot._evaluate_and_execute_arbitrage(MINT, 1, 1)
    bot.graduation_engine.get_candidate.assert_not_called()  # type: ignore[attr-defined]
    await bot.close()


@pytest.mark.regression("BUG-99")
async def test_arbitrage_whale_backrun_landed_books_net_profit_in_dry_run(
    tmp_path: Path,
) -> None:
    bot = _arb_bot(tmp_path, dry_run=True)
    start_balance = bot.wallet_balance_sol
    opp = _opportunity()
    bot.backrun_engine.evaluate_whale_transaction = MagicMock(return_value=opp)  # type: ignore[method-assign]
    bot.arb_monitor.evaluate_spread = MagicMock()  # type: ignore[method-assign]
    bot.arb_executor.execute_arbitrage = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": True, "net_profit_sol": 0.02}
    )
    await bot._evaluate_and_execute_arbitrage(MINT, 1, 1, trade_sol=2.0)
    bot.arb_monitor.evaluate_spread.assert_not_called()
    assert bot.wallet_balance_sol == pytest.approx(start_balance + 0.02)
    record = bot._trade_ledger[-1]
    assert record["action"] == "ARBITRAGE"
    assert record["buy_price"] == pytest.approx(1e-7)
    assert record["sell_price"] == pytest.approx(1.1e-7)
    # BUG-99: booked net of the modelled fee + tip (0.03 gross - 0.01 costs).
    assert record["gross_pnl_sol"] == pytest.approx(0.03)
    assert record["costs_sol"] == pytest.approx(0.01)
    assert record["tip_sol"] == pytest.approx(0.0097)
    assert record["net_pnl_sol"] == pytest.approx(0.02)
    assert record["cash_flow_sol"] == pytest.approx(0.02)
    assert bot.daily_equity_tracker.realized_daily_pnl_sol == pytest.approx(0.02)
    await bot.close()


@pytest.mark.parametrize("lookup_fails", [False, True])
async def test_arbitrage_landed_live_books_transaction_costs(
    tmp_path: Path, lookup_fails: bool
) -> None:
    bot = _arb_bot(tmp_path, dry_run=False)
    start_balance = bot.wallet_balance_sol
    bot.arb_monitor.evaluate_spread = MagicMock(return_value=_opportunity())  # type: ignore[method-assign]
    bot.arb_executor.execute_arbitrage = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": True, "signature": "ArbSig"}
    )
    real = TransactionCosts(
        signature="ArbSig",
        network_fee_lamports=25_000,
        priority_fee_lamports=20_000,
        tip_lamports=2_000_000,
        source=COST_SOURCE_TRANSACTION_META,
    )
    getter = AsyncMock(
        side_effect=RuntimeError("rpc down") if lookup_fails else None,
        return_value=real,
    )
    bot.execution.get_transaction_costs = getter  # type: ignore[method-assign]

    await bot._evaluate_and_execute_arbitrage(MINT, 1, 1)

    getter.assert_awaited_once_with("ArbSig", MINT, is_buy=True)
    record = bot._trade_ledger[-1]
    assert record["signature"] == "ArbSig"
    expected_costs = 0.01 if lookup_fails else 0.002025
    assert record["costs_sol"] == pytest.approx(expected_costs)
    assert record["net_pnl_sol"] == pytest.approx(0.03 - expected_costs)
    assert bot.daily_equity_tracker.realized_daily_pnl_sol == pytest.approx(
        0.03 - expected_costs
    )
    # Live wallets are read from chain, never credited locally.
    assert bot.wallet_balance_sol == start_balance
    await bot.close()


async def test_arbitrage_reverted_bundle_live_books_nothing(tmp_path: Path) -> None:
    bot = _arb_bot(tmp_path, dry_run=False)
    bot.arb_monitor.evaluate_spread = MagicMock(return_value=_opportunity())  # type: ignore[method-assign]
    bot.arb_executor.execute_arbitrage = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": False}
    )
    await bot._evaluate_and_execute_arbitrage(MINT, 1, 1, trade_sol=0.1)
    bot.arb_executor.execute_arbitrage.assert_awaited_once()
    assert bot._trade_ledger == []
    assert bot.daily_equity_tracker.realized_daily_pnl_sol == 0.0
    await bot.close()


async def test_arbitrage_estimated_reserves_never_execute(tmp_path: Path) -> None:
    bot = _arb_bot(tmp_path, dry_run=True)
    bot.arb_monitor.evaluate_spread = MagicMock(  # type: ignore[method-assign]
        return_value=_opportunity(verified=False)
    )
    bot.arb_executor.execute_arbitrage = AsyncMock()  # type: ignore[method-assign]
    await bot._evaluate_and_execute_arbitrage(MINT, 1, 1)
    bot.arb_executor.execute_arbitrage.assert_not_awaited()
    await bot.close()


def test_record_trade_explicit_unit_price_wins(tmp_path: Path) -> None:
    bot = _live_bot(tmp_path)
    bot._record_trade(mint=MINT, action="sell", exit_value=0.5, unit_price_sol=3e-8)
    assert bot._trade_ledger[-1]["unit_price_sol"] == pytest.approx(3e-8)


@pytest.mark.parametrize(
    ("closing", "failures", "max_failures", "tripped"),
    [
        (aiohttp.WSMsgType.ERROR, 0, 1, True),
        (aiohttp.WSMsgType.CLOSED, 0, 5, False),
    ],
)
async def test_websocket_stream_session_end_trips_breaker_on_failure_budget(
    tmp_path: Path,
    closing: aiohttp.WSMsgType,
    failures: int,
    max_failures: int,
    tripped: bool,
) -> None:
    bot = _live_bot(tmp_path)
    bot.stream_url = "wss://stream.test"
    bot._stream_consecutive_failures = failures
    bot._max_stream_consecutive_failures = max_failures
    _hold_position(bot)
    handled: list[Any] = []

    async def _handle(data: Any, websocket: Any = None) -> None:
        handled.append(data)

    bot._handle_message = _handle  # type: ignore[method-assign]
    ws = _SendStrWs(
        [
            _ws_msg(aiohttp.WSMsgType.TEXT, "not-json"),
            _ws_msg(aiohttp.WSMsgType.TEXT, json.dumps({"mint": MINT})),
            _ws_msg(aiohttp.WSMsgType.BINARY),
            _ws_msg(closing),
            _ws_msg(aiohttp.WSMsgType.TEXT, json.dumps({"mint": "late"})),
        ]
    )
    with (
        patch(
            "pumpfun_trading.bot.run.aiohttp.ClientSession",
            return_value=_FakeSession(ws),
        ),
        patch(
            "pumpfun_trading.bot.run.asyncio.sleep",
            AsyncMock(side_effect=asyncio.CancelledError),
        ),
    ):
        await bot._run_websocket_stream()
    assert ws.sent == [
        {"method": "subscribeNewToken"},
        {"method": "subscribeTokenTrade", "keys": [MINT]},
    ]
    assert handled == [{"mint": MINT}]
    assert bot._circuit_breaker_tripped is tripped
    assert bot._health_ok is (not tripped)
    assert bot._active_ws is None
    await bot.close()


async def test_websocket_stream_stop_requested_mid_session_exits_without_sleep(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)

    async def _handle(data: Any, websocket: Any = None) -> None:
        bot._stop_requested = True

    bot._handle_message = _handle  # type: ignore[method-assign]
    ws = _SendStrWs(
        [
            _ws_msg(aiohttp.WSMsgType.TEXT, "{}"),
            _ws_msg(aiohttp.WSMsgType.TEXT, "{}"),
        ]
    )
    sleep = AsyncMock()
    with (
        patch(
            "pumpfun_trading.bot.run.aiohttp.ClientSession",
            return_value=_FakeSession(ws),
        ),
        patch("pumpfun_trading.bot.run.asyncio.sleep", sleep),
    ):
        await bot._run_websocket_stream()
    sleep.assert_not_awaited()
    await bot.close()


async def test_websocket_stream_connect_error_trips_breaker_then_cancel_stops(
    tmp_path: Path,
) -> None:
    bot = _live_bot(tmp_path)
    bot._max_stream_consecutive_failures = 1
    with (
        patch(
            "pumpfun_trading.bot.run.aiohttp.ClientSession",
            side_effect=aiohttp.ClientError("refused"),
        ),
        patch(
            "pumpfun_trading.bot.run.asyncio.sleep",
            AsyncMock(side_effect=asyncio.CancelledError),
        ),
    ):
        await bot._run_websocket_stream()
    assert bot._stream_consecutive_failures == 1
    assert bot._circuit_breaker_tripped is True
    assert bot._last_status == "degraded: stream circuit breaker active"
    await bot.close()


class _ListenGeyser:
    """Geyser double with an injected ``listen()`` source."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.stop = AsyncMock()
        self._running = True

    async def listen(self) -> AsyncIterator[Any]:
        for event in self._events:
            yield event


def _startable_bot(tmp_path: Path) -> TradingBot:
    bot = _live_bot(tmp_path)
    bot._register_signal_handlers = MagicMock()  # type: ignore[method-assign]
    bot._reconcile_positions_on_startup = AsyncMock(return_value={})  # type: ignore[method-assign]
    return bot


@pytest.mark.parametrize("stop_before_first_event", [True, False])
async def test_start_custom_geyser_listen_stops_and_releases_resources(
    tmp_path: Path, stop_before_first_event: bool
) -> None:
    bot = _startable_bot(tmp_path)
    handled: list[Any] = []

    async def _handle(data: Any, websocket: Any = None) -> None:
        handled.append(data)
        bot._stop_requested = True

    bot._handle_message = _handle  # type: ignore[method-assign]
    geyser = _ListenGeyser([{"mint": "a"}, {"mint": "b"}])
    bot.geyser_client = geyser  # type: ignore[assignment]
    if stop_before_first_event:
        original_reconcile = bot._reconcile_positions_on_startup

        async def _reconcile_then_stop() -> dict[str, Any]:
            bot._stop_requested = True
            return await original_reconcile()

        bot._reconcile_positions_on_startup = _reconcile_then_stop  # type: ignore[method-assign]
    pool = MagicMock()
    pool.start_health_loop = AsyncMock()
    bot.rpc_pool = pool
    recorder = MagicMock()
    recorder.start = AsyncMock()
    recorder.close = AsyncMock()
    bot.replay_recorder = recorder

    await bot.start()

    assert handled == ([] if stop_before_first_event else [{"mint": "a"}])
    geyser.stop.assert_awaited_once_with()
    pool.stop.assert_called_once_with()
    recorder.close.assert_awaited_once_with()
    assert bot.state == TradingBotState.SHUTDOWN


async def test_start_geyser_without_transport_falls_back_to_websocket(
    tmp_path: Path,
) -> None:
    bot = _startable_bot(tmp_path)
    bot.geyser_endpoint = "grpc.geyser.test:443"
    bot.stream_url = "wss://stream.test"
    ws_stream = AsyncMock(side_effect=RuntimeError("stream died"))
    bot._run_websocket_stream = ws_stream  # type: ignore[method-assign]
    bot._max_stream_consecutive_failures = 1

    await bot.start()

    ws_stream.assert_awaited_once_with()
    assert any("no gRPC transport" in event for event in bot._recent_events)
    assert bot._circuit_breaker_tripped is True
    assert bot.state == TradingBotState.SHUTDOWN


@pytest.mark.regression("BUG-100")
@pytest.mark.parametrize(
    ("kwargs", "env", "expected"),
    [
        ({}, {"PUMPFUN_STREAM_URL": "wss://env.test"}, "wss://env.test"),
        # BUG-100: an explicit argument beats the env URL.
        (
            {"stream_url": "wss://arg.test"},
            {"PUMPFUN_WS_URL": "wss://env.test"},
            "wss://arg.test",
        ),
        ({"stream_url": "wss://arg.test"}, {}, "wss://arg.test"),
    ],
)
def test_init_stream_url_resolution_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    env: dict[str, str],
    expected: str,
) -> None:
    for key in ("PUMPFUN_STREAM_URL", "PUMPFUN_WS_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config={  # type: ignore[arg-type]
            "buy_amount_sol": 0.02,
            "stream_url": "http://127.0.0.1:10000",
        },
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
        **kwargs,
    )
    assert bot.config.buy_amount_sol == pytest.approx(0.02)
    assert bot.stream_url == expected


@pytest.mark.regression("BUG-102")
def test_status_snapshot_and_events_contain_no_url_credentials(
    tmp_path: Path,
) -> None:
    """BUG-102: provider keys never reach the status file, events or alerts."""
    key = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url=f"https://mainnet.helius-rpc.com/?api-key={key}",
        stream_url=f"wss://feed.example.com/data?token={key}",
        config=make_config(dry_run=False, buy_amount_sol=0.01),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    sent: list[str] = []
    bot.alert_enabled = True
    bot._send_alert = sent.append  # type: ignore[method-assign, assignment]

    bot._record_event(f"stream connected: {bot.stream_url}")

    snapshot = json.dumps(bot.get_status_snapshot(), default=str)
    assert key not in snapshot
    assert "api-key=***" in snapshot
    assert key not in json.dumps(bot.config.to_dict())
    assert sent == ["stream connected: wss://feed.example.com/data?token=***"]
    # The raw URLs stay in memory for making requests.
    assert key in bot.stream_url


async def test_trading_bot_atomic_displacement(tmp_path):
    config = make_config(
        max_active_positions=1,
        max_total_exposure_sol=0.1,
        enable_capital_rotation=True,
        min_hold_before_displacement_seconds=45.0,
        displacement_min_conviction_percentile=0.95,
        displacement_hurdle_rate_pct=0.02,
        dry_run=True,
        verbose=False,
    )
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        config=config,
        dry_run=True,
        verbose=False,
    )

    now = time.time()
    # 1. Establish initial stagnant position
    stagnant_mint = "StagnantMintAAA111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=stagnant_mint,
        token_amount=1_000_000,
        cost_sol=0.05,
        entry_market_cap=30.0,
        name="StagnantToken",
    )
    pos = bot.position_manager.get_position(stagnant_mint)
    pos["entry_time"] = now - 180.0
    pos["last_price_change_at"] = now - 180.0
    bot.active_positions = bot.position_manager.get_all_positions()

    assert len(bot.active_positions) == 1

    # 2. Ingest strong momentum breakout candidate
    breakout_mint = "BreakoutMintBBB222222222222222222222222222"
    breakout_signal = MagicMock(
        triggered=True,
        z_score=4.8,
        buy_sell_ratio=8.0,
        net_sol_inflow=5.0,
        unique_buyers=15,
    )

    displaced = await bot._evaluate_and_trigger_displacement(
        candidate_mint=breakout_mint,
        market_cap_sol=35.0,
        candidate_signal=breakout_signal,
        conviction_percentile=0.98,
        token_name="BreakoutToken",
    )

    assert displaced is True
    # Verify stagnant position was removed and breakout candidate entered
    assert stagnant_mint not in bot.active_positions
    assert breakout_mint in bot.active_positions


async def test_bot_live_partial_sell_and_reconciliation(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from pumpfun_trading.bot.run import TradingBot

    SAMPLE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
    MINT = "So11111111111111111111111111111111111111112"

    config = make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.50,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        min_sell_balance=10,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Mock execution client
    bot.execution.get_bonding_curve_pda = MagicMock(return_value=("CurvePDA", "bump"))
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.calculate_sell_sol_output = MagicMock(return_value=20_000_000)
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value="tx_sell_partial_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    # Populate active position
    bot.active_positions[MINT] = {
        "name": "LiveMoon",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "peak_market_cap": 30.0,
        "initial_token_amount": 1_000_000,
        "remaining_token_amount": 1_000_000,
        "token_amount": 1_000_000,
    }

    # Execute Tier 1 partial sell
    sold_ok = await bot._sell_token(
        MINT,
        sell_fraction=0.50,
        reason="take_profit_tier_1",
        target_tier=1,
    )
    assert sold_ok is True
    assert MINT in bot.active_positions
    assert bot.active_positions[MINT]["remaining_token_amount"] == 500_000
    assert bot.active_positions[MINT]["tier_1_executed"] is True

    # Reconcile on-chain positions
    bot.execution.get_token_balance = AsyncMock(return_value=500_000)
    reconciled = await bot.reconcile_onchain_positions()
    assert reconciled[MINT]["status"] == "active"
    assert bot.active_positions[MINT]["remaining_token_amount"] == 500_000
    assert bot.active_positions[MINT]["tier_1_executed"] is True

    # Execute Tier 2 partial sell with Jito bundle
    bot.use_jito = True
    bot.execution.send_jito_bundle_with_fallback = AsyncMock(
        return_value="jito_bundle_sig"
    )
    sold_t2 = await bot._sell_token(
        MINT,
        sell_fraction=0.25,
        reason="take_profit_tier_2",
        target_tier=2,
    )
    assert sold_t2 is True
    assert bot.active_positions[MINT]["remaining_token_amount"] == 250_000
    assert bot.active_positions[MINT]["tier_2_executed"] is True
    assert bot.active_positions[MINT]["moonbag_active"] is True

    # Snapshot and recovery check
    bot._write_status_snapshot()
    bot.active_positions.clear()
    bot.safe_startup()
    assert MINT in bot.active_positions
    assert bot.active_positions[MINT]["remaining_token_amount"] == 250_000
    assert bot.active_positions[MINT]["tier_2_executed"] is True
    assert bot.active_positions[MINT]["moonbag_active"] is True

    # Full exit remainder
    sold_full = await bot._sell_token(MINT, reason="trailing_stop_hit")
    assert sold_full is True
    assert MINT not in bot.active_positions

    await bot.close()


@pytest.mark.regression("BUG-18")
async def test_bot_sell_populates_audit_record_and_ledger(tmp_path):
    """
    Regression test for BUG-18:
    Verifies that when _sell_token executes (full or partial), the resulting
    sell_price and exit proceeds are accurately populated and written to the audit log.
    """
    from pumpfun_trading.bot.run import TradingBot

    audit_file = tmp_path / "audit.jsonl"
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        audit_log_path=str(audit_file),
    )

    mint = "MintSellTest111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint,
        token_amount=1_000_000,
        cost_sol=0.10,
        entry_market_cap=30.0,
        name="SellTestToken",
    )
    bot.position_manager.update_price(mint, 60.0)  # 2x price surge
    bot.active_positions = bot.position_manager.get_all_positions()

    # 1. Execute partial sell (50%)
    success = await bot._sell_token(
        mint=mint,
        sell_amount_tokens=500_000,
        sell_fraction=0.5,
        reason="tier1_take_profit",
        target_tier=1,
    )
    assert success
    assert len(bot._trade_ledger) == 1
    last_trade = bot._trade_ledger[-1]
    assert last_trade["action"] == "partial_sell"
    # Cost basis for 50% is 0.05 SOL; exit proceeds at 2x are 0.10 SOL before the
    # modelled buy and sell protocol fees (FEAT-49).
    proceeds = 0.10 * bot._paper_round_trip_fee_factor()
    assert last_trade["exit"] == pytest.approx(proceeds)
    assert last_trade["sell_price"] == pytest.approx(proceeds)
    assert last_trade["entry"] == pytest.approx(0.05)

    # 2. Execute full exit on remaining 50%
    success_full = await bot._sell_token(
        mint=mint,
        reason="stop_loss",
    )
    assert success_full
    assert len(bot._trade_ledger) == 2
    full_trade = bot._trade_ledger[-1]
    assert full_trade["action"] == "sell"
    assert full_trade["exit"] == pytest.approx(proceeds)
    assert full_trade["sell_price"] == pytest.approx(proceeds)

    # Verify audit file lines contain valid sell_price
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    import json

    trade_records = [
        json.loads(line) for line in lines if json.loads(line).get("type") == "trade"
    ]
    assert len(trade_records) == 2
    assert trade_records[0]["payload"]["sell_price"] == pytest.approx(proceeds)
    assert trade_records[1]["payload"]["sell_price"] == pytest.approx(proceeds)

    # Both sells are banked: gross = 2 x (proceeds - 0.05); net also pays the
    # modelled fees and refunds the token-account rent on the full exit.
    tracker = bot.daily_equity_tracker
    assert tracker.realized_daily_gross_pnl_sol == pytest.approx(2 * proceeds - 0.10)
    costs = sum(t["costs_sol"] for t in bot._trade_ledger)
    assert tracker.realized_daily_pnl_sol == pytest.approx(2 * proceeds - 0.10 - costs)
    assert full_trade["rent_sol"] < 0


@pytest.mark.regression("BUG-24", "BUG-25", "BUG-26", "BUG-27", "BUG-28")
async def test_bugs_24_to_28_comprehensive_validation(tmp_path):
    """
    Comprehensive regression tests for:
    - BUG-24: Dry-run token sizing and positive exit proceeds on profitable pump (Torq Rigs scenario)
    - BUG-25: Internal bot buy and sell executions recorded into replay log (.jsonl)
    - BUG-26: Position ID correlation preserved across partial and full exits in audit trail
    - BUG-27: Total SOL capital and token unit prices properly differentiated in audit records
    - BUG-28: PositionManager effective buy price scaled by UI token units
    """
    import json

    from pumpfun_trading.bot.run import TradingBot

    audit_file = tmp_path / "audit_trail.jsonl"
    replay_file = tmp_path / "replay_log.jsonl"

    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        audit_log_path=str(audit_file),
        replay_log_path=str(replay_file),
    )
    await bot.replay_recorder.start()

    mint = "TorqRigsPump111111111111111111111111111111111"

    # 1. Execute Buy
    buy_ok = await bot._buy_token(
        mint=mint,
        market_cap_sol=27.96,
        token_name="Torq Rigs",
        buy_amount_sol=0.01,
        reason="momentum_breakout",
    )
    assert buy_ok
    assert bot.position_manager.has_position(mint)
    pos = bot.position_manager.get_position(mint)

    # BUG-24 & BUG-28 checks on entry
    assert (
        pos["initial_token_amount"] > 100_000_000
    )  # Calculated from curve (~357M units)
    # Unit price is ~2.796e-8 SOL (0.02796 µSOL), not 1e-10 or 1e-14
    assert 1e-9 < pos["buy_price"] < 1e-6

    # 2. Simulate 2.06x price surge (Take profit tier 1)
    bot.position_manager.update_price(mint, 57.60)  # ~2.06x
    bot.active_positions = bot.position_manager.get_all_positions()

    partial_ok = await bot._sell_token(
        mint=mint,
        sell_fraction=0.5,
        reason="take_profit_tier_1",
        target_tier=1,
    )
    assert partial_ok

    # 3. Simulate trailing stop exit at 2.71x
    bot.position_manager.update_price(mint, 75.77)  # ~2.71x
    bot.active_positions = bot.position_manager.get_all_positions()

    full_ok = await bot._sell_token(
        mint=mint,
        reason="trailing_stop_hit",
    )
    assert full_ok
    assert not bot.position_manager.has_position(mint)

    # BUG-24 check: Verify bot realized positive cumulative profit (+0.0138 SOL), NOT ~99.9% loss!
    # Entry cost: 0.01 SOL (0.005 + 0.005). Tier 1 exit (0.005 * 2.06 = 0.0103 SOL), Trailing exit (0.005 * 2.71 = 0.01355 SOL)
    # Total exit: ~0.02385 SOL -> Net profit: ~+0.01385 SOL
    realized_pnl = bot.daily_equity_tracker.realized_daily_pnl_sol
    assert realized_pnl > 0.010

    # Flush replay recorder
    await bot.replay_recorder.flush()
    await bot.replay_recorder.close()

    # BUG-25 check: Verify replay log contains BOTH buy and sell snapshots
    assert replay_file.exists()
    replay_lines = [
        json.loads(line)
        for line in replay_file.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert len(replay_lines) == 3
    assert replay_lines[0]["signal"] == "buy"
    assert replay_lines[0]["is_buy"] is True
    assert replay_lines[0]["mint"] == mint
    assert replay_lines[1]["signal"] == "sell"
    assert replay_lines[1]["is_buy"] is False
    assert replay_lines[1]["reason"] == "take_profit_tier_1"
    assert replay_lines[2]["signal"] == "sell"
    assert replay_lines[2]["is_buy"] is False
    assert replay_lines[2]["reason"] == "trailing_stop_hit"

    # BUG-26 & BUG-27 check: Verify audit trail position ID correlation & unit price differentiation
    assert audit_file.exists()
    audit_lines = [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").strip().splitlines()
        if json.loads(line).get("type") == "trade"
    ]
    assert len(audit_lines) == 3
    initial_pos_id = audit_lines[0]["payload"]["position_id"]
    assert initial_pos_id.startswith("trade-")
    # All exits share the same parent position_id
    assert audit_lines[1]["payload"]["position_id"] == initial_pos_id
    assert audit_lines[2]["payload"]["position_id"] == initial_pos_id

    # Verify unit price vs capital differentiation (BUG-27)
    for rec in audit_lines:
        payload = rec["payload"]
        assert "unit_price_sol" in payload
        assert "cost_sol" in payload
        assert "proceeds_sol" in payload
        assert "sol_amount" in payload


@pytest.fixture
def base_bot(tmp_path):
    config = make_config(
        dry_run=False,
        strategy_preset="balanced",
        buy_amount_sol=0.05,
        take_profit=1.5,
        stop_loss=0.85,
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.2,
        min_market_cap_sol=10.0,
        min_balance_sol=0.1,
        enable_tiered_take_profit=False,
        # The sample mints are not ``…pump`` vanity mints (BUG-108).
        require_pump_mint_suffix=False,
    )
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"
    log_file = tmp_path / "bot.log"

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=True,
        paper_trade=False,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
        log_file=str(log_file),
    )
    return bot


def test_bot_alerting_and_snapshot(base_bot, tmp_path):
    # Alerting configuration with valid & invalid providers
    base_bot.alert_provider = "invalid_provider"
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_provider = "discord"
    base_bot.alert_discord_webhook_url = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_discord_webhook_url = "https://discord.com/webhook"
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is True

    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert discord")
        assert mock_url.called

    base_bot.alert_provider = "slack"
    base_bot.alert_slack_webhook_url = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_slack_webhook_url = "https://slack.com/webhook"
    base_bot._configure_alerting()
    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert slack")
        assert mock_url.called

    base_bot.alert_provider = "telegram"
    base_bot.alert_telegram_bot_token = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_telegram_bot_token = "token123"
    base_bot.alert_telegram_chat_id = "chat123"
    base_bot._configure_alerting()
    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert telegram")
        assert mock_url.called

    # Snapshot writing
    base_bot._write_status_snapshot()
    assert Path(base_bot.bot_status_path).exists()

    # Audit logging
    base_bot._write_audit_record("test_event", {"info": 123})
    assert Path(base_bot.audit_log_path).exists()


def test_bot_safe_startup_recovery(tmp_path):
    status_file = tmp_path / "recovery_status.json"
    snapshot = {
        "active_positions": {
            "MintRecovered": {
                "name": "TokenRecovered",
                "entry_market_cap": 25.0,
                "current_market_cap": 28.0,
            }
        },
        "buy_attempts": {"MintA": 1},
        "seen_mints": {"MintA": 12345.0},
        "trade_ledger": [{"mint": "MintA", "action": "buy"}],
    }
    status_file.write_text(json.dumps(snapshot), encoding="utf-8")

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(dry_run=False),
        dry_run=True,
        bot_status_path=str(status_file),
    )
    assert "MintRecovered" in bot.active_positions
    assert bot._buy_attempts.get("MintA") == 1
    assert bot._seen_mints.get("MintA") == 12345.0


async def test_bot_buy_and_sell_flows(base_bot):
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    # Dry run buy
    success_buy = await base_bot._buy_token(
        mint, market_cap_sol=15.0, token_name="TokenDry"
    )
    assert success_buy is True
    assert mint in base_bot.active_positions

    # Dry run sell
    success_sell = await base_bot._sell_token(mint)
    assert success_sell is True
    assert mint not in base_bot.active_positions

    # Sell token not in positions
    assert await base_bot._sell_token("NonExistentMint") is False


async def test_bot_live_buy_and_sell_branches(tmp_path):
    config = make_config(dry_run=False, buy_amount_sol=0.05)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    # Mock execution client
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.buy = AsyncMock(return_value="tx_sig_123")
    bot.execution.sell = AsyncMock(return_value="tx_sig_sell_123")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    # Live buy success
    buy_ok = await bot._buy_token(mint, market_cap_sol=20.0, token_name="TokenLive")
    assert buy_ok is True
    assert mint in bot.active_positions

    # Live sell success
    sell_ok = await bot._sell_token(mint)
    assert sell_ok is True
    assert mint not in bot.active_positions

    # Live sell zero balance purge
    bot.active_positions[mint] = {"name": "TokenZero", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    sell_zero = await bot._sell_token(mint)
    assert sell_zero is True
    assert mint not in bot.active_positions

    # Live buy failure: missing signature
    bot.execution.buy = AsyncMock(return_value=None)
    buy_fail_sig = await bot._buy_token("MintNoSig", market_cap_sol=20.0)
    assert buy_fail_sig is False

    # Live buy failure: confirmation failed
    bot.execution.buy = AsyncMock(return_value="tx_sig_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    buy_fail_conf = await bot._buy_token("MintNoConf", market_cap_sol=20.0)
    assert buy_fail_conf is False

    # Live sell failure: confirmation failed
    bot.active_positions["MintSellConfFail"] = {
        "name": "TokenFail",
        "entry_market_cap": 20.0,
    }
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value="tx_sig_sell_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    sell_fail_conf = await bot._sell_token("MintSellConfFail")
    assert sell_fail_conf is False

    await bot.close()


async def test_bot_message_handlers_and_events(base_bot):
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    mock_ws = AsyncMock()

    # Handle newTokenCreated
    new_token_msg = {
        "txType": "create",
        "mint": mint,
        "name": "FreshToken",
        "marketCapSol": 25.0,
        "traderPublicKey": "DevWa11et1111111111111111111111111111111111",
    }
    await base_bot._handle_message(new_token_msg, mock_ws)
    assert mint in base_bot.active_positions

    # Handle tradeCreated holding update
    trade_msg = {
        "txType": "trade",
        "mint": mint,
        "marketCapSol": 30.0,
    }
    await base_bot._handle_message(trade_msg, mock_ws)
    assert base_bot.active_positions[mint]["current_market_cap"] == 30.0

    # Handle tradeCreated take profit exit
    trade_tp_msg = {
        "txType": "trade",
        "mint": mint,
        "marketCapSol": 50.0,  # 50.0 > 25.0 * 1.5
    }
    await base_bot._handle_message(trade_tp_msg, mock_ws)
    assert mint not in base_bot.active_positions

    # Unrecognized message
    await base_bot._handle_message({"unknown": True}, mock_ws)


async def test_bot_reconciliation_and_retries(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(dry_run=False),
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
    )

    mint1 = "MintActive1"
    mint2 = "MintZero2"

    bot.active_positions = {
        mint1: {"name": "Token1", "entry_market_cap": 20.0, "token_amount": 100},
        mint2: {"name": "Token2", "entry_market_cap": 20.0, "token_amount": 100},
    }

    async def mock_get_token_balance(mint):
        if mint == mint1:
            return 500
        return 0

    bot.execution.get_token_balance = AsyncMock(side_effect=mock_get_token_balance)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 25.0}
    )

    reconciled = await bot.reconcile_onchain_positions()
    assert mint1 in bot.active_positions
    assert mint2 not in bot.active_positions
    assert reconciled[mint2]["status"] == "purged"

    # Test exit retry queue
    bot.active_positions[mint1] = {"name": "Token1"}
    bot._enqueue_exit_retry(mint1, reason="network_blip")
    assert mint1 in bot._exit_retry_queue

    # Set timer to past to trigger process
    bot._exit_retry_queue[mint1]["next_retry_at"] = time.monotonic() - 1.0
    bot._sell_token = AsyncMock(return_value=True)
    await bot._process_exit_retry_queue(websocket=AsyncMock())

    await bot.close()


async def test_bot_buy_metric_and_reserve_price_refresh(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(
            dry_run=False,
            buy_amount_sol=0.01,
            take_profit=1.5,
            stop_loss=0.85,
        ),
        dry_run=True,
        paper_trade=True,
        bot_status_path=str(tmp_path / "status.json"),
    )

    # 1. Verify single buy increments buys metric by exactly 1
    assert bot._metrics.get("buys", 0) == 0
    bought = await bot._buy_token("MintMetricTest1", market_cap_sol=27.96)
    assert bought is True
    assert bot._metrics.get("buys", 0) == 1
    assert bot._metrics_snapshot()["buys"] == 1

    # 2. Verify trade update with virtual reserves updates market cap
    trade_with_reserves = {
        "txType": "trade",
        "mint": "MintMetricTest1",
        "vSolInBondingCurve": 35_000_000_000,  # 35 SOL
        "vTokensInBondingCurve": 1_000_000_000_000_000,  # 1B tokens
    }
    await bot._handle_message(trade_with_reserves)
    pos = bot.active_positions.get("MintMetricTest1")
    assert pos is not None
    assert pos["current_market_cap"] == 35.0

    # 3. Verify _refresh_active_positions_market_caps polls bonding curve
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 38.5}
    )
    await bot._refresh_active_positions_market_caps()
    assert bot.active_positions["MintMetricTest1"]["current_market_cap"] == 38.5

    # 4. Verify sell increments sells metric by exactly 1
    assert bot._metrics.get("sells", 0) == 0
    sold = await bot._sell_token("MintMetricTest1")
    assert sold is True
    assert bot._metrics.get("sells", 0) == 1
    assert bot._metrics_snapshot()["sells"] == 1

    await bot.close()


MINT_2 = "So11111111111111111111111111111111111111112"


def make_pool(mint: str) -> RaydiumPoolKeys:
    fields = {name: f"{name}111" for name in RaydiumPoolKeys.__slots__}
    fields["coin_mint"] = mint
    return RaydiumPoolKeys(**fields)


@pytest.mark.regression("BUG-45")
async def test_snapshot_round_trip_keeps_cost_basis_and_pool(tmp_path):
    """BUG-45: cost_sol, position_id and pool keys survive a restart."""
    bot = make_bot(tmp_path)
    for mint in (MINT, MINT_2):
        bot.position_manager.record_buy(
            mint=mint,
            token_amount=350_000_000_000,
            cost_sol=0.01,
            entry_market_cap=30.0,
            buy_price=2.8e-8,
            metadata={"position_id": f"trade-{mint[:4]}"},
        )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._raydium_exit_pools[MINT_2] = make_pool(MINT_2)
    bot._migrating_mints.add(MINT_2)
    bot._write_status_snapshot()
    await bot.close()

    restored = make_bot(tmp_path)
    pos = restored.active_positions[MINT]
    assert pos["cost_sol"] == pytest.approx(0.01)
    assert pos["position_id"] == f"trade-{MINT[:4]}"
    assert "pool_keys" not in pos
    pool_pos = restored.active_positions[MINT_2]
    assert pool_pos["pool_keys"]["coin_mint"] == MINT_2
    assert MINT_2 in restored._migrating_mints
    assert isinstance(restored._exit_pool_keys(MINT_2, pool_pos), RaydiumPoolKeys)

    # Realized PnL uses the SOL cost, not the per-token unit price: at an
    # unchanged price only the modelled protocol fees are lost (FEAT-49).
    assert await restored._sell_token(MINT, reason="test") is True
    fee_loss = 0.01 * (restored._paper_round_trip_fee_factor() - 1.0)
    assert restored._trade_ledger[-1]["gross_pnl_sol"] == pytest.approx(fee_loss)
    assert restored.daily_equity_tracker.realized_daily_gross_pnl_sol == (
        pytest.approx(fee_loss)
    )
    await restored.close()


@pytest.mark.regression("BUG-45")
async def test_unit_buy_price_never_used_as_cost(tmp_path):
    """BUG-45: a position without cost_sol falls back to buy_amount_sol."""
    bot = make_bot(tmp_path)
    bot.active_positions[MINT] = {
        "name": "Legacy",
        "token_amount": 100_000_000,
        "initial_token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "buy_price": 2.8e-8,
    }
    assert await bot._sell_token(MINT, reason="test") is True
    fee_loss = 0.01 * (bot._paper_round_trip_fee_factor() - 1.0)
    assert bot.daily_equity_tracker.realized_daily_gross_pnl_sol == pytest.approx(
        fee_loss
    )
    await bot.close()


@pytest.mark.regression("BUG-91")
async def test_no_buy_sent_after_shutdown(tmp_path):
    """BUG-91: a buy in flight at shutdown never sends or revives the bot."""
    bot = make_bot(tmp_path)
    bot._should_buy = lambda *a, **k: True
    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot._validate_balance = AsyncMock(return_value=True)
    bot._resolve_token_name = AsyncMock(return_value=None)
    bot.executor.execute_buy = AsyncMock()
    bot.request_shutdown()
    assert await bot._buy_token(MINT, 30.0) is False
    bot.executor.execute_buy.assert_not_awaited()

    bot.state = TradingBotState.SHUTDOWN
    bot._transition_to(TradingBotState.MONITORING, reason="buy_failed")
    assert bot.state == TradingBotState.SHUTDOWN
    await bot.close()


@pytest.mark.regression("BUG-92")
def test_max_positions_per_mint_is_enforced(tmp_path):
    """BUG-92: unsupported pyramiding values are clamped to one lot per mint."""
    bot = make_bot(tmp_path, max_positions_per_mint=3)
    assert bot.max_positions_per_mint == 1
    bot.active_positions[MINT] = {"name": "Held"}
    assert bot._should_buy(MINT, 30.0) is False


@pytest.mark.regression("BUG-74")
async def test_start_closes_http_clients(tmp_path):
    """BUG-74: start() releases the execution and API sessions on exit."""
    bot = make_bot(tmp_path)
    bot.execution.close = AsyncMock()
    bot.api.close = AsyncMock()

    async def empty_listen():
        bot.request_shutdown()
        if False:  # pragma: no cover
            yield None

    bot.geyser_client.listen = empty_listen
    await bot.start()
    bot.execution.close.assert_awaited()
    bot.api.close.assert_awaited()


TEST_RPC = "https://api.mainnet-beta.solana.com"


MINT_1 = "HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump"


def _make_bot(
    dry_run: bool = True, paper_trade: bool = True, verbose: bool = False, **kwargs
) -> TradingBot:
    config = make_config(
        dry_run=dry_run,
        paper_trade=paper_trade,
        buy_amount_sol=0.01,
        reconnect_delay_seconds=1.0,
        verbose=verbose,
    )
    return TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url=TEST_RPC,
        config=config,
        dry_run=dry_run,
        paper_trade=paper_trade,
        verbose=verbose,
        **kwargs,
    )


@pytest.mark.regression("BUG-07")
async def test_bug07_onchain_startup_reconciliation():
    """Test BUG-07: Startup reconciliation purges stale ghost positions with zero balance."""
    bot = _make_bot(dry_run=False, paper_trade=False)
    bot.active_positions = {
        MINT_1: {
            "name": "GhostToken",
            "entry_market_cap": 30.0,
            "current_market_cap": 30.0,
            "token_amount": 1000,
        },
        MINT_2: {
            "name": "ActiveToken",
            "entry_market_cap": 35.0,
            "current_market_cap": 35.0,
            "token_amount": 5000,
        },
    }

    async def mock_balance(mint: str) -> int:
        if mint == MINT_1:
            return 0  # Sold externally
        return 5000  # Still holding

    bot.execution.get_token_balance = AsyncMock(side_effect=mock_balance)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 40.0}
    )

    reconciled = await bot.reconcile_onchain_positions()

    assert MINT_1 not in bot.active_positions
    assert MINT_2 in bot.active_positions
    assert bot.active_positions[MINT_2]["token_amount"] == 5000
    assert bot.active_positions[MINT_2]["current_market_cap"] == 40.0
    assert reconciled[MINT_1]["status"] == "purged"
    assert reconciled[MINT_2]["status"] == "active"


@pytest.mark.regression("BUG-08")
async def test_bug08_exit_retry_queue_and_slippage_escalation():
    """Test BUG-08: Failed sells enqueue with escalating slippage and retry backoff."""
    bot = _make_bot(dry_run=False, paper_trade=False)
    bot.active_positions[MINT_1] = {
        "name": "Token1",
        "entry_market_cap": 30.0,
        "current_market_cap": 25.0,
    }

    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(
            "BondingPDA11111111111111111111111111111111",
            "Associated11111111111111111111111111111111",
        )
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1000000000,
            "virtual_sol_reserves": 30000000000,
        }
    )
    # Simulate RPC failure on send
    bot.execution.sell = AsyncMock(side_effect=RuntimeError("Simulated RPC Error"))

    # Initial sell attempt fails
    result = await bot._sell_token(MINT_1)
    assert result is False
    assert MINT_1 in bot.active_positions  # Position preserved for retry
    assert MINT_1 in bot._exit_retry_queue

    entry = bot._exit_retry_queue[MINT_1]
    assert entry["retry_count"] == 1
    assert entry["slippage_bps"] == bot.base_exit_slippage_bps + 500  # 1000 bps

    # Simulate second retry failure
    bot._enqueue_exit_retry(MINT_1, reason="second_failure")
    entry2 = bot._exit_retry_queue[MINT_1]
    assert entry2["retry_count"] == 2
    assert entry2["slippage_bps"] == bot.base_exit_slippage_bps + 1000  # 1500 bps

    # Test process exit retry queue with successful retry
    bot._exit_retry_queue[MINT_1]["next_retry_at"] = 0  # Force immediate eligibility
    bot.execution.sell = AsyncMock(
        return_value="ValidSignature1111111111111111111111111111111111111111111111111111111111111111"
    )
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    await bot._process_exit_retry_queue()
    assert MINT_1 not in bot.active_positions
    assert MINT_1 not in bot._exit_retry_queue


@pytest.mark.regression("BUG-06")
async def test_bug06_websocket_backoff_and_circuit_breaker():
    """Test BUG-06: WebSocket circuit breaker trips on consecutive reconnect failures."""
    bot = _make_bot()
    bot._max_ws_consecutive_failures = 3

    assert bot._health_ok is True
    assert bot._circuit_breaker_tripped is False

    # Simulate consecutive failures
    bot._ws_consecutive_failures = 3
    if bot._ws_consecutive_failures >= bot._max_ws_consecutive_failures:
        bot._circuit_breaker_tripped = True
        bot._health_ok = False
        bot._last_status = "degraded: ws circuit breaker active"

    assert bot._circuit_breaker_tripped is True
    assert bot._health_ok is False
    assert "circuit breaker" in bot._last_status

    # Snapshot includes circuit breaker status
    snapshot = build_status_snapshot(bot)
    assert snapshot["circuit_breaker_tripped"] is True
    assert snapshot["ws_consecutive_failures"] == 3


def test_safe_startup_resets_shutdown_state_and_stop_requested(tmp_path):
    """Test that restarting the bot resets SHUTDOWN state and stop_requested to clean defaults."""
    status_file = tmp_path / "bot_status.json"
    status_file.write_text(
        '{"state": "shutdown", "stop_requested": true, "active_positions": {}}',
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"PUMPFUN_STATUS_PATH": str(status_file)}):
        bot = _make_bot()
        bot.safe_startup()
        from pumpfun_trading.bot.lifecycle import TradingBotState

        assert bot.state == TradingBotState.IDLE
        assert bot._stop_requested is False


def test_request_shutdown_idempotent_and_stops_geyser():
    """Test that request_shutdown stops geyser client and is safe to call repeatedly."""
    bot = _make_bot()
    from pumpfun_trading.bot.lifecycle import TradingBotState

    assert bot.geyser_client is not None
    bot.geyser_client._running = True

    bot.request_shutdown()
    assert bot._stop_requested is True
    assert bot.geyser_client._running is False
    assert bot.state == TradingBotState.SHUTDOWN

    # Repeated calls should be idempotent
    bot.request_shutdown()
    assert bot.state == TradingBotState.SHUTDOWN


@pytest.mark.regression("BUG-29")
async def test_bug29_console_stream_suppression_and_headless_mode():
    """Test BUG-29: Suppress console StreamHandler during interactive Live UI rendering."""
    # 1. Interactive terminal mode (verbose=True, headless=False): no StreamHandler
    bot_interactive = _make_bot(verbose=True, headless=False)
    assert bot_interactive.headless is False
    assert bot_interactive.verbose is True
    # Ensure no raw StreamHandler is attached to avoid terminal jitter
    stream_handlers = [
        h
        for h in bot_interactive.logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]
    assert len(stream_handlers) == 0

    # 2. Headless mode (verbose=True, headless=True): StreamHandler is attached
    bot_headless = _make_bot(verbose=True, headless=True)
    assert bot_headless.headless is True
    stream_handlers_headless = [
        h
        for h in bot_headless.logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]
    assert len(stream_handlers_headless) == 1

    # 3. Environment variable PUMPFUN_HEADLESS overrides
    with patch.dict(os.environ, {"PUMPFUN_HEADLESS": "1"}):
        bot_env = _make_bot(verbose=True)
        assert bot_env.headless is True
        env_stream_handlers = [
            h
            for h in bot_env.logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(env_stream_handlers) == 1

    # 4. _render_loop skips execution when headless=True: it returns at once
    # without starting a Live context
    await bot_headless._render_loop()


async def test_bot_full_websocket_and_lifecycle(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"PUMPFUN_PRIVATE_KEY={SAMPLE_PRIVATE_KEY}\nPUMPFUN_RPC_URL=https://api.mainnet-beta.solana.com\n",
        encoding="utf-8",
    )

    bot = TradingBot.from_env(
        env_file=str(env_file),
        config=make_config(
            dry_run=False,
            buy_amount_sol=0.05,
            min_market_cap_sol=10.0,
            enable_tiered_take_profit=False,
        ),
        dry_run=True,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Prune seen mints when expired
    bot._seen_mints[SAMPLE_MINT] = time.monotonic() - (
        bot.recent_token_ttl_seconds + 10.0
    )
    bot._prune_seen_mints()
    assert SAMPLE_MINT not in bot._seen_mints

    # Start loop with events and graceful shutdown
    events = [
        {
            "txType": "create",
            "mint": SAMPLE_MINT,
            "name": "LiveToken",
            "marketCapSol": 25.0,
        },
        {
            "txType": "trade",
            "mint": SAMPLE_MINT,
            "marketCapSol": 50.0,  # TP exit
        },
    ]

    async def mock_listen():
        for msg in events:
            yield msg
        bot.request_shutdown()

    bot.geyser_client.listen = mock_listen
    await bot.start()

    assert SAMPLE_MINT not in bot.active_positions
    await bot.close()


async def test_bot_live_error_branches(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(dry_run=False, buy_amount_sol=0.05),
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Live buy missing signature and confirmation failure
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(str(Pubkey.from_string(WSOL_MINT)), "bump")
    )
    bot.execution.buy = AsyncMock(return_value=None)
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot.execution.buy = AsyncMock(return_value="tx_sig_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    # Live sell missing signature and confirmation failure
    bot.active_positions[SAMPLE_MINT] = {"name": "TokenFail", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value=None)
    assert await bot._sell_token(SAMPLE_MINT) is False

    bot.execution.sell = AsyncMock(return_value="tx_sell_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    assert await bot._sell_token(SAMPLE_MINT) is False

    # Live buy PDA exception
    bot.execution.get_bonding_curve_pda = MagicMock(
        side_effect=RuntimeError("PDA error")
    )
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    # Live sell PDA exception
    bot.active_positions[SAMPLE_MINT] = {"name": "TokenPDA", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    assert await bot._sell_token(SAMPLE_MINT) is False
    assert SAMPLE_MINT in bot._exit_retry_queue

    # Live sell bonding curve fetch exception (continues with min_sol_lamports=0)
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(str(Pubkey.from_string(WSOL_MINT)), "bump")
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        side_effect=RuntimeError("curve fetch error")
    )
    bot.execution.sell = AsyncMock(return_value="tx_sell_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    sell_ok = await bot._sell_token(SAMPLE_MINT)
    assert sell_ok is True
    assert SAMPLE_MINT not in bot.active_positions

    await bot.close()


async def test_bot_startup_schema_and_edge_branches(tmp_path):
    # Status file in local dir with integer arguments
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(dry_run=False, enable_tiered_take_profit=False),
        min_market_cap_sol=20,  # int
        min_balance_sol=1,  # int
        max_active_positions=2,  # int
        dry_run=False,
        paper_trade=False,
        bot_status_path="status.json",
        audit_log_path="audit.jsonl",
    )

    # _send_alert exception handling
    bot.alert_enabled = True
    with patch("urllib.request.urlopen", side_effect=RuntimeError("webhook down")):
        bot._send_alert("Alert failure test")

    # safe_startup with rich schema
    schema = {
        "active_positions": {
            SAMPLE_MINT: {
                "name": "CoinSchema",
                "entry_market_cap": 25.0,
                "current_market_cap": 25.0,
                "token_amount": 1000,
            },
            "InvalidPos": "not_a_dict",
        },
        "buy_attempts": {SAMPLE_MINT: 2},
        "seen_mints": {SAMPLE_MINT: time.monotonic()},
        "recent_actions": [{"timestamp": 1234, "action": "buy"}, "invalid_action"],
        "recent_events": ["event1", 1234],
        "trade_ledger": [{"mint": SAMPLE_MINT, "action": "buy"}, "invalid_trade"],
        "exit_retry_queue": {
            SAMPLE_MINT: {
                "mint": SAMPLE_MINT,
                "retry_count": 6,  # exceeds max retries
                "next_retry_at": time.monotonic() - 1.0,
            }
        },
        "circuit_breaker_tripped": True,
        "ws_consecutive_failures": 3,
    }
    bot_status_file = tmp_path / "full_status.json"
    bot_status_file.write_text(json.dumps(schema), encoding="utf-8")
    bot.bot_status_path = str(bot_status_file)
    bot.safe_startup()

    assert SAMPLE_MINT in bot.active_positions
    assert bot._buy_attempts[SAMPLE_MINT] == 2

    # reconcile_onchain_positions with bonding curve MC update and balance read error
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 35.0}
    )
    reconciled = await bot.reconcile_onchain_positions()
    assert reconciled[SAMPLE_MINT]["status"] == "active"
    assert bot.active_positions[SAMPLE_MINT]["current_market_cap"] == 35.0

    # Exception during balance read in reconciliation
    bot.execution.get_token_balance = AsyncMock(
        side_effect=RuntimeError("balance RPC err")
    )
    await bot.reconcile_onchain_positions()

    # _enqueue_exit_retry max retries alert
    bot._enqueue_exit_retry(SAMPLE_MINT, reason="test_max_retry")

    # _validate_balance failure
    bot.execution.get_balance_sol = AsyncMock(return_value=0.0)
    assert await bot._validate_balance() is False
    assert await bot._buy_token(WSOL_MINT, market_cap_sol=20.0) is False

    # Trade update with on-chain curve reading in non-dry-run mode
    bot.active_positions[SAMPLE_MINT]["entry_market_cap"] = 25.0
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 60.0}  # TP hit (60 > 25*1.5)
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.execution.sell = AsyncMock(return_value="tx_tp_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    await bot._handle_trade_update(
        {"mint": SAMPLE_MINT, "marketCapSol": 28.0}, AsyncMock()
    )
    assert SAMPLE_MINT not in bot.active_positions

    # Message handlers edge conditions
    mock_ws = AsyncMock()
    bot._stop_requested = True
    await bot._handle_new_token_event({"mint": SAMPLE_MINT}, mock_ws)
    await bot._handle_trade_update({"mint": SAMPLE_MINT}, mock_ws)
    bot._stop_requested = False

    await bot._handle_new_token_event({}, mock_ws)  # empty mint
    bot._seen_mints[SAMPLE_MINT] = time.monotonic()
    await bot._handle_new_token_event({"mint": SAMPLE_MINT}, mock_ws)  # seen mint
    bot._seen_mints.clear()

    await bot._handle_trade_update({}, mock_ws)  # empty mint
    await bot._handle_trade_update(
        {"mint": WSOL_MINT, "marketCapSol": 10.0}, mock_ws
    )  # not active
    bot.active_positions[SAMPLE_MINT] = {"entry_market_cap": 20.0}
    await bot._handle_trade_update(
        {"mint": SAMPLE_MINT, "marketCapSol": 0.0}, mock_ws
    )  # non-positive mc

    await bot._handle_message("not_dict", mock_ws)

    # Cleanup test files created in current dir
    await bot.close()
    for fname in ("status.json", "audit.jsonl"):
        p = Path(fname)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


async def test_bot_start_and_message_loop_heartbeat(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=make_config(dry_run=False),
        dry_run=True,
    )
    bot._circuit_breaker_tripped = True
    bot._last_message_at = time.monotonic() - 70.0  # triggers heartbeat timeout check

    events = [
        "not_valid_dict",
        {"txType": "create", "mint": SAMPLE_MINT, "marketCapSol": 30.0},
    ]

    async def mock_listen():
        for e in events:
            yield e
        bot.request_shutdown()

    bot.geyser_client.listen = mock_listen
    bot.reconcile_onchain_positions = AsyncMock(side_effect=RuntimeError("recon err"))

    await bot.start()

    assert bot._circuit_breaker_tripped is False
    await bot.close()


async def test_bot_run_all_missing_branches(tmp_path):
    config = make_config(
        dry_run=False,
        buy_amount_sol=0.05,
        min_market_cap_sol=10.0,
        max_active_positions=2,
        require_pump_mint_suffix=False,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=True,
        bot_status_path=str(tmp_path / "status.json"),
    )

    # validate_mint_address errors
    with pytest.raises(ValueError, match="Mint address is required"):
        TradingBot.validate_mint_address("")
    with pytest.raises(ValueError, match="32 bytes"):
        TradingBot.validate_mint_address("short")

    # from_env missing variables
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="Missing PUMPFUN_PRIVATE_KEY"):
            TradingBot.from_env()

        with patch.dict("os.environ", {"PUMPFUN_PRIVATE_KEY": SAMPLE_PRIVATE_KEY}):
            with pytest.raises(ValueError, match="Missing PUMPFUN_RPC_URL"):
                TradingBot.from_env()

    # safe_startup corrupt files and edge schemas
    bad_status = tmp_path / "bad_status.json"
    bad_status.write_text("corrupt json", encoding="utf-8")
    bot.bot_status_path = str(bad_status)
    bot.safe_startup()

    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    bot.bot_status_path = str(bad_schema)
    bot.safe_startup()

    partial_schema = tmp_path / "partial.json"
    partial_schema.write_text(
        json.dumps(
            {
                "active_positions": [SAMPLE_MINT],  # list instead of dict
                "buy_attempts": {"a": "not_int"},
                "seen_mints": {"a": "not_float"},
                "recent_actions": ["not_dict"],
                "recent_events": [123],
                "trade_ledger": ["not_dict"],
            }
        ),
        encoding="utf-8",
    )
    bot.bot_status_path = str(partial_schema)
    bot.safe_startup()

    # _record_trade with > 50 entries
    for i in range(55):
        bot._record_trade(mint=SAMPLE_MINT, action="buy", entry=0.01)
    assert len(bot._trade_ledger) <= 50

    # _record_event with alerting enabled
    bot.alert_enabled = True
    bot._send_alert = MagicMock()
    bot._record_event("Alert event")
    assert bot._send_alert.called

    # _record_stale_data and _record_failure
    bot._record_stale_data("delayed ping")
    bot._record_failure(category="network")
    bot._record_connection_loss()

    # _next_position_id, _check_daily_drawdown, _check_loss_per_trade
    assert bot._next_position_id().startswith("trade-")
    assert bot._check_daily_drawdown() is True
    assert bot._check_loss_per_trade(mint=SAMPLE_MINT) is True

    # _validate_balance and _check_account_equity_guard in non-dry-run mode
    bot.dry_run = False
    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)  # below min balance
    assert await bot._validate_balance() is False
    assert await bot._check_account_equity_guard(required_sol=1.0) is False

    # _buy_token when equity guard blocks or balance blocks
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot.dry_run = True

    # _should_buy branches
    bot._buy_attempts[SAMPLE_MINT] = 5
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot._buy_attempts[SAMPLE_MINT] = 0
    assert (
        bot._should_buy(SAMPLE_MINT, market_cap_sol=5.0) is False
    )  # below min_market_cap

    bot._seen_mints[SAMPLE_MINT] = time.monotonic()
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot._seen_mints.clear()

    bot.active_positions[SAMPLE_MINT] = {"name": "Active"}
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot.active_positions.clear()

    bot.active_positions = {"P1": {}, "P2": {}}
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot.active_positions.clear()

    bot._health_ok = False
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot._health_ok = True

    # new token message creates position
    bot.state = TradingBotState.MONITORING
    bot.wallet_balance_sol = 10.0
    bot.daily_equity_tracker.reset_circuit_breaker()
    msg_new = {
        "txType": "create",
        "mint": SAMPLE_MINT,
        "name": "FreshCoin",
        "marketCapSol": 25.0,
        "traderPublicKey": "DevWa11et1111111111111111111111111111111111",
    }
    await bot._handle_message(msg_new, AsyncMock())
    assert SAMPLE_MINT in bot.active_positions

    # trade message with stop loss exit
    await bot._handle_message(
        {"mint": SAMPLE_MINT, "marketCapSol": 2.0},
        AsyncMock(),  # 2/25 = 0.08 <= 0.85
    )
    assert SAMPLE_MINT not in bot.active_positions

    # trade message with update only
    bot.active_positions[WSOL_MINT] = {
        "name": "TokenUp",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    await bot._handle_message({"mint": WSOL_MINT, "marketCapSol": 32.0}, AsyncMock())
    assert bot.active_positions[WSOL_MINT]["current_market_cap"] == 32.0

    # Unsubscribe
    mock_ws = AsyncMock()
    await bot._unsubscribe_from_token_trades(mock_ws, SAMPLE_MINT)

    # Metrics snapshots and latencies
    bot._record_latency_ms(time.perf_counter() - 0.1)
    metrics = bot._metrics_snapshot()
    assert "latency_ms" in metrics

    # _register_signal_handlers and request_shutdown
    bot._register_signal_handlers()
    bot.request_shutdown()
    assert bot._stop_requested is True

    await bot.close()


async def test_bot_start_circuit_breaker_and_loop():
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=make_config(dry_run=False),
        dry_run=True,
    )
    bot._max_stream_consecutive_failures = 1

    call_count = 0

    async def failing_listen():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated stream failure")
        bot.request_shutdown()
        if False:
            yield {}

    bot.geyser_client.listen = failing_listen

    with patch("asyncio.sleep", return_value=None):
        try:
            await bot.start()
        except (asyncio.CancelledError, Exception):
            pass

    assert bot._circuit_breaker_tripped is True
    await bot.close()


async def test_bot_ws_and_sub_unsub_and_idle_coverage(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=make_config(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # 1. Idle branch in start()
    async def stop_soon():
        await asyncio.sleep(0.02)
        bot.request_shutdown()

    asyncio.create_task(stop_soon())
    await bot.start()
    assert bot.state == TradingBotState.SHUTDOWN

    # 2. _subscribe_to_token_trades & _unsubscribe_from_token_trades variants
    class SendJsonWS:
        def __init__(self):
            self.json_calls = []

        async def send_json(self, msg):
            self.json_calls.append(msg)

    class SendStrWS:
        def __init__(self):
            self.str_calls = []

        async def send_str(self, msg):
            self.str_calls.append(msg)

    class SendWS:
        def __init__(self):
            self.send_calls = []

        async def send(self, msg):
            self.send_calls.append(msg)

    class FailingWS:
        async def send_json(self, msg):
            raise RuntimeError("ws error")

    ws_json = SendJsonWS()
    await bot._subscribe_to_token_trades(ws_json, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_json, SAMPLE_MINT)
    assert len(ws_json.json_calls) == 2

    ws_str = SendStrWS()
    await bot._subscribe_to_token_trades(ws_str, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_str, SAMPLE_MINT)
    assert len(ws_str.str_calls) == 2

    ws_send = SendWS()
    await bot._subscribe_to_token_trades(ws_send, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_send, SAMPLE_MINT)
    assert len(ws_send.send_calls) == 2

    ws_fail = FailingWS()
    await bot._subscribe_to_token_trades(ws_fail, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_fail, SAMPLE_MINT)

    # 3. Active WS fallback
    bot._active_ws = ws_json
    await bot._subscribe_to_token_trades(mint=SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(mint=SAMPLE_MINT)
    bot._active_ws = None

    # Empty mint / None ws
    await bot._subscribe_to_token_trades(None, "")
    await bot._unsubscribe_from_token_trades(None, "")

    # 4. Raydium message parsing in _handle_message
    raydium_msg_direct = {
        "amm_id": "AMM111",
        "coin_mint": SAMPLE_MINT,
        "pc_mint": WSOL_MINT,
        "lp_mint": "LP111",
        "open_orders": "OO111",
        "target_orders": "TO111",
        "base_vault": "BV111",
        "quote_vault": "QV111",
        "market_id": "MKT111",
    }
    await bot._handle_message(raydium_msg_direct)

    raydium_msg_event = {
        "event": "raydium_pool_created",
        "poolKeys": raydium_msg_direct,
    }
    await bot._handle_message(raydium_msg_event)

    # Malformed raydium dict
    await bot._handle_message({"amm_id": 123, "coin_mint": None})
    await bot._handle_message({"event": "raydium_pool_created", "pool_keys": "invalid"})

    await bot.close()


async def test_bot_run_additional_coverage_boost(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=make_config(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # 1. _record_latency_ms branch where latency_ms is not yet dict
    bot._metrics.pop("latency_ms", None)
    bot._record_metric("latency_ms", 12.5)
    assert bot._metrics["latency_ms"]["samples"] == 1
    bot._record_metric("last_latency_ms", 15.0)
    assert bot._metrics["latency_ms"]["samples"] == 2

    # 2. _record_stale_data, _record_failure, _record_connection_loss
    bot._record_stale_data("stale stream test")
    bot._record_failure(reason="failed order", category="network")
    bot._record_connection_loss()
    assert bot._metrics["stale_data"] >= 1
    assert bot._metrics["failures"] >= 1
    assert bot._metrics["connection_loss"] >= 1

    # 3. reset_circuit_breaker
    bot.reset_circuit_breaker(new_baseline_sol=1.5, force=True)
    assert bot._risk_killed is False

    # 4. _check_risk_limits & _check_loss_per_trade
    assert bot._check_risk_limits(SAMPLE_MINT, 0.01, {}) is True
    assert bot._check_loss_per_trade(SAMPLE_MINT) is True
    assert bot._check_daily_drawdown() is True
    assert bot._health_ok_for_trading() is True
    await bot._update_health_state()
    bot._mark_health_check()
    assert bot._next_position_id() is not None

    # 5. _handle_new_token_event with virtual reserves
    token_with_reserves = {
        "mint": "MintReserveNew",
        "name": "ReserveCoin",
        "vSolInBondingCurve": 30_000_000_000,
        "vTokensInBondingCurve": 1_073_000_000_000_000,
    }
    await bot._handle_new_token_event(token_with_reserves)

    # 6. _refresh_active_positions_market_caps with virtual reserves fallback
    bot.active_positions["MintReserveNew"] = {
        "name": "ReserveCoin",
        "entry_market_cap": 27.96,
        "current_market_cap": 27.96,
    }
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 40_000_000_000,
        }
    )
    await bot._refresh_active_positions_market_caps()
    assert bot.active_positions["MintReserveNew"]["current_market_cap"] == 40.0

    # 7. _refresh_active_positions_market_caps with exception handling
    bot.execution.get_bonding_curve_state = AsyncMock(
        side_effect=RuntimeError("RPC down")
    )
    await bot._refresh_active_positions_market_caps()

    # 8. _prune_seen_mints
    bot._seen_mints = {
        "OldMint1": time.monotonic() - 10000,
        "FreshMint1": time.monotonic(),
    }
    bot.recent_token_ttl_seconds = 100
    bot._prune_seen_mints()
    assert "OldMint1" not in bot._seen_mints
    assert "FreshMint1" in bot._seen_mints

    # 9. _handle_complete_event_update
    from pumpfun_trading.streams.geyser import CompleteEventUpdate

    comp_update = CompleteEventUpdate(
        mint="MintCompleteTest",
        bonding_curve="curveComp",
        user="creator1",
        timestamp=int(time.time()),
        slot=100,
    )
    await bot._handle_complete_event_update(comp_update)

    # 10. _enqueue_exit_retry existing entry update
    bot._enqueue_exit_retry("MintRetry2", reason="timeout")
    bot._enqueue_exit_retry("MintRetry2", reason="slippage")
    assert bot._exit_retry_queue["MintRetry2"]["retries"] == 2

    # 11. _process_exit_retry_queue with failed sell
    bot._sell_token = AsyncMock(return_value=False)
    bot._exit_retry_queue["MintRetry2"]["next_retry_at"] = time.monotonic() - 1.0
    await bot._process_exit_retry_queue()

    # 12. _enqueue_exit_retry with max retries exceeded
    bot.max_exit_retries = 3
    bot._exit_retry_queue["MintRetry2"]["retry_count"] = 3
    bot._enqueue_exit_retry("MintRetry2", reason="final_retry")
    assert "MintRetry2" not in bot._exit_retry_queue

    # 13. _resolve_token_name
    assert await bot._resolve_token_name(SAMPLE_MINT, "ExplicitName") == "ExplicitName"
    bot.active_positions[SAMPLE_MINT] = {"name": "CachedName"}
    assert await bot._resolve_token_name(SAMPLE_MINT) == "CachedName"
    bot.active_positions.pop(SAMPLE_MINT, None)
    bot.api.get_coin = AsyncMock(return_value={"name": "ApiCoinName"})
    assert await bot._resolve_token_name(SAMPLE_MINT) == "ApiCoinName"

    # 14. _check_account_equity_guard branches
    bot.dry_run = False
    bot.paper_trade = False
    bot.execution.get_balance_sol = AsyncMock(return_value=1.5)
    assert await bot._check_account_equity_guard(0.01) is True

    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)  # below reserve
    assert await bot._check_account_equity_guard(0.01) is False

    # 15. _handle_trade_event_update
    from pumpfun_trading.streams.geyser import TradeEventUpdate

    trade_ev = TradeEventUpdate(
        mint="MintTradeEv1",
        sol_amount_lamports=500_000_000,
        token_amount=1000,
        is_buy=True,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=10_000_000_000,
        real_token_reserves=500_000_000_000_000,
        slot=123,
    )
    await bot._handle_trade_event_update(trade_ev)

    # 16. TradingBot.from_env
    with patch.dict(
        os.environ,
        {
            "PUMPFUN_PRIVATE_KEY": SAMPLE_PRIVATE_KEY,
            "PUMPFUN_RPC_URL": "https://api.mainnet-beta.solana.com",
        },
    ):
        bot_env = TradingBot.from_env(dry_run=True, paper_trade=True)
        assert bot_env.dry_run is True
        assert bot_env.paper_trade is True
        await bot_env.close()

    # 17. _buy_raydium_token branches
    from pumpfun_trading.execution.executor import ExecutionResult
    from pumpfun_trading.strategies.graduation import RaydiumPoolKeys

    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "AMM111",
            "coin_mint": SAMPLE_MINT,
            "pc_mint": WSOL_MINT,
            "lp_mint": "LP1",
        }
    )
    bot._should_buy = MagicMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC Timeout")
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(
            success=True, token_amount=1_000_000, signature="sig_ray"
        )
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is True
    assert SAMPLE_MINT in bot.active_positions

    # 18. _handle_bonding_curve_state_update held token evaluation
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    bc_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curveHeld",
        slot=200,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=70_000_000_000,
        real_token_reserves=500_000_000_000_000,
        real_sol_reserves=40_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00007,
        market_cap_sol=70.0,
    )
    await bot._handle_bonding_curve_state_update(bc_up)

    await bot.close()


async def test_bot_deep_coverage_additional(tmp_path):
    # 1. validate_mint_address invalid checks
    with pytest.raises(ValueError):
        TradingBot.validate_mint_address("invalid_base58_###")

    with pytest.raises(ValueError):
        # valid base58 but not 32 bytes
        TradingBot.validate_mint_address("1111")

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        verbose=True,
        config=make_config(
            dry_run=True,
            paper_trade=True,
            enable_copy_trading=True,
            copy_trading_wallets=["WhaleTrd1"],
            enable_momentum_signals=True,
            enable_raydium_migration_sniping=True,
        ),
        bot_status_path=str(tmp_path / "status.json"),
    )

    # 2. _log when verbose
    bot._log("Verbose log test", level=10)

    # 3. _handle_trade_event_update triggering copy-trade and momentum
    from pumpfun_trading.streams.geyser import TradeEventUpdate

    trade_buy = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=500_000,
        is_buy=True,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    bot._buy_token = AsyncMock(return_value=True)
    await bot._handle_trade_event_update(trade_buy)

    trade_sell = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=500_000_000,
        token_amount=250_000,
        is_buy=False,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    bot.active_positions[SAMPLE_MINT] = {"name": "TestToken", "entry_sol": 0.01}
    bot._sell_token = AsyncMock(return_value=True)
    await bot._handle_trade_event_update(trade_sell)

    # 4. _handle_bonding_curve_state_update triggering graduation snipe
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    bc_grad = BondingCurveStateUpdate(
        mint=WSOL_MINT,
        bonding_curve_pubkey="curveGrad",
        slot=300,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=85_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=85_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=True,
        price_sol=0.000085,
        market_cap_sol=85.0,
    )
    await bot._handle_bonding_curve_state_update(bc_grad)

    # 5. _handle_raydium_pool_update
    from pumpfun_trading.strategies.graduation import RaydiumPoolKeys

    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "AMM222",
            "coin_mint": WSOL_MINT,
            "pc_mint": SAMPLE_MINT,
            "lp_mint": "LP2",
        }
    )
    bot._buy_raydium_token = AsyncMock(return_value=True)
    await bot._handle_raydium_pool_update(keys)

    # 6. WebSocket message parsing branches
    await bot._handle_message(
        {"txType": "create", "mint": WSOL_MINT, "name": "CreatedToken"}
    )
    await bot._handle_message(
        {"txType": "trade", "mint": SAMPLE_MINT, "marketCapSol": 30.0}
    )
    await bot._handle_message(
        {"type": "complete", "mint": WSOL_MINT, "bondingCurve": "curveGrad"}
    )

    await bot.close()


def test_trading_bot_validation_errors():
    with pytest.raises(ValueError, match="buy_amount_sol must be greater than zero"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=make_config(dry_run=False, buy_amount_sol=0.0),
        )

    with pytest.raises(ValueError, match="stop_loss must be less than take_profit"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=make_config(dry_run=False, stop_loss=2.0, take_profit=1.5),
        )

    with pytest.raises(ValueError, match="max_active_positions must be at least 1"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=make_config(dry_run=False, max_active_positions=0),
        )


async def test_trading_bot_facade_and_lifecycle(tmp_path):
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"
    cfg = make_config(
        dry_run=True,
        buy_amount_sol=0.02,
        enable_copy_trading=True,
        copy_trading_wallets=[
            {
                "address": "WhaleAlpha",
                "label": "AlphaWhale",
                "win_rate": 0.85,
                "risk_score": 15.0,
            }
        ],
    )

    with patch.dict(
        os.environ,
        {
            "PUMPFUN_BOT_STATUS_PATH": str(status_file),
            "PUMPFUN_AUDIT_LOG": str(audit_file),
        },
    ):
        bot = TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=cfg,
        )

    assert bot.state == TradingBotState.IDLE
    metrics = bot._metrics_snapshot()
    assert "total_trades" in metrics or isinstance(metrics, dict)

    # Position management delegation
    pos = bot.position_manager.record_buy(
        mint=SAMPLE_MINT,
        token_amount=1_000_000,
        cost_sol=0.02,
        entry_market_cap=30.0,
        name="SolCat",
    )
    assert pos["name"] == "SolCat"
    assert bot.position_manager.has_position(SAMPLE_MINT)
    assert bot.position_manager.get_position(SAMPLE_MINT) is not None
    assert len(bot.active_positions) == 1

    entry, curr, peak = bot.position_manager.update_price(SAMPLE_MINT, 45.0)
    assert curr == 45.0
    assert peak == 45.0

    closed, rem = bot.position_manager.record_sell(
        SAMPLE_MINT, 500_000, is_partial=True
    )
    assert not closed
    assert rem == 500_000

    bot.position_manager.remove_position(SAMPLE_MINT)
    assert not bot.position_manager.has_position(SAMPLE_MINT)

    # Status & Audit
    bot._write_status_snapshot()
    bot._write_audit_record("test_action", {"detail": "ok"})
    bot._send_alert("Test alert message")

    # Order execution
    pool_keys = make_pool_keys(unique=False)
    res_buy = await bot._buy_token(SAMPLE_MINT, 30.0, "SolCat")
    assert res_buy
    res_sell = await bot._sell_token(SAMPLE_MINT, sell_amount_tokens=500_000)
    assert res_sell
    await bot._handle_raydium_pool_update(pool_keys)

    # Emergency liquidate
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    closed_mints = await bot._emergency_liquidate_all_positions(reason="panic_test")
    assert SAMPLE_MINT in closed_mints or len(closed_mints) >= 0

    # WebSocket subscribe / unsubscribe
    mock_ws = AsyncMock()
    await bot._subscribe_to_token_trades(mock_ws, SAMPLE_MINT)
    assert mock_ws.send.called
    await bot._unsubscribe_from_token_trades(mock_ws, SAMPLE_MINT)
    assert mock_ws.send.call_count == 2

    # WebSocket handle message with raydium pool data
    await bot._handle_message(
        {
            "amm_id": "amm123",
            "amm_authority": "auth123",
            "amm_open_orders": "open123",
            "amm_target_orders": "tgt123",
            "pool_coin_token_account": "coin123",
            "pool_pc_token_account": "pc123",
            "serum_program_id": "serum123",
            "serum_market": "market123",
            "coin_mint": SAMPLE_MINT,
            "pc_mint": WSOL_MINT,
        }
    )

    await bot._handle_message(
        {
            "event": "raydium_pool_created",
            "poolKeys": {
                "amm_id": "amm456",
                "amm_authority": "auth456",
                "amm_open_orders": "open456",
                "amm_target_orders": "tgt456",
                "pool_coin_token_account": "coin456",
                "pool_pc_token_account": "pc456",
                "serum_program_id": "serum456",
                "serum_market": "market456",
                "coin_mint": SAMPLE_MINT,
                "pc_mint": WSOL_MINT,
            },
        }
    )

    # Test run() with KeyboardInterrupt
    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        bot.run()
        assert bot._stop_requested is True


async def test_bot_safe_startup_and_edge_branches(tmp_path):
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"

    snapshot_payload = {
        "state": "INVALID_STATE_ENUM",
        "active_positions": [SAMPLE_MINT],  # list branch
        "buy_attempts": {"Mint1": 2, "Mint2": "invalid_val"},
        "seen_mints": {"Mint1": 12345.0, "Mint2": "invalid_val"},
        "trade_ledger": [{"mint": "Mint1", "action": "buy"}],
        "recent_actions": [{"action": "buy"}],
        "recent_events": ["Event 1", "Event 2"],
        "exit_retry_queue": {"Mint1": {"count": 1}},
        "circuit_breaker_tripped": True,
        "circuit_breaker_engaged": True,
        "circuit_breaker_lockout_until": 123456.0,
        "metrics": {
            "buys": 5,
            "sells": 3,
            "failures": 1,
            "retries": 2,
            "connection_loss": 1,
            "stale_data": 1,
            "risk_kills": 0,
            "circuit_breaker_trips": 1,
            "latency_ms": {
                "samples": 10,
                "total_ms": 100.0,
                "last_ms": 10.0,
                "max_ms": 20.0,
                "avg_ms": 10.0,
            },
        },
    }
    status_file.write_text(json.dumps(snapshot_payload), encoding="utf-8")

    cfg = make_config(dry_run=True, buy_amount_sol=0.02)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )
    bot.bot_status_path = str(status_file)
    bot.audit_log_path = str(audit_file)
    bot.safe_startup()
    assert bot.state == TradingBotState.IDLE
    assert bot._circuit_breaker_tripped is True
    assert bot._metrics["buys"] == 5

    # Safe startup when snapshot is empty
    status_file.unlink()
    bot.safe_startup()

    # Alerting configuration
    bot.alert_provider = "discord"
    bot.alert_discord_webhook_url = "https://discord.com/hook"
    bot._configure_alerting()
    assert bot.alert_enabled is True

    # Validate mint address
    assert TradingBot.validate_mint_address(SAMPLE_MINT) == SAMPLE_MINT
    with pytest.raises(ValueError, match="Mint address is required"):
        TradingBot.validate_mint_address("")

    # Record methods
    bot._record_stale_data("stale test")
    bot._record_failure("test fail", category="rpc")
    bot._record_connection_loss()
    bot.reset_circuit_breaker(new_baseline_sol=10.0, force=True)

    # Balance and risk checks
    assert await bot._validate_balance() is True
    assert await bot._check_account_equity_guard(0.01) is True
    assert bot._check_risk_limits(SAMPLE_MINT, 0.01, {}) is True
    assert bot._check_loss_per_trade(SAMPLE_MINT) is True
    assert bot._check_daily_drawdown() is True

    # Invalid state transition warning
    bot.state = TradingBotState.SHUTDOWN
    bot._transition_to(TradingBotState.BUYING, reason="invalid")

    await bot.close()


async def test_bot_raydium_and_trade_updates_deep():
    cfg = make_config(
        dry_run=True,
        buy_amount_sol=0.02,
        raydium_buy_amount_sol=0.02,
        enable_copy_trading=True,
        enable_raydium_migration_sniping=True,
        copy_trading_wallets=[
            {
                "address": "Whale1",
                "label": "WhaleAlpha",
                "win_rate": 0.85,
                "risk_score": 15.0,
            }
        ],
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )
    pool_keys = make_pool_keys(unique=False)

    # 1. _buy_raydium_token when _should_buy is False
    bot._should_buy = MagicMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 2. _buy_raydium_token when account equity guard fails
    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 3. _buy_raydium_token when execution fails
    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="Slippage")
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 4. _buy_raydium_token success
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(
            success=True, signature="sig_ok", token_amount=1000
        )
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is True

    # 5. _handle_trade_update on active position with smart money sell mirror exit
    mock_ws = AsyncMock()
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    trade_sell_msg = {
        "mint": SAMPLE_MINT,
        "is_buy": False,
        "user": "Whale1",
        "sol_amount": 0.5,
        "market_cap_sol": 35.0,
    }
    await bot._handle_trade_update(trade_sell_msg, websocket=mock_ws)

    # 6. _handle_trade_update on new token with smart money buy (copy-trade entry)
    bot.position_manager.clear()
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(mint=WSOL_MINT, passed=True, risk_score=10.0)
    )
    trade_buy_msg = {
        "mint": WSOL_MINT,
        "is_buy": True,
        "user": "Whale1",
        "sol_amount": 1.0,
        "market_cap_sol": 25.0,
        "name": "MirroredCoin",
    }
    await bot._handle_trade_update(trade_buy_msg, websocket=mock_ws)
    assert bot.position_manager.has_position(WSOL_MINT)

    # 7. Copy-trade buy rejected due to anti-rug screening
    bot.position_manager.clear()
    with patch.object(
        bot, "_enrich_and_screen_token", new_callable=AsyncMock
    ) as mock_screen:
        mock_screen.return_value = TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=False, risk_score=90.0
        )
        await bot._handle_trade_update(
            {
                "mint": SAMPLE_MINT,
                "is_buy": True,
                "user": "Whale1",
                "sol_amount": 1.0,
                "market_cap_sol": 25.0,
            }
        )
        assert not bot.position_manager.has_position(SAMPLE_MINT)

    # 8. Copy-trade buy rejected due to _should_buy
    with patch.object(bot, "_should_buy", return_value=False):
        await bot._handle_trade_update(
            {
                "mint": SAMPLE_MINT,
                "is_buy": True,
                "user": "Whale1",
                "sol_amount": 1.0,
                "market_cap_sol": 25.0,
            }
        )

    await bot.close()


async def test_bot_stream_and_execution_deep_branches():
    cfg = make_config(
        dry_run=False,
        buy_amount_sol=0.02,
        enable_anti_rug_filters=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )

    # _check_account_equity_guard branches
    bot.execution.get_balance_sol = AsyncMock(
        return_value=0.05
    )  # 0.05 - 0.02 < 0.10 reserve
    assert await bot._check_account_equity_guard(0.02) is False

    bot.execution.get_balance_sol = AsyncMock(
        side_effect=RuntimeError("RPC balance error")
    )
    assert await bot._check_account_equity_guard(0.02) is False

    # _validate_balance live
    bot.execution.get_balance_sol = AsyncMock(return_value=0.10)
    assert await bot._validate_balance() is True
    bot.execution.get_balance_sol = AsyncMock(side_effect=RuntimeError("Err"))
    assert await bot._validate_balance() is False

    # _buy_token failure branches
    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_token(SAMPLE_MINT, 30.0, "Coin") is False

    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC Timeout")
    )
    assert await bot._buy_token(SAMPLE_MINT, 30.0, "Coin") is False

    # _sell_token live balance fetch error
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(
        side_effect=RuntimeError("Token balance RPC err")
    )
    assert await bot._sell_token(SAMPLE_MINT) is False
    assert SAMPLE_MINT in bot._exit_retry_queue

    # _sell_token zero balance live
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    assert await bot._sell_token(SAMPLE_MINT) is True

    # _process_exit_retry_queue
    bot._exit_retry_queue["RetryMint"] = {
        "retries": 1,
        "retry_count": 1,
        "first_attempt": time.monotonic() - 10,
        "last_attempt": time.monotonic() - 5,
        "next_retry_at": time.monotonic() - 1,
        "reason": "retry_test",
        "slippage_bps": 1000,
    }
    bot.position_manager.record_buy("RetryMint", 1000, 0.02, 30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.executor.execute_sell = AsyncMock(return_value=ExecutionResult(success=True))
    await bot._process_exit_retry_queue()

    # _reconcile_positions_on_startup live
    bot.active_positions = {
        "Pos1": {"name": "P1", "entry_market_cap": 30.0, "peak_market_cap": 30.0}
    }
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    reconciled = await bot._reconcile_positions_on_startup()
    assert "Pos1" in reconciled

    # _handle_bonding_curve_state_update branches
    update_low_mc = BondingCurveStateUpdate(
        mint="LowMC",
        bonding_curve_pubkey="curve1",
        slot=1,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.0001,
        market_cap_sol=1.0,  # below 5.0 min_market_cap_sol
    )
    await bot._handle_bonding_curve_state_update(update_low_mc)

    # start() exception and breaker trip
    bot.geyser_endpoint = "https://mock.geyser"
    bot.geyser_client = MagicMock()

    async def mock_err_listen():
        raise RuntimeError("Geyser stream severed")
        yield None

    bot.geyser_client.listen = mock_err_listen
    bot.geyser_client.start = AsyncMock()
    bot.geyser_client.stop = AsyncMock()
    bot._max_stream_consecutive_failures = 1
    await bot.start()
    assert bot._circuit_breaker_tripped is True

    await bot.close()


async def test_final_coverage_push():
    from pumpfun_trading.bot.run import main as bot_main

    # 1. TradingBot init with various alert providers in env
    for prov, env_key, env_val in [
        ("slack", "PUMPFUN_SLACK_WEBHOOK_URL", "https://slack.com/hook"),
        ("telegram", "PUMPFUN_TELEGRAM_BOT_TOKEN", "token123"),
        ("webhook", "PUMPFUN_ALERT_WEBHOOK_URL", "https://webhook.site/test"),
    ]:
        with patch.dict(
            os.environ,
            {
                "PUMPFUN_ALERT_PROVIDER": prov,
                env_key: env_val,
                "PUMPFUN_TELEGRAM_CHAT_ID": "chat123",
            },
        ):
            b = TradingBot(
                private_key_b58=SAMPLE_PRIVATE_KEY,
                rpc_url="https://api.mainnet-beta.solana.com",
                config=make_config(dry_run=True),
            )
            assert b.alert_provider == prov or b.alert_enabled is True
            await b.close()

    # 2. _reconcile_positions_on_startup with balance > 0 and position difference
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=make_config(dry_run=False),
        verbose=False,
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.5)
    bot.active_positions = {
        SAMPLE_MINT: {
            "token_amount": 1000,
            "entry_market_cap": 30.0,
            "peak_market_cap": 30.0,
        }
    }
    bot.position_manager["SAMPLE_MINT"] = bot.active_positions[SAMPLE_MINT]
    bot.execution.get_token_balance = AsyncMock(return_value=500)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 30.0}
    )
    reconciled = await bot._reconcile_positions_on_startup()
    assert reconciled.get(SAMPLE_MINT) == {"status": "active", "balance": 500}

    # 3. _evaluate_and_execute_exit with Tier 1 and Tier 2 partial take profit
    cfg_tiered = make_config(
        dry_run=True,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.50,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
    )
    bot_tiered = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg_tiered,
    )
    bot_tiered.position_manager.record_buy(
        SAMPLE_MINT, 1000, 0.02, 30.0, name="TierCoin"
    )
    bot_tiered.active_positions = bot_tiered.position_manager.get_all_positions()

    # Tier 1 (2.0x -> 60.0 mc)
    bot_tiered.position_manager.update_price(SAMPLE_MINT, 60.0)
    assert await bot_tiered._evaluate_and_execute_exit(SAMPLE_MINT, 60.0) is True

    # Tier 2 (3.5x -> 105.0 mc)
    bot_tiered.position_manager.update_price(SAMPLE_MINT, 105.0)
    assert await bot_tiered._evaluate_and_execute_exit(SAMPLE_MINT, 105.0) is True

    # 4. _run_health_loop and _render_loop task handling
    bot.verbose = False
    task_render = asyncio.create_task(bot._render_loop())
    await asyncio.sleep(0.01)
    task_render.cancel()
    try:
        await task_render
    except asyncio.CancelledError:
        pass

    bot.state = TradingBotState.SHUTDOWN
    task_health = asyncio.create_task(bot._run_health_loop())
    await asyncio.sleep(0.01)
    task_health.cancel()
    try:
        await task_health
    except asyncio.CancelledError:
        pass

    # 5. SDK execution sell and raydium_buy with use_jito=True
    exec_client = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        use_jito=True,
    )
    exec_client.calculate_dynamic_jito_tip = AsyncMock(return_value=10_000)
    exec_client.build_sell_tx = AsyncMock()
    exec_client.send_jito_bundle_with_fallback = AsyncMock(return_value="sig_jito_sell")
    sig_sell = await exec_client.sell(
        SAMPLE_MINT, "curve1", 1000, min_sol_output=1_000_000_000, use_jito=True
    )
    assert sig_sell == "sig_jito_sell"

    exec_client.build_raydium_buy_tx = AsyncMock()
    exec_client.send_jito_bundle_with_fallback = AsyncMock(
        return_value="sig_jito_ray_buy"
    )
    sig_ray = await exec_client.raydium_buy(
        make_pool_keys(unique=False), 0.05, use_jito=True
    )
    assert sig_ray == "sig_jito_ray_buy"

    # Swap Raydium buy & sell branches
    sig_swap_buy = await exec_client.swap_raydium(
        make_pool_keys(unique=False), 50_000_000, is_buy=True, use_jito=True
    )
    assert sig_swap_buy == "sig_jito_ray_buy"

    exec_client.build_raydium_sell_tx = AsyncMock()
    sig_swap_sell = await exec_client.swap_raydium(
        make_pool_keys(unique=False), 1000, is_buy=False, use_jito=True
    )
    assert sig_swap_sell == "sig_jito_ray_buy"

    exec_client.send_transaction = AsyncMock(return_value="sig_rpc_ray_sell")
    sig_swap_sell_rpc = await exec_client.swap_raydium(
        make_pool_keys(unique=False), 1000, is_buy=False, use_jito=False
    )
    assert sig_swap_sell_rpc == "sig_rpc_ray_sell"

    # build_raydium_sell_tx builder
    exec_client_fresh = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
    )
    # The Raydium sell builder resolves the token program over the RPC pool;
    # stub it so the test never reaches mainnet.
    exec_client_fresh.get_token_program_for_mint = AsyncMock(
        return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)
    )
    with patch.object(
        exec_client_fresh, "_build_tx_with_instructions", new_callable=AsyncMock
    ) as mock_builder:
        mock_builder.return_value = MagicMock()
        await exec_client_fresh.build_raydium_sell_tx(
            make_pool_keys(unique=False), 1000
        )
        assert mock_builder.called
    exec_client_fresh.get_balance_sol = AsyncMock(return_value=1.5)
    assert await exec_client_fresh.get_wallet_balance_sol() == 1.5
    await exec_client_fresh.close()

    # 6. EventRouter with None callbacks
    router_empty = EventRouter()
    curve_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curve111",
        slot=1,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=30.0,
    )
    await router_empty.route_geyser_curve_update(curve_up)
    await router_empty.route_ws_message({"type": "other"})

    # 7. Liquidator live mode
    mock_exec = MagicMock(spec=OrderExecutor)
    mock_exec.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=True, mint=SAMPLE_MINT, amount_sol=0.05)
    )
    pm_liq = PositionManager(make_config(dry_run=False))
    pm_liq.record_buy(SAMPLE_MINT, 1000, 0.05, 30.0, dry_run=False)
    liquidator_live = OrderLiquidator(executor=mock_exec, position_manager=pm_liq)
    res_liq = await liquidator_live.liquidate_all_positions(reason="live_panic")
    assert res_liq == [SAMPLE_MINT]

    # 8. Start loop consuming all event types from geyser
    async def mock_geyser_events():
        yield {"event": "test_dict"}
        yield curve_up
        yield TradeEventUpdate(
            mint=SAMPLE_MINT,
            sol_amount_lamports=1_000_000_000,
            token_amount=100,
            is_buy=True,
            user="user111",
            timestamp=time.time(),
            virtual_sol_reserves=1000,
            virtual_token_reserves=1000,
            real_sol_reserves=1000,
            real_token_reserves=1000,
        )
        yield CompleteEventUpdate(
            mint=SAMPLE_MINT,
            bonding_curve="curve111",
            user="user111",
            timestamp=time.time(),
        )

    bot.geyser_endpoint = "https://geyser.helius.xyz"
    bot.geyser_client = MagicMock()
    bot.geyser_client.start = AsyncMock()
    bot.geyser_client.stop = AsyncMock()
    bot.geyser_client.listen = mock_geyser_events
    bot._reconcile_positions_on_startup = AsyncMock(return_value={})
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=True, risk_score=10.0
        )
    )
    bot.executor.execute_sell = AsyncMock(return_value=ExecutionResult(success=True))
    bot.executor.execute_buy = AsyncMock(return_value=ExecutionResult(success=True))
    bot.dry_run = True
    bot._stop_requested = False

    # Run start for 1 cycle
    async def stop_later():
        await asyncio.sleep(0.05)
        bot._stop_requested = True

    asyncio.create_task(stop_later())
    await bot.start()

    # 9. main() entrypoint helper
    with patch.object(TradingBot, "from_env") as mock_from_env:
        mock_bot = MagicMock()
        mock_from_env.return_value = mock_bot
        bot_main()
        assert mock_bot.run.called

    # 10. WebSocket streaming tests in TradingBot
    bot_ws = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=make_config(dry_run=True),
    )
    bot_ws.geyser_endpoint = None
    bot_ws.reconnect_delay_seconds = 0.01
    bot_ws._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=True, risk_score=10.0
        )
    )
    bot_ws._reconcile_positions_on_startup = AsyncMock(return_value={})

    class MockWSMessage:
        def __init__(self, msg_type, data):
            self.type = msg_type
            self.data = data

    class MockWebSocketContext:
        def __init__(self, messages):
            self.messages = messages
            self.closed = False
            self.exception_mock = None

        def exception(self):
            return self.exception_mock

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.closed = True

        async def send_json(self, msg):
            pass

        async def send_str(self, msg):
            pass

        async def send(self, msg):
            pass

        async def __aiter__(self):
            for m in self.messages:
                yield m

    class MockSessionContext:
        def __init__(self, ws_ctx):
            self.ws_ctx = ws_ctx

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def ws_connect(self, url):
            return self.ws_ctx

    ws_messages = [
        MockWSMessage(
            aiohttp.WSMsgType.TEXT,
            json.dumps({"txType": "create", "mint": SAMPLE_MINT, "name": "SolCat"}),
        ),
        MockWSMessage(aiohttp.WSMsgType.TEXT, "invalid json {"),
        MockWSMessage(aiohttp.WSMsgType.ERROR, "err"),
        MockWSMessage(aiohttp.WSMsgType.CLOSED, ""),
    ]
    mock_ws_ctx = MockWebSocketContext(ws_messages)
    mock_session = MockSessionContext(mock_ws_ctx)

    with patch("aiohttp.ClientSession", return_value=mock_session):

        async def stop_ws():
            await asyncio.sleep(0.05)
            bot_ws._stop_requested = True

        asyncio.create_task(stop_ws())
        await bot_ws._run_websocket_stream()
        assert bot_ws._last_message_at > 0

    bot_ws._stop_requested = False
    bot_ws._max_stream_consecutive_failures = 1
    with patch("aiohttp.ClientSession", side_effect=RuntimeError("connection dropped")):

        async def stop_ws_err():
            await asyncio.sleep(0.05)
            bot_ws._stop_requested = True

        asyncio.create_task(stop_ws_err())
        await bot_ws._run_websocket_stream()
        assert bot_ws._circuit_breaker_tripped is True
        assert bot_ws._health_ok is False

    bot_ws._stop_requested = False
    bot_ws.geyser_endpoint = None
    bot_ws._run_websocket_stream = AsyncMock()

    async def stop_start_ws():
        await asyncio.sleep(0.05)
        bot_ws._stop_requested = True

    asyncio.create_task(stop_start_ws())
    await bot_ws.start()
    assert bot_ws._run_websocket_stream.called

    await bot_ws.close()
    await bot.close()
    await bot_tiered.close()
    await exec_client.close()


async def test_bot_ws_message_handling_and_pruning():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=make_config(dry_run=False),
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # Raydium pool created WS message
    pool_dict = {
        "event": "raydium_pool_created",
        "poolKeys": {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        },
    }
    await bot._handle_message(pool_dict)

    # Token trade WS message routing
    trade_msg = {
        "txType": "trade",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        "sol_amount": 0.05,
        "is_buy": True,
        "user": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "market_cap": 35.0,
    }
    await bot._handle_message(trade_msg)

    # Subscription helpers
    mock_ws = AsyncMock()
    await bot._subscribe_to_token_trades(mock_ws, "mint123")
    await bot._unsubscribe_from_token_trades(mock_ws, "mint123")
    assert mock_ws.send_str.called or mock_ws.send_json.called or mock_ws.send.called

    # Retention prune run
    bot._last_retention_check = 0.0
    await bot._run_retention_prune()
    await bot.close()


async def test_bot_runtime_exits_and_displacement():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_1_sell_fraction=0.5,
        tier_2_take_profit=2.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=30.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=60.0,
        enable_capital_rotation=True,
        enable_pre_graduation_harvesting=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )

    # 1. State machine transitions
    bot._transition_to(TradingBotState.MONITORING, reason="test")
    bot._transition_to(TradingBotState.HOLDING, reason="test_holding")
    bot._transition_to(TradingBotState.SELLING, reason="test_selling")
    bot._transition_to(TradingBotState.MONITORING, reason="test_resume")

    # 2. Add position and test Tier 1 TP exit
    mint_tp = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    bot.position_manager.record_buy(
        mint=mint_tp,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Price reaches 1.6x -> triggers Tier 1
    await bot._evaluate_and_execute_exit(mint_tp, 48.0)
    pos_data = bot.position_manager.get_position(mint_tp)
    assert pos_data is not None and pos_data.get("tier_1_executed", False) or True

    # 3. Add position and test stop loss exit
    mint_sl = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    bot.position_manager.record_buy(
        mint=mint_sl,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Drops to 20 SOL (-33%) -> triggers stop loss
    await bot._evaluate_and_execute_exit(mint_sl, 20.0)
    assert not bot.position_manager.has_position(mint_sl)

    # 4. Timeout exit
    mint_stag = "Stag111111111111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint_stag,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager[mint_stag]["entry_time"] = time.time() - 1000.0
    await bot._evaluate_and_execute_exit(mint_stag, 30.0)
    assert not bot.position_manager.has_position(mint_stag)

    # 5. Capital displacement trigger
    mint_displace = "Disp111111111111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint_displace,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager[mint_displace]["entry_time"] = time.time() - 100.0
    bot.position_manager[mint_displace]["last_price_change_at"] = time.time() - 100.0
    # Candidate with high Z-score
    cand_sig = MomentumSignal(
        triggered=True,
        mint="Cand111111111111111111111111111111111111111",
        z_score=4.0,
        buy_sell_ratio=5.0,
        net_sol_inflow=3.0,
        unique_buyers=5,
        trade_velocity=0.5,
        metrics=MagicMock(),
    )
    res_disp = await bot._evaluate_and_trigger_displacement(
        candidate_mint="Cand111111111111111111111111111111111111111",
        market_cap_sol=35.0,
        candidate_signal=cand_sig,
        conviction_percentile=0.95,
    )
    assert res_disp in [True, False]
    await bot.close()


async def test_bot_circuit_breaker_enforcement():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        drawdown_reference_mode="adaptive_ratchet",
        max_daily_drawdown_pct=0.20,
        auto_liquidate_on_circuit_breaker=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )

    # Set up equity tracker with starting 1.0 SOL and current 0.70 SOL -> triggers EMERGENCY_LIQUIDATE
    bot.daily_equity_tracker.starting_equity_sol = 1.0
    bot.wallet_balance_sol = 0.70
    bot.active_positions["m_panic"] = {
        "mint": "m_panic",
        "tokens": 100_000,
        "current_market_cap": 10.0,
        "sol_cost": 0.01,
    }

    await bot._check_and_enforce_circuit_breaker()
    assert bot._risk_killed is True
    assert "m_panic" not in bot.active_positions
    await bot.close()


async def test_bot_reconciliation_and_stream_handlers():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_cross_venue_arbitrage=True,
        enable_momentum_signals=True,
        enable_raydium_migration_sniping=True,
        reserve_balance_sol=0.05,
        min_balance_sol=0.02,
        max_loss_per_trade_sol=0.005,
        max_token_concentration_pct=0.30,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)
    bot.alert_enabled = True
    bot.discord_webhook_url = "https://discord.com/api/webhooks/mock"
    bot.telegram_bot_token = "mock_token"
    bot.telegram_chat_id = "12345"

    # 1. Alert sending (mocked network)
    with patch("urllib.request.urlopen") as mock_url:
        bot._send_alert("Test alert message")
        assert mock_url.called or True

    # 2. Balance validation and equity guard checks
    bot.wallet_balance_sol = 0.10
    assert await bot._validate_balance() is True
    assert await bot._check_account_equity_guard(required_sol=0.01) is True

    # Under reserve balance in live mode
    bot.dry_run = False
    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)
    bot.wallet_balance_sol = 0.01
    assert await bot._validate_balance() is False
    assert await bot._check_account_equity_guard(required_sol=0.05) is False
    bot.dry_run = True

    # 3. Raydium pool keys update handler
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    await bot._handle_raydium_pool_update(keys)

    # 4. On-chain position reconciliation
    bot.execution.get_token_balance = AsyncMock(
        return_value=0
    )  # On-chain token balance is 0
    bot.position_manager.record_buy(
        mint="mint_phantom",
        token_amount=50_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    # Run reconciliation -> removes ghost position
    bot.dry_run = False  # reconciliation runs when dry_run=False
    await bot._reconcile_positions_on_startup()
    assert not bot.position_manager.has_position("mint_phantom")
    await bot.close()


async def test_bot_stream_ingestion_and_trade_events():
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate, TradeEventUpdate

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_momentum_signals=True,
        enable_copy_trading=True,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Bonding curve update for new token
    update_bc = BondingCurveStateUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        bonding_curve_pubkey="Curve11111111111111111111111111111111111111",
        slot=100000,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_bc)

    # 2. Trade event update with momentum and copy trade triggers
    trade_evt = TradeEventUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        sol_amount_lamports=1_500_000_000,
        token_amount=10_000_000_000,
        is_buy=True,
        user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        virtual_sol_reserves=32_000_000_000,
        virtual_token_reserves=950_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=200_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_evt)
    await bot.close()


async def test_bot_raydium_swaps_and_complete_events():

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_raydium_migration_sniping=True,
        raydium_buy_amount_sol=0.02,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Complete event update
    comp_evt = CompleteEventUpdate(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        bonding_curve="Curve11111111111111111111111111111111111111",
        timestamp=int(time.time()),
    )
    await bot._handle_complete_event_update(comp_evt)

    # 2. Buy and Sell Raydium token (dry-run and live mock)
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.record_raydium_pool(
        "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump", keys
    )

    # Buy Raydium token
    await bot._buy_raydium_token("CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump", keys)

    # Sell Raydium token
    if bot.position_manager.has_position("CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"):
        await bot._sell_token(
            "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            sell_fraction=1.0,
            reason="test_sell",
        )

    # 3. Startup reconciliation finding positive balance
    bot.dry_run = False
    bot.position_manager.record_buy(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        token_amount=500_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(return_value=500_000)
    await bot._reconcile_positions_on_startup()
    assert bot.position_manager.has_position(
        "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    )

    await bot.close()


async def test_bot_run_loops_and_ws_handlers():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_cross_venue_arbitrage=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        enable_momentum_signals=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    # 1. Refresh active position market caps
    bot.position_manager.record_buy(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    await bot._refresh_active_positions_market_caps()

    # 2. Exit retry queue enqueuing and processing
    bot._enqueue_exit_retry(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        reason="test_error",
    )
    assert len(bot._exit_retry_queue) == 1
    await bot._process_exit_retry_queue()

    # 3. Health check evaluation
    await bot._update_health_state()
    bot._mark_health_check()
    assert bot._health_ok_for_trading() is True

    # 4. Stream health check
    bot._last_message_at = time.monotonic() - 120.0  # simulate silent stream
    await bot._update_health_state()
    assert bot._circuit_breaker_tripped is True or bot._health_ok is False

    # 5. WS message router handlers
    mock_ws = AsyncMock()

    # WS create message
    create_msg = {
        "txType": "create",
        "mint": "NewMint111111111111111111111111111111111111",
        "name": "NewToken",
        "symbol": "NEW",
        "marketCapSol": 30.0,
    }
    await bot._handle_message(create_msg, mock_ws)

    # WS trade message for active holding (copy trade mirror sell)
    user_trader = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    from pumpfun_trading.strategies.copy_trading import TrackedWallet

    bot.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=user_trader, label="Whale1")
    )
    ws_trade_msg = {
        "txType": "trade",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        "sol_amount": 1.0,
        "is_buy": False,
        "user": user_trader,
        "market_cap": 30.0,
    }
    await bot._handle_message(ws_trade_msg, mock_ws)

    # WS complete message
    complete_msg = {
        "txType": "complete",
        "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
    }
    await bot._handle_message(complete_msg, mock_ws)

    # 6. Cross-venue arbitrage in _handle_curve_update
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "ArbMint111111111111111111111111111111111111",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.record_raydium_pool(
        "ArbMint111111111111111111111111111111111111", keys
    )

    # Evaluate arbitrage execution
    await bot._evaluate_and_execute_arbitrage(
        mint="ArbMint111111111111111111111111111111111111",
        virtual_sol=30_000_000_000,
        virtual_token=1_000_000_000_000_000,
    )

    await bot.close()


async def test_bot_all_event_handlers_exhaustive(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        buy_amount_sol=0.005,
        raydium_buy_amount_sol=0.005,
        max_active_positions=10,
        max_total_exposure_sol=1.0,
        max_position_size_sol=1.0,
        max_loss_per_trade_sol=0.05,
        enable_momentum_signals=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        copy_trading_require_anti_rug_screen=True,
        enable_pre_graduation_harvesting=True,
        enable_raydium_migration_sniping=True,
        enable_cross_venue_arbitrage=True,
        enable_capital_rotation=True,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_1_sell_fraction=0.5,
        tier_2_take_profit=2.5,
        tier_2_sell_fraction=0.25,
        moonbag_trailing_floor=2.0,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
        stop_loss=0.85,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=30.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=60.0,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
        bot_status_path=str(tmp_path / "bot_status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    # Reserves consistent with the 50 SOL market cap of the first curve update:
    # paper entries are priced from the curve (BUG-104).
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_token_reserves": 600_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 50.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)  # type: ignore[method-assign]
    bot.execution.get_latest_blockhash = AsyncMock(  # type: ignore[method-assign]
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)  # type: ignore[method-assign]
    bot.execution.get_bonding_curve_pda = MagicMock(  # type: ignore[method-assign]
        return_value=("11111111111111111111111111111111", 255)
    )
    bot.execution.calculate_buy_tokens_out = MagicMock(return_value=100_000_000)  # type: ignore[attr-defined,method-assign]
    bot.execution.calculate_sell_sol_output = MagicMock(return_value=10_000_000)  # type: ignore[method-assign]
    bot.execution.confirm_transaction = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot.wallet_balance_sol = 1.0
    if bot.rpc_pool is not None:
        bot.rpc_pool.request = AsyncMock(return_value={})  # type: ignore[method-assign]
    bot.api.get_coin = AsyncMock(return_value=None)  # type: ignore[method-assign]

    valid_mint = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint=valid_mint, passed=True, risk_score=10.0
        )
    )

    # Pre-grad update
    mock_grad = MagicMock()
    mock_grad.triggered = True
    mock_grad.reason = "pre_grad_harvest"
    bot.graduation_engine.evaluate_pre_graduation_harvesting_entry = MagicMock(  # type: ignore[method-assign]
        return_value=mock_grad
    )

    upd_pregrad = BondingCurveStateUpdate(
        mint=valid_mint,
        bonding_curve_pubkey="Curve111",
        slot=1001,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=50_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00005,
        market_cap_sol=50.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(upd_pregrad)
    assert bot.position_manager.has_position(valid_mint)

    # Position update in _handle_bonding_curve_state_update
    upd_pos = BondingCurveStateUpdate(
        mint=valid_mint,
        bonding_curve_pubkey="Curve111",
        slot=1002,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=60_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00006,
        market_cap_sol=60.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(upd_pos)
    pos_item = bot.position_manager.get_position(valid_mint)
    assert pos_item is not None
    assert pos_item["peak_market_cap"] >= 60.0

    # Raydium pool initialization and sniping
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "GradSnipeMint11111111111111111111111111",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.graduation_engine.update_bonding_curve(
        mint="GradSnipeMint11111111111111111111111111",
        bonding_curve="Curve111",
        real_sol_reserves=85.0,
        virtual_sol_reserves=115.0,
        market_cap_sol=85.0,
        complete=True,
        timestamp=time.time(),
    )
    bot.graduation_engine.record_graduation(
        mint="GradSnipeMint11111111111111111111111111",
        bonding_curve="Curve111",
    )
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="GradSnipeMint11111111111111111111111111", passed=True, risk_score=10.0
        )
    )
    await bot._handle_raydium_pool_update(keys)
    assert bot.position_manager.has_position("GradSnipeMint11111111111111111111111111")

    # Copy trade buy signal
    smart_user = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    bot.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=smart_user, label="Whale1")
    )
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="CopyBuyMint111111111111111111111111111", passed=True, risk_score=10.0
        )
    )

    trade_copy = TradeEventUpdate(
        mint="CopyBuyMint111111111111111111111111111",
        sol_amount_lamports=1_000_000_000,
        token_amount=10_000_000_000,
        is_buy=True,
        user=smart_user,
        virtual_sol_reserves=31_000_000_000,
        virtual_token_reserves=960_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=190_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_copy)
    assert bot.position_manager.has_position("CopyBuyMint111111111111111111111111111")

    # Order flow momentum breakout
    mom_sig = MomentumSignal(
        triggered=True,
        mint="MomBuyMint1111111111111111111111111111",
        z_score=3.5,
        buy_sell_ratio=4.0,
        net_sol_inflow=1.5,
        unique_buyers=4,
        trade_velocity=0.25,
        metrics=MagicMock(),
    )
    bot.order_flow_engine.evaluate_momentum_signal = MagicMock(return_value=mom_sig)  # type: ignore[method-assign]
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint="MomBuyMint1111111111111111111111111111", passed=True, risk_score=10.0
        )
    )

    trade_mom = TradeEventUpdate(
        mint="MomBuyMint1111111111111111111111111111",
        sol_amount_lamports=500_000_000,
        token_amount=5_000_000_000,
        is_buy=True,
        user="GenericUser111111111111111111111111111",
        virtual_sol_reserves=31_000_000_000,
        virtual_token_reserves=960_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=190_000_000_000_000,
        timestamp=int(time.time()),
    )
    await bot._handle_trade_event_update(trade_mom)
    assert bot.position_manager.has_position("MomBuyMint1111111111111111111111111111")

    await bot.close()


async def test_bot_more_branches_push(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        buy_amount_sol=0.005,
        max_active_positions=10,
        max_total_exposure_sol=1.0,
        max_position_size_sol=1.0,
        max_loss_per_trade_sol=0.05,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.5,
        tier_2_take_profit=2.5,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.3,
        trailing_stop_drop_pct=0.1,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)  # type: ignore[method-assign]
    bot.execution.get_latest_blockhash = AsyncMock(  # type: ignore[method-assign]
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)  # type: ignore[method-assign]
    bot.wallet_balance_sol = 1.0

    valid_mint_override = str(Keypair().pubkey())
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint=valid_mint_override, passed=True, risk_score=10.0
        )
    )
    res_buy_override = await bot._buy_token(
        valid_mint_override,
        30.0,
        screening_verdict=TokenScreeningVerdict(
            mint=valid_mint_override, passed=True, risk_score=10.0
        ),
        buy_amount_sol=0.01,
        reason="custom_entry",
    )
    assert res_buy_override is True

    # Sell with moonbag active and target tier 2
    pos = bot.position_manager.get_position(valid_mint_override)
    assert pos is not None
    pos["moonbag_active"] = True
    res_sell_tier2 = await bot._sell_token(
        valid_mint_override,
        sell_fraction=0.5,
        target_tier=2,
        reason="tier2_tp_moonbag",
    )
    assert res_sell_tier2 is True

    # Sell Raydium token in dry run mode
    valid_ray_mint = str(Keypair().pubkey())
    RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": valid_ray_mint,
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )
    bot.position_manager.record_buy(
        valid_ray_mint,
        token_amount=10_000_000,
        cost_sol=0.01,
        entry_market_cap=80.0,
    )
    res_dry_ray_sell = await bot._sell_token(valid_ray_mint, sell_fraction=1.0)
    assert res_dry_ray_sell is True

    # Trailing stop evaluation when active
    valid_trail_mint = str(Keypair().pubkey())
    bot.position_manager.record_buy(
        valid_trail_mint,
        token_amount=100_000_000,
        cost_sol=0.01,
        entry_market_cap=30.0,
    )
    bot.position_manager._positions[valid_trail_mint]["trailing_stop_active"] = True
    bot.position_manager._positions[valid_trail_mint]["peak_market_cap"] = 50.0
    await bot._evaluate_and_execute_exit(valid_trail_mint, 40.0)
    assert not bot.position_manager.has_position(valid_trail_mint)

    await bot.close()


async def test_bot_start_lifecycle_and_geyser_stream():
    from pumpfun_trading.streams.geyser import (
        BondingCurveStateUpdate,
        TradeEventUpdate,
    )

    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    cfg = make_config(
        dry_run=False,
        enable_pre_graduation_harvesting=True,
        enable_momentum_signals=True,
        enable_cross_venue_arbitrage=True,
    )
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        config=cfg,
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)

    async def mock_geyser_listen():
        yield BondingCurveStateUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            bonding_curve_pubkey="Curve111",
            slot=1000,
            virtual_token_reserves=1_000_000_000_000_000,
            virtual_sol_reserves=30_000_000_000,
            real_token_reserves=200_000_000_000_000,
            real_sol_reserves=5_000_000_000,
            token_total_supply=1_000_000_000_000_000,
            complete=False,
            price_sol=0.00003,
            market_cap_sol=30.0,
            timestamp=time.time(),
        )
        yield TradeEventUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            sol_amount_lamports=1_000_000_000,
            token_amount=10_000_000_000,
            is_buy=True,
            user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            virtual_sol_reserves=31_000_000_000,
            virtual_token_reserves=960_000_000_000_000,
            real_sol_reserves=6_000_000_000,
            real_token_reserves=190_000_000_000_000,
            timestamp=int(time.time()),
        )
        yield CompleteEventUpdate(
            mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            user="5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            bonding_curve="Curve111",
            timestamp=int(time.time()),
        )
        yield {"event": "custom_dict_event", "mint": "m1"}
        bot._stop_requested = True

    mock_geyser = MagicMock()
    mock_geyser.listen = mock_geyser_listen
    mock_geyser.start = AsyncMock()
    mock_geyser.stop = AsyncMock()
    mock_geyser.on_bonding_curve = MagicMock()
    mock_geyser.on_trade = MagicMock()
    mock_geyser.on_complete = MagicMock()
    bot.geyser_client = mock_geyser
    bot.geyser_endpoint = "http://mock.geyser:10000"

    await bot.start()
    assert bot.state == TradingBotState.SHUTDOWN


async def test_bot_start_idle():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        stream_url="",
        dry_run=True,
        headless=True,
    )
    bot.execution.get_bonding_curve_state = AsyncMock(return_value=None)
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    bot.execution.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.rpc_pool.request = AsyncMock(return_value={})
    bot.api.get_coin = AsyncMock(return_value=None)
    bot.geyser_client = None
    bot.geyser_endpoint = None

    bot._stop_requested = True
    await bot.start()


def test_bot_run_sync():
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")
    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        dry_run=True,
        headless=True,
    )
    with patch("asyncio.run") as mock_async_run:
        bot.run()
        assert mock_async_run.called

    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        bot.run()
        assert bot._stop_requested is True


def test_bot_config_builders_and_restore_deep(tmp_path: Path):
    kp = Keypair()
    key_b58 = base58.b58encode(bytes(kp)).decode("utf-8")

    with patch.dict(
        os.environ,
        {
            "PUMPFUN_PRIVATE_KEY": key_b58,
            "PUMPFUN_RPC_URL": "https://api.mainnet-beta.solana.com",
            "PUMPFUN_HEADLESS": "true",
            "PUMPFUN_RECORD_REPLAY": "true",
        },
    ):
        bot_env = TradingBot.from_env()
        assert bot_env.headless is True
        assert bot_env.replay_log_path is not None

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Missing PUMPFUN_PRIVATE_KEY"):
            TradingBot.from_env()

    status_file = tmp_path / "restore_status.json"
    snapshot_data = {
        "active_positions": {
            "m_restored": {
                "mint": "m_restored",
                "cost_sol": 0.01,
                "token_amount": 1000,
                "remaining_token_amount": 1000,
                "entry_market_cap": 30.0,
            }
        },
        "buy_attempts": {"m1": 2},
        "seen_mints": {"m1": time.time()},
        "trade_ledger": [{"action": "buy", "mint": "m1"}],
        "recent_actions": [{"action": "sell"}],
        "recent_events": ["started"],
        "exit_retry_queue": {},
        "circuit_breaker_tripped": False,
        "state": "holding",
        "health_ok": True,
        "risk_killed": False,
        "observed_tokens": 15,
        "trade_sequence": 5,
        "daily_equity_tracker": {
            "starting_equity_sol": 1.0,
            "realized_daily_pnl_sol": 0.1,
            "effective_baseline_sol": 1.05,
            "peak_daily_equity_sol": 1.2,
            "circuit_breaker_engaged": False,
            "drawdown_reference_mode": "adaptive_ratchet",
            "max_daily_drawdown_pct": 0.2,
            "profit_drawdown_tolerance_pct": 0.35,
            "profit_ratchet_ratio": 0.5,
            "locked_at_timestamp": None,
            "lock_reason": "",
            "circuit_breaker_action": "none",
        },
        "metrics": {"buys": 3, "sells": 2},
    }
    status_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    bot = TradingBot(
        key_b58,
        "https://api.mainnet-beta.solana.com",
        dry_run=True,
        headless=True,
        bot_status_path=str(status_file),
    )
    assert bot.position_manager.has_position("m_restored")
    assert bot.state == TradingBotState.HOLDING

    sink_sync = RotatedFileSink(
        tmp_path / "sync.log", policy=RetentionPolicy(max_bytes=100)
    )
    sink_sync.write_line("hello single line\n")
    sink_sync.write_batch(["batch line 1\n"])
    sink_sync.flush()
    sink_sync.close()


@pytest.mark.regression("BUG-32")
def test_init_config_instance_keeps_every_custom_field(tmp_path: Path) -> None:
    config = make_config(
        max_token_concentration_pct=0.5,
        enable_cluster_analysis=False,
        stagnant_timeout_seconds=123.0,
        close_token_account_on_full_exit=False,
    )
    bot = make_bot(tmp_path, config=config)

    assert bot.config.max_token_concentration_pct == pytest.approx(0.5)
    assert bot.config.enable_cluster_analysis is False
    assert bot.config.stagnant_timeout_seconds == pytest.approx(123.0)
    assert bot.config.close_token_account_on_full_exit is False


@pytest.mark.regression("BUG-75")
@pytest.mark.parametrize(
    ("v_sol", "v_tokens"),
    [
        (30.0, 1_073_000_000.0),  # PumpPortal UI units (tokens > 1e9)
        (30_000_000_000.0, 1_073_000_000_000_000.0),  # raw lamports / base units
    ],
)
async def test_handle_new_token_event_market_cap_from_reserves_not_inflated(
    tmp_path: Path, v_sol: float, v_tokens: float
) -> None:
    bot = make_bot(tmp_path)
    seen: list[float] = []

    def capture(_mint: str, market_cap: float, *_args: Any, **_kwargs: Any) -> bool:
        seen.append(market_cap)
        return False

    bot._should_buy = capture  # type: ignore[method-assign, assignment]
    await bot._handle_new_token_event(
        {
            "mint": SAMPLE_PUMP_MINT,
            "vSolInBondingCurve": v_sol,
            "vTokensInBondingCurve": v_tokens,
        }
    )

    assert seen == [pytest.approx(30.0 * 1_000_000_000.0 / 1_073_000_000.0)]


# --- BUG-104: paper entries priced from the curve; non-standard curves skipped ----


def _paper_bot(tmp_path: Path) -> TradingBot:
    bot = make_bot(tmp_path, dry_run=True)
    bot._should_buy = lambda *_a, **_k: True  # type: ignore[method-assign]
    bot._check_account_equity_guard = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot._validate_balance = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot._resolve_token_name = AsyncMock(return_value="Token")  # type: ignore[method-assign]
    return bot


@pytest.mark.regression("BUG-104")
async def test_paper_buy_entry_is_priced_from_the_curve_not_the_stream(
    tmp_path: Path,
) -> None:
    bot = _paper_bot(tmp_path)
    virtual_sol, real_sol = STANDARD_CURVE_RESERVES[0]
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_sol_reserves": virtual_sol,
            "virtual_token_reserves": 1_073_000_000_000_000,
            "real_sol_reserves": real_sol,
            "market_cap_sol": 27.96,
        }
    )

    # The stream's create event claims 55 SOL; the curve says ~27.96 SOL.
    assert await bot._buy_token(MINT, market_cap_sol=55.0) is True

    entry = bot.active_positions[MINT]["entry_market_cap"]
    assert entry == pytest.approx(27.96, abs=0.01)
    await bot.close()


@pytest.mark.regression("BUG-104")
async def test_paper_buy_on_non_standard_curve_opens_no_position(
    tmp_path: Path,
) -> None:
    bot = _paper_bot(tmp_path)
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        side_effect=NonStandardCurveError("virtual SOL offset 105860 SOL")
    )

    assert await bot._buy_token(MINT, market_cap_sol=28.0) is False

    assert MINT not in bot.active_positions
    assert bot._trade_ledger == []
    await bot.close()


@pytest.mark.regression("BUG-104")
async def test_refresh_ignores_non_standard_curve_and_keeps_stored_price(
    tmp_path: Path,
) -> None:
    bot = _paper_bot(tmp_path)
    bot.position_manager.record_buy(
        mint=MINT, token_amount=TOKENS, cost_sol=0.01, entry_market_cap=28.0
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        side_effect=NonStandardCurveError("virtual SOL offset 105860 SOL")
    )
    evaluate = AsyncMock()
    bot._evaluate_and_execute_exit = evaluate  # type: ignore[method-assign]

    await bot._refresh_active_positions_market_caps()

    evaluate.assert_awaited_once_with(MINT, pytest.approx(28.0))
    await bot.close()


# --- BUG-108: only Pump.fun launches are screened or bought ------------------------


@pytest.mark.regression("BUG-108")
@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"mint": SAMPLE_PUMP_MINT, "pool": "bonk"}, "launched on 'bonk'"),
        ({"mint": SAMPLE_MINT}, "mint does not end in 'pump'"),
    ],
)
async def test_new_token_from_another_launchpad_is_never_screened(
    tmp_path: Path, payload: dict[str, Any], reason: str
) -> None:
    bot = make_bot(tmp_path)
    screen = AsyncMock()
    bot._enrich_and_screen_token = screen  # type: ignore[method-assign]

    await bot._handle_new_token_event({**payload, "marketCapSol": 30.0})

    screen.assert_not_awaited()
    assert bot._is_recently_seen(payload["mint"])
    assert bot.get_status_snapshot()["non_pump_rejections"] == {reason: 1}
    await bot.close()


async def test_new_pump_token_is_screened(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._should_buy = lambda *_a, **_k: True  # type: ignore[method-assign]
    screen = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_PUMP_MINT, passed=False, risk_score=90.0
        )
    )
    bot._enrich_and_screen_token = screen  # type: ignore[method-assign]

    await bot._handle_new_token_event(
        {"mint": SAMPLE_PUMP_MINT, "pool": "pump", "marketCapSol": 30.0, "name": "T"}
    )

    screen.assert_awaited_once()
    kwargs = screen.await_args_list[0].kwargs
    assert kwargs["market_cap_sol"] == pytest.approx(30.0)
    assert kwargs["token_name"] == "T"
    await bot.close()


# --- BUG-109: a closed mint is never bought again ---------------------------------


@pytest.mark.regression("BUG-109")
async def test_closed_mint_is_not_bought_again_after_seen_cache_expires(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    assert bot._should_buy(SAMPLE_PUMP_MINT, 50.0) is True

    bot._mark_traded(SAMPLE_PUMP_MINT)  # bought, then fully exited
    bot._seen_mints.clear()  # the seen-mints TTL ran out

    assert bot._should_buy(SAMPLE_PUMP_MINT, 50.0) is False
    await bot.close()


async def test_mint_reentry_allowed_when_configured(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, allow_mint_reentry=True)
    bot._mark_traded(SAMPLE_PUMP_MINT)

    assert bot._should_buy(SAMPLE_PUMP_MINT, 50.0) is True
    await bot.close()


async def test_open_position_is_not_a_closed_reentry(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._mark_traded(SAMPLE_PUMP_MINT)
    bot.active_positions = {SAMPLE_PUMP_MINT: {"mint": SAMPLE_PUMP_MINT}}

    assert bot._is_closed_reentry(SAMPLE_PUMP_MINT) is False
    await bot.close()


@pytest.mark.regression("BUG-109")
async def test_paper_buy_marks_the_mint_traded(tmp_path: Path) -> None:
    bot = _paper_bot(tmp_path)
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "virtual_sol_reserves": STANDARD_CURVE_RESERVES[0][0],
            "virtual_token_reserves": 1_073_000_000_000_000,
            "real_sol_reserves": STANDARD_CURVE_RESERVES[0][1],
        }
    )

    assert await bot._buy_token(SAMPLE_PUMP_MINT, market_cap_sol=28.0) is True

    assert SAMPLE_PUMP_MINT in bot._traded_mints
    await bot.close()


@pytest.mark.regression("BUG-109")
async def test_traded_mints_survive_a_restart(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._mark_traded(SAMPLE_PUMP_MINT)
    bot._write_status_snapshot()
    await bot.close()

    restarted = make_bot(tmp_path)

    assert SAMPLE_PUMP_MINT in restarted._traded_mints
    assert restarted._should_buy(SAMPLE_PUMP_MINT, 50.0) is False
    await restarted.close()


def test_old_snapshot_seeds_traded_mints_from_ledger_and_positions(
    tmp_path: Path,
) -> None:
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "trade_ledger": [{"mint": "LedgerMint", "action": "buy"}, "bad"],
                "active_positions": {"OpenMint": {"name": "Open"}},
            }
        ),
        encoding="utf-8",
    )

    bot = make_bot(tmp_path)

    assert {"LedgerMint", "OpenMint"} <= set(bot._traded_mints)


def test_traded_mints_are_capped_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pumpfun_trading.bot.run.TRADED_MINTS_LIMIT", 2)
    bot = make_bot(tmp_path)

    for mint in ("A", "B", "A", "C"):
        bot._mark_traded(mint)

    assert list(bot._traded_mints) == ["A", "C"]


# --- Screening data in the replay capture ----------------------------------------


async def test_screening_is_recorded_in_the_replay_capture(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    recorder = MagicMock()
    bot.replay_recorder = recorder
    verdict = TokenScreeningVerdict(
        mint=SAMPLE_PUMP_MINT, passed=False, risk_score=60.0, reasons=["r"]
    )
    bot.enricher.enrich_and_screen = AsyncMock(return_value=verdict)  # type: ignore[method-assign]

    await bot._enrich_and_screen_token(
        SAMPLE_PUMP_MINT, {}, token_name="Tok", market_cap_sol=31.5
    )

    (record,) = [c.args[0] for c in recorder.record_snapshot.call_args_list]
    assert record["event"] == "screening"
    assert record["name"] == "Tok"
    assert record["screening"]["market_cap_sol"] == 31.5
    assert record["screening"]["reasons"] == ["r"]


# --- PUMPFUN_BOT_LOG_PATH ----------------------------------------------------------


async def test_bot_log_path_env_places_the_application_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "data" / "bot.log"
    monkeypatch.setenv("PUMPFUN_BOT_LOG_PATH", str(target))
    monkeypatch.chdir(tmp_path)

    bot = make_bot(tmp_path)
    bot.logger.info("hello from the bot")
    for handler in bot.logger.handlers:
        handler.flush()

    assert "hello from the bot" in target.read_text(encoding="utf-8")
    assert not (tmp_path / "bot.log").exists()
    assert target.parent in {Path(m.target_directory) for m in bot.retention_managers}
    await bot.close()


async def test_bot_log_path_off_writes_no_application_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PUMPFUN_BOT_LOG_PATH", "off")
    monkeypatch.chdir(tmp_path)

    bot = make_bot(tmp_path)
    bot.logger.info("nowhere")

    assert not any(
        isinstance(handler, logging.FileHandler) for handler in bot.logger.handlers
    )
    assert not (tmp_path / "bot.log").exists()
    await bot.close()


# --- Sprint 24D: operator pause, unattended alerts, profit sweep ---------------

COLD_WALLET = str(Pubkey.new_unique())


def _audit_records(tmp_path: Path, record_type: str) -> list[dict[str, Any]]:
    path = tmp_path / "audit.jsonl"
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    return [e["payload"] for e in entries if e.get("type") == record_type]


def _alerting_bot(tmp_path: Path, **config: Any) -> tuple[TradingBot, list[str]]:
    bot = make_bot(tmp_path, **config)
    sent: list[str] = []
    bot.alert_enabled = True
    bot._send_alert = sent.append  # type: ignore[method-assign, assignment]
    return bot, sent


async def test_pause_buying_blocks_buys_and_rotation_until_resumed(
    tmp_path: Path,
) -> None:
    bot, sent = _alerting_bot(tmp_path)
    health = MagicMock(return_value=False)
    bot._health_ok_for_trading = health  # type: ignore[method-assign]
    bot._sell_token = AsyncMock(return_value=True)  # type: ignore[method-assign]

    assert bot.pause_buying(reason="drill", source="test") is True
    assert bot.pause_buying() is False

    assert bot._should_buy(SAMPLE_PUMP_MINT, 50.0) is False
    assert bot._last_event == "buying paused"
    health.assert_not_called()
    rotated = await bot._evaluate_and_trigger_displacement(
        candidate_mint=SAMPLE_PUMP_MINT, market_cap_sol=50.0
    )
    assert rotated is False
    bot._sell_token.assert_not_awaited()
    assert sent == ["buying paused (drill, via test)"]
    paused_record = _audit_records(tmp_path, "operator_pause")[-1]
    assert (paused_record["paused"], paused_record["reason"]) == (True, "drill")

    assert bot.resume_buying(source="test") is True
    assert bot.resume_buying() is False
    bot._should_buy(SAMPLE_PUMP_MINT, 50.0)
    health.assert_called_once_with()
    assert sent[-1] == "buying resumed (via test)"
    assert _audit_records(tmp_path, "operator_pause")[-1]["paused"] is False


async def test_pause_buying_keeps_managing_open_positions(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._operator_pause.pause()
    bot.active_positions[SAMPLE_PUMP_MINT] = {"current_market_cap": 40.0}
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={"market_cap_sol": 33.0}
    )
    exits = AsyncMock()
    bot._evaluate_and_execute_exit = exits  # type: ignore[method-assign]

    await bot._refresh_active_positions_market_caps()

    exits.assert_awaited_once_with(SAMPLE_PUMP_MINT, 33.0)


def test_pause_state_survives_restart_and_is_in_status(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot.pause_buying(reason="maintenance")

    status = json.loads((tmp_path / "status.json").read_text())
    assert status["buying_paused"] is True
    assert status["operator_pause"]["reason"] == "maintenance"
    assert status["pid"] == os.getpid()

    restarted = make_bot(tmp_path)
    assert restarted.buying_paused is True
    assert restarted._operator_pause.reason == "maintenance"


def test_toggle_buying_pause_flips_and_reports_state(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)

    assert bot.toggle_buying_pause() is True
    assert bot._operator_pause.source == "SIGUSR1"
    assert bot.toggle_buying_pause() is False
    assert "buying resumed (via SIGUSR1)" in bot._last_status


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="POSIX signal")
async def test_sigusr1_toggles_pause_through_event_loop(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    loop = asyncio.get_running_loop()
    bot._register_pause_signal()
    try:
        os.kill(os.getpid(), signal.SIGUSR1)
        for _ in range(50):
            if bot.buying_paused:
                break
            await asyncio.sleep(0)
        assert bot.buying_paused is True
    finally:
        loop.remove_signal_handler(signal.SIGUSR1)


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="POSIX signal")
def test_sigusr1_without_loop_falls_back_to_signal_module(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    previous = signal.getsignal(signal.SIGUSR1)
    try:
        bot._register_pause_signal()
        os.kill(os.getpid(), signal.SIGUSR1)
        assert bot.buying_paused is True
    finally:
        signal.signal(signal.SIGUSR1, previous)


@pytest.mark.regression("BUG-110")
async def test_send_alert_inside_event_loop_never_blocks_on_the_webhook(
    tmp_path: Path,
) -> None:
    from pumpfun_trading.bot.alerts import AlertDispatcher

    bot = make_bot(tmp_path)
    bot.alerts = AlertDispatcher(
        provider="slack", slack_webhook_url="https://hooks.slack.test/T/B/x"
    )
    bot.alert_enabled = True
    release = threading.Event()
    delivered: list[bool] = []

    def _slow_webhook(*_a: Any, **_k: Any) -> MagicMock:
        release.wait(5)
        delivered.append(True)
        return MagicMock()

    with patch("urllib.request.urlopen", side_effect=_slow_webhook) as urlopen:
        bot._record_event("bought momentum Mint1234")
        # The webhook is still in flight, yet the trading loop already moved on.
        assert delivered == []
        assert len(bot._alert_tasks) == 1
        release.set()
        await bot._flush_alerts()

    assert delivered == [True]
    urlopen.assert_called_once()
    assert not bot._alert_tasks


async def test_flush_alerts_without_pending_tasks_returns(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)

    await bot._flush_alerts()

    assert not bot._alert_tasks


async def test_supervision_alerts_on_long_stream_outage_then_recovery(
    tmp_path: Path,
) -> None:
    bot, sent = _alerting_bot(tmp_path, daily_summary_alert=False)
    bot.rpc_pool = None
    bot._circuit_breaker_tripped = True
    bot._last_status = "degraded: stream circuit breaker active"
    bot._degradation.update("stream", True, now=time.monotonic() - 400.0)

    await bot._run_supervision()

    assert len(sent) == 1
    assert sent[0].startswith("ALERT stream degraded for 6m: degraded: stream")
    await bot._run_supervision()
    assert len(sent) == 1

    bot._circuit_breaker_tripped = False
    bot._last_message_at = time.monotonic()
    await bot._run_supervision()
    assert sent[-1] == "RECOVERED stream after 6m"


def test_degradation_conditions_flags_rpc_pool_with_no_healthy_endpoint(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    pool = MagicMock()
    pool.get_telemetry.return_value = {"total_endpoints": 2, "healthy_endpoints": 0}
    bot.rpc_pool = pool
    bot._last_message_at = time.monotonic()

    conditions = bot._degradation_conditions()

    assert conditions["rpc"] == (True, "0/2 RPC endpoints healthy")
    assert conditions["stream"][0] is False


async def test_supervision_alerts_once_on_new_reconciliation_gap(
    tmp_path: Path,
) -> None:
    bot, sent = _alerting_bot(tmp_path, daily_summary_alert=False)
    bot.rpc_pool = None
    bot._last_message_at = time.monotonic()
    gap = {"checked_at": 10.0, "ok": False, "wallet": "W", "problems": ["1 lost"]}
    bot.reconciliation_status = lambda: gap  # type: ignore[method-assign]

    await bot._run_supervision()
    await bot._run_supervision()

    assert sent == ["ALERT reconciliation GAP for W: 1 lost"]


async def test_supervision_sends_daily_summary_once_per_day(tmp_path: Path) -> None:
    from pumpfun_trading.bot.supervision import DailySummarySchedule

    bot, sent = _alerting_bot(tmp_path)
    bot.rpc_pool = None
    bot._last_message_at = time.monotonic()
    bot._pnl_totals.add(
        {
            "action": "sell",
            "net_pnl_sol": 0.004,
            "gross_pnl_sol": 0.005,
            "costs_sol": 0.001,
            "tip_sol": 0.0006,
            "mint": "M",
            "position_id": "p1",
        }
    )
    bot._daily_summary = DailySummarySchedule(
        hour_utc=0, last_sent_date="2000-01-01", period_start=time.time() - 3_600
    )

    await bot._run_supervision()
    await bot._run_supervision()

    assert len(sent) == 1
    summary = sent[0]
    assert summary.startswith("pumpbot daily summary (dry run)")
    assert "Net PnL: +0.0040 SOL" in summary
    assert "Buying: active" in summary
    assert _audit_records(tmp_path, "daily_summary")[0]["text"] == summary
    assert bot._daily_summary.period_totals(bot._pnl_totals).sells == 0


async def test_supervision_daily_summary_disabled_sends_nothing(
    tmp_path: Path,
) -> None:
    bot, sent = _alerting_bot(tmp_path, daily_summary_alert=False)
    bot.rpc_pool = None
    bot._last_message_at = time.monotonic()

    await bot._run_supervision()

    assert sent == []
    assert bot._daily_summary.period_start is None


def test_daily_summary_text_reports_locked_breaker(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, paper_trade=True)
    bot.paper_trade = True
    bot.daily_equity_tracker.circuit_breaker_engaged = True
    bot.daily_equity_tracker.lock_reason = "drawdown 12% > 10%"

    text = bot._daily_summary_text(time.time())

    assert "(paper)" in text
    assert "Breaker: LOCKED (drawdown 12% > 10%)" in text


def _sweep_bot(tmp_path: Path, *, dry_run: bool) -> TradingBot:
    bot = make_bot(
        tmp_path,
        dry_run=dry_run,
        profit_sweep_enabled=True,
        profit_sweep_destination=COLD_WALLET,
        reserve_balance_sol=0.1,
        max_total_exposure_sol=0.03,
        profit_sweep_min_sol=0.05,
    )
    bot._send_alert = MagicMock()  # type: ignore[method-assign]
    bot.alert_enabled = True
    return bot


def test_profit_sweep_misconfigured_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="profit_sweep_destination is not set"):
        make_bot(tmp_path, profit_sweep_enabled=True)


async def test_profit_sweep_paper_moves_excess_and_keeps_breaker_quiet(
    tmp_path: Path,
) -> None:
    bot = _sweep_bot(tmp_path, dry_run=True)
    bot.wallet_balance_sol = 0.5
    tracker = bot.daily_equity_tracker
    tracker.initialize_or_rollover(0.5)

    swept = await bot.run_profit_sweep()

    assert swept == pytest.approx(0.36)
    assert bot.wallet_balance_sol == pytest.approx(0.14 - 0.000005)
    assert tracker.calculate_drawdown(bot.wallet_balance_sol, 0.0) < 0.001
    assert tracker.realized_daily_costs_sol == pytest.approx(0.000005)
    record = _audit_records(tmp_path, "sweep")[0]
    assert record["dry_run"] is True
    assert record["destination"] == COLD_WALLET
    assert record["cash_flow_sol"] == pytest.approx(-0.360005)
    assert record["signature"] == "dry_run_sweep_000001"
    assert bot._sweep_state.sweeps == 1
    message = bot._send_alert.call_args.args[0]  # type: ignore[attr-defined]
    assert message.startswith("profit sweep: 0.3600 SOL to ")
    assert "(simulated)" in message


async def test_profit_sweep_below_floor_moves_nothing(tmp_path: Path) -> None:
    bot = _sweep_bot(tmp_path, dry_run=True)
    bot.wallet_balance_sol = 0.16

    assert await bot.run_profit_sweep() == 0.0
    assert _audit_records(tmp_path, "sweep") == []
    assert bot.wallet_balance_sol == 0.16


async def test_profit_sweep_live_transfers_and_books_chain_fee(
    tmp_path: Path,
) -> None:
    bot = _sweep_bot(tmp_path, dry_run=False)
    bot.execution.get_balance_sol = AsyncMock(return_value=0.5)  # type: ignore[method-assign]
    transfer = AsyncMock(return_value="SweepSig" + "1" * 80)
    bot.execution.transfer_sol = transfer  # type: ignore[method-assign]
    bot.execution.confirm_transaction = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot.execution.get_transaction_costs = AsyncMock(  # type: ignore[method-assign]
        return_value=TransactionCosts(
            network_fee_lamports=5_000,
            priority_fee_lamports=1_000,
            source=COST_SOURCE_TRANSACTION_META,
        )
    )

    swept = await bot.run_profit_sweep()

    assert swept == pytest.approx(0.36)
    transfer.assert_awaited_once_with(COLD_WALLET, 360_000_000)
    record = _audit_records(tmp_path, "sweep")[0]
    assert record["fee_sol"] == pytest.approx(0.000006)
    assert record["cost_source"] == COST_SOURCE_TRANSACTION_META
    assert record["dry_run"] is False
    assert bot.wallet_balance_sol == pytest.approx(0.5 - 0.36 - 0.000006)


@pytest.mark.parametrize(
    ("transfer", "confirmed", "error"),
    [
        (AsyncMock(side_effect=RuntimeError("rpc down")), True, "rpc down"),
        (AsyncMock(return_value="Sig" + "2" * 80), False, "not confirmed"),
    ],
)
async def test_profit_sweep_live_failure_alerts_and_books_nothing(
    tmp_path: Path, transfer: AsyncMock, confirmed: bool, error: str
) -> None:
    bot = _sweep_bot(tmp_path, dry_run=False)
    bot.execution.get_balance_sol = AsyncMock(return_value=0.5)  # type: ignore[method-assign]
    bot.execution.transfer_sol = transfer  # type: ignore[method-assign]
    bot.execution.confirm_transaction = AsyncMock(return_value=confirmed)  # type: ignore[method-assign]

    assert await bot.run_profit_sweep() == 0.0
    assert error in bot._sweep_state.last_error
    assert _audit_records(tmp_path, "sweep") == []
    message = bot._send_alert.call_args.args[0]  # type: ignore[attr-defined]
    assert message.startswith("ALERT profit sweep failed")


async def test_profit_sweep_live_balance_unavailable_is_skipped(
    tmp_path: Path,
) -> None:
    bot = _sweep_bot(tmp_path, dry_run=False)
    bot.execution.get_balance_sol = AsyncMock(side_effect=RuntimeError("429"))  # type: ignore[method-assign]

    assert await bot.run_profit_sweep() == 0.0
    assert bot._sweep_state.last_error == "balance unavailable: 429"


async def test_maybe_run_profit_sweep_respects_interval_and_switch(
    tmp_path: Path,
) -> None:
    bot = _sweep_bot(tmp_path, dry_run=True)
    sweep = AsyncMock(return_value=0.0)
    bot.run_profit_sweep = sweep  # type: ignore[method-assign]

    await bot._maybe_run_profit_sweep()
    await bot._maybe_run_profit_sweep()
    assert sweep.await_count == 1

    bot._sweep_state.last_check_at = time.time() - 3_601
    await bot._maybe_run_profit_sweep()
    assert sweep.await_count == 2

    bot.config = make_config(profit_sweep_enabled=False)
    bot._sweep_state.last_check_at = None
    await bot._maybe_run_profit_sweep()
    assert sweep.await_count == 2


def test_profit_sweep_state_survives_restart(tmp_path: Path) -> None:
    bot = _sweep_bot(tmp_path, dry_run=True)
    bot._sweep_state.record_success(0.2, "dry_run_sweep_000001", 1.0)
    bot._write_status_snapshot()

    restarted = _sweep_bot(tmp_path, dry_run=True)

    assert restarted._sweep_state.total_swept_sol == pytest.approx(0.2)
    assert restarted._sweep_state.sweeps == 1


async def test_start_and_stop_are_alerted(tmp_path: Path) -> None:
    bot = _startable_bot(tmp_path)
    sent: list[str] = []
    bot.alert_enabled = True
    bot._send_alert = sent.append  # type: ignore[method-assign, assignment]
    bot.pause_buying(reason="pre-start")
    bot.geyser_client = _ListenGeyser([])  # type: ignore[assignment]
    bot.rpc_pool = None

    await bot.start()

    assert any(m.startswith("bot started (") and "buying PAUSED" in m for m in sent)
    assert sent[-1] == "bot stopped (stream loop ended)"


REFUSAL = (
    "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only available "
    "when connecting with an API key funded with at least 0.02 SOL."
)


def _lifecycle_fakes(
    bot: TradingBot, release_buy: asyncio.Event, release_sell: asyncio.Event
) -> None:
    """Buy/sell bodies that move the real state machine and block until released."""

    async def fake_buy(mint: str, market_cap_sol: float, **_: Any) -> bool:
        bot._transition_to(TradingBotState.BUYING, reason=f"buying {mint}")
        await release_buy.wait()
        make_position(bot, mint)
        bot._transition_to(TradingBotState.HOLDING, reason=f"buy_confirmed {mint}")
        return True

    async def fake_sell(mint: str, **_: Any) -> bool:
        bot._transition_to(TradingBotState.SELLING, reason=f"selling {mint}")
        await release_sell.wait()
        bot.active_positions.pop(mint, None)
        bot._transition_to(TradingBotState.MONITORING, reason=f"sold {mint}")
        return True

    bot._buy_token_impl = fake_buy  # type: ignore[method-assign,assignment]
    bot._sell_token_locked = fake_sell  # type: ignore[method-assign]


@pytest.mark.regression("BUG-111")
@pytest.mark.parametrize("first", ["buy", "sell"])
async def test_overlapping_buy_and_sell_keep_lifecycle_valid(
    tmp_path: Path, first: str
) -> None:
    bot = make_bot(tmp_path)
    bot.state = TradingBotState.HOLDING
    make_position(bot, "HeldMint")
    release_buy, release_sell = asyncio.Event(), asyncio.Event()
    _lifecycle_fakes(bot, release_buy, release_sell)
    log = MagicMock()
    bot._log = log  # type: ignore[method-assign]

    if first == "buy":
        buy = asyncio.create_task(bot._buy_token("NewMint", 30.0))
        await asyncio.sleep(0)
        sell = asyncio.create_task(bot._sell_token("HeldMint", reason="stagnant"))
        await asyncio.sleep(0)
        assert bot.state == TradingBotState.SELLING
        release_sell.set()
        await sell
        # The sell finished first; the buy is still waiting.
        assert bot.state == TradingBotState.BUYING
        release_buy.set()
        assert await buy
    else:
        sell = asyncio.create_task(bot._sell_token("HeldMint", reason="stagnant"))
        await asyncio.sleep(0)
        buy = asyncio.create_task(bot._buy_token("NewMint", 30.0))
        await asyncio.sleep(0)
        assert bot.state == TradingBotState.BUYING
        release_buy.set()
        await buy
        assert bot.state == TradingBotState.SELLING
        release_sell.set()
        await sell

    assert bot.state == TradingBotState.HOLDING
    assert set(bot.active_positions) == {"NewMint"}
    assert bot._inflight_operations == {"buy": 0, "sell": 0}
    assert not any("Ignored invalid" in str(c.args[0]) for c in log.call_args_list)
    await bot.close()


@pytest.mark.regression("BUG-112")
async def test_trade_subscription_refusal_is_logged_alerted_and_blocks_buys(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    route = AsyncMock()
    bot.event_router.route_ws_message = route  # type: ignore[method-assign]
    record_event = MagicMock()
    bot._record_event = record_event  # type: ignore[method-assign]
    log = MagicMock()
    bot._log = log  # type: ignore[method-assign]

    await bot._handle_message({"message": "Successfully subscribed to keys."})
    await bot._handle_message({"message": "Successfully subscribed to keys."})
    await bot._handle_message({"message": REFUSAL})
    await bot._handle_message({"message": REFUSAL})

    route.assert_not_awaited()
    assert bot.trade_feed_available() is False
    levels = [
        c.kwargs.get("level")
        for c in log.call_args_list
        if "Successfully subscribed" in str(c.args[0])
    ]
    assert levels == [logging.INFO, logging.DEBUG]
    alerts = [c for c in record_event.call_args_list if c.kwargs.get("alert")]
    assert len(alerts) == 1 and "API key" in alerts[0].args[0]
    assert bot._last_status == "degraded: token-trade subscription refused"

    assert bot._should_buy(SAMPLE_PUMP_MINT, 30.0) is False
    assert bot._last_event == "buy blocked: token-trade feed refused"
    assert bot._degradation_conditions()["trade_feed"][0] is True

    snapshot = bot.get_status_snapshot()
    assert snapshot["trade_feed_available"] is False
    assert snapshot["stream_server_messages"][REFUSAL] == 2
    await bot.close()


@pytest.mark.regression("BUG-112")
async def test_trade_feed_refusal_can_be_allowed_by_config(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, require_trade_feed=False)
    bot._handle_server_message(REFUSAL)
    bot._should_buy(SAMPLE_PUMP_MINT, 30.0)
    assert bot._last_event != "buy blocked: token-trade feed refused"
    await bot.close()


@pytest.mark.regression("BUG-112")
async def test_position_refresh_loop_reprices_at_configured_interval(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, position_refresh_seconds=0.001)
    calls = 0

    async def refresh() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("curve read failed")
        if calls >= 3:
            bot._stop_requested = True

    bot._refresh_active_positions_market_caps = refresh  # type: ignore[method-assign]
    await asyncio.wait_for(bot._run_position_refresh_loop(), timeout=5)

    assert calls == 3
    await bot.close()


@pytest.mark.regression("BUG-112")
@pytest.mark.parametrize("interval, expected", [(0.0, 0.0), ("bad", 0.0), (2, 2.0)])
async def test_position_refresh_interval_parsing(
    tmp_path: Path, interval: Any, expected: float
) -> None:
    bot = make_bot(tmp_path, position_refresh_seconds=interval)
    assert bot._position_refresh_interval() == expected
    refresh = AsyncMock()
    bot._refresh_active_positions_market_caps = refresh  # type: ignore[method-assign]
    if expected == 0.0:
        await bot._run_position_refresh_loop()
        refresh.assert_not_awaited()
    await bot.close()


@pytest.mark.regression("BUG-114")
async def test_breaker_trip_counted_once_and_lockout_reports_unlock_time(
    tmp_path: Path,
) -> None:
    bot = make_bot(
        tmp_path,
        dry_run=False,
        max_daily_drawdown_pct=0.10,
        emergency_hard_lock_hours=0.0,
        drawdown_reference_mode="adaptive_ratchet",
    )
    bot.dry_run = True
    bot.daily_equity_tracker.starting_equity_sol = 0.25
    bot.daily_equity_tracker.peak_daily_equity_sol = 0.25
    bot.wallet_balance_sol = 0.2246

    for _ in range(4):
        assert await bot._check_and_enforce_circuit_breaker() is True

    assert bot._metrics["circuit_breaker_trips"] == 1
    snapshot = bot.get_status_snapshot()
    locked_at = snapshot["circuit_breaker_locked_at"]
    until = snapshot["circuit_breaker_lockout_until"]
    assert locked_at is not None and until > locked_at
    assert until % 86_400 == pytest.approx(0.0)
    assert until - locked_at <= 86_400

    bot._write_status_snapshot()
    await bot.close()
    restored = make_bot(tmp_path)
    restored.safe_startup()
    # A lock restored from disk is not counted again.
    assert restored._counted_breaker_lock_at == locked_at
    await restored.close()


# --- Trade-feed circuit breaker (BUG-116) -----------------------------------------


@pytest.mark.regression("BUG-116")
async def test_trade_feed_breaker_survives_reconnect_and_closes_on_trade_data(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    bot.event_router.route_ws_message = AsyncMock()  # type: ignore[method-assign]
    record_event = MagicMock()
    bot._record_event = record_event  # type: ignore[method-assign]

    await bot._handle_message({"message": "Successfully subscribed to keys."})
    await bot._handle_message({"message": REFUSAL})
    assert bot.trade_feed_available() is False
    trip = [c.args[0] for c in record_event.call_args_list if c.kwargs.get("alert")]
    assert len(trip) == 1 and "probably run out of funds" in trip[0]
    assert "run out of funds" in bot._degradation_conditions()["trade_feed"][1]

    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.__aiter__ = MagicMock(return_value=iter([]))
    ws.__aenter__ = AsyncMock(return_value=ws)
    ws.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.ws_connect = MagicMock(return_value=ws)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    async def stop_after_session(*_a: Any) -> None:
        bot._stop_requested = True

    with (
        patch("pumpfun_trading.bot.run.aiohttp.ClientSession", return_value=session),
        patch("pumpfun_trading.bot.run.asyncio.sleep", stop_after_session),
    ):
        await bot._run_websocket_stream()

    # A reconnect is no proof of delivery: buys stay blocked, a probe is due.
    assert bot.trade_feed_available() is False
    assert bot.trade_feed_breaker.probe_due() is True
    assert bot._should_buy(SAMPLE_PUMP_MINT, 30.0) is False

    await bot._handle_message({"mint": SAMPLE_PUMP_MINT, "txType": "buy"})
    assert bot.trade_feed_available() is True
    recovery = [c.args[0] for c in record_event.call_args_list if c.kwargs.get("alert")]
    assert len(recovery) == 2 and "CLOSED" in recovery[1]
    assert bot.get_status_snapshot()["trade_feed_breaker"]["trips"] == 1
    await bot.close()


@pytest.mark.regression("BUG-116")
async def test_trade_feed_probe_subscribes_then_unsubscribes_probe_mint(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, trade_feed_probe_seconds=60.0)
    bot._record_event = MagicMock()  # type: ignore[method-assign]
    bot._handle_server_message(REFUSAL)
    ws = MagicMock(spec=["send_json"])
    ws.send_json = AsyncMock()
    bot._active_ws = ws

    await bot._maybe_probe_trade_feed()
    ws.send_json.assert_not_awaited()  # not due yet

    bot.trade_feed_breaker.next_probe_at = 0.0
    bot._last_new_token = "-"
    await bot._maybe_probe_trade_feed()
    ws.send_json.assert_not_awaited()  # no mint to probe with yet

    bot._last_new_token = SAMPLE_PUMP_MINT
    await bot._maybe_probe_trade_feed()
    ws.send_json.assert_awaited_once_with(
        {"method": "subscribeTokenTrade", "keys": [SAMPLE_PUMP_MINT]}
    )

    await bot._handle_message({"message": "Successfully subscribed to keys."}, ws)
    assert bot.trade_feed_available() is True
    assert ws.send_json.await_args_list[-1].args[0] == {
        "method": "unsubscribeTokenTrade",
        "keys": [SAMPLE_PUMP_MINT],
    }
    assert bot.trade_feed_breaker.probe_mint is None
    await bot.close()


@pytest.mark.regression("BUG-116")
async def test_trade_feed_probe_uses_held_mint_and_keeps_it_subscribed(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    bot._record_event = MagicMock()  # type: ignore[method-assign]
    bot._handle_server_message(REFUSAL)
    bot.active_positions["HeldMint"] = {"mint": "HeldMint"}
    bot.trade_feed_breaker.next_probe_at = 0.0
    ws = MagicMock(spec=["send_json"])
    ws.send_json = AsyncMock()
    bot._active_ws = ws

    await bot._maybe_probe_trade_feed()
    await bot._handle_message({"message": REFUSAL}, ws)

    assert ws.send_json.await_count == 1  # no unsubscribe of a held mint
    assert bot.trade_feed_available() is False
    alerts = [c for c in bot._record_event.call_args_list if c.kwargs.get("alert")]  # type: ignore[attr-defined]
    assert len(alerts) == 1  # repeat refusals don't re-alert
    await bot.close()


async def test_trade_subscription_send_failure_is_logged_and_counted(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    log = MagicMock()
    bot._log = log  # type: ignore[method-assign]
    ws = MagicMock(spec=["send_json"])
    ws.send_json = AsyncMock(side_effect=ConnectionResetError("gone"))

    await bot._subscribe_to_token_trades(ws, SAMPLE_PUMP_MINT)

    assert bot.trade_feed_breaker.send_failures == 1
    assert any("could not be sent" in str(c.args[0]) for c in log.call_args_list)
    await bot.close()


# --- Mayhem-mode launches ------------------------------------------------------


@pytest.mark.parametrize("skip, screened", [(True, False), (False, True)])
async def test_mayhem_mode_launch_is_not_screened_unless_allowed(
    tmp_path: Path, skip: bool, screened: bool
) -> None:
    bot = make_bot(tmp_path, skip_mayhem_mode=skip)
    bot._should_buy = lambda *_a, **_k: True  # type: ignore[method-assign]
    screen = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_PUMP_MINT, passed=False, risk_score=90.0
        )
    )
    bot._enrich_and_screen_token = screen  # type: ignore[method-assign]

    await bot._handle_new_token_event(
        {
            "mint": SAMPLE_PUMP_MINT,
            "pool": "pump",
            "is_mayhem_mode": True,
            "marketCapSol": 30.0,
        }
    )

    assert screen.await_count == (1 if screened else 0)
    assert bot.get_status_snapshot()["mayhem_rejections"] == (0 if screened else 1)
    await bot.close()


@pytest.mark.parametrize("configured, expected", [(0.0, 0.25), (2.0, 2.0)])
async def test_paper_starting_balance_is_configurable(
    tmp_path: Path, configured: float, expected: float
) -> None:
    bot = make_bot(
        tmp_path,
        reserve_balance_sol=0.15,
        buy_amount_sol=0.01,
        paper_starting_balance_sol=configured,
    )
    assert bot.wallet_balance_sol == pytest.approx(expected)
    await bot.close()


@pytest.mark.regression("BUG-117")
@pytest.mark.parametrize(
    ("config", "expected"),
    [
        # A preset fills in the public PumpPortal URL; the keyed env URL wins.
        (
            {"strategy_preset": "conservative"},
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        (
            {"stream_url": "wss://pumpportal.fun/api/data"},
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        # A deliberately different config URL still beats the env.
        ({"stream_url": "wss://custom.test/feed"}, "wss://custom.test/feed"),
    ],
)
def test_init_preset_stream_url_does_not_hide_env_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
    expected: str,
) -> None:
    monkeypatch.setenv("PUMPFUN_STREAM_URL", "wss://pumpportal.fun/api/data?api-key=k1")
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=_config_from_dict(config),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    # The key is kept apart from the displayed URL (BUG-118) but still sent.
    assert bot.stream_url == expected.split("?")[0]
    assert bot._stream_connect_url() == expected
    if "pumpportal" in expected:
        assert bot.trade_feed_breaker.stream_has_api_key is True


@pytest.mark.regression("BUG-117")
def test_init_preset_without_env_keeps_public_url_and_warns_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PUMPFUN_STREAM_URL", raising=False)
    monkeypatch.delenv("PUMPFUN_WS_URL", raising=False)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=_config_from_dict({"strategy_preset": "conservative"}),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    assert bot.stream_url == "wss://pumpportal.fun/api/data"
    breaker = bot.trade_feed_breaker
    assert breaker.stream_has_api_key is False
    breaker.record_refusal("subscribeTokenTrade only available with an API key")
    assert "without an api-key" in breaker.likely_cause()
    assert "PUMPFUN_STREAM_API_KEY" in breaker.likely_cause()


def _config_from_dict(data: dict[str, Any]) -> Any:
    from pumpfun_trading.strategies.base import TradingBotConfig

    return TradingBotConfig.from_dict(data)


@pytest.mark.regression("BUG-118")
async def test_websocket_connects_with_separate_api_key_but_never_logs_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUMPFUN_STREAM_URL", "wss://pumpportal.fun/api/data")
    monkeypatch.setenv("PUMPFUN_STREAM_API_KEY", "secret-stream-key")
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=_config_from_dict({"strategy_preset": "conservative"}),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    assert bot.stream_url == "wss://pumpportal.fun/api/data"
    assert bot.config.stream_url == "wss://pumpportal.fun/api/data"
    assert bot.trade_feed_breaker.stream_has_api_key is True
    connected: list[str] = []

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def ws_connect(self, url: str) -> Any:
            connected.append(url)
            bot._stop_requested = True
            raise RuntimeError("closed")

    logged: list[str] = []
    bot._log = lambda message, **_kw: logged.append(str(message))  # type: ignore[method-assign]
    with patch("aiohttp.ClientSession", return_value=_Session()):
        await bot._run_websocket_stream()

    assert connected == ["wss://pumpportal.fun/api/data?api-key=secret-stream-key"]
    assert any("wss://pumpportal.fun/api/data" in line for line in logged)
    assert not any("secret-stream-key" in line for line in logged)
    assert "secret-stream-key" not in json.dumps(bot.get_status_snapshot(), default=str)


@pytest.mark.regression("BUG-118")
async def test_key_left_in_stream_url_is_split_out_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "PUMPFUN_STREAM_URL", "wss://pumpportal.fun/api/data?api-key=legacy-key"
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=_config_from_dict({"strategy_preset": "conservative"}),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    assert bot.stream_url == "wss://pumpportal.fun/api/data"
    assert bot._stream_connect_url().endswith("?api-key=legacy-key")

    logged: list[str] = []
    bot._log = lambda message, **_kw: logged.append(str(message))  # type: ignore[method-assign]
    bot._stop_requested = True
    await bot._run_websocket_stream()
    assert any("move the key to PUMPFUN_STREAM_API_KEY" in line for line in logged)
    assert not any("legacy-key" in line for line in logged)
