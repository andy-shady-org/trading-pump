import asyncio

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


def test_setup_structured_logging_can_write_to_console_and_file(tmp_path):
    log_path = tmp_path / "runtime.log"
    logger = setup_structured_logging(
        logger_name="pumpfun_trading.coverage_boost",
        log_file=str(log_path),
        console=True,
    )
    assert logger.name == "pumpfun_trading.coverage_boost"
    log_runtime_event(logger, "check", component="tests", ok=True)
    assert log_path.exists()
    assert "check" in log_path.read_text(encoding="utf-8")

    log_runtime_event(logger, "caplog_check", component="tests", ok=False)
    assert "caplog_check" in log_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_market_data_service_fallback_and_resilience_paths():
    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def get_coin(self, mint: str):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")
            return {"displayName": "Recovered Token", "marketCapSol": 21.5}

        async def get_coin_info(self, mint: str):
            return {"displayName": "Recovered Token"}

    service = MarketDataService(AsyncClient())
    assert await service.get_market_cap_sol({"market_cap": "8.25"}) == 8.25
    assert await service.get_market_cap_sol({}) == 30.0
    assert await service.get_token_name({"name": "  Token  "}) == "Token"
    assert await service.get_token_name({}) is None

    fallback_result = await service.fetch_with_fallback(
        [("get_coin", [("mint", "abc")]), ("get_coin_info", [("mint", "abc")])],
        timeout=0.1,
        fallback_value={"name": "fallback"},
    )
    assert fallback_result == {"displayName": "Recovered Token"}

    resilience = ResilienceState()
    resilience.record_failure("temporary")
    assert resilience.last_error == "temporary"
    assert resilience.consecutive_failures == 1
    resilience.record_success()
    assert resilience.last_error is None
    assert resilience.consecutive_failures == 0

    assert (
        service.is_data_fresh(
            last_seen_at=asyncio.get_running_loop().time(), max_age_seconds=0
        )
        is False
    )
    assert service.is_data_fresh(last_seen_at=None, max_age_seconds=30) is False


def test_market_data_service_handles_missing_client_and_invalid_data():
    service = MarketDataService(api_client=None)
    assert await_async(
        service.fetch_with_fallback([], fallback_value={"name": "fallback"})
    ) == {"name": "fallback"}

    class BrokenClient:
        async def nope(self):
            return {}

    broken = MarketDataService(BrokenClient())
    assert await_async(
        broken.fetch_with_fallback(
            [("missing_method", None)],
            fallback_value={"name": "fallback"},
        )
    ) == {"name": "fallback"}

    assert await_async(service.get_market_cap_sol({"marketCapSol": "bad"})) == 30.0
    assert await_async(service.get_token_name({"tokenName": "  "})) is None


def await_async(coro):
    return asyncio.run(coro)
