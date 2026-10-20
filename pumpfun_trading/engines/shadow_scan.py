"""Offline shadow variants: rebuild ``shadow_entry`` rows from a capture.

The live bot writes a ``shadow_entry`` row when a FEAT-58 variant fires. A
capture recorded before a variant existed (the pullback rule, FEAT-59, or a
new FEAT-60/61 filter) has none, so this module runs the same
``ShadowVariantBook`` over the capture's recorded trades (and, for
``pullback_curve`` variants, its ``watch`` curve polls; rc.2 captures on) and
writes the rows the bot would have written. The fill is the first recorded market cap (a trade or a
``curve_poll`` row) at least ``paper_entry_delay_seconds`` after the signal, so
:func:`pumpfun_trading.engines.shadow_report.build_shadow_report` can model the
positions exactly as it does for recorded rows.

Limits, said plainly in the read-out:

* the book sees every mint with recorded trades. In a confirmed-mode capture
  those are the promoted (subscribed) and held mints, as live; in a launch-mode
  capture they are the mints the launch bot bought;
* fills come from recorded data only. The live shadow fill reads the curve,
  which also sees trades the capture missed, so replayed drift is lower than
  paper drift (AGENTS.md, "Replay can't see what it didn't record");
* ``early_holders`` / ``early_holder_pct`` (FEAT-61) only exist in captures
  whose screening records carry them (rc.3 on).
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any, Iterable, Mapping, Sequence

from pumpfun_trading.engines.cuts import CaptureIndex
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.momentum import OrderFlowEngine
from pumpfun_trading.strategies.shadow import (
    ShadowVariantBook,
    parse_shadow_variants,
    shadow_fill_record,
)

# A fill must land within this many seconds after it is due, else "no_curve".
FILL_WINDOW_SECONDS = 5.0
STATIC_SCREENING_KEYS = ("early_holders", "early_holder_pct")


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _price_rows(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[list[float], list[float]]]:
    """Per mint, the recorded market caps (trades and curve polls) by time."""
    series: dict[str, list[tuple[float, float]]] = {}
    for record in records:
        mint = record.get("mint")
        event = record.get("event")
        if not mint or (event and event != "curve_poll") or "reason" in record:
            continue
        market_cap = _float(record.get("market_cap_sol"))
        if market_cap <= 0:
            continue
        series.setdefault(str(mint), []).append(
            (_float(record.get("timestamp")), market_cap)
        )
    out: dict[str, tuple[list[float], list[float]]] = {}
    for mint, rows in series.items():
        rows.sort()
        out[mint] = ([ts for ts, _ in rows], [mc for _, mc in rows])
    return out


def _static_metrics(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("event") != "screening" or not record.get("mint"):
            continue
        screening = record.get("screening") or {}
        metrics = {
            key: screening[key]
            for key in STATIC_SCREENING_KEYS
            if screening.get(key) is not None
        }
        if metrics:
            out[str(record["mint"])] = metrics
    return out


def _created_at(
    index: CaptureIndex, records: Sequence[Mapping[str, Any]]
) -> dict[str, float]:
    created = {
        mint: _float(row.get("timestamp")) for mint, row in index.creates.items()
    }
    for record in records:
        mint = record.get("mint")
        if record.get("event") == "screening" and mint and str(mint) not in created:
            created[str(mint)] = _float(record.get("timestamp"))
    return created


def scan_shadow_entries(
    records: Sequence[Mapping[str, Any]],
    config: TradingBotConfig,
    variants: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The ``shadow_entry`` rows ``variants`` (default: the config's
    ``shadow_variants``) would have written on this capture."""
    parsed = parse_shadow_variants(
        list(variants if variants is not None else config.shadow_variants or ())
    )
    if not parsed:
        return []
    index = CaptureIndex.from_records(records)
    created = _created_at(index, records)
    static = _static_metrics(records)
    prices = _price_rows(records)
    delay = max(0.0, float(getattr(config, "paper_entry_delay_seconds", 0.0) or 0.0))
    book = ShadowVariantBook(config, parsed, max_mints=10**6)
    engine = OrderFlowEngine(max_retention_seconds=10**9, max_tracked_tokens=10**6)
    events: list[tuple[float, int, str, Mapping[str, Any]]] = [
        (_float(row.get("timestamp")), 0, str(mint), row)
        for mint, rows in index.trades.items()
        for row in rows
    ]
    events += [
        (_float(row.get("timestamp")), 1, str(row["mint"]), row)
        for row in records
        if row.get("event") == "curve_poll"
        and row.get("source") == "watch"
        and row.get("mint")
        and row.get("real_sol_reserves") is not None
    ]
    events.sort(key=lambda item: (item[0], item[1]))
    out: list[dict[str, Any]] = []
    for ts, kind, mint, row in events:
        real_sol: float | None = None
        if kind == 0:
            engine.record_trade(
                mint,
                bool(row.get("is_buy")),
                _float(row.get("sol_amount")),
                str(row.get("user") or ""),
                timestamp=ts,
            )
        else:
            real_sol = _float(row.get("real_sol_reserves"))
        if not book.knows(mint):
            book.remember(
                mint,
                created_at=created.get(mint, ts),
                creator=index.creator(mint),
                static_metrics=static.get(mint),
            )
        for signal in book.evaluate(
            engine,
            mint,
            now=ts,
            market_cap_sol=_float(row.get("market_cap_sol")),
            real_sol=real_sol,
        ):
            due = signal.signal_time + delay
            times, caps = prices.get(mint, ([], []))
            at = bisect_left(times, due)
            if at < len(times) and times[at] - due <= FILL_WINDOW_SECONDS:
                fill_time, fill_cap = times[at], caps[at]
            else:
                fill_time, fill_cap = due, None
            shadow_row = shadow_fill_record(
                signal, fill_market_cap_sol=fill_cap, fill_time=fill_time
            )
            shadow_row["scanned"] = True
            out.append(shadow_row)
    out.sort(key=lambda r: _float(r.get("timestamp")))
    return out


def with_scanned_entries(
    records: Sequence[Mapping[str, Any]],
    config: TradingBotConfig,
    variants: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The capture with its recorded ``shadow_entry`` rows replaced by scanned ones."""
    kept = [dict(r) for r in records if r.get("event") != "shadow_entry"]
    return kept + scan_shadow_entries(records, config, variants)


__all__ = [
    "FILL_WINDOW_SECONDS",
    "scan_shadow_entries",
    "with_scanned_entries",
]
