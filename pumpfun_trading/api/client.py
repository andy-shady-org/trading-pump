import asyncio
import inspect
import json as json_module
import time
from typing import Any, Dict, Optional

import aiohttp


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
        session: Optional[aiohttp.ClientSession] = None,
        headers: Optional[Dict[str, str]] = None,
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

    def _backoff_delay(self, attempt: int) -> float:
        return self.retry_backoff_seconds * (2**attempt)

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        session = await self._get_session()
        url = self._build_url(path)
        request_headers = {**self.headers, **(headers or {})}
        async with session.request(
            method, url, params=params, json=json, data=data, headers=request_headers
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(
                    f"PumpFun API {method.upper()} {path} failed: HTTP {resp.status} :: {text[:500]}"
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
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        if self._circuit_open_until > time.monotonic():
            raise RuntimeError(
                "PumpFun API circuit open; market data requests are temporarily disabled."
            )

        last_error: Exception | None = None
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
                self._circuit_failures = 0
                return result
            except (
                Exception
            ) as exc:  # pragma: no cover - retry path exercised via tests
                last_error = exc
                if attempt >= self.max_retries:
                    self._circuit_failures += 1
                    if self._circuit_failures >= self.circuit_breaker_threshold:
                        self._circuit_open_until = (
                            time.monotonic() + self.circuit_cooldown_seconds
                        )
                    raise
                await asyncio.sleep(self._backoff_delay(attempt))

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"PumpFun API request failed for {method.upper()} {path}.")

    async def get(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        return await self.request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
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
        client = PumpFunApiClient(base_url=base_url)
        return await client.post("/coins-v2/mints", json={"mints": mints})

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
            if isinstance(payload, list) and payload:
                first = payload[0]
                if isinstance(first, dict):
                    return first
            if isinstance(payload, dict):
                if isinstance(payload.get("data"), list) and payload["data"]:
                    first = payload["data"][0]
                    if isinstance(first, dict):
                        return first
                if isinstance(payload.get("items"), list) and payload["items"]:
                    first = payload["items"][0]
                    if isinstance(first, dict):
                        return first
            raise RuntimeError(
                f"Mint {mint} not found via the public Pump.fun metadata endpoints."
            ) from exc

    async def get_coin_info(self, mint: str) -> Dict[str, Any]:
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
