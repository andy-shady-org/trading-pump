"""Shadow variants of the momentum entry, logged on paper (FEAT-58).

Replay cannot judge a rule that acts on the fill price: the paper fill reads the
curve, and a capture only holds the trades the bot subscribed to. A shadow
variant is a momentum rule the bot does *not* trade. On every trade of a
watched (or momentum-held) mint each variant is evaluated with its own
thresholds; the first time one fires, the runtime reads the curve after the
paper entry delay and records what the fill would have been. One paper capture
then tests several rules on real fill prices.

Variants never buy, never touch the watch list and never change a subscription.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any, Mapping, Sequence

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.decision import TradingStrategy
from pumpfun_trading.strategies.momentum import OrderFlowEngine

# Order-flow filters a variant may add on top of the momentum rule
# (FEAT-56 / FEAT-57 inputs): ``max_*`` refuse above, ``min_*`` below.
FLOW_FILTER_KEYS = frozenset(
    {
        "max_top_buyer_share",
        "min_wallet_diversity",
        "max_round_trip_share",
        "max_quick_flips",
    }
)
# Config keys a variant may override; everything else is the bot's own config.
_OVERRIDE_EXTRA_KEYS = frozenset({"min_market_cap_sol"})
SHADOW_NAME_MAX_LENGTH = 40


def _overridable_keys() -> frozenset[str]:
    names = {f.name for f in fields(TradingBotConfig)}
    return frozenset(
        name
        for name in names
        if (name.startswith("momentum_") and name != "momentum_max_entry_drift_pct")
        or name in _OVERRIDE_EXTRA_KEYS
    )


OVERRIDABLE_KEYS = _overridable_keys()


@dataclass(frozen=True)
class ShadowVariant:
    """One momentum rule logged but never traded."""

    name: str
    overrides: Mapping[str, Any] = field(default_factory=dict)
    # Drift guard of this variant (0 = off), applied to the shadow fill.
    max_entry_drift_pct: float = 0.0
    flow_filters: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ShadowVariant:
        """Parse one ``shadow_variants`` entry; raises ``ValueError`` when invalid."""
        if not isinstance(raw, Mapping):
            raise ValueError("shadow_variants entries must be JSON objects.")
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > SHADOW_NAME_MAX_LENGTH:
            raise ValueError(
                "shadow_variants entries need a name of 1-"
                f"{SHADOW_NAME_MAX_LENGTH} characters."
            )
        overrides: dict[str, Any] = {}
        filters: dict[str, float] = {}
        drift = 0.0
        for key, value in raw.items():
            if key == "name":
                continue
            if key == "max_entry_drift_pct":
                drift = float(value)
                if drift < 0:
                    raise ValueError(
                        f"shadow variant '{name}': max_entry_drift_pct must not be negative."
                    )
            elif key in FLOW_FILTER_KEYS:
                filters[key] = float(value)
            elif key in OVERRIDABLE_KEYS:
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' must be a number."
                    )
                overrides[key] = value
            else:
                raise ValueError(
                    f"shadow variant '{name}': unknown key '{key}'. Allowed: "
                    "momentum_* thresholds, min_market_cap_sol, "
                    "max_entry_drift_pct and " + ", ".join(sorted(FLOW_FILTER_KEYS))
                )
        return cls(
            name=name,
            overrides=overrides,
            max_entry_drift_pct=drift,
            flow_filters=filters,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, **dict(self.overrides)}
        if self.max_entry_drift_pct:
            out["max_entry_drift_pct"] = self.max_entry_drift_pct
        out.update(self.flow_filters)
        return out


def parse_shadow_variants(raw: Sequence[Any] | None) -> tuple[ShadowVariant, ...]:
    """Parse and check a ``shadow_variants`` list (unique names)."""
    variants = tuple(ShadowVariant.from_dict(item) for item in (raw or ()))
    names = [variant.name for variant in variants]
    if len(set(names)) != len(names):
        raise ValueError("shadow_variants names must be unique.")
    return variants


def variant_config(
    config: TradingBotConfig, variant: ShadowVariant
) -> TradingBotConfig:
    """The bot's config with the variant's thresholds, typed like the base field."""
    typed: dict[str, Any] = {}
    for key, value in variant.overrides.items():
        current = getattr(config, key)
        if isinstance(current, bool):
            typed[key] = bool(value)
        elif isinstance(current, int):
            typed[key] = int(value)
        else:
            typed[key] = float(value)
    return replace(config, **typed)


@dataclass(frozen=True)
class ShadowSignal:
    """A variant firing on one mint: the inputs of its shadow fill."""

    variant: ShadowVariant
    mint: str
    signal_time: float
    signal_market_cap_sol: float
    entry_metrics: dict[str, Any]


@dataclass(slots=True)
class _MintContext:
    created_at: float
    creator: str | None
    fired: set[str] = field(default_factory=set)


class ShadowVariantBook:
    """Evaluates every variant once per mint on the live order flow."""

    def __init__(
        self,
        config: TradingBotConfig,
        variants: Sequence[ShadowVariant],
        *,
        max_mints: int = 2_000,
    ) -> None:
        self.variants = tuple(variants)
        self.max_mints = max(1, int(max_mints))
        self._strategies = {
            variant.name: TradingStrategy(variant_config(config, variant))
            for variant in self.variants
        }
        self._mints: dict[str, _MintContext] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.variants)

    @property
    def tracked_mints(self) -> int:
        return len(self._mints)

    def remember(self, mint: str, *, created_at: float, creator: str | None) -> None:
        """Keep a mint's age and creator so evaluation can go on after the watch
        entry is gone (the bot bought it, or the entry was dropped)."""
        if mint in self._mints:
            return
        while len(self._mints) >= self.max_mints:
            self._mints.pop(next(iter(self._mints)))
        self._mints[mint] = _MintContext(created_at=float(created_at), creator=creator)

    def knows(self, mint: str) -> bool:
        return mint in self._mints

    def forget(self, mint: str) -> None:
        self._mints.pop(mint, None)

    def evaluate(
        self,
        engine: OrderFlowEngine,
        mint: str,
        *,
        now: float,
        market_cap_sol: float,
        exclude_users: frozenset[str] = frozenset(),
    ) -> list[ShadowSignal]:
        """Variants that fire on ``mint`` now for the first time.

        Each variant sees the bot's capacity as empty (no open positions, no
        attempts), so it measures the rule and not the bot's position limits.
        """
        context = self._mints.get(mint)
        if context is None or market_cap_sol <= 0:
            return []
        exclude = frozenset(u for u in (*exclude_users, context.creator or "") if u)
        age = max(0.0, float(now) - context.created_at)
        flow: dict[str, Any] | None = None
        fired: list[ShadowSignal] = []
        for variant in self.variants:
            if variant.name in context.fired:
                continue
            strategy = self._strategies[variant.name]
            signal = strategy.evaluate_momentum(
                engine,
                mint,
                token_creation_timestamp=context.created_at,
                current_time=now,
                exclude_users=exclude,
            )
            if not strategy.should_buy_momentum(
                momentum_signal=signal,
                active_positions=0,
                buy_attempts=0,
                token_age_seconds=age,
                market_cap_sol=market_cap_sol,
            ):
                continue
            if flow is None:
                flow = {
                    **engine.buy_flow_concentration(
                        mint, exclude_users=exclude, current_time=now
                    ),
                    **engine.round_trip_flow(
                        mint, exclude_users=exclude, current_time=now
                    ),
                }
            if not _passes_flow_filters(variant, flow):
                continue
            context.fired.add(variant.name)
            fired.append(
                ShadowSignal(
                    variant=variant,
                    mint=mint,
                    signal_time=float(now),
                    signal_market_cap_sol=float(market_cap_sol),
                    entry_metrics={
                        "unique_buyers": signal.unique_buyers,
                        "net_inflow_sol": signal.net_sol_inflow,
                        "buy_sell_ratio": signal.buy_sell_ratio,
                        "z_score": signal.z_score,
                        "token_age_seconds": round(age, 1),
                        "market_cap_sol": round(float(market_cap_sol), 4),
                        "top_buyer_share": flow["top_buyer_share"],
                        "wallet_diversity": flow["wallet_diversity"],
                        "round_trip_share": flow["round_trip_share"],
                        "quick_flips": flow["quick_flips"],
                    },
                )
            )
        return fired


def _passes_flow_filters(variant: ShadowVariant, flow: Mapping[str, Any]) -> bool:
    for key, limit in variant.flow_filters.items():
        metric = float(flow.get(key.split("_", 1)[1], 0.0) or 0.0)
        if key.startswith("max_") and metric > limit:
            return False
        if key.startswith("min_") and metric < limit:
            return False
    return True


def shadow_fill_record(
    signal: ShadowSignal,
    *,
    fill_market_cap_sol: float | None,
    fill_time: float,
    error: str | None = None,
) -> dict[str, Any]:
    """The ``shadow_entry`` capture row for one shadow fill.

    It carries no ``price`` / ``market_cap_sol`` key, so replay never reads it
    as market data; the curve read itself is written as a ``curve_poll`` row.
    """
    record: dict[str, Any] = {
        "timestamp": fill_time,
        "mint": signal.mint,
        "event": "shadow_entry",
        "variant": signal.variant.name,
        "signal_timestamp": signal.signal_time,
        "signal_market_cap_sol": round(signal.signal_market_cap_sol, 6),
        "entry_metrics": dict(signal.entry_metrics),
    }
    if fill_market_cap_sol is None or fill_market_cap_sol <= 0:
        record["refused"] = "no_curve" if error is None else error
        return record
    drift = fill_market_cap_sol / signal.signal_market_cap_sol - 1.0
    record["fill_market_cap_sol"] = round(fill_market_cap_sol, 6)
    record["fill_drift_pct"] = round(drift, 4)
    limit = signal.variant.max_entry_drift_pct
    if limit > 0 and drift > limit:
        record["refused"] = "entry_drift"
    return record


__all__ = [
    "FLOW_FILTER_KEYS",
    "OVERRIDABLE_KEYS",
    "ShadowSignal",
    "ShadowVariant",
    "ShadowVariantBook",
    "parse_shadow_variants",
    "shadow_fill_record",
]
