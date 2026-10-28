"""Unit tests for ``bot/reconcile.py`` wallet reconciliation (FEAT-49)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from trading_pump.bot.reconcile import (
    ReconciliationReport,
    ReconciliationStatusReader,
    describe_reconciliation_status,
    fetch_wallet_balance_sol,
    fetch_wallet_token_balances,
    load_reconciliation_status,
    reconcile_status_path,
    reconcile_wallet,
    write_reconciliation_status,
)

WALLET = "Wallet1111111111111111111111111111111111111"
SIG_BUY = "B" * 64
SIG_SELL = "S" * 64
SIG_OPEN = "O" * 64


class FakeRpc:
    """Answers getTransaction / getTokenAccountsByOwner / getBalance from dicts."""

    def __init__(
        self,
        deltas: dict[str, int],
        *,
        tokens: dict[str, int] | None = None,
        balance_lamports: int | None = None,
        failed: set[str] | None = None,
        token_error: bool = False,
    ) -> None:
        self.deltas = deltas
        self.tokens = tokens or {}
        self.balance_lamports = balance_lamports
        self.failed = failed or set()
        self.token_error = token_error
        self.token_calls = 0

    async def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload["method"]
        if method == "getTransaction":
            signature = payload["params"][0]
            if signature not in self.deltas:
                return {"result": None}
            start = 1_000_000_000
            return {
                "result": {
                    "meta": {
                        "err": {"Custom": 1} if signature in self.failed else None,
                        "preBalances": [start],
                        "postBalances": [start + self.deltas[signature]],
                    },
                    "transaction": {"message": {"accountKeys": [WALLET]}},
                }
            }
        if method == "getTokenAccountsByOwner":
            if self.token_error:
                return {"error": {"message": "boom"}}
            self.token_calls += 1
            if self.token_calls > 1:  # Token-2022 program: no accounts
                return {"result": {"value": []}}
            return {
                "result": {
                    "value": [
                        {
                            "account": {
                                "data": {
                                    "parsed": {
                                        "info": {
                                            "mint": mint,
                                            "tokenAmount": {"amount": str(amount)},
                                        }
                                    }
                                }
                            }
                        }
                        for mint, amount in self.tokens.items()
                    ]
                }
            }
        if method == "getBalance":
            if self.balance_lamports is None:
                return {"error": "nope"}
            return {"result": {"value": self.balance_lamports}}
        raise AssertionError(method)


def _trades() -> list[dict[str, Any]]:
    return [
        {
            "action": "buy",
            "mint": "MintA",
            "position_id": "p1",
            "signature": SIG_BUY,
            "cost_sol": 0.01,
            "cash_flow_sol": -0.0122,
        },
        {
            "action": "sell",
            "mint": "MintA",
            "position_id": "p1",
            "signature": SIG_SELL,
            "cost_sol": 0.01,
            "cash_flow_sol": 0.0135,
        },
        {
            "action": "buy",
            "mint": "MintB",
            "position_id": "p2",
            "signature": SIG_OPEN,
            "cost_sol": 0.01,
            "cash_flow_sol": -0.0121,
        },
        {
            "action": "buy",
            "mint": "MintC",
            "signature": "dry_run_buy_x",
            "dry_run": True,
        },
        {"action": "state", "mint": "ignored"},
    ]


async def test_reconcile_passes_when_chain_matches_audit() -> None:
    rpc = FakeRpc(
        {SIG_BUY: -12_200_000, SIG_SELL: 13_500_000, SIG_OPEN: -12_100_000},
        tokens={"MintB": 350_000, "Foreign": 5},
        balance_lamports=1_000_000_000 - 10_800_000,
    )

    report = await reconcile_wallet(
        _trades(), wallet=WALLET, rpc=rpc, start_balance_sol=1.0
    )

    assert report.ok, report.problems
    assert report.trades_checked == 3 and report.trades_skipped == 1
    assert report.cash_flow_gap_sol == pytest.approx(0.0)
    assert report.open_cost_basis_sol == pytest.approx(0.01)
    assert report.wallet_gap_sol == pytest.approx(0.0, abs=1e-9)
    assert report.lost_positions == {} and report.phantom_positions == []


async def test_reconcile_flags_gaps_lost_and_phantom_positions() -> None:
    rpc = FakeRpc(
        {SIG_BUY: -12_200_000, SIG_SELL: 3_500_000},  # sell got 0.01 SOL less
        tokens={"MintA": 900_000},  # closed in the audit, still on-chain
        balance_lamports=900_000_000,
    )

    report = await reconcile_wallet(
        _trades(), wallet=WALLET, rpc=rpc, start_balance_sol=1.0
    )

    assert not report.ok
    assert [c.signature for c in report.trade_mismatches] == [SIG_SELL]
    assert [c.signature for c in report.unreadable_trades] == [SIG_OPEN]
    assert report.lost_positions == {"MintA": 900_000}
    assert report.phantom_positions == ["MintB"]
    assert report.warnings
    text = " ".join(report.problems)
    for fragment in ("cash-flow gap", "could not be verified", "still hold", "hold no"):
        assert fragment in text
    assert "wallet change differs" in text
    assert report.to_dict()["wallet"] == WALLET


async def test_reconcile_wallet_check_counts_live_profit_sweeps() -> None:
    """FEAT-42: SOL swept to the cold wallet is not an unexplained wallet change."""
    deltas = {SIG_BUY: -12_200_000, SIG_SELL: 13_500_000, SIG_OPEN: -12_100_000}
    swept_lamports = 300_005_000
    sweeps = [
        {"signature": "W" * 64, "cash_flow_sol": -0.300005},
        {"signature": "dry_run_sweep_000001", "cash_flow_sol": -5.0, "dry_run": True},
    ]
    balance = 1_000_000_000 - 10_800_000 - swept_lamports

    without = await reconcile_wallet(
        _trades(),
        wallet=WALLET,
        rpc=FakeRpc(deltas, tokens={"MintB": 1}, balance_lamports=balance),
        start_balance_sol=1.0,
        dust_raw_amount=0,
    )
    report = await reconcile_wallet(
        _trades(),
        wallet=WALLET,
        rpc=FakeRpc(deltas, tokens={"MintB": 1}, balance_lamports=balance),
        start_balance_sol=1.0,
        dust_raw_amount=0,
        sweeps=sweeps,
    )

    assert not without.ok
    assert without.wallet_gap_sol == pytest.approx(-0.300005)
    assert report.ok, report.problems
    assert report.swept_sol == pytest.approx(0.300005)
    assert report.wallet_gap_sol == pytest.approx(0.0, abs=1e-9)


async def test_reconcile_reports_rpc_failures_without_raising() -> None:
    rpc = FakeRpc({SIG_BUY: -1, SIG_SELL: 1, SIG_OPEN: -1}, token_error=True)
    rpc.failed = {SIG_SELL}

    report = await reconcile_wallet(
        _trades(), wallet=WALLET, rpc=rpc, start_balance_sol=1.0
    )

    assert not report.ok
    assert "failed on-chain" in (report.unreadable_trades[0].error or "")
    assert any("token balances unavailable" in p for p in report.problems)
    assert any("wallet balance unavailable" in p for p in report.problems)


async def test_reconcile_skips_token_check_and_handles_foreign_wallet() -> None:
    rpc = FakeRpc({SIG_BUY: -12_200_000, SIG_SELL: 13_500_000, SIG_OPEN: -12_100_000})

    report = await reconcile_wallet(
        _trades(), wallet="OtherWallet", rpc=rpc, check_tokens=False
    )

    assert len(report.unreadable_trades) == 3
    assert "not part of the transaction" in (report.unreadable_trades[0].error or "")
    assert rpc.token_calls == 0


async def test_fetch_helpers_raise_on_rpc_errors() -> None:
    with pytest.raises(RuntimeError):
        await fetch_wallet_token_balances(FakeRpc({}, token_error=True), WALLET)
    with pytest.raises(RuntimeError):
        await fetch_wallet_balance_sol(FakeRpc({}), WALLET)
    assert await fetch_wallet_balance_sol(
        FakeRpc({}, balance_lamports=2_000_000_000), WALLET
    ) == pytest.approx(2.0)


# --- Stored reconciliation status (dashboard / status snapshot) -----------------


def test_reconcile_status_path_defaults_next_to_audit_trail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PUMPFUN_RECONCILE_STATUS_PATH", raising=False)
    audit = tmp_path / "data" / "audit_trail.jsonl"
    assert reconcile_status_path(audit) == tmp_path / "data" / "reconcile_status.json"
    assert reconcile_status_path(None) is None

    monkeypatch.setenv("PUMPFUN_RECONCILE_STATUS_PATH", str(tmp_path / "r.json"))
    assert reconcile_status_path(audit) == tmp_path / "r.json"


def test_write_and_load_reconciliation_status_round_trip(tmp_path: Path) -> None:
    report = ReconciliationReport(wallet=WALLET, ok=False, trades_checked=4)
    report.lost_positions = {"MintA": 10}
    report.problems = ["1 closed position(s) still hold tokens"]
    target = tmp_path / "nested" / "reconcile_status.json"

    written = write_reconciliation_status(report, target, checked_at=1_000.0)

    assert load_reconciliation_status(target) == written
    assert written["ok"] is False and written["lost_positions"] == 1
    assert not target.with_name("reconcile_status.json.tmp").exists()


@pytest.mark.parametrize("content", [None, "not json", '{"no_ok": 1}', "[1]"])
def test_load_reconciliation_status_ignores_missing_or_bad_files(
    tmp_path: Path, content: str | None
) -> None:
    target = tmp_path / "reconcile_status.json"
    if content is not None:
        target.write_text(content, encoding="utf-8")
    assert load_reconciliation_status(target) is None
    assert load_reconciliation_status(None) is None


def test_status_reader_reparses_only_when_file_changes(tmp_path: Path) -> None:
    target = tmp_path / "reconcile_status.json"
    reader = ReconciliationStatusReader(target)
    assert reader.read() is None
    assert ReconciliationStatusReader(None).read() is None

    write_reconciliation_status(ReconciliationReport(wallet=WALLET), target)
    first = reader.read()
    assert first is not None and first["ok"] is True
    assert reader.read() is first

    os.utime(target, (1.0, 1.0))
    target.write_text('{"ok": false, "problems": ["x"]}', encoding="utf-8")
    os.utime(target, (2.0, 2.0))
    assert reader.read() == {"ok": False, "problems": ["x"]}

    target.unlink()
    assert reader.read() is None


@pytest.mark.parametrize(
    "status, expected",
    [
        (None, "not run"),
        (
            {"ok": True, "trades_checked": 12, "checked_at": 10_000 - 120},
            "OK (12 trades, 2m ago)",
        ),
        (
            {"ok": True, "trades_checked": 3, "checked_at": 10_000 - 7_200},
            "OK (3 trades, 2h ago)",
        ),
        (
            {"ok": True, "trades_checked": 3, "checked_at": 10_000 - 3 * 86_400},
            "STALE (3 trades, 3d ago)",
        ),
        ({"ok": True}, "STALE (0 trades, time unknown)"),
        (
            {"ok": False, "problems": ["a", "b"], "checked_at": 9_400},
            "GAP (2 problem(s), 10m ago)",
        ),
    ],
)
def test_describe_reconciliation_status(
    status: dict[str, Any] | None, expected: str
) -> None:
    assert describe_reconciliation_status(status, now=10_000.0) == expected
