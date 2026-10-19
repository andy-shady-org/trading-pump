"""Tests for the `TradingBot` composition root (`bot/factory.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pumpfun_trading.bot import factory
from pumpfun_trading.bot.trade_feed import PUMPPORTAL_PUBLIC_STREAM_URL
from pumpfun_trading.tests.support.factories import make_config

KEYED_URL = "wss://pumpportal.fun/api/data?api-key=secret-key"


def _resolve(**kwargs: object) -> factory.ResolvedBotConfig:
    args: dict[str, object] = {
        "config": make_config(),
        "strategy_preset": "balanced",
        "overrides": {},
        "stream_url": factory.DEFAULT_STREAM_URL,
        "api_base_url": None,
        "dry_run": False,
        "paper_trade": False,
        "verbose": True,
        "headless": False,
        "replay_log_path": None,
    }
    args.update(kwargs)
    return factory.resolve_bot_config(**args)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_rpc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLANA_RPC_URLS", raising=False)


@pytest.mark.parametrize(
    ("argument", "config_url", "env_url", "expected"),
    [
        ("wss://arg", "wss://cfg", "wss://env", "wss://arg"),
        (factory.DEFAULT_STREAM_URL, "wss://cfg", "wss://env", "wss://cfg"),
        (
            factory.DEFAULT_STREAM_URL,
            PUMPPORTAL_PUBLIC_STREAM_URL,
            "wss://env",
            "wss://env",
        ),
        (
            factory.DEFAULT_STREAM_URL,
            PUMPPORTAL_PUBLIC_STREAM_URL,
            None,
            PUMPPORTAL_PUBLIC_STREAM_URL,
        ),
        (factory.DEFAULT_STREAM_URL, None, None, factory.DEFAULT_STREAM_URL),
        (None, None, None, ""),
    ],
)
@pytest.mark.regression("BUG-117")
def test_stream_url_precedence(
    monkeypatch: pytest.MonkeyPatch,
    argument: str | None,
    config_url: str | None,
    env_url: str | None,
    expected: str,
) -> None:
    if env_url:
        monkeypatch.setenv("PUMPFUN_STREAM_URL", env_url)
    assert factory.resolve_stream_url(argument, config_url) == expected


def test_ws_url_alias_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUMPFUN_WS_URL", "wss://alias")
    assert factory.resolve_stream_url(None, None) == "wss://alias"


@pytest.mark.regression("BUG-118")
def test_embedded_stream_key_is_split_out_of_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUMPFUN_STREAM_URL", KEYED_URL)
    resolved = _resolve(config=make_config(stream_url=PUMPPORTAL_PUBLIC_STREAM_URL))
    assert "secret-key" not in resolved.config.stream_url
    assert resolved.stream_api_key == "secret-key"
    assert resolved.stream_key_in_url is True

    monkeypatch.setenv("PUMPFUN_STREAM_API_KEY", "  env-key  ")
    resolved = _resolve(config=make_config(stream_url=PUMPPORTAL_PUBLIC_STREAM_URL))
    assert resolved.stream_api_key == "env-key"


def test_resolve_bot_config_merges_flags_and_overrides(tmp_path: Path) -> None:
    resolved = _resolve(
        config=None,
        overrides={"buy_amount_sol": 0.03, "stop_loss": None},
        paper_trade=True,
        headless=True,
        verbose=False,
        api_base_url="https://api.example",
        replay_log_path=tmp_path / "r.jsonl",
    )
    cfg = resolved.config
    assert cfg.buy_amount_sol == pytest.approx(0.03)
    assert cfg.paper_trade is True and cfg.dry_run is True
    assert cfg.headless is True and cfg.verbose is False
    assert cfg.api_base_url == "https://api.example"
    assert cfg.replay_log_path == str(tmp_path / "r.jsonl")
    assert resolved.stream_api_key is None
    assert resolved.stream_key_in_url is False


def test_resolve_bot_config_accepts_dicts_and_keeps_config_replay_path() -> None:
    resolved = _resolve(config={"buy_amount_sol": 0.02})
    assert resolved.config.buy_amount_sol == pytest.approx(0.02)
    resolved = _resolve(config=make_config(replay_log_path="x.jsonl"))
    assert resolved.config.replay_log_path == "x.jsonl"
    assert _resolve(config=make_config()).config.replay_log_path is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"buy_amount_sol": 0.0}, "buy_amount_sol"),
        ({"stop_loss": 3.0, "take_profit": 2.0}, "stop_loss"),
        ({"max_active_positions": 0}, "max_active_positions"),
    ],
)
def test_invalid_configs_are_rejected(
    overrides: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory.validate_bot_config(make_config(**overrides))


def test_strategy_engines_follow_the_config() -> None:
    cfg = make_config(
        watch_max_mints=42,
        copy_trading_wallets=(
            {"address": "Wallet111111111111111111111111111111111111"},
        ),
    )
    assert factory.build_order_flow_engine(cfg).max_watch_mints == 42
    assert factory.build_graduation_engine(cfg) is not None
    assert factory.build_arbitrage_monitor(cfg) is not None
    engine = factory.build_copy_trade_engine(cfg)
    assert engine.registry.wallet_count == 1
    assert factory.build_copy_trade_engine(make_config()).registry.wallet_count == 0


def test_geyser_client_falls_back_to_the_stream_url() -> None:
    client = factory.build_geyser_client(
        endpoint=None, x_token=None, stream_url="wss://s", reconnect_delay_seconds=2.0
    )
    assert client.endpoint == "wss://s"


def test_stream_retry_budget_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert factory.stream_max_consecutive_failures() == 5
    monkeypatch.setenv("PUMPFUN_WS_MAX_RETRIES", "7")
    assert factory.stream_max_consecutive_failures() == 7
    monkeypatch.setenv("PUMPFUN_STREAM_MAX_RETRIES", "3")
    assert factory.stream_max_consecutive_failures() == 3


def test_rpc_endpoints_and_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_config(rpc_endpoints=("https://a", "https://b"))
    assert factory.resolve_rpc_endpoints(cfg, "https://single") == [
        "https://a",
        "https://b",
    ]
    assert factory.resolve_rpc_endpoints(make_config(), "https://single") == [
        "https://single"
    ]
    assert factory.resolve_rpc_endpoints(make_config(), None) == []
    monkeypatch.setenv("SOLANA_RPC_URLS", "https://x, ,https://y")
    assert factory.resolve_rpc_endpoints(make_config(), None) == [
        "https://x",
        "https://y",
    ]

    assert (
        factory.build_rpc_pool(make_config(enable_rpc_pool=False), ["https://a"])
        is None
    )
    assert factory.build_rpc_pool(make_config(enable_rpc_pool=True), []) is None
    pool = factory.build_rpc_pool(make_config(enable_rpc_pool=True), ["https://a"])
    assert pool is not None


@pytest.mark.regression("BUG-87")
def test_status_and_audit_paths_use_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PUMPFUN_STATUS_PATH",
        "PUMPFUN_BOT_STATUS_PATH",
        "PUMPFUN_AUDIT_LOG_PATH",
        "PUMPFUN_AUDIT_LOG",
    ):
        monkeypatch.delenv(name, raising=False)
    assert factory.resolve_status_path("given.json") == "given.json"
    assert factory.resolve_status_path(None) is None
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", "alias.json")
    assert factory.resolve_status_path(None) == "alias.json"
    monkeypatch.setenv("PUMPFUN_STATUS_PATH", "primary.json")
    assert factory.resolve_status_path(None) == "primary.json"

    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", "alias.jsonl")
    assert factory.resolve_audit_log_path(None) == "alias.jsonl"
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG_PATH", "primary.jsonl")
    assert factory.resolve_audit_log_path(None) == "primary.jsonl"


def test_retention_policies_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUMPFUN_AUDIT_MAX_BYTES", "123")
    monkeypatch.setenv("PUMPFUN_REPLAY_BACKUP_COUNT", "4")
    assert factory.audit_retention_policy(make_config()).max_bytes == 123
    assert factory.replay_retention_policy(make_config()).max_files == 4
    monkeypatch.setenv("PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS", "60")
    assert factory.retention_check_interval_seconds(make_config()) == 60.0


def test_persistence_writes_where_it_was_told(tmp_path: Path) -> None:
    manager = factory.build_persistence(
        bot_status_path=str(tmp_path / "s.json"),
        audit_log_path=str(tmp_path / "a.jsonl"),
        policy=factory.audit_retention_policy(make_config()),
    )
    assert manager.bot_status_path == str(tmp_path / "s.json")
    manager.close()


def test_event_logger_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    logger, path = factory.build_event_logger(
        make_config(event_log_path=str(tmp_path / "cfg.jsonl"))
    )
    assert path == str(tmp_path / "cfg.jsonl")

    monkeypatch.setenv("PUMPFUN_EVENT_LOG_PATH", str(tmp_path / "env.jsonl"))
    monkeypatch.setenv("PUMPFUN_EVENT_SUBSYSTEMS", "risk, ,execution")
    monkeypatch.setenv("PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS", "no")
    logger, path = factory.build_event_logger(make_config())
    assert path == str(tmp_path / "env.jsonl")
    assert logger.enabled is False


def test_replay_path_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = make_config()
    assert factory.resolve_replay_log_path(None, cfg) is None
    assert factory.resolve_replay_log_path("a.jsonl", cfg) == Path("a.jsonl")
    assert factory.resolve_replay_log_path(
        None, make_config(replay_log_path="c.jsonl")
    ) == Path("c.jsonl")
    monkeypatch.setenv("PUMPFUN_RECORD_REPLAY", "false")
    assert factory.resolve_replay_log_path(None, cfg) is None
    monkeypatch.setenv("PUMPFUN_RECORD_REPLAY", "true")
    assert factory.resolve_replay_log_path(None, cfg) == Path("market_replay.jsonl")
    monkeypatch.setenv("PUMPFUN_RECORD_REPLAY", "named.jsonl")
    assert factory.resolve_replay_log_path(None, cfg) == Path("named.jsonl")
    monkeypatch.setenv("PUMPFUN_REPLAY_LOG_PATH", "env.jsonl")
    assert factory.resolve_replay_log_path(None, cfg) == Path("env.jsonl")

    policy = factory.replay_retention_policy(cfg)
    assert factory.build_replay_recorder(None, policy) is None
    assert factory.build_replay_recorder(tmp_path / "r.jsonl", policy) is not None


def test_retention_managers_one_per_directory(tmp_path: Path) -> None:
    policy = factory.audit_retention_policy(make_config())
    managers = factory.build_retention_managers(
        (
            str(tmp_path / "bot.log"),
            str(tmp_path / "audit.jsonl"),
            None,
            Path("events.jsonl"),
        ),
        policy,
    )
    dirs = sorted(str(m.target_directory) for m in managers)
    assert dirs == sorted([str(tmp_path), "."])


def test_jito_flag_and_execution_client_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert factory.use_jito_from_env() is True
    monkeypatch.setenv("PUMPFUN_USE_JITO", "0")
    assert factory.use_jito_from_env() is False

    captured: dict[str, object] = {}

    def fake_build(private_key: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "client"

    monkeypatch.setattr(factory, "build_execution_client", fake_build)
    monkeypatch.setenv("PUMPFUN_JITO_TIP_LAMPORTS", "25000")
    monkeypatch.setenv("PUMPFUN_JITO_FALLBACK_TO_RPC", "no")
    client = factory.build_execution_from_env(
        "key",
        rpc_url="https://rpc",
        rpc_pool=None,
        endpoints=[],
        config=make_config(),
        use_jito=False,
    )
    assert client == "client"
    assert captured["jito_tip_lamports"] == 25000
    assert captured["jito_fallback_to_rpc"] is False
    assert captured["rpc_urls"] is None
    assert captured["use_jito"] is False
