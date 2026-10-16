"""Multi-RPC connection pool, latency tracking, circuit breaking, and transaction broadcasting.

This module provides high-availability infrastructure for Solana JSON-RPC interactions,
supporting rolling latency percentiles (p50, p95, p99), dynamic circuit breaking on rate limits
(HTTP 429) and server errors (5xx), lowest-latency read routing, and concurrent transaction broadcasting.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

import aiohttp

from pumpfun_trading.ops.redact import redact_url

# JSON-RPC errors caused by the request itself (bad params, missing account,
# preflight/simulation or signature failure). Every other error code is treated
# as an endpoint problem and triggers failover.
DETERMINISTIC_JSONRPC_ERROR_CODES = frozenset(
    {-32600, -32601, -32602, -32002, -32003, -32006, -32013, -32015}
)


class CircuitState(str, Enum):
    """Circuit breaker states for an RPC endpoint."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class RpcEndpoint:
    """Solana RPC endpoint state, rolling latency metrics, and circuit breaker."""

    url: str
    label: str = ""
    weight: float = 1.0
    state: CircuitState = CircuitState.HEALTHY
    consecutive_failures: int = 0
    total_requests: int = 0
    total_errors: int = 0
    rate_limited_count: int = 0
    last_error_time: Optional[float] = None
    last_success_time: Optional[float] = None
    cooldown_until: float = 0.0
    latency_samples: deque[float] = field(default_factory=lambda: deque(maxlen=100))

    def __post_init__(self) -> None:
        if not self.label:
            # Generate a compact label from URL hostname if empty
            clean_url = (
                self.url.replace("https://", "").replace("http://", "").split("/")[0]
            )
            # Never let ``user:password@`` userinfo into the label (BUG-102).
            clean_url = clean_url.rsplit("@", 1)[-1].split("?")[0]
            self.label = clean_url or "rpc_endpoint"

    def record_success(self, latency_seconds: float) -> None:
        """Record a successful RPC response and append latency measurement."""
        self.total_requests += 1
        self.consecutive_failures = 0
        now = time.time()
        self.last_success_time = now
        self.latency_samples.append(max(0.0, float(latency_seconds)))
        # Any success restores circuit to healthy
        self.state = CircuitState.HEALTHY

    def record_failure(
        self,
        error_type: str = "generic",
        cooldown_seconds: float = 60.0,
        circuit_breaker_threshold: int = 3,
    ) -> None:
        """Record an RPC failure and dynamically adjust circuit breaker state."""
        self.total_requests += 1
        self.total_errors += 1
        self.consecutive_failures += 1
        now = time.time()
        self.last_error_time = now

        err_lower = str(error_type).lower()
        is_rate_limit = (
            "429" in err_lower
            or "rate" in err_lower
            or "too many" in err_lower
            or "limit" in err_lower
        )

        if is_rate_limit:
            self.rate_limited_count += 1
            self.state = CircuitState.OPEN
            self.cooldown_until = now + cooldown_seconds
        elif self.state == CircuitState.HALF_OPEN:
            # Probe failed in half-open state, re-open immediately with full cooldown
            self.state = CircuitState.OPEN
            self.cooldown_until = now + cooldown_seconds
        elif self.consecutive_failures >= circuit_breaker_threshold:
            self.state = CircuitState.OPEN
            self.cooldown_until = now + cooldown_seconds
        else:
            self.state = CircuitState.DEGRADED

    def check_health_and_cooldown(self, now: Optional[float] = None) -> CircuitState:
        """Check and transition circuit state if cooldown window has expired."""
        current_time = time.time() if now is None else now
        if self.state == CircuitState.OPEN:
            if current_time >= self.cooldown_until:
                self.state = CircuitState.HALF_OPEN
        return self.state

    def is_available(self, now: Optional[float] = None) -> bool:
        """Return True if endpoint can accept traffic (HEALTHY, DEGRADED, or HALF_OPEN)."""
        current_state = self.check_health_and_cooldown(now)
        return current_state in (
            CircuitState.HEALTHY,
            CircuitState.DEGRADED,
            CircuitState.HALF_OPEN,
        )

    def _calculate_percentile(self, p: float) -> float:
        if not self.latency_samples:
            return 0.0
        if len(self.latency_samples) == 1:
            return round(self.latency_samples[0] * 1000.0, 2)
        sorted_samples = sorted(s * 1000.0 for s in self.latency_samples)
        index = (len(sorted_samples) - 1) * p
        lower = math.floor(index)
        upper = math.ceil(index)
        weight = index - lower
        val = sorted_samples[lower] * (1.0 - weight) + sorted_samples[upper] * weight
        return round(val, 2)

    @property
    def p50_latency_ms(self) -> float:
        """Median rolling latency in milliseconds."""
        return self._calculate_percentile(0.50)

    @property
    def p95_latency_ms(self) -> float:
        """95th percentile rolling latency in milliseconds."""
        return self._calculate_percentile(0.95)

    @property
    def p99_latency_ms(self) -> float:
        """99th percentile rolling latency in milliseconds."""
        return self._calculate_percentile(0.99)

    @property
    def mean_latency_ms(self) -> float:
        """Mean rolling latency in milliseconds."""
        if not self.latency_samples:
            return 0.0
        return round(
            (sum(self.latency_samples) / len(self.latency_samples)) * 1000.0, 2
        )

    def get_score(self) -> float:
        """Calculate weighted latency score for routing decisions (lower is better)."""
        base_latency = self.p50_latency_ms if self.latency_samples else 100.0
        # Penalize degraded endpoints slightly, and half-open endpoints moderately
        penalty = 0.0
        if self.state == CircuitState.DEGRADED:
            penalty = 50.0 + (self.consecutive_failures * 25.0)
        elif self.state == CircuitState.HALF_OPEN:
            penalty = 200.0
        elif self.state == CircuitState.OPEN:
            penalty = 10_000.0

        effective_score = (base_latency / max(0.1, self.weight)) + penalty
        return round(effective_score, 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize endpoint metrics to dictionary representation."""
        return {
            "url": redact_url(self.url),
            "label": self.label,
            "weight": self.weight,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "rate_limited_count": self.rate_limited_count,
            "last_error_time": self.last_error_time,
            "last_success_time": self.last_success_time,
            "cooldown_until": self.cooldown_until,
            "sample_count": len(self.latency_samples),
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "mean_latency_ms": self.mean_latency_ms,
            "score": self.get_score(),
        }


@dataclass(slots=True)
class RpcPoolConfig:
    """Configuration for multi-provider RPC connection pool."""

    endpoints: tuple[str | RpcEndpoint, ...] = ()
    health_check_interval_seconds: float = 30.0
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 60.0
    broadcast_concurrency: int = 3
    request_timeout_seconds: float = 15.0
    max_retries_per_query: int = 3

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "endpoints": [
                redact_url(e.url if isinstance(e, RpcEndpoint) else e)
                for e in self.endpoints
            ],
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_cooldown_seconds": self.circuit_breaker_cooldown_seconds,
            "broadcast_concurrency": self.broadcast_concurrency,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_retries_per_query": self.max_retries_per_query,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RpcPoolConfig:
        """Create RpcPoolConfig from dictionary."""
        endpoints = data.get("endpoints", ())
        if isinstance(endpoints, (list, tuple)):
            normalized_endpoints: tuple[str | RpcEndpoint, ...] = tuple(
                e if isinstance(e, RpcEndpoint) else str(e).strip()
                for e in endpoints
                if (isinstance(e, RpcEndpoint) or str(e).strip())
            )
        elif isinstance(endpoints, str):
            normalized_endpoints = tuple(
                e.strip() for e in endpoints.split(",") if e.strip()
            )
        else:
            normalized_endpoints = ()

        return cls(
            endpoints=normalized_endpoints,
            health_check_interval_seconds=float(
                data.get("health_check_interval_seconds", 30.0)
            ),
            circuit_breaker_threshold=int(data.get("circuit_breaker_threshold", 3)),
            circuit_breaker_cooldown_seconds=float(
                data.get("circuit_breaker_cooldown_seconds", 60.0)
            ),
            broadcast_concurrency=int(data.get("broadcast_concurrency", 3)),
            request_timeout_seconds=float(data.get("request_timeout_seconds", 15.0)),
            max_retries_per_query=int(data.get("max_retries_per_query", 3)),
        )


class RpcConnectionPool:
    """Asynchronous multi-provider Solana RPC connection pool with latency routing and broadcast."""

    def __init__(
        self,
        endpoints: Optional[Sequence[str | RpcEndpoint] | str] = None,
        config: Optional[RpcPoolConfig] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.config = config or RpcPoolConfig()
        self._endpoints: list[RpcEndpoint] = []
        self._health_check_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._session: Optional[aiohttp.ClientSession] = session
        self._lock = asyncio.Lock()

        # Ingest initial endpoints
        raw_list: list[str | RpcEndpoint] = []
        if isinstance(endpoints, str):
            raw_list = [e.strip() for e in endpoints.split(",") if e.strip()]
        elif endpoints is not None:
            raw_list = list(endpoints)
        elif self.config.endpoints:
            raw_list = list(self.config.endpoints)

        for ep in raw_list:
            self.add_endpoint(ep)

    @property
    def endpoints(self) -> list[RpcEndpoint]:
        """List of all registered endpoints."""
        return list(self._endpoints)

    @property
    def endpoint_count(self) -> int:
        """Total number of registered endpoints."""
        return len(self._endpoints)

    def add_endpoint(
        self, endpoint: str | RpcEndpoint, label: str = "", weight: float = 1.0
    ) -> RpcEndpoint:
        """Register a new RPC endpoint to the pool."""
        if isinstance(endpoint, RpcEndpoint):
            # Check for duplicates
            for existing in self._endpoints:
                if existing.url == endpoint.url:
                    return existing
            self._endpoints.append(endpoint)
            return endpoint

        url = str(endpoint).strip()
        if not url:
            raise ValueError("Endpoint URL cannot be empty")

        for existing in self._endpoints:
            if existing.url == url:
                return existing

        ep = RpcEndpoint(url=url, label=label, weight=weight)
        self._endpoints.append(ep)
        return ep

    def remove_endpoint(self, url: str) -> bool:
        """Remove an endpoint by URL."""
        initial_len = len(self._endpoints)
        self._endpoints = [ep for ep in self._endpoints if ep.url != url]
        return len(self._endpoints) < initial_len

    def get_healthy_endpoints(self, now: Optional[float] = None) -> list[RpcEndpoint]:
        """Return available endpoints sorted by routing score (best first)."""
        available = [ep for ep in self._endpoints if ep.is_available(now)]
        return sorted(available, key=lambda ep: ep.get_score())

    def get_best_endpoint(self, now: Optional[float] = None) -> Optional[RpcEndpoint]:
        """Return the optimal endpoint with the lowest score."""
        healthy = self.get_healthy_endpoints(now)
        if healthy:
            return healthy[0]
        # If no endpoint is healthy/half-open, fallback to the one with soonest cooldown expiry
        if self._endpoints:
            return min(
                self._endpoints,
                key=lambda ep: (ep.cooldown_until, ep.consecutive_failures),
            )
        return None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or getattr(self._session, "closed", False) is True:
            self._session = aiohttp.ClientSession()
        return self._session

    async def request(
        self,
        payload: dict[str, Any],
        *,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        """Intelligently route a JSON-RPC request to the lowest-latency healthy endpoint with failover."""
        if not self._endpoints:
            raise RuntimeError("No RPC endpoints configured in connection pool")

        retries = (
            max_retries
            if max_retries is not None
            else self.config.max_retries_per_query
        )
        timeout_sec = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.request_timeout_seconds
        )

        last_error: Exception | None = None
        attempted_urls: set[str] = set()

        for attempt in range(retries + 1):
            now = time.time()
            candidates = self.get_healthy_endpoints(now)

            # Prioritize candidates not yet attempted in this query cycle
            unattempted = [ep for ep in candidates if ep.url not in attempted_urls]
            chosen_ep = (
                unattempted[0]
                if unattempted
                else (candidates[0] if candidates else self.get_best_endpoint(now))
            )

            if chosen_ep is None:
                break

            attempted_urls.add(chosen_ep.url)
            start_t = time.perf_counter()

            try:
                session = await self._get_session()
                client_timeout = aiohttp.ClientTimeout(total=timeout_sec)
                async with session.post(
                    chosen_ep.url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=client_timeout,
                ) as resp:
                    elapsed = time.perf_counter() - start_t
                    body = ""
                    parsed = None

                    if resp.status == 429:
                        chosen_ep.record_failure(
                            error_type="429",
                            cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                            circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                        )
                        raise RuntimeError(
                            f"RPC endpoint rate limited (HTTP 429): {chosen_ep.label}"
                        )

                    if resp.status != 200:
                        try:
                            body = await resp.text()
                        except Exception:
                            body = ""
                        chosen_ep.record_failure(
                            error_type=f"HTTP_{resp.status}",
                            cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                            circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                        )
                        raise RuntimeError(
                            f"RPC HTTP {resp.status} from {chosen_ep.label}: {body[:200]}"
                        )

                    try:
                        text_res = await resp.text()
                        if isinstance(text_res, str):
                            body = text_res
                            parsed = json.loads(body)
                    except Exception:
                        parsed = None

                    if parsed is None and hasattr(resp, "json"):
                        try:
                            json_res = await resp.json()
                            if isinstance(json_res, dict):
                                parsed = json_res
                        except Exception:
                            pass

                    if not isinstance(parsed, dict):
                        chosen_ep.record_failure(
                            error_type="invalid_json_type",
                            cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                            circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                        )
                        raise RuntimeError(
                            f"RPC response not a JSON dict from {chosen_ep.label}"
                        )

                    # Check for JSON-RPC level rate limits or server errors
                    # Node-side errors fail over; deterministic request errors are
                    # returned to the caller with the endpoint still healthy (BUG-67).
                    if "error" in parsed and isinstance(parsed["error"], dict):
                        err_code = parsed["error"].get("code", 0)
                        err_msg = str(parsed["error"].get("message", ""))
                        if err_code not in DETERMINISTIC_JSONRPC_ERROR_CODES:
                            is_rate_limit = err_code == 429
                            chosen_ep.record_failure(
                                error_type=(
                                    "429_jsonrpc" if is_rate_limit else "jsonrpc_error"
                                ),
                                cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                                circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                            )
                            label = "rate limit" if is_rate_limit else "error"
                            raise RuntimeError(
                                f"JSON-RPC {label} on {chosen_ep.label}: "
                                f"[{err_code}] {err_msg}"
                            )

                    # Success!
                    chosen_ep.record_success(elapsed)
                    return parsed

            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                # Short backoff before trying next candidate
                await asyncio.sleep(min(0.5, 0.1 * (2**attempt)))

        if last_error is not None:
            raise RuntimeError(
                f"All RPC pool query attempts failed: {last_error}"
            ) from last_error
        raise RuntimeError("RPC pool query failed without captured error")

    async def broadcast_transaction(
        self,
        base64_tx: str,
        *,
        skip_preflight: bool = True,
        preflight_commitment: str = "confirmed",
        max_concurrency: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """Concurrently broadcast signed transaction across healthy RPC endpoints using scatter-gather."""
        if not self._endpoints:
            raise RuntimeError("No RPC endpoints configured for broadcast")

        concurrency = (
            max_concurrency
            if max_concurrency is not None
            else self.config.broadcast_concurrency
        )
        timeout_sec = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.request_timeout_seconds
        )

        healthy = self.get_healthy_endpoints()
        if not healthy:
            best_ep = self.get_best_endpoint()
            if best_ep:
                healthy = [best_ep]

        selected = healthy[: max(1, concurrency)]
        if not selected:
            raise RuntimeError("No available RPC endpoints to broadcast transaction")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64_tx,
                {
                    "skipPreflight": skip_preflight,
                    "preflightCommitment": preflight_commitment,
                    "encoding": "base64",
                    "maxRetries": 3,
                },
            ],
        }

        async def _send_to_single_endpoint(endpoint: RpcEndpoint) -> str:
            start_t = time.perf_counter()
            session = await self._get_session()
            client_timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with session.post(
                endpoint.url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=client_timeout,
            ) as resp:
                elapsed = time.perf_counter() - start_t
                body = ""
                parsed = None

                if resp.status == 429:
                    endpoint.record_failure(
                        error_type="429",
                        cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                        circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                    )
                    raise RuntimeError(f"Rate limited (HTTP 429) on {endpoint.label}")

                if resp.status != 200:
                    try:
                        body = await resp.text()
                    except Exception:
                        body = ""
                    endpoint.record_failure(
                        error_type=f"HTTP_{resp.status}",
                        cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                        circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                    )
                    raise RuntimeError(
                        f"HTTP {resp.status} on {endpoint.label}: {body[:200]}"
                    )

                try:
                    text_res = await resp.text()
                    if isinstance(text_res, str):
                        body = text_res
                        parsed = json.loads(body)
                except Exception:
                    parsed = None

                if parsed is None and hasattr(resp, "json"):
                    try:
                        json_res = await resp.json()
                        if isinstance(json_res, dict):
                            parsed = json_res
                    except Exception:
                        pass

                if not isinstance(parsed, dict):
                    endpoint.record_failure(
                        error_type="invalid_json_type",
                        cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                        circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                    )
                    raise RuntimeError(f"Invalid JSON from {endpoint.label}")

                if "error" in parsed:
                    err_msg = str(parsed["error"])
                    endpoint.record_failure(
                        error_type="send_tx_error",
                        cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                        circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                    )
                    raise RuntimeError(
                        f"SendTransaction error on {endpoint.label}: {err_msg}"
                    )

                sig = parsed.get("result")
                if not isinstance(sig, str) or len(sig) < 20:
                    endpoint.record_failure(
                        error_type="invalid_signature",
                        cooldown_seconds=self.config.circuit_breaker_cooldown_seconds,
                        circuit_breaker_threshold=self.config.circuit_breaker_threshold,
                    )
                    raise RuntimeError(
                        f"Invalid signature response on {endpoint.label}: {parsed}"
                    )

                endpoint.record_success(elapsed)
                return sig

        tasks = [asyncio.create_task(_send_to_single_endpoint(ep)) for ep in selected]
        errors: list[Exception] = []

        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    sig = await fut
                    # First valid signature returned wins!
                    return sig
                except Exception as exc:
                    errors.append(exc)
        finally:
            # Let remaining background broadcasts finish or cancel cleanly
            for t in tasks:
                if not t.done():
                    t.cancel()

        raise RuntimeError(
            f"Multi-RPC transaction broadcast failed across {len(selected)} endpoints: "
            + "; ".join(str(e) for e in errors)
        )

    async def check_endpoint_health(
        self, endpoint: RpcEndpoint, timeout_seconds: float = 5.0
    ) -> bool:
        """Perform a lightweight health probe to verify endpoint responsiveness."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getHealth",
            "params": [],
        }
        start_t = time.perf_counter()
        try:
            session = await self._get_session()
            client_timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.post(
                endpoint.url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=client_timeout,
            ) as resp:
                elapsed = time.perf_counter() - start_t
                if resp.status == 200:
                    endpoint.record_success(elapsed)
                    return True
                elif resp.status == 429:
                    endpoint.record_failure(
                        "429",
                        self.config.circuit_breaker_cooldown_seconds,
                        self.config.circuit_breaker_threshold,
                    )
                    return False
                else:
                    endpoint.record_failure(
                        f"HTTP_{resp.status}",
                        self.config.circuit_breaker_cooldown_seconds,
                        self.config.circuit_breaker_threshold,
                    )
                    return False
        except Exception as exc:
            endpoint.record_failure(
                str(exc),
                self.config.circuit_breaker_cooldown_seconds,
                self.config.circuit_breaker_threshold,
            )
            return False

    async def check_all_health(self) -> dict[str, bool]:
        """Check health across all registered endpoints concurrently."""
        tasks = [self.check_endpoint_health(ep) for ep in self._endpoints]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        health_map: dict[str, bool] = {}
        for ep, res in zip(self._endpoints, results):
            health_map[ep.url] = bool(res is True)
        return health_map

    async def _health_loop(self) -> None:
        """Periodic background health monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self.config.health_check_interval_seconds)
                if not self._running:
                    break
                await self.check_all_health()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def start_health_loop(self) -> None:
        """Start the background periodic health check loop."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._health_check_task = asyncio.create_task(self._health_loop())

    async def stop_health_loop(self) -> None:
        """Stop the background health check loop."""
        async with self._lock:
            self._running = False
            if self._health_check_task is not None:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None

    async def close(self) -> None:
        """Stop health loop and close client session."""
        await self.stop_health_loop()
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    def get_telemetry(self) -> dict[str, Any]:
        """Generate structured telemetry summary for status monitoring and logs."""
        endpoints_data = [ep.to_dict() for ep in self._endpoints]
        healthy_count = sum(
            1 for ep in self._endpoints if ep.state == CircuitState.HEALTHY
        )
        degraded_count = sum(
            1 for ep in self._endpoints if ep.state == CircuitState.DEGRADED
        )
        open_count = sum(1 for ep in self._endpoints if ep.state == CircuitState.OPEN)
        half_open_count = sum(
            1 for ep in self._endpoints if ep.state == CircuitState.HALF_OPEN
        )
        total_requests = sum(ep.total_requests for ep in self._endpoints)
        total_errors = sum(ep.total_errors for ep in self._endpoints)

        return {
            "total_endpoints": len(self._endpoints),
            "healthy_endpoints": healthy_count,
            "degraded_endpoints": degraded_count,
            "open_endpoints": open_count,
            "half_open_endpoints": half_open_count,
            "total_requests": total_requests,
            "total_errors": total_errors,
            "endpoints": endpoints_data,
        }


__all__ = [
    "CircuitState",
    "RpcEndpoint",
    "RpcPoolConfig",
    "RpcConnectionPool",
]
