"""Alerts for unattended operation (Sprint 24D, FEAT-50).

Three things an operator running ``pumpbot --headless`` under a supervisor needs
to hear about without watching the dashboard:

* **Daily summary** (:class:`DailySummarySchedule`): once per UTC day at
  ``daily_summary_hour_utc``, net PnL, trades, fees + tips + rent, breaker state,
  reconciliation and buying state for the period since the previous summary.
  The period is the difference of the persisted session ``PnlTotals``, so it is
  exact across restarts and independent of the 50-entry ledger.
* **Degradation** (:class:`DegradationMonitor`): one alert when a condition
  (stream, RPC) has been degraded for longer than ``degradation_alert_minutes``,
  one when it recovers. Short blips never alert.
* **Reconciliation gap** (:class:`ReconcileGapWatcher`): one alert per new
  ``pumpfun-audit reconcile`` result that reports a gap.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from trading_pump.bot.pnl import _FLOAT_FIELDS, _INT_FIELDS, PnlTotals


def _utc(ts: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)


def _utc_date(ts: float) -> str:
    return _utc(ts).strftime("%Y-%m-%d")


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h{int(seconds % 3600 // 60):02d}m"


def pnl_delta(current: PnlTotals, baseline: PnlTotals) -> PnlTotals:
    """``current - baseline`` for every counter (open positions not included).

    If any count went down the session totals were reset (status file removed),
    so the whole of ``current`` is the period.
    """
    if any(getattr(current, n) < getattr(baseline, n) for n in _INT_FIELDS):
        baseline = PnlTotals()
    delta = PnlTotals()
    for name in _FLOAT_FIELDS:
        setattr(delta, name, float(getattr(current, name)) - getattr(baseline, name))
    for name in _INT_FIELDS:
        setattr(delta, name, int(getattr(current, name)) - getattr(baseline, name))
    return delta


@dataclass
class DailySummarySchedule:
    """When the daily summary is due, and the totals it is measured from."""

    hour_utc: int = 0
    last_sent_date: str = ""
    period_start: float | None = None
    baseline: dict[str, Any] = field(default_factory=dict)

    def prime(self, totals: PnlTotals, now: float) -> None:
        """First run: start the period now; the first summary waits for the next slot."""
        if self.period_start is not None:
            return
        self.baseline = totals.to_dict()
        self.period_start = now
        if _utc(now).hour >= self.hour_utc:
            self.last_sent_date = _utc_date(now)

    def due(self, now: float) -> bool:
        return _utc(now).hour >= self.hour_utc and self.last_sent_date != _utc_date(now)

    def period_totals(self, totals: PnlTotals) -> PnlTotals:
        return pnl_delta(totals, PnlTotals.from_dict(self.baseline))

    def mark_sent(self, totals: PnlTotals, now: float) -> None:
        self.last_sent_date = _utc_date(now)
        self.baseline = totals.to_dict()
        self.period_start = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "hour_utc": self.hour_utc,
            "last_sent_date": self.last_sent_date,
            "period_start": self.period_start,
            "baseline": dict(self.baseline),
        }

    @classmethod
    def from_dict(cls, data: Any, *, hour_utc: int = 0) -> "DailySummarySchedule":
        """Restores the schedule; the configured hour always wins over the stored one."""
        if not isinstance(data, dict):
            return cls(hour_utc=hour_utc)
        start = data.get("period_start")
        baseline = data.get("baseline")
        return cls(
            hour_utc=hour_utc,
            last_sent_date=str(data.get("last_sent_date") or ""),
            period_start=float(start) if isinstance(start, (int, float)) else None,
            baseline=dict(baseline) if isinstance(baseline, dict) else {},
        )


def _sol(value: float) -> str:
    return f"{value:+.4f} SOL"


def format_daily_summary(
    *,
    mode: str,
    now: float,
    period_start: float | None,
    period: PnlTotals,
    session: PnlTotals,
    wallet_balance_sol: float,
    open_positions: int,
    breaker: str,
    drawdown_pct: float,
    reconciliation: str,
    buying: str,
    health: str,
    swept_sol: float = 0.0,
) -> str:
    """Plain-text daily summary (fits Slack, Discord and Telegram)."""
    since = (
        _utc(period_start).strftime("%Y-%m-%d %H:%M UTC")
        if period_start is not None
        else "start"
    )
    lines = [
        f"pumpbot daily summary ({mode}) {_utc_date(now)}, since {since}",
        f"Net PnL: {_sol(period.net_pnl_sol)} (gross {_sol(period.gross_pnl_sol)}, "
        f"costs {period.costs_sol:.4f} SOL: fees {period.fees_sol:.4f}, "
        f"tips {period.tips_sol:.4f}, rent {period.rent_sol:+.4f})",
        f"Trades: {period.buys} buys, {period.sells} sells; "
        f"{period.positions_closed} positions closed, win rate {period.win_rate:.0%}, "
        f"expectancy {_sol(period.expectancy_sol)}",
        f"Session net: {_sol(session.net_pnl_sol)} | wallet {wallet_balance_sol:.4f} SOL"
        f" | open positions {open_positions}",
        f"Breaker: {breaker} | drawdown today {drawdown_pct:.1%}",
        f"Reconciliation: {reconciliation}",
        f"Buying: {buying} | health: {health}",
    ]
    if swept_sol > 0:
        lines.append(f"Swept to cold wallet (total): {swept_sol:.4f} SOL")
    return "\n".join(lines)


@dataclass
class DegradationMonitor:
    """Alerts once per condition after it has been degraded for ``threshold_seconds``."""

    threshold_seconds: float = 300.0
    _since: dict[str, float] = field(default_factory=dict)
    _alerted: set[str] = field(default_factory=set)

    @property
    def enabled(self) -> bool:
        return self.threshold_seconds > 0

    def update(
        self, name: str, degraded: bool, *, now: float, detail: str = ""
    ) -> str | None:
        """Feeds one observation; returns an alert message when one is due."""
        if not self.enabled:
            return None
        if degraded:
            since = self._since.setdefault(name, now)
            if name in self._alerted or now - since < self.threshold_seconds:
                return None
            self._alerted.add(name)
            suffix = f": {detail}" if detail else ""
            return f"ALERT {name} degraded for {format_duration(now - since)}{suffix}"
        since_opt = self._since.pop(name, None)
        if name not in self._alerted:
            return None
        self._alerted.discard(name)
        duration = format_duration(now - since_opt) if since_opt is not None else "?"
        return f"RECOVERED {name} after {duration}"

    def degraded_for(self, now: float) -> dict[str, float]:
        return {name: max(0.0, now - since) for name, since in self._since.items()}


@dataclass
class ReconcileGapWatcher:
    """Alerts once for each new reconciliation result that reports a gap."""

    last_checked_at: float | None = None

    def check(self, status: dict[str, Any] | None) -> str | None:
        if not status:
            return None
        checked_at = status.get("checked_at")
        if not isinstance(checked_at, (int, float)):
            return None
        if self.last_checked_at is not None and checked_at <= self.last_checked_at:
            return None
        self.last_checked_at = float(checked_at)
        if status.get("ok"):
            return None
        problems = status.get("problems") or []
        detail = "; ".join(str(p) for p in problems[:3]) or "see reconcile_status.json"
        return f"ALERT reconciliation GAP for {status.get('wallet', '?')}: {detail}"


__all__ = [
    "DailySummarySchedule",
    "DegradationMonitor",
    "ReconcileGapWatcher",
    "format_daily_summary",
    "format_duration",
    "pnl_delta",
]
