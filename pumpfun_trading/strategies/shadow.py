"""Shadow variants of the momentum entry, logged on paper (FEAT-58).

Replay cannot judge a rule that acts on the fill price: the paper fill reads the
curve, and a capture only holds the trades the bot subscribed to. A shadow
variant is a momentum rule the bot does *not* trade. On every trade of a
watched (or momentum-held) mint each variant is evaluated with its own
thresholds; the first time one fires, the runtime reads the curve after the
paper entry delay and records what the fill would have been. One paper capture
then tests several rules on real fill prices.

A variant is either a ``momentum`` rule (the default: the bot's momentum
check with other thresholds) or a ``pullback`` rule (FEAT-59): wait for the
first dump after the pump, buy when the price has held a base above its low
and buying comes back. Both can add the FEAT-56/57/60/61 order-flow filters.

Variants never buy, never touch the watch list and never change a subscription.
"""

from __future__ import annotations

from collections import deque
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
        # FEAT-60 buy timing (drizzle / burst).
        "min_buy_gap_cv",
        "max_burst_share",
        "min_buy_size_cv",
        "max_small_buy_share",
        # FEAT-61 bundle proxy from the screening holder snapshot.
        "max_early_holders",
        "max_early_holder_pct",
    }
)
VARIANT_KINDS = ("momentum", "pullback", "pullback_curve")
PULLBACK_KINDS = frozenset({"pullback", "pullback_curve"})
# Curve readings kept per mint for ``pullback_curve`` inflow (bounded).
CURVE_HISTORY_SECONDS = 300.0
# Pullback rule (FEAT-59) and its defaults: the mint must have pumped to at
# least ``min_peak_market_cap_sol``, now sit ``min..max_drawdown_pct`` below
# that peak, have made no new low for ``min_base_seconds``, be at least
# ``min_rebound_pct`` off the low, and show ``min_net_inflow_sol`` from
# ``min_unique_buyers`` other wallets over the last ``window_seconds``.
# ``pullback_curve`` runs the same rule on the watch poller's curve reads
# instead of the trade feed, so it covers every watched mint (no billed
# subscription): its inflow is the curve's real SOL change over the window,
# and ``min_unique_buyers`` is not checked (a curve read has no wallets).
PULLBACK_DEFAULTS: Mapping[str, float] = {
    "pullback_min_peak_market_cap_sol": 40.0,
    "pullback_min_drawdown_pct": 0.30,
    "pullback_max_drawdown_pct": 0.70,
    "pullback_min_base_seconds": 10.0,
    "pullback_min_rebound_pct": 0.03,
    "pullback_window_seconds": 15.0,
    "pullback_min_net_inflow_sol": 0.2,
    "pullback_min_unique_buyers": 2.0,
    "pullback_min_token_age_seconds": 30.0,
    "pullback_max_token_age_seconds": 900.0,
}
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
    kind: str = "momentum"
    # Pullback thresholds (``PULLBACK_DEFAULTS`` keys), set for ``pullback``.
    pullback: Mapping[str, float] = field(default_factory=dict)

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
        kind = str(raw.get("kind") or "momentum").strip().lower()
        if kind not in VARIANT_KINDS:
            raise ValueError(
                f"shadow variant '{name}': kind must be one of "
                + ", ".join(VARIANT_KINDS)
                + "."
            )
        overrides: dict[str, Any] = {}
        filters: dict[str, float] = {}
        pullback: dict[str, float] = (
            dict(PULLBACK_DEFAULTS) if kind in PULLBACK_KINDS else {}
        )
        drift = 0.0
        for key, value in raw.items():
            if key in ("name", "kind"):
                continue
            if key in PULLBACK_DEFAULTS:
                if kind not in PULLBACK_KINDS:
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' needs \"kind\": "
                        '"pullback" or "pullback_curve".'
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' must be a number."
                    )
                if value < 0:
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' must not be negative."
                    )
                pullback[key] = float(value)
            elif key == "max_entry_drift_pct":
                drift = float(value)
                if drift < 0:
                    raise ValueError(
                        f"shadow variant '{name}': max_entry_drift_pct must not be negative."
                    )
            elif key in FLOW_FILTER_KEYS:
                filters[key] = float(value)
            elif key in OVERRIDABLE_KEYS:
                if kind in PULLBACK_KINDS:
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' is a momentum threshold; "
                        "a pullback variant uses pullback_* keys."
                    )
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"shadow variant '{name}': '{key}' must be a number."
                    )
                overrides[key] = value
            else:
                raise ValueError(
                    f"shadow variant '{name}': unknown key '{key}'. Allowed: "
                    "kind, momentum_* thresholds, min_market_cap_sol, pullback_* "
                    "thresholds, max_entry_drift_pct and "
                    + ", ".join(sorted(FLOW_FILTER_KEYS))
                )
        if kind in PULLBACK_KINDS and (
            pullback["pullback_max_drawdown_pct"]
            <= pullback["pullback_min_drawdown_pct"]
            or pullback["pullback_max_drawdown_pct"] >= 1.0
        ):
            raise ValueError(
                f"shadow variant '{name}': need pullback_min_drawdown_pct < "
                "pullback_max_drawdown_pct < 1."
            )
        return cls(
            name=name,
            overrides=overrides,
            max_entry_drift_pct=drift,
            flow_filters=filters,
            kind=kind,
            pullback=pullback,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, **dict(self.overrides)}
        if self.kind != "momentum":
            out["kind"] = self.kind
            out.update(self.pullback)
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
    # Per-mint metrics fixed at screening (the FEAT-61 bundle proxy).
    static_metrics: dict[str, Any] = field(default_factory=dict)
    # Price path seen on the trade feed, for the pullback rule: the highest
    # market cap so far, and the lowest one since that peak.
    peak: float = 0.0
    low: float = 0.0
    low_at: float = 0.0
    # (time, real SOL) of recent curve reads, for ``pullback_curve`` inflow.
    curve: deque[tuple[float, float]] = field(default_factory=deque)

    def observe_curve(self, real_sol: float, now: float) -> None:
        self.curve.append((now, real_sol))
        while self.curve and now - self.curve[0][0] > CURVE_HISTORY_SECONDS:
            self.curve.popleft()

    def curve_inflow(self, window_seconds: float, now: float) -> float | None:
        """Real SOL change over the last ``window_seconds`` (``None`` until the
        history spans the window)."""
        if not self.curve or now - self.curve[0][0] < window_seconds:
            return None
        start = self.curve[0][1]
        for ts, real_sol in self.curve:
            if now - ts < window_seconds:
                break
            start = real_sol
        return self.curve[-1][1] - start

    def observe(self, market_cap_sol: float, now: float) -> None:
        if market_cap_sol > self.peak:
            self.peak = market_cap_sol
            self.low = market_cap_sol
            self.low_at = now
        elif market_cap_sol < self.low:
            self.low = market_cap_sol
            self.low_at = now


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

    def remember(
        self,
        mint: str,
        *,
        created_at: float,
        creator: str | None,
        static_metrics: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep a mint's age, creator and screening metrics so evaluation can go
        on after the watch entry is gone (the bot bought it, or it was dropped)."""
        if mint in self._mints:
            return
        while len(self._mints) >= self.max_mints:
            self._mints.pop(next(iter(self._mints)))
        self._mints[mint] = _MintContext(
            created_at=float(created_at),
            creator=creator,
            static_metrics=dict(static_metrics or {}),
        )

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
        real_sol: float | None = None,
    ) -> list[ShadowSignal]:
        """Variants that fire on ``mint`` now for the first time.

        Called with a trade (``real_sol`` is ``None``) it evaluates the
        ``momentum`` and ``pullback`` variants; called with a curve read
        (``real_sol`` set) only the ``pullback_curve`` ones. Both update the
        mint's price path.

        Each variant sees the bot's capacity as empty (no open positions, no
        attempts), so it measures the rule and not the bot's position limits.
        """
        context = self._mints.get(mint)
        if context is None or market_cap_sol <= 0:
            return []
        context.observe(float(market_cap_sol), float(now))
        from_curve = real_sol is not None
        if real_sol is not None:
            context.observe_curve(float(real_sol), float(now))
        exclude = frozenset(u for u in (*exclude_users, context.creator or "") if u)
        age = max(0.0, float(now) - context.created_at)
        flow: dict[str, Any] | None = None
        fired: list[ShadowSignal] = []
        for variant in self.variants:
            if variant.name in context.fired:
                continue
            if (variant.kind == "pullback_curve") != from_curve:
                continue
            if variant.kind in PULLBACK_KINDS:
                metrics = _pullback_metrics(
                    variant, engine, mint, context, now, market_cap_sol, age, exclude
                )
            else:
                metrics = self._momentum_metrics(
                    variant, engine, mint, context, now, market_cap_sol, age, exclude
                )
            if metrics is None:
                continue
            if flow is None:
                flow = {
                    **engine.buy_flow_concentration(
                        mint, exclude_users=exclude, current_time=now
                    ),
                    **engine.round_trip_flow(
                        mint, exclude_users=exclude, current_time=now
                    ),
                    **engine.buy_timing(mint, exclude_users=exclude, current_time=now),
                    **context.static_metrics,
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
                        **metrics,
                        "token_age_seconds": round(age, 1),
                        "market_cap_sol": round(float(market_cap_sol), 4),
                        **{k: v for k, v in flow.items() if k in _RECORDED_FLOW_KEYS},
                    },
                )
            )
        return fired

    def _momentum_metrics(
        self,
        variant: ShadowVariant,
        engine: OrderFlowEngine,
        mint: str,
        context: _MintContext,
        now: float,
        market_cap_sol: float,
        age: float,
        exclude: frozenset[str],
    ) -> dict[str, Any] | None:
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
            return None
        return {
            "unique_buyers": signal.unique_buyers,
            "net_inflow_sol": signal.net_sol_inflow,
            "buy_sell_ratio": signal.buy_sell_ratio,
            "z_score": signal.z_score,
        }


# Order-flow metrics copied into a shadow signal's ``entry_metrics``.
_RECORDED_FLOW_KEYS = frozenset(
    {
        "top_buyer_share",
        "wallet_diversity",
        "round_trip_share",
        "quick_flips",
        "buy_gap_cv",
        "buy_gap_median_seconds",
        "burst_share",
        "buy_size_cv",
        "small_buy_share",
        "early_holders",
        "early_holder_pct",
    }
)


def _pullback_metrics(
    variant: ShadowVariant,
    engine: OrderFlowEngine,
    mint: str,
    context: _MintContext,
    now: float,
    market_cap_sol: float,
    age: float,
    exclude: frozenset[str],
) -> dict[str, Any] | None:
    """The pullback rule's inputs when it holds now, else ``None`` (FEAT-59)."""
    rule = variant.pullback
    if not (
        rule["pullback_min_token_age_seconds"]
        <= age
        <= rule["pullback_max_token_age_seconds"]
    ):
        return None
    peak = context.peak
    if peak <= 0 or peak < rule["pullback_min_peak_market_cap_sol"]:
        return None
    drawdown = 1.0 - float(market_cap_sol) / peak
    if not (
        rule["pullback_min_drawdown_pct"]
        <= drawdown
        <= rule["pullback_max_drawdown_pct"]
    ):
        return None
    base_seconds = float(now) - context.low_at
    if base_seconds < rule["pullback_min_base_seconds"]:
        return None
    if context.low <= 0 or float(market_cap_sol) < context.low * (
        1.0 + rule["pullback_min_rebound_pct"]
    ):
        return None
    shape = {
        "kind": variant.kind,
        "peak_market_cap_sol": round(peak, 4),
        "low_market_cap_sol": round(context.low, 4),
        "drawdown_pct": round(drawdown, 4),
        "base_seconds": round(base_seconds, 1),
    }
    if variant.kind == "pullback_curve":
        inflow = context.curve_inflow(rule["pullback_window_seconds"], float(now))
        if inflow is None or inflow < rule["pullback_min_net_inflow_sol"]:
            return None
        return {**shape, "curve_inflow_sol": round(inflow, 6)}
    window = engine.get_metrics(
        mint,
        window_seconds=max(1, int(round(rule["pullback_window_seconds"]))),
        current_time=now,
        exclude_users=exclude,
    )
    if window.net_sol_inflow < rule["pullback_min_net_inflow_sol"]:
        return None
    if window.unique_buyers < int(rule["pullback_min_unique_buyers"]):
        return None
    return {
        **shape,
        "unique_buyers": window.unique_buyers,
        "net_inflow_sol": window.net_sol_inflow,
        "buy_sell_ratio": window.buy_sell_ratio,
    }


def _passes_flow_filters(variant: ShadowVariant, flow: Mapping[str, Any]) -> bool:
    """A missing metric (too few buys for gap statistics, no holder data)
    leaves its filter unapplied rather than guessing a value."""
    for key, limit in variant.flow_filters.items():
        value = flow.get(key.split("_", 1)[1])
        if value is None:
            continue
        metric = float(value or 0.0)
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
        **({"kind": signal.variant.kind} if signal.variant.kind != "momentum" else {}),
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
    "PULLBACK_DEFAULTS",
    "PULLBACK_KINDS",
    "VARIANT_KINDS",
    "ShadowSignal",
    "ShadowVariant",
    "ShadowVariantBook",
    "parse_shadow_variants",
    "shadow_fill_record",
]
