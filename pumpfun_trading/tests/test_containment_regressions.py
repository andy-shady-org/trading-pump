"""Regression tests for the Batch 7 containment fixes (BUG-37, 55, 59, 61, 90)."""

import argparse
import json
import time
from unittest.mock import MagicMock

import pytest
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.cli.arbitrage import build_arbitrage_parser, run_arbitrage_cli
from pumpfun_trading.execution.arbitrage import AtomicArbitrageBuilder
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.arbitrage import ArbitrageOpportunity
from pumpfun_trading.streams.geyser import (
    GeyserConnectionState,
    GeyserTransportUnavailableError,
    YellowstoneGeyserClient,
)

MINT = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"


async def test_geyser_without_transport_fails_fast():
    """BUG-55: no transport means a clear error, never a fake CONNECTED state."""
    client = YellowstoneGeyserClient(endpoint="grpc.example:443")
    assert client.has_transport is False
    with pytest.raises(GeyserTransportUnavailableError):
        await client.start()
    assert client.state == GeyserConnectionState.DISCONNECTED

    client.subscribe_bonding_curves([MINT])
    curve = client.bonding_curve_address(MINT)
    assert curve != MINT
    assert client._curve_to_mint[curve] == MINT


def _builder() -> tuple[AtomicArbitrageBuilder, MagicMock]:
    kp = Keypair()
    ix = Instruction(program_id=Pubkey.default(), data=b"", accounts=[])
    client = MagicMock(spec=PumpFunExecutionClient)
    client.wallet = kp.pubkey()
    client._to_pubkey = lambda s: Pubkey.from_string(s) if isinstance(s, str) else s
    client.get_bonding_curve_pda.return_value = (str(Pubkey.default()), 255)
    for name in (
        "build_set_compute_unit_limit_instruction",
        "build_set_compute_unit_price_instruction",
        "build_buy_instruction",
        "build_sell_instruction",
        "build_raydium_swap_instruction",
        "build_jito_tip_instruction",
        "_wsol_close_instruction",
    ):
        getattr(client, name).return_value = ix
    client._wsol_open_instructions.return_value = [ix]
    return AtomicArbitrageBuilder(client), client


def _opp(direction: str) -> ArbitrageOpportunity:
    keys = MagicMock(spec=RaydiumPoolKeys)
    keys.pc_mint = "So11111111111111111111111111111111111111112"
    return ArbitrageOpportunity(
        mint=MINT,
        direction=direction,
        pump_spot_price=1.0,
        raydium_spot_price=1.1,
        spread_pct=0.1,
        optimal_input_sol=0.5,
        expected_output_sol=0.55,
        gross_profit_sol=0.05,
        estimated_fees_sol=0.0,
        estimated_jito_tip_sol=0.0,
        net_profit_sol=0.05,
        timestamp=time.time(),
        pool_keys=keys,
        leg1_min_amount_out=1_000,
        leg2_min_amount_out=2_000,
    )


def test_arbitrage_raydium_leg_directions():
    """BUG-37: Raydium legs swap between WSOL and token ATAs, never ATA -> same ATA."""
    builder, client = _builder()

    builder.build_arbitrage_instructions(_opp("pump_to_raydium"))
    kwargs = client.build_raydium_swap_instruction.call_args.kwargs
    assert kwargs["is_buy"] is False
    assert "user_source_token_account" not in kwargs
    assert client._wsol_open_instructions.call_args.args[1] == 0
    client._wsol_close_instruction.assert_called()

    builder.build_arbitrage_instructions(_opp("raydium_to_pump"))
    kwargs = client.build_raydium_swap_instruction.call_args.kwargs
    assert kwargs["is_buy"] is True
    assert client._wsol_open_instructions.call_args.args[1] == 500_000_000


def test_arbitrage_opportunity_unverified_by_default():
    """BUG-59: opportunities are unverified unless reserves were read on-chain."""
    assert _opp("pump_to_raydium").reserves_verified is False


def _arb_args(*argv: str) -> argparse.Namespace:
    return build_arbitrage_parser().parse_args(list(argv))


def test_arb_cli_refuses_live_and_labels_demo(tmp_path, capsys):
    """BUG-90: `--live` is refused and exported rows are marked as demo data."""
    assert run_arbitrage_cli(_arb_args("--live")) == 2

    out = tmp_path / "arb.json"
    assert run_arbitrage_cli(_arb_args("--export-history", str(out))) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert rows and all(row["demo"] is True for row in rows)
