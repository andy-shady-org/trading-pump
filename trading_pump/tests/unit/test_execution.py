"""Unit tests for ``execution.py``: PumpSwap paper fills and the live gate."""

from __future__ import annotations

from typing import Any

import pytest
from trading_core.module.base import ExecutionRefused, OrderRequest, Side

from trading_pump.config.settings import ExecutionSettings
from trading_pump.execution import (
    CLOSES_POSITION,
    LIVE_REFUSAL,
    Holdings,
    LiveExecutor,
    PaperExecutor,
)
from trading_pump.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import (
    GRADUATION_BASE_RESERVE,
    GRADUATION_QUOTE_RESERVE,
)
from trading_pump.tests.support.fakes import FakeClock, FakePoolSource

MINT = SAMPLE_MINT


def _paper(**settings: object) -> tuple[PaperExecutor, FakePoolSource, FakeClock]:
    source = FakePoolSource(fee_bps=100)
    source.set(MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)
    clock = FakeClock(start=1_000.0)
    executor = PaperExecutor(
        source,
        ExecutionSettings(**settings),  # type: ignore[arg-type]
        clock=clock.time,
        sleep=clock.async_sleep,
    )
    return executor, source, clock


def _buy(notional: float = 0.1, **kwargs: Any) -> OrderRequest:
    return OrderRequest(MINT, Side.BUY, notional=notional, **kwargs)


def _sell(size: float, **kwargs: object) -> OrderRequest:
    return OrderRequest(MINT, Side.SELL, size=size, **kwargs)  # type: ignore[arg-type]


async def test_a_buy_swaps_through_the_pool_and_books_every_cost() -> None:
    executor, source, _ = _paper(priority_fee_lamports=10_000)

    fill = await executor.execute(_buy(0.1))

    swapped = 100_000_000 * 10_000 // 10_100
    tokens = GRADUATION_BASE_RESERVE * swapped // (GRADUATION_QUOTE_RESERVE + swapped)
    assert fill.side is Side.BUY and fill.simulated
    assert fill.size == tokens / 1e6
    assert fill.notional == swapped / 1e9
    assert fill.price == pytest.approx(fill.notional / fill.size)
    costs = fill.costs.components
    assert costs["swap_fee"] == pytest.approx((100_000_000 - swapped) / 1e9)
    assert costs["fee"] == 5_000 / 1e9 and costs["priority_fee"] == 10_000 / 1e9
    assert costs["tip"] == 0.0
    assert costs["rent"] == TOKEN_ACCOUNT_RENT_LAMPORTS / 1e9
    assert fill.notional + costs["swap_fee"] == pytest.approx(0.1)
    assert fill.metadata["fee_bps"] == 100 and fill.metadata["fee_source"] == "fake"
    assert fill.metadata["tokens_raw"] == tokens
    assert fill.reference == "paper-1"
    assert executor.holdings.get(MINT) == tokens
    assert source.reads[0] == ([MINT], 1_000.0)


async def test_a_second_buy_pays_no_rent_and_jito_tips_are_booked() -> None:
    executor, _, _ = _paper(use_jito=True, jito_tip_lamports=50_000)
    await executor.buy(_buy())
    again = await executor.buy(_buy())
    assert again.costs.components["rent"] == 0.0
    assert again.costs.components["tip"] == 50_000 / 1e9


async def test_the_entry_delay_waits_before_reading_the_pool() -> None:
    executor, source, clock = _paper(paper_entry_delay_seconds=2.0)
    await executor.buy(_buy())
    assert clock.sleeps == [2.0]
    assert source.reads[0][1] == 1_002.0


@pytest.mark.regression("BUG-145")
@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (
            lambda s: s.reject(MINT, "not_sol_pair"),
            "no PumpSwap pool \\(not_sol_pair\\)",
        ),
        (lambda s: s.set(MINT, 0, 5), "drained"),
        (lambda s: setattr(s, "fail", RuntimeError("rpc down")), "pool read failed"),
        (lambda s: setattr(s, "fee_error", RuntimeError("no fee")), "fee unknown"),
        (lambda s: s.set(MINT, 1, 10**15), "zero tokens"),
    ],
)
async def test_a_paper_buy_is_refused_wherever_a_live_one_would_fail(
    setup: object, message: str
) -> None:
    executor, source, _ = _paper()
    setup(source)  # type: ignore[operator]
    with pytest.raises(ExecutionRefused, match=message):
        await executor.buy(_buy())
    assert executor.holdings.get(MINT) == 0


async def test_a_buy_above_the_limit_price_is_refused() -> None:
    executor, _, _ = _paper()
    spot = (GRADUATION_QUOTE_RESERVE / 1e9) / (GRADUATION_BASE_RESERVE / 1e6)
    with pytest.raises(ExecutionRefused, match="above the limit"):
        await executor.buy(_buy(limit_price=spot))
    fill = await executor.buy(_buy(limit_price=spot * 1.05))
    assert fill.size > 0


async def test_a_buy_must_be_sized_in_sol() -> None:
    executor, _, _ = _paper()
    with pytest.raises(ExecutionRefused, match="sized in SOL"):
        await executor.buy(OrderRequest(MINT, Side.BUY, size=5.0))


@pytest.mark.regression("BUG-152")
async def test_a_paper_sell_needs_a_fresh_pool_read() -> None:
    executor, source, _ = _paper()
    source.fail = RuntimeError("rpc down")
    with pytest.raises(ExecutionRefused, match="pool read failed"):
        await executor.sell(_sell(1_000.0))


async def test_a_full_sell_refunds_the_rent_and_a_partial_one_does_not() -> None:
    executor, source, _ = _paper()
    bought = await executor.buy(_buy())
    half = bought.size / 2

    partial = await executor.sell(_sell(half))
    assert partial.costs.components["rent"] == 0.0
    assert partial.metadata["closes_position"] is False
    gross = partial.notional
    assert partial.costs.components["swap_fee"] == pytest.approx(gross * 0.01, abs=2e-9)

    rest = await executor.sell(_sell(bought.size - half))
    assert rest.costs.components["rent"] == -TOKEN_ACCOUNT_RENT_LAMPORTS / 1e9
    assert rest.metadata["closes_position"] is True
    assert executor.holdings.get(MINT) == 0
    assert rest.reference == "paper-3"


async def test_the_engine_flag_closes_a_position_the_module_did_not_buy() -> None:
    executor, _, _ = _paper()  # e.g. restored from the status file
    fill = await executor.sell(_sell(1_000.0, metadata={CLOSES_POSITION: True}))
    assert fill.costs.components["rent"] < 0
    plain = await executor.sell(_sell(1_000.0))
    assert plain.costs.components["rent"] == 0.0


async def test_a_sell_into_nothing_is_refused() -> None:
    executor, source, _ = _paper()
    source.set(MINT, 10**15, 1)
    with pytest.raises(ExecutionRefused, match="zero SOL"):
        await executor.execute(_sell(0.000001))


def test_holdings_never_go_negative() -> None:
    holdings = Holdings()
    holdings.add(MINT, 10)
    holdings.remove(MINT, 4)
    assert holdings.get(MINT) == 6
    holdings.remove(MINT, 99)
    assert holdings.get(MINT) == 0 and MINT not in holdings.raw


async def test_live_orders_are_refused_until_the_live_gate() -> None:
    with pytest.raises(ExecutionRefused) as refused:
        await LiveExecutor().execute(_buy())
    assert str(refused.value) == LIVE_REFUSAL
