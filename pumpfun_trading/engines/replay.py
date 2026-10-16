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
from pumpfun_trading.strategies.exits import (
    ExitAction,
    ExitDecision,
    PositionExitState,
    evaluate_exit_strategy,
)
from pumpfun_trading.strategies.graduation import GraduationEngine
from pumpfun_trading.strategies.momentum import OrderFlowEngine

# Abstract token units per replay position. The live exit stack works in raw
# token amounts; replay only needs the fraction sold, so each position starts
# with this many units (far above any ``min_sell_balance``).
LIVE_POSITION_TOKEN_UNITS = 10**12


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
    screener (social links, holders, creator history) is not replayed, because a
    capture does not record the enrichment data.
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
        if entry_mode not in {"auto", "live_fills", "signals"}:
            raise ValueError(f"Unsupported entry_mode: {entry_mode}")
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
        mirror_live_entries = self.live_fidelity and (
            self.entry_mode == "live_fills"
            or (
                self.entry_mode == "auto"
                and any(self._is_live_fill(s, "buy") for s in snapshots)
            )
        )

        for index, snapshot in enumerate(snapshots):
            mint = self._snapshot_mint(snapshot)
            name = self._snapshot_name(snapshot)
            price = max(0.0, self._snapshot_price(snapshot))
            if price <= 0.0:
                continue

            last_prices[mint] = price

            parsed_ts = self._parse_timestamp(self._snapshot_timestamp(snapshot))
            ts = parsed_ts if parsed_ts is not None else float(index)

            # Process order flow recording and momentum signal evaluation
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
                )
                pre_grad_triggered = grad_sig.triggered

            if (
                snapshot.get("event") == "raydium_pool_created"
                or "poolKeys" in snapshot
                or snapshot.get("raydium_pool")
            ):
                graduation_triggered = self.enable_raydium_graduation

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

            # No re-entry on the same snapshot that closed the position (BUG-83).
            if (
                mint not in positions
                and not exited_this_snapshot
                and (
                    self._is_live_fill(snapshot, "buy")
                    if mirror_live_entries
                    else self._buy_signal(
                        (
                            snapshot
                            if not (self.live_fidelity and "user" in snapshot)
                            else {k: v for k, v in snapshot.items() if k != "signal"}
                        ),
                        momentum_triggered=momentum_triggered,
                        graduation_triggered=graduation_triggered,
                        copy_trade_triggered=copy_trade_buy_triggered,
                        pre_grad_triggered=pre_grad_triggered,
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
                        if copy_trade_buy_triggered:
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
            "entries_from": "live_fills" if mirror_live_entries else "signals",
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
