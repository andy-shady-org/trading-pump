"""Characterisation (golden replay) tests for ``TradingBot`` decisions.

Each scenario feeds a fixed sequence of PumpPortal WebSocket messages to a
dry-run bot through its stream entry point (``_handle_message``) and compares
the resulting decisions with ``golden/<scenario>.json``: every trade-ledger
row (action, reason, SOL amounts net and gross of costs) plus the final
positions, lifecycle state and wallet balance.

They pin today's behaviour so the Sprint 28 decomposition of ``bot/run.py``
can be checked for behavioural equivalence (TESTING.md finding T5). A diff
here means a decision changed: if that is intended, regenerate with
``PUMPFUN_UPDATE_GOLDEN=1 pytest pumpfun_trading/tests/integration/test_golden_replay.py``
and review the JSON diff like code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from pumpfun_trading.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot
from pumpfun_trading.tests.support.fakes import FakeCurves

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("PUMPFUN_UPDATE_GOLDEN") == "1"
THIRD_MINT = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"

LEDGER_FIELDS = (
    "action",
    "mint",
    "reason",
    "strategy",
    "cost_sol",
    "proceeds_sol",
    "gross_pnl_sol",
    "costs_sol",
    "net_pnl_sol",
    "cash_flow_sol",
    "rent_sol",
)

# Screening and momentum need enrichment data a WS message does not carry;
# they have their own unit tests. Here they are off so the scenarios pin the
# entry, sizing and exit decisions.
BASE_CONFIG: dict[str, Any] = {
    "enable_anti_rug_filters": False,
    "enable_momentum_signals": False,
    "enable_cluster_analysis": False,
    "enable_diagnostic_events": False,
}


def _create(mint: str, market_cap: float, name: str) -> dict[str, Any]:
    return {
        "txType": "create",
        "mint": mint,
        "name": name,
        "symbol": name[:4].upper(),
        "marketCapSol": market_cap,
        "traderPublicKey": "Creator1",
    }


def _trade(mint: str, side: str, market_cap: float) -> dict[str, Any]:
    return {
        "txType": side,
        "mint": mint,
        "marketCapSol": market_cap,
        "traderPublicKey": "Trader1",
        "solAmount": 1.0,
    }


SCENARIOS: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {
    "tiered_take_profit_and_trailing": (
        {},
        [
            _create(SAMPLE_PUMP_MINT, 30.0, "Rocket"),
            _trade(SAMPLE_PUMP_MINT, "buy", 40.0),
            _trade(SAMPLE_PUMP_MINT, "buy", 70.0),
            _trade(SAMPLE_PUMP_MINT, "buy", 110.0),
            _trade(SAMPLE_PUMP_MINT, "buy", 140.0),
            _trade(SAMPLE_PUMP_MINT, "sell", 95.0),
            _trade(SAMPLE_PUMP_MINT, "sell", 60.0),
        ],
    ),
    "stop_loss": (
        {},
        [
            _create(SAMPLE_PUMP_MINT, 30.0, "Dud"),
            _trade(SAMPLE_PUMP_MINT, "sell", 28.0),
            _trade(SAMPLE_PUMP_MINT, "sell", 20.0),
        ],
    ),
    "position_cap_and_unheld_trades": (
        {"max_active_positions": 2},
        [
            _create(SAMPLE_PUMP_MINT, 30.0, "First"),
            _create(THIRD_MINT, 32.0, "Second"),
            _create(SAMPLE_MINT, 34.0, "Third"),
            _trade(SAMPLE_MINT, "buy", 90.0),
            _trade(THIRD_MINT, "sell", 22.0),
            _trade(SAMPLE_PUMP_MINT, "buy", 45.0),
        ],
    ),
    "below_min_market_cap_is_skipped": (
        {"min_market_cap_sol": 25.0},
        [
            _create(SAMPLE_PUMP_MINT, 10.0, "Tiny"),
            _trade(SAMPLE_PUMP_MINT, "buy", 60.0),
        ],
    ),
}


def _rounded(value: Any) -> Any:
    return round(value, 12) if isinstance(value, float) else value


async def _run(
    config: dict[str, Any], messages: list[dict[str, Any]], tmp_path: Path
) -> dict[str, Any]:
    bot = make_bot(tmp_path, **{**BASE_CONFIG, **config})
    # Paper fills read the curve (BUG-145): it follows the stream's price.
    curves = FakeCurves().install(bot)
    for message in messages:
        if message.get("marketCapSol"):
            curves.at(str(message["mint"]), float(message["marketCapSol"]))
        await bot._handle_message(message)
    ledger = [
        {field: _rounded(row.get(field)) for field in LEDGER_FIELDS}
        for row in bot._trade_ledger
    ]
    positions = {
        mint: {
            "entry_market_cap": _rounded(position.get("entry_market_cap")),
            "cost_sol": _rounded(position.get("cost_sol")),
            "remaining_token_amount": position.get("remaining_token_amount"),
            "tier_1_executed": position.get("tier_1_executed"),
        }
        for mint, position in sorted(bot.active_positions.items())
    }
    return {
        "ledger": ledger,
        "positions": positions,
        "state": bot.state.value,
        "wallet_balance_sol": _rounded(bot.wallet_balance_sol),
    }


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_golden_replay_decisions_match_recorded(
    scenario: str, tmp_path: Path
) -> None:
    config, messages = SCENARIOS[scenario]
    actual = await _run(config, messages, tmp_path)
    golden = GOLDEN_DIR / f"{scenario}.json"

    if UPDATE:
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")

    assert golden.is_file(), "no golden file; run with PUMPFUN_UPDATE_GOLDEN=1"
    assert actual == json.loads(golden.read_text())
