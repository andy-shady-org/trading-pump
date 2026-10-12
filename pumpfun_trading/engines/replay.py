from __future__ import annotations

import json
from math import inf
from pathlib import Path
from typing import Any, Iterable, Sequence

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.momentum import OrderFlowEngine


class PaperTradingEngine:
    """Lightweight paper-trading engine for historical token snapshots."""

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
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.max_positions = int(max_positions)
        self.fee_bps = int(fee_bps)
        self.slippage_bps = int(slippage_bps)
        self.buy_fraction = float(buy_fraction)
        self.take_profit = float(take_profit)
        self.stop_loss = float(stop_loss)
        self.strategy_config = strategy_config
        self.enable_order_flow_momentum = enable_order_flow_momentum or (
            bool(strategy_config.enable_momentum_signals) if strategy_config else False
        )
        self.order_flow_engine = OrderFlowEngine()

    @staticmethod
    def _coerce_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "items", "snapshots", "records", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
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
    def load_history(path: str | Path) -> list[dict[str, Any]]:
        file_path = Path(path)
        if not file_path.exists():
            return []

        raw = file_path.read_text(encoding="utf-8")
        if not raw.strip():
            return []

        if file_path.suffix.lower() == ".jsonl":
            records: list[dict[str, Any]] = []
            for line in raw.splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
            return records

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return PaperTradingEngine._coerce_records(payload)

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
        snapshot: dict[str, Any], momentum_triggered: bool = False
    ) -> bool:
        if isinstance(snapshot.get("buy_signal"), bool):
            return bool(snapshot["buy_signal"])
        if isinstance(snapshot.get("signal"), str):
            if snapshot["signal"].lower() in {"buy", "long", "entry"}:
                return True
        if momentum_triggered:
            return True
        return bool(snapshot.get("should_buy"))

    @staticmethod
    def _sell_signal(snapshot: dict[str, Any]) -> bool:
        if isinstance(snapshot.get("sell_signal"), bool):
            return bool(snapshot["sell_signal"])
        if isinstance(snapshot.get("signal"), str):
            return snapshot["signal"].lower() in {"sell", "exit", "close"}
        return bool(snapshot.get("should_sell"))

    def run(self, snapshots: Sequence[dict[str, Any]]) -> dict[str, Any]:
        cash = self.initial_cash
        positions: dict[str, dict[str, Any]] = {}
        trades: list[dict[str, Any]] = []
        equity_history: list[dict[str, Any]] = []
        last_prices: dict[str, float] = {}

        for index, snapshot in enumerate(snapshots):
            mint = self._snapshot_mint(snapshot)
            name = self._snapshot_name(snapshot)
            price = max(0.0, self._snapshot_price(snapshot))
            if price <= 0.0:
                continue

            last_prices[mint] = price

            # Process order flow recording and momentum signal evaluation
            momentum_triggered = False
            if (
                "txType" in snapshot
                or "is_buy" in snapshot
                or "sol_amount" in snapshot
                or "solAmount" in snapshot
            ):
                is_buy = snapshot.get("txType") == "buy" or bool(
                    snapshot.get("is_buy", True)
                )
                sol_amount = float(
                    snapshot.get("sol_amount") or snapshot.get("solAmount") or 0.0
                )
                user = str(
                    snapshot.get("user")
                    or snapshot.get("traderPublicKey")
                    or "replay_trader"
                )
                ts_raw = self._snapshot_timestamp(snapshot)
                try:
                    ts = float(ts_raw)
                except (TypeError, ValueError):
                    ts = float(index)

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

            if mint in positions:
                position = positions[mint]
                performance = (price - position["entry_price"]) / position[
                    "entry_price"
                ]
                should_sell = (
                    self._sell_signal(snapshot)
                    or performance >= self.take_profit
                    or performance <= -abs(self.stop_loss)
                )
                if should_sell:
                    exit_value = position["quantity"] * price
                    pnl = exit_value - position["cost_basis"]
                    reason = "sell_signal"
                    if self._sell_signal(snapshot):
                        reason = "sell_signal"
                    elif performance >= self.take_profit:
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
                        "return_pct": performance,
                        "reason": reason,
                    }
                    trades.append(trade)
                    cash += exit_value
                    del positions[mint]

            if (
                mint not in positions
                and self._buy_signal(snapshot, momentum_triggered=momentum_triggered)
                and len(positions) < self.max_positions
            ):
                buy_amount = max(0.0, min(cash * self.buy_fraction, cash))
                if buy_amount > 0:
                    fee_ratio = 1.0 + (self.fee_bps + self.slippage_bps) / 10_000.0
                    gross_cost = buy_amount * fee_ratio
                    quantity = gross_cost / price if price > 0 else 0.0
                    if quantity > 0 and cash > 0:
                        positions[mint] = {
                            "mint": mint,
                            "name": name,
                            "quantity": quantity,
                            "entry_price": price,
                            "entry_timestamp": self._snapshot_timestamp(snapshot),
                            "cost_basis": gross_cost,
                        }
                        cash -= gross_cost
                        buy_reason = (
                            "momentum_spike"
                            if momentum_triggered
                            else "buy_signal"
                        )
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
            trade["return_pct"] for trade in trades if trade["action"] == "sell"
        ]
        gross_profit = sum(value for value in sell_returns if value > 0)
        gross_loss = abs(sum(value for value in sell_returns if value < 0))
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
            "positions": positions,
        }
        return summary


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
