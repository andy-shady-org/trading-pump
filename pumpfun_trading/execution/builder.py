"""Execution client construction helpers for the bot runtime."""

from __future__ import annotations

from typing import Any

from pumpfun_trading.sdk.execution import PumpFunExecutionClient


class ExecutionBuilder:
    """Create the on-chain execution client for live trading."""

    def __init__(self, private_key_b58: str, rpc_url: str, **kwargs: Any):
        self.private_key_b58 = private_key_b58
        self.rpc_url = rpc_url
        self.kwargs = kwargs

    def build(self) -> PumpFunExecutionClient:
        return PumpFunExecutionClient(
            self.private_key_b58,
            self.rpc_url,
            **self.kwargs,
        )


def build_execution_client(
    private_key_b58: str,
    rpc_url: str,
    **kwargs: Any,
) -> PumpFunExecutionClient:
    """Construct the runtime execution client used by the trading bot."""
    return PumpFunExecutionClient(private_key_b58, rpc_url, **kwargs)


__all__ = ["ExecutionBuilder", "build_execution_client"]
