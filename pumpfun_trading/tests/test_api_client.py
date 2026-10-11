import pytest

from pumpfun_trading.api.client import PumpFunApiClient


class _FakeResponse:
    def __init__(self, status: int, payload: str):
        self.status = status
        self._payload = payload

    async def text(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _RetrySession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            return _FakeResponse(500, '{"error": "temporary"}')
        return _FakeResponse(200, '{"ok": true}')


class _FailingSession:
    def __init__(self):
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return _FakeResponse(500, '{"error": "down"}')


@pytest.mark.asyncio
async def test_build_url_and_headers():
    client = PumpFunApiClient(base_url="https://frontend-api-v3.pump.fun")
    assert client._build_url("/coins/latest").startswith(
        "https://frontend-api-v3.pump.fun"
    )
    assert client.headers["Accept"] == "application/json"
    await client.close()


@pytest.mark.asyncio
async def test_market_overview_wrapper():
    client = PumpFunApiClient()
    assert callable(client.get_market_overview)
    await client.close()


@pytest.mark.asyncio
async def test_request_retries_and_recovers():
    session = _RetrySession()
    client = PumpFunApiClient(
        session=session,
        max_retries=3,
        retry_backoff_seconds=0.01,
    )

    result = await client.request("GET", "/health")

    assert result == {"ok": True}
    assert session.calls == 3
    await client.close()


@pytest.mark.asyncio
async def test_request_opens_circuit_after_failures():
    session = _FailingSession()
    client = PumpFunApiClient(
        session=session,
        max_retries=0,
        circuit_breaker_threshold=1,
        circuit_cooldown_seconds=30.0,
    )

    with pytest.raises(RuntimeError, match="HTTP 500"):
        await client.request("GET", "/health")

    with pytest.raises(RuntimeError, match="circuit open"):
        await client.request("GET", "/health")

    assert session.calls == 1
    await client.close()
