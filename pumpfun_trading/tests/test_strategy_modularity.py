import json

import pytest

from pumpfun_trading.config.env import (
    get_env_bool,
    get_env_float,
    get_env_int,
    mask_secret,
    sanitize_env_for_logging,
    validate_required_runtime_env,
)
from pumpfun_trading.ops.logging import log_runtime_event, setup_structured_logging
from pumpfun_trading.services.market_data import MarketDataService, ResilienceState
from pumpfun_trading.strategies import TradingBotConfig, TradingStrategy
from pumpfun_trading.strategies.exits import should_exit_position
from pumpfun_trading.strategies.filters import token_is_eligible
from pumpfun_trading.strategies.presets import resolve_strategy_config
from pumpfun_trading.strategies.risk_validation import validate_risk_limits
from pumpfun_trading.strategies.signal import generate_buy_signal


def test_generate_buy_signal_and_filters():
    config = TradingBotConfig(
        max_active_positions=2,
        min_market_cap_sol=5.0,
        max_buy_attempts_per_mint=3,
    )
    assert generate_buy_signal(
        config,
        market_cap_sol=10.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert token_is_eligible(
        config,
        market_cap_sol=10.0,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert not token_is_eligible(
        config,
        market_cap_sol=2.0,
        mint_seen_recently=False,
        buy_attempts=1,
    )


def test_validate_risk_limits_and_exit_logic():
    config = TradingBotConfig(max_active_positions=2, reserve_balance_sol=0.1)
    assert validate_risk_limits(
        config,
        current_positions={"a": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert not validate_risk_limits(
        config,
        current_positions={"a": {}, "b": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert not validate_risk_limits(
        config,
        current_positions={"a": {}},
        proposed_entry_sol=0.15,
        wallet_balance_sol=0.15,
    )
    assert should_exit_position(config, performance=1.8, token_balance=2)
    assert not should_exit_position(config, performance=1.0, token_balance=0)


def test_trading_strategy_uses_modular_components():
    strategy = TradingStrategy(
        TradingBotConfig(
            max_active_positions=2,
            min_market_cap_sol=5.0,
            max_buy_attempts_per_mint=3,
            reserve_balance_sol=0.1,
        )
    )
    assert strategy.should_buy(
        market_cap_sol=10.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert strategy.validate_risk(
        current_positions={"a": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert strategy.should_sell(performance=1.8, token_balance=2)


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
        logger_name="pumpfun_trading.coverage_test",
        log_file=str(tmp_path / "audit.log"),
        console=False,
    )
    log_runtime_event(logger, "coverage_check", component="tests", ok=True)
    assert (tmp_path / "audit.log").exists()


@pytest.mark.asyncio
async def test_market_data_service_handles_failures_and_fallbacks():
    class FakeClient:
        async def get_coin(self, mint: str):
            return {"displayName": "  Alpha  ", "marketCapSol": 12.5}

        async def get_coin_info(self, mint: str):
            return {"displayName": "Alpha"}

        async def flaky(self, mint: str):
            raise RuntimeError("temporary failure")

    service = MarketDataService(FakeClient())
    assert await service.get_market_cap_sol({"marketCap": 7.25}) == 7.25
    assert await service.get_market_cap_sol({"market_cap_sol": "9.5"}) == 9.5
    assert await service.get_token_name({"tokenName": " Beta "}) == "Beta"
    assert await service.get_token_name({}) is None
    assert await service.fetch_with_fallback(
        [("flaky", [("mint", "abc")])],
        timeout=0.1,
        fallback_value={"name": "fallback"},
    ) == {"name": "fallback"}
    assert service.is_data_fresh(last_seen_at=0.0, max_age_seconds=1) is False
    assert service.is_data_fresh(last_seen_at=0.0, max_age_seconds=0) is False

    resilience = ResilienceState()
    resilience.record_failure("temporary")
    assert resilience.consecutive_failures == 1
    resilience.record_success()
    assert resilience.last_error is None


def test_strategy_config_round_trip_from_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "strategy_preset": "aggressive",
                "buy_amount_sol": 0.02,
                "paper_trade": True,
                "max_active_positions": 2,
            }
        ),
        encoding="utf-8",
    )

    config = TradingBotConfig.from_file(config_path)
    payload = config.to_dict()
    assert config.strategy_preset == "aggressive"
    assert payload["paper_trade"] is True
    assert payload["buy_amount_sol"] == 0.02


def test_strategy_preset_validation_and_fallbacks():
    config = resolve_strategy_config("balanced")
    assert config.strategy_preset == "balanced"
    assert resolve_strategy_config("unknown").strategy_preset == "balanced"

    overridden = resolve_strategy_config(
        "balanced",
        overrides={"max_active_positions": 2, "take_profit": 1.8, "stop_loss": 0.75},
    )
    assert overridden.max_active_positions == 2
    assert overridden.take_profit == 1.8

    with pytest.raises(ValueError, match="greater than zero"):
        resolve_strategy_config("balanced", overrides={"buy_amount_sol": 0})

    with pytest.raises(ValueError, match="less than take_profit"):
        resolve_strategy_config(
            "balanced",
            overrides={"take_profit": 1.2, "stop_loss": 1.3},
        )

    with pytest.raises(ValueError, match="at least 1"):
        resolve_strategy_config("balanced", overrides={"max_active_positions": 0})
