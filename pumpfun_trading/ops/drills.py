"""Scripted, repeatable risk drills on a real paper bot (FEAT-69).

RUNBOOK §7 asked for incident drills "forced if needed". These are the forced
ones: each drill builds a real :class:`~pumpfun_trading.bot.run.TradingBot` in
a scratch folder, drives its own risk code (breaker checks, pause, restart,
sells) on a simulated clock and wallet, and checks what the operator would
check. Nothing touches the network: the stream is never opened, the balance
RPC and the sell executor are replaced by fakes, and alerts are captured
instead of sent. A drill can therefore run anywhere, in seconds, and must pass
on every release that touches the risk path.

Drills:

``cumulative_cap``
    Two losing days trip ``max_cumulative_drawdown_pct``; buying pauses, the
    pause and the cap survive a restart and the lock expiry, and ``SIGUSR1``
    (the operator resume) resets the cap to the current equity.
``midnight_lock``
    An emergency lock taken at 23:55 UTC still holds at 00:05 and ends after
    ``emergency_hard_lock_hours``.
``balance_rpc_down``
    A live start whose balance RPC fails: no day baseline from the simulated
    balance, buys blocked, then the baseline comes from the first real read.
    The bot is in live mode but no transaction is built or sent.
``slow_tier_sell``
    A take-profit tier whose sell runs past the 60 s pending latch is not sold
    a second time.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine, Iterator, Sequence

import base58
from solders.keypair import Keypair

DRILL_NAMES = ("cumulative_cap", "midnight_lock", "balance_rpc_down", "slow_tier_sell")
_UTC = _dt.timezone.utc
# Never contacted: every network path a drill reaches is replaced by a fake.
_UNUSED_RPC_URL = "http://127.0.0.1:9"
_DRILL_MINT = "DriLLSLowTier1111111111111111111111111111pump"


@dataclass
class DrillCheck:
    description: str
    passed: bool
    detail: str = ""


@dataclass
class DrillResult:
    name: str
    title: str
    checks: list[DrillCheck] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and bool(self.checks)
            and all(c.passed for c in self.checks)
        )

    def check(self, description: str, passed: bool, detail: Any = "") -> bool:
        self.checks.append(DrillCheck(description, bool(passed), str(detail)))
        return bool(passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "passed": self.passed,
            "error": self.error,
            "checks": [
                {"check": c.description, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


@dataclass
class DrillReport:
    results: list[DrillResult]
    workdir: str
    started_at_utc: str

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "started_at_utc": self.started_at_utc,
            "workdir": self.workdir,
            "drills": [r.to_dict() for r in self.results],
        }


class DrillClock:
    """A settable UTC clock for the bot's risk checks."""

    def __init__(self, start: _dt.datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def set(self, when: _dt.datetime) -> None:
        self.now = when.timestamp()

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@contextmanager
def isolated_environment(workdir: Path) -> Iterator[None]:
    """No operator settings (keys, endpoints, alert hooks) reach a drill bot."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("PUMPFUN_")}
    for key in saved:
        del os.environ[key]
    os.environ["PUMPFUN_BOT_LOG_PATH"] = str(workdir / "bot.log")
    os.environ["PUMPFUN_EVENT_LOG_PATH"] = str(workdir / "events.jsonl")
    os.environ["PUMPFUN_ALERT_PROVIDER"] = "none"
    try:
        yield
    finally:
        for key in [k for k in os.environ if k.startswith("PUMPFUN_")]:
            del os.environ[key]
        os.environ.update(saved)


def _throwaway_key() -> str:
    """A fresh in-memory keypair: drills never sign with a real wallet."""
    return base58.b58encode(bytes(Keypair())).decode()


def _drill_config(**overrides: Any) -> Any:
    from pumpfun_trading.strategies.presets import resolve_strategy_config

    base = resolve_strategy_config("conservative")
    values = {
        "dry_run": True,
        "paper_trade": True,
        "verbose": False,
        "headless": True,
        "enable_rpc_pool": False,
        "replay_log_path": None,
        **overrides,
    }
    return replace(base, **values)


def _make_bot(folder: Path, clock: DrillClock, *, live: bool = False, **config: Any):
    from pumpfun_trading.bot.run import TradingBot

    folder.mkdir(parents=True, exist_ok=True)
    bot = TradingBot(
        private_key_b58=_throwaway_key(),
        rpc_url=_UNUSED_RPC_URL,
        config=_drill_config(dry_run=not live, paper_trade=not live, **config),
        dry_run=not live,
        paper_trade=not live,
        verbose=False,
        headless=True,
        log_file=str(folder / "bot.log"),
        audit_log_path=str(folder / "audit_trail.jsonl"),
        bot_status_path=str(folder / "bot_status.json"),
    )
    bot.clock = clock
    alerts: list[str] = []
    bot.alert_enabled = True
    bot._send_alert = alerts.append  # type: ignore[method-assign, assignment]
    bot.drill_alerts = alerts  # type: ignore[attr-defined]
    return bot


def _audit_types(folder: Path) -> list[str]:
    path = folder / "audit_trail.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(str(json.loads(line).get("type")))
        except json.JSONDecodeError:
            continue
    return out


async def drill_cumulative_cap(folder: Path) -> DrillResult:
    """Cumulative cap trips; the pause survives a restart; SIGUSR1 resets it."""
    result = DrillResult(
        "cumulative_cap",
        "Cumulative cap trips, the pause survives a restart, SIGUSR1 resets it",
    )
    clock = DrillClock(_dt.datetime(2026, 1, 5, 12, 0, tzinfo=_UTC))
    settings: dict[str, Any] = {
        "max_daily_drawdown_pct": 0.15,
        "max_cumulative_drawdown_pct": 0.25,
        "emergency_hard_lock_hours": 24.0,
        "auto_liquidate_on_circuit_breaker": False,
    }
    bot = _make_bot(folder, clock, **settings)
    tracker = bot.daily_equity_tracker
    bot.wallet_balance_sol = 1.0
    await bot._check_and_enforce_circuit_breaker()
    result.check(
        "day 1: reference equity set from the wallet",
        abs(tracker.reference_equity_sol - 1.0) < 1e-9,
        f"{tracker.reference_equity_sol:.4f} SOL",
    )
    result.check(
        "day 1: buying allowed before any loss",
        bot._should_buy(_DRILL_MINT, 40.0) is True,
    )
    bot.wallet_balance_sol = 0.86
    locked = await bot._check_and_enforce_circuit_breaker()
    result.check("day 1: a 14% loss stays inside the 15% daily limit", not locked)

    clock.advance(24 * 3600)
    await bot._check_and_enforce_circuit_breaker()
    bot.wallet_balance_sol = 0.74
    locked = await bot._check_and_enforce_circuit_breaker()
    result.check(
        "day 2: 26% below the reference trips the 25% cumulative cap",
        locked and tracker.cumulative_cap_hit,
        tracker.lock_reason,
    )
    result.check(
        "buying paused with reason 'cumulative loss cap'",
        bot.buying_paused and bot._operator_pause.reason == "cumulative loss cap",
        bot._operator_pause.reason,
    )
    result.check("no new buys allowed", bot._should_buy(_DRILL_MINT, 40.0) is False)
    result.check(
        "the trip was alerted",
        any("buying paused" in a for a in bot.drill_alerts),  # type: ignore[attr-defined]
    )
    bot._write_status_snapshot()
    await bot.close()

    restarted = _make_bot(folder, clock, **settings)
    restarted.safe_startup()
    result.check(
        "after a restart: still paused and the cap still hit",
        restarted.buying_paused and restarted.daily_equity_tracker.cumulative_cap_hit,
    )
    restarted.wallet_balance_sol = 0.74
    clock.advance(25 * 3600)
    locked = await restarted._check_and_enforce_circuit_breaker()
    result.check(
        "after the 24 h lock expires: still locked and paused (only the operator resets)",
        locked and restarted.buying_paused,
    )
    paused = restarted.toggle_buying_pause(source="SIGUSR1")
    after = restarted.daily_equity_tracker
    result.check(
        "SIGUSR1 resumes buying and resets the cap to the current equity",
        not paused
        and not after.cumulative_cap_hit
        and abs(after.reference_equity_sol - 0.74) < 1e-9,
        f"reference {after.reference_equity_sol:.4f} SOL",
    )
    locked = await restarted._check_and_enforce_circuit_breaker()
    result.check("the next breaker check is clear", not locked)
    types = _audit_types(folder)
    result.check(
        "pause and resume are in the audit trail",
        types.count("operator_pause") >= 2,
        f"{types.count('operator_pause')} operator_pause records",
    )
    await restarted.close()
    return result


async def drill_midnight_lock(folder: Path) -> DrillResult:
    """An emergency lock at 23:55 UTC still holds at 00:05 and ends after 24 h."""
    result = DrillResult(
        "midnight_lock", "An emergency lock at 23:55 UTC holds across midnight"
    )
    clock = DrillClock(_dt.datetime(2026, 1, 5, 23, 50, tzinfo=_UTC))
    bot = _make_bot(
        folder,
        clock,
        max_daily_drawdown_pct=0.15,
        max_cumulative_drawdown_pct=0.0,
        emergency_hard_lock_hours=24.0,
        auto_liquidate_on_circuit_breaker=False,
    )
    tracker = bot.daily_equity_tracker
    bot.wallet_balance_sol = 1.0
    await bot._check_and_enforce_circuit_breaker()
    result.check(
        "23:50: buying allowed before the loss",
        bot._should_buy(_DRILL_MINT, 40.0) is True,
    )
    clock.set(_dt.datetime(2026, 1, 5, 23, 55, tzinfo=_UTC))
    bot.wallet_balance_sol = 0.80
    locked = await bot._check_and_enforce_circuit_breaker()
    locked_at = tracker.locked_at_timestamp
    result.check(
        "23:55: a 20% loss takes an emergency lock",
        locked and tracker.circuit_breaker_action.value == "emergency_liquidate",
        tracker.lock_reason,
    )
    until = tracker.lockout_until(24.0)
    result.check(
        "lockout_until is 24 h after the lock, not midnight",
        locked_at is not None and until is not None and until == locked_at + 86_400,
        _dt.datetime.fromtimestamp(until, tz=_UTC).isoformat() if until else None,
    )
    clock.set(_dt.datetime(2026, 1, 6, 0, 5, tzinfo=_UTC))
    locked = await bot._check_and_enforce_circuit_breaker()
    result.check(
        "00:05 next day: the rollover ran and the lock still holds",
        locked
        and tracker.circuit_breaker_engaged
        and tracker.last_reset_date_utc == "2026-01-06",
        f"day {tracker.last_reset_date_utc}",
    )
    result.check("no new buys at 00:05", bot._should_buy(_DRILL_MINT, 40.0) is False)
    status = bot.get_status_snapshot()
    result.check(
        "the status file reports the real unlock time",
        status.get("circuit_breaker_lockout_until") == until,
    )
    assert locked_at is not None
    clock.now = locked_at + 86_400 + 60
    bot._risk_killed = False
    locked = await bot._check_and_enforce_circuit_breaker()
    result.check(
        "24 h after the lock: released, baseline re-set to the equity then",
        not locked and abs(tracker.starting_equity_sol - 0.80) < 1e-9,
        f"baseline {tracker.starting_equity_sol:.4f} SOL",
    )
    await bot.close()
    return result


async def drill_balance_rpc_down(folder: Path) -> DrillResult:
    """Live start, balance RPC down: no baseline, buys blocked, then the real one."""
    result = DrillResult(
        "balance_rpc_down",
        "Live start with the balance RPC down: no baseline, buys blocked",
    )
    clock = DrillClock(_dt.datetime(2026, 1, 5, 9, 0, tzinfo=_UTC))
    bot = _make_bot(
        folder,
        clock,
        live=True,
        buy_amount_sol=0.02,
        reserve_balance_sol=0.15,
        max_daily_drawdown_pct=0.10,
    )
    simulated = float(bot.wallet_balance_sol)
    calls = {"balance": 0}

    async def balance_down() -> float:
        calls["balance"] += 1
        raise ConnectionError("balance RPC unreachable (drill)")

    bot.execution.get_balance_sol = balance_down  # type: ignore[method-assign]

    def no_transactions(*_: Any, **__: Any) -> Any:
        raise AssertionError("a drill must never build or send a transaction")

    bot.executor.execute_buy = no_transactions  # type: ignore[method-assign]
    bot.executor.execute_sell = no_transactions  # type: ignore[method-assign]
    tracker = bot.daily_equity_tracker

    await bot._check_and_enforce_circuit_breaker()
    result.check(
        "no day baseline from the simulated balance",
        tracker.last_reset_date_utc == "" and tracker.starting_equity_sol == 0.0,
        f"simulated start balance {simulated:.4f} SOL not used",
    )
    from pumpfun_trading.bot.risk import evaluate_portfolio_circuit_breaker

    locked, reason = evaluate_portfolio_circuit_breaker(bot)
    result.check(
        "the breaker reports locked until the first live balance read",
        locked and "first live wallet balance" in reason,
        reason,
    )
    allowed = await bot._check_account_equity_guard(0.02)
    result.check("the pre-buy equity guard refuses the buy", allowed is False)
    status = bot.get_status_snapshot()
    result.check(
        "the status file shows no drawdown and no baseline",
        status.get("daily_drawdown_pct") == 0.0
        and status.get("daily_starting_equity_sol") == 0.0,
    )

    async def balance_up() -> float:
        calls["balance"] += 1
        return 0.20

    bot.execution.get_balance_sol = balance_up  # type: ignore[method-assign]
    await bot._check_and_enforce_circuit_breaker()
    result.check(
        "after the RPC recovers the baseline is the real balance",
        abs(tracker.starting_equity_sol - 0.20) < 1e-9
        and abs(tracker.reference_equity_sol - 0.20) < 1e-9,
        f"{tracker.starting_equity_sol:.4f} SOL (simulated was {simulated:.4f})",
    )
    result.check("balance RPC was called", calls["balance"] >= 3, calls["balance"])
    await bot.close()
    return result


async def drill_slow_tier_sell(folder: Path) -> DrillResult:
    """A tier sell slower than the 60 s pending latch is not sold twice."""
    from pumpfun_trading.execution.executor import ExecutionResult

    result = DrillResult(
        "slow_tier_sell",
        "A tier sell slower than the 60 s pending latch is not repeated",
    )
    clock = DrillClock(_dt.datetime(2026, 1, 5, 9, 0, tzinfo=_UTC))
    bot = _make_bot(folder, clock)
    bot.position_manager.record_buy(
        mint=_DRILL_MINT,
        token_amount=1_000_000,
        cost_sol=0.02,
        entry_market_cap=30.0,
    )
    bot.position_manager.update_price(_DRILL_MINT, 45.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    release = asyncio.Event()
    calls = 0

    async def slow_sell(*_: Any, **kwargs: Any) -> ExecutionResult:
        nonlocal calls
        calls += 1
        await release.wait()  # a Jito timeout, then the RPC fallback
        amount = int(kwargs.get("sell_amount_tokens") or 500_000)
        return ExecutionResult(
            success=True,
            signature=f"drill_sell_{calls}",
            mint=_DRILL_MINT,
            is_buy=False,
            amount_sol=0.015,
            token_amount=amount,
            dry_run=True,
        )

    bot.executor.execute_sell = slow_sell  # type: ignore[method-assign]

    def tier_1() -> Coroutine[Any, Any, bool]:
        return bot._sell_token(
            _DRILL_MINT,
            sell_amount_tokens=500_000,
            sell_fraction=0.5,
            reason="take_profit_tier_1",
            target_tier=1,
        )

    first = asyncio.create_task(tier_1())
    await asyncio.sleep(0)
    # The pending latch (60 s) has run out, so the exit stack emits tier 1 again.
    second = asyncio.create_task(tier_1())
    await asyncio.sleep(0)
    release.set()
    outcomes = await asyncio.gather(first, second)
    position = bot.active_positions.get(_DRILL_MINT, {})
    result.check(
        "the first tier-1 sell completes, the queued repeat is refused",
        list(outcomes) == [True, False],
        outcomes,
    )
    result.check("one sell sent to the executor", calls == 1, f"{calls} calls")
    result.check(
        "tier 1 marked executed and half the tokens left",
        position.get("tier_1_executed") is True
        and int(position.get("remaining_token_amount") or 0) == 500_000,
        position.get("remaining_token_amount"),
    )
    await bot.close()
    return result


DRILLS: dict[str, Callable[[Path], Awaitable[DrillResult]]] = {
    "cumulative_cap": drill_cumulative_cap,
    "midnight_lock": drill_midnight_lock,
    "balance_rpc_down": drill_balance_rpc_down,
    "slow_tier_sell": drill_slow_tier_sell,
}


async def run_drills(
    names: Sequence[str] | None = None, *, workdir: str | Path | None = None
) -> DrillReport:
    """Run the named drills (all by default) in ``workdir`` (a temp dir)."""
    selected = list(names or DRILL_NAMES)
    unknown = [n for n in selected if n not in DRILLS]
    if unknown:
        raise ValueError(
            f"Unknown drill(s): {', '.join(unknown)} (known: {', '.join(DRILL_NAMES)})"
        )
    started = _dt.datetime.now(_UTC).isoformat().replace("+00:00", "Z")
    root = (
        Path(workdir)
        if workdir is not None
        else Path(tempfile.mkdtemp(prefix="pumpfun-drill-"))
    )
    root.mkdir(parents=True, exist_ok=True)
    results: list[DrillResult] = []
    # The bots log their trips and pauses at WARNING; the report says it all.
    previous_disable = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        with isolated_environment(root):
            for name in selected:
                try:
                    results.append(await DRILLS[name](root / name))
                except Exception as exc:  # a broken drill is a failed drill
                    results.append(
                        DrillResult(name, name, error=f"{type(exc).__name__}: {exc}")
                    )
    finally:
        logging.disable(previous_disable)
    return DrillReport(results=results, workdir=str(root), started_at_utc=started)


__all__ = [
    "DRILLS",
    "DRILL_NAMES",
    "DrillCheck",
    "DrillClock",
    "DrillReport",
    "DrillResult",
    "isolated_environment",
    "run_drills",
]
