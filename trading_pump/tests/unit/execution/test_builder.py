"""Unit tests for ``execution/builder.py``."""

from __future__ import annotations

from trading_pump.execution.builder import ExecutionBuilder, build_execution_client


def test_execution_builder():
    pk = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
    rpc = "https://api.mainnet-beta.solana.com"

    builder = ExecutionBuilder(pk, rpc, default_slippage_bps=200)
    client1 = builder.build()
    assert client1.rpc_url == rpc

    client2 = build_execution_client(pk, rpc)
    assert client2.rpc_url == rpc
