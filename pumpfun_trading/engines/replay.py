from __future__ import annotations

import glob
import gzip
import json
from datetime import datetime, timezone
from math import inf
from pathlib import Path
from typing import Any, Iterable, Sequence

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.strategies.arbitrage import CrossVenueDisparityMonitor
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.copy_trading import CopyTradeEngine
from pumpfun_trading.strategies.decision import TradingStrategy
from pumpfun_trading.strategies.exits import (
    ExitAction,
    ExitDecision,
    PositionExitState,
    evaluate_exit_strategy,
)
from pumpfun_trading.strategies.graduation import (
    PRE_GRADUATION_MIN_POLLED_SAMPLES,
    GraduationEngine,
)
from pumpfun_trading.strategies.momentum import OrderFlowEngine, near_graduation_expiry

# Abstract token units per replay position. The live exit stack works in raw
# token amounts; replay only needs the fraction sold, so each position starts
# with this many units (far above any ``min_sell_balance``).
LIVE_POSITION_TOKEN_UNITS = 10**12

# Pump.fun curve invariant in SOL x UI tokens (30 SOL x 1.073e9 tokens): a
# market cap in SOL maps back to the curve's virtual (and so real) SOL reserve.
CURVE_K_SOL_TOKENS = 30.0 * 1_073_000_000.0
CURVE_INITIAL_VIRTUAL_SOL = 30.0
# A paper buy reads the curve just after its entry delay; a recorded curve read
# of the mint this soon after the fill is due is that read (curve_poll rows).
CURVE_READ_FILL_TOLERANCE_SECONDS = 1.0
# Capture rows that are not market data.
NON_MARKET_EVENTS = frozenset({"screening", "shadow_entry"})


def real_sol_from_market_cap(market_cap_sol: float) -> float:
    """Real SOL in a standard curve priced at ``market_cap_sol`` (SOL)."""
    if market_cap_sol <= 0:
        return 0.0
    virtual_sol = (market_cap_sol * CURVE_K_SOL_TOKENS / 1_000_000_000.0) ** 0.5
    return max(0.0, virtual_sol - CURVE_INITIAL_VIRTUAL_SOL)


class PaperTradingEngine:
    """Lightweight paper-trading engine for historical token snapshots.

    With ``live_fidelity=True`` (requires ``strategy_config``) the engine sizes
    entries and manages exits exactly like the live bot (BUG-61): a fixed
    ``buy_amount_sol`` per entry gated by the live risk limits, and the full exit
    stack from ``strategies/exits.py`` (stop-loss, stagnant and max-hold
    timeouts, tiered take-profits, moonbag floor, trailing stop). Passing a
    ``cost_model`` (live-fidelity only) also books the modelled fee, priority fee,
    Jito tip and token-account rent of every trade, so ``pnl`` is net of costs.

    ``entry_mode`` picks the live-fidelity entries: ``live_fills`` buys only where
    the live bot bought (its recorded fills, so exits and sizing can be compared
    with the audit trail); ``signals`` buys on buy signals; ``auto`` (default)
    uses ``live_fills`` when the dataset contains recorded fills. The live
    screener (social links, holders, creator history) is not replayed. Captures
    from v0.2.1 on hold ``event = "screening"`` records of what it saw (for
    filter analysis); the replay loop skips them.

    ``confirmed`` (the default under ``auto`` when the config has
    ``entry_mode: "confirmed"``, FEAT-52) models the watch -> confirm path: new
    tokens whose recorded screening passed are watched, promoted once their curve
    (derived from the market cap) grew by ``watch_promote_min_sol_growth`` within
    the subscription budget, and bought when the order flow seen *after*
    promotion confirms demand inside the age window and market-cap band. The
    creator is left out of the buyer count; buys are tagged ``momentum``.
    Promotion is optimistic by up to one poll interval.

    Entries that are not mirrored from recorded fills pay the paper latency the
    live bot pays (``paper_entry_delay_seconds`` / ``paper_entry_slippage_bps``):
    the fill is priced from the last curve price at signal + delay, worsened by
    the penalty, and the position takes no exits until it has filled.
    """

    def __init__(
        self,
        *,
        initial_cash: float = 100.0,
        max_positions: int = 1,
        fee_bps: int = 100,
        slippage_bps: int = 100,
        buy_fraction: float = 0.5,
        take_profit: float = 1.5,
        stop_loss: float = 0.85,
        strategy_config: TradingBotConfig | None = None,
        enable_order_flow_momentum: bool = False,
        enable_raydium_graduation: bool = False,
        enable_copy_trading: bool = False,
        enable_cross_venue_arbitrage: bool = False,
        arb_cooldown_seconds: float = 60.0,
        live_fidelity: bool = False,
        cost_model: ReplayCostModel | None = None,
        entry_mode: str = "auto",
    ) -> None:
        if entry_mode not in {"auto", "live_fills", "signals", "confirmed"}:
            raise ValueError(f"Unsupported entry_mode: {entry_mode}")
        if entry_mode == "confirmed" and not live_fidelity:
            raise ValueError("entry_mode='confirmed' requires live_fidelity=True")
        if live_fidelity and strategy_config is None:
            raise ValueError("live_fidelity=True requires a strategy_config")
        if cost_model is not None and not live_fidelity:
            raise ValueError("cost_model requires live_fidelity=True")
        if cost_model is not None:
            fee_bps = cost_model.protocol_fee_bps
        if strategy_config is not None:
            if take_profit == 1.5 and hasattr(strategy_config, "take_profit"):
                take_profit = strategy_config.take_profit
            if stop_loss == 0.85 and hasattr(strategy_config, "stop_loss"):
                stop_loss = strategy_config.stop_loss
            if max_positions == 1 and hasattr(strategy_config, "max_active_positions"):
                max_positions = strategy_config.max_active_positions

        self.initial_cash = float(initial_cash)
        self.max_positions = int(max_positions)
        self.fee_bps = int(fee_bps)
        self.slippage_bps = int(slippage_bps)
        self.buy_fraction = float(buy_fraction)
        self.take_profit = float(take_profit)
        self.stop_loss = float(stop_loss)
        self.strategy_config = strategy_config
        self.live_fidelity = bool(live_fidelity)
        self.cost_model = cost_model
        self.entry_mode = entry_mode
        self.enable_order_flow_momentum = enable_order_flow_momentum or (
            bool(strategy_config.enable_momentum_signals) if strategy_config else False
        )
        self.enable_raydium_graduation = enable_raydium_graduation or (
            bool(strategy_config.enable_raydium_migration_sniping)
            if strategy_config
            else False
        )
        self.enable_copy_trading = enable_copy_trading or (
            bool(strategy_config.enable_copy_trading) if strategy_config else False
        )
        self.enable_cross_venue_arbitrage = enable_cross_venue_arbitrage or (
            bool(strategy_config.enable_cross_venue_arbitrage)
            if strategy_config
            else False
        )
        self.order_flow_engine = OrderFlowEngine()
        self.confirmed_entries = self.live_fidelity and (
            entry_mode == "confirmed"
            or (
                entry_mode == "auto"
                and getattr(strategy_config, "entry_mode", "launch") == "confirmed"
            )
        )
        if strategy_config is not None:
            self.order_flow_engine.max_watch_mints = int(
                getattr(strategy_config, "watch_max_mints", 300) or 300
            )
        self.graduation_engine = GraduationEngine()
        self.copy_trade_engine = CopyTradeEngine()
        self.arb_monitor = CrossVenueDisparityMonitor()
        self.arb_cooldown_seconds = float(arb_cooldown_seconds)
        if strategy_config and getattr(strategy_config, "copy_trading_wallets", None):
            self.copy_trade_engine.registry.register_wallets(
                list(strategy_config.copy_trading_wallets)
            )

    @staticmethod
    def _coerce_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "items", "snapshots", "records", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if any(
                k in payload
                for k in (
                    "mint",
                    "address",
                    "price",
                    "market_cap",
                    "market_cap_sol",
                    "timestamp",
                    "time",
                )
            ):
                return [payload]
        return []

    @staticmethod
    def _snapshot_value(snapshot: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in snapshot and snapshot.get(key) is not None:
                return snapshot.get(key)
        return None

    @staticmethod
    def _snapshot_float(snapshot: dict[str, Any], *keys: str) -> float:
        value = PaperTradingEngine._snapshot_value(snapshot, *keys)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_timestamp(value: Any) -> float | None:
        """Parse unix seconds, unix milliseconds or ISO-8601 into seconds (BUG-84)."""
        if value is None or isinstance(value, bool):
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            text = str(value).strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        return seconds / 1000.0 if seconds > 1e11 else seconds

    @staticmethod
    def _read_records_from_file(file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists() or not file_path.is_file():
            return []

        is_gz = file_path.name.endswith(".gz") or file_path.suffix.lower() == ".gz"
        try:
            opener = (
                gzip.open(file_path, "rt", encoding="utf-8")
                if is_gz
                else open(file_path, "r", encoding="utf-8")
            )
            with opener as handle:
                lines = [line.strip() for line in handle if line.strip()]
                if not lines:
                    return []

                # If there are multiple lines or file is a jsonl format, parse line-by-line
                if len(lines) > 1 or ".jsonl" in file_path.name:
                    records: list[dict[str, Any]] = []
                    for line_str in lines:
                        try:
                            item = json.loads(line_str)
                            if isinstance(item, dict):
                                records.append(item)
                            elif isinstance(item, list):
                                records.extend(PaperTradingEngine._coerce_records(item))
                        except json.JSONDecodeError:
                            continue
                    if records:
                        return records

                # Fallback: parse entire joined content as JSON payload
                full_content = "\n".join(lines)
                try:
                    payload = json.loads(full_content)
                    return PaperTradingEngine._coerce_records(payload)
                except json.JSONDecodeError:
                    return []
        except Exception:
            return []

    @staticmethod
    def load_history(path: str | Path) -> list[dict[str, Any]]:
        """
        Loads and aggregates replay snapshots from a single file (.jsonl / .json / .gz),
        a directory containing chunked archives, or a glob pattern.
        """
        target = Path(path)
        records: list[dict[str, Any]] = []

        if target.is_dir():
            files = sorted(
                [f for f in target.glob("*replay*.jsonl*") if f.is_file()]
                or [f for f in target.glob("*.jsonl*") if f.is_file()]
                or [f for f in target.glob("*.json*") if f.is_file()],
                key=lambda p: p.stat().st_mtime,
            )
            for f in files:
                records.extend(PaperTradingEngine._read_records_from_file(f))
        elif target.is_file():
            records.extend(PaperTradingEngine._read_records_from_file(target))
        else:
            matching = sorted(glob.glob(str(path)))
            if matching:
                for m in matching:
                    mf = Path(m)
                    if mf.is_file():
                        records.extend(PaperTradingEngine._read_records_from_file(mf))
            else:
                return []

        # Sort chronologically; records without a parseable timestamp inherit the
        # previous record's time so they keep their original position (BUG-84).
        keys: list[float] = []
        last_ts = float("-inf")
        for record in records:
            parsed = PaperTradingEngine._parse_timestamp(
                PaperTradingEngine._snapshot_timestamp(record)
            )
            if parsed is not None:
                last_ts = parsed
            keys.append(last_ts)
        order = sorted(range(len(records)), key=lambda i: keys[i])
        return [records[i] for i in order]

    @staticmethod
    def _snapshot_mint(snapshot: dict[str, Any]) -> str:
        value = PaperTradingEngine._snapshot_value(
            snapshot, "mint", "address", "token_mint", "tokenMint"
        )
        return str(value) if value is not None else "unknown-mint"

    @staticmethod
    def _snapshot_name(snapshot: dict[str, Any]) -> str:
        value = PaperTradingEngine._snapshot_value(
            snapshot, "mint_name", "token_name", "name", "display_name", "displayName"
        )
        return str(value) if value is not None else "unknown"

    @staticmethod
    def _snapshot_timestamp(snapshot: dict[str, Any]) -> Any:
        return PaperTradingEngine._snapshot_value(
            snapshot,
            "timestamp",
            "time",
            "event_time",
            "ts",
            "created_at",
            "createdAt",
        )

    @staticmethod
    def _snapshot_price(snapshot: dict[str, Any]) -> float:
        return PaperTradingEngine._snapshot_float(
            snapshot,
            "price",
            "price_usd",
            "priceUsd",
            "last_price",
            "lastPrice",
            "market_cap_sol",
            "marketCapSol",
            "market_cap",
            "marketCap",
        )

    @staticmethod
    def _buy_signal(
        snapshot: dict[str, Any],
        momentum_triggered: bool = False,
        graduation_triggered: bool = False,
        copy_trade_triggered: bool = False,
        pre_grad_triggered: bool = False,
    ) -> bool:
        if isinstance(snapshot.get("buy_signal"), bool):
            return bool(snapshot["buy_signal"])
        if isinstance(snapshot.get("signal"), str):
            if snapshot["signal"].lower() in {"buy", "long", "entry"}:
                return True
        if (
            momentum_triggered
            or graduation_triggered
            or copy_trade_triggered
            or pre_grad_triggered
        ):
            return True
        return bool(snapshot.get("should_buy"))

    @staticmethod
    def _sell_signal(snapshot: dict[str, Any]) -> bool:
        if isinstance(snapshot.get("sell_signal"), bool):
            return bool(snapshot["sell_signal"])
        if isinstance(snapshot.get("signal"), str):
            if snapshot["signal"].lower() in {"sell", "exit", "close"}:
                return True
        if (
            snapshot.get("complete") is True
            or snapshot.get("txType") == "complete"
            or snapshot.get("event") == "complete"
        ):
            return True
        return bool(snapshot.get("should_sell"))

    @staticmethod
    def _is_live_fill(snapshot: dict[str, Any], side: str) -> bool:
        """A fill the live bot recorded (``--record-replay``): ``signal`` plus a
        ``reason``. Market-trade and new-token snapshots carry no ``reason``."""
        return (
            str(snapshot.get("signal") or "").lower() == side
            and "reason" in snapshot
            and "user" not in snapshot
        )

    @staticmethod
    def _is_new_token(snapshot: dict[str, Any]) -> bool:
        """A recorded create event: ``signal`` buy, no trader and no fill reason."""
        return (
            str(snapshot.get("signal") or "").lower() == "buy"
            and "user" not in snapshot
            and "reason" not in snapshot
            and "sol_amount" not in snapshot
        )

    @staticmethod
    def _screening_index(
        snapshots: Sequence[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Recorded screening verdicts by mint (last one wins)."""
        index: dict[str, dict[str, Any]] = {}
        for snapshot in snapshots:
            if snapshot.get("event") == "screening" and snapshot.get("mint"):
                verdict = snapshot.get("screening")
                if isinstance(verdict, dict):
                    index[str(snapshot["mint"])] = verdict
        return index

    def _confirmed_entry(
        self,
        *,
        snapshot: dict[str, Any],
        mint: str,
        ts: float,
        market_cap: float,
        trade: tuple[bool, float, str] | None,
        open_positions: int,
        screening: dict[str, dict[str, Any]],
        flow: OrderFlowEngine,
        traded: set[str],
        stats: dict[str, int],
    ) -> dict[str, Any] | None:
        """Watch -> promote -> confirm for one snapshot; the entry metrics when it
        confirms a buy, else ``None``."""
        cfg = self.strategy_config
        assert cfg is not None
        engine = self.order_flow_engine

        def count(key: str) -> None:
            stats[key] = stats.get(key, 0) + 1

        if self._is_new_token(snapshot):
            verdict = screening.get(mint)
            if mint in traded or engine.is_watched(mint):
                return None
            if verdict is not None and not verdict.get("passed"):
                count("screen_rejected")
                return None
            engine.watch(
                mint,
                created_at=ts,
                creator=(verdict or {}).get("creator") or None,
                now=ts,
                real_sol=real_sol_from_market_cap(market_cap),
                market_cap_sol=market_cap,
            )
            count("watched")
            return None
        entry = engine.get_watch(mint)
        if entry is None:
            return None
        if not entry.near_graduation and ts - entry.watched_at > float(
            cfg.watch_ttl_seconds
        ):
            self._expire_watch(ts, stats)
            entry = engine.get_watch(mint)
            if entry is None:
                return None
        # A recorded curve read carries the real reserve; trades only the price.
        recorded_real_sol = self._snapshot_float(snapshot, "real_sol_reserves")
        engine.update_watch_curve(
            mint,
            real_sol=(
                recorded_real_sol
                if recorded_real_sol > 0
                else real_sol_from_market_cap(market_cap)
            ),
            market_cap_sol=market_cap,
            now=ts,
        )
        if entry.near_graduation:
            return None  # polled for the pre-graduation lane only
        if trade is None:
            if (
                snapshot.get("event") == "curve_poll"
                and snapshot.get("source", "watch") == "watch"
                and not entry.subscribed
                and entry.sol_growth >= float(cfg.watch_promote_min_sol_growth)
            ):
                # Live promotion runs on the watch poll, as here.
                if engine.watch_subscribed_count >= int(
                    cfg.watch_max_trade_subscriptions
                ):
                    count("budget_full")
                else:
                    engine.mark_watch_subscribed(mint)
                    count("promoted")
            return None
        if not entry.subscribed:
            if entry.sol_growth < float(cfg.watch_promote_min_sol_growth):
                return None
            if engine.watch_subscribed_count >= int(cfg.watch_max_trade_subscriptions):
                count("budget_full")
                return None
            # Live, trades arrive only after the subscription: this one is unseen.
            engine.mark_watch_subscribed(mint)
            count("promoted")
            return None
        is_buy, sol_amount, user = trade
        flow.record_trade(mint, is_buy, sol_amount, user, timestamp=ts)
        strategy = TradingStrategy(cfg)
        signal = strategy.evaluate_momentum(
            flow,
            mint,
            token_creation_timestamp=entry.created_at,
            current_time=ts,
            exclude_users=frozenset({entry.creator}) if entry.creator else None,
        )
        age = ts - entry.created_at
        if not strategy.should_buy_momentum(
            momentum_signal=signal,
            active_positions=open_positions,
            buy_attempts=0,
            token_age_seconds=age,
            market_cap_sol=market_cap,
        ):
            return None
        if self._cost_guard_refuses(stats):
            return None
        count("confirmed")
        return {
            "unique_buyers": signal.unique_buyers,
            "net_inflow_sol": signal.net_sol_inflow,
            "buy_sell_ratio": signal.buy_sell_ratio,
            "z_score": signal.z_score,
            "token_age_seconds": round(age, 1),
            "market_cap_sol": round(market_cap, 4),
            "sol_growth": round(entry.sol_growth, 6),
        }

    def _cost_guard_refuses(self, stats: dict[str, int]) -> bool:
        """``max_entry_cost_share_pct`` as ``_should_buy`` applies it live."""
        cfg = self.strategy_config
        limit = float(getattr(cfg, "max_entry_cost_share_pct", 0.0) or 0.0)
        if self.cost_model is None or limit <= 0:
            return False
        share = self.cost_model.round_trip_fixed_costs_sol() / max(
            float(getattr(cfg, "buy_amount_sol", 0.0)), 1e-9
        )
        if share > limit:
            stats["cost_guard_refused"] = stats.get("cost_guard_refused", 0) + 1
            return True
        return False

    def _expire_watch(self, ts: float, stats: dict[str, int]) -> None:
        """Watch-list expiry as the live poller runs it, near-graduation set
        included (FEAT-53)."""
        cfg = self.strategy_config
        assert cfg is not None
        engine = self.order_flow_engine
        expired = engine.expire_watch(
            ttl=float(cfg.watch_ttl_seconds), now=ts, **near_graduation_expiry(cfg)
        )
        if expired:
            stats["expired"] = stats.get("expired", 0) + len(expired)
        moved = engine.drain_near_graduation()
        if moved:
            stats["near_graduation"] = stats.get("near_graduation", 0) + len(moved)
        engine.drain_watch_evictions()

    def _curve_progress(self, mint: str) -> float | None:
        """Curve progress (0-100) the graduation engine has for ``mint``."""
        candidate = self.graduation_engine.get_candidate(mint)
        return candidate.progress_pct if candidate is not None else None

    def _paper_entry_model(self) -> tuple[float, int]:
        """``(delay_seconds, penalty_bps)`` the live paper executor applies."""
        cfg = self.strategy_config
        delay = getattr(cfg, "paper_entry_delay_seconds", 0.0)
        penalty = getattr(cfg, "paper_entry_slippage_bps", 0)
        delay = float(delay) if isinstance(delay, (int, float)) else 0.0
        penalty = int(penalty) if isinstance(penalty, int) else 0
        return max(0.0, delay), max(0, min(5_000, penalty))

    def _entry_drift_limit(self) -> float:
        """``momentum_max_entry_drift_pct`` (0 = off), as the paper executor reads it."""
        value = getattr(self.strategy_config, "momentum_max_entry_drift_pct", 0.0)
        return max(0.0, float(value)) if isinstance(value, (int, float)) else 0.0

    def _drift_refused(self, position: dict[str, Any], price: float) -> bool:
        """True when the drift guard skips this momentum entry at its fill.

        Mirrors ``execution/executor.py``: the curve at the fill (before the
        paper penalty) against the market cap the signal fired at.
        """
        limit = self._entry_drift_limit()
        if limit <= 0 or position.get("strategy") != "momentum":
            return False
        signal_price = float(position.get("signal_price") or 0.0)
        return signal_price > 0 and price / signal_price - 1.0 > limit

    def _fill_entry(
        self,
        position: dict[str, Any],
        trades: list[dict[str, Any]],
        *,
        price: float,
        ts: float,
        penalty_bps: int,
    ) -> None:
        """Price a live-fidelity entry at ``price`` (the curve when it lands).

        Mirrors ``execution/executor.py`` paper buys: with a penalty the token
        amount is cut by ``penalty_bps`` and the entry market cap raised to match
        (BUG-121); without one the engine's ``slippage_bps`` applies as before.
        """
        fee_rate = self.fee_bps / 10_000.0
        net_spend = float(position["cost_basis"]) / (1.0 + fee_rate)
        if penalty_bps > 0:
            keep = (10_000 - penalty_bps) / 10_000.0
            quantity = net_spend * keep / price
            entry_price = price / keep
        else:
            quantity = net_spend / (price * (1.0 + self.slippage_bps / 10_000.0))
            entry_price = price
        signal_ts = position.pop("fill_due", None)
        position["quantity"] = quantity
        position["entry_price"] = entry_price
        position["exit_state"] = PositionExitState(
            entry_market_cap=entry_price,
            current_market_cap=price,
            peak_market_cap=entry_price,
            initial_token_amount=LIVE_POSITION_TOKEN_UNITS,
            remaining_token_amount=LIVE_POSITION_TOKEN_UNITS,
            entry_time=ts,
            last_price_change_at=ts,
            last_price=price,
        )
        buy = trades[int(position["buy_trade_index"])]
        buy["entry_price"] = entry_price
        buy["quantity"] = quantity
        metrics = buy.get("entry_metrics")
        if signal_ts is not None and isinstance(metrics, dict):
            signal_price = float(position.get("signal_price") or price)
            metrics["fill_market_cap_sol"] = round(entry_price, 4)
            metrics["fill_drift_pct"] = round(price / signal_price - 1.0, 4)

    def _apply_mirrored_entry(
        self,
        position: dict[str, Any],
        trades: list[dict[str, Any]],
        snapshot: dict[str, Any],
        *,
        price: float,
        ts: float,
    ) -> None:
        """Lane, creator, metrics and paper penalty a mirrored fill row carries.

        The shadow-variant read-out (``engines/shadow_report.py``) mirrors
        synthetic fills that carry these keys; fills the bot recorded carry none
        of them, so they mirror exactly as before.
        """
        strategy = snapshot.get("strategy")
        if isinstance(strategy, str) and strategy:
            position["strategy"] = strategy
            position["creator"] = snapshot.get("creator")
            trades[-1]["strategy"] = strategy
        metrics = snapshot.get("entry_metrics")
        if isinstance(metrics, dict):
            trades[-1]["entry_metrics"] = dict(metrics)
        penalty = snapshot.get("entry_penalty_bps")
        if isinstance(penalty, int) and not isinstance(penalty, bool) and penalty > 0:
            position["buy_trade_index"] = len(trades) - 1
            self._fill_entry(
                position, trades, price=price, ts=ts, penalty_bps=min(5_000, penalty)
            )

    @staticmethod
    def _cancel_entry(
        position: dict[str, Any],
        trades: list[dict[str, Any]],
        buys_per_mint: dict[str, int],
    ) -> float:
        """Undo a buy the drift guard skipped; returns the cash to give back.

        A skipped paper buy costs nothing, so the spend and its modelled costs
        are refunded and the buy is flagged for removal from the ledger.
        """
        trades[int(position["buy_trade_index"])]["drift_refused"] = True
        mint = str(position.get("mint") or "")
        if buys_per_mint.get(mint, 0) > 0:
            buys_per_mint[mint] -= 1
        return float(position["cost_basis"]) + float(position.get("costs_sol", 0.0))

    def _live_entry_size(
        self,
        cash: float,
        positions: dict[str, dict[str, Any]],
        mint: str,
        buys_per_mint: dict[str, int],
        rejections: dict[str, int],
    ) -> float:
        """SOL to spend on a live-fidelity entry, or 0.0 when a live limit rejects it.

        Mirrors ``bot/risk.py::check_risk_limits`` and the account equity guard.
        """
        cfg = self.strategy_config
        assert cfg is not None
        entry = float(cfg.buy_amount_sol)
        reason = ""
        exposure = sum(float(p["cost_basis"]) for p in positions.values())
        attempts_cap = int(cfg.max_buy_attempts_per_mint)
        exposure_cap = float(cfg.max_total_exposure_sol)
        if entry <= 0:
            reason = "no_buy_amount"
        elif attempts_cap > 0 and buys_per_mint.get(mint, 0) >= attempts_cap:
            reason = "max_buy_attempts_per_mint"
        elif exposure + entry > exposure_cap:
            reason = "max_total_exposure"
        elif entry > float(cfg.max_position_size_sol):
            reason = "max_position_size"
        elif exposure_cap > 0 and (
            max([float(p["cost_basis"]) for p in positions.values()] + [entry])
            / exposure_cap
            > float(cfg.max_token_concentration_pct)
        ):
            reason = "token_concentration"
        elif cash - entry < float(cfg.reserve_balance_sol):
            reason = "reserve_balance"
        if reason:
            rejections[reason] = rejections.get(reason, 0) + 1
            return 0.0
        return entry

    @classmethod
    def _snapshot_market_cap(cls, snapshot: dict[str, Any], price: float) -> float:
        """Market cap in SOL; captures store the per-token price as mc / 1e9."""
        market_cap = cls._snapshot_float(snapshot, "market_cap_sol", "marketCapSol")
        if market_cap > 0:
            return market_cap
        return price * 1_000_000_000.0 if price < 1.0 else price

    def _note_replay_follow_on_buy(
        self,
        position: dict[str, Any],
        trade: tuple[bool, float, str],
        ts: float,
    ) -> None:
        """Feed the buy-flow stagnation exit like the live trade handler."""
        cfg = self.strategy_config
        assert cfg is not None
        is_buy, sol_amount, user = trade
        if not is_buy or sol_amount < float(cfg.stagnant_min_buy_sol):
            return
        if user and user == position.get("creator"):
            return
        position["exit_state"].last_qualifying_buy_at = ts

    def _sell_value(self, quantity: float, price: float) -> float:
        """SOL received for selling ``quantity`` at ``price`` after slippage and fee."""
        exec_sell_price = price * (1.0 - self.slippage_bps / 10_000.0)
        return quantity * exec_sell_price * (1.0 - self.fee_bps / 10_000.0)

    def _live_exit_pass(
        self,
        *,
        mint: str,
        price: float,
        ts: float,
        raw_ts: Any,
        positions: dict[str, dict[str, Any]],
        trades: list[dict[str, Any]],
        last_prices: dict[str, float],
        forced_reason: str,
    ) -> tuple[float, bool]:
        """Run the live exit stack over every open position.

        The snapshot's own mint is re-priced; the others are evaluated at their
        last price so time-based exits (stagnant, max-hold) fire on the replay
        clock like the live refresh loop. Returns ``(cash_in, exited_mint)``.
        """
        cfg = self.strategy_config
        assert cfg is not None
        cash_in = 0.0
        exited_mint = False
        for pos_mint in list(positions):
            position = positions[pos_mint]
            if "fill_due" in position:
                # The paper buy has not landed yet: nothing to exit.
                continue
            state: PositionExitState = position["exit_state"]
            if pos_mint == mint and forced_reason:
                state.update_price(
                    price, now=ts, threshold_pct=cfg.stagnant_price_delta_threshold_pct
                )
                decision = ExitDecision(
                    action=ExitAction.FULL_EXIT,
                    sell_fraction=1.0,
                    sell_tokens=state.remaining_token_amount,
                    reason=forced_reason,
                    exit_type=forced_reason,
                )
            else:
                decision = evaluate_exit_strategy(
                    cfg,
                    state,
                    current_market_cap=price if pos_mint == mint else None,
                    now=ts,
                    # Live exits read curve progress for the pre-graduation
                    # tranches; replay has it only from recorded curve reads.
                    curve_progress_pct=self._curve_progress(pos_mint),
                )
            if decision.action == ExitAction.HOLD:
                continue
            remaining = state.remaining_token_amount
            full = decision.action == ExitAction.FULL_EXIT
            # A held position always has units left (full exits delete it), and the
            # exit stack never asks for fewer than one unit.
            sell_tokens = remaining if full else min(decision.sell_tokens, remaining)
            ratio = sell_tokens / remaining
            full = full or ratio >= 1.0
            sold_qty = float(position["quantity"]) * ratio
            cost_part = float(position["cost_basis"]) * ratio
            exit_price = last_prices.get(pos_mint, position["entry_price"])
            exit_value = self._sell_value(sold_qty, exit_price)
            buy_cost_part = float(position.get("costs_sol", 0.0)) * ratio
            sell_cost = (
                self.cost_model.sell_costs(full_exit=full).total_cost_sol
                if self.cost_model is not None
                else 0.0
            )
            gross_pnl = exit_value - cost_part
            costs = buy_cost_part + sell_cost
            pnl = gross_pnl - costs
            trade_name = position.get("name") or ""
            trades.append(
                {
                    "index": len(trades),
                    "timestamp": raw_ts,
                    "mint": pos_mint,
                    "name": trade_name,
                    "mint_name": trade_name,
                    "token_name": trade_name,
                    "action": "sell",
                    "partial": not full,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "quantity": sold_qty,
                    "cost": cost_part,
                    "proceeds": exit_value,
                    "pnl": pnl,
                    "gross_pnl_sol": gross_pnl,
                    "costs_sol": costs,
                    "net_pnl_sol": pnl,
                    "return_pct": pnl / cost_part if cost_part > 0 else 0.0,
                    "reason": decision.exit_type,
                    "exit_detail": decision.reason,
                    "hold_seconds": max(0.0, ts - state.entry_time),
                }
            )
            cash_in += exit_value - sell_cost
            if full:
                del positions[pos_mint]
                exited_mint = exited_mint or pos_mint == mint
            else:
                position["quantity"] = float(position["quantity"]) - sold_qty
                position["cost_basis"] = float(position["cost_basis"]) - cost_part
                position["costs_sol"] = (
                    float(position.get("costs_sol", 0.0)) - buy_cost_part
                )
                state.record_partial_exit(decision.target_tier, sell_tokens)
        return cash_in, exited_mint

    def run(self, snapshots: Sequence[dict[str, Any]]) -> dict[str, Any]:
        cash = self.initial_cash
        positions: dict[str, dict[str, Any]] = {}
        trades: list[dict[str, Any]] = []
        equity_history: list[dict[str, Any]] = []
        last_prices: dict[str, float] = {}
        last_arb_at: dict[str, float] = {}
        buys_per_mint: dict[str, int] = {}
        entry_rejections: dict[str, int] = {}
        confirmed = self.confirmed_entries
        mirror_live_entries = (
            self.live_fidelity
            and not confirmed
            and (
                self.entry_mode == "live_fills"
                or (
                    self.entry_mode == "auto"
                    and any(self._is_live_fill(s, "buy") for s in snapshots)
                )
            )
        )
        screening = self._screening_index(snapshots) if confirmed else {}
        confirm_flow = OrderFlowEngine()
        traded_mints: set[str] = set()
        watch_stats: dict[str, int] = {}
        last_expiry_at: float | None = None
        entry_delay, entry_penalty_bps = (
            self._paper_entry_model()
            if self.live_fidelity and not mirror_live_entries
            else (0.0, 0)
        )
        # Entries waiting for their paper fill: mint -> time the buy lands.
        pending_fills: dict[str, float] = {}
        # Last price of a pending mint as of its fill time, kept while waiting
        # for the curve read the paper fill takes just after it.
        due_prices: dict[str, float] = {}
        # Captures from rc.2 on record polled curves; without them a fill is
        # priced at the first snapshot after it is due, as before.
        has_curve_reads = any(s.get("event") == "curve_poll" for s in snapshots)
        # Buys the entry drift guard skipped at the fill.
        refused_buys = 0

        for index, snapshot in enumerate(snapshots):
            if snapshot.get("event") in NON_MARKET_EVENTS:
                # Screener inputs and shadow fills: analysis data, not market data.
                continue
            mint = self._snapshot_mint(snapshot)
            name = self._snapshot_name(snapshot)
            price = max(0.0, self._snapshot_price(snapshot))
            if price <= 0.0:
                continue

            parsed_ts = self._parse_timestamp(self._snapshot_timestamp(snapshot))
            ts = parsed_ts if parsed_ts is not None else float(index)

            # A delayed paper buy fills at the curve as it was when it landed:
            # the last price seen before this (later) snapshot (BUG-121), or the
            # recorded curve read of the mint just after it, which is the read
            # the paper fill itself takes.
            is_curve_read = snapshot.get("event") == "curve_poll"
            for pending_mint, due in list(pending_fills.items()):
                if ts < due:
                    continue
                due_prices.setdefault(pending_mint, last_prices[pending_mint])
                curve_read_now = is_curve_read and pending_mint == mint
                if (
                    has_curve_reads
                    and not curve_read_now
                    and ts < due + CURVE_READ_FILL_TOLERANCE_SECONDS
                ):
                    continue
                fill_price = due_prices.pop(pending_mint)
                if curve_read_now and ts <= due + CURVE_READ_FILL_TOLERANCE_SECONDS:
                    fill_price = price
                del pending_fills[pending_mint]
                if self._drift_refused(positions[pending_mint], fill_price):
                    cash += self._cancel_entry(
                        positions.pop(pending_mint), trades, buys_per_mint
                    )
                    refused_buys += 1
                    continue
                self._fill_entry(
                    positions[pending_mint],
                    trades,
                    price=fill_price,
                    ts=due,
                    penalty_bps=entry_penalty_bps,
                )

            last_prices[mint] = price

            # Process order flow recording and momentum signal evaluation
            trade_info: tuple[bool, float, str] | None = None
            momentum_triggered = False
            copy_trade_buy_triggered = False
            copy_trade_sell_triggered = False
            copy_wallet_label = ""
            if (
                "txType" in snapshot
                or "is_buy" in snapshot
                or "sol_amount" in snapshot
                or "solAmount" in snapshot
            ):
                if "txType" in snapshot:
                    is_buy = str(snapshot.get("txType")).lower() == "buy"
                elif "is_buy" in snapshot:
                    is_buy = bool(snapshot.get("is_buy"))
                else:
                    is_buy = True
                sol_amount = float(
                    snapshot.get("sol_amount") or snapshot.get("solAmount") or 0.0
                )
                user = str(
                    snapshot.get("user")
                    or snapshot.get("traderPublicKey")
                    or "replay_trader"
                )

                self.order_flow_engine.record_trade(
                    mint=mint,
                    is_buy=is_buy,
                    sol_amount=sol_amount,
                    user=user,
                    timestamp=ts,
                )
                if "user" in snapshot or "traderPublicKey" in snapshot:
                    trade_info = (is_buy, sol_amount, user)

                if self.enable_order_flow_momentum:
                    if self.strategy_config:
                        from pumpfun_trading.strategies.decision import TradingStrategy

                        strategy = TradingStrategy(self.strategy_config)
                        signal = strategy.evaluate_momentum(
                            self.order_flow_engine, mint, current_time=ts
                        )
                        momentum_triggered = signal.triggered
                    else:
                        signal = self.order_flow_engine.evaluate_momentum_signal(
                            mint, current_time=ts
                        )
                        momentum_triggered = signal.triggered

                if self.enable_copy_trading and user:
                    copy_sig = self.copy_trade_engine.record_and_evaluate(
                        user=user,
                        mint=mint,
                        sol_amount=sol_amount,
                        is_buy=is_buy,
                        timestamp=ts,
                    )
                    if copy_sig.triggered:
                        copy_wallet_label = (
                            copy_sig.wallet_label or copy_sig.wallet_address[:8]
                        )
                        if copy_sig.is_buy:
                            copy_trade_buy_triggered = True
                        else:
                            copy_trade_sell_triggered = True

            # Process bonding curve graduation tracking
            graduation_triggered = False
            pre_grad_triggered = False
            # Entry metrics of a confirmed-mode pre-graduation buy (FEAT-53).
            confirmed_pre_grad: dict[str, Any] | None = None
            real_sol = self._snapshot_float(
                snapshot, "real_sol_reserves", "realSolReserves"
            )
            virt_sol = self._snapshot_float(
                snapshot, "virtual_sol_reserves", "virtualSolReserves"
            )
            is_curve_complete = bool(
                snapshot.get("complete") is True
                or snapshot.get("txType") == "complete"
                or snapshot.get("event") == "complete"
            )

            if real_sol > 0 or is_curve_complete:
                self.graduation_engine.update_bonding_curve(
                    mint=mint,
                    bonding_curve=str(snapshot.get("bonding_curve") or ""),
                    real_sol_reserves=real_sol,
                    virtual_sol_reserves=virt_sol,
                    market_cap_sol=price,
                    complete=is_curve_complete,
                    timestamp=ts,
                )

            # Process cross-venue arbitrage evaluation (FEAT-28)
            if self.enable_cross_venue_arbitrage:
                ray_sol_flt = self._snapshot_float(
                    snapshot, "raydium_sol_reserve", "ray_sol", "raydium_sol"
                )
                ray_tok_flt = self._snapshot_float(
                    snapshot, "raydium_token_reserve", "ray_tok", "raydium_token"
                )
                ray_sol = int(ray_sol_flt * 1_000_000_000) if ray_sol_flt > 0 else 0
                ray_tok = int(ray_tok_flt) if ray_tok_flt > 0 else 200_000_000_000_000
                pump_sol = (
                    int(virt_sol * 1_000_000_000) if virt_sol > 0 else 30_000_000_000
                )
                pump_tok = int(
                    self._snapshot_float(snapshot, "virtual_token_reserves")
                    or 1_073_000_000_000_000
                )

                if ray_sol > 0:
                    opp = self.arb_monitor.evaluate_spread(
                        mint=mint,
                        pump_virtual_sol=pump_sol,
                        pump_virtual_token=pump_tok,
                        raydium_sol_reserve=ray_sol,
                        raydium_token_reserve=ray_tok,
                    )
                    # Capital must cover the input leg, and each mint has a cooldown so
                    # one disparity is not banked on every snapshot (BUG-63).
                    prev_arb = last_arb_at.get(mint)
                    if (
                        opp
                        and opp.is_profitable
                        and cash >= opp.optimal_input_sol
                        and (
                            prev_arb is None
                            or ts - prev_arb >= self.arb_cooldown_seconds
                        )
                    ):
                        last_arb_at[mint] = ts
                        # Atomic bundle: the input leg returns in the same slot.
                        cash += opp.net_profit_sol
                        trades.append(
                            {
                                "timestamp": ts,
                                "mint": mint,
                                "name": name,
                                "action": "arbitrage",
                                "side": "ARBITRAGE",
                                "direction": opp.direction,
                                "entry_price": opp.pump_spot_price,
                                "exit_price": opp.raydium_spot_price,
                                "spread_pct": opp.spread_pct,
                                "tokens": opp.leg1_min_amount_out,
                                "cost": opp.optimal_input_sol,
                                "proceeds": opp.expected_output_sol,
                                "fee": opp.estimated_fees_sol
                                + opp.estimated_jito_tip_sol,
                                "pnl": opp.net_profit_sol,
                                "return_pct": (
                                    (opp.net_profit_sol / opp.optimal_input_sol)
                                    if opp.optimal_input_sol > 0
                                    else 0.0
                                ),
                            }
                        )

            # Pre-graduation harvesting is independent of the arbitrage flag (BUG-82).
            if self.strategy_config and getattr(
                self.strategy_config, "enable_pre_graduation_harvesting", False
            ):
                min_p = (
                    self.strategy_config.pre_graduation_entry_progress_pct * 100.0
                    if self.strategy_config.pre_graduation_entry_progress_pct <= 1.0
                    else self.strategy_config.pre_graduation_entry_progress_pct
                )
                max_p = (
                    self.strategy_config.pre_graduation_max_entry_progress_pct * 100.0
                    if self.strategy_config.pre_graduation_max_entry_progress_pct <= 1.0
                    else self.strategy_config.pre_graduation_max_entry_progress_pct
                )
                grad_sig = self.graduation_engine.evaluate_pre_graduation_harvesting_entry(
                    mint=mint,
                    min_progress_pct=min_p,
                    max_progress_pct=max_p,
                    min_acceleration=self.strategy_config.pre_graduation_min_acceleration,
                    current_time=ts,
                    # Confirmed mode runs the lane on polled curves, as live.
                    min_samples=PRE_GRADUATION_MIN_POLLED_SAMPLES if confirmed else 0,
                )
                pre_grad_triggered = grad_sig.triggered
                if (
                    confirmed
                    and pre_grad_triggered
                    and snapshot.get("event") == "curve_poll"
                    and self.order_flow_engine.is_watched(mint)
                    and mint not in traded_mints
                    and mint not in positions
                    and not self._cost_guard_refuses(watch_stats)
                ):
                    # FEAT-53: live runs the lane from the watch poll only.
                    trajectory = grad_sig.trajectory
                    confirmed_pre_grad = {
                        "curve_progress_pct": (
                            trajectory.progress_pct if trajectory else None
                        ),
                        "acceleration_sol_per_sec2": (
                            round(trajectory.acceleration_sol_per_sec2, 6)
                            if trajectory
                            else None
                        ),
                        "real_sol_reserves": round(grad_sig.real_sol_reserves, 4),
                        "market_cap_sol": round(
                            self._snapshot_market_cap(snapshot, price), 4
                        ),
                    }

            if (
                snapshot.get("event") == "raydium_pool_created"
                or "poolKeys" in snapshot
                or snapshot.get("raydium_pool")
            ):
                graduation_triggered = self.enable_raydium_graduation

            if (
                trade_info is not None
                and mint in positions
                and (confirmed or positions[mint].get("strategy") == "momentum")
            ):
                self._note_replay_follow_on_buy(positions[mint], trade_info, ts)
            if confirmed:
                if last_expiry_at is None or ts - last_expiry_at >= 1.0:
                    last_expiry_at = ts
                    self._expire_watch(ts, watch_stats)

            exited_this_snapshot = False
            if self.live_fidelity:
                forced_reason = ""
                if mint in positions:
                    if copy_trade_sell_triggered:
                        forced_reason = f"copy_trade_exit_{copy_wallet_label}"
                    elif is_curve_complete:
                        forced_reason = "bonding_curve_graduated"
                    elif snapshot.get("sell_signal") is True:
                        # Only an explicit flag: recorded ``signal`` strings are
                        # market trades or the bot's own fills, not exit orders.
                        forced_reason = "sell_signal"
                cash_in, exited_this_snapshot = self._live_exit_pass(
                    mint=mint,
                    price=price,
                    ts=ts,
                    raw_ts=self._snapshot_timestamp(snapshot),
                    positions=positions,
                    trades=trades,
                    last_prices=last_prices,
                    forced_reason=forced_reason,
                )
                cash += cash_in
            elif mint in positions:
                position = positions[mint]
                price_multiplier = (
                    price / position["entry_price"]
                    if position["entry_price"] > 0
                    else 1.0
                )
                should_sell = (
                    self._sell_signal(snapshot)
                    or price_multiplier >= self.take_profit
                    or price_multiplier <= self.stop_loss
                    or copy_trade_sell_triggered
                )
                if should_sell:
                    fee_rate = self.fee_bps / 10_000.0
                    slippage_rate = self.slippage_bps / 10_000.0
                    exec_sell_price = price * (1.0 - slippage_rate)
                    gross_exit = position["quantity"] * exec_sell_price
                    exit_value = gross_exit * (1.0 - fee_rate)
                    pnl = exit_value - position["cost_basis"]
                    return_pct = (
                        pnl / position["cost_basis"]
                        if position["cost_basis"] > 0
                        else 0.0
                    )
                    reason = "sell_signal"
                    if copy_trade_sell_triggered:
                        reason = f"copy_trade_exit_{copy_wallet_label}"
                    elif is_curve_complete:
                        reason = "bonding_curve_graduated"
                    elif self._sell_signal(snapshot):
                        reason = "sell_signal"
                    elif price_multiplier >= self.take_profit:
                        reason = "take_profit"
                    else:
                        reason = "stop_loss"
                    trade_name = position.get("name") or name
                    trade = {
                        "index": len(trades),
                        "timestamp": self._snapshot_timestamp(snapshot),
                        "mint": mint,
                        "name": trade_name,
                        "mint_name": trade_name,
                        "token_name": trade_name,
                        "action": "sell",
                        "entry_price": position["entry_price"],
                        "exit_price": price,
                        "quantity": position["quantity"],
                        "pnl": pnl,
                        "return_pct": return_pct,
                        "reason": reason,
                    }
                    trades.append(trade)
                    cash += exit_value
                    del positions[mint]
                    exited_this_snapshot = True

            confirmed_metrics: dict[str, Any] | None = None
            if confirmed and mint not in positions and not exited_this_snapshot:
                confirmed_metrics = self._confirmed_entry(
                    snapshot=snapshot,
                    mint=mint,
                    ts=ts,
                    market_cap=self._snapshot_market_cap(snapshot, price),
                    trade=trade_info,
                    open_positions=len(positions),
                    screening=screening,
                    flow=confirm_flow,
                    traded=traded_mints,
                    stats=watch_stats,
                )

            # No re-entry on the same snapshot that closed the position (BUG-83).
            if (
                mint not in positions
                and not exited_this_snapshot
                and (
                    (confirmed_metrics is not None or confirmed_pre_grad is not None)
                    if confirmed
                    else (
                        self._is_live_fill(snapshot, "buy")
                        if mirror_live_entries
                        else self._buy_signal(
                            (
                                snapshot
                                if not (self.live_fidelity and "user" in snapshot)
                                else {
                                    k: v for k, v in snapshot.items() if k != "signal"
                                }
                            ),
                            momentum_triggered=momentum_triggered,
                            graduation_triggered=graduation_triggered,
                            copy_trade_triggered=copy_trade_buy_triggered,
                            pre_grad_triggered=pre_grad_triggered,
                        )
                    )
                )
                and len(positions) < self.max_positions
            ):
                if self.live_fidelity:
                    spend_budget = self._live_entry_size(
                        cash, positions, mint, buys_per_mint, entry_rejections
                    )
                else:
                    spend_budget = max(0.0, min(cash * self.buy_fraction, cash))
                if spend_budget > 0:
                    fee_rate = self.fee_bps / 10_000.0
                    slippage_rate = self.slippage_bps / 10_000.0
                    net_spend = spend_budget / (1.0 + fee_rate)
                    exec_price = price * (1.0 + slippage_rate)
                    quantity = net_spend / exec_price if exec_price > 0 else 0.0
                    buy_cost = (
                        self.cost_model.buy_costs().total_cost_sol
                        if self.cost_model is not None
                        else 0.0
                    )
                    if quantity > 0 and cash >= spend_budget + buy_cost:
                        positions[mint] = {
                            "mint": mint,
                            "name": name,
                            "quantity": quantity,
                            "entry_price": price,
                            "entry_timestamp": self._snapshot_timestamp(snapshot),
                            "cost_basis": spend_budget,
                        }
                        if self.live_fidelity:
                            positions[mint]["exit_state"] = PositionExitState(
                                entry_market_cap=price,
                                current_market_cap=price,
                                peak_market_cap=price,
                                initial_token_amount=LIVE_POSITION_TOKEN_UNITS,
                                remaining_token_amount=LIVE_POSITION_TOKEN_UNITS,
                                entry_time=ts,
                                last_price_change_at=ts,
                                last_price=price,
                            )
                            buys_per_mint[mint] = buys_per_mint.get(mint, 0) + 1
                            positions[mint]["costs_sol"] = buy_cost
                        cash -= spend_budget + buy_cost
                        if confirmed_metrics is not None:
                            buy_reason = "momentum_confirmed"
                            self.order_flow_engine.unwatch(mint)
                            traded_mints.add(mint)
                        elif confirmed_pre_grad is not None:
                            buy_reason = "pre_graduation_harvesting_entry"
                            self.order_flow_engine.unwatch(mint)
                            traded_mints.add(mint)
                        elif copy_trade_buy_triggered:
                            buy_reason = f"copy_trade_{copy_wallet_label}"
                        elif graduation_triggered:
                            buy_reason = "raydium_graduation_snipe"
                        elif pre_grad_triggered:
                            buy_reason = "pre_graduation_harvesting_entry"
                        elif momentum_triggered:
                            buy_reason = "momentum_spike"
                        else:
                            buy_reason = "buy_signal"
                        trades.append(
                            {
                                "index": len(trades),
                                "timestamp": self._snapshot_timestamp(snapshot),
                                "mint": mint,
                                "name": name,
                                "mint_name": name,
                                "token_name": name,
                                "action": "buy",
                                "entry_price": price,
                                "exit_price": None,
                                "quantity": quantity,
                                "cost": spend_budget,
                                "costs_sol": buy_cost,
                                "pnl": 0.0,
                                "return_pct": 0.0,
                                "reason": buy_reason,
                            }
                        )
                        lane_metrics = confirmed_metrics or confirmed_pre_grad
                        if lane_metrics is not None:
                            lane = (
                                "momentum"
                                if confirmed_metrics is not None
                                else "pre_graduation"
                            )
                            trades[-1]["strategy"] = lane
                            trades[-1]["entry_metrics"] = lane_metrics
                            positions[mint]["strategy"] = lane
                            positions[mint]["creator"] = (
                                screening.get(mint) or {}
                            ).get("creator")
                        if mirror_live_entries:
                            self._apply_mirrored_entry(
                                positions[mint], trades, snapshot, price=price, ts=ts
                            )
                        if self.live_fidelity and (
                            entry_delay > 0 or entry_penalty_bps > 0
                        ):
                            # Paper latency the live executor applies (BUG-121).
                            positions[mint]["buy_trade_index"] = len(trades) - 1
                            positions[mint]["signal_price"] = price
                            if entry_delay > 0:
                                positions[mint]["fill_due"] = ts + entry_delay
                                pending_fills[mint] = ts + entry_delay
                            else:
                                self._fill_entry(
                                    positions[mint],
                                    trades,
                                    price=price,
                                    ts=ts,
                                    penalty_bps=entry_penalty_bps,
                                )

            portfolio_value = cash + sum(
                position["quantity"]
                * last_prices.get(position["mint"], position["entry_price"])
                for position in positions.values()
            )
            equity_history.append(
                {
                    "timestamp": self._snapshot_timestamp(snapshot),
                    "mint": mint,
                    "equity": portfolio_value,
                    "cash": cash,
                    "open_positions": len(positions),
                }
            )

        # Buys still landing when the data ends fill at the last price seen.
        for pending_mint, due in pending_fills.items():
            end_price = due_prices.get(pending_mint, last_prices[pending_mint])
            if self._drift_refused(positions[pending_mint], end_price):
                cash += self._cancel_entry(
                    positions.pop(pending_mint), trades, buys_per_mint
                )
                refused_buys += 1
                continue
            self._fill_entry(
                positions[pending_mint],
                trades,
                price=end_price,
                ts=due,
                penalty_bps=entry_penalty_bps,
            )
        if refused_buys:
            # Refused buys never happened: drop them from the ledger.
            trades = [t for t in trades if not t.get("drift_refused")]
            for new_index, trade in enumerate(trades):
                trade["index"] = new_index
            entry_rejections["entry_drift"] = refused_buys
            watch_stats["drift_refused"] = refused_buys

        sell_returns = [
            trade["return_pct"]
            for trade in trades
            if trade.get("action") in {"sell", "arbitrage"}
        ]
        # Profit factor uses SOL PnL, not return percentages (BUG-62).
        sell_pnls = [
            float(trade.get("pnl") or 0.0)
            for trade in trades
            if trade.get("action") in {"sell", "arbitrage"}
        ]
        gross_profit = sum(value for value in sell_pnls if value > 0)
        gross_loss = abs(sum(value for value in sell_pnls if value < 0))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = inf
        else:
            profit_factor = 0.0

        final_equity = cash + sum(
            pos["quantity"] * last_prices.get(pos["mint"], pos["entry_price"])
            for pos in positions.values()
        )

        max_drawdown = 0.0
        peak_equity = self.initial_cash
        for point in equity_history:
            peak_equity = max(peak_equity, point["equity"])
            if peak_equity > 0:
                drawdown = (peak_equity - point["equity"]) / peak_equity
                max_drawdown = max(max_drawdown, drawdown)

        summary = {
            "initial_cash": self.initial_cash,
            "final_cash": cash,
            "final_equity": final_equity,
            "total_trades": len(trades),
            "buy_count": sum(1 for trade in trades if trade["action"] == "buy"),
            "sell_count": sum(1 for trade in trades if trade["action"] == "sell"),
            "open_positions": len(positions),
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "win_rate": (
                sum(1 for value in sell_returns if value > 0) / len(sell_returns)
                if sell_returns
                else 0.0
            ),
            "average_trade_return": (
                sum(sell_returns) / len(sell_returns) if sell_returns else 0.0
            ),
            "total_return": (
                (final_equity - self.initial_cash) / self.initial_cash
                if self.initial_cash
                else 0.0
            ),
            "trades": trades,
            "equity_history": equity_history,
            "positions": {
                m: {k: v for k, v in pos.items() if k != "exit_state"}
                for m, pos in positions.items()
            },
            "live_fidelity": self.live_fidelity,
            "costs_modelled": self.cost_model is not None,
            "entries_from": (
                "confirmed"
                if confirmed
                else "live_fills" if mirror_live_entries else "signals"
            ),
            "gross_pnl_sol": sum(
                float(t.get("gross_pnl_sol", t.get("pnl") or 0.0))
                for t in trades
                if t.get("action") in {"sell", "arbitrage"}
            ),
            "costs_sol": sum(
                float(t.get("costs_sol") or 0.0)
                for t in trades
                if t.get("action") == "sell"
            ),
            "net_pnl_sol": sum(sell_pnls),
            "open_position_costs_sol": sum(
                float(pos.get("costs_sol", 0.0)) for pos in positions.values()
            ),
            "entry_rejections": entry_rejections,
        }
        if confirmed:
            summary["watch_stats"] = watch_stats
        self.trades = trades
        return summary

    def run_simulation(self, snapshots: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Alias for run() providing standard simulation execution."""
        return self.run(snapshots)


class ReplayEngine(PaperTradingEngine):
    """Backward-compatible alias retained for replay tooling."""


def run_replay(
    path: str | Path,
    *,
    engine: PaperTradingEngine | None = None,
    mint: str | None = None,
    mint_name: str | None = None,
    token_name: str | None = None,
) -> dict[str, Any]:
    replay_engine = engine or PaperTradingEngine()
    snapshots = replay_engine.load_history(path)
    target_name = mint_name if mint_name is not None else token_name
    if mint or target_name:
        filtered = []
        for snapshot in snapshots:
            s_mint = replay_engine._snapshot_mint(snapshot)
            s_name = replay_engine._snapshot_name(snapshot)
            if mint and s_mint.lower() != str(mint).lower():
                continue
            if target_name and str(target_name).lower() not in s_name.lower():
                continue
            filtered.append(snapshot)
        snapshots = filtered
    return replay_engine.run(snapshots)


def render_replay_summary(
    summary: dict[str, Any], console: Console | None = None
) -> None:
    target = console or Console()
    table = Table(title="Replay summary", header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in (
        ("initial_cash", summary.get("initial_cash")),
        ("final_equity", summary.get("final_equity")),
        ("total_trades", summary.get("total_trades")),
        ("buy_count", summary.get("buy_count")),
        ("sell_count", summary.get("sell_count")),
        ("profit_factor", summary.get("profit_factor")),
        ("max_drawdown", summary.get("max_drawdown")),
        ("win_rate", summary.get("win_rate")),
        ("average_trade_return", summary.get("average_trade_return")),
        ("open_positions", summary.get("open_positions")),
    ):
        table.add_row(str(key), str(value))
    if summary.get("live_fidelity"):
        table.add_row(
            "mode",
            "live fidelity" + (" + costs" if summary.get("costs_modelled") else ""),
        )
        for key in ("gross_pnl_sol", "costs_sol", "net_pnl_sol"):
            table.add_row(key, f"{float(summary.get(key) or 0.0):.6f}")
        rejections = summary.get("entry_rejections") or {}
        if rejections:
            table.add_row(
                "entry_rejections",
                ", ".join(f"{k}={v}" for k, v in sorted(rejections.items())),
            )
    target.print(table)


def render_replay_trades(
    trades: Iterable[dict[str, Any]], console: Console | None = None
) -> None:
    target = console or Console()
    trade_rows = list(trades)
    if not trade_rows:
        target.print("[yellow]No replay trades recorded.[/yellow]")
        return

    table = Table(title="Replay trades", header_style="bold cyan")
    table.add_column("Index")
    table.add_column("Timestamp")
    table.add_column("Mint Name")
    table.add_column("Mint")
    table.add_column("Action")
    table.add_column("Qty")
    table.add_column("P&L")
    table.add_column("Return")
    table.add_column("Reason")
    for trade in trade_rows:
        mint_name = str(
            trade.get("mint_name")
            or trade.get("token_name")
            or trade.get("name")
            or trade.get("display_name")
            or "-"
        )
        table.add_row(
            str(trade.get("index", "-")),
            str(trade.get("timestamp", "-")),
            mint_name,
            str(trade.get("mint", "-")),
            str(trade.get("action", "-")),
            f"{trade.get('quantity', 0):.6f}",
            f"{trade.get('pnl', 0):.6f}",
            f"{trade.get('return_pct', 0):.2%}",
            str(trade.get("reason", "-")),
        )
    target.print(table)


def render_replay_dashboard(
    summary: dict[str, Any], console: Console | None = None
) -> None:
    target = console or Console()
    summary_table = Table(show_lines=False, expand=True)
    summary_table.add_column("Metric")
    summary_table.add_column("Value")
    for key, value in (
        ("initial_cash", summary.get("initial_cash")),
        ("final_equity", summary.get("final_equity")),
        ("profit_factor", summary.get("profit_factor")),
        ("max_drawdown", summary.get("max_drawdown")),
        ("win_rate", summary.get("win_rate")),
        ("average_trade_return", summary.get("average_trade_return")),
        ("total_return", summary.get("total_return")),
        ("open_positions", summary.get("open_positions")),
    ):
        summary_table.add_row(str(key), str(value))

    status_panel = Panel(
        "\n".join(
            [
                f"Trades: {summary.get('total_trades', 0)}",
                f"Buys: {summary.get('buy_count', 0)}",
                f"Sells: {summary.get('sell_count', 0)}",
                f"Final cash: {summary.get('final_cash', 0.0)}",
            ]
        ),
        title="Replay Status",
        border_style="green",
    )
    target.print(
        Panel(
            Group(summary_table, status_panel),
            title="Replay Engine",
            border_style="cyan",
        )
    )
    render_replay_trades(summary.get("trades", []), console=target)


__all__ = [
    "PaperTradingEngine",
    "ReplayEngine",
    "run_replay",
    "render_replay_summary",
    "render_replay_trades",
    "render_replay_dashboard",
]
