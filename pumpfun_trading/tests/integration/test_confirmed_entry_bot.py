"""Confirmed entries end to end: create -> screen -> watch -> poll -> subscribe ->
confirm -> buy -> momentum exit (FEAT-51, FEAT-52)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pumpfun_trading.bot.enrichment import TokenScreeningVerdict
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.tests.support.constants import SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot

CREATOR = "CreatorWallet1111111111111111111111111111111"


def _curve(real_sol: float) -> dict[str, Any]:
    real = int(real_sol * 1e9)
    v_sol = 30_000_000_000 + real
    return {
        "virtual_sol_reserves": v_sol,
        "virtual_token_reserves": int(32_190_000_000 * 1e15 / v_sol),
        "real_sol_reserves": real,
        "complete": False,
        "is_mayhem_mode": False,
    }


def _market_cap(real_sol: float) -> float:
    curve = _curve(real_sol)
    v_sol = curve["virtual_sol_reserves"] / 1e9
    v_tok = curve["virtual_token_reserves"] / 1e6
    return float(v_sol * 1e9 / v_tok)


def _confirmed_bot(tmp_path: Path) -> TradingBot:
    bot = make_bot(
        tmp_path,
        entry_mode="confirmed",
        buy_amount_sol=0.02,
        max_active_positions=2,
        min_market_cap_sol=35.0,
        momentum_max_market_cap_sol=75.0,
        momentum_min_token_age_seconds=60.0,
        momentum_max_token_age_seconds=600,
        momentum_window_seconds=30,
        momentum_min_buy_ratio=2.0,
        momentum_min_z_score=1.0,
        momentum_min_unique_buyers=5,
        momentum_min_net_inflow_sol=1.0,
        watch_promote_min_sol_growth=1.0,
        watch_max_trade_subscriptions=5,
        stagnant_timeout_seconds=35.0,
        stagnant_min_buy_sol=0.1,
        enable_anti_rug_filters=False,
        require_trade_feed=False,
        enable_copy_trading=False,
        enable_capital_rotation=False,
    )
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_PUMP_MINT, passed=True, risk_score=5.0
        )
    )
    bot._active_ws = MagicMock(spec=["send_json"])
    bot._active_ws.send_json = AsyncMock()
    return bot


def _sent_methods(bot: TradingBot) -> list[tuple[str, list[str]]]:
    sent: list[tuple[str, list[str]]] = []
    for call in bot._active_ws.send_json.await_args_list:  # type: ignore[union-attr]
        msg = call.args[0]
        sent.append((msg["method"], msg.get("keys", [])))
    return sent


async def _trade(
    bot: TradingBot, *, user: str, sol: float, ts: float, mc: float, buy: bool = True
) -> None:
    await bot._handle_trade_update(
        {
            "mint": SAMPLE_PUMP_MINT,
            "txType": "buy" if buy else "sell",
            "solAmount": sol,
            "traderPublicKey": user,
            "timestamp": ts,
            "marketCapSol": mc,
        }
    )


async def test_confirmed_entry_watches_promotes_confirms_and_buys_once(
    tmp_path: Path,
) -> None:
    bot = _confirmed_bot(tmp_path)
    created = time.time() - 120.0

    await bot._handle_new_token_event(
        {
            "mint": SAMPLE_PUMP_MINT,
            "pool": "pump",
            "name": "Confirmed",
            "vSolInBondingCurve": 30.5,
            "vTokensInBondingCurve": 1_055_000_000,
            "traderPublicKey": CREATOR,
            "timestamp": created,
        }
    )
    assert SAMPLE_PUMP_MINT not in bot.active_positions
    assert bot.order_flow_engine.is_watched(SAMPLE_PUMP_MINT)
    await bot.close()

    bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
        return_value={SAMPLE_PUMP_MINT: _curve(10.0)}
    )
    await bot._poll_watch_list()
    assert _sent_methods(bot) == [("subscribeTokenTrade", [SAMPLE_PUMP_MINT])]

    mc = _market_cap(10.0)
    now = time.time()
    # Creator buys and a single wallet do not confirm demand.
    await _trade(bot, user=CREATOR, sol=3.0, ts=now - 20, mc=mc)
    await _trade(bot, user="Buyer0", sol=0.5, ts=now - 19, mc=mc)
    assert SAMPLE_PUMP_MINT not in bot.active_positions

    for i in range(1, 6):
        await _trade(bot, user=f"Buyer{i}", sol=0.5, ts=now - 10 + i, mc=mc)

    assert SAMPLE_PUMP_MINT in bot.active_positions
    position = bot.active_positions[SAMPLE_PUMP_MINT]
    assert position["strategy"] == "momentum"
    assert position["entry_reason"] == "momentum_confirmed"
    assert not bot.order_flow_engine.is_watched(SAMPLE_PUMP_MINT)
    status = bot.watch_list_status()["stats"]
    assert status["promoted"] == 1 and status["bought"] == 1

    buys = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text().splitlines()
        if '"type": "trade"' in line and '"action": "buy"' in line
    ]
    assert len(buys) == 1
    record = buys[0]["payload"]
    assert record["strategy"] == "momentum"
    metrics = record["entry_metrics"]
    assert metrics["unique_buyers"] >= 5
    assert metrics["token_age_seconds"] >= 60.0
    assert CREATOR not in json.dumps(metrics)

    # A follow-on buyer of size keeps the buy-flow stagnation clock fresh.
    await _trade(bot, user="LateBuyer", sol=0.4, ts=now + 1, mc=mc * 1.02)
    assert bot.active_positions[SAMPLE_PUMP_MINT]["last_qualifying_buy_at"] == (now + 1)
    await bot.close()


async def test_confirmed_entry_too_young_or_outside_band_is_not_bought(
    tmp_path: Path,
) -> None:
    bot = _confirmed_bot(tmp_path)
    bot.order_flow_engine.watch(
        SAMPLE_PUMP_MINT, created_at=time.time() - 10.0, creator=CREATOR, real_sol=0.0
    )
    bot.order_flow_engine.mark_watch_subscribed(SAMPLE_PUMP_MINT)
    now = time.time()

    for i in range(8):  # strong flow, but the token is only 10 s old
        await _trade(bot, user=f"Young{i}", sol=0.5, ts=now - 8 + i, mc=50.0)
    assert SAMPLE_PUMP_MINT not in bot.active_positions

    bot.order_flow_engine.get_watch(SAMPLE_PUMP_MINT).created_at = now - 120  # type: ignore[union-attr]
    for i in range(8):  # old enough, but far above the band
        await _trade(bot, user=f"Late{i}", sol=0.5, ts=now + i, mc=95.0)
    assert SAMPLE_PUMP_MINT not in bot.active_positions
    assert bot.order_flow_engine.is_watched(SAMPLE_PUMP_MINT)
    await bot.close()
