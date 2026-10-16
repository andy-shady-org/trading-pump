"""Unit tests for ``cli/arbitrage.py``."""

from __future__ import annotations

from pumpfun_trading.cli.arbitrage import build_arbitrage_parser, run_arbitrage_cli


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
