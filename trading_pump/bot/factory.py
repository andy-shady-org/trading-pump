"""Composition root for `TradingBot`: config resolution and component wiring.

Everything here builds an object from the config and the environment and has
no runtime behaviour of its own. `TradingBot.__init__` (`bot/run.py`) calls
these builders and keeps only the wiring between the results.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from trading_pump.bot.persistence import StatusPersistenceManager
from trading_pump.bot.recorder import ReplayRecorder
from trading_pump.bot.strategy import (
    CopyTradeEngine,
    CrossVenueDisparityMonitor,
    GraduationEngine,
    OrderFlowEngine,
    TradingBotConfig,
    resolve_strategy_config,
)
from trading_pump.bot.trade_feed import (
    PUMPPORTAL_PUBLIC_STREAM_URL,
    split_stream_api_key,
)
from trading_pump.config.env import (
    get_env_bool,
    get_env_int,
    resolve_bot_log_path,
)
from trading_pump.execution.builder import build_execution_client
from trading_pump.infra.rpc_pool import RpcConnectionPool, RpcPoolConfig
from trading_pump.ops.events import DiagnosticEventLogger
from trading_pump.ops.logging import setup_structured_logging
from trading_pump.ops.retention import LogRetentionManager, RetentionPolicy
from trading_pump.sdk.costs import (
    ENTRY_TIP_ENV,
    EXIT_TIP_ENV,
    side_tip_lamports_from_env,
)
from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.streams.geyser import YellowstoneGeyserClient

DEFAULT_STREAM_URL = "http://127.0.0.1:10000"
_FALSE_VALUES = {"false", "0", "no"}
_TRUE_VALUES = {"1", "true", "yes"}


@dataclass(frozen=True)
class ResolvedBotConfig:
    """The effective config plus the stream key kept out of it (BUG-118)."""

    config: TradingBotConfig
    stream_api_key: str | None
    stream_key_in_url: bool


def resolve_stream_url(argument: str | None, config_url: str | None) -> str:
    """Pick the stream URL: argument, config, env, then the default.

    Precedence (BUG-100): an explicit ``stream_url=`` argument wins, then a
    config URL, then PUMPFUN_STREAM_URL / PUMPFUN_WS_URL, then the default.
    ``pumpbot`` never passes the argument, so its order is unchanged. Preset
    configs fill in the public PumpPortal URL when the JSON has no
    ``stream_url``; that placeholder must not hide the env URL carrying the
    API key (BUG-117).
    """
    placeholder_stream_urls = {DEFAULT_STREAM_URL, PUMPPORTAL_PUBLIC_STREAM_URL}
    env_stream_url = os.getenv("PUMPFUN_STREAM_URL") or os.getenv("PUMPFUN_WS_URL")
    effective = argument
    if argument and argument != DEFAULT_STREAM_URL:
        effective = argument
    elif config_url and config_url not in placeholder_stream_urls:
        effective = config_url
    elif env_stream_url:
        effective = env_stream_url
    elif config_url:
        effective = config_url
    return str(effective or "")


def resolve_bot_config(
    *,
    config: TradingBotConfig | Mapping[str, Any] | None,
    strategy_preset: str,
    overrides: Mapping[str, Any],
    stream_url: str | None,
    api_base_url: str | None,
    dry_run: bool,
    paper_trade: bool,
    verbose: bool,
    headless: bool,
    replay_log_path: str | Path | None,
) -> ResolvedBotConfig:
    """Merge preset, config and constructor arguments; validate the result."""
    resolved = resolve_strategy_config(
        strategy_preset,
        overrides={key: value for key, value in overrides.items() if value is not None},
    )
    base: Any = config or resolved
    if not isinstance(base, TradingBotConfig):
        base = TradingBotConfig.from_dict(base if isinstance(base, dict) else {})
    # The PumpPortal API key lives in PUMPFUN_STREAM_API_KEY, never in the
    # stream URL the bot keeps, logs and displays (BUG-118). A key still
    # embedded as ``?api-key=`` is split out and used, with a warning.
    effective_stream_url, embedded_stream_key = split_stream_api_key(
        resolve_stream_url(stream_url, base.stream_url)
    )
    stream_api_key = (
        os.getenv("PUMPFUN_STREAM_API_KEY") or ""
    ).strip() or embedded_stream_key

    effective = replace(
        base,
        dry_run=bool(base.dry_run or dry_run or paper_trade),
        paper_trade=bool(base.paper_trade or paper_trade),
        verbose=bool(base.verbose and verbose),
        headless=bool(getattr(base, "headless", False) or headless),
        stream_url=str(effective_stream_url),
        api_base_url=str(api_base_url if api_base_url else base.api_base_url),
        replay_log_path=(
            str(replay_log_path)
            if replay_log_path is not None
            else (
                str(base.replay_log_path)
                if getattr(base, "replay_log_path", None)
                else None
            )
        ),
    )
    validate_bot_config(effective)
    return ResolvedBotConfig(
        config=effective,
        stream_api_key=stream_api_key,
        stream_key_in_url=embedded_stream_key is not None,
    )


def validate_bot_config(config: TradingBotConfig) -> None:
    """Reject configs the runtime can't trade safely with."""
    if config.buy_amount_sol <= 0:
        raise ValueError("buy_amount_sol must be greater than zero.")
    if not 0 < config.stop_loss < config.take_profit:
        raise ValueError(
            "stop_loss must be less than take_profit and both must be greater than zero."
        )
    if config.max_active_positions < 1:
        raise ValueError("max_active_positions must be at least 1.")


def build_order_flow_engine(config: TradingBotConfig) -> OrderFlowEngine:
    engine = OrderFlowEngine(
        max_retention_seconds=600,
        recent_token_ttl_seconds=config.recent_token_ttl_seconds,
    )
    engine.max_watch_mints = int(getattr(config, "watch_max_mints", 300) or 300)
    return engine


def build_graduation_engine(config: TradingBotConfig) -> GraduationEngine:
    return GraduationEngine(
        target_graduation_sol=85.0,
        candidate_ttl_seconds=1800,
        pre_migration_threshold_sol=config.raydium_pre_migration_sol_threshold,
    )


def build_arbitrage_monitor(config: TradingBotConfig) -> CrossVenueDisparityMonitor:
    return CrossVenueDisparityMonitor(
        min_arbitrage_spread_pct=config.min_arbitrage_spread_pct,
        min_arbitrage_profit_sol=config.min_arbitrage_profit_sol,
        max_arbitrage_input_sol=config.max_arbitrage_input_sol,
        min_arbitrage_input_sol=config.min_arbitrage_input_sol,
        jito_tip_profit_share_pct=config.arbitrage_jito_tip_profit_share_pct,
    )


def build_copy_trade_engine(config: TradingBotConfig) -> CopyTradeEngine:
    engine = CopyTradeEngine(
        base_buy_amount_sol=config.buy_amount_sol,
        max_position_size_sol=config.max_position_size_sol,
        sizing_mode=config.copy_trading_sizing_mode,
        scale_factor=config.copy_trading_scale_factor,
        min_wallet_win_rate=config.copy_trading_min_wallet_win_rate,
        max_wallet_risk_score=config.copy_trading_max_wallet_risk_score,
        mirror_sells=config.copy_trading_mirror_sells,
        enabled=config.enable_copy_trading,
    )
    if config.copy_trading_wallets:
        engine.registry.register_wallets(list(config.copy_trading_wallets))
    return engine


def build_geyser_client(
    *,
    endpoint: str | None,
    x_token: str | None,
    stream_url: str,
    reconnect_delay_seconds: float,
) -> YellowstoneGeyserClient:
    return YellowstoneGeyserClient(
        endpoint=endpoint or stream_url,
        x_token=x_token,
        reconnect_initial_backoff=reconnect_delay_seconds,
    )


def stream_max_consecutive_failures() -> int:
    stream_retries_env = os.getenv("PUMPFUN_STREAM_MAX_RETRIES") or os.getenv(
        "PUMPFUN_WS_MAX_RETRIES", "5"
    )
    return int(stream_retries_env or "5")


def resolve_rpc_endpoints(config: TradingBotConfig, rpc_url: str | None) -> list[str]:
    """Config endpoints, else PUMPFUN_RPC_URLS / SOLANA_RPC_URLS, else `rpc_url`."""
    endpoints = list(config.rpc_endpoints)
    if not endpoints:
        env_urls = os.getenv("PUMPFUN_RPC_URLS") or os.getenv("SOLANA_RPC_URLS")
        if env_urls:
            endpoints = [u.strip() for u in env_urls.split(",") if u.strip()]
    if not endpoints and rpc_url:
        endpoints = [rpc_url]
    return endpoints


def build_rpc_pool(
    config: TradingBotConfig, endpoints: list[str]
) -> RpcConnectionPool | None:
    """Multi-RPC pool (FEAT-08), or None when disabled or no endpoint is known."""
    if not (config.enable_rpc_pool and len(endpoints) > 0):
        return None
    pool_cfg = RpcPoolConfig(
        endpoints=tuple(endpoints),
        health_check_interval_seconds=config.rpc_pool_health_check_interval_seconds,
        circuit_breaker_threshold=config.rpc_pool_circuit_breaker_threshold,
        circuit_breaker_cooldown_seconds=config.rpc_pool_circuit_breaker_cooldown_seconds,
        broadcast_concurrency=config.rpc_pool_broadcast_concurrency,
    )
    return RpcConnectionPool(endpoints=tuple(endpoints), config=pool_cfg)


def build_bot_logger(
    config: TradingBotConfig,
    *,
    log_file: str | None,
    headless: bool,
    verbose: bool,
) -> tuple[logging.Logger, str | None]:
    """Structured bot logger and the log file it writes (FEAT-22 rotation).

    In interactive terminal mode (verbose and not headless), Rich's Live
    dashboard manages the alternate screen buffer; raw console handler writes
    would reposition the cursor (BUG-29), so console logging is only on in
    headless mode or when verbose logging is off.
    """
    enable_console_logging = bool(headless or not verbose)
    effective_log_file = resolve_bot_log_path(log_file, config.log_file)
    logger = setup_structured_logging(
        logger_name="trading_pump.bot",
        log_file=effective_log_file,
        console=enable_console_logging,
        max_bytes=get_env_int("PUMPFUN_LOG_MAX_BYTES", config.log_max_bytes),
        backup_count=get_env_int("PUMPFUN_LOG_BACKUP_COUNT", config.log_backup_count),
        rotation_type=os.getenv("PUMPFUN_LOG_ROTATION_TYPE", config.log_rotation_type),
        compress=get_env_bool("PUMPFUN_LOG_COMPRESS", config.log_compress),
    )
    return logger, effective_log_file


def resolve_status_path(argument: str | None) -> str | None:
    # Primary env names with documented aliases (BUG-87).
    return (
        argument
        or os.getenv("PUMPFUN_STATUS_PATH")
        or os.getenv("PUMPFUN_BOT_STATUS_PATH")
    )


def resolve_audit_log_path(argument: str | None) -> str | None:
    return (
        argument
        or os.getenv("PUMPFUN_AUDIT_LOG_PATH")
        or os.getenv("PUMPFUN_AUDIT_LOG")
    )


def audit_retention_policy(config: TradingBotConfig) -> RetentionPolicy:
    return RetentionPolicy(
        max_bytes=get_env_int("PUMPFUN_AUDIT_MAX_BYTES", config.audit_max_bytes),
        max_files=get_env_int("PUMPFUN_AUDIT_BACKUP_COUNT", config.audit_backup_count),
        max_age_days=get_env_int(
            "PUMPFUN_AUDIT_RETENTION_DAYS", config.audit_retention_days
        ),
        compress_archives=get_env_bool("PUMPFUN_AUDIT_COMPRESS", config.audit_compress),
    )


def build_persistence(
    *,
    bot_status_path: str | None,
    audit_log_path: str | None,
    policy: RetentionPolicy,
) -> StatusPersistenceManager:
    return StatusPersistenceManager(
        bot_status_path=bot_status_path,
        audit_log_path=audit_log_path,
        policy=policy,
    )


def build_event_logger(
    config: TradingBotConfig,
) -> tuple[DiagnosticEventLogger, str]:
    """Diagnostic event logger (FEAT-30) and the path it writes."""
    event_log_path_env = os.getenv("PUMPFUN_EVENT_LOG_PATH")
    effective_event_log_path = (
        event_log_path_env
        if event_log_path_env
        else getattr(config, "event_log_path", "events.jsonl") or "events.jsonl"
    )
    subsystems_env = os.getenv("PUMPFUN_EVENT_SUBSYSTEMS")
    effective_subsystems = (
        tuple(p.strip() for p in subsystems_env.split(",") if p.strip())
        if subsystems_env
        else getattr(config, "event_log_subsystems", None)
    )
    enable_events_env = os.getenv("PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS")
    effective_enable_events = (
        enable_events_env.lower() in _TRUE_VALUES
        if enable_events_env is not None
        else getattr(config, "enable_diagnostic_events", True)
    )
    logger = DiagnosticEventLogger(
        output_path=effective_event_log_path,
        enabled_categories=effective_subsystems,
        enabled=effective_enable_events,
    )
    return logger, effective_event_log_path


def resolve_replay_log_path(
    argument: str | Path | None, config: TradingBotConfig
) -> Path | None:
    """Replay capture path: argument, config, env path, or PUMPFUN_RECORD_REPLAY."""
    resolved = (
        argument
        or getattr(config, "replay_log_path", None)
        or os.getenv("PUMPFUN_REPLAY_LOG_PATH")
    )
    if not resolved:
        rec_env = os.getenv("PUMPFUN_RECORD_REPLAY")
        if rec_env and rec_env.lower() not in _FALSE_VALUES:
            resolved = (
                rec_env
                if rec_env.lower() not in _TRUE_VALUES
                else "market_replay.jsonl"
            )
    return Path(resolved) if resolved else None


def replay_retention_policy(config: TradingBotConfig) -> RetentionPolicy:
    return RetentionPolicy(
        max_bytes=get_env_int("PUMPFUN_REPLAY_MAX_BYTES", config.replay_max_bytes),
        max_files=get_env_int(
            "PUMPFUN_REPLAY_BACKUP_COUNT", config.replay_backup_count
        ),
        max_age_days=get_env_int(
            "PUMPFUN_REPLAY_RETENTION_DAYS", config.replay_retention_days
        ),
        compress_archives=get_env_bool(
            "PUMPFUN_REPLAY_COMPRESS", config.replay_compress
        ),
    )


def build_replay_recorder(
    path: Path | None, policy: RetentionPolicy
) -> ReplayRecorder | None:
    return ReplayRecorder(output_path=path, policy=policy) if path else None


def retention_check_interval_seconds(config: TradingBotConfig) -> float:
    return float(
        os.getenv(
            "PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS",
            str(getattr(config, "retention_check_interval_seconds", 3600.0)),
        )
    )


def build_retention_managers(
    paths: Iterable[str | Path | None],
    policy: RetentionPolicy,
    per_file: Mapping[str | Path, RetentionPolicy] | None = None,
) -> list[LogRetentionManager]:
    """Pruning managers for the bot's log, audit, event and replay files.

    One manager per directory and policy, matching only the archives of the
    files it manages (``<name>*``). ``per_file`` gives a file its own policy:
    the replay capture's ``replay_backup_count`` used to be overridden by the
    audit policy, which pruned every ``*.jsonl*`` archive in the folder and
    deleted the first 14-21 h of the 37 h rc.8 captures (BUG-157).
    """
    overrides = {Path(k): v for k, v in (per_file or {}).items() if k}
    groups: dict[tuple[Path, int], tuple[RetentionPolicy, set[str]]] = {}
    for p in [*paths, *overrides]:
        if not p:
            continue
        p_path = Path(p)
        parent = p_path.parent if str(p_path.parent) != "" else Path(".")
        file_policy = overrides.get(p_path, policy)
        key = (parent, id(file_policy))
        groups.setdefault(key, (file_policy, set()))[1].add(f"{p_path.name}*")
    return [
        LogRetentionManager(
            target_directory=directory,
            policy=file_policy,
            file_patterns=tuple(sorted(patterns)),
        )
        for (directory, _), (file_policy, patterns) in groups.items()
    ]


def use_jito_from_env() -> bool:
    return os.getenv("PUMPFUN_USE_JITO", "true").lower() not in _FALSE_VALUES


def build_execution_from_env(
    private_key_b58: str,
    *,
    rpc_url: str,
    rpc_pool: RpcConnectionPool | None,
    endpoints: list[str],
    config: TradingBotConfig,
    use_jito: bool,
) -> PumpFunExecutionClient:
    """Execution client with the Jito, slippage and compute settings from env."""
    return build_execution_client(
        private_key_b58,
        rpc_url=rpc_url,
        rpc_pool=rpc_pool,
        rpc_urls=endpoints if endpoints else None,
        default_slippage_bps=int(
            os.getenv(
                "PUMPFUN_SLIPPAGE_BPS",
                str(getattr(config, "raydium_slippage_bps", 250)),
            )
        ),
        compute_unit_limit=int(os.getenv("PUMPFUN_COMPUTE_UNIT_LIMIT", "200000")),
        jito_tip_lamports=int(os.getenv("PUMPFUN_JITO_TIP_LAMPORTS", "100000")),
        # Entry/exit tip experiment: a fixed tip per side, 0 = plain RPC.
        jito_entry_tip_lamports=side_tip_lamports_from_env(ENTRY_TIP_ENV),
        jito_exit_tip_lamports=side_tip_lamports_from_env(EXIT_TIP_ENV),
        jito_block_engine_url=os.getenv(
            "PUMPFUN_JITO_BLOCK_ENGINE_URL",
            "https://mainnet.block-engine.jito.wtf",
        ),
        use_jito=use_jito,
        jito_fallback_to_rpc=os.getenv("PUMPFUN_JITO_FALLBACK_TO_RPC", "true").lower()
        not in _FALSE_VALUES,
        jito_confirmation_timeout=float(
            os.getenv("PUMPFUN_JITO_CONFIRMATION_TIMEOUT", "12.0")
        ),
    )
