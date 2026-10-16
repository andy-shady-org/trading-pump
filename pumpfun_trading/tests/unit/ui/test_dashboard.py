"""Unit tests for ``ui/dashboard.py`` net vs. gross PnL and reconciliation rows
(FEAT-49)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.ui.dashboard import (
    _reconciliation_text,
    build_dashboard,
    format_sol_amount,
)

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"


def test_format_sol_amount_switches_to_micro_sol() -> None:
    assert format_sol_amount(0.0) == "+0.0000 SOL"
    assert format_sol_amount(-0.00023) == "-230.0000 µSOL"
    assert format_sol_amount(0.0125) == "+0.0125 SOL"


def test_risk_panel_shows_net_gross_costs_and_session(tmp_path: Path) -> None:
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    bot.daily_equity_tracker.record_realized_trade(0.004, 0.0012)
    bot._pnl_totals.net_pnl_sol = 0.0105

    console = Console(width=220, record=True)
    console.print(build_dashboard(bot))
    text = console.export_text()

    assert "Daily PnL (net)" in text and "+0.0040 SOL" in text
    assert "Daily PnL (gross)" in text and "+0.0052 SOL" in text
    assert "Costs today" in text and "+0.0012 SOL" in text
    assert "Session net PnL" in text and "+0.0105 SOL" in text


@pytest.mark.parametrize(
    "status, expected",
    [
        (None, "not run"),
        ({"ok": True, "trades_checked": 7}, "STALE (7 trades"),
        ({"ok": False, "problems": ["gap"]}, "GAP (1 problem(s)"),
    ],
)
def test_risk_panel_shows_last_reconciliation(
    tmp_path: Path, status: dict[str, Any] | None, expected: str
) -> None:
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        verbose=False,
    )
    if status is not None:
        (tmp_path / "reconcile_status.json").write_text(
            json.dumps(status), encoding="utf-8"
        )

    console = Console(width=220, record=True)
    console.print(build_dashboard(bot))

    text = console.export_text()

    assert "Reconciliation" in text
    assert expected in text


def test_reconciliation_row_tolerates_broken_reader() -> None:
    class Broken:
        def reconciliation_status(self) -> dict[str, Any]:
            raise RuntimeError("boom")

    assert "not run" in _reconciliation_text(Broken())
    assert "not run" in _reconciliation_text(object())

    class OkBot:
        def reconciliation_status(self) -> dict[str, Any]:
            return {"ok": True, "checked_at": time.time()}

    assert _reconciliation_text(OkBot()).startswith("[green]OK")
