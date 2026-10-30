"""Unit tests for ``config/settings.py``: every key checked, every level."""

from __future__ import annotations

import pytest
from trading_core.strategy.exits import ExitRules

from trading_pump.config.settings import (
    GRADUATION_MARKET_CAP_SOL,
    CaptureSettings,
    ExecutionSettings,
    GraduationSettings,
    InstantLaneSettings,
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
        (LaneSettings, {"max_ratio": -1}, "max_ratio must not be negative"),
        (LaneSettings, {"max_ratio": 1.1}, "max_ratio must be above min_ratio"),
        (
            LaneSettings,
            {"first_pool_min_sol": 10, "first_pool_max_sol": 5},
            "first_pool_max_sol must be >= the minimum",
        ),
        (LaneSettings, {"slippage_bps": 10_000}, "slippage_bps must be within"),
        (LaneSettings, {"slippage_bps": -1}, "slippage_bps must be within"),
        (LaneSettings, {"exits": 5}, "exits must be an object"),
        (LaneSettings, {"exits": {"stop": 1}}, "Unknown exit rule keys: stop"),
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


def test_lane_exits_are_read_from_an_object() -> None:
    settings = PumpSettings.from_mapping(
        {"lane": {"exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.15}}}
    )
    assert settings.lane.exits == ExitRules(take_profit_pct=0.5, stop_loss_pct=0.15)
    assert LaneSettings().exits == ExitRules() and not LaneSettings().exits.any_enabled
    assert settings.to_dict()["lane"]["exits"]["take_profit_pct"] == 0.5


def test_the_instant_lane_is_off_with_the_replayed_rule_as_its_defaults() -> None:
    instant = PumpSettings.from_mapping({}).instant
    assert isinstance(instant, InstantLaneSettings) and instant.enabled is False
    assert (instant.min_ratio, instant.max_ratio) == (1.0, 1.10)
    assert instant.market_cap_band() == (1_000.0, 2_000.0)
    assert (instant.first_pool_min_sol, instant.first_pool_max_sol) == (130.0, 200.0)
    assert instant.exits == ExitRules(
        stop_loss_pct=0.15, take_profit_pct=0.50, max_hold_seconds=1800.0
    )
    assert PumpSettings.from_mapping({}).enabled_lanes() == [
        ("lane", PumpSettings().lane)
    ]


@pytest.mark.parametrize(
    ("cap", "pool", "accepted"),
    [
        (1_200.0, 145.0, True),
        (999.0, 145.0, False),
        (2_001.0, 145.0, False),
        (1_200.0, 129.0, False),
        (1_200.0, 201.0, False),
    ],
)
def test_a_lane_accepts_a_first_reading_inside_its_bands(
    cap: float, pool: float, accepted: bool
) -> None:
    assert InstantLaneSettings().accepts_first(cap, pool) is accepted
    # No pool ceiling when first_pool_max_sol is 0.
    assert LaneSettings().accepts_first(410.0, 5_000.0)


def test_both_lanes_enabled_must_share_the_signal_and_not_overlap() -> None:
    both = PumpSettings.from_mapping({"instant": {"enabled": True}})
    assert [key for key, _ in both.enabled_lanes()] == ["instant", "lane"]
    with pytest.raises(ValueError, match="share signal_after_seconds"):
        PumpSettings.from_mapping(
            {"instant": {"enabled": True, "signal_after_seconds": 90}}
        )
    with pytest.raises(ValueError, match="bands overlap"):
        PumpSettings.from_mapping(
            {"instant": {"enabled": True, "first_market_cap_min_sol": 800}}
        )
    only = PumpSettings.from_mapping(
        {
            "instant": {"enabled": True, "signal_after_seconds": 90},
            "lane": {"enabled": False},
        }
    )
    assert [key for key, _ in only.enabled_lanes()] == ["instant"]
