"""Unit tests for ``api/client.py`` token metadata fetching (BUG-95)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.api.client import (
    IPFS_GATEWAY,
    PumpFunApiClient,
    PumpFunApiHttpError,
    resolve_metadata_uri,
)

CID = "bafkreientcdd2rvizwb3ww42kx6uslbaqglpxph26cpwqoys552wtsj4ti"


async def test_fetch_token_metadata_rewrites_ipfs_scheme() -> None:
    client = PumpFunApiClient()
    request = AsyncMock(return_value={"twitter": "https://x.com/a"})

    with patch.object(client, "_request_once", request):
        result = await client.fetch_token_metadata("ipfs://QmHash")

    request.assert_awaited_once_with("GET", IPFS_GATEWAY + "QmHash")
    assert result == {"twitter": "https://x.com/a"}


async def test_fetch_token_metadata_non_dict_payload_returns_empty() -> None:
    client = PumpFunApiClient()

    with patch.object(client, "_request_once", AsyncMock(return_value="<html>")):
        assert await client.fetch_token_metadata("https://cdn.example/meta") == {}


async def test_fetch_token_metadata_bypasses_circuit_breaker() -> None:
    client = PumpFunApiClient(circuit_breaker_threshold=1)
    request = AsyncMock(side_effect=RuntimeError("HTTP 504"))

    with patch.object(client, "_request_once", request):
        with pytest.raises(RuntimeError):
            await client.fetch_token_metadata("https://cdn.example/meta")

    assert request.await_count == 1
    assert client._circuit_failures == 0


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (f"ipfs://{CID}", IPFS_GATEWAY + CID),
        (f"https://ipfs.io/ipfs/{CID}", IPFS_GATEWAY + CID),
        (f" https://dweb.link/ipfs/{CID} ", IPFS_GATEWAY + CID),
        ("https://arweave.net/abc", "https://arweave.net/abc"),
    ],
)
def test_resolve_metadata_uri_avoids_rate_limited_gateways(
    uri: str, expected: str
) -> None:
    assert resolve_metadata_uri(uri) == expected


@pytest.mark.parametrize(
    ("status", "calls", "circuit_failures"), [(404, 1, 0), (429, 3, 1), (503, 3, 1)]
)
async def test_request_retries_only_transient_http_errors(
    status: int, calls: int, circuit_failures: int
) -> None:
    client = PumpFunApiClient(max_retries=2, retry_backoff_seconds=0.0)
    request = AsyncMock(side_effect=PumpFunApiHttpError(f"HTTP {status}", status))

    with patch.object(client, "_request_once", request):
        with pytest.raises(PumpFunApiHttpError):
            await client.get("/coins/Mint111")

    assert request.await_count == calls
    assert client._circuit_failures == circuit_failures


@pytest.mark.parametrize("uri", ["", "ar://abc", "file:///etc/passwd"])
async def test_fetch_token_metadata_rejects_unsupported_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        await PumpFunApiClient().fetch_token_metadata(uri)
