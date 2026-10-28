"""Execution client construction helpers for the bot runtime."""

from __future__ import annotations

from typing import Any, Optional

from trading_pump.infra.rpc_pool import RpcConnectionPool
from trading_pump.sdk.execution import PumpFunExecutionClient


class ExecutionBuilder:
    """Create the on-chain execution client for live trading."""

    def __init__(
        self,
        private_key_b58: str,
        rpc_url: Optional[str] = None,
        *,
        rpc_pool: Optional[RpcConnectionPool] = None,
        rpc_urls: Optional[list[str] | tuple[str, ...]] = None,
        **kwargs: Any,
    ):
        self.private_key_b58 = private_key_b58
        self.rpc_url = rpc_url
        self.rpc_pool = rpc_pool
        self.rpc_urls = rpc_urls
        self.kwargs = kwargs

    def build(self) -> PumpFunExecutionClient:
        return PumpFunExecutionClient(
            self.private_key_b58,
            rpc_url=self.rpc_url,
            rpc_pool=self.rpc_pool,
            rpc_urls=self.rpc_urls,
            **self.kwargs,
        )


def build_execution_client(
    private_key_b58: str,
    rpc_url: Optional[str] = None,
    *,
    rpc_pool: Optional[RpcConnectionPool] = None,
    rpc_urls: Optional[list[str] | tuple[str, ...]] = None,
    **kwargs: Any,
) -> PumpFunExecutionClient:
    """Construct the runtime execution client used by the trading bot."""
    return PumpFunExecutionClient(
        private_key_b58,
        rpc_url=rpc_url,
        rpc_pool=rpc_pool,
        rpc_urls=rpc_urls,
        **kwargs,
    )


__all__ = ["ExecutionBuilder", "build_execution_client"]
