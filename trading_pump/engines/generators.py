from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from trading_pump.api.client import PumpFunApiClient

logger = logging.getLogger(__name__)


class SyntheticReplayGenerator:
    """
    Deterministic and parametric synthetic price curve generator for backtesting
    and risk rule stress testing on Pump.fun bonding curves.
    """

    SUPPORTED_SCENARIOS = (
        "pump_and_dump",
        "stagnant_curve",
        "multi_tier_take_profit",
        "gradual_grind",
        "flash_rug",
    )

    @classmethod
    def generate(
        cls,
        scenario: str = "pump_and_dump",
        mint: str | None = None,
        steps: int = 60,
        base_price: float = 0.000000028,
        start_timestamp: float | None = None,
        seed: int = 42,
    ) -> list[dict[str, Any]]:
        """
        Generate a list of replay snapshots representing a specific market trajectory.
        """
        if scenario not in cls.SUPPORTED_SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario}'. Supported: {', '.join(cls.SUPPORTED_SCENARIOS)}"
            )

        rng = random.Random(seed)
        ts = start_timestamp if start_timestamp is not None else time.time()
        token_mint = (
            mint or f"Synth{scenario[:6].capitalize()}1111111111111111111111111111"
        )
        token_name = f"Synth-{scenario.replace('_', ' ').title()}"

        records: list[dict[str, Any]] = []
        base_mc = base_price * 1_000_000_000.0  # ~28.0 SOL for 2.8e-8 unit price

        for i in range(max(5, steps)):
            current_ts = ts + (i * 2.0)
            progress = i / float(steps - 1)

            if scenario == "pump_and_dump":
                if progress < 0.4:
                    multiplier = 1.0 + (progress / 0.4) * 3.5  # 1.0x -> 4.5x
                elif progress < 0.6:
                    multiplier = 4.5 - ((progress - 0.4) / 0.2) * 1.5  # 4.5x -> 3.0x
                else:
                    multiplier = 3.0 - ((progress - 0.6) / 0.4) * 2.8  # 3.0x -> 0.2x
                multiplier += rng.uniform(-0.05, 0.05)
                multiplier = max(0.05, multiplier)

            elif scenario == "stagnant_curve":
                # Stays locked at ~27.96 SOL launch MC with negligible micro-drift
                multiplier = 1.0 + rng.uniform(-0.002, 0.002)

            elif scenario == "multi_tier_take_profit":
                # Escalates through 2.0x (Tier 1), 3.5x (Tier 2), and holds moonbag floor
                if progress < 0.3:
                    multiplier = 1.0 + (progress / 0.3) * 1.2  # 1.0x -> 2.2x
                elif progress < 0.6:
                    multiplier = 2.2 + ((progress - 0.3) / 0.3) * 1.6  # 2.2x -> 3.8x
                else:
                    multiplier = 3.8 - ((progress - 0.6) / 0.4) * 1.2  # 3.8x -> 2.6x
                multiplier += rng.uniform(-0.03, 0.03)

            elif scenario == "gradual_grind":
                # Organic upward grind
                multiplier = 1.0 + (progress * 1.8) + rng.uniform(-0.05, 0.05)
                multiplier = max(0.8, multiplier)

            elif scenario == "flash_rug":
                # Rapid rug pull drop
                if progress < 0.25:
                    multiplier = 1.0 + (progress / 0.25) * 0.3  # 1.0x -> 1.3x
                else:
                    multiplier = (
                        1.3 - ((progress - 0.25) / 0.75) * 1.25
                    )  # 1.3x -> 0.05x
                multiplier += rng.uniform(-0.02, 0.02)
                multiplier = max(0.02, multiplier)

            price = max(1e-11, base_price * multiplier)
            mc = max(0.1, base_mc * multiplier)
            is_buy = multiplier >= (
                records[-1]["price"] / base_price if records else 1.0
            )
            signal = "buy" if i == 0 else ("buy" if is_buy else "sell")

            record = {
                "timestamp": round(current_ts, 3),
                "mint": token_mint,
                "name": token_name,
                "price": price,
                "market_cap_sol": round(mc, 4),
                "is_buy": is_buy,
                "sol_amount": round(rng.uniform(0.05, 0.5), 4),
                "token_amount": round(rng.uniform(10_000, 500_000), 2),
                "volume": round(mc * 0.1, 4),
                "signal": signal,
                "buy_signal": (i == 0 or (is_buy and rng.random() > 0.6)),
            }
            records.append(record)

        return records

    @classmethod
    def generate_to_file(
        cls,
        path: str | Path,
        scenario: str = "pump_and_dump",
        mint: str | None = None,
        steps: int = 60,
    ) -> int:
        """Generate synthetic scenario records and write to a JSONL file."""
        records = cls.generate(scenario=scenario, mint=mint, steps=steps)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return len(records)


class RestHistoryExporter:
    """
    Historical REST API exporter fetching chronological trades and coin info
    via PumpFunApiClient and converting them into standard replay datasets.
    """

    @staticmethod
    async def export_token_trades(
        client: PumpFunApiClient, mint: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Fetch trades and metadata for a specific token and format into replay snapshots."""
        trades = await client.get_trade_history(mint, limit=limit)
        coin_info = await client.get_coin(mint)
        token_name = "PumpToken"
        if isinstance(coin_info, dict):
            token_name = coin_info.get("name") or coin_info.get("symbol") or token_name

        snapshots: list[dict[str, Any]] = []
        if isinstance(trades, list):
            for t in trades:
                if not isinstance(t, dict):
                    continue
                ts = float(t.get("timestamp") or t.get("time") or time.time())
                price = float(t.get("price", 0.0) or 0.0)
                sol_amount = float(
                    t.get("sol_amount", 0.0)
                    or (float(t.get("sol_amount_lamports", 0)) / 1_000_000_000.0)
                    or 0.0
                )
                is_buy = bool(
                    t.get("is_buy")
                    if t.get("is_buy") is not None
                    else t.get("tx_type") == "buy"
                )
                mc = float(
                    t.get("market_cap", 0.0)
                    or t.get("market_cap_sol", 0.0)
                    or (price * 1_000_000_000.0)
                )

                snapshots.append(
                    {
                        "timestamp": ts,
                        "mint": mint,
                        "name": token_name,
                        "price": price,
                        "market_cap_sol": mc,
                        "is_buy": is_buy,
                        "sol_amount": sol_amount,
                        "token_amount": float(
                            t.get("token_amount", 0.0)
                            or t.get("tokenAmount", 0.0)
                            or 0.0
                        ),
                        "user": str(t.get("user") or t.get("traderPublicKey") or ""),
                        "signal": "buy" if is_buy else "sell",
                        "buy_signal": is_buy,
                    }
                )

        # Sort chronologically by timestamp
        snapshots.sort(key=lambda s: float(s["timestamp"]))
        return snapshots

    @classmethod
    async def export_token_trades_to_file(
        cls,
        client: PumpFunApiClient,
        mint: str,
        output_path: str | Path,
        limit: int = 200,
    ) -> int:
        """Fetch trades for a mint and write them to a JSONL replay file."""
        records = await cls.export_token_trades(client=client, mint=mint, limit=limit)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return len(records)


__all__ = ["SyntheticReplayGenerator", "RestHistoryExporter"]
