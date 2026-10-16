"""Environment-backed configuration helpers."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

import base58
from solders.keypair import Keypair


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_float(name: str, default: float = 0.0) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def get_env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Parse comma-separated environment variable into tuple of strings."""
    value = os.getenv(name)
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def mask_secret(value: str | None, *, hidden: str = "********") -> str:
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return hidden
    return f"{value[:4]}...{value[-2:]}"


def decode_keypair(private_key_b58: str) -> Keypair:
    """Decode a base58-encoded string into a solders Keypair."""
    decoded = base58.b58decode(private_key_b58.strip())
    if len(decoded) == 32:
        return Keypair.from_seed(decoded)
    if len(decoded) == 64:
        try:
            return Keypair.from_bytes(decoded)
        except Exception:
            return Keypair.from_seed(decoded[:32])
    if len(decoded) >= 32:
        return Keypair.from_seed(decoded[:32])
    raise ValueError(
        "Private key must be a base58-encoded Solana 32-byte seed or 64-byte secret key; "
        f"got {len(decoded)} bytes after decoding."
    )


def load_keypair_from_env(
    env_var: str | None = None,
) -> Keypair | None:
    """Load and decode a Keypair from environment variables (e.g. PUMPFUN_PRIVATE_KEY or SOLANA_PRIVATE_KEY)."""
    raw_key: str | None = None
    if env_var:
        raw_key = os.getenv(env_var)
    else:
        raw_key = os.getenv("PUMPFUN_PRIVATE_KEY") or os.getenv("SOLANA_PRIVATE_KEY")

    if not raw_key or not raw_key.strip():
        return None
    return decode_keypair(raw_key.strip())


def get_runtime_env(**overrides: Any) -> dict[str, Any]:
    """Return the environment-backed settings for bot startup."""
    return {
        "PUMPFUN_PRIVATE_KEY": os.getenv("PUMPFUN_PRIVATE_KEY")
        or os.getenv("SOLANA_PRIVATE_KEY"),
        "PUMPFUN_RPC_URL": os.getenv("PUMPFUN_RPC_URL") or os.getenv("HELIUS_RPC_URL"),
        "PUMPFUN_RPC_URLS": os.getenv("PUMPFUN_RPC_URLS")
        or os.getenv("SOLANA_RPC_URLS"),
        "PUMPFUN_STREAM_URL": os.getenv("PUMPFUN_STREAM_URL")
        or os.getenv("PUMPFUN_WS_URL"),
        "PUMPFUN_GEYSER_ENDPOINT": os.getenv("PUMPFUN_GEYSER_ENDPOINT"),
        "PUMPFUN_GEYSER_X_TOKEN": os.getenv("PUMPFUN_GEYSER_X_TOKEN")
        or os.getenv("PUMPFUN_GEYSER_TOKEN"),
        "PUMPFUN_ALERT_PROVIDER": os.getenv("PUMPFUN_ALERT_PROVIDER"),
        # Primary names per docs, with legacy aliases (BUG-87).
        "PUMPFUN_AUDIT_LOG_PATH": os.getenv("PUMPFUN_AUDIT_LOG_PATH")
        or os.getenv("PUMPFUN_AUDIT_LOG"),
        "PUMPFUN_STATUS_PATH": os.getenv("PUMPFUN_STATUS_PATH")
        or os.getenv("PUMPFUN_BOT_STATUS_PATH"),
        "PUMPFUN_REPLAY_LOG_PATH": os.getenv("PUMPFUN_REPLAY_LOG_PATH"),
        "PUMPFUN_RECORD_REPLAY": os.getenv("PUMPFUN_RECORD_REPLAY"),
        "PUMPFUN_DRAWDOWN_MODE": os.getenv("PUMPFUN_DRAWDOWN_MODE"),
        "PUMPFUN_PROFIT_RATCHET_RATIO": os.getenv("PUMPFUN_PROFIT_RATCHET_RATIO"),
        "PUMPFUN_PROFIT_DRAWDOWN_TOLERANCE_PCT": os.getenv(
            "PUMPFUN_PROFIT_DRAWDOWN_TOLERANCE_PCT"
        ),
        "PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS": os.getenv(
            "PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS"
        ),
        "PUMPFUN_EVENT_LOG_PATH": os.getenv("PUMPFUN_EVENT_LOG_PATH"),
        "PUMPFUN_EVENT_SUBSYSTEMS": os.getenv("PUMPFUN_EVENT_SUBSYSTEMS"),
        "PUMPFUN_LOG_MAX_BYTES": os.getenv("PUMPFUN_LOG_MAX_BYTES"),
        "PUMPFUN_LOG_BACKUP_COUNT": os.getenv("PUMPFUN_LOG_BACKUP_COUNT"),
        "PUMPFUN_LOG_ROTATION_TYPE": os.getenv("PUMPFUN_LOG_ROTATION_TYPE"),
        "PUMPFUN_LOG_COMPRESS": os.getenv("PUMPFUN_LOG_COMPRESS"),
        "PUMPFUN_AUDIT_MAX_BYTES": os.getenv("PUMPFUN_AUDIT_MAX_BYTES"),
        "PUMPFUN_AUDIT_BACKUP_COUNT": os.getenv("PUMPFUN_AUDIT_BACKUP_COUNT"),
        "PUMPFUN_AUDIT_RETENTION_DAYS": os.getenv("PUMPFUN_AUDIT_RETENTION_DAYS"),
        "PUMPFUN_AUDIT_COMPRESS": os.getenv("PUMPFUN_AUDIT_COMPRESS"),
        "PUMPFUN_REPLAY_MAX_BYTES": os.getenv("PUMPFUN_REPLAY_MAX_BYTES"),
        "PUMPFUN_REPLAY_BACKUP_COUNT": os.getenv("PUMPFUN_REPLAY_BACKUP_COUNT"),
        "PUMPFUN_REPLAY_RETENTION_DAYS": os.getenv("PUMPFUN_REPLAY_RETENTION_DAYS"),
        "PUMPFUN_REPLAY_COMPRESS": os.getenv("PUMPFUN_REPLAY_COMPRESS"),
        "PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS": os.getenv(
            "PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS"
        ),
        "PUMPFUN_DYNAMIC_SLIPPAGE_ENABLED": os.getenv(
            "PUMPFUN_DYNAMIC_SLIPPAGE_ENABLED"
        )
        or os.getenv("PUMPFUN_ENABLE_DYNAMIC_SLIPPAGE"),
        "PUMPFUN_MIN_SLIPPAGE_BPS": os.getenv("PUMPFUN_MIN_SLIPPAGE_BPS"),
        "PUMPFUN_MAX_SLIPPAGE_BPS": os.getenv("PUMPFUN_MAX_SLIPPAGE_BPS"),
        "PUMPFUN_MAX_EXIT_SLIPPAGE_BPS": os.getenv("PUMPFUN_MAX_EXIT_SLIPPAGE_BPS"),
        "PUMPFUN_PRIORITY_FEE_MODE": os.getenv("PUMPFUN_PRIORITY_FEE_MODE"),
        "PUMPFUN_CAPITAL_ROTATION_ENABLED": os.getenv(
            "PUMPFUN_CAPITAL_ROTATION_ENABLED"
        )
        or os.getenv("PUMPFUN_ENABLE_CAPITAL_ROTATION"),
        "PUMPFUN_DISPLACEMENT_MIN_CONVICTION_PERCENTILE": os.getenv(
            "PUMPFUN_DISPLACEMENT_MIN_CONVICTION_PERCENTILE"
        ),
        "PUMPFUN_DISPLACEMENT_HURDLE_RATE_PCT": os.getenv(
            "PUMPFUN_DISPLACEMENT_HURDLE_RATE_PCT"
        ),
        "PUMPFUN_PRE_GRADUATION_ENABLED": os.getenv("PUMPFUN_PRE_GRADUATION_ENABLED")
        or os.getenv("PUMPFUN_ENABLE_PRE_GRADUATION_HARVESTING"),
        "PUMPFUN_PRE_GRADUATION_ENTRY_PROGRESS_PCT": os.getenv(
            "PUMPFUN_PRE_GRADUATION_ENTRY_PROGRESS_PCT"
        ),
        "PUMPFUN_CLUSTER_ANALYSIS_ENABLED": os.getenv(
            "PUMPFUN_CLUSTER_ANALYSIS_ENABLED"
        )
        or os.getenv("PUMPFUN_ENABLE_CLUSTER_ANALYSIS"),
        "PUMPFUN_MAX_CLUSTER_CONCENTRATION_PCT": os.getenv(
            "PUMPFUN_MAX_CLUSTER_CONCENTRATION_PCT"
        ),
        "PUMPFUN_MAX_SINGLE_CLUSTER_PCT": os.getenv("PUMPFUN_MAX_SINGLE_CLUSTER_PCT"),
        "PUMPFUN_MAX_SYBIL_WASH_RATIO": os.getenv("PUMPFUN_MAX_SYBIL_WASH_RATIO"),
        "PUMPFUN_CLUSTER_TRACE_DEPTH": os.getenv("PUMPFUN_CLUSTER_TRACE_DEPTH"),
        "PUMPFUN_ARB_ENABLED": os.getenv("PUMPFUN_ARB_ENABLED")
        or os.getenv("PUMPFUN_ENABLE_CROSS_VENUE_ARBITRAGE"),
        "PUMPFUN_ARB_BACKRUNNING_ENABLED": os.getenv("PUMPFUN_ARB_BACKRUNNING_ENABLED")
        or os.getenv("PUMPFUN_ENABLE_MEMPOOL_BACKRUNNING"),
        "PUMPFUN_ARB_MIN_PROFIT_SOL": os.getenv("PUMPFUN_ARB_MIN_PROFIT_SOL"),
        "PUMPFUN_ARB_MIN_SPREAD_PCT": os.getenv("PUMPFUN_ARB_MIN_SPREAD_PCT"),
        "PUMPFUN_ARB_MAX_INPUT_SOL": os.getenv("PUMPFUN_ARB_MAX_INPUT_SOL"),
        "PUMPFUN_ARB_MIN_INPUT_SOL": os.getenv("PUMPFUN_ARB_MIN_INPUT_SOL"),
        "PUMPFUN_ARB_JITO_TIP_SHARE_PCT": os.getenv("PUMPFUN_ARB_JITO_TIP_SHARE_PCT"),
    } | overrides


def sanitize_env_for_logging() -> dict[str, Any]:
    """Return environment values with sensitive secrets masked."""
    masked: dict[str, Any] = {}
    for key, value in get_runtime_env().items():
        if value is None:
            masked[key] = None
            continue
        if any(token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "WEBHOOK")):
            masked[key] = mask_secret(str(value))
        else:
            masked[key] = value
    return masked


def validate_required_runtime_env(
    required: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Ensure required runtime env vars are configured before startup."""
    env = get_runtime_env()
    names = list(required or ("PUMPFUN_PRIVATE_KEY", "PUMPFUN_RPC_URL"))
    missing: list[str] = []
    for name in names:
        if name == "PUMPFUN_RPC_URL":
            if not env.get("PUMPFUN_RPC_URL") and not env.get("PUMPFUN_RPC_URLS"):
                missing.append(name)
        elif not env.get(name):
            missing.append(name)

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )
    return env


__all__ = [
    "decode_keypair",
    "get_env_bool",
    "get_env_float",
    "get_env_int",
    "get_env_list",
    "get_runtime_env",
    "load_keypair_from_env",
    "mask_secret",
    "sanitize_env_for_logging",
    "validate_required_runtime_env",
]
