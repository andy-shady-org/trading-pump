"""Unit tests for ``config/env.py``: credentials, keypairs, unread variables."""

from __future__ import annotations

import re
from pathlib import Path

import base58
import pytest
from solders.keypair import Keypair

from trading_pump.config.env import (
    MODULE_ENV_VARS,
    PUBLIC_RPC_URL,
    PUMPPORTAL_URL,
    REPLACED_ENV_VARS,
    Credentials,
    decode_keypair,
    known_env_names,
    load_credentials,
    unread_env_warnings,
)

REPO = Path(__file__).parents[4]


def test_credentials_default_to_the_public_endpoints() -> None:
    creds = load_credentials({})

    assert creds.private_key is None and not creds.has_private_key
    assert creds.rpc_urls == (PUBLIC_RPC_URL,)
    assert creds.stream_url == PUMPPORTAL_URL
    assert creds.stream_connect_url() == PUMPPORTAL_URL
    with pytest.raises(ValueError, match="PUMPFUN_PRIVATE_KEY is not set"):
        creds.keypair()


def test_primary_names_beat_their_aliases_and_urls_are_deduplicated() -> None:
    creds = load_credentials(
        {
            "PUMPFUN_RPC_URL": "https://a.example",
            "HELIUS_RPC_URL": "https://ignored.example",
            "PUMPFUN_RPC_URLS": "https://b.example, https://a.example,,",
            "PUMPFUN_WS_URL": "wss://alias.example/ws",
            "SOLANA_PRIVATE_KEY": "alias-key",
        }
    )

    assert creds.rpc_urls == ("https://a.example", "https://b.example")
    assert creds.stream_url == "wss://alias.example/ws"
    assert creds.private_key == "alias-key"


def test_aliases_are_read_when_the_primary_is_blank() -> None:
    creds = load_credentials(
        {"PUMPFUN_RPC_URL": "  ", "HELIUS_RPC_URL": "https://h.example"}
    )

    assert creds.rpc_urls == ("https://h.example",)


@pytest.mark.regression("BUG-118")
def test_the_stream_key_is_added_for_pumpportal_only_and_never_shown() -> None:
    creds = load_credentials({"PUMPFUN_STREAM_API_KEY": "k1"})

    assert creds.stream_connect_url() == f"{PUMPPORTAL_URL}?api-key=k1"
    assert creds.stream_display_url == PUMPPORTAL_URL
    assert not creds.stream_key_in_url
    assert "k1" not in repr(creds)

    in_url = load_credentials({"PUMPFUN_STREAM_URL": f"{PUMPPORTAL_URL}?api-key=k2"})
    assert in_url.stream_key_in_url
    assert in_url.stream_display_url == PUMPPORTAL_URL
    assert in_url.stream_connect_url() == f"{PUMPPORTAL_URL}?api-key=k2"

    other = load_credentials(
        {"PUMPFUN_STREAM_URL": "wss://other.test/feed", "PUMPFUN_STREAM_API_KEY": "k1"}
    )
    assert other.stream_connect_url() == "wss://other.test/feed"


def test_repr_hides_every_value() -> None:
    creds = Credentials(private_key="secret-key", rpc_urls=("https://rpc/?api-key=x",))

    text = repr(creds)
    assert "secret-key" not in text and "api-key=x" not in text
    assert "private_key=set" in text and "rpc_urls=1" in text


def test_decode_keypair_seed_secret_and_bad_lengths() -> None:
    seed = b"12345678901234567890123456789012"
    kp = Keypair.from_seed(seed)
    b58_seed = base58.b58encode(seed).decode("ascii")
    b58_full = base58.b58encode(kp.to_bytes()).decode("ascii")

    assert decode_keypair(b58_seed).pubkey() == kp.pubkey()
    assert decode_keypair(b58_full).pubkey() == kp.pubkey()
    # 64 bytes that are not a valid secret key: the first 32 are the seed.
    bogus = base58.b58encode(seed + b"\x00" * 32).decode("ascii")
    assert decode_keypair(bogus).pubkey() == kp.pubkey()
    # Longer than 32 (and not 64): the first 32 are the seed.
    longer = base58.b58encode(seed + b"\x01" * 8).decode("ascii")
    assert decode_keypair(longer).pubkey() == kp.pubkey()
    assert (
        load_credentials({"PUMPFUN_PRIVATE_KEY": b58_seed}).keypair().pubkey()
        == kp.pubkey()
    )
    with pytest.raises(ValueError, match="Private key must be a base58-encoded"):
        decode_keypair(base58.b58encode(b"short").decode("ascii"))


# --- Documented variables must be read (BUG-142) -----------------------------


def _source_text() -> str:
    """The package source, without the env tables themselves."""
    package = REPO / "trading_pump"
    env_py = package / "config" / "env.py"
    head, rest = env_py.read_text(encoding="utf-8").split("REPLACED_ENV_VARS: dict", 1)
    tail = rest.split("def _first", 1)[1]
    others = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package.rglob("*.py")
        if "tests" not in path.relative_to(package).parts and path != env_py
    )
    return others + head + tail


@pytest.mark.regression("BUG-142")
def test_unread_variables_are_reported_by_name_only() -> None:
    env = {
        "PUMPFUN_DRY_RUN": "true",
        "PUMPFUN_STOP_LOSS": "0.9",
        "PUMPFUN_ALERT_WEBHOOK_URL": "https://discord.com/api/webhooks/1/SECRET",
        "PUMPFUN_PRESET": "  ",  # blank: not set
        "PUMPFUN_RPC_URL": "https://example.invalid",  # read
        "PUMPFUN_SOMETHING_NEW": "1",
        "OTHER_VARIABLE": "x",
    }
    warnings = unread_env_warnings(env)

    assert [w.split(" ")[0] for w in warnings] == [
        "PUMPFUN_ALERT_WEBHOOK_URL",
        "PUMPFUN_DRY_RUN",
        "PUMPFUN_SOMETHING_NEW",
        "PUMPFUN_STOP_LOSS",
    ]
    assert "TRADING_CORE_ALERT_" in warnings[0]
    assert "not read by trading-pump" in warnings[2]
    assert not any("SECRET" in w for w in warnings)


def test_unread_env_warnings_reads_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUMPFUN_GEYSER_ENDPOINT", "grpc.example:443")

    assert unread_env_warnings() == [
        "PUMPFUN_GEYSER_ENDPOINT is set but not read: a pumpbot feature that was "
        "not ported (docs/dev/TODO.md, Not ported)"
    ]


@pytest.mark.regression("BUG-142")
def test_every_listed_variable_is_read_and_no_replaced_one_is() -> None:
    source = _source_text()
    for name in known_env_names():
        assert re.search(rf"[\"']{name}[\"']", source), name
    read = [n for n in REPLACED_ENV_VARS if re.search(rf"[\"']{n}[\"']", source)]
    assert read == [], "now read by the code: drop them from REPLACED_ENV_VARS"
    assert not set(REPLACED_ENV_VARS) & known_env_names()


@pytest.mark.regression("BUG-142")
def test_the_manual_lists_exactly_the_variables_that_are_read() -> None:
    manual = (REPO / "docs" / "ENVIRONMENT.md").read_text(encoding="utf-8")
    table = manual.split("## 1.")[1].split("## 2.")[0]
    documented = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)`", table, re.MULTILINE))
    assert documented == set(MODULE_ENV_VARS)
    for name, (aliases, _) in MODULE_ENV_VARS.items():
        row = next(line for line in table.splitlines() if f"| `{name}`" in line)
        for alias in aliases:
            assert f"`{alias}`" in row, (name, alias)


def test_every_variable_the_old_manual_documented_has_a_hint() -> None:
    """An operator moving from pumpbot is told what replaced each variable."""
    archived = REPO / "docs" / "archive" / "pumpfun-trading"
    manual = (archived / "ENVIRONMENTAL-VARIABLES.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(PUMPFUN_[A-Z0-9_]+)`", manual))
    unhinted = sorted(documented - set(REPLACED_ENV_VARS) - known_env_names())
    assert unhinted == []
