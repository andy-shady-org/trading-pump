"""Record-only cross-chain market data (FEAT-74).

The Pump.fun lanes are not profitable on paper (rc.3 to rc.6), and the coins
the operator sees running are mostly elsewhere: other Solana launchpads, Base
and BSC, and coins days or weeks old. This collector records that market so
entry rules can be tested on it before anything is built to trade there.

Run by ``trading-pump record --market`` as its own process, next to (never
inside) a trading-core run. Nothing here signs, sends or trades, and no RPC credits
are used: both data sources are free public APIs, used keyless and paced.

* **Discovery** (GeckoTerminal): every new pool on each chain
  (``new_pools``, paged until a known pool), and every ``list_interval`` the
  chain's momentum lists (trending over 5 minutes and 1 hour, top 24 h
  volume). A pool is picked when it appears, before anyone knows how it does,
  so a rule tested on the data has no hindsight in its selection.
* **Following** (DexScreener, 30 pools per call): each picked pool is
  snapshotted on an age-based cadence (30 s for 30 minutes, 2 minutes to
  6 hours, 10 minutes to 7 days) until it is dead (no trades in an hour and
  below the liquidity floor), missing from DexScreener, or too old. A
  snapshot is written only when the pool changed, or at least every
  ``heartbeat_seconds``.

Rows (``venue: "market"``): ``market_pool`` (a pool appeared, with its
GeckoTerminal state and whether it is followed), ``market_list`` (one
momentum list, in rank order), ``market_snapshot`` (DexScreener state of a
followed pool), ``market_end`` (why a pool stopped being followed) and
``market_stats`` (counters, every ``stats_interval``). They go to their own
JSONL files, away from the Pump.fun captures the replay tools read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from trading_pump.services.slow_lane import (
    GECKOTERMINAL_URL,
    Clock,
    HttpStatusError,
    JsonHttp,
    RequestPacer,
    RowSink,
    Sleep,
    _paced,
)
from trading_pump.strategies.observation import in_sample

logger = logging.getLogger(__name__)

VENUE = "market"
POOL_EVENT = "market_pool"
LIST_EVENT = "market_list"
SNAPSHOT_EVENT = "market_snapshot"
END_EVENT = "market_end"
STATS_EVENT = "market_stats"
MARKET_EVENTS = frozenset(
    {POOL_EVENT, LIST_EVENT, SNAPSHOT_EVENT, END_EVENT, STATS_EVENT}
)

DEXSCREENER_URL = "https://api.dexscreener.com"
# Chain name -> (GeckoTerminal network id, DexScreener chain id).
CHAINS: dict[str, tuple[str, str]] = {
    "solana": ("solana", "solana"),
    "base": ("base", "base"),
    "bsc": ("bsc", "bsc"),
    "eth": ("eth", "ethereum"),
}
# Ethereum gas makes small trades uneconomic: off unless asked for.
DEFAULT_CHAINS: tuple[str, ...] = ("solana", "base", "bsc")
# Share of new pools followed per ``chain:dex`` (GeckoTerminal dex id); every
# other new pool is followed. Pump.fun curves are 85-90% of Solana's new pools
# and the bot's own launch sample already records them (FEAT-72).
DEFAULT_SAMPLE: dict[str, float] = {"solana:pump-fun": 0.1}
SAMPLE_SALT = "market:"
# (max age in seconds, snapshot interval in seconds), youngest first.
DEFAULT_TIERS: tuple[tuple[float, float], ...] = (
    (1_800.0, 30.0),
    (21_600.0, 120.0),
    (604_800.0, 600.0),
)
# Momentum lists: (name, GeckoTerminal path under the network, query).
MOMENTUM_LISTS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("trending_5m", "trending_pools", {"duration": "5m"}),
    ("trending_1h", "trending_pools", {"duration": "1h"}),
    ("top_volume_24h", "pools", {"sort": "h24_volume_usd_desc"}),
)
# GeckoTerminal's public API refused requests below about 2.5 s apart (slow
# lane, 2026-10-21) and rate-limited minute bars at about 6 a minute
# (2026-10-26): 6 s keeps discovery plus lists at about 7 requests a minute.
DEFAULT_GECKO_GAP_SECONDS = 6.0
# DexScreener allows 300 pair requests a minute; stay at 240.
DEFAULT_DEXSCREENER_GAP_SECONDS = 0.25
DEXSCREENER_BATCH = 30
DEFAULT_DISCOVERY_INTERVAL_SECONDS = 60.0
DEFAULT_LIST_INTERVAL_SECONDS = 300.0
DEFAULT_MAX_NEW_POOL_PAGES = 4
DEFAULT_DEAD_AFTER_SECONDS = 3_600.0
DEFAULT_MIN_LIQUIDITY_USD = 1_000.0
DEFAULT_HEARTBEAT_SECONDS = 1_800.0
DEFAULT_MAX_FOLLOWED = 20_000
DEFAULT_STATS_INTERVAL_SECONDS = 600.0
DEFAULT_STATE_INTERVAL_SECONDS = 60.0
# Snapshots in a row a pool may be absent from DexScreener before it ends,
# and never in its first 10 minutes (DexScreener can lag a new pool).
MISSING_LIMIT = 5
MISSING_GRACE_SECONDS = 600.0
# New-pool addresses remembered per chain to find where the last page ended.
SEEN_PER_CHAIN = 5_000
STATE_VERSION = 1


def _gecko_items(payload: Any) -> list[Any]:
    """The ``data`` list of a GeckoTerminal answer; empty for anything else."""
    return (payload or {}).get("data") or [] if isinstance(payload, dict) else []


@dataclass
class MarketRecorderConfig:
    chains: tuple[str, ...] = DEFAULT_CHAINS
    sample: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SAMPLE))
    tiers: tuple[tuple[float, float], ...] = DEFAULT_TIERS
    discovery_interval_seconds: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS
    list_interval_seconds: float = DEFAULT_LIST_INTERVAL_SECONDS
    max_new_pool_pages: int = DEFAULT_MAX_NEW_POOL_PAGES
    dead_after_seconds: float = DEFAULT_DEAD_AFTER_SECONDS
    min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    max_followed: int = DEFAULT_MAX_FOLLOWED
    gecko_gap_seconds: float = DEFAULT_GECKO_GAP_SECONDS
    dexscreener_gap_seconds: float = DEFAULT_DEXSCREENER_GAP_SECONDS
    stats_interval_seconds: float = DEFAULT_STATS_INTERVAL_SECONDS
    state_interval_seconds: float = DEFAULT_STATE_INTERVAL_SECONDS
    lists: bool = True

    def __post_init__(self) -> None:
        unknown = [c for c in self.chains if c not in CHAINS]
        if not self.chains or unknown:
            raise ValueError(
                f"unknown chain(s) {unknown or '(none)'}; known: {', '.join(CHAINS)}"
            )
        if not self.tiers or any(a <= 0 or i <= 0 for a, i in self.tiers):
            raise ValueError("follow tiers need positive ages and intervals")
        ages = [a for a, _ in self.tiers]
        if ages != sorted(ages):
            raise ValueError("follow tiers must be ordered by age")
        for key, share in self.sample.items():
            if ":" not in key or not 0.0 <= float(share) <= 1.0:
                raise ValueError(f"sample {key}={share}: use chain:dex=0..1")

    @property
    def max_age_seconds(self) -> float:
        return self.tiers[-1][0]

    def interval_for(self, age: float) -> float:
        for max_age, interval in self.tiers:
            if age <= max_age:
                return interval
        return self.tiers[-1][1]

    def share_for(self, chain: str, dex: str) -> float:
        return float(self.sample.get(f"{chain}:{dex}", 1.0))


def parse_sample(text: str | None) -> dict[str, float]:
    """``chain:dex=share,...`` (``--market-sample``); empty keeps the default."""
    if not text:
        return dict(DEFAULT_SAMPLE)
    out: dict[str, float] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            raise ValueError(f"--market-sample {part!r}: expected chain:dex=share")
        out[key.strip()] = float(value)
    return out


def parse_chains(text: str | None) -> tuple[str, ...]:
    if not text:
        return DEFAULT_CHAINS
    return tuple(c.strip().lower() for c in text.split(",") if c.strip())


@dataclass
class FollowedPool:
    chain: str
    pool: str
    source: str
    first_seen: float
    created_at: float | None = None
    rank: int | None = None
    last_snapshot_at: float = 0.0
    last_written_at: float = 0.0
    snapshots: int = 0
    missing: int = 0
    signature: list[Any] = field(default_factory=list)
    # Used to find the pool on DexScreener when the pair lookup misses it.
    base_token: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.chain, self.pool)


@dataclass
class MarketRecorderStats:
    discovery_calls: int = 0
    list_calls: int = 0
    snapshot_calls: int = 0
    new_pools: int = 0
    followed: int = 0
    list_entries: int = 0
    snapshots: int = 0
    snapshots_unchanged: int = 0
    token_lookups: int = 0
    token_matched: int = 0
    ended: dict[str, int] = field(default_factory=dict)
    discovery_gaps: int = 0
    full: int = 0
    errors: int = 0
    rate_limited: int = 0


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _epoch(text: Any) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _rel_id(item: Mapping[str, Any], name: str, network: str) -> str | None:
    """A relationship id without GeckoTerminal's ``<network>_`` prefix."""
    data = ((item.get("relationships") or {}).get(name) or {}).get("data") or {}
    raw = data.get("id")
    if not isinstance(raw, str):
        return None
    prefix = f"{network}_"
    return raw[len(prefix) :] if raw.startswith(prefix) else raw


def gecko_pool_fields(item: Mapping[str, Any], network: str) -> dict[str, Any]:
    """The compact state of one GeckoTerminal pool record."""
    attrs = item.get("attributes") or {}
    volume = attrs.get("volume_usd") or {}
    change = attrs.get("price_change_percentage") or {}
    txns = (attrs.get("transactions") or {}).get("h1") or {}
    return {
        "pool": attrs.get("address"),
        "name": attrs.get("name"),
        "dex": _rel_id(item, "dex", network),
        "base_token": _rel_id(item, "base_token", network),
        "quote_token": _rel_id(item, "quote_token", network),
        "created_at": _epoch(attrs.get("pool_created_at")),
        "price_usd": _float(attrs.get("base_token_price_usd")),
        "liquidity_usd": _float(attrs.get("reserve_in_usd")),
        "fdv_usd": _float(attrs.get("fdv_usd")),
        "market_cap_usd": _float(attrs.get("market_cap_usd")),
        "volume_usd": {k: _float(volume.get(k)) for k in ("m5", "h1", "h24")},
        "price_change_pct": {k: _float(change.get(k)) for k in ("m5", "h1", "h24")},
        "txns_h1": [txns.get("buys"), txns.get("sells")],
    }


def dexscreener_snapshot(pair: Mapping[str, Any]) -> dict[str, Any]:
    """The compact state of one DexScreener pair."""
    txns = pair.get("txns") or {}
    volume = pair.get("volume") or {}
    change = pair.get("priceChange") or {}

    def counts(window: str) -> list[Any]:
        row = txns.get(window) or {}
        return [row.get("buys"), row.get("sells")]

    return {
        "price_usd": _float(pair.get("priceUsd")),
        "price_native": _float(pair.get("priceNative")),
        "liquidity_usd": _float((pair.get("liquidity") or {}).get("usd")),
        "fdv_usd": _float(pair.get("fdv")),
        "market_cap_usd": _float(pair.get("marketCap")),
        "volume_usd": {k: _float(volume.get(k)) for k in ("m5", "h1", "h6", "h24")},
        "price_change_pct": {
            k: _float(change.get(k)) for k in ("m5", "h1", "h6", "h24")
        },
        "txns": {k: counts(k) for k in ("m5", "h1", "h24")},
    }


def _signature(snap: Mapping[str, Any]) -> list[Any]:
    """What makes a snapshot worth writing: price, liquidity, recent trades."""
    txns = snap.get("txns") or {}
    return [
        snap.get("price_usd"),
        snap.get("liquidity_usd"),
        txns.get("m5"),
        txns.get("h1"),
    ]


def _pair_key(pair: Mapping[str, Any]) -> str:
    """A DexScreener pair address as GeckoTerminal names the pool: four.meme
    curves are listed as ``<token>:4meme``, EVM addresses in any case."""
    return str(pair.get("pairAddress") or "").lower().split(":")[0]


def _liquidity(pair: Mapping[str, Any]) -> float:
    return _float((pair.get("liquidity") or {}).get("usd")) or 0.0


def _trades(counts: Any) -> int:
    if not isinstance(counts, (list, tuple)):
        return 0
    return sum(int(c) for c in counts if isinstance(c, (int, float)))


class MarketRecorder:
    """Discovers pools on several chains and follows them into a row sink."""

    def __init__(
        self,
        http: JsonHttp,
        sink: RowSink,
        config: MarketRecorderConfig | None = None,
        *,
        state_path: str | Path | None = None,
        gecko_url: str = GECKOTERMINAL_URL,
        dexscreener_url: str = DEXSCREENER_URL,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.time,
        monotonic: Clock = time.monotonic,
    ) -> None:
        self.http = http
        self.sink = sink
        self.config = config or MarketRecorderConfig()
        self.state_path = Path(state_path) if state_path else None
        self.gecko_url = gecko_url.rstrip("/")
        self.dexscreener_url = dexscreener_url.rstrip("/")
        self._sleep = sleep
        self._clock = clock
        self.gecko_pacer = RequestPacer(
            self.config.gecko_gap_seconds, sleep=sleep, clock=monotonic
        )
        self.dex_pacer = RequestPacer(
            self.config.dexscreener_gap_seconds, sleep=sleep, clock=monotonic
        )
        self.followed: dict[tuple[str, str], FollowedPool] = {}
        self.seen: dict[str, OrderedDict[str, None]] = {
            c: OrderedDict() for c in self.config.chains
        }
        self.stats = MarketRecorderStats()
        self._discovered_at: dict[str, float] = {}
        self._listed_at: dict[str, float] = {}
        self._stats_at = 0.0
        self._state_at = 0.0

    # -- rows ---------------------------------------------------------------

    def _write(self, event: str, row: dict[str, Any], now: float) -> None:
        self.sink.record_snapshot(
            {"timestamp": now, "venue": VENUE, "event": event, **row}
        )

    def _end(self, pool: FollowedPool, cause: str, now: float) -> None:
        self.followed.pop(pool.key, None)
        self.stats.ended[cause] = self.stats.ended.get(cause, 0) + 1
        self._write(
            END_EVENT,
            {
                "chain": pool.chain,
                "pool": pool.pool,
                "source": pool.source,
                "cause": cause,
                "followed_seconds": round(max(0.0, now - pool.first_seen), 1),
                "snapshots": pool.snapshots,
            },
            now,
        )

    # -- following ----------------------------------------------------------

    def _follow(
        self,
        chain: str,
        fields: Mapping[str, Any],
        *,
        source: str,
        rank: int | None,
        now: float,
    ) -> bool:
        address = fields.get("pool")
        if not isinstance(address, str) or not address:
            return False
        if (chain, address) in self.followed:
            return False
        if len(self.followed) >= max(0, int(self.config.max_followed)):
            self.stats.full += 1
            return False
        pool = FollowedPool(
            chain=chain,
            pool=address,
            source=source,
            first_seen=now,
            created_at=_float(fields.get("created_at")),
            rank=rank,
            base_token=(
                fields["base_token"]
                if isinstance(fields.get("base_token"), str)
                else None
            ),
        )
        self.followed[pool.key] = pool
        self.stats.followed += 1
        return True

    def due(self, now: float) -> list[FollowedPool]:
        """Followed pools whose snapshot is due, never-tried and most overdue
        first. A miss counts as a try, so a pool DexScreener has not indexed
        yet waits its interval like any other."""
        out: list[tuple[float, FollowedPool]] = []
        for pool in self.followed.values():
            if pool.last_snapshot_at <= 0:
                out.append((float("inf"), pool))
                continue
            interval = self.config.interval_for(now - pool.first_seen)
            overdue = now - pool.last_snapshot_at - interval
            if overdue >= 0:
                out.append((overdue, pool))
        out.sort(key=lambda item: -item[0])
        return [pool for _, pool in out]

    async def snapshot_batch(self, chain: str, pools: Sequence[FollowedPool]) -> int:
        """One DexScreener call for up to 30 pools of one chain; rows written."""
        if not pools:
            return 0
        matches = await self._fetch_matches(chain, pools)
        now = self._clock()
        written = 0
        for pool in pools:
            written += self._apply_snapshot(chain, pool, matches.get(pool.key), now)
        return written

    async def _fetch_matches(
        self, chain: str, pools: Sequence[FollowedPool]
    ) -> dict[tuple[str, str], tuple[Mapping[str, Any], str]]:
        """The pair call for ``pools``, then the token lookup for the misses."""
        dex_chain = CHAINS[chain][1]
        url = f"{self.dexscreener_url}/latest/dex/pairs/{dex_chain}/" + ",".join(
            p.pool for p in pools
        )
        self.stats.snapshot_calls += 1
        payload = await _paced(
            self.dex_pacer, lambda: self.http.get_json(url), self._sleep
        )
        pairs = (payload or {}).get("pairs") or [] if isinstance(payload, dict) else []
        by_address = {_pair_key(p): p for p in pairs if isinstance(p, Mapping)}
        matches: dict[tuple[str, str], tuple[Mapping[str, Any], str]] = {}
        for pool in pools:
            found = by_address.get(pool.pool.lower())
            if found is not None:
                matches[pool.key] = (found, "pool")
        unmatched = [p for p in pools if p.key not in matches and p.base_token]
        if unmatched:
            matches.update(await self._match_by_token(chain, unmatched))
        return matches

    def _apply_snapshot(
        self,
        chain: str,
        pool: FollowedPool,
        match: tuple[Mapping[str, Any], str] | None,
        now: float,
    ) -> int:
        """One pool's answer (or miss); returns rows written."""
        pool.last_snapshot_at = now
        if match is None:
            self._note_missing(pool, now)
            return 0
        pair, matched = match
        pool.missing = 0
        pool.snapshots += 1
        snap = dexscreener_snapshot(pair)
        age = now - pool.first_seen
        written = self._write_snapshot(chain, pool, pair, matched, snap, age, now)
        if age >= self.config.dead_after_seconds and self._looks_dead(snap):
            self._end(pool, "dead", now)
        return written

    def _note_missing(self, pool: FollowedPool, now: float) -> None:
        pool.missing += 1
        if (
            pool.missing >= MISSING_LIMIT
            and now - pool.first_seen >= MISSING_GRACE_SECONDS
        ):
            self._end(pool, "missing", now)

    def _write_snapshot(
        self,
        chain: str,
        pool: FollowedPool,
        pair: Mapping[str, Any],
        matched: str,
        snap: dict[str, Any],
        age: float,
        now: float,
    ) -> int:
        """Write the row unless nothing changed within the heartbeat; 1 if written."""
        signature = _signature(snap)
        if (
            signature == pool.signature
            and now - pool.last_written_at < self.config.heartbeat_seconds
        ):
            self.stats.snapshots_unchanged += 1
            return 0
        pool.signature = signature
        pool.last_written_at = now
        self._write(
            SNAPSHOT_EVENT,
            {
                "chain": chain,
                "pool": pool.pool,
                "source": pool.source,
                "dex": pair.get("dexId"),
                "matched": matched,
                **(
                    {"pair_address": pair.get("pairAddress")}
                    if matched == "token"
                    else {}
                ),
                "age_seconds": round(age, 1),
                **snap,
            },
            now,
        )
        self.stats.snapshots += 1
        return 1

    def _looks_dead(self, snap: Mapping[str, Any]) -> bool:
        liquidity = snap.get("liquidity_usd")
        quiet = _trades((snap.get("txns") or {}).get("h1")) == 0
        return quiet and (
            liquidity is None or liquidity < self.config.min_liquidity_usd
        )

    async def _match_by_token(
        self, chain: str, pools: Sequence[FollowedPool]
    ) -> dict[tuple[str, str], tuple[Mapping[str, Any], str]]:
        """Second lookup for pools the pair call missed, by their base token.

        DexScreener does not index every pool GeckoTerminal lists (newer BSC
        exchange versions) and lists four.meme curves under another id. The
        token's pair at the pool's address wins (``matched: "pool"``); without
        one, its most liquid pair on the chain stands in (``matched: "token"``,
        with that pair's address on the row). A failure leaves them missing.
        """
        tokens = list(dict.fromkeys(str(p.base_token) for p in pools))
        url = f"{self.dexscreener_url}/tokens/v1/{CHAINS[chain][1]}/" + ",".join(tokens)
        self.stats.token_lookups += 1
        try:
            payload = await _paced(
                self.dex_pacer, lambda: self.http.get_json(url), self._sleep
            )
        except Exception as exc:
            self._note_error(exc)
            return {}
        pairs = (
            [p for p in payload if isinstance(p, Mapping)]
            if isinstance(payload, list)
            else []
        )
        found: dict[tuple[str, str], tuple[Mapping[str, Any], str]] = {}
        for pool in pools:
            token = str(pool.base_token).lower()
            candidates = [
                p
                for p in pairs
                if str((p.get("baseToken") or {}).get("address") or "").lower() == token
            ]
            if not candidates:
                continue
            exact = [p for p in candidates if _pair_key(p) == pool.pool.lower()]
            if exact:
                found[pool.key] = (exact[0], "pool")
            else:
                found[pool.key] = (max(candidates, key=_liquidity), "token")
            self.stats.token_matched += 1
        return found

    async def snapshot_due(self) -> int:
        """Snapshot every due pool (batched per chain); retires aged-out pools."""
        now = self._clock()
        for pool in list(self.followed.values()):
            if now - pool.first_seen > self.config.max_age_seconds:
                self._end(pool, "max_age", now)
        written = 0
        for chain, batch in self._due_batches(now):
            try:
                written += await self.snapshot_batch(chain, batch)
            except Exception as exc:  # HTTP status, network, JSON: retry next pass
                self._note_error(exc)
                return written
        return written

    def _due_batches(self, now: float) -> list[tuple[str, list[FollowedPool]]]:
        """The due pools, per chain, in batches of one DexScreener call."""
        by_chain: dict[str, list[FollowedPool]] = {}
        for pool in self.due(now):
            by_chain.setdefault(pool.chain, []).append(pool)
        return [
            (chain, pools[start : start + DEXSCREENER_BATCH])
            for chain, pools in by_chain.items()
            for start in range(0, len(pools), DEXSCREENER_BATCH)
        ]

    # -- discovery ------------------------------------------------------------

    async def _gecko(self, path: str, params: Mapping[str, Any]) -> Any:
        url = f"{self.gecko_url}/{path}"
        return await _paced(
            self.gecko_pacer,
            lambda: self.http.get_json(url, params=dict(params)),
            self._sleep,
        )

    def _remember(self, chain: str, address: str) -> None:
        seen = self.seen.setdefault(chain, OrderedDict())
        seen[address] = None
        while len(seen) > SEEN_PER_CHAIN:
            seen.popitem(last=False)

    async def discover(self, chain: str) -> int:
        """Page through the chain's new pools until a known one; returns new pools."""
        network = CHAINS[chain][0]
        seen = self.seen.setdefault(chain, OrderedDict())
        first_run = not seen
        found = 0
        reached_known = False
        for page in range(1, max(1, int(self.config.max_new_pool_pages)) + 1):
            self.stats.discovery_calls += 1
            payload = await self._gecko(f"networks/{network}/new_pools", {"page": page})
            items = _gecko_items(payload)
            if not items:
                reached_known = True
                break
            page_found, reached_known = self._discover_page(chain, items, seen)
            found += page_found
            if reached_known:
                break
        if not reached_known and not first_run:
            # More new pools than pages: some were never seen.
            self.stats.discovery_gaps += 1
        return found

    def _discover_page(
        self, chain: str, items: Sequence[Any], seen: Mapping[str, None]
    ) -> tuple[int, bool]:
        """One page of new pools: (pools new to us, whether a known one appeared)."""
        network = CHAINS[chain][0]
        now = self._clock()
        found = 0
        reached_known = False
        for item in items:
            fields = gecko_pool_fields(item, network)
            address = fields.get("pool")
            if not isinstance(address, str) or not address:
                continue
            if address in seen:
                reached_known = True
                continue
            self._remember(chain, address)
            found += 1
            self.stats.new_pools += 1
            dex = str(fields.get("dex") or "")
            share = self.config.share_for(chain, dex)
            follow = in_sample(f"{chain}:{address}", share, salt=SAMPLE_SALT)
            followed = follow and self._follow(
                chain, fields, source="new", rank=None, now=now
            )
            self._write(
                POOL_EVENT,
                {
                    "chain": chain,
                    "source": "new",
                    "followed": bool(followed),
                    "sample_share": share,
                    **fields,
                },
                now,
            )
        return found, reached_known

    async def refresh_lists(self, chain: str) -> int:
        """The chain's momentum lists; returns pools newly followed from them."""
        network = CHAINS[chain][0]
        added = 0
        for name, path, query in MOMENTUM_LISTS:
            self.stats.list_calls += 1
            payload = await self._gecko(
                f"networks/{network}/{path}", {**query, "page": 1}
            )
            items = _gecko_items(payload)
            now = self._clock()
            ranked: list[str] = []
            for rank, item in enumerate(items, start=1):
                fields = gecko_pool_fields(item, network)
                address = fields.get("pool")
                if not isinstance(address, str) or not address:
                    continue
                ranked.append(address)
                self.stats.list_entries += 1
                if self._follow(chain, fields, source=name, rank=rank, now=now):
                    added += 1
                    self._write(
                        POOL_EVENT,
                        {
                            "chain": chain,
                            "source": name,
                            "rank": rank,
                            "followed": True,
                            **fields,
                        },
                        now,
                    )
            self._write(
                LIST_EVENT, {"chain": chain, "list": name, "pools": ranked}, now
            )
        return added

    async def discovery_pass(self) -> None:
        """Discovery and lists for every chain that is due."""
        for chain in self.config.chains:
            now = self._clock()
            # A failure waits for the next interval; the other job still runs.
            if self._claim(
                self._discovered_at, chain, now, self.config.discovery_interval_seconds
            ):
                await self._attempt(self.discover(chain))
            if self.config.lists and self._claim(
                self._listed_at, chain, now, self.config.list_interval_seconds
            ):
                await self._attempt(self.refresh_lists(chain))

    @staticmethod
    def _claim(
        stamps: dict[str, float], chain: str, now: float, interval: float
    ) -> bool:
        """True (and the job's time stamped) when the chain's job is due."""
        if now - stamps.get(chain, float("-inf")) < interval:
            return False
        stamps[chain] = now
        return True

    async def _attempt(self, job: Awaitable[Any]) -> None:
        try:
            await job
        except Exception as exc:
            self._note_error(exc)

    def _note_error(self, exc: Exception) -> None:
        self.stats.errors += 1
        if isinstance(exc, HttpStatusError) and exc.status == 429:
            self.stats.rate_limited += 1
        logger.debug("Market recorder request failed: %s", exc)

    # -- stats and state ------------------------------------------------------

    def maybe_write_stats(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._stats_at < self.config.stats_interval_seconds:
            return
        self._stats_at = now
        by_chain: dict[str, int] = {}
        for pool in self.followed.values():
            by_chain[pool.chain] = by_chain.get(pool.chain, 0) + 1
        self._write(
            STATS_EVENT,
            {
                "following": len(self.followed),
                "by_chain": by_chain,
                **asdict(self.stats),
            },
            now,
        )

    def save_state(self, *, force: bool = False) -> bool:
        """Write the follow list, so a restart resumes it (atomic replace)."""
        if self.state_path is None:
            return False
        now = self._clock()
        if not force and now - self._state_at < self.config.state_interval_seconds:
            return False
        self._state_at = now
        state = {
            "version": STATE_VERSION,
            "saved_at": now,
            "followed": [asdict(p) for p in self.followed.values()],
            "seen": {c: list(s)[-SEEN_PER_CHAIN:] for c, s in self.seen.items()},
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.state_path)
        return True

    def load_state(self) -> int:
        """Resume a saved follow list; returns pools resumed."""
        state = self._read_state()
        if state is None:
            return 0
        resumed = self._resume_followed(state.get("followed") or [], self._clock())
        self._resume_seen(state.get("seen") or {})
        return resumed

    def _read_state(self) -> dict[str, Any] | None:
        """The saved state when it exists, parses and has this version."""
        if self.state_path is None or not self.state_path.exists():
            return None
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Market state %s unreadable: %s", self.state_path, exc)
            return None
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            return None
        return state

    def _resume_followed(self, raws: Sequence[Any], now: float) -> int:
        resumed = 0
        for raw in raws:
            try:
                pool = FollowedPool(**raw)
            except TypeError:
                continue
            if pool.chain not in self.config.chains:
                continue
            if now - pool.first_seen > self.config.max_age_seconds:
                continue
            self.followed[pool.key] = pool
            resumed += 1
        return resumed

    def _resume_seen(self, saved: Mapping[str, Any]) -> None:
        for chain, addresses in saved.items():
            if chain in self.seen and isinstance(addresses, list):
                for address in addresses:
                    if isinstance(address, str):
                        self._remember(chain, address)

    # -- loop -----------------------------------------------------------------

    async def run(
        self,
        *,
        stop: asyncio.Event | None = None,
        duration_seconds: float | None = None,
        tick_seconds: float = 1.0,
    ) -> MarketRecorderStats:
        """Discovery and snapshots in two tasks until ``stop`` or the duration."""
        stop = stop or asyncio.Event()
        finished = partial(self._finished, stop, self._clock(), duration_seconds)
        try:
            await asyncio.gather(
                self._discovery_loop(finished, tick_seconds),
                self._snapshot_loop(finished, tick_seconds),
            )
        finally:
            self.maybe_write_stats(force=True)
            self._save_state_noting_errors(force=True)
        return self.stats

    def _finished(
        self, stop: asyncio.Event, started: float, duration_seconds: float | None
    ) -> bool:
        if stop.is_set():
            return True
        if duration_seconds is not None and self._clock() - started >= float(
            duration_seconds
        ):
            stop.set()
            return True
        return False

    async def _discovery_loop(
        self, finished: Callable[[], bool], tick_seconds: float
    ) -> None:
        while not finished():
            await self.discovery_pass()
            await self._sleep(tick_seconds)

    async def _snapshot_loop(
        self, finished: Callable[[], bool], tick_seconds: float
    ) -> None:
        while not finished():
            await self.snapshot_due()
            self.maybe_write_stats()
            self._save_state_noting_errors()
            await self._sleep(tick_seconds)

    def _save_state_noting_errors(self, *, force: bool = False) -> None:
        try:
            self.save_state(force=force)
        except OSError as exc:
            self._note_error(exc)


__all__ = [
    "CHAINS",
    "DEFAULT_CHAINS",
    "DEFAULT_SAMPLE",
    "DEFAULT_TIERS",
    "DEXSCREENER_URL",
    "END_EVENT",
    "LIST_EVENT",
    "MARKET_EVENTS",
    "MOMENTUM_LISTS",
    "POOL_EVENT",
    "SNAPSHOT_EVENT",
    "STATS_EVENT",
    "VENUE",
    "FollowedPool",
    "MarketRecorder",
    "MarketRecorderConfig",
    "MarketRecorderStats",
    "dexscreener_snapshot",
    "gecko_pool_fields",
    "parse_chains",
    "parse_sample",
]
