import json as json_module
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
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://pump.fun",
            "User-Agent": "pumpfun-trading/0.1.0",
            **(headers or {}),
        }
        self._session = session

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    def _build_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

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

    async def get_market_overview(
        self, limit: int = 20, offset: int = 0, **kwargs
    ) -> Any:
        return await self.get_latest_coins(limit=limit, offset=offset, **kwargs)
