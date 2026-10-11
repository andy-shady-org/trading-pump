from pumpfun_trading.config.env import (
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
