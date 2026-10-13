import base58
import pytest
from solders.keypair import Keypair

from pumpfun_trading.config.env import (
    decode_keypair,
    load_keypair_from_env,
    sanitize_env_for_logging,
    validate_required_runtime_env,
)
from pumpfun_trading.ops.logging import setup_structured_logging
from pumpfun_trading.ops.monitoring import build_runtime_summary, runtime_is_healthy


def test_runtime_env_is_masked_and_validated(monkeypatch):
    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", "supersecretkey123456")
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://example.com/rpc")
    env = validate_required_runtime_env()
    assert env["PUMPFUN_PRIVATE_KEY"] == "supersecretkey123456"
    masked = sanitize_env_for_logging()
    assert "supersecretkey123456" not in str(masked)
    assert "PUMPFUN_PRIVATE_KEY" in masked


def test_structured_logging_and_runtime_summary():
    logger = setup_structured_logging(
        logger_name="pumpfun_trading.test", log_file=None, console=False
    )
    assert logger.name == "pumpfun_trading.test"

    class DummyBot:
        state = type("S", (), {"value": "monitoring"})()
        _health_ok = True
        _risk_killed = False
        _stop_requested = False
        active_positions = {"a": {}, "b": {}}
        _buy_attempts = {"a": 2}

        def _metrics_snapshot(self):
            return {"buys": 1, "sells": 0}

        _last_event = "ready"
        _last_status = "monitoring"

    bot = DummyBot()
    summary = build_runtime_summary(bot)
    assert summary["active_positions"] == 2
    assert runtime_is_healthy(bot) is True


def test_decode_and_load_keypair_from_env(monkeypatch):
    # Unset case
    monkeypatch.delenv("PUMPFUN_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("SOLANA_PRIVATE_KEY", raising=False)
    assert load_keypair_from_env() is None

    # Valid 32-byte seed
    seed = b"12345678901234567890123456789012"
    kp = Keypair.from_seed(seed)
    b58_seed = base58.b58encode(seed).decode("ascii")
    b58_full = base58.b58encode(kp.to_bytes()).decode("ascii")

    # From 32-byte seed
    decoded_seed_kp = decode_keypair(b58_seed)
    assert decoded_seed_kp.pubkey() == kp.pubkey()

    # From 64-byte secret key
    decoded_full_kp = decode_keypair(b58_full)
    assert decoded_full_kp.pubkey() == kp.pubkey()

    # From PUMPFUN_PRIVATE_KEY
    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", b58_seed)
    loaded_kp = load_keypair_from_env()
    assert loaded_kp is not None
    assert loaded_kp.pubkey() == kp.pubkey()

    # From SOLANA_PRIVATE_KEY fallback
    monkeypatch.delenv("PUMPFUN_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", b58_full)
    loaded_kp2 = load_keypair_from_env()
    assert loaded_kp2 is not None
    assert loaded_kp2.pubkey() == kp.pubkey()

    # Custom env var
    monkeypatch.setenv("CUSTOM_WALLET_KEY", b58_seed)
    loaded_kp3 = load_keypair_from_env("CUSTOM_WALLET_KEY")
    assert loaded_kp3 is not None
    assert loaded_kp3.pubkey() == kp.pubkey()

    # Invalid key length raises ValueError
    with pytest.raises(ValueError, match="Private key must be a base58-encoded"):
        decode_keypair(base58.b58encode(b"short").decode("ascii"))
