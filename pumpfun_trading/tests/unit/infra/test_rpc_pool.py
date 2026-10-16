"""Unit tests for ``infra/rpc_pool.py`` telemetry redaction (BUG-102)."""

from __future__ import annotations

import json

import pytest

from pumpfun_trading.infra.rpc_pool import RpcConnectionPool, RpcEndpoint, RpcPoolConfig

KEY = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
HELIUS = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
BASIC_AUTH = "https://user:hunter2@rpc.example.com/"


def test_endpoint_to_dict_masks_api_key_but_keeps_raw_url_in_memory() -> None:
    endpoint = RpcEndpoint(url=HELIUS)

    data = endpoint.to_dict()

    assert data["url"] == "https://mainnet.helius-rpc.com/?api-key=***"
    assert data["label"] == "mainnet.helius-rpc.com"
    assert endpoint.url == HELIUS


@pytest.mark.parametrize(
    ("url", "label"),
    [
        (BASIC_AUTH, "rpc.example.com"),
        ("https://rpc.example.com?token=abc", "rpc.example.com"),
    ],
)
def test_endpoint_label_never_contains_credentials(url: str, label: str) -> None:
    assert RpcEndpoint(url=url).label == label


def test_pool_config_to_dict_masks_endpoints() -> None:
    config = RpcPoolConfig(endpoints=(HELIUS, RpcEndpoint(url=BASIC_AUTH)))

    assert config.to_dict()["endpoints"] == [
        "https://mainnet.helius-rpc.com/?api-key=***",
        "https://***@rpc.example.com/",
    ]


def test_pool_telemetry_contains_no_secret() -> None:
    pool = RpcConnectionPool(endpoints=(HELIUS, BASIC_AUTH))

    text = json.dumps(pool.get_telemetry())

    assert KEY not in text
    assert "hunter2" not in text
    assert pool.get_telemetry()["total_endpoints"] == 2
