"""Runtime counters and execution latency telemetry.

The bot keeps its metrics in a plain dict (persisted in `bot_status.json`
and read by the dashboard); these helpers own its shape and update rules.
"""

from __future__ import annotations

from typing import Any, Mapping

COUNTER_NAMES: tuple[str, ...] = (
    "buys",
    "sells",
    "failures",
    "retries",
    "connection_loss",
    "stale_data",
    "risk_kills",
    "circuit_breaker_trips",
)
LATENCY_KEY = "latency_ms"
_LATENCY_ALIASES = frozenset({"latency_ms", "last_latency_ms"})


def empty_latency() -> dict[str, Any]:
    return {
        "samples": 0,
        "avg_ms": 0.0,
        "last_ms": 0.0,
        "max_ms": 0.0,
        "total_ms": 0.0,
    }


def new_runtime_metrics() -> dict[str, Any]:
    """Zeroed counters plus an empty latency summary."""
    metrics: dict[str, Any] = dict.fromkeys(COUNTER_NAMES, 0)
    metrics[LATENCY_KEY] = empty_latency()
    return metrics


def record_latency_ms(metrics: dict[str, Any], latency_ms: float) -> None:
    """Add one latency sample (count, total, last, max, running mean)."""
    lat = metrics.get(LATENCY_KEY)
    if not isinstance(lat, dict):
        lat = empty_latency()
        metrics[LATENCY_KEY] = lat
    lat["samples"] = int(lat.get("samples", 0)) + 1
    lat["total_ms"] = float(lat.get("total_ms", 0.0)) + float(latency_ms)
    lat["last_ms"] = float(latency_ms)
    lat["max_ms"] = max(float(lat.get("max_ms", 0.0)), float(latency_ms))
    lat["avg_ms"] = float(lat["total_ms"]) / int(lat["samples"])


def record_metric(metrics: dict[str, Any], name: str, value: float | int = 1) -> None:
    """Increment counter `name` by `value`; latency names add a sample instead."""
    if name in _LATENCY_ALIASES:
        record_latency_ms(metrics, float(value))
        return
    current_val = metrics.get(name)
    if isinstance(current_val, (int, float)):
        metrics[name] = int(current_val + value)
    else:
        metrics[name] = int(value)


def metrics_snapshot(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Copy safe to persist or render (the latency summary is copied too)."""
    snapshot = dict(metrics)
    if isinstance(metrics.get(LATENCY_KEY), dict):
        snapshot[LATENCY_KEY] = dict(metrics[LATENCY_KEY])
    return snapshot


def restore_metrics(metrics: dict[str, Any], persisted: Mapping[str, Any]) -> None:
    """Load counters and the latency summary from a persisted snapshot."""
    for name in COUNTER_NAMES:
        if name in persisted and isinstance(persisted[name], (int, float)):
            metrics[name] = int(persisted[name])
    if LATENCY_KEY in persisted and isinstance(persisted[LATENCY_KEY], dict):
        metrics[LATENCY_KEY] = dict(persisted[LATENCY_KEY])
