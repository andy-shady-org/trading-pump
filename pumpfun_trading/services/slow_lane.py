"""Record-only data for the FEAT-65 slow lane (phase 0, rc.3).

Two collectors, both run by ``pumpfun-recorder`` as their own process, next to
(never inside) ``pumpbot``:

* :class:`QuoteRecorder` samples Jupiter swap quotes for a fixed token list at
  a few SOL sizes, buy and sell side, plus Jupiter's price / liquidity and the
  network's recent priority fees. A quote is only valid when it is taken, so
  this is the one dataset that cannot be fetched later.
* :func:`backfill_bars` downloads daily / hourly OHLCV bars from GeckoTerminal
  for the same list (history that can be fetched at any time).

Nothing here signs, sends or trades. Rows are tagged with ``venue`` and go to
their own JSONL files, away from the Pump.fun captures the replay tools read.
Both public APIs are used keyless and rate-limited; an optional
``PUMPFUN_JUPITER_API_KEY`` moves the quotes to the keyed host and is sent as a
header only, never as part of a URL (BUG-118).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pumpfun_trading.ops.redact import redact_text, redact_url

logger = logging.getLogger(__name__)

WSOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000

JUPITER_LITE_URL = "https://lite-api.jup.ag"
JUPITER_KEYED_URL = "https://api.jup.ag"
GECKOTERMINAL_URL = "https://api.geckoterminal.com/api/v2"
JUPITER_API_KEY_ENV = "PUMPFUN_JUPITER_API_KEY"

QUOTE_VENUE = "jupiter"
BAR_VENUE = "geckoterminal"
FEE_VENUE = "solana"
QUOTE_EVENT = "quote"
QUOTE_ERROR_EVENT = "quote_error"
PRICE_EVENT = "price"
FEE_EVENT = "fee_sample"
BAR_EVENT = "bar"
SLOW_LANE_EVENTS = frozenset(
    {QUOTE_EVENT, QUOTE_ERROR_EVENT, PRICE_EVENT, FEE_EVENT, BAR_EVENT}
)

DEFAULT_SIZES_SOL: tuple[float, ...] = (0.02, 0.1, 0.5)
DEFAULT_SLIPPAGE_BPS = 50
# Keyless lite-api allowed 5 requests per ~10 s when checked (2026-10-21);
# GeckoTerminal's public API refused the 5th request at a 2.5 s gap.
DEFAULT_QUOTE_REQUEST_GAP_SECONDS = 2.0
DEFAULT_BAR_REQUEST_GAP_SECONDS = 6.0
DEFAULT_QUOTE_INTERVAL_SECONDS = 300.0
DEFAULT_FEE_INTERVAL_SECONDS = 300.0
# Pools per fee sample (one RPC call each, on the operator's own RPC).
DEFAULT_FEE_MAX_POOLS = 12
MAX_TRACKED_POOLS = 256
HTTP_TIMEOUT_SECONDS = 15.0
# Longest wait for a rate-limit window to reset before giving up on a request.
MAX_RATE_LIMIT_WAIT_SECONDS = 30.0
# Wait after a 429 that names no reset time.
RATE_LIMIT_FALLBACK_WAIT_SECONDS = 10.0
RATE_LIMIT_RETRIES = 3
BAR_TIMEFRAMES = ("day", "hour", "minute")
BARS_PER_PAGE = 1000

# Reviewed default list (configs/slow_lane_tokens.json is the editable copy).
# SOL gets bars only, since it is the quote currency; USDC stands in for it.
DEFAULT_TOKENS: tuple[tuple[str, str], ...] = (
    ("SOL", WSOL_MINT),
    ("USDC", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    ("JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"),
    ("JTO", "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"),
    ("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
    ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
    ("PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"),
    ("RAY", "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"),
    ("ORCA", "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"),
    ("mSOL", "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"),
    ("jitoSOL", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"),
)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class HttpStatusError(RuntimeError):
    """A non-2xx answer; ``retry_after`` is set from rate-limit headers."""

    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class JsonHttp(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...

    async def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...

    async def close(self) -> None: ...


def _retry_after(headers: Mapping[str, str], now: float) -> float | None:
    raw = headers.get("Retry-After")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    reset = headers.get("x-ratelimit-reset")
    if reset is not None:
        try:
            return max(0.0, float(reset) - now)
        except ValueError:
            pass
    return None


class AiohttpJson:
    """Minimal JSON-over-HTTP client with bounded timeouts."""

    def __init__(self, timeout_seconds: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self._session: Any = None

    async def _get_session(self) -> Any:
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
            )
        return self._session

    async def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        session = await self._get_session()
        async with session.request(method, url, **kwargs) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise HttpStatusError(
                    resp.status,
                    f"HTTP {resp.status} from {redact_url(url)}: "
                    f"{redact_text(text[:200])}",
                    _retry_after(resp.headers, time.time()),
                )
            return json.loads(text) if text else None

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return await self._send(
            "GET", url, params=dict(params or {}), headers=dict(headers or {})
        )

    async def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return await self._send("POST", url, json=payload, headers=dict(headers or {}))

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


class RequestPacer:
    """Keeps at least ``gap_seconds`` between requests to one provider."""

    def __init__(
        self,
        gap_seconds: float,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self.gap_seconds = max(0.0, float(gap_seconds))
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    async def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.gap_seconds - (now - self._last)
            if remaining > 0:
                await self._sleep(remaining)
                now = self._clock()
        self._last = now


async def _paced(
    pacer: RequestPacer, call: Callable[[], Awaitable[Any]], sleep: Sleep
) -> Any:
    """One paced request, retried after a 429 or 5xx with growing, bounded waits.

    GeckoTerminal answers ``Retry-After: 0`` while still limiting and returns
    the odd transient 500, so a zero or missing reset time falls back to
    ``RATE_LIMIT_FALLBACK_WAIT_SECONDS`` × attempt.
    """
    attempt = 0
    while True:
        await pacer.wait()
        try:
            return await call()
        except HttpStatusError as exc:
            retryable = exc.status == 429 or exc.status >= 500
            if not retryable or attempt >= RATE_LIMIT_RETRIES:
                raise
            attempt += 1
            wait = exc.retry_after or RATE_LIMIT_FALLBACK_WAIT_SECONDS * attempt
            await sleep(min(MAX_RATE_LIMIT_WAIT_SECONDS, wait))


@dataclass(frozen=True)
class SlowLaneToken:
    symbol: str
    mint: str


def default_tokens() -> list[SlowLaneToken]:
    return [SlowLaneToken(symbol, mint) for symbol, mint in DEFAULT_TOKENS]


def load_token_list(path: str | Path | None) -> list[SlowLaneToken]:
    """Read ``{"tokens": [{"symbol", "mint"}]}``; ``None`` gives the default list."""
    if path is None:
        return default_tokens()
    raw = json.loads(Path(path).read_text())
    entries = raw.get("tokens") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: expected a non-empty 'tokens' list.")
    tokens: list[SlowLaneToken] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("mint"):
            raise ValueError(f"{path}: every token needs a 'mint'.")
        mint = str(entry["mint"]).strip()
        if mint in seen:
            raise ValueError(f"{path}: duplicate mint {mint}.")
        seen.add(mint)
        tokens.append(SlowLaneToken(str(entry.get("symbol") or mint[:6]), mint))
    return tokens


def parse_sizes(text: str | Sequence[float] | None) -> tuple[float, ...]:
    """``"0.02,0.1,0.5"`` → sizes in SOL (positive, de-duplicated, sorted)."""
    if text is None:
        return DEFAULT_SIZES_SOL
    parts: Iterable[Any] = text.split(",") if isinstance(text, str) else text
    sizes = sorted({float(p) for p in parts if str(p).strip()})
    if not sizes or any(s <= 0 for s in sizes):
        raise ValueError("quote sizes must be positive SOL amounts.")
    return tuple(sizes)


class JupiterClient:
    """Keyless (lite) or keyed Jupiter quote and price API."""

    def __init__(
        self,
        http: JsonHttp,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.http = http
        self._api_key = (api_key or "").strip() or None
        self.base_url = (
            base_url or (JUPITER_KEYED_URL if self._api_key else JUPITER_LITE_URL)
        ).rstrip("/")

    @classmethod
    def from_env(cls, http: JsonHttp) -> JupiterClient:
        return cls(http, api_key=os.getenv(JUPITER_API_KEY_ENV))

    @property
    def keyed(self) -> bool:
        return self._api_key is not None

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key} if self._api_key else {}

    async def quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
    ) -> dict[str, Any]:
        payload = await self.http.get_json(
            f"{self.base_url}/swap/v1/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(int(amount)),
                "slippageBps": str(int(slippage_bps)),
                "swapMode": "ExactIn",
            },
            headers=self._headers(),
        )
        if not isinstance(payload, dict) or "outAmount" not in payload:
            raise ValueError(f"unexpected quote payload: {str(payload)[:200]}")
        return payload

    async def prices(self, mints: Sequence[str]) -> dict[str, Any]:
        payload = await self.http.get_json(
            f"{self.base_url}/price/v3",
            params={"ids": ",".join(mints)},
            headers=self._headers(),
        )
        return payload if isinstance(payload, dict) else {}


class GeckoTerminalClient:
    """Public GeckoTerminal pool lookup and OHLCV bars (no key)."""

    def __init__(self, http: JsonHttp, *, base_url: str = GECKOTERMINAL_URL) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def top_pool(self, mint: str) -> dict[str, Any] | None:
        payload = await self.http.get_json(
            f"{self.base_url}/networks/solana/tokens/{mint}/pools",
            params={"page": 1},
        )
        pools = payload.get("data") if isinstance(payload, dict) else None
        if not pools:
            return None
        attrs = pools[0].get("attributes") or {}
        address = attrs.get("address")
        if not address:
            return None
        return {
            "address": str(address),
            "name": attrs.get("name"),
            "reserve_usd": _float(attrs.get("reserve_in_usd")),
        }

    async def ohlcv(
        self,
        pool: str,
        *,
        timeframe: str,
        before_timestamp: int | None = None,
        limit: int = BARS_PER_PAGE,
        token_mint: str | None = None,
    ) -> list[list[float]]:
        params: dict[str, Any] = {"limit": int(limit), "currency": "usd"}
        if before_timestamp is not None:
            params["before_timestamp"] = int(before_timestamp)
        if token_mint:
            params["token"] = token_mint
        payload = await self.http.get_json(
            f"{self.base_url}/networks/solana/pools/{pool}/ohlcv/{timeframe}",
            params=params,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        attrs = (data or {}).get("attributes") or {}
        bars = attrs.get("ohlcv_list") or []
        return [list(b) for b in bars if isinstance(b, list) and len(b) >= 6]


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _route(quote: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(venue labels, pool accounts) of each route leg."""
    labels: list[str] = []
    pools: list[str] = []
    for leg in quote.get("routePlan") or []:
        info = leg.get("swapInfo") if isinstance(leg, dict) else None
        if not isinstance(info, dict):
            continue
        labels.append(str(info.get("label") or "?"))
        if info.get("ammKey"):
            pools.append(str(info["ammKey"]))
    return labels, pools


def quote_row(
    quote: Mapping[str, Any],
    *,
    token: SlowLaneToken,
    side: str,
    size_sol: float,
    decimals: int | None,
    now: float,
    latency_ms: float,
) -> dict[str, Any]:
    """One ``event: "quote"`` row. Buy: SOL → token; sell: the bought tokens → SOL,
    so ``round_trip_ratio`` is what a full in-and-out at this size returns."""
    in_amount = int(quote.get("inAmount") or 0)
    out_amount = int(quote.get("outAmount") or 0)
    route, pools = _route(quote)
    row: dict[str, Any] = {
        "timestamp": now,
        "event": QUOTE_EVENT,
        "venue": QUOTE_VENUE,
        "symbol": token.symbol,
        "mint": token.mint,
        "side": side,
        "size_sol": size_sol,
        "in_amount": in_amount,
        "out_amount": out_amount,
        "other_amount_threshold": int(quote.get("otherAmountThreshold") or 0),
        "price_impact_pct": _float(quote.get("priceImpactPct")),
        "slippage_bps": quote.get("slippageBps"),
        "route": route,
        "pools": pools,
        "hops": len(route),
        "context_slot": quote.get("contextSlot"),
        "latency_ms": round(latency_ms, 1),
    }
    if decimals is not None:
        row["decimals"] = decimals
    if side == "buy" and out_amount > 0 and decimals is not None:
        row["price_sol"] = size_sol / (out_amount / 10**decimals)
    if side == "sell":
        out_sol = out_amount / LAMPORTS_PER_SOL
        ratio = out_sol / size_sol if size_sol > 0 else 0.0
        row["out_sol"] = out_sol
        row["round_trip_ratio"] = round(ratio, 8)
        row["round_trip_cost_bps"] = round((1.0 - ratio) * 10_000, 2)
    return row


def price_rows(
    payload: Mapping[str, Any], tokens: Sequence[SlowLaneToken], now: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for token in tokens:
        info = payload.get(token.mint)
        if not isinstance(info, dict):
            continue
        rows.append(
            {
                "timestamp": now,
                "event": PRICE_EVENT,
                "venue": QUOTE_VENUE,
                "symbol": token.symbol,
                "mint": token.mint,
                "usd_price": _float(info.get("usdPrice")),
                "liquidity_usd": _float(info.get("liquidity")),
                "price_change_24h_pct": _float(info.get("priceChange24h")),
                "decimals": info.get("decimals"),
                "block_id": info.get("blockId"),
            }
        )
    return rows


def _percentile(values: Sequence[int], pct: float) -> int:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return int(ordered[index])


def fee_row(
    result: Any,
    now: float,
    *,
    account: str | None = None,
    symbols: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Summarise ``getRecentPrioritizationFees`` (micro-lamports per CU).

    For one writable pool ``account`` each slot reports the lowest fee a
    transaction that locked it paid, and 0 when none touched it, so the
    ``nonzero_*`` fields are the useful ones; ``account=None`` is the
    network-wide sample.
    """
    if not isinstance(result, list) or not result:
        return None
    entries = [r for r in result if isinstance(r, dict)]
    fees = [int(r.get("prioritizationFee") or 0) for r in entries]
    slots = [int(r.get("slot") or 0) for r in entries]
    if not fees:
        return None
    nonzero = [f for f in fees if f > 0]
    row: dict[str, Any] = {
        "timestamp": now,
        "event": FEE_EVENT,
        "venue": FEE_VENUE,
        "account": account,
        "symbols": sorted(set(symbols)),
        "slots": len(fees),
        "min_slot": min(slots),
        "max_slot": max(slots),
        "p50": _percentile(fees, 0.5),
        "p90": _percentile(fees, 0.9),
        "max": max(fees),
        "mean": round(statistics.fmean(fees), 1),
        "nonzero_share": round(len(nonzero) / len(fees), 4),
    }
    if nonzero:
        row["nonzero_p50"] = _percentile(nonzero, 0.5)
        row["nonzero_p90"] = _percentile(nonzero, 0.9)
    return row


def rpc_url_from_env() -> str | None:
    url = os.getenv("PUMPFUN_RPC_URL") or os.getenv("HELIUS_RPC_URL")
    if url:
        return url.strip() or None
    many = os.getenv("PUMPFUN_RPC_URLS") or ""
    first = next((u.strip() for u in many.split(",") if u.strip()), None)
    return first


class RowSink(Protocol):
    def record_snapshot(self, record: dict[str, Any]) -> None: ...


@dataclass
class QuoteRecorderStats:
    cycles: int = 0
    quotes: int = 0
    quote_errors: int = 0
    price_rows: int = 0
    price_errors: int = 0
    fee_samples: int = 0
    fee_errors: int = 0
    rate_limited: int = 0


class QuoteRecorder:
    """Samples quotes, prices and priority fees into a row sink."""

    def __init__(
        self,
        jupiter: JupiterClient,
        sink: RowSink,
        *,
        tokens: Sequence[SlowLaneToken],
        sizes_sol: Sequence[float] = DEFAULT_SIZES_SOL,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
        request_gap_seconds: float = DEFAULT_QUOTE_REQUEST_GAP_SECONDS,
        rpc_http: JsonHttp | None = None,
        rpc_url: str | None = None,
        fee_interval_seconds: float = DEFAULT_FEE_INTERVAL_SECONDS,
        fee_max_pools: int = DEFAULT_FEE_MAX_POOLS,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.time,
        monotonic: Clock = time.monotonic,
    ) -> None:
        self.jupiter = jupiter
        self.sink = sink
        self.tokens = list(tokens)
        self.quote_tokens = [t for t in self.tokens if t.mint != WSOL_MINT]
        self.sizes_sol = tuple(sizes_sol)
        self.slippage_bps = int(slippage_bps)
        self.rpc_http = rpc_http
        self.rpc_url = rpc_url
        self.fee_interval_seconds = float(fee_interval_seconds)
        self.fee_max_pools = max(0, int(fee_max_pools))
        self._pool_symbols: dict[str, set[str]] = {}
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic
        self.pacer = RequestPacer(request_gap_seconds, sleep=sleep, clock=monotonic)
        self.decimals: dict[str, int] = {}
        self.stats = QuoteRecorderStats()
        self._last_fee_at: float | None = None

    @property
    def requests_per_cycle(self) -> int:
        return 1 + 2 * len(self.quote_tokens) * len(self.sizes_sol)

    async def _paced(self, call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await _paced(self.pacer, call, self._sleep)
        except HttpStatusError as exc:
            if exc.status == 429:
                self.stats.rate_limited += 1
            raise

    async def sample_prices(self) -> None:
        try:
            payload = await self._paced(
                lambda: self.jupiter.prices([t.mint for t in self.tokens])
            )
        except Exception as exc:
            self.stats.price_errors += 1
            logger.debug("Jupiter price sample failed: %s", redact_text(exc))
            return
        for row in price_rows(payload, self.tokens, self._clock()):
            if isinstance(row.get("decimals"), int):
                self.decimals[row["mint"]] = row["decimals"]
            self.sink.record_snapshot(row)
            self.stats.price_rows += 1

    def _error(
        self, token: SlowLaneToken, side: str, size_sol: float, exc: Exception
    ) -> None:
        self.stats.quote_errors += 1
        self.sink.record_snapshot(
            {
                "timestamp": self._clock(),
                "event": QUOTE_ERROR_EVENT,
                "venue": QUOTE_VENUE,
                "symbol": token.symbol,
                "mint": token.mint,
                "side": side,
                "size_sol": size_sol,
                "status": getattr(exc, "status", None),
                "error": redact_text(str(exc))[:200],
            }
        )

    async def _quote(
        self, token: SlowLaneToken, side: str, size_sol: float, **kwargs: Any
    ) -> dict[str, Any] | None:
        timing = {"started": 0.0, "ended": 0.0}

        async def call() -> dict[str, Any]:
            # Latency of the request itself, not of the pacer's wait.
            timing["started"] = self._monotonic()
            try:
                return await self.jupiter.quote(
                    slippage_bps=self.slippage_bps, **kwargs
                )
            finally:
                timing["ended"] = self._monotonic()

        try:
            quote = await self._paced(call)
        except Exception as exc:
            self._error(token, side, size_sol, exc)
            return None
        row = quote_row(
            quote,
            token=token,
            side=side,
            size_sol=size_sol,
            decimals=self.decimals.get(token.mint),
            now=self._clock(),
            latency_ms=(timing["ended"] - timing["started"]) * 1000.0,
        )
        for pool in row["pools"]:
            # Most recently quoted first, so the fee sample follows the routes.
            symbols = self._pool_symbols.pop(pool, set())
            symbols.add(token.symbol)
            self._pool_symbols[pool] = symbols
        while len(self._pool_symbols) > MAX_TRACKED_POOLS:
            self._pool_symbols.pop(next(iter(self._pool_symbols)))
        self.sink.record_snapshot(row)
        self.stats.quotes += 1
        return row

    async def sample_quotes(self, token: SlowLaneToken) -> None:
        for size_sol in self.sizes_sol:
            buy = await self._quote(
                token,
                "buy",
                size_sol,
                input_mint=WSOL_MINT,
                output_mint=token.mint,
                amount=int(round(size_sol * LAMPORTS_PER_SOL)),
            )
            if buy is None or int(buy["out_amount"]) <= 0:
                continue
            await self._quote(
                token,
                "sell",
                size_sol,
                input_mint=token.mint,
                output_mint=WSOL_MINT,
                amount=int(buy["out_amount"]),
            )

    def fee_accounts(self) -> list[tuple[str | None, list[str]]]:
        """Network-wide sample first, then the most recently quoted pools."""
        recent = list(self._pool_symbols.items())[::-1][: self.fee_max_pools]
        return [(None, []), *((pool, sorted(s)) for pool, s in recent)]

    async def _fee_sample(self, account: str | None, symbols: list[str]) -> None:
        if self.rpc_http is None or not self.rpc_url:
            return
        try:
            payload = await self.rpc_http.post_json(
                self.rpc_url,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getRecentPrioritizationFees",
                    "params": [[account]] if account else [],
                },
            )
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(str(payload["error"])[:200])
            result = payload.get("result") if isinstance(payload, dict) else None
            row = fee_row(result, self._clock(), account=account, symbols=symbols)
        except Exception as exc:
            self.stats.fee_errors += 1
            logger.debug("Priority fee sample failed: %s", redact_text(exc))
            return
        if row is not None:
            self.sink.record_snapshot(row)
            self.stats.fee_samples += 1

    async def sample_fees(self) -> None:
        if self.rpc_http is None or not self.rpc_url:
            return
        now = self._monotonic()
        if (
            self._last_fee_at is not None
            and now - self._last_fee_at < self.fee_interval_seconds
        ):
            return
        self._last_fee_at = now
        for account, symbols in self.fee_accounts():
            await self._fee_sample(account, symbols)

    async def run_cycle(self) -> None:
        await self.sample_prices()
        for token in self.quote_tokens:
            await self.sample_quotes(token)
        # After the quotes, so the pool samples follow this cycle's routes.
        await self.sample_fees()
        self.stats.cycles += 1

    async def run(
        self,
        *,
        interval_seconds: float = DEFAULT_QUOTE_INTERVAL_SECONDS,
        stop: asyncio.Event | None = None,
        duration_seconds: float | None = None,
        max_cycles: int | None = None,
    ) -> QuoteRecorderStats:
        """Cycle until ``stop``, the duration or ``max_cycles``; never raises
        for a provider failure (each one is a counted row or stat)."""
        stop = stop or asyncio.Event()
        started = self._monotonic()

        def finished() -> bool:
            if stop.is_set():
                return True
            if max_cycles is not None and self.stats.cycles >= max_cycles:
                return True
            return bool(
                duration_seconds and self._monotonic() - started >= duration_seconds
            )

        while not finished():
            cycle_started = self._monotonic()
            await self.run_cycle()
            next_at = cycle_started + max(1.0, float(interval_seconds))
            if duration_seconds:
                next_at = min(next_at, started + duration_seconds)
            while not finished() and self._monotonic() < next_at:
                await self._sleep(min(1.0, next_at - self._monotonic()))
        return self.stats


@dataclass
class BackfillStats:
    tokens: int = 0
    pools_missing: int = 0
    bars: int = 0
    requests: int = 0
    errors: int = 0
    # Paging stopped at the public API's history limit (it answers 401).
    history_limited: int = 0
    failures: list[str] = field(default_factory=list)

    def fail(self, what: str, exc: Exception) -> None:
        self.errors += 1
        self.failures.append(f"{what}: {redact_text(exc)[:160]}")
        logger.warning("Bar backfill %s failed: %s", what, redact_text(exc))


def bar_row(
    bar: Sequence[float],
    *,
    token: SlowLaneToken,
    pool: Mapping[str, Any],
    timeframe: str,
) -> dict[str, Any]:
    ts, open_, high, low, close, volume = (float(v) for v in bar[:6])
    return {
        "timestamp": ts,
        "event": BAR_EVENT,
        "venue": BAR_VENUE,
        "symbol": token.symbol,
        "mint": token.mint,
        "pool": pool.get("address"),
        "pool_name": pool.get("name"),
        "timeframe": timeframe,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume_usd": volume,
    }


async def backfill_bars(
    gecko: GeckoTerminalClient,
    sink: RowSink,
    *,
    tokens: Sequence[SlowLaneToken],
    timeframes: Sequence[str] = ("day", "hour"),
    max_pages: int = 6,
    request_gap_seconds: float = DEFAULT_BAR_REQUEST_GAP_SECONDS,
    sleep: Sleep = asyncio.sleep,
    monotonic: Clock = time.monotonic,
) -> BackfillStats:
    """Page bars back in time from each token's top pool, oldest page last.

    Prices are USD for the token itself (``token=<mint>``), so the pool's side
    does not matter. Bars are de-duplicated per token and timeframe.
    """
    for timeframe in timeframes:
        if timeframe not in BAR_TIMEFRAMES:
            raise ValueError(f"unknown bar timeframe {timeframe!r}.")
    pacer = RequestPacer(request_gap_seconds, sleep=sleep, clock=monotonic)
    stats = BackfillStats()
    for token in tokens:
        stats.tokens += 1
        try:
            stats.requests += 1
            pool = await _paced(pacer, lambda: gecko.top_pool(token.mint), sleep)
        except Exception as exc:
            stats.fail(f"{token.symbol} pool", exc)
            continue
        if pool is None:
            stats.pools_missing += 1
            continue
        for timeframe in timeframes:
            seen: set[float] = set()
            before: int | None = None
            for page_index in range(max(1, int(max_pages))):
                try:
                    stats.requests += 1
                    page = await _paced(
                        pacer,
                        lambda: gecko.ohlcv(
                            pool["address"],
                            timeframe=timeframe,
                            before_timestamp=before,
                            token_mint=token.mint,
                        ),
                        sleep,
                    )
                except HttpStatusError as exc:
                    if exc.status == 401 and page_index > 0:
                        stats.history_limited += 1
                    else:
                        stats.fail(f"{token.symbol} {timeframe}", exc)
                    break
                except Exception as exc:
                    stats.fail(f"{token.symbol} {timeframe}", exc)
                    break
                fresh = [b for b in page if float(b[0]) not in seen]
                for bar in fresh:
                    seen.add(float(bar[0]))
                    sink.record_snapshot(
                        bar_row(bar, token=token, pool=pool, timeframe=timeframe)
                    )
                    stats.bars += 1
                if len(page) < BARS_PER_PAGE or not fresh:
                    break
                before = int(min(float(b[0]) for b in page))
    return stats


__all__ = [
    "AiohttpJson",
    "BackfillStats",
    "GeckoTerminalClient",
    "HttpStatusError",
    "JupiterClient",
    "QuoteRecorder",
    "QuoteRecorderStats",
    "RequestPacer",
    "SLOW_LANE_EVENTS",
    "SlowLaneToken",
    "backfill_bars",
    "bar_row",
    "default_tokens",
    "fee_row",
    "load_token_list",
    "parse_sizes",
    "price_rows",
    "quote_row",
    "rpc_url_from_env",
]
