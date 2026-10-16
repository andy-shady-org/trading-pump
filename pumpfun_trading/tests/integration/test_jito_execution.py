import asyncio

import base58
import pytest
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.execution.builder import ExecutionBuilder, build_execution_client
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.jito import (
    JitoBundleStatus,
    JitoClient,
    JitoTipFloor,
)

pytestmark = pytest.mark.usefixtures("offline_trade_rpc")


@pytest.fixture
def mock_keypair():
    return Keypair.from_seed(b"01234567890123456789012345678901")


@pytest.fixture
def execution_client(mock_keypair):
    b58_key = base58.b58encode(mock_keypair.to_bytes()).decode()
    return PumpFunExecutionClient(
        b58_key,
        "https://mock-rpc.solana.com",
        use_jito=True,
        jito_fallback_to_rpc=True,
        jito_confirmation_timeout=2.0,
    )


async def test_execution_client_jito_initialization(execution_client):
    assert execution_client.use_jito is True
    assert execution_client.jito_fallback_to_rpc is True
    assert execution_client.jito_client is not None
    assert isinstance(execution_client.jito_client, JitoClient)


async def test_calculate_dynamic_jito_tip(execution_client, monkeypatch):
    async def mock_fetch_tip_floor(self, max_age_seconds=10.0):
        return JitoTipFloor(
            p25_landed_tip_sol=0.00001,
            p50_landed_tip_sol=0.00005,  # 50,000 lamports
            p75_landed_tip_sol=0.0001,
            p95_landed_tip_sol=0.001,
        )

    monkeypatch.setattr(JitoClient, "fetch_tip_floor", mock_fetch_tip_floor)

    tip = await execution_client.calculate_dynamic_jito_tip(
        trade_amount_sol=0.01, conviction_score=1.0
    )
    assert tip == 50_000

    tip_high_conviction = await execution_client.calculate_dynamic_jito_tip(
        trade_amount_sol=0.01, conviction_score=2.0
    )
    assert tip_high_conviction == 100_000

    tip_large_trade = await execution_client.calculate_dynamic_jito_tip(
        trade_amount_sol=10.0, conviction_score=1.0
    )
    assert tip_large_trade == 50_000_000


async def test_calculate_dynamic_jito_tip_fallback_when_error(
    execution_client, monkeypatch
):
    async def mock_fetch_error(self, max_age_seconds=10.0):
        raise RuntimeError("Network error")

    monkeypatch.setattr(JitoClient, "fetch_tip_floor", mock_fetch_error)
    tip = await execution_client.calculate_dynamic_jito_tip(trade_amount_sol=0.1)
    assert tip >= 10_000


async def test_build_buy_and_sell_tx_with_jito_tip(execution_client, monkeypatch):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    buy_tx = await execution_client.build_buy_tx(
        mint, curve, sol_amount=0.1, tip_lamports=75_000
    )
    assert isinstance(buy_tx, VersionedTransaction)
    assert len(buy_tx.signatures) > 0

    sell_tx = await execution_client.build_sell_tx(
        mint, curve, token_amount=1_000_000, min_sol_output=0.05, tip_lamports=75_000
    )
    assert isinstance(sell_tx, VersionedTransaction)
    assert len(sell_tx.signatures) > 0


async def test_send_jito_bundle_with_fallback_success(execution_client, monkeypatch):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    tx = await execution_client.build_buy_tx(mint, curve, sol_amount=0.1)

    async def mock_send_bundle(self, txs, endpoint_url=None):
        return "mock_bundle_id_123"

    async def mock_wait_confirmation(
        self, bundle_id, timeout_seconds=12.0, poll_interval=0.5
    ):
        return JitoBundleStatus(
            bundle_id=bundle_id,
            status="Landed",
            confirmation_status="confirmed",
            slot=280000000,
        )

    monkeypatch.setattr(JitoClient, "send_bundle", mock_send_bundle)
    monkeypatch.setattr(
        JitoClient, "wait_for_bundle_confirmation", mock_wait_confirmation
    )

    sig = await execution_client.send_jito_bundle_with_fallback([tx])
    assert sig == str(tx.signatures[0])
    assert execution_client.execution_health_score >= 100.0


async def test_send_jito_bundle_fallback_to_rpc_on_timeout(
    execution_client, monkeypatch
):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    tx = await execution_client.build_buy_tx(mint, curve, sol_amount=0.1)

    async def mock_send_bundle(self, txs, endpoint_url=None):
        return "mock_bundle_id_timeout"

    async def mock_wait_timeout(
        self, bundle_id, timeout_seconds=12.0, poll_interval=0.5
    ):
        raise TimeoutError("Bundle confirmation timed out")

    async def mock_send_tx(transaction):
        return "direct_rpc_signature_xyz_123456789012345"

    monkeypatch.setattr(JitoClient, "send_bundle", mock_send_bundle)
    monkeypatch.setattr(JitoClient, "wait_for_bundle_confirmation", mock_wait_timeout)
    monkeypatch.setattr(execution_client, "send_transaction", mock_send_tx)

    sig = await execution_client.send_jito_bundle_with_fallback([tx])
    assert sig == "direct_rpc_signature_xyz_123456789012345"
    assert execution_client.failed_execution_attempts >= 1


async def test_send_jito_bundle_with_fallback_without_jito_client(
    execution_client, monkeypatch
):
    execution_client.jito_client = None
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    tx = await execution_client.build_buy_tx(mint, curve, sol_amount=0.1)

    async def mock_send_bundle_raw(txs, endpoint_url=None):
        return "mock_raw_bundle_id"

    async def mock_confirm(sig, max_retries=20, interval=1.0):
        return True

    monkeypatch.setattr(execution_client, "send_jito_bundle", mock_send_bundle_raw)
    monkeypatch.setattr(execution_client, "confirm_transaction", mock_confirm)

    sig = await execution_client.send_jito_bundle_with_fallback([tx])
    assert sig == str(tx.signatures[0])


async def test_send_jito_bundle_with_fallback_empty_tx_list(execution_client):
    with pytest.raises(ValueError, match="Cannot submit empty"):
        await execution_client.send_jito_bundle_with_fallback([])


async def test_send_jito_bundle_fallback_disabled_raises(execution_client, monkeypatch):
    execution_client.jito_fallback_to_rpc = False
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    tx = await execution_client.build_buy_tx(mint, curve, sol_amount=0.1)

    async def mock_send_bundle(self, txs, endpoint_url=None):
        raise RuntimeError("Block engine unavailable")

    monkeypatch.setattr(JitoClient, "send_bundle", mock_send_bundle)

    with pytest.raises(RuntimeError):
        await execution_client.send_jito_bundle_with_fallback([tx])


async def test_buy_and_sell_high_level_with_jito(execution_client, monkeypatch):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    async def mock_send_bundle_fallback(txs, timeout_seconds=None):
        return f"mock_sig_{len(txs)}"

    monkeypatch.setattr(
        execution_client, "send_jito_bundle_with_fallback", mock_send_bundle_fallback
    )

    buy_sig = await execution_client.buy(mint, curve, 0.2, conviction_score=1.5)
    assert buy_sig == "mock_sig_1"

    sell_sig = await execution_client.sell(mint, curve, 100_000, min_sol_output=0.1)
    assert sell_sig == "mock_sig_1"


async def test_buy_and_sell_without_jito(execution_client, monkeypatch):
    execution_client.use_jito = False
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, _ = execution_client.get_bonding_curve_pda(mint)

    monkeypatch.setattr(
        execution_client, "get_ata_exists", lambda m: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(
        execution_client,
        "get_latest_blockhash",
        lambda: asyncio.sleep(0, result="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"),
    )

    async def mock_send_tx(tx):
        return "direct_sig_tx"

    monkeypatch.setattr(execution_client, "send_transaction", mock_send_tx)

    buy_sig = await execution_client.buy(mint, curve, 0.1)
    assert buy_sig == "direct_sig_tx"

    sell_sig = await execution_client.sell(mint, curve, 50_000)
    assert sell_sig == "direct_sig_tx"


async def test_execution_client_close(execution_client):
    assert execution_client.jito_client is not None
    await execution_client.close()


async def test_execution_builder_with_jito():
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    b58_key = base58.b58encode(keypair.to_bytes()).decode()

    builder = ExecutionBuilder(
        b58_key,
        "https://mock-rpc.solana.com",
        use_jito=True,
        jito_tip_lamports=50_000,
    )
    client = builder.build()
    assert client.use_jito is True
    assert client.jito_tip_lamports == 50_000
    await client.close()

    direct_client = build_execution_client(
        b58_key,
        "https://mock-rpc.solana.com",
        use_jito=True,
    )
    assert direct_client.use_jito is True
    await direct_client.close()


async def test_trading_bot_jito_env_configuration(monkeypatch):
    monkeypatch.setenv("PUMPFUN_USE_JITO", "true")
    monkeypatch.setenv("PUMPFUN_JITO_TIP_LAMPORTS", "25000")
    monkeypatch.setenv("PUMPFUN_JITO_CONFIRMATION_TIMEOUT", "8.0")
    monkeypatch.setenv("PUMPFUN_JITO_FALLBACK_TO_RPC", "true")

    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    b58_key = base58.b58encode(keypair.to_bytes()).decode()

    bot = TradingBot(
        private_key_b58=b58_key,
        rpc_url="https://mock-rpc.solana.com",
        dry_run=True,
    )
    assert bot.execution.use_jito is True
    assert bot.execution.jito_tip_lamports == 25_000
    assert bot.execution.jito_confirmation_timeout == 8.0
    assert bot.execution.jito_fallback_to_rpc is True

    await bot.close()
