"""Integration tests: recorder replay."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.streams.geyser import BondingCurveStateUpdate, TradeEventUpdate
from pumpfun_trading.tests.support.factories import make_config


async def test_trading_bot_replay_recording_hook(tmp_path: Path):
    """Test TradingBot integration with ReplayRecorder during market events."""
    replay_file = tmp_path / "bot_replay.jsonl"

    config = make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        replay_log_path=str(replay_file),
    )

    with (
        patch("pumpfun_trading.bot.factory.build_execution_client"),
        patch("pumpfun_trading.bot.factory.YellowstoneGeyserClient"),
    ):
        bot = TradingBot(
            private_key_b58="1" * 64,
            rpc_url="http://127.0.0.1:8899",
            config=config,
            dry_run=True,
            replay_log_path=replay_file,
        )

        assert bot.replay_recorder is not None
        await bot.replay_recorder.start()

        # Simulate bonding curve update
        curve_update = BondingCurveStateUpdate(
            mint="RecordMint1111111111111111111111111111111",
            bonding_curve_pubkey="CurvePubkey11111111111111111111111111111",
            slot=1000,
            virtual_token_reserves=1_000_000_000_000,
            virtual_sol_reserves=30_000_000_000,
            real_token_reserves=800_000_000_000,
            real_sol_reserves=5_000_000_000,
            token_total_supply=1_000_000_000_000,
            complete=False,
            price_sol=0.000000030,
            market_cap_sol=30.0,
            timestamp=1700000100.0,
        )
        await bot._handle_bonding_curve_state_update(curve_update)

        # Simulate Geyser trade event
        trade_event = TradeEventUpdate(
            mint="RecordMint1111111111111111111111111111111",
            sol_amount_lamports=500_000_000,
            token_amount=15_000_000,
            is_buy=True,
            user="BuyerWallet111111111111111111111111111111",
            timestamp=1700000105,
            virtual_sol_reserves=30_500_000_000,
            virtual_token_reserves=985_000_000_000,
            real_sol_reserves=5_500_000_000,
            real_token_reserves=785_000_000_000,
        )
        await bot._handle_trade_event_update(trade_event)

        # Simulate new token discovery
        await bot._handle_new_token_event(
            {
                "mint": "NewCoinMint11111111111111111111111111111",
                "name": "NewCoin",
                "market_cap": 27.96,
            }
        )

        # Simulate WebSocket trade update
        await bot._handle_trade_update(
            {
                "mint": "NewCoinMint11111111111111111111111111111",
                "is_buy": True,
                "sol_amount": 0.25,
                "token_amount": 8_000_000,
                "market_cap": 28.2,
                "timestamp": 1700000120.0,
            }
        )

        await bot.close()

    assert replay_file.exists()
    lines = [
        json.loads(line)
        for line in replay_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 4
    mints = {record["mint"] for record in lines}
    assert "RecordMint1111111111111111111111111111111" in mints
    assert "NewCoinMint11111111111111111111111111111" in mints
