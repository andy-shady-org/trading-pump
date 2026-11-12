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
  ``liquidity`` the SOL in the pool.

Meteora DAMM v2 rows (FEAT-107's ``damm_*``) are trading-meteora's since
0.5.0: its own ``lane-rows`` translates them.

The captures hold no swaps by wallet and no holder snapshots, so no trade
prints or holders are written. A row that holds market data but cannot be
translated is *skipped* and counted by reason (a reading of a coin whose
listing is not in the capture, which the library would take for a new one;
a reading before its listing; a coin whose decimals were not read; a price
of 0, which the row format cannot carry); the other rows (``migration``,
``observation_end``, other runs' rows) are *ignored*, counted by event.

A capture is read twice: first for the listings (its parts may come in any
order), then for the rows (trading-core's ``capture_records``, FEAT-184);
the writer and the ``lane-rows`` command are trading-core's too
(``trading_core.lanes.rows``), given this translator. The module's live market book uses
the same translator on its capture rows as they are written
(``PumpModule.market_book``), so a lane sees the same records live as the
sweep does on the capture.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_core.lanes.market import (
    ROW_LISTING,
    ROW_READING,
    Listing,
    Reading,
    Record,
)
from trading_core.lanes.rows import Conversion, capture_records, number
from trading_core.lanes.rows import write_lane_rows as core_write_lane_rows

from trading_pump.market import PoolReading
from trading_pump.strategies.observation import (
    GRADUATION_SOURCE,
    NEW_POOL_SOURCE,
    OBSERVATION_START_EVENT,
)

SOURCES = (GRADUATION_SOURCE, NEW_POOL_SOURCE)
KIND_GRADUATION = "graduation"
KIND_LISTING = "listing"
CURVE_POLL_EVENT = "curve_poll"
# Pump.fun mints have 6 decimals; PoolReading prices every pool with them.
PUMP_DECIMALS = 6
# The default public key (all zero bytes): no coin creator set.
NO_CREATOR = "11111111111111111111111111111111"

SKIP_MALFORMED = "malformed"
SKIP_NO_LISTING = "no listing in the capture (followed before it started)"
SKIP_BEFORE_LISTING = "before its listing"
SKIP_NO_DECIMALS = "coin decimals not recorded"
SKIP_NO_PRICE = "price 0 (drained pool): the row format has no price 0"


def _whole(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _source(row: Mapping[str, Any]) -> Any:
    return row.get("source")


def _instrument(row: Mapping[str, Any]) -> str | None:
    """A PumpSwap coin's instrument is its mint."""
    return _text(row.get("mint"))


def _label(row: Mapping[str, Any]) -> str:
    event = str(row.get("event") or "no event")
    source = row.get("source")
    return f"{event}/{source}" if source else event


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = number(row.get(key))
        if value is not None:
            return value
    return None


@dataclass
class LaneRowStats:
    """Records written by kind, rows skipped by reason, rows ignored by event."""

    written: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    ignored: Counter[str] = field(default_factory=Counter)


@dataclass
class _Listed:
    """An instrument's listing and its coin's decimals (``None``: unknown)."""

    listing: Listing
    decimals: int | None = PUMP_DECIMALS
    written: bool = False


@dataclass(frozen=True)
class _Context:
    """What a reading row needs from its instrument."""

    instrument: str
    at: float
    decimals: int


class LaneRows:
    """Translates capture rows into library records; see the module
    docstring. Call :meth:`learn` on a row before :meth:`records` (every row
    of a capture first, or each row as it is written). ``skipped`` and
    ``ignored`` are ``stats``' counters, as trading-core's writer reads them."""

    def __init__(self, sources: Iterable[str] = SOURCES) -> None:
        chosen = frozenset(sources)
        unknown = sorted(chosen - set(SOURCES))
        if unknown:
            raise ValueError(
                f"unknown sources: {', '.join(unknown)} (known: {', '.join(SOURCES)})"
            )
        self.sources = chosen
        self.listed: dict[str, _Listed] = {}
        self.stats = LaneRowStats()
        self.skipped = self.stats.skipped
        self.ignored = self.stats.ignored
        self._handlers: dict[str, Callable[[Mapping[str, Any]], list[Record]]] = {
            OBSERVATION_START_EVENT: self._listing,
            CURVE_POLL_EVENT: self._curve_reading,
        }

    # -- listings ----------------------------------------------------------------
    def learn(self, row: Mapping[str, Any]) -> None:
        """Note an instrument's listing, if the row has it."""
        if _source(row) in self.sources and row.get("event") == OBSERVATION_START_EVENT:
            self._learn_start(row)

    def _learn_start(self, row: Mapping[str, Any]) -> None:
        mint = _text(row.get("mint"))
        if row.get("source") == GRADUATION_SOURCE:
            at = _first_number(row, "migrated_at", "timestamp")
            listed = None if mint is None or at is None else _graduation(mint, at)
        else:
            at = _first_number(row, "created_at", "migrated_at", "timestamp")
            listed = None if mint is None or at is None else _new_pool(row, mint, at)
        self._keep(listed)

    def _keep(self, listed: _Listed | None) -> None:
        """Keep an instrument's earliest listing."""
        if listed is None:
            return
        key = listed.listing.instrument_id
        known = self.listed.get(key)
        if known is None or listed.listing.at < known.listing.at:
            self.listed[key] = listed

    def forget(self, keep: Iterable[str]) -> None:
        """Drop what is known of every instrument not in ``keep``."""
        kept = set(keep)
        self.listed = {k: v for k, v in self.listed.items() if k in kept}

    # -- rows --------------------------------------------------------------------
    def records(self, row: Mapping[str, Any]) -> list[Record]:
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
        if listed.decimals is None:
            return self._skip(SKIP_NO_DECIMALS)
        listed.written = True
        return self._wrote(listed.listing)

    def _context(self, row: Mapping[str, Any]) -> _Context | str:
        """What a reading row needs, or why it is skipped."""
        key = _instrument(row)
        at = number(row.get("timestamp"))
        if key is None or at is None:
            return SKIP_MALFORMED
        listed = self.listed.get(key)
        if listed is None:
            return SKIP_NO_LISTING
        if listed.decimals is None:
            return SKIP_NO_DECIMALS
        if at < listed.listing.at:
            return SKIP_BEFORE_LISTING
        return _Context(key, at, listed.decimals)

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
    order, read as given); ``rows.stats`` counts what was written, skipped and
    ignored."""
    return capture_records(paths, rows, order=list)


def write_lane_rows(
    paths: Sequence[str | Path],
    out: str | Path,
    *,
    sources: Iterable[str] = SOURCES,
) -> Conversion:
    """Write a capture's records as library rows to ``out`` (a new
    ``.jsonl`` or ``.jsonl.gz`` file), for ``trading-core-lanes sweep``:
    trading-core's writer on this translator. Rows are listings and readings
    in capture order, not time order: the sweep sorts them."""
    return core_write_lane_rows(paths, out, LaneRows(sources), order=list)


__all__ = [
    "SOURCES",
    "LaneRowStats",
    "LaneRows",
    "lane_records",
    "write_lane_rows",
]
