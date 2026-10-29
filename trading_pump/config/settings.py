"""``PumpSettings``: the module's ``module_settings``, validated.

The engine passes the settings file's ``module_settings`` object to
:class:`~trading_pump.module.PumpModule` as keyword arguments. Every key is
checked: an unknown key is an error at every level, never a silent default
(pumpfun BUG-125). Amounts are SOL, times are seconds.

Example (``configs/paper.example.json``)::

    "module_settings": {
      "graduation": {"observation_seconds": 14400, "fast_seconds": 300},
      "lane": {"signal_after_seconds": 60, "min_ratio": 1.2},
      "execution": {"slippage_bps": 500},
      "capture": {"path": "data/capture.jsonl"}
    }

Credentials never go here (docs/ENVIRONMENT.md): the settings are hashed
into the run provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

from trading_pump.strategies.filters import ScreeningSettings

# Market cap (SOL) of a curve that has just completed: 85 SOL real plus the
# 30 SOL virtual reserve against ~279M tokens left, times 1B tokens. The rc.8
# read-out measured graduations against it (STRATEGY-PIVOT.md §6.13).
GRADUATION_MARKET_CAP_SOL = 410.88

T = TypeVar("T")


def _clean(data: Mapping[str, Any] | None, *, where: str, kind: type) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ValueError(f"{where} must be an object")
    values = {k: v for k, v in data.items() if not str(k).startswith("_")}
    known = {item.name for item in fields(kind)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"Unknown {where} keys: {', '.join(unknown)}")
    return values


def _positive(owner: object, *names: str) -> None:
    for name in names:
        value = getattr(owner, name)
        if isinstance(value, bool) or not float(value) > 0:
            raise ValueError(f"{type(owner).__name__}.{name} must be positive")


def _not_negative(owner: object, *names: str) -> None:
    for name in names:
        value = getattr(owner, name)
        if isinstance(value, bool) or float(value) < 0:
            raise ValueError(f"{type(owner).__name__}.{name} must not be negative")


@dataclass(frozen=True)
class GraduationSettings:
    """Graduation tracking (FEAT-73): every migrated coin's PumpSwap pool.

    Each pool is read every ``fast_poll_interval_seconds`` for its first
    ``fast_seconds``, then every ``poll_interval_seconds`` until
    ``observation_seconds`` after the migration. At most ``max_mints`` pools
    are followed at once (a full list never evicts, so every observation runs
    its course). The lane reads the same rows.
    """

    observation_seconds: float = 14_400.0
    max_mints: int = 500
    poll_interval_seconds: float = 10.0
    fast_seconds: float = 300.0
    fast_poll_interval_seconds: float = 2.0
    # A lagging RPC node may not have the pool yet when the event arrives.
    pool_missing_grace_seconds: float = 60.0

    def __post_init__(self) -> None:
        _positive(
            self,
            "observation_seconds",
            "max_mints",
            "poll_interval_seconds",
            "fast_poll_interval_seconds",
        )
        _not_negative(self, "fast_seconds", "pool_missing_grace_seconds")


@dataclass(frozen=True)
class LaneSettings:
    """The ``pumpswap_momentum`` lane (FEAT-76).

    One decision per graduate, at the first pool reading at least
    ``signal_after_seconds`` after the migration: buy when that price is at
    least ``min_ratio`` times the first reading after the migration and the
    first reading looks like a standard graduation (market cap between
    ``first_market_cap_min_sol`` and ``first_market_cap_max_sol``, 0.5-2x of
    410.88 SOL by default: about 60% of PumpPortal's migration events are
    empty or unrelated pools). A reading later than ``signal_window_seconds``
    past the signal time is too late: no decision is made on it.
    """

    enabled: bool = True
    signal_after_seconds: float = 60.0
    signal_window_seconds: float = 30.0
    min_ratio: float = 1.2
    first_market_cap_min_sol: float = 0.5 * GRADUATION_MARKET_CAP_SOL
    first_market_cap_max_sol: float = 2.0 * GRADUATION_MARKET_CAP_SOL
    min_pool_sol: float = 0.0
    screen_entries: bool = False

    def __post_init__(self) -> None:
        _positive(self, "signal_after_seconds", "signal_window_seconds", "min_ratio")
        _not_negative(
            self, "first_market_cap_min_sol", "first_market_cap_max_sol", "min_pool_sol"
        )
        if self.first_market_cap_max_sol < self.first_market_cap_min_sol:
            raise ValueError(
                "LaneSettings.first_market_cap_max_sol must be >= the minimum"
            )


@dataclass(frozen=True)
class ExecutionSettings:
    """How paper fills are priced and what a trade is modelled to cost.

    A buy is refused when its fill price is more than ``slippage_bps`` above
    the signal price. Fees: the pool's fee tier from the PumpSwap fee config
    when it can be read, else the AMM ``global_config`` total; never below
    ``fee_bps_floor``. ``paper_entry_delay_seconds`` waits before a paper buy
    reads the pool, to model the latency a live buy pays.
    """

    slippage_bps: int = 500
    fee_bps_floor: int = 0
    priority_fee_lamports: int = 5_000
    compute_unit_limit: int = 200_000
    use_jito: bool = False
    jito_tip_lamports: int = 0
    paper_entry_delay_seconds: float = 0.0
    quote_max_age_seconds: float = 15.0
    rpc_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        _not_negative(
            self,
            "slippage_bps",
            "fee_bps_floor",
            "priority_fee_lamports",
            "jito_tip_lamports",
            "paper_entry_delay_seconds",
        )
        _positive(
            self, "compute_unit_limit", "quote_max_age_seconds", "rpc_timeout_seconds"
        )
        if int(self.slippage_bps) >= 10_000 or int(self.fee_bps_floor) >= 10_000:
            raise ValueError("ExecutionSettings basis points must be below 10000")


@dataclass(frozen=True)
class CaptureSettings:
    """The capture file: every migration and pool reading (record-only).

    Rows have pumpfun-trading's capture shape (``observation_start``,
    ``curve_poll``, ``observation_end``, ``migration``), so its read-out
    scripts work on it. It is rotated and pruned by its own policy, never by
    another file's (BUG-157). ``path`` null turns it off.
    """

    path: str | None = "data/capture.jsonl"
    max_bytes: int = 50 * 1024 * 1024
    max_files: int = 20
    max_age_days: int = 30
    compress: bool = True
    flush_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        _not_negative(self, "max_bytes", "max_files", "max_age_days")
        _positive(self, "flush_interval_seconds")


@dataclass(frozen=True)
class StreamSettings:
    """PumpPortal WebSocket timing (BUG-150): pings and the idle reconnect."""

    reconnect_delay_seconds: float = 1.0
    heartbeat_seconds: float = 20.0
    idle_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        _positive(self, "reconnect_delay_seconds")
        _not_negative(self, "heartbeat_seconds", "idle_timeout_seconds")


_NESTED: dict[str, type] = {
    "graduation": GraduationSettings,
    "lane": LaneSettings,
    "execution": ExecutionSettings,
    "capture": CaptureSettings,
    "stream": StreamSettings,
}


@dataclass(frozen=True)
class PumpSettings:
    """Everything ``module_settings`` can say; see the module docstring."""

    graduation: GraduationSettings = field(default_factory=GraduationSettings)
    lane: LaneSettings = field(default_factory=LaneSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    stream: StreamSettings = field(default_factory=StreamSettings)
    screening: ScreeningSettings = field(default_factory=ScreeningSettings)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PumpSettings:
        values = _clean(data, where="module_settings", kind=cls)
        built: dict[str, Any] = {}
        for key, kind in _NESTED.items():
            if key in values and values[key] is not None:
                nested = _clean(values[key], where=key, kind=kind)
                built[key] = kind(**nested)
        if values.get("screening") is not None:
            if not isinstance(values["screening"], Mapping):
                raise ValueError("screening must be an object")
            built["screening"] = ScreeningSettings.from_mapping(values["screening"])
        return cls(**built)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "GRADUATION_MARKET_CAP_SOL",
    "CaptureSettings",
    "ExecutionSettings",
    "GraduationSettings",
    "LaneSettings",
    "PumpSettings",
    "StreamSettings",
]
