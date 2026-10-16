"""Unit tests for ``cli/arbitrage.py``."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pumpfun_trading.cli.arbitrage import (
    build_arbitrage_parser,
    render_opportunity_table,
    run_arbitrage_cli,
)
from pumpfun_trading.cli.arbitrage import main as arb_main
from pumpfun_trading.strategies.arbitrage import ArbitrageOpportunity


def test_arbitrage_cli_parser_and_execution() -> None:
    """Test CLI argument parsing and execution for pumpfun-arb."""
    parser = build_arbitrage_parser()
    args = parser.parse_args(
        [
            "--min-spread",
            "0.02",
            "--min-profit",
            "0.005",
            "--max-input",
            "0.40",
            "--raw",
        ]
    )
    assert args.min_spread == 0.02
    assert args.min_profit == 0.005
    assert args.max_input == 0.40
    assert args.raw is True

    exit_code = run_arbitrage_cli(args)
    assert exit_code == 0


def _arb_args(*argv: str) -> argparse.Namespace:
    return build_arbitrage_parser().parse_args(list(argv))


@pytest.mark.regression("BUG-90")
def test_arb_cli_refuses_live_and_labels_demo(tmp_path, capsys):
    """BUG-90: `--live` is refused and exported rows are marked as demo data."""
    assert run_arbitrage_cli(_arb_args("--live")) == 2

    out = tmp_path / "arb.json"
    assert run_arbitrage_cli(_arb_args("--export-history", str(out))) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert rows and all(row["demo"] is True for row in rows)


def test_arbitrage_cli_parser_and_table_render():
    parser = build_arbitrage_parser()
    args = parser.parse_args(["--min-spread", "0.02", "--min-profit", "0.005", "--raw"])
    assert args.min_spread == 0.02
    assert args.min_profit == 0.005
    assert args.raw is True

    opp = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        leg1_min_amount_out=1_000_000,
        leg2_min_amount_out=120_000_000,
    )
    opp2 = ArbitrageOpportunity(
        mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        direction="raydium_to_pump",
        pump_spot_price=0.00005,
        raydium_spot_price=0.00004,
        spread_pct=0.25,
        optimal_input_sol=0.08,
        expected_output_sol=0.095,
        gross_profit_sol=0.015,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.004,
        net_profit_sol=0.010,
        timestamp=time.time(),
        leg1_min_amount_out=2_000_000,
        leg2_min_amount_out=95_000_000,
    )
    # Renders without error
    render_opportunity_table([opp, opp2])


def test_arbitrage_cli_run_and_export(tmp_path: Path):
    export_file = tmp_path / "arb_export.json"
    parser = build_arbitrage_parser()

    # Test rich output with export
    args = parser.parse_args(["--export-history", str(export_file)])
    ret = run_arbitrage_cli(args)
    assert ret == 0
    assert export_file.exists()
    content = json.loads(export_file.read_text(encoding="utf-8"))
    assert len(content) > 0

    # Test raw json output
    args_raw = parser.parse_args(["--raw"])
    assert run_arbitrage_cli(args_raw) == 0


def test_arbitrage_cli_main_wrapper():
    with patch("sys.argv", ["pumpfun-arb", "--raw"]):
        with pytest.raises(SystemExit) as exc_info:
            arb_main()
        assert exc_info.value.code == 0
