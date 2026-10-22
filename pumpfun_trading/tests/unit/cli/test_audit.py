"""Unit tests for ``cli/audit.py`` ``pnl`` and ``reconcile`` commands (FEAT-49)."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

import pumpfun_trading.cli.audit as cli_audit
from pumpfun_trading.bot.reconcile import ReconciliationReport, TradeCheck
from pumpfun_trading.cli import audit as audit_cli
from pumpfun_trading.cli.main import _build_parser


def _write_audit(path: Path) -> Path:
    trades: list[dict[str, Any]] = [
        {
            "action": "buy",
            "cost_sol": 0.01,
            "costs_sol": 0.0021,
            "net_pnl_sol": -0.0021,
            "gross_pnl_sol": 0.0,
            "cost_source": "modelled",
            "reason": "entry",
            "timestamp": 1_792_141_900.0,
            "mint": "MintA",
            "position_id": "p1",
        },
        {
            "action": "sell",
            "cost_sol": 0.01,
            "proceeds_sol": 0.013,
            "costs_sol": -0.0019,
            "gross_pnl_sol": 0.003,
            "net_pnl_sol": 0.0049,
            "cost_source": "modelled",
            "reason": "trailing_stop_hit (x)",
            "timestamp": 1_792_142_000.0,
            "mint": "MintA",
            "position_id": "p1",
        },
    ]
    lines: list[dict[str, Any]] = [
        {"type": "state_transition", "payload": {"to_state": "buying"}}
    ]
    lines += [
        {"type": "trade", "payload": t, "timestamp": t["timestamp"]} for t in trades
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def _args(*argv: str) -> Any:
    return audit_cli.build_parser().parse_args(list(argv))


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    """The CLI console, recording instead of writing to the terminal."""
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(audit_cli, "console", console)
    return console


def test_pnl_command_prints_json_summary(tmp_path: Path, output: Console) -> None:
    path = _write_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(
        _args("pnl", "--path", str(path), "--json", "--group-by", "reason")
    )

    summary = json.loads(output.export_text())
    assert summary["trades"] == 2
    assert summary["totals"]["net_pnl_sol"] == pytest.approx(0.0028)
    # The buy leg is booked under the position's exit reason (BUG-115).
    assert set(summary["groups"]) == {"trailing_stop_hit"}
    assert summary["groups"]["trailing_stop_hit"]["net_pnl_sol"] == pytest.approx(
        summary["totals"]["net_pnl_sol"]
    )


def test_pnl_command_renders_tables_and_legacy_warning(
    tmp_path: Path, output: Console
) -> None:
    path = tmp_path / "legacy.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "trade",
                "payload": {"action": "sell", "entry": 0.01, "exit": 0.02},
            }
        ),
        encoding="utf-8",
    )

    audit_cli.run_audit_cli(_args("pnl", "--path", str(path), "--group-by", "day"))

    out = output.export_text()
    assert "Net PnL" in out and "no cost data" in out and "By day" in out


@pytest.mark.regression("BUG-105")
def test_pnl_command_labels_win_rate_per_position(
    tmp_path: Path, output: Console
) -> None:
    path = _write_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(_args("pnl", "--path", str(path), "--group-by", "reason"))

    out = output.export_text()
    assert "Win rate per position (net)" in out
    assert "Expectancy per position (SOL)" in out
    assert "Win rate per sell (detail)" in out
    assert "Positions" in out


def _write_momentum_audit(path: Path) -> Path:
    """Four closed momentum positions (two per half) and one launch position."""
    trades: list[dict[str, Any]] = []
    for index, (ts, share, net, lane) in enumerate(
        [
            (100.0, 0.2, 0.004, "momentum"),
            (110.0, 0.6, -0.004, "momentum"),
            (200.0, 0.1, 0.002, "momentum"),
            (210.0, 0.9, -0.006, "momentum"),
            (220.0, 0.1, 0.050, "launch"),
        ]
    ):
        position = f"p{index}"
        trades.append(
            {
                "action": "buy",
                "position_id": position,
                "timestamp": ts,
                "strategy": lane,
                "net_pnl_sol": 0.0,
                "entry_metrics": {"top_buyer_share": share},
                "market_regime": {"hour_utc": 4},
            }
        )
        trades.append(
            {
                "action": "sell",
                "position_id": position,
                "timestamp": ts + 30,
                "net_pnl_sol": net,
                "reason": "stop_loss",
            }
        )
    path.write_text(
        "\n".join(json.dumps({"type": "trade", "payload": t}) for t in trades),
        encoding="utf-8",
    )
    return path


def test_pnl_command_groups_by_entry_hour(tmp_path: Path, output: Console) -> None:
    path = _write_momentum_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(
        _args("pnl", "--path", str(path), "--group-by", "hour", "--json")
    )

    summary = json.loads(output.export_text())
    assert list(summary["groups"]) == ["04"]
    assert summary["groups"]["04"]["positions_closed"] == 5


def test_cuts_command_reports_rules_against_a_random_cut(
    tmp_path: Path, output: Console
) -> None:
    path = _write_momentum_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(
        _args(
            "cuts",
            "--path",
            str(path),
            "--strategy",
            "momentum",
            "--keep",
            "top_buyer_share<0.3",
            "--keep",
            "hour_utc==4",
            "--split-at",
            "mid",
            "--json",
        )
    )

    report = json.loads(output.export_text())
    assert report["positions"] == 4  # the launch position is left out
    share = report["rules"][0]
    assert share["rule"] == "top_buyer_share<0.3"
    assert share["segments"]["A"]["kept"] == 1
    assert share["beats_random_cut"] is True
    assert len(report["rules"]) == 3  # both rules, then both together


def test_cuts_command_renders_a_table(tmp_path: Path, output: Console) -> None:
    path = _write_momentum_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(
        _args("cuts", "--path", str(path), "--keep", "top_buyer_share>=0.5")
    )

    out = output.export_text()
    assert "Entry rules against a random cut" in out
    assert "top_buyer_share>=0.5" in out and "no edge" in out
    assert "Closed positions: all 5" in out


def test_cuts_command_shows_beating_rules(tmp_path: Path, output: Console) -> None:
    path = _write_momentum_audit(tmp_path / "audit.jsonl")

    audit_cli.run_audit_cli(
        _args("cuts", "--path", str(path), "--keep", "top_buyer_share<0.3")
    )

    assert "beats random cut" in output.export_text()


@pytest.mark.parametrize(
    "extra", [(), ("--keep", "nonsense")], ids=["no-rule", "bad-rule"]
)
def test_cuts_command_rejects_missing_or_bad_rules(
    tmp_path: Path, output: Console, extra: tuple[str, ...]
) -> None:
    path = _write_momentum_audit(tmp_path / "audit.jsonl")

    with pytest.raises(SystemExit) as exc:
        audit_cli.run_audit_cli(_args("cuts", "--path", str(path), *extra))

    assert exc.value.code == 2


def test_unified_cli_keeps_its_command_dest() -> None:
    args = _build_parser().parse_args(
        ["audit", "reconcile", "--path", "x", "--wallet", "W"]
    )
    assert args.command == "audit"
    assert args.audit_command == "reconcile"
    assert _build_parser().parse_args(["audit", "--path", "x"]).audit_command is None


def _report(ok: bool) -> ReconciliationReport:
    check = TradeCheck("Sig", "MintA", "sell", 0.01, 0.009, -0.001, None)
    return ReconciliationReport(
        wallet="W",
        ok=ok,
        trades_checked=1,
        trade_mismatches=[check],
        unreadable_trades=[
            TradeCheck("Sig2", "MintB", "buy", -0.01, None, None, "gone")
        ],
        lost_positions={"MintA": 5},
        phantom_positions=["MintB"],
        wallet_balance_sol=0.9,
        start_balance_sol=1.0,
        wallet_gap_sol=-0.1,
        problems=[] if ok else ["cash-flow gap"],
        warnings=["1 trade(s) differ"],
    )


def test_reconcile_requires_wallet(tmp_path: Path) -> None:
    path = _write_audit(tmp_path / "audit.jsonl")
    with pytest.raises(SystemExit) as exc:
        audit_cli.run_audit_cli(_args("reconcile", "--path", str(path)))
    assert exc.value.code == 2


def test_reconcile_exit_code_reflects_gap(tmp_path: Path, output: Console) -> None:
    path = _write_audit(tmp_path / "audit.jsonl")
    args = _args("reconcile", "--path", str(path), "--wallet", "W")

    with patch.object(
        audit_cli, "_run_reconcile", AsyncMock(return_value=_report(True))
    ):
        audit_cli.run_audit_cli(args)
    out = output.export_text()
    assert "OK" in out and "lost position" in out and "phantom position" in out

    with patch.object(
        audit_cli, "_run_reconcile", AsyncMock(return_value=_report(False))
    ):
        with pytest.raises(SystemExit) as exc:
            audit_cli.run_audit_cli(
                _args("reconcile", "--path", str(path), "--wallet", "W", "--json")
            )
    assert exc.value.code == 1
    assert json.loads(output.export_text())["ok"] is False


def test_reconcile_passes_sweep_records_and_prints_them(
    tmp_path: Path, output: Console
) -> None:
    """FEAT-42: audit ``sweep`` records reach the whole-wallet check."""
    path = _write_audit(tmp_path / "audit.jsonl")
    sweep = {"signature": "W" * 64, "cash_flow_sol": -0.300005}
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps({"type": "sweep", "payload": sweep}))
    report = ReconciliationReport(
        wallet="W",
        wallet_balance_sol=0.7,
        start_balance_sol=1.0,
        wallet_gap_sol=0.0,
        swept_sol=0.300005,
    )
    run = AsyncMock(return_value=report)

    with patch.object(audit_cli, "_run_reconcile", run):
        audit_cli.run_audit_cli(
            _args("reconcile", "--path", str(path), "--wallet", "W", "--no-status-file")
        )

    assert run.await_args is not None
    assert run.await_args.args[2] == [sweep]
    assert "profit sweeps: 0.300005 SOL" in output.export_text()


async def test_run_reconcile_uses_rpc_pool_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://rpc.invalid")
    args = _args("reconcile", "--path", "x", "--wallet", "W", "--no-token-check")
    created: list[Any] = []

    class FakePool:
        def __init__(self, endpoints: tuple[str, ...]) -> None:
            self.endpoints = endpoints
            self.closed = False
            created.append(self)

        async def request(self, payload: dict[str, Any], **_: Any) -> dict[str, Any]:
            return {"result": None}

        async def close(self) -> None:
            self.closed = True

    with patch("pumpfun_trading.infra.rpc_pool.RpcConnectionPool", FakePool):
        report = await audit_cli._run_reconcile(
            args, [{"action": "buy", "signature": "S" * 64, "mint": "M"}]
        )

    assert created[0].endpoints == ("https://rpc.invalid",)
    assert created[0].closed
    assert report.unreadable_trades and not report.ok


def test_reconcile_stores_status_for_dashboard(tmp_path: Path, output: Console) -> None:
    path = _write_audit(tmp_path / "audit.jsonl")
    default_target = tmp_path / "reconcile_status.json"

    with patch.object(
        audit_cli, "_run_reconcile", AsyncMock(return_value=_report(True))
    ):
        audit_cli.run_audit_cli(
            _args("reconcile", "--path", str(path), "--wallet", "W")
        )
        assert json.loads(default_target.read_text())["ok"] is True

        custom = tmp_path / "custom.json"
        audit_cli.run_audit_cli(
            _args(
                "reconcile",
                "--path",
                str(path),
                "--wallet",
                "W",
                "--status-file",
                str(custom),
            )
        )
        assert custom.exists()

        default_target.unlink()
        audit_cli.run_audit_cli(
            _args("reconcile", "--path", str(path), "--wallet", "W", "--no-status-file")
        )
        assert not default_target.exists()

        with patch.object(
            audit_cli, "write_reconciliation_status", side_effect=OSError("ro")
        ):
            audit_cli.run_audit_cli(
                _args("reconcile", "--path", str(path), "--wallet", "W")
            )
    assert "Could not store reconciliation status" in output.export_text()


def test_cli_audit_subcommand(tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    record = {
        "timestamp": 1700000000.0,
        "type": "trade",
        "mint": "MintAudit111",
        "action": "buy",
        "status": "success",
    }
    audit_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    # Audit summary
    args = argparse.Namespace(
        path=str(audit_file),
        record_type=None,
        state=None,
        date_from=None,
        date_to=None,
        mint=None,
        token_name=None,
        reason=None,
        status=None,
        limit=None,
        summary=True,
        json=False,
        export=None,
    )
    cli_audit.run_audit_cli(args)

    # Audit export
    export_out = tmp_path / "exported.json"
    args.summary = False
    args.export = str(export_out)
    cli_audit.run_audit_cli(args)
    assert export_out.exists()

    # Audit JSON output
    args.export = None
    args.json = True
    cli_audit.run_audit_cli(args)

    # Audit table output
    args.json = False
    cli_audit.run_audit_cli(args)

    # Audit empty records
    args.mint = "NonExistent"
    cli_audit.run_audit_cli(args)

    # Audit main with parsed args
    with patch(
        "sys.argv",
        ["audit_cli", "--path", str(audit_file), "--summary"],
    ):
        cli_audit.main()


def test_audit_cli_price_filters(tmp_path):
    from unittest.mock import patch

    from pumpfun_trading.cli.audit import build_parser, run_audit_cli

    path = tmp_path / "audit.jsonl"
    records = [
        {
            "timestamp": 1700000000,
            "type": "trade",
            "state": "buying",
            "payload": {
                "mint": "MintA",
                "buy_price": 0.005,
                "action": "buy",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000100,
            "type": "trade",
            "state": "selling",
            "payload": {
                "mint": "MintB",
                "buy_price": 0.005,
                "sell_price": 0.015,
                "action": "sell",
                "status": "success",
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(
        ["--path", str(path), "--min-sell-price", "0.010", "--json"]
    )
    with patch("pumpfun_trading.cli.audit.console.print") as mock_print:
        run_audit_cli(args)
        assert mock_print.called
        printed_arg = mock_print.call_args[0][0]
        data = json.loads(printed_arg)
        assert len(data) == 1
        assert data[0]["payload"]["mint"] == "MintB"


def test_cuts_command_rebuilds_entry_features_from_a_capture(
    tmp_path: Path, output: Console
) -> None:
    """A pre-rc.2 trail has no FEAT-56 metrics; --capture rebuilds them."""
    trades: list[dict[str, Any]] = []
    capture: list[dict[str, Any]] = []
    for index, (ts, whale, net) in enumerate(
        [(100.0, True, -0.004), (110.0, False, 0.004)]
    ):
        mint = f"M{index}"
        trades += [
            {"action": "buy", "position_id": mint, "mint": mint, "timestamp": ts},
            {
                "action": "sell",
                "position_id": mint,
                "mint": mint,
                "timestamp": ts + 30,
                "net_pnl_sol": net,
                "reason": "stop_loss",
            },
        ]
        buys = [("W", 2.0), ("V", 0.1)] if whale else [("W", 0.5), ("V", 0.5)]
        capture += [
            {
                "timestamp": ts - 5 + i,
                "mint": mint,
                "price": 3e-8,
                "is_buy": True,
                "sol_amount": sol,
                "user": user,
            }
            for i, (user, sol) in enumerate(buys)
        ]
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n".join(json.dumps({"type": "trade", "payload": t}) for t in trades),
        encoding="utf-8",
    )
    capture_path = tmp_path / "capture.jsonl"
    capture_path.write_text("\n".join(json.dumps(r) for r in capture), encoding="utf-8")

    audit_cli.run_audit_cli(
        _args(
            "cuts",
            "--path",
            str(audit),
            "--capture",
            str(capture_path),
            "--keep",
            "top_buyer_share<0.8",
            "--json",
        )
    )

    rule = json.loads(output.export_text())["rules"][0]
    assert rule["segments"]["all"]["kept"] == 1
    assert rule["segments"]["all"]["missing"] == 0
    assert rule["beats_random_cut"] is True


# --- verdict (FEAT-67) --------------------------------------------------------


def _write_verdict_audit(path: Path, nets: list[float]) -> Path:
    start = 1_792_022_400.0  # 2026-10-15 00:00 UTC
    lines: list[dict[str, Any]] = []
    for index, net in enumerate(nets):
        ts = start + index * 2 * 86_400 / len(nets)
        for action, value, extra in (
            ("buy", 0.0, {}),
            ("sell", net, {"proceeds_sol": 0.02, "reason": "stop_loss"}),
        ):
            lines.append(
                {
                    "type": "trade",
                    "payload": {
                        "action": action,
                        "position_id": f"p{index}",
                        "timestamp": ts + (60 if action == "sell" else 0),
                        "strategy": "momentum",
                        "net_pnl_sol": value,
                        **extra,
                    },
                }
            )
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def test_verdict_go_prints_json_and_exits_zero(tmp_path: Path, output: Console) -> None:
    path = _write_verdict_audit(tmp_path / "audit.jsonl", [0.002, 0.001] * 30)
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"min_positions": 50, "bootstrap_samples": 500}))

    audit_cli.run_audit_cli(
        _args("verdict", "--path", str(path), "--rules", str(rules), "--json")
    )

    report = json.loads(output.export_text())
    assert report["verdict"] == "GO"
    assert report["positions"] == 60
    assert report["rules"]["min_positions"] == 50


def test_verdict_no_go_renders_and_exits_one(tmp_path: Path, output: Console) -> None:
    path = _write_verdict_audit(tmp_path / "audit.jsonl", [0.002, 0.001] * 30)

    with pytest.raises(SystemExit) as exc:
        # Shipped defaults need 100 positions; the haircut flag overrides.
        audit_cli.run_audit_cli(
            _args(
                "verdict",
                "--path",
                str(path),
                "--exit-haircut-bps",
                "100",
                "--tip-lamports",
                "25000",
                "--bootstrap-samples",
                "200",
            )
        )
    assert exc.value.code == 1
    out = output.export_text()
    assert "Verdict: NO-GO" in out
    assert "min_positions" in out and "FAIL" in out
    assert "Per UTC day" in out and "2026-10-15" in out
    assert "Without the best N positions" in out


def test_verdict_bad_rules_exit_two(tmp_path: Path, output: Console) -> None:
    path = _write_verdict_audit(tmp_path / "audit.jsonl", [0.001] * 3)
    with pytest.raises(SystemExit) as exc:
        audit_cli.run_audit_cli(
            _args("verdict", "--path", str(path), "--confidence", "1.5")
        )
    assert exc.value.code == 2
    assert "confidence" in output.export_text()


def test_verdict_runs_from_the_unified_cli(tmp_path: Path) -> None:
    path = _write_verdict_audit(tmp_path / "audit.jsonl", [0.001] * 3)
    args = _build_parser().parse_args(
        ["audit", "verdict", "--path", str(path), "--min-positions", "3"]
    )
    assert args.audit_command == "verdict"
    rules = audit_cli.verdict_rules_from_args(args)
    assert rules.min_positions == 3
    assert rules.exit_haircut_bps == 0.0
