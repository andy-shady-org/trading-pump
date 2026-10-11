"""Market-data access helpers for the runtime."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class ResilienceState:
    """Tracks transient data-provider failures for fallback logic."""

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_failure_at: float | None = None
        self.consecutive_failures = 0

    def record_failure(self, error: str | None = None) -> None:
        self.last_error = error
        self.last_failure_at = time.monotonic()
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.last_error = None
        self.last_failure_at = None
        self.consecutive_failures = 0


class MarketDataService:
    """Thin wrapper over market-data lookups used by the bot runtime."""

    def __init__(self, api_client: Any | None = None):
        self.api_client = api_client
        self._resilience = ResilienceState()

    @property
    def resilience(self) -> ResilienceState:
        return self._resilience

    async def get_market_cap_sol(self, data: dict[str, Any]) -> float:
        for key in ("marketCapSol", "marketCap", "market_cap_sol", "market_cap"):
            value = data.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return 30.0

    async def get_token_name(self, data: dict[str, Any]) -> str | None:
        token_name = str(
            data.get("name") or data.get("tokenName") or data.get("displayName") or ""
        ).strip()
        return token_name or None

    async def fetch_with_fallback(
        self,
        candidate_calls: list[tuple[str, list[tuple[str, Any]] | None]],
        *,
        timeout: float = 5.0,
        fallback_value: Any = None,
    ) -> Any:
        last_error: Exception | None = None
        for name, params in candidate_calls:
            try:
                if self.api_client is None:
                    raise RuntimeError("No API client configured")
                method = getattr(self.api_client, name, None)
                if method is None:
                    raise AttributeError(f"API client missing method: {name}")
                if params is None:
                    result = await asyncio.wait_for(method(), timeout=timeout)
                else:
                    result = await asyncio.wait_for(
                        method(**dict(params)),
                        timeout=timeout,
                    )
                self._resilience.record_success()
                return result
            except Exception as exc:  # pragma: no cover - defensive fallback branch
                last_error = exc
                self._resilience.record_failure(str(exc))
        if last_error is not None:
            return fallback_value
        return fallback_value

    def is_data_fresh(
        self, *, last_seen_at: float | None, max_age_seconds: float
    ) -> bool:
        if last_seen_at is None:
            return False
        return (time.monotonic() - float(last_seen_at)) <= max_age_seconds


__all__ = ["MarketDataService", "ResilienceState"]
