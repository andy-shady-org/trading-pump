"""Regression tests pinning the Pump.fun buy/sell account layout and Jito encoding.

The layouts mirror successful mainnet Pump.fun ``buy`` (18 accounts) and ``sell``
(16 accounts) instructions. The previous ``BuyV2``/``SellV2`` layout was rejected
on-chain with ``sharing_config`` ConstraintSeeds (error 2006), so every buy failed.
Mayhem-mode curves additionally require the reserved fee recipient (error 6000).
"""

import base64

import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from pumpfun_trading.sdk.execution import (
    BUY_DISCRIMINATOR,
    BUYBACK_FEE_RECIPIENT,
    EVENT_AUTHORITY,
    FEE_RECIPIENT,
    GLOBAL_STATE,
    MAYHEM_FEE_RECIPIENT,
    PUMP_FEE_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    SELL_DISCRIMINATOR,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    PumpFunExecutionClient,
)
from pumpfun_trading.sdk.jito import JitoClient

MINT = "6SdFRZBMcgFtJ8cUgrohtwJVg2CALT8W1bAmoyBnpump"
CREATOR = "C7bbBs42K6ktWUjwUcxSGvXAVUqeaEJ2y5PRHFzcPqWe"
FEE_CONFIG = "8Wf5TiAheLUqBrKXeYg2JtAFFMWtKdG2BSFgqUcPVwTt"
GLOBAL_VOLUME_ACCUMULATOR = "Hq2wp8uJ9jCPsYgNHex8RtqdvMPfVGoYwjvF1ATiwn2Y"


@pytest.fixture
def client() -> PumpFunExecutionClient:
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        base58.b58encode(keypair.to_bytes()).decode(),
        "https://mock-rpc.solana.com",
    )


def _pda(seeds: list[bytes]) -> Pubkey:
    return Pubkey.find_program_address(seeds, Pubkey.from_string(PUMP_PROGRAM_ID))[0]


def test_buy_instruction_matches_mainnet_layout(client: PumpFunExecutionClient):
    mint = Pubkey.from_string(MINT)
    token_prog = Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)
    curve, _ = client.get_bonding_curve_pda(MINT)
    curve_pk = Pubkey.from_string(curve)

    ix = client.build_buy_instruction(
        MINT, curve, 1_000, 2_000, creator=CREATOR, base_token_program=token_prog
    )

    assert str(ix.program_id) == PUMP_PROGRAM_ID
    assert ix.data[:8] == BUY_DISCRIMINATOR
    assert int.from_bytes(ix.data[8:16], "little") == 1_000
    assert int.from_bytes(ix.data[16:24], "little") == 2_000

    expected = [
        (GLOBAL_STATE, False, False),
        (FEE_RECIPIENT, False, True),
        (MINT, False, False),
        (curve, False, True),
        (str(get_associated_token_address(curve_pk, mint, token_prog)), False, True),
        (
            str(get_associated_token_address(client.wallet, mint, token_prog)),
            False,
            True,
        ),
        (str(client.wallet), True, True),
        (SYSTEM_PROGRAM_ID, False, False),
        (TOKEN_2022_PROGRAM_ID_STR, False, False),
        (
            str(_pda([b"creator-vault", bytes(Pubkey.from_string(CREATOR))])),
            False,
            True,
        ),
        (EVENT_AUTHORITY, False, False),
        (PUMP_PROGRAM_ID, False, False),
        (GLOBAL_VOLUME_ACCUMULATOR, False, False),
        (
            str(_pda([b"user_volume_accumulator", bytes(client.wallet)])),
            False,
            True,
        ),
        (FEE_CONFIG, False, False),
        (PUMP_FEE_PROGRAM_ID, False, False),
        (str(_pda([b"bonding-curve-v2", bytes(mint)])), False, False),
        (BUYBACK_FEE_RECIPIENT, False, True),
    ]
    actual = [(str(m.pubkey), m.is_signer, m.is_writable) for m in ix.accounts]
    assert actual == expected


def test_sell_instruction_matches_mainnet_layout(client: PumpFunExecutionClient):
    mint = Pubkey.from_string(MINT)
    token_prog = Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)
    curve, _ = client.get_bonding_curve_pda(MINT)

    ix = client.build_sell_instruction(
        MINT, curve, 5_000, 10, creator=CREATOR, base_token_program=token_prog
    )

    assert ix.data[:8] == SELL_DISCRIMINATOR
    accounts = [(str(m.pubkey), m.is_writable) for m in ix.accounts]
    assert len(accounts) == 16
    assert accounts[6] == (str(client.wallet), True)
    assert accounts[8] == (
        str(_pda([b"creator-vault", bytes(Pubkey.from_string(CREATOR))])),
        True,
    )
    assert accounts[9] == (TOKEN_2022_PROGRAM_ID_STR, False)
    assert accounts[12] == (FEE_CONFIG, False)
    assert accounts[14] == (str(_pda([b"bonding-curve-v2", bytes(mint)])), False)
    assert accounts[15] == (BUYBACK_FEE_RECIPIENT, True)


def test_mayhem_mode_curves_use_reserved_fee_recipient(
    client: PumpFunExecutionClient,
):
    curve, _ = client.get_bonding_curve_pda(MINT)

    buy_ix = client.build_buy_instruction(MINT, curve, 1, 1, is_mayhem_mode=True)
    sell_ix = client.build_sell_instruction(MINT, curve, 1, 1, is_mayhem_mode=True)

    assert str(buy_ix.accounts[1].pubkey) == MAYHEM_FEE_RECIPIENT
    assert str(sell_ix.accounts[1].pubkey) == MAYHEM_FEE_RECIPIENT
    assert buy_ix.accounts[1].is_writable


def test_decode_bonding_curve_reads_mayhem_flag():
    creator = bytes(Pubkey.from_string(CREATOR))
    base = bytes(8) + (1).to_bytes(8, "little") * 5 + b"\x00" + creator

    decode = PumpFunExecutionClient.decode_bonding_curve_data

    assert decode(base)["is_mayhem_mode"] is False
    assert decode(base + b"\x00")["is_mayhem_mode"] is False
    assert decode(base + b"\x01")["is_mayhem_mode"] is True


@pytest.mark.asyncio
async def test_build_buy_tx_routes_mayhem_curve_fees(
    client: PumpFunExecutionClient, monkeypatch
):
    creator = bytes(Pubkey.from_string(CREATOR))
    raw = (
        bytes(8)
        + (1_073_000_000_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (793_100_000_000_000).to_bytes(8, "little")
        + bytes(8)
        + (1_000_000_000_000_000).to_bytes(8, "little")
        + b"\x00"
        + creator
        + b"\x01"
    )

    async def fake_request(payload, **_kwargs):
        if payload["method"] == "getAccountInfo":
            return {
                "result": {"value": {"data": [base64.b64encode(raw).decode(), "b"]}}
            }
        return {"result": {"value": {"blockhash": SYSTEM_PROGRAM_ID}}}

    async def fake_ata_exists(*_args, **_kwargs):
        return True

    async def fake_token_program(_mint):
        return Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)

    async def fake_blockhash():
        return "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"

    monkeypatch.setattr(client.rpc_pool, "request", fake_request)
    monkeypatch.setattr(client, "get_ata_exists", fake_ata_exists)
    monkeypatch.setattr(client, "get_token_program_for_mint", fake_token_program)
    monkeypatch.setattr(client, "get_latest_blockhash", fake_blockhash)

    curve, _ = client.get_bonding_curve_pda(MINT)
    tx = await client.build_buy_tx(MINT, curve, 0.005, tip_lamports=0)

    keys = [str(k) for k in tx.message.account_keys]
    assert MAYHEM_FEE_RECIPIENT in keys
    assert FEE_RECIPIENT not in keys


@pytest.mark.asyncio
async def test_jito_send_bundle_declares_base64_encoding(monkeypatch):
    captured: dict = {}

    async def fake_send_json_rpc(self, payload, endpoint_url=None):
        captured.update(payload)
        return "bundle-id"

    monkeypatch.setattr(JitoClient, "_send_json_rpc", fake_send_json_rpc)
    bundle_id = await JitoClient().send_bundle(["AAAA"])

    assert bundle_id == "bundle-id"
    assert captured["params"] == [["AAAA"], {"encoding": "base64"}]
