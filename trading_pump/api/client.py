import asyncio
import inspect
import json as json_module
import time
from typing import Any

import aiohttp

# ipfs.io / dweb.link now answer HTTP 429 ("service worker gateway only"), so
# token metadata is read through Pump.fun's own Pinata gateway (BUG-95).
IPFS_GATEWAY = "https://pump.mypinata.cloud/ipfs/"
_PUBLIC_IPFS_HOSTS = (
    "https://ipfs.io/ipfs/",
    "https://dweb.link/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://cf-ipfs.com/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
)
# Client errors that are final answers, not transient failures.
_RETRYABLE_CLIENT_STATUSES = frozenset({408, 425, 429})


class PumpFunApiHttpError(RuntimeError):
    """HTTP error response from a Pump.fun (or metadata) endpoint."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status

    @property
    def is_retryable(self) -> bool:
        return self.status >= 500 or self.status in _RETRYABLE_CLIENT_STATUSES


def resolve_metadata_uri(uri: str) -> str:
    """Maps ``ipfs://`` and rate-limited public gateway URLs to ``IPFS_GATEWAY``."""
    url = str(uri or "").strip()
    if url.startswith("ipfs://"):
        return IPFS_GATEWAY + url[len("ipfs://") :].lstrip("/")
    for prefix in _PUBLIC_IPFS_HOSTS:
        if url.startswith(prefix):
            return IPFS_GATEWAY + url[len(prefix) :]
    return url


class PumpFunApiClient:
    """Client for Pump.fun frontend / analytics HTTP APIs.

    This layer is intentionally read-only and metadata-focused. It does not build
    or submit on-chain transactions.
    """

    def __init__(
        self,
        base_url: str = "https://frontend-api-v3.pump.fun",
        *,
        timeout: float = 20.0,
        session: aiohttp.ClientSession | None = None,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        circuit_breaker_threshold: int = 5,
        circuit_cooldown_seconds: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://pump.fun",
            "User-Agent": "pumpfun-trading/0.1.0",
            **(headers or {}),
        }
        self._session = session
        self._circuit_failures = 0
        self._circuit_open_until = 0.0

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or getattr(self._session, "closed", False):
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        close_method = getattr(self._session, "close", None)
        if close_method is not None and inspect.iscoroutinefunction(close_method):
            await close_method()

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    def _record_circuit_failure(self) -> None:
        self._circuit_failures += 1
        if self._circuit_failures >= self.circuit_breaker_threshold:
            self._circuit_open_until = time.monotonic() + self.circuit_cooldown_seconds

    def _backoff_delay(self, attempt: int) -> float:
        return self.retry_backoff_seconds * (2**attempt)

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        session = await self._get_session()
        url = self._build_url(path)
        request_headers = {**self.headers, **(headers or {})}
        async with session.request(
            method, url, params=params, json=json, data=data, headers=request_headers
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise PumpFunApiHttpError(
                    f"PumpFun API {method.upper()} {path} failed: HTTP {resp.status} "
                    f":: {text[:500]}",
                    resp.status,
                )
            try:
                return json_module.loads(text) if text else {}
            except json_module.JSONDecodeError:
                return text

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if self._circuit_open_until > time.monotonic():
            raise RuntimeError(
                "PumpFun API circuit open; market data requests are temporarily "
                "disabled."
            )

        for attempt in range(self.max_retries + 1):
            try:
                result = await self._request_once(
                    method,
                    path,
                    params=params,
                    json=json,
                    data=data,
                    headers=headers,
                )
            except Exception as exc:
                if not self._should_retry(exc, attempt):
                    raise
                await asyncio.sleep(self._backoff_delay(attempt))
                continue
            self._circuit_failures = 0
            return result

        # Only reached with max_retries < 0 (no attempt at all): every attempt
        # above either returns or raises on the last try.
        raise RuntimeError(f"PumpFun API request failed for {method.upper()} {path}.")

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        """Whether a failed attempt is tried again (the last one trips the
        circuit). A 404 for a not-yet-indexed mint is an answer: retrying only
        adds ~3.5 s of backoff and must not trip the circuit (BUG-95)."""
        if isinstance(exc, PumpFunApiHttpError) and not exc.is_retryable:
            return False
        if attempt >= self.max_retries:
            self._record_circuit_failure()
            return False
        return True

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self.request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self.request(
            "POST", path, params=params, json=json, data=data, headers=headers
        )

    @staticmethod
    def _pick_first_mapping(payload: Any, *keys: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return {}

    async def get_liquidity_snapshot(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if not isinstance(payload, dict):
            return {}
        liquidity = (
            payload.get("liquidity")
            or payload.get("liquidityInfo")
            or payload.get("liquidity_snapshot")
            or payload.get("liquiditySnapshot")
        )
        if isinstance(liquidity, dict):
            return liquidity
        return {}

    async def get_holder_counts(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if not isinstance(payload, dict):
            return {}
        holders = (
            payload.get("holders")
            or payload.get("holderCounts")
            or payload.get("holder_count")
            or payload.get("holderCount")
        )
        if isinstance(holders, dict):
            return holders
        return {}

    async def get_token_supply(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if not isinstance(payload, dict):
            return {}
        supply = (
            payload.get("supply")
            or payload.get("tokenSupply")
            or payload.get("totalSupply")
            or payload.get("supplyInfo")
        )
        if isinstance(supply, dict):
            return supply
        return {}

    async def get_token_age(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if not isinstance(payload, dict):
            return {}
        age = (
            payload.get("age")
            or payload.get("tokenAge")
            or payload.get("createdAt")
            or payload.get("creationTimestamp")
            or payload.get("tokenAgeSeconds")
        )
        if isinstance(age, dict):
            return age
        if age is None:
            return {}
        return {"value": age}

    async def get_market_data_snapshot(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if not isinstance(payload, dict):
            return {"mint": mint, "payload": {}}
        return {
            "mint": mint,
            "name": payload.get("name")
            or payload.get("tokenName")
            or payload.get("displayName"),
            "market_cap_sol": payload.get("marketCapSol") or payload.get("marketCap"),
            "liquidity": await self.get_liquidity_snapshot(mint),
            "holders": await self.get_holder_counts(mint),
            "supply": await self.get_token_supply(mint),
            "age": await self.get_token_age(mint),
        }

    async def get_latest_coins(self, limit: int = 20, offset: int = 0, **kwargs) -> Any:
        params = {"limit": limit, "offset": offset, **kwargs}
        return await self.get("/coins", params=params)

    async def scan_active_coins(self, *, limit: int = 50, offset: int = 0) -> Any:
        """Recently traded coins still on their curve (record-only discovery).

        A single attempt outside the retry loop and circuit breaker, like
        :meth:`fetch_token_metadata`: a failing scan must never disable the API
        for screening.
        """
        params = {
            "limit": int(limit),
            "offset": int(offset),
            "sort": "last_trade_timestamp",
            "order": "DESC",
            "includeNsfw": "true",
            "complete": "false",
        }
        return await self._request_once("GET", "/coins", params=params)

    async def get_advanced_coins_list(
        self, *, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        params = {"limit": limit, "offset": offset, **kwargs}
        return await self.get(
            "https://advanced-api-v2.pump.fun/coins/list", params=params
        )

    async def get_coins_by_mints(
        self, mints: list[str], *, base_url: str = "https://frontend-api-v3.pump.fun"
    ) -> Any:
        # Reuse this client's session instead of leaking a new one per call (BUG-74).
        return await self.post(
            f"{base_url.rstrip('/')}/coins-v2/mints", json={"mints": mints}
        )

    @staticmethod
    def _first_coin(payload: Any) -> dict[str, Any] | None:
        """The first coin record of a ``coins-v2/mints`` answer: a list, or a
        mapping with a ``data`` or ``items`` list."""
        candidates: list[Any] = [payload]
        if isinstance(payload, dict):
            candidates = [payload.get("data"), payload.get("items")]
        for items in candidates:
            if isinstance(items, list) and items and isinstance(items[0], dict):
                return items[0]
        return None

    async def get_coin(self, mint: str) -> Any:
        try:
            return await self.get(f"/coins/{mint}")
        except RuntimeError as exc:
            error_text = str(exc)
            if (
                "HTTP 404" not in error_text
                and "HTTP 401" not in error_text
                and "HTTP 403" not in error_text
            ):
                raise

            payload = await self.post("/coins-v2/mints", json={"mints": [mint]})
            first = self._first_coin(payload)
            if first is not None:
                return first
            raise RuntimeError(
                f"Mint {mint} not found via the public Pump.fun metadata endpoints."
            ) from exc

    async def fetch_token_metadata(self, uri: str) -> dict[str, Any]:
        """Fetches a token's off-chain metadata JSON (name, socials) from its URI.

        Makes a single attempt outside the retry loop and circuit breaker, so a
        slow IPFS gateway can't disable the Pump.fun API for other callers (BUG-95).
        """
        url = resolve_metadata_uri(uri)
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Unsupported token metadata URI: {uri!r}")
        payload = await self._request_once("GET", url)
        return payload if isinstance(payload, dict) else {}

    async def get_coin_info(self, mint: str) -> dict[str, Any]:
        payload = await self.get_coin(mint)
        if isinstance(payload, dict):
            return payload
        raise ValueError(
            f"Unexpected payload for mint {mint}: {type(payload).__name__}"
        )

    async def get_coins_for_you(
        self, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        params = {"limit": limit, "offset": offset, **kwargs}
        return await self.get("/coins/for-you", params=params)

    async def get_coins_featured(
        self, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        params = {"limit": limit, "offset": offset, **kwargs}
        return await self.get("/coins/featured", params=params)

    async def get_coins_search(
        self, query: str, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        params = {"query": query, "limit": limit, "offset": offset, **kwargs}
        return await self.get("/coins/search", params=params)

    async def get_trades_for_mint(
        self, mint: str, limit: int = 50, offset: int = 0
    ) -> Any:
        return await self.get(
            f"/trades/all/{mint}", params={"limit": limit, "offset": offset}
        )

    async def get_trade_history(
        self, mint: str, limit: int = 50, offset: int = 0
    ) -> Any:
        return await self.get_trades_for_mint(mint, limit=limit, offset=offset)

    async def get_trade_count(self, mint: str) -> Any:
        return await self.get(f"/trades/count/{mint}")

    async def get_candlesticks(
        self, mint: str, *, interval: str = "1m", limit: int = 100
    ) -> Any:
        return await self.get(
            f"/candlesticks/{mint}", params={"interval": interval, "limit": limit}
        )

    async def get_sol_price(self) -> Any:
        return await self.get("/sol-price")

    async def get_creator_coins(
        self, creator: str, limit: int = 50, offset: int = 0
    ) -> Any:
        try:
            return await self.get(
                f"/coins/user-created-coins/{creator}",
                params={"limit": limit, "offset": offset},
            )
        except Exception:
            return await self.get(
                "/coins",
                params={"creator": creator, "limit": limit, "offset": offset},
            )

    async def get_market_overview(
        self, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        return await self.get_latest_coins(limit=limit, offset=offset, **kwargs)
