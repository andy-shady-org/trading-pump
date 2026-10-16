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
    assert set(summary["groups"]) == {"entry", "trailing_stop_hit"}


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
