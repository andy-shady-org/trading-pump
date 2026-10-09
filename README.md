# pumpfun_trading

A lightweight Python package for Pump.fun API access and on-chain execution helpers.

This package intentionally excludes the bot runtime and the `pumpfun-apis` repository. It focuses on a reusable client layer:

- `pumpfun_trading.api` for HTTP access to Pump.fun public APIs
- `pumpfun_trading.sdk` for execution-layer transaction building and broadcast helpers

## Installation

```bash
pip install -e .
```

## Example

```python
from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.sdk.execution import PumpFunExecutionClient

api = PumpFunApiClient()

execution = PumpFunExecutionClient(
    private_key_b58="...",
    rpc_url="https://mainnet.helius-rpc.com/?api-key=...",
)
```

