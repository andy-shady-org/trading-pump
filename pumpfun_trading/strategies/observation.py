"""Record-only curve observation lists (rc.3).

Two experiments need curves the watch list never sees, without changing what
the bot buys:

* ``reject_sample``: a deterministic share of the launches the screen rejects
  (``screen_reject_sample_pct``), so a capture shows whether the top-5 holder
  and creator-holding caps keep out coins that later get demand.
* ``discovery``: curves found by a bounded Pump.fun API scan whose real SOL
  reserve is already past ``graduation_discovery_min_real_sol``, regardless of
  screening or the watch TTL, so the pre-graduation lane can be judged on
  more than the few screened coins that live that long.

Entries here are polled and written to the capture only. They are never
promoted to a trade subscription, never evaluated by the shadow book and never
bought; replay skips their rows (``RECORD_ONLY_POLL_SOURCES``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

# ``curve_poll`` sources that are analysis data only: replay, the shadow report
# and the shadow scan skip them, so a capture with them replays like one without.
REJECT_SAMPLE_SOURCE = "reject_sample"
DISCOVERY_SOURCE = "discovery"
RECORD_ONLY_POLL_SOURCES = frozenset({REJECT_SAMPLE_SOURCE, DISCOVERY_SOURCE})
# Capture rows written when an observation starts and ends.
OBSERVATION_START_EVENT = "observation_start"
OBSERVATION_END_EVENT = "observation_end"
OBSERVATION_EVENTS = frozenset({OBSERVATION_START_EVENT, OBSERVATION_END_EVENT})

# Native SOL quote mint in the Pump.fun API's coin records.
SOL_QUOTE_MINT = "11111111111111111111111111111111"
LAMPORTS_PER_SOL = 1_000_000_000


def is_record_only_row(row: Mapping[str, Any]) -> bool:
    """True for capture rows written by the observation lists (never market
    data for replay)."""
    event = row.get("event")
    if event in OBSERVATION_EVENTS:
        return True
    return event == "curve_poll" and row.get("source") in RECORD_ONLY_POLL_SOURCES


def in_reject_sample(mint: str, share: float) -> bool:
    """Deterministic sample: the same mint is always in or out for a given
    share, so two runs (and a re-read of a capture) agree."""
    if share <= 0.0:
        return False
    if share >= 1.0:
        return True
    digest = hashlib.sha256(mint.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return bucket < share


@dataclass(slots=True)
class ObservedCurve:
    """One curve polled for the capture only."""

    mint: str
    source: str
    added_at: float
    created_at: float | None = None
    reasons: tuple[str, ...] = ()
    last_polled_at: float = 0.0
    polls: int = 0
    first_real_sol: float | None = None
    last_real_sol: float | None = None
    peak_real_sol: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "source": self.source,
            "added_at": self.added_at,
            "created_at": self.created_at,
            "reasons": list(self.reasons),
            "polls": self.polls,
            "first_real_sol": self.first_real_sol,
            "last_real_sol": self.last_real_sol,
            "peak_real_sol": round(self.peak_real_sol, 9),
        }


@dataclass
class CurveObservationList:
    """Bounded, TTL-limited set of record-only curves of one ``source``.

    ``min_real_sol`` > 0 drops an entry whose polled real SOL reserve falls
    below it (discovery); the reject sample keeps every entry until its TTL.
    """

    source: str
    max_mints: int
    ttl_seconds: float
    poll_interval_seconds: float
    min_real_sol: float = 0.0
    _entries: dict[str, ObservedCurve] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, mint: object) -> bool:
        return mint in self._entries

    def get(self, mint: str) -> ObservedCurve | None:
        return self._entries.get(mint)

    def mints(self) -> list[str]:
        return list(self._entries)

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def add(
        self,
        mint: str,
        *,
        now: float,
        created_at: float | None = None,
        reasons: Iterable[str] = (),
    ) -> ObservedCurve | None:
        """Start observing ``mint``; ``None`` when already observed or full
        (a full list never evicts, so an observation always runs its course)."""
        if mint in self._entries:
            return None
        if len(self._entries) >= max(0, int(self.max_mints)):
            self._count("full")
            return None
        entry = ObservedCurve(
            mint=mint,
            source=self.source,
            added_at=float(now),
            created_at=None if created_at is None else float(created_at),
            reasons=tuple(str(r) for r in reasons),
        )
        self._entries[mint] = entry
        self._count("added")
        return entry

    def due(self, now: float) -> list[str]:
        """Never-polled mints and those whose last poll is at least one poll
        interval old."""
        interval = float(self.poll_interval_seconds)
        return [
            mint
            for mint, entry in self._entries.items()
            if entry.polls == 0 or now - entry.last_polled_at >= interval
        ]

    def update(self, mint: str, *, real_sol: float, now: float) -> str | None:
        """Record one polled reading; returns why the entry ended, if it did."""
        entry = self._entries.get(mint)
        if entry is None:
            return None
        value = float(real_sol)
        entry.polls += 1
        entry.last_polled_at = float(now)
        if entry.first_real_sol is None:
            entry.first_real_sol = value
        entry.last_real_sol = value
        entry.peak_real_sol = max(entry.peak_real_sol, value)
        if self.min_real_sol > 0 and value < float(self.min_real_sol):
            return "below_floor"
        return None

    def remove(self, mint: str, cause: str) -> ObservedCurve | None:
        entry = self._entries.pop(mint, None)
        if entry is not None:
            self._count(f"ended_{cause}")
        return entry

    def expired(self, now: float) -> list[str]:
        """Mints observed longer than the TTL (the caller ends them)."""
        ttl = float(self.ttl_seconds)
        return [
            mint for mint, entry in self._entries.items() if now - entry.added_at > ttl
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "observed": len(self._entries),
            "max_mints": int(self.max_mints),
            "stats": dict(self.stats),
        }


def discovery_candidates(
    payload: Any, *, min_real_sol: float, max_real_sol: float
) -> list[tuple[str, float | None]]:
    """Mints in a Pump.fun API ``/coins`` page worth a curve poll: Pump.fun
    program, SOL quote, not complete, real SOL reserve inside
    [``min_real_sol``, ``max_real_sol``). Returns ``(mint, created_at)``;
    the RPC poll checks the curve itself before anything is recorded."""
    rows = payload
    if isinstance(payload, Mapping):
        rows = payload.get("coins") or payload.get("data") or payload.get("items")
    if not isinstance(rows, list):
        return []
    found: list[tuple[str, float | None]] = []
    for coin in rows:
        if not isinstance(coin, Mapping):
            continue
        mint = coin.get("mint")
        if not isinstance(mint, str) or not mint:
            continue
        if coin.get("complete") is True:
            continue
        program = coin.get("program")
        if program not in (None, "pump"):
            continue
        quote = coin.get("quote_mint")
        if quote not in (None, SOL_QUOTE_MINT):
            continue
        try:
            real_sol = float(coin.get("real_sol_reserves") or 0) / LAMPORTS_PER_SOL
        except (TypeError, ValueError):
            continue
        if not min_real_sol <= real_sol < max_real_sol:
            continue
        created: float | None = None
        raw_created = coin.get("created_timestamp")
        if isinstance(raw_created, (int, float)) and raw_created > 0:
            created = float(raw_created)
            if created > 1e12:  # milliseconds
                created /= 1000.0
        found.append((mint, created))
    return found


__all__ = [
    "DISCOVERY_SOURCE",
    "OBSERVATION_END_EVENT",
    "OBSERVATION_EVENTS",
    "OBSERVATION_START_EVENT",
    "RECORD_ONLY_POLL_SOURCES",
    "REJECT_SAMPLE_SOURCE",
    "CurveObservationList",
    "ObservedCurve",
    "discovery_candidates",
    "in_reject_sample",
    "is_record_only_row",
]
