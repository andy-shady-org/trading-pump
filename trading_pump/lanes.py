"""Pump's captures as the strategy library's records (trading-core FEAT-133).

trading-core's strategy library (its ADR-011) runs venue-neutral rules on
four records (``trading_core.lanes.market``): a *listing*, a *reading*, a
*trade print* and a *holders* snapshot. :class:`LaneRows` translates the
rows this module writes to its capture into them, and nothing of the venue
is left in what it writes:

* ``observation_start`` of a graduate (``source: "graduation"``): a
  :class:`~trading_core.lanes.market.Listing` of the mint, ``kind:
  "graduation"``, at the migration (``migrated_at``). The capture records no
  name or creator for a graduate;
* ``observation_start`` of a new PumpSwap pool (``source: "new_pool"``,
  FEAT-80): a ``listing`` of the mint at the pool's creation
  (``created_at``, else when it was found), its creator from the pool's
  ``coin_creator``;
* ``curve_poll`` of either: a :class:`~trading_core.lanes.market.Reading`,
  priced as the module prices a pool (:attr:`PoolReading.price`, SOL per
  whole token; a new pool's by its mint's recorded decimals), its
  ``liquidity`` the SOL in the pool;
* ``damm_pool`` (FEAT-107): a ``listing`` of the pool at its activation,
  its creator the pool's; ``damm_state``: a reading, priced from the pool's
  ``sqrt_price`` and the coin's decimals (``damm_decimals``) as the capture
  prices it, its liquidity the SOL amount when the pool tracks it (0 when the
  pool's liquidity is 0, a drained pool).

The captures hold no swaps by wallet and no holder snapshots, so no trade
prints or holders are written. A row that holds market data but cannot be
translated is *skipped* and counted by reason (a reading of a coin whose
listing is not in the capture, which the library would take for a new one;
a reading before its listing; a coin whose decimals were not read; a price
of 0, which the row format cannot carry); the other rows (``migration``,
``observation_end``, ``damm_decimals``, ``damm_end``, other runs' rows) are
*ignored*, counted by event.

A capture is read twice: first for the listings and decimals (its parts may
come in any order), then for the rows. The module's live market book uses
the same translator on its capture rows as they are written
(``PumpModule.market_book``), so a lane sees the same records live as the
sweep does on the capture.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from trading_core.lanes.market import (
    ROW_LISTING,
    ROW_READING,
    Listing,
    Reading,
    Record,
    to_row,
)
from trading_core.replay import read_rows

from trading_pump.damm import coin_price_sol, raw_price
from trading_pump.market import LAMPORTS_PER_SOL, PoolReading
from trading_pump.strategies.observation import (
    GRADUATION_SOURCE,
    NEW_POOL_SOURCE,
    OBSERVATION_START_EVENT,
)

DAMM_SOURCE = "damm"
SOURCES = (GRADUATION_SOURCE, NEW_POOL_SOURCE, DAMM_SOURCE)
KIND_GRADUATION = "graduation"
KIND_LISTING = "listing"
CURVE_POLL_EVENT = "curve_poll"
DAMM_PREFIX = "damm_"
DAMM_POOL_EVENT = "damm_pool"
DAMM_DECIMALS_EVENT = "damm_decimals"
DAMM_STATE_EVENT = "damm_state"
# Pump.fun mints have 6 decimals; PoolReading prices every pool with them.
PUMP_DECIMALS = 6
# The default public key (all zero bytes): no coin creator set.
NO_CREATOR = "11111111111111111111111111111111"

SKIP_MALFORMED = "malformed"
SKIP_NO_LISTING = "no listing in the capture (followed before it started)"
SKIP_BEFORE_LISTING = "before its listing"
SKIP_NO_DECIMALS = "coin decimals not recorded"
SKIP_NO_PRICE = "price 0 (drained pool): the row format has no price 0"
OUTPUT_SUFFIXES = (".jsonl", ".jsonl.gz")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _whole(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _source(row: Mapping[str, Any]) -> Any:
    """``damm`` for a DAMM v2 row, else the row's own ``source``."""
    if str(row.get("event") or "").startswith(DAMM_PREFIX):
        return DAMM_SOURCE
    return row.get("source")


def _instrument(row: Mapping[str, Any]) -> str | None:
    """A DAMM v2 pool is its own instrument; a PumpSwap coin is its mint."""
    key = "pool" if _source(row) == DAMM_SOURCE else "mint"
    return _text(row.get(key))


def _label(row: Mapping[str, Any]) -> str:
    event = str(row.get("event") or "no event")
    source = row.get("source")
    return f"{event}/{source}" if source else event


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _damm_liquidity(row: Mapping[str, Any], sol_is_a: bool) -> float | None:
    """SOL in a DAMM v2 pool: 0 when its liquidity is 0, else its SOL
    amount, ``None`` on a layout that does not track the amounts (0)."""
    if _whole(row.get("liquidity")) == 0:
        return 0.0
    amount = _number(row.get("a_amount" if sol_is_a else "b_amount"))
    return amount / LAMPORTS_PER_SOL if amount else None


@dataclass
class LaneRowStats:
    """Records written by kind, rows skipped by reason, rows ignored by event."""

    written: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    ignored: Counter[str] = field(default_factory=Counter)


@dataclass
class _Listed:
    """An instrument's listing, its coin's decimals (``None``: unknown, or
    read from ``damm_decimals``) and, for a DAMM v2 pool, its SOL side."""

    listing: Listing
    decimals: int | None = PUMP_DECIMALS
    sol_is_a: bool = False
    written: bool = False


@dataclass(frozen=True)
class _Context:
    """What a reading row needs from its instrument."""

    instrument: str
    at: float
    decimals: int
    sol_is_a: bool


class LaneRows:
    """Translates capture rows into library records; see the module
    docstring. Call :meth:`learn` on a row before :meth:`translate` (every row
    of a capture first, or each row as it is written)."""

    def __init__(self, sources: Iterable[str] = SOURCES) -> None:
        chosen = frozenset(sources)
        unknown = sorted(chosen - set(SOURCES))
        if unknown:
            raise ValueError(
                f"unknown sources: {', '.join(unknown)} (known: {', '.join(SOURCES)})"
            )
        self.sources = chosen
        self.listed: dict[str, _Listed] = {}
        self.decimals: dict[str, int] = {}
        self.stats = LaneRowStats()
        self._handlers: dict[str, Callable[[Mapping[str, Any]], list[Record]]] = {
            OBSERVATION_START_EVENT: self._listing,
            DAMM_POOL_EVENT: self._listing,
            CURVE_POLL_EVENT: self._curve_reading,
            DAMM_STATE_EVENT: self._damm_reading,
        }

    # -- listings and decimals ---------------------------------------------------
    def learn(self, row: Mapping[str, Any]) -> None:
        """Note an instrument's listing or decimals, if the row has them."""
        if _source(row) not in self.sources:
            return
        event = row.get("event")
        if event == OBSERVATION_START_EVENT:
            self._learn_start(row)
        elif event == DAMM_POOL_EVENT:
            self._learn_damm(row)
        elif event == DAMM_DECIMALS_EVENT:
            self._learn_decimals(row)

    def _learn_start(self, row: Mapping[str, Any]) -> None:
        mint = _text(row.get("mint"))
        if row.get("source") == GRADUATION_SOURCE:
            at = _first_number(row, "migrated_at", "timestamp")
            listed = None if mint is None or at is None else _graduation(mint, at)
        else:
            at = _first_number(row, "created_at", "migrated_at", "timestamp")
            listed = None if mint is None or at is None else _new_pool(row, mint, at)
        self._keep(listed)

    def _learn_damm(self, row: Mapping[str, Any]) -> None:
        pool = _text(row.get("pool"))
        stamp = _number(row.get("timestamp"))
        if pool is None or stamp is None:
            return
        at = stamp - (_number(row.get("age_seconds")) or 0.0)
        listing = Listing(
            pool, at, kind=KIND_LISTING, creator=_creator(row.get("creator"))
        )
        self._keep(_Listed(listing, None, sol_is_a=bool(row.get("sol_is_a"))))

    def _learn_decimals(self, row: Mapping[str, Any]) -> None:
        pool = _text(row.get("pool"))
        decimals = _whole(row.get("decimals"))
        if pool is not None and decimals is not None:
            self.decimals[pool] = decimals

    def _keep(self, listed: _Listed | None) -> None:
        """Keep an instrument's earliest listing."""
        if listed is None:
            return
        key = listed.listing.instrument_id
        known = self.listed.get(key)
        if known is None or listed.listing.at < known.listing.at:
            self.listed[key] = listed

    def _decimals(self, key: str, listed: _Listed) -> int | None:
        return (
            listed.decimals if listed.decimals is not None else self.decimals.get(key)
        )

    def forget(self, keep: Iterable[str]) -> None:
        """Drop what is known of every instrument not in ``keep``."""
        kept = set(keep)
        self.listed = {k: v for k, v in self.listed.items() if k in kept}
        self.decimals = {k: v for k, v in self.decimals.items() if k in kept}

    # -- rows --------------------------------------------------------------------
    def translate(self, row: Mapping[str, Any]) -> list[Record]:
        """The records one row holds (none for a skipped or ignored row)."""
        handler = self._handlers.get(str(row.get("event")))
        if handler is None or _source(row) not in self.sources:
            self.stats.ignored[_label(row)] += 1
            return []
        return handler(row)

    def _wrote(self, record: Record) -> list[Record]:
        kind = ROW_LISTING if isinstance(record, Listing) else ROW_READING
        self.stats.written[kind] += 1
        return [record]

    def _skip(self, reason: str) -> list[Record]:
        self.stats.skipped[reason] += 1
        return []

    def _listing(self, row: Mapping[str, Any]) -> list[Record]:
        key = _instrument(row)
        listed = None if key is None else self.listed.get(key)
        if key is None or listed is None:
            return self._skip(SKIP_MALFORMED)
        if listed.written:
            self.stats.ignored[f"{_label(row)} (listed already)"] += 1
            return []
        if self._decimals(key, listed) is None:
            return self._skip(SKIP_NO_DECIMALS)
        listed.written = True
        return self._wrote(listed.listing)

    def _context(self, row: Mapping[str, Any]) -> _Context | str:
        """What a reading row needs, or why it is skipped."""
        key = _instrument(row)
        at = _number(row.get("timestamp"))
        if key is None or at is None:
            return SKIP_MALFORMED
        listed = self.listed.get(key)
        if listed is None:
            return SKIP_NO_LISTING
        decimals = self._decimals(key, listed)
        if decimals is None:
            return SKIP_NO_DECIMALS
        if at < listed.listing.at:
            return SKIP_BEFORE_LISTING
        return _Context(key, at, decimals, listed.sol_is_a)

    def _reading(
        self, context: _Context, price: float | None, liquidity: float | None
    ) -> list[Record]:
        if not price or price <= 0:
            return self._skip(SKIP_NO_PRICE)
        return self._wrote(
            Reading(context.instrument, context.at, price, liquidity=liquidity)
        )

    def _curve_reading(self, row: Mapping[str, Any]) -> list[Record]:
        context = self._context(row)
        if isinstance(context, str):
            return self._skip(context)
        reading = PoolReading.from_capture_row(
            row, mint=context.instrument, at=context.at
        )
        if reading is None:
            return self._skip(SKIP_MALFORMED)
        # PoolReading assumes Pump.fun's 6 decimals (FEAT-80 pools may differ).
        price = reading.price * 10 ** (context.decimals - PUMP_DECIMALS)
        return self._reading(context, price, reading.pool_sol)

    def _damm_reading(self, row: Mapping[str, Any]) -> list[Record]:
        context = self._context(row)
        if isinstance(context, str):
            return self._skip(context)
        sqrt_price = _whole(row.get("sqrt_price"))
        if sqrt_price is None:
            return self._skip(SKIP_MALFORMED)
        price = coin_price_sol(
            raw_price(sqrt_price), context.sol_is_a, context.decimals
        )
        return self._reading(context, price, _damm_liquidity(row, context.sol_is_a))


def _creator(value: Any) -> str | None:
    text = _text(value)
    return None if text == NO_CREATOR else text


def _graduation(mint: str, at: float) -> _Listed:
    return _Listed(Listing(mint, at, kind=KIND_GRADUATION))


def _new_pool(row: Mapping[str, Any], mint: str, at: float) -> _Listed:
    listing = Listing(
        mint, at, kind=KIND_LISTING, creator=_creator(row.get("coin_creator"))
    )
    return _Listed(listing, _whole(row.get("decimals")))


def lane_records(paths: Sequence[str | Path], rows: LaneRows) -> Iterator[Record]:
    """The records of a capture's files (``.jsonl`` and ``.gz`` parts, in any
    order); ``rows.stats`` counts what was written, skipped and ignored."""
    for row in read_rows(paths):
        rows.learn(row)
    for row in read_rows(paths):
        yield from rows.translate(row)


def _open_output(path: Path, compress: bool) -> TextIO:
    if compress:
        return gzip.open(path, "wt", encoding="utf-8")
    return path.open("w", encoding="utf-8")


def write_lane_rows(
    paths: Sequence[str | Path],
    out: str | Path,
    *,
    sources: Iterable[str] = SOURCES,
) -> LaneRowStats:
    """Write a capture's records as library rows to ``out`` (``.jsonl`` or
    ``.jsonl.gz``, a new file), for ``trading-core-lanes sweep``. Rows are
    listings and readings in capture order, not time order: the sweep sorts
    them."""
    target = Path(out)
    if not target.name.endswith(OUTPUT_SUFFIXES):
        raise ValueError(f"{target}: the output must end in .jsonl or .jsonl.gz")
    if target.exists():
        raise ValueError(f"{target} exists already: write to a new file")
    rows = LaneRows(sources)
    partial = target.with_name(target.name + ".partial")
    try:
        with _open_output(partial, target.name.endswith(".gz")) as handle:
            for record in lane_records(paths, rows):
                handle.write(json.dumps(to_row(record)) + "\n")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return rows.stats


__all__ = [
    "DAMM_SOURCE",
    "SOURCES",
    "LaneRowStats",
    "LaneRows",
    "lane_records",
    "write_lane_rows",
]
