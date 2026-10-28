"""In-memory fakes for the I/O boundaries: clock, RPC pool, Jito, alerts.

Each fake records what it was asked and answers from what the test
registered, so a test asserts on behaviour instead of on mock internals.
They duck-type the real objects (``RpcConnectionPool``, ``JitoClient``,
``AlertDispatcher``); assign them where the code under test looks them up,
e.g. ``client.rpc_pool = FakeRpc()``.
"""

from __future__ import annotations

import asyncio
import math
import types
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from pumpfun_trading.sdk.curve import (
    INITIAL_REAL_TOKEN_RAW,
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RAW,
    TOTAL_TOKEN_SUPPLY_RAW,
)
from pumpfun_trading.sdk.jito import JITO_TIP_ACCOUNTS, JitoBundleStatus, JitoTipFloor

_REAL_ASYNC_SLEEP = asyncio.sleep


class FakeClock:
    """A manual clock: time only moves when the test (or a fake sleep) says so.

    It exposes ``time()``, ``monotonic()``, ``perf_counter()`` and ``sleep()``
    like the ``time`` module, so :meth:`install` can stand it in for a
    module's ``time`` import. ``async_sleep`` advances the clock and yields
    once to the event loop instead of waiting.
    """

    def __init__(self, start: float = 1_728_600_000.0) -> None:
        self.now = float(start)
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a clock cannot go backwards")
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(max(0.0, seconds))

    async def async_sleep(self, seconds: float, result: Any = None) -> Any:
        self.sleep(seconds)
        await _REAL_ASYNC_SLEEP(0)
        return result

    def install(
        self, monkeypatch: pytest.MonkeyPatch, *modules: types.ModuleType
    ) -> None:
        """Replace ``module.time`` with this clock in each module under test.

        Only the named modules see the fake; ``time`` itself and the event
        loop are untouched.
        """
        for module in modules:
            monkeypatch.setattr(module, "time", self)

    def install_async_sleep(
        self, monkeypatch: pytest.MonkeyPatch, *modules: types.ModuleType
    ) -> None:
        """Make ``module.asyncio.sleep`` advance this clock without waiting.

        Each module gets its own ``asyncio`` stand-in, so the global
        ``asyncio.sleep`` that the event loop and other tests use is kept.
        """
        for module in modules:
            stand_in = types.SimpleNamespace(**vars(asyncio))
            stand_in.sleep = self.async_sleep
            monkeypatch.setattr(module, "asyncio", stand_in)


class FakeRpc:
    """Stand-in for ``RpcConnectionPool`` keyed by JSON-RPC method.

    Register an answer with :meth:`on`: a value (returned as ``result``), an
    exception (raised), or a callable taking the payload. Unregistered
    methods raise, so a test never silently gets an empty answer.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.broadcasts: list[str] = []
        self.broadcast_signature = "FakeSignature1111111111111111111111111111111"
        self.endpoints: list[Any] = []
        self.closed = False
        self._answers: dict[str, list[Any]] = {}

    def on(self, method: str, *answers: Any) -> FakeRpc:
        """Queue answers for ``method``; the last one repeats once the rest are used."""
        if not answers:
            raise ValueError("give at least one answer")
        self._answers[method] = list(answers)
        return self

    def methods_called(self) -> list[str]:
        return [str(call.get("method")) for call in self.calls]

    async def request(
        self,
        payload: dict[str, Any],
        *,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(payload)
        method = str(payload.get("method"))
        queue = self._answers.get(method)
        if not queue:
            raise AssertionError(f"FakeRpc: no answer registered for {method!r}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(answer):
            answer = answer(payload)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, dict) and ("result" in answer or "error" in answer):
            return answer
        return {"jsonrpc": "2.0", "id": payload.get("id", 1), "result": answer}

    async def broadcast_transaction(self, base64_tx: str, **_: Any) -> str:
        self.broadcasts.append(base64_tx)
        return self.broadcast_signature

    @property
    def endpoint_count(self) -> int:
        return max(1, len(self.endpoints))

    def get_telemetry(self) -> dict[str, Any]:
        return {"endpoints": [], "healthy_endpoints": self.endpoint_count}

    async def start_health_loop(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def standard_curve(
    market_cap_sol: float | None = None, *, complete: bool = False
) -> dict[str, Any]:
    """A decoded standard Pump.fun curve at ``market_cap_sol`` (a fresh launch
    when ``None``), shaped like ``get_bonding_curve_state``'s answer.

    The reserves keep the standard invariant (30 SOL x 1.073 B tokens), so the
    curve passes the BUG-104 checks and a buy quote on it is realistic.
    """
    k = INITIAL_VIRTUAL_SOL_LAMPORTS * INITIAL_VIRTUAL_TOKEN_RAW
    if market_cap_sol is None or market_cap_sol <= 0:
        v_sol, v_token = INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW
    else:
        # A whole number of tokens (1e6 raw units each) keeps the market cap
        # exact: v_sol = market cap x whole tokens.
        whole_tokens = round(math.sqrt(k * 1_000_000.0 / market_cap_sol) / 1_000_000.0)
        v_token = whole_tokens * 1_000_000
        v_sol = round(market_cap_sol * whole_tokens)
    sold = INITIAL_VIRTUAL_TOKEN_RAW - v_token
    return {
        "virtual_token_reserves": v_token,
        "virtual_sol_reserves": v_sol,
        "real_token_reserves": max(0, INITIAL_REAL_TOKEN_RAW - sold),
        "real_sol_reserves": max(0, v_sol - INITIAL_VIRTUAL_SOL_LAMPORTS),
        "token_total_supply": TOTAL_TOKEN_SUPPLY_RAW,
        "complete": complete,
        "market_cap_sol": (v_sol / 1e9) * (TOTAL_TOKEN_SUPPLY_RAW / v_token),
        "is_mayhem_mode": False,
    }


class FakeCurves:
    """Curve reads for a bot or executor that has no RPC (BUG-145).

    Paper buys need a curve read, as live buys do, so a test that buys sets
    the market cap each mint's curve answers with (:meth:`at`); other mints
    answer with ``default_market_cap`` (a fresh launch when ``None``).
    :meth:`install` puts both curve reads on an execution client.
    """

    def __init__(self, default_market_cap: float | None = None) -> None:
        self.default_market_cap = default_market_cap
        self.market_caps: dict[str, float] = {}
        self.complete: set[str] = set()
        self.reads: list[str] = []

    def at(
        self, mint: str, market_cap_sol: float, *, complete: bool = False
    ) -> FakeCurves:
        self.market_caps[mint] = market_cap_sol
        if complete:
            self.complete.add(mint)
        else:
            self.complete.discard(mint)
        return self

    def curve(self, mint: str) -> dict[str, Any]:
        return standard_curve(
            self.market_caps.get(mint, self.default_market_cap),
            complete=mint in self.complete,
        )

    async def get_bonding_curve_state(self, mint: str) -> dict[str, Any]:
        self.reads.append(mint)
        return self.curve(mint)

    async def get_bonding_curve_states(
        self,
        mints: Sequence[str],
        *,
        rejected: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, dict[str, Any]]:
        self.reads.extend(mints)
        return {mint: self.curve(mint) for mint in mints}

    def install(self, target: Any) -> FakeCurves:
        """Answer the curve reads of ``target`` (a bot or an execution client)."""
        execution = getattr(target, "execution", target)
        execution.get_bonding_curve_state = self.get_bonding_curve_state
        execution.get_bonding_curve_states = self.get_bonding_curve_states
        return self


@dataclass
class FakeJito:
    """Stand-in for ``JitoClient``: records bundles, answers with ``status``."""

    status: str = "Landed"
    tip_lamports: int = 100_000
    bundle_id: str = "fake-bundle"
    err: Any = None
    tip_accounts: list[str] = field(default_factory=lambda: list(JITO_TIP_ACCOUNTS))
    bundles: list[list[Any]] = field(default_factory=list)
    closed: bool = False

    def get_tip_account(self, random_pick: bool = False) -> str:
        return self.tip_accounts[0]

    async def fetch_tip_floor(self, max_age_seconds: float = 10.0) -> JitoTipFloor:
        return JitoTipFloor(fetched_at=0.0)

    def calculate_tip_lamports(self, *_: Any, **__: Any) -> int:
        return self.tip_lamports

    async def send_bundle(self, transactions: Sequence[Any], **_: Any) -> str:
        self.bundles.append(list(transactions))
        return self.bundle_id

    async def wait_for_bundle_confirmation(
        self, bundle_id: str, **_: Any
    ) -> JitoBundleStatus:
        return JitoBundleStatus(bundle_id=bundle_id, status=self.status, err=self.err)

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeAlertSink:
    """Stand-in for ``AlertDispatcher`` that keeps every message it was sent."""

    enabled: bool = True
    provider: str = "fake"
    deliver: bool = True
    messages: list[str] = field(default_factory=list)

    def send_alert(self, message: str) -> bool:
        if not self.enabled:
            return False
        self.messages.append(message)
        return self.deliver

    async def send_alert_async(self, message: str) -> bool:
        return self.send_alert(message)
