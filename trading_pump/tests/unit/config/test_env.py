"""Unit tests for ``config/env.py``."""

from __future__ import annotations

import re
from pathlib import Path

import base58
import pytest
from solders.keypair import Keypair

from trading_pump.config.env import (
    UNREAD_ENV_VARS,
    resolve_bot_log_path,
    decode_keypair,
    get_env_bool,
    get_env_float,
    get_env_int,
    get_runtime_env,
    load_keypair_from_env,
    mask_secret,
    sanitize_env_for_logging,
    unread_env_warnings,
    validate_required_runtime_env,
)
from trading_pump.ops.logging import log_runtime_event, setup_structured_logging
from trading_pump.tests.support.factories import make_screening


def test_runtime_env_and_logging_helpers(monkeypatch, tmp_path):
    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", "supersecretkey123")
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://example.com/rpc")
    assert get_env_bool("PUMPFUN_USE_SSL", True) is True
    assert get_env_bool("PUMPFUN_USE_SSL", False) is False
    assert get_env_float("PUMPFUN_TEST_FLOAT", 2.5) == 2.5
    assert get_env_float("PUMPFUN_TEST_FLOAT_BAD", 3.5) == 3.5
    assert get_env_int("PUMPFUN_TEST_INT", 7) == 7
    assert get_env_int("PUMPFUN_TEST_INT_BAD", 9) == 9
    assert mask_secret("") == "<unset>"
    assert mask_secret("abc") == "********"
    assert "supersecretkey123" not in str(sanitize_env_for_logging())
    validate_required_runtime_env()

    logger = setup_structured_logging(
        logger_name="trading_pump.coverage_test",
        log_file=str(tmp_path / "audit.log"),
        console=False,
    )
    log_runtime_event(logger, "coverage_check", component="tests", ok=True)
    assert (tmp_path / "audit.log").exists()


def test_runtime_env_is_masked_and_validated(monkeypatch):
    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", "supersecretkey123456")
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://example.com/rpc")
    env = validate_required_runtime_env()
    assert env["PUMPFUN_PRIVATE_KEY"] == "supersecretkey123456"
    masked = sanitize_env_for_logging()
    assert "supersecretkey123456" not in str(masked)
    assert "PUMPFUN_PRIVATE_KEY" in masked


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


@pytest.mark.regression("BUG-87")
def test_status_and_audit_env_aliases(monkeypatch, tmp_path):
    """BUG-87: primary names and aliases resolve in env and the bot."""
    for name in (
        "PUMPFUN_STATUS_PATH",
        "PUMPFUN_AUDIT_LOG_PATH",
        "PUMPFUN_BOT_STATUS_PATH",
        "PUMPFUN_AUDIT_LOG",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", str(tmp_path / "s.json"))
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    env = get_runtime_env()
    assert env["PUMPFUN_STATUS_PATH"] == str(tmp_path / "s.json")
    assert env["PUMPFUN_AUDIT_LOG_PATH"] == str(tmp_path / "a.jsonl")

    from trading_pump.bot.run import TradingBot

    bot = TradingBot(
        private_key_b58="1" * 64,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=make_screening(dry_run=True),
    )
    assert bot.bot_status_path == str(tmp_path / "s.json")
    assert bot.audit_log_path == str(tmp_path / "a.jsonl")

    monkeypatch.setenv("PUMPFUN_STATUS_PATH", str(tmp_path / "p.json"))
    assert get_runtime_env()["PUMPFUN_STATUS_PATH"] == str(tmp_path / "p.json")


@pytest.mark.parametrize(
    ("name", "default", "value", "expected"),
    [
        ("PUMPFUN_USE_SSL", False, "true", True),
        ("PUMPFUN_USE_SSL", False, "0", False),
        ("PUMPFUN_USE_SSL", True, "yes", True),
        ("PUMPFUN_USE_SSL", False, "on", True),
        ("PUMPFUN_USE_SSL", False, "false", False),
    ],
)
def test_env_helpers_cover_all_branch_paths(
    monkeypatch, name, default, value, expected
):
    monkeypatch.setenv(name, value)
    assert get_env_bool(name, default) is expected
    assert get_env_float("PUMPFUN_TEST_FLOAT", 2.5) == 2.5
    assert get_env_int("PUMPFUN_TEST_INT", 7) == 7

    monkeypatch.delenv(name, raising=False)
    assert get_env_bool(name, default) is default
    assert get_env_float("PUMPFUN_TEST_FLOAT_MISSING", 3.5) == 3.5
    assert get_env_int("PUMPFUN_TEST_INT_MISSING", 9) == 9

    monkeypatch.setenv("PUMPFUN_TEST_FLOAT_BAD", "not-a-number")
    monkeypatch.setenv("PUMPFUN_TEST_INT_BAD", "nope")
    assert get_env_float("PUMPFUN_TEST_FLOAT_BAD", 4.5) == 4.5
    assert get_env_int("PUMPFUN_TEST_INT_BAD", 11) == 11

    assert mask_secret(None) == "<unset>"
    assert mask_secret("abc") == "********"
    assert mask_secret("abcdefgh") == "********"
    assert mask_secret("abcdefghij") == "abcd...ij"

    env = sanitize_env_for_logging()
    assert isinstance(env, dict)


def test_required_runtime_env_accepts_standard_names(monkeypatch):
    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", "abc123")
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://rpc.example")
    result = validate_required_runtime_env()
    assert result["PUMPFUN_PRIVATE_KEY"] == "abc123"
    assert result["PUMPFUN_RPC_URL"] == "https://rpc.example"

    monkeypatch.delenv("PUMPFUN_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PUMPFUN_RPC_URL", raising=False)
    with pytest.raises(ValueError, match="Missing required environment variables"):
        validate_required_runtime_env()


@pytest.mark.parametrize(
    "explicit, env, configured, expected",
    [
        (None, None, "bot.log", "bot.log"),
        (None, "data/bot.log", "bot.log", "data/bot.log"),
        ("arg.log", "data/bot.log", "bot.log", "arg.log"),
        (None, "  ", "bot.log", "bot.log"),
        (None, " data/bot.log ", "bot.log", "data/bot.log"),
        (None, "none", "bot.log", None),
        (None, "OFF", "bot.log", None),
        ("off", "data/bot.log", "bot.log", None),
        (None, None, None, None),
        (None, None, "", None),
    ],
)
def test_resolve_bot_log_path_precedence(
    monkeypatch: pytest.MonkeyPatch,
    explicit: str | None,
    env: str | None,
    configured: str | None,
    expected: str | None,
) -> None:
    if env is None:
        monkeypatch.delenv("PUMPFUN_BOT_LOG_PATH", raising=False)
    else:
        monkeypatch.setenv("PUMPFUN_BOT_LOG_PATH", env)

    assert resolve_bot_log_path(explicit, configured) == expected


def test_runtime_env_reports_bot_log_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUMPFUN_BOT_LOG_PATH", "data/bot.log")

    assert get_runtime_env()["PUMPFUN_BOT_LOG_PATH"] == "data/bot.log"


# --- Documented variables must be read (BUG-142) -----------------------------

REPO = Path(__file__).parents[4]


def _source_text() -> str:
    """The package source, without the UNREAD_ENV_VARS table itself."""
    package = REPO / "trading_pump"
    env_py = package / "config" / "env.py"
    head, rest = env_py.read_text(encoding="utf-8").split("UNREAD_ENV_VARS: dict", 1)
    tail = rest.split("def unread_env_warnings", 1)[1]
    others = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package.rglob("*.py")
        if "tests" not in path.relative_to(package).parts and path != env_py
    )
    return others + head + tail


@pytest.mark.regression("BUG-142")
def test_unread_variables_are_reported_by_name_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        "PUMPFUN_DRY_RUN": "true",
        "PUMPFUN_STOP_LOSS": "0.9",
        "PUMPFUN_ALERT_WEBHOOK_URL": "https://discord.com/api/webhooks/1/SECRET",
        "PUMPFUN_PRESET": "  ",  # blank: not set
        "PUMPFUN_RPC_URL": "https://example.invalid",
    }
    warnings = unread_env_warnings(env)

    assert [w.split(" ")[0] for w in warnings] == [
        "PUMPFUN_DRY_RUN",
        "PUMPFUN_ALERT_WEBHOOK_URL",
        "PUMPFUN_STOP_LOSS",
    ]
    assert "does NOT stop live trading" in warnings[0]
    assert not any("SECRET" in w for w in warnings)

    monkeypatch.setenv("PUMPFUN_CONFIG_PATH", "configs/canary.json")
    assert unread_env_warnings() == [
        "PUMPFUN_CONFIG_PATH is set but not read: use pumpbot --config <path>"
    ]


@pytest.mark.regression("BUG-142")
def test_unread_names_really_are_unread() -> None:
    source = _source_text()
    read = [n for n in UNREAD_ENV_VARS if re.search(rf"[\"']{n}[\"']", source)]
    assert read == [], "now read by the code: drop them from UNREAD_ENV_VARS"


@pytest.mark.regression("BUG-142")
def test_every_variable_in_the_manual_matrix_is_read() -> None:
    manual = (REPO / "docs" / "ENVIRONMENTAL-VARIABLES.md").read_text(encoding="utf-8")
    matrix = manual.split("## 2.")[1].split("## 3.")[0]
    documented = set(re.findall(r"\| \[`([A-Z][A-Z0-9_]+)`\]", matrix))
    aliases = {
        alias
        for cell in re.findall(r"\]\([^)]*\) \| ([^|]+) \|", matrix)
        for alias in re.findall(r"`([A-Z][A-Z0-9_]+)`", cell)
    }
    source = _source_text()
    unread = sorted(
        name
        for name in documented | aliases
        if name != "NO_COLOR" and not re.search(rf"[\"']{name}[\"']", source)
    )
    assert len(documented) > 40
    assert unread == []
    assert not (documented | aliases) & set(UNREAD_ENV_VARS)
