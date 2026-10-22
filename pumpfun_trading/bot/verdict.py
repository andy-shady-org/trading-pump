"""Pre-registered go / no-go verdict on a paper audit trail (FEAT-67).

A paper run is only evidence when the rule that judges it was fixed before the
run started. :class:`VerdictRules` holds that rule: write it to a JSON file
(``configs/verdict_rules.json``), record its SHA-256 in the release record when
the run starts, and judge the trail with ``pumpfun-audit verdict --rules``.

Every check works on closed positions (buy plus sells, net of all recorded
costs), adjusted for what paper does not pay:

* ``exit_haircut_bps``: an extra cut on every sell's proceeds, on top of the
  paper exit model (``paper_exit_slippage_bps``), as a margin for live exits;
* ``tip_lamports``: the Jito tip a live transaction would pay; a trade that
  recorded a smaller tip is charged the difference.

GO needs every check to pass: enough positions, adjusted net above
``min_net_sol``, both halves positive, enough positive UTC days, still positive
without the ``drop_top`` best positions, and the lower bound of a bootstrap
confidence interval of the per-position mean above zero.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pumpfun_trading.bot.pnl import (
    closes_position,
    is_buy,
    is_round_trip,
    is_sell,
    position_key,
    trade_net_pnl,
)
from pumpfun_trading.bot.selection import resolve_split

LAMPORTS_PER_SOL = 1_000_000_000
VERDICT_GO = "GO"
VERDICT_NO_GO = "NO-GO"


@dataclass(frozen=True)
class VerdictRules:
    """The go / no-go rule. Fix it before the run; never tune it afterwards."""

    min_positions: int = 100
    min_net_sol: float = 0.0
    exit_haircut_bps: float = 0.0
    tip_lamports: int = 0
    split_at: str | float | None = "mid"
    min_positive_day_share: float = 0.5
    drop_top: int = 3
    bootstrap_samples: int = 10_000
    confidence: float = 0.90
    seed: int = 7
    strategy: str | None = None

    def __post_init__(self) -> None:
        # Normalise number types so the same rule always has the same hash
        # (50 and 50.0 in a JSON file are one rule).
        for name in (
            "min_net_sol",
            "exit_haircut_bps",
            "min_positive_day_share",
            "confidence",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))
        for name in (
            "min_positions",
            "tip_lamports",
            "drop_top",
            "bootstrap_samples",
            "seed",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or float(value) != int(value):
                raise ValueError(f"{name} must be a whole number, not {value!r}")
            object.__setattr__(self, name, int(value))
        if isinstance(self.split_at, (int, float)) and not isinstance(
            self.split_at, bool
        ):
            object.__setattr__(self, "split_at", float(self.split_at))
        if self.min_positions < 1:
            raise ValueError("min_positions must be at least 1")
        if not 0.0 <= self.exit_haircut_bps < 10_000:
            raise ValueError("exit_haircut_bps must be in [0, 10000)")
        if self.tip_lamports < 0:
            raise ValueError("tip_lamports must not be negative")
        if not 0.0 <= self.min_positive_day_share <= 1.0:
            raise ValueError("min_positive_day_share must be in [0, 1]")
        if self.drop_top < 0:
            raise ValueError("drop_top must not be negative")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be at least 100")
        if not 0.5 <= self.confidence < 1.0:
            raise ValueError("confidence must be in [0.5, 1)")
        try:
            resolve_split(self.split_at, 0.0, 1.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"split_at must be 'mid', a Unix time or null, not {self.split_at!r}"
            ) from exc

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> VerdictRules:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"Unknown verdict rule keys: {', '.join(unknown)}")
        return cls(**dict(data))

    @classmethod
    def from_file(cls, path: str | Path) -> VerdictRules:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read verdict rules {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Verdict rules {path} must be a JSON object")
        # Keys starting with "_" are comments.
        return cls.from_mapping(
            {k: v for k, v in data.items() if not k.startswith("_")}
        )

    def with_overrides(self, **overrides: Any) -> VerdictRules:
        values = asdict(self)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return VerdictRules(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sha256(self) -> str:
        """Fingerprint of the rule, for the release record."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def adjusted_positions(
    trades: Iterable[Mapping[str, Any]], rules: VerdictRules
) -> tuple[list[dict[str, Any]], int]:
    """Closed positions with ``net`` and ``adjusted_net``; also the open count."""
    haircut = rules.exit_haircut_bps / 10_000.0
    tip_floor = rules.tip_lamports / LAMPORTS_PER_SOL
    open_: dict[str, dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    for raw in trades:
        trade = dict(raw)
        if not (is_buy(trade) or is_sell(trade) or is_round_trip(trade)):
            continue
        key = position_key(trade)
        position = open_.get(key)
        if position is None:
            position = {
                "position_id": key,
                "mint": trade.get("mint"),
                "strategy": trade.get("strategy"),
                "entry_ts": _float(trade.get("timestamp")),
                "net": 0.0,
                "haircut_sol": 0.0,
                "extra_tip_sol": 0.0,
            }
            open_[key] = position
        if is_buy(trade):
            position["strategy"] = trade.get("strategy") or position["strategy"]
        if is_sell(trade) or is_round_trip(trade):
            proceeds = _float(trade.get("proceeds_sol") or trade.get("exit"))
            position["haircut_sol"] += proceeds * haircut
        position["extra_tip_sol"] += max(0.0, tip_floor - _float(trade.get("tip_sol")))
        position["net"] += trade_net_pnl(trade)
        if closes_position(trade):
            position["exit_ts"] = _float(trade.get("timestamp"))
            position["adjusted_net"] = (
                position["net"] - position["haircut_sol"] - position["extra_tip_sol"]
            )
            closed.append(open_.pop(key))
    if rules.strategy:
        closed = [p for p in closed if p.get("strategy") == rules.strategy]
        still_open = sum(
            1 for p in open_.values() if p.get("strategy") == rules.strategy
        )
    else:
        still_open = len(open_)
    closed.sort(key=lambda p: p["entry_ts"])
    return closed, still_open


def bootstrap_mean_interval(
    values: Sequence[float], *, samples: int, confidence: float, seed: int
) -> tuple[float, float, float]:
    """Mean and percentile bootstrap interval of the mean (seeded)."""
    if not values:
        return 0.0, 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(samples))
    tail = (1.0 - confidence) / 2.0
    low = means[min(samples - 1, max(0, int(tail * samples)))]
    high = means[min(samples - 1, max(0, int((1.0 - tail) * samples) - 1))]
    return mean, low, high


def _day(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%d")


def _check(name: str, passed: bool, value: Any, threshold: Any, detail: str) -> dict:
    return {
        "check": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
        "detail": detail,
    }


def evaluate_verdict(
    trades: Iterable[Mapping[str, Any]], rules: VerdictRules | None = None
) -> dict[str, Any]:
    """Apply ``rules`` to the trail's trade payloads and return the report."""
    rules = rules or VerdictRules()
    positions, still_open = adjusted_positions(trades, rules)
    nets = [float(p["adjusted_net"]) for p in positions]
    total = float(sum(nets))
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "min_positions",
            len(positions) >= rules.min_positions,
            len(positions),
            rules.min_positions,
            "closed positions judged",
        )
    )
    checks.append(
        _check(
            "net_positive",
            total > rules.min_net_sol,
            total,
            rules.min_net_sol,
            "adjusted net SOL above the minimum",
        )
    )

    start = positions[0]["entry_ts"] if positions else 0.0
    end = positions[-1]["entry_ts"] if positions else 0.0
    split = resolve_split(rules.split_at, start, end)
    halves: dict[str, dict[str, Any]] = {}
    if split is not None:
        for name, keep in (("A", lambda ts: ts < split), ("B", lambda ts: ts >= split)):
            part = [p for p in positions if keep(p["entry_ts"])]
            halves[name] = {
                "positions": len(part),
                "adjusted_net_sol": sum(p["adjusted_net"] for p in part),
            }
        checks.append(
            _check(
                "halves_positive",
                all(
                    h["positions"] > 0 and h["adjusted_net_sol"] > 0
                    for h in halves.values()
                ),
                {k: v["adjusted_net_sol"] for k, v in halves.items()},
                "> 0 in A and B",
                f"split at {split:.0f} (entry time)",
            )
        )

    days: dict[str, dict[str, Any]] = {}
    for position in positions:
        row = days.setdefault(
            _day(position["entry_ts"]), {"positions": 0, "adjusted_net_sol": 0.0}
        )
        row["positions"] += 1
        row["adjusted_net_sol"] += position["adjusted_net"]
    positive_days = sum(1 for row in days.values() if row["adjusted_net_sol"] > 0)
    day_share = positive_days / len(days) if days else 0.0
    checks.append(
        _check(
            "positive_days",
            bool(days) and day_share >= rules.min_positive_day_share,
            day_share,
            rules.min_positive_day_share,
            f"{positive_days} of {len(days)} UTC days positive",
        )
    )

    ranked = sorted(nets, reverse=True)
    without_top = {
        str(k): float(sum(ranked[k:])) for k in range(0, max(rules.drop_top, 5) + 1)
    }
    kept_after_drop = float(sum(ranked[rules.drop_top :]))
    checks.append(
        _check(
            "without_top_winners",
            len(ranked) > rules.drop_top and kept_after_drop > 0,
            kept_after_drop,
            "> 0",
            f"adjusted net without the {rules.drop_top} best positions",
        )
    )

    mean, low, high = bootstrap_mean_interval(
        nets,
        samples=rules.bootstrap_samples,
        confidence=rules.confidence,
        seed=rules.seed,
    )
    checks.append(
        _check(
            "bootstrap_lower_bound",
            bool(nets) and low > 0,
            low,
            "> 0",
            f"{rules.confidence:.0%} interval of the per-position mean "
            f"[{low:+.6f}, {high:+.6f}] SOL",
        )
    )

    passed = all(check["passed"] for check in checks)
    return {
        "verdict": VERDICT_GO if passed else VERDICT_NO_GO,
        "rules": rules.to_dict(),
        "rules_sha256": rules.sha256,
        "positions": len(positions),
        "open_positions": still_open,
        "net_sol": sum(p["net"] for p in positions),
        "haircut_sol": sum(p["haircut_sol"] for p in positions),
        "extra_tip_sol": sum(p["extra_tip_sol"] for p in positions),
        "adjusted_net_sol": total,
        "mean_per_position_sol": mean,
        "bootstrap": {
            "mean": mean,
            "low": low,
            "high": high,
            "confidence": rules.confidence,
            "samples": rules.bootstrap_samples,
            "seed": rules.seed,
        },
        "halves": halves,
        "days": dict(sorted(days.items())),
        "without_top_sol": without_top,
        "checks": checks,
    }


__all__ = [
    "VERDICT_GO",
    "VERDICT_NO_GO",
    "VerdictRules",
    "adjusted_positions",
    "bootstrap_mean_interval",
    "evaluate_verdict",
]
