"""Operational summary helpers for runtime health and risk visibility."""

from __future__ import annotations

from typing import Any


def build_runtime_summary(bot: Any) -> dict[str, Any]:
    """Return a compact summary for dashboards and incident triage."""
    metrics_func: Any = getattr(bot, "_metrics_snapshot", lambda: {})
    metrics: dict[str, Any] = metrics_func() if callable(metrics_func) else {}
    bot_state = getattr(bot, "state", None)
    state_val = (
        getattr(bot_state, "value", bot_state) if bot_state is not None else None
    )
    return {
        "state": state_val,
        "health_ok": getattr(bot, "_health_ok", False),
        "risk_killed": getattr(bot, "_risk_killed", False),
        "stop_requested": getattr(bot, "_stop_requested", False),
        "active_positions": len(getattr(bot, "active_positions", {})),
        "buy_attempts": dict(getattr(bot, "_buy_attempts", {})),
        "metrics": metrics,
        "last_event": getattr(bot, "_last_event", ""),
        "last_status": getattr(bot, "_last_status", ""),
    }


def runtime_is_healthy(bot: Any) -> bool:
    """Quick guard for runtime health checks and release gates."""
    summary = build_runtime_summary(bot)
    return bool(summary["health_ok"]) and not summary["risk_killed"]


__all__ = ["build_runtime_summary", "runtime_is_healthy"]
