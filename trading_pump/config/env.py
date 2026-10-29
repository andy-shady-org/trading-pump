"""The module's environment: credentials and endpoints, never settings.

Credentials (the wallet key, RPC URLs that carry API keys, the PumpPortal
key) come from ``PUMPFUN_*`` variables only, never from ``module_settings``:
the settings file is hashed and recorded in run provenance
(trading-core ``docs/MODULE-GUIDE.md`` §7). Everything else is a setting.

``MODULE_ENV_VARS`` is the single list of variables this package reads
(pumpfun BUG-142: 51 documented variables were read by nothing).
``unread_env_warnings`` names any other ``PUMPFUN_*`` variable that is set,
with what replaces it, so an operator moving from pumpbot sees at start-up
which of their old variables no longer do anything.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import base58
from solders.keypair import Keypair

from trading_pump.streams.websocket import split_stream_api_key, stream_connect_url

PRIVATE_KEY_ENV = "PUMPFUN_PRIVATE_KEY"
RPC_URL_ENV = "PUMPFUN_RPC_URL"
RPC_URLS_ENV = "PUMPFUN_RPC_URLS"
STREAM_URL_ENV = "PUMPFUN_STREAM_URL"
STREAM_API_KEY_ENV = "PUMPFUN_STREAM_API_KEY"
JUPITER_API_KEY_ENV = "PUMPFUN_JUPITER_API_KEY"

# name -> (legacy aliases, what it is). Read in this order: the name, then
# each alias.
MODULE_ENV_VARS: dict[str, tuple[tuple[str, ...], str]] = {
    PRIVATE_KEY_ENV: (
        ("SOLANA_PRIVATE_KEY",),
        "wallet key (base58 seed or secret key); live mode only",
    ),
    RPC_URL_ENV: (("HELIUS_RPC_URL",), "primary Solana RPC endpoint"),
    RPC_URLS_ENV: (
        ("SOLANA_RPC_URLS",),
        "comma-separated extra RPC endpoints for failover",
    ),
    STREAM_URL_ENV: (("PUMPFUN_WS_URL",), "PumpPortal WebSocket URL"),
    STREAM_API_KEY_ENV: ((), "PumpPortal API key, appended to the stream URL"),
    JUPITER_API_KEY_ENV: ((), "Jupiter API key for the quote recorder"),
}

PUMPPORTAL_URL = "wss://pumpportal.fun/api/data"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"

_ENGINE = (
    "trading-core settings / TRADING_CORE_* variables "
    "(trading-core docs/ENVIRONMENT.md)"
)
_MODULE = "a module_settings key (docs/CONFIGURATION.md)"
# pumpbot-era variables and what replaces them. Names only: some held
# webhook URLs, so a value is never echoed.
REPLACED_ENV_VARS: dict[str, str] = {
    **dict.fromkeys(
        (
            "PUMPFUN_ALERT_PROVIDER",
            "PUMPFUN_ALERT_DISCORD_WEBHOOK_URL",
            "PUMPFUN_ALERT_SLACK_WEBHOOK_URL",
            "PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN",
            "PUMPFUN_ALERT_TELEGRAM_CHAT_ID",
            "PUMPFUN_ALERT_WEBHOOK_URL",
            "PUMPFUN_TELEGRAM_BOT_TOKEN",
            "PUMPFUN_TELEGRAM_CHAT_ID",
        ),
        "alerts are the engine's: use TRADING_CORE_ALERT_* (trading-core "
        "docs/ENVIRONMENT.md)",
    ),
    **dict.fromkeys(
        (
            "PUMPFUN_AUDIT_LOG_PATH",
            "PUMPFUN_AUDIT_LOG",
            "PUMPFUN_STATUS_PATH",
            "PUMPFUN_BOT_STATUS_PATH",
            "PUMPFUN_EVENT_LOG_PATH",
            "PUMPFUN_BOT_LOG_PATH",
            "PUMPFUN_AUDIT_MAX_BYTES",
            "PUMPFUN_AUDIT_BACKUP_COUNT",
            "PUMPFUN_AUDIT_RETENTION_DAYS",
            "PUMPFUN_AUDIT_COMPRESS",
            "PUMPFUN_LOG_MAX_BYTES",
            "PUMPFUN_LOG_BACKUP_COUNT",
            "PUMPFUN_LOG_ROTATION_TYPE",
            "PUMPFUN_LOG_COMPRESS",
            "PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS",
            "PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS",
            "PUMPFUN_EVENT_SUBSYSTEMS",
            "PUMPFUN_DRAWDOWN_MODE",
            "PUMPFUN_PROFIT_RATCHET_RATIO",
            "PUMPFUN_PROFIT_DRAWDOWN_TOLERANCE_PCT",
            "PUMPFUN_MAX_DAILY_DRAWDOWN",
            "PUMPFUN_MAX_POSITIONS",
            "PUMPFUN_MAX_TOTAL_EXPOSURE_SOL",
            "PUMPFUN_STOP_LOSS",
            "PUMPFUN_TRAILING_STOP_ENABLED",
            "PUMPFUN_TRAILING_ACTIVATION_PCT",
            "PUMPFUN_TRAILING_DROP_PCT",
            "PUMPFUN_DRY_RUN",
            "PUMPFUN_CONFIG",
            "PUMPFUN_CONFIG_PATH",
        ),
        f"files, risk and exits are the engine's: use {_ENGINE}",
    ),
    **dict.fromkeys(
        (
            "PUMPFUN_REPLAY_LOG_PATH",
            "PUMPFUN_RECORD_REPLAY",
            "PUMPFUN_REPLAY_MAX_BYTES",
            "PUMPFUN_REPLAY_BACKUP_COUNT",
            "PUMPFUN_REPLAY_RETENTION_DAYS",
            "PUMPFUN_REPLAY_COMPRESS",
            "PUMPFUN_JITO_TIP_LAMPORTS",
            "PUMPFUN_JITO_ENTRY_TIP_LAMPORTS",
            "PUMPFUN_JITO_EXIT_TIP_LAMPORTS",
            "PUMPFUN_PRIORITY_FEE_MODE",
            "PUMPFUN_DYNAMIC_SLIPPAGE_ENABLED",
            "PUMPFUN_ENABLE_DYNAMIC_SLIPPAGE",
            "PUMPFUN_MIN_SLIPPAGE_BPS",
            "PUMPFUN_MAX_SLIPPAGE_BPS",
            "PUMPFUN_MAX_EXIT_SLIPPAGE_BPS",
            "PUMPFUN_CLUSTER_ANALYSIS_ENABLED",
            "PUMPFUN_ENABLE_CLUSTER_ANALYSIS",
            "PUMPFUN_MAX_CLUSTER_CONCENTRATION_PCT",
            "PUMPFUN_MAX_SINGLE_CLUSTER_PCT",
            "PUMPFUN_MAX_SYBIL_WASH_RATIO",
            "PUMPFUN_CLUSTER_TRACE_DEPTH",
            "PUMPFUN_ANTI_RUG_ENABLED",
            "PUMPFUN_MAX_CREATOR_HOLDING_PCT",
            "PUMPFUN_MAX_GINI_COEFFICIENT",
            "PUMPFUN_MAX_RISK_SCORE",
            "PUMPFUN_STRATEGY_PRESET",
            "PUMPFUN_PRESET",
            "PUMPFUN_BASE_BUY_SOL",
            "PUMPFUN_BUY_AMOUNT_SOL",
            "PUMPFUN_SLIPPAGE_BPS",
            "PUMPFUN_USE_JITO",
            "PUMPFUN_COMPUTE_UNIT_LIMIT",
        ),
        f"capture, costs and screening are settings: use {_MODULE}",
    ),
    "PUMPFUN_GIT_COMMIT": f"run provenance is the engine's: use {_ENGINE}",
    "PUMPFUN_HEADLESS": "use trading-core run --headless",
    **dict.fromkeys(
        (
            "PUMPFUN_GEYSER_ENDPOINT",
            "PUMPFUN_GEYSER_X_TOKEN",
            "PUMPFUN_GEYSER_TOKEN",
            "PUMPFUN_ARB_ENABLED",
            "PUMPFUN_ENABLE_CROSS_VENUE_ARBITRAGE",
            "PUMPFUN_ARB_BACKRUNNING_ENABLED",
            "PUMPFUN_ENABLE_MEMPOOL_BACKRUNNING",
            "PUMPFUN_ARB_MIN_PROFIT_SOL",
            "PUMPFUN_ARB_MIN_SPREAD_PCT",
            "PUMPFUN_ARB_MAX_INPUT_SOL",
            "PUMPFUN_ARB_MIN_INPUT_SOL",
            "PUMPFUN_ARB_JITO_TIP_SHARE_PCT",
            "PUMPFUN_CAPITAL_ROTATION_ENABLED",
            "PUMPFUN_ENABLE_CAPITAL_ROTATION",
            "PUMPFUN_DISPLACEMENT_MIN_CONVICTION_PERCENTILE",
            "PUMPFUN_DISPLACEMENT_HURDLE_RATE_PCT",
            "PUMPFUN_DISPLACEMENT_HURDLE_PCT",
            "PUMPFUN_DISPLACEMENT_MIN_CONVICTION",
            "PUMPFUN_MIN_HOLD_BEFORE_DISPLACEMENT",
            "PUMPFUN_PRE_GRADUATION_ENABLED",
            "PUMPFUN_ENABLE_PRE_GRADUATION_HARVESTING",
            "PUMPFUN_PRE_GRADUATION_ENTRY_PROGRESS_PCT",
            "PUMPFUN_PRE_GRAD_ENTRY_PROGRESS",
            "PUMPFUN_PRE_GRAD_MAX_ENTRY_PROGRESS",
            "PUMPFUN_COPY_TRADING_ENABLED",
            "PUMPFUN_COPY_TRADING_SCALE_FACTOR",
            "PUMPFUN_COPY_TRADING_SIZING_MODE",
            "PUMPFUN_COPY_TRADING_WALLETS",
            "PUMPFUN_MOMENTUM_ENABLED",
            "PUMPFUN_MOMENTUM_MIN_BUY_RATIO",
            "PUMPFUN_MOMENTUM_MIN_NET_INFLOW_SOL",
            "PUMPFUN_MOMENTUM_MIN_UNIQUE_BUYERS",
            "PUMPFUN_MOMENTUM_MIN_Z_SCORE",
            "PUMPFUN_RAYDIUM_BUY_SOL",
            "PUMPFUN_RAYDIUM_SLIPPAGE_BPS",
            "PUMPFUN_RAYDIUM_SNIPE_ENABLED",
            "PUMPFUN_TIERED_TP_ENABLED",
            "PUMPFUN_TIER1_TP_FRACTION",
            "PUMPFUN_TIER1_TP_MULT",
            "PUMPFUN_TIER2_TP_FRACTION",
            "PUMPFUN_TIER2_TP_MULT",
            "PUMPFUN_STAGNANT_TIMEOUT",
            "PUMPFUN_MIN_MARKET_CAP_SOL",
            "PUMPFUN_MAX_MARKET_CAP_SOL",
            "PUMPFUN_RPC_ENDPOINTS",
            "PUMPFUN_RPC_POOL_CONCURRENCY",
            "PUMPFUN_RPC_POOL_ENABLED",
            "PUMPFUN_DIAGNOSTIC_EVENTS_ENABLED",
            "PUMPFUN_EVENT_LOG_SUBSYSTEMS",
            # Live execution and the reconcile tool wait for the live gate.
            "PUMPFUN_JITO_BLOCK_ENGINE_URL",
            "PUMPFUN_JITO_CONFIRMATION_TIMEOUT",
            "PUMPFUN_JITO_FALLBACK_TO_RPC",
            "PUMPFUN_BASE_EXIT_SLIPPAGE_BPS",
            "PUMPFUN_MAX_EXIT_RETRIES",
            "PUMPFUN_RECONCILE_STATUS_PATH",
            # The migration feed reconnects for as long as the run lasts.
            "PUMPFUN_STREAM_MAX_RETRIES",
            "PUMPFUN_WS_MAX_RETRIES",
        ),
        "a pumpbot feature that was not ported (docs/dev/TODO.md, Not ported)",
    ),
}


def _first(env: Mapping[str, str], name: str) -> str | None:
    aliases, _ = MODULE_ENV_VARS[name]
    for candidate in (name, *aliases):
        value = (env.get(candidate) or "").strip()
        if value:
            return value
    return None


def known_env_names() -> frozenset[str]:
    """Every variable this package reads, aliases included."""
    names: set[str] = set()
    for name, (aliases, _) in MODULE_ENV_VARS.items():
        names.update((name, *aliases))
    return frozenset(names)


def unread_env_warnings(env: Mapping[str, str] | None = None) -> list[str]:
    """One warning per set ``PUMPFUN_*`` variable that nothing reads (BUG-142).

    Only names are reported, never values: some of these held webhook URLs.
    """
    source = os.environ if env is None else env
    known = known_env_names()
    warnings: list[str] = []
    for name in sorted(source):
        if not name.startswith("PUMPFUN_") or name in known:
            continue
        if not str(source.get(name, "")).strip():
            continue
        hint = REPLACED_ENV_VARS.get(name, "not read by trading-pump")
        warnings.append(f"{name} is set but not read: {hint}")
    return warnings


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
        "Private key must be a base58-encoded Solana 32-byte seed or 64-byte secret "
        "key; "
        f"got {len(decoded)} bytes after decoding."
    )


@dataclass(frozen=True)
class Credentials:
    """What the module reads from its environment. ``repr`` hides every value."""

    private_key: str | None = None
    rpc_urls: tuple[str, ...] = ()
    stream_url: str = PUMPPORTAL_URL
    stream_api_key: str | None = None

    def __repr__(self) -> str:
        return (
            f"Credentials(private_key={'set' if self.private_key else 'unset'}, "
            f"rpc_urls={len(self.rpc_urls)}, "
            f"stream_api_key={'set' if self.stream_api_key else 'unset'})"
        )

    @property
    def has_private_key(self) -> bool:
        return bool(self.private_key)

    @property
    def stream_display_url(self) -> str:
        """The stream URL without any API key, safe to show (BUG-118)."""
        return split_stream_api_key(self.stream_url)[0]

    @property
    def stream_key_in_url(self) -> bool:
        """``PUMPFUN_STREAM_URL`` itself carries ``api-key`` (move it out, BUG-118)."""
        return split_stream_api_key(self.stream_url)[1] is not None

    def stream_connect_url(self) -> str:
        """The URL to connect with, key added for PumpPortal only. Never log it."""
        return stream_connect_url(self.stream_url, self.stream_api_key)

    def keypair(self) -> Keypair:
        """The wallet; raises when no key is configured."""
        if not self.private_key:
            raise ValueError(f"{PRIVATE_KEY_ENV} is not set")
        return decode_keypair(self.private_key)


def load_credentials(env: Mapping[str, str] | None = None) -> Credentials:
    """Credentials from the environment (``PUMPFUN_*`` beats its alias).

    RPC endpoints: ``PUMPFUN_RPC_URL`` first, then ``PUMPFUN_RPC_URLS``; the
    public mainnet RPC only when neither is set (fine for a short paper
    test, rate-limited for a real run).
    """
    source = os.environ if env is None else env
    urls: list[str] = []
    primary = _first(source, RPC_URL_ENV)
    if primary:
        urls.append(primary)
    extra = _first(source, RPC_URLS_ENV) or ""
    for url in (part.strip() for part in extra.split(",")):
        if url and url not in urls:
            urls.append(url)
    return Credentials(
        private_key=_first(source, PRIVATE_KEY_ENV),
        rpc_urls=tuple(urls) or (PUBLIC_RPC_URL,),
        stream_url=_first(source, STREAM_URL_ENV) or PUMPPORTAL_URL,
        stream_api_key=_first(source, STREAM_API_KEY_ENV),
    )


__all__ = [
    "Credentials",
    "JUPITER_API_KEY_ENV",
    "MODULE_ENV_VARS",
    "PRIVATE_KEY_ENV",
    "PUBLIC_RPC_URL",
    "PUMPPORTAL_URL",
    "REPLACED_ENV_VARS",
    "RPC_URLS_ENV",
    "RPC_URL_ENV",
    "STREAM_API_KEY_ENV",
    "STREAM_URL_ENV",
    "decode_keypair",
    "known_env_names",
    "load_credentials",
    "unread_env_warnings",
]
