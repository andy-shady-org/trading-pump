"""Unit tests for ``config/settings.py``: every key checked, every level."""

from __future__ import annotations

import pytest

from trading_pump.config.settings import (
    GRADUATION_MARKET_CAP_SOL,
    CaptureSettings,
    ExecutionSettings,
    GraduationSettings,
    LaneSettings,
    PumpSettings,
    StreamSettings,
)
from trading_pump.strategies.filters import ScreeningSettings


def test_defaults_are_the_feat_73_and_feat_76_rules() -> None:
    settings = PumpSettings.from_mapping({})

    assert settings.graduation.observation_seconds == 14_400
    assert settings.graduation.fast_poll_interval_seconds == 2
    assert settings.lane.signal_after_seconds == 60
    assert settings.lane.min_ratio == 1.2
    assert settings.lane.first_market_cap_min_sol == pytest.approx(
        0.5 * GRADUATION_MARKET_CAP_SOL
    )
    assert settings.lane.screen_entries is False
    assert settings.capture.path == "data/capture.jsonl"
    assert settings.screening == ScreeningSettings()
    assert PumpSettings.from_mapping(None) == settings
    assert settings.to_dict()["lane"]["min_ratio"] == 1.2


def test_nested_values_and_comments_are_read() -> None:
    settings = PumpSettings.from_mapping(
        {
            "_comment": "ignored",
            "graduation": {"max_mints": 10, "_why": "small box"},
            "lane": {"enabled": False, "min_ratio": 1.1},
            "execution": {"slippage_bps": 300, "use_jito": True},
            "capture": {"path": None},
            "stream": {"heartbeat_seconds": 0},
            "screening": {"preset": "conservative"},
        }
    )

    assert settings.graduation.max_mints == 10
    assert settings.lane.enabled is False and settings.lane.min_ratio == 1.1
    assert settings.execution.slippage_bps == 300 and settings.execution.use_jito
    assert settings.capture.path is None
    assert settings.stream.heartbeat_seconds == 0
    assert settings.screening == ScreeningSettings.preset("conservative")


def test_a_null_section_keeps_its_defaults() -> None:
    settings = PumpSettings.from_mapping({"lane": None, "screening": None})

    assert settings.lane == LaneSettings()
    assert settings.screening == ScreeningSettings()


@pytest.mark.regression("BUG-125")
@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"lanes": {}}, "Unknown module_settings keys: lanes"),
        ({"lane": {"ratio": 1.2}}, "Unknown lane keys: ratio"),
        ({"graduation": {"seconds": 1}}, "Unknown graduation keys: seconds"),
        ({"screening": {"max_gini": 0.9}}, "Unknown screening keys: max_gini"),
        ({"lane": 5}, "lane must be an object"),
        ({"screening": 5}, "screening must be an object"),
    ],
)
def test_unknown_keys_and_bad_shapes_are_refused(data: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PumpSettings.from_mapping(data)


def test_module_settings_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="module_settings must be an object"):
        PumpSettings.from_mapping(5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "values", "message"),
    [
        (GraduationSettings, {"max_mints": 0}, "max_mints must be positive"),
        (GraduationSettings, {"fast_seconds": -1}, "fast_seconds must not be negative"),
        (LaneSettings, {"min_ratio": 0}, "min_ratio must be positive"),
        (LaneSettings, {"min_ratio": True}, "min_ratio must be positive"),
        (LaneSettings, {"min_pool_sol": -1}, "min_pool_sol must not be negative"),
        (
            LaneSettings,
            {"first_market_cap_min_sol": 10, "first_market_cap_max_sol": 5},
            "first_market_cap_max_sol must be >= the minimum",
        ),
        (ExecutionSettings, {"slippage_bps": -1}, "slippage_bps must not be negative"),
        (
            ExecutionSettings,
            {"slippage_bps": True},
            "slippage_bps must not be negative",
        ),
        (ExecutionSettings, {"slippage_bps": 10_000}, "below 10000"),
        (ExecutionSettings, {"fee_bps_floor": 10_000}, "below 10000"),
        (ExecutionSettings, {"quote_max_age_seconds": 0}, "must be positive"),
        (CaptureSettings, {"max_files": -1}, "max_files must not be negative"),
        (CaptureSettings, {"flush_interval_seconds": 0}, "must be positive"),
        (StreamSettings, {"reconnect_delay_seconds": 0}, "must be positive"),
        (StreamSettings, {"idle_timeout_seconds": -1}, "must not be negative"),
    ],
)
def test_each_section_validates_its_values(
    kind: type, values: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        kind(**values)
