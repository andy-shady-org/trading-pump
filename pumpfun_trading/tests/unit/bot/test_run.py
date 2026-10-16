"""Unit tests for ``bot/run.py`` net PnL booking (FEAT-49) and the full-exit
token-account close (BUG-96)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.execution.executor import ExecutionResult
from pumpfun_trading.sdk.costs import (
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
)

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"
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
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(buy_amount_sol=0.01, dry_run=False),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
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
        config=TradingBotConfig(
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
def test_init_stream_url_resolution_prefers_env_over_default(
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


def test_status_snapshot_and_events_contain_no_url_credentials(
    tmp_path: Path,
) -> None:
    """BUG-102: provider keys never reach the status file, events or alerts."""
    key = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url=f"https://mainnet.helius-rpc.com/?api-key={key}",
        stream_url=f"wss://feed.example.com/data?token={key}",
        config=TradingBotConfig(buy_amount_sol=0.01),
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
