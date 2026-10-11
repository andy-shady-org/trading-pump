# Pump Fun Trading

A lightweight Python package for [Pump.fun](https://pump.fun) public market data access and on-chain execution helpers.

<div align="center">
<a href="https://pypi.org/project/pumpfun-trading/"><img src="https://img.shields.io/pypi/v/pumpfun-trading" alt="PyPi"/></a>
<a href="https://codecov.io/gh/andy-shady-org/pumpfun-trading"><img src="https://codecov.io/gh/andy-shady-org/pumpfun-trading/branch/main/graph/badge.svg" alt="Coverage"/></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/stargazers"><img src="https://img.shields.io/github/stars/andy-shady-org/pumpfun-trading?style=flat" alt="Stars Badge"/></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/network/members"><img src="https://img.shields.io/github/forks/andy-shady-org/pumpfun-trading?style=flat" alt="Forks Badge"/></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/issues"><img src="https://img.shields.io/github/issues/andy-shady-org/pumpfun-trading" alt="Issues Badge"/></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/pulls"><img src="https://img.shields.io/github/issues-pr/andy-shady-org/pumpfun-trading" alt="Pull Requests Badge"/></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/graphs/contributors"><img alt="GitHub contributors" src="https://img.shields.io/github/contributors/andy-shady-org/pumpfun-trading?color=2b9348"></a>
<a href="https://github.com/andy-shady-org/pumpfun-trading/blob/master/LICENSE"><img src="https://img.shields.io/github/license/andy-shady-org/pumpfun-trading?color=2b9348" alt="License Badge"/></a>
<a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code Style Black"/></a>
<a href="https://pepy.tech/project/pumpfun-trading"><img alt="Downloads" src="https://static.pepy.tech/badge/pumpfun-trading"></a>
<a href="https://pepy.tech/project/pumpfun-trading"><img alt="Downloads/Week" src="https://static.pepy.tech/badge/pumpfun-trading/month"></a>
<a href="https://pepy.tech/project/pumpfun-trading"><img alt="Downloads/Month" src="https://static.pepy.tech/badge/pumpfun-trading/week"></a>
</div>

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

## Public API usage

This project only uses public [Pump.fun](https://pump.fun) endpoints for market data. No auth flow is required to inspect coins or fetch recent listings.

```bash
pumpbot --mode latest-coins --limit 20 --offset 0
pumpbot --mode market-info --mint <mint-address>
```

## Local configuration

The CLI and public API client do not require any auth token. To use the execution SDK, keep wallet secrets in environment variables or `.envrc` only.

```bash
cp .envrc.sample .envrc
# edit .envrc with your real values
```

The sample file contains the supported environment variables for bot and execution setup:

| Variable                            | Description                                                                                              | Required?                          |
|-------------------------------------|----------------------------------------------------------------------------------------------------------|------------------------------------|
| `PUMPFUN_PRIVATE_KEY`               | Base58 private key for the wallet used to sign transactions.                                             | Yes                                |
| `SOLANA_PRIVATE_KEY`                | Legacy alias accepted by the bot runtime if `PUMPFUN_PRIVATE_KEY` is not set.                            | Optional alias                     |
| `PUMPFUN_RPC_URL`                   | Solana RPC endpoint for execution and state queries.                                                     | Yes                                |
| `HELIUS_RPC_URL`                    | Legacy alias accepted by the bot runtime if `PUMPFUN_RPC_URL` is not set.                                | Optional alias                     |
| `PUMPFUN_AUDIT_LOG`                 | File path for the JSONL audit trail of lifecycle and trade events.                                       | Optional                           |
| `PUMPFUN_BOT_STATUS_PATH`           | File path for the JSON bot status snapshot used for monitoring and incident review.                      | Optional                           |
| `PUMPFUN_ALERT_PROVIDER`            | Alerting backend to use. Set to `none`, `discord`, `slack`, or `telegram`. Default is `none` (disabled). | Optional                           |
| `PUMPFUN_ALERT_DISCORD_WEBHOOK_URL` | Discord webhook URL used when `PUMPFUN_ALERT_PROVIDER=discord`.                                          | Required if provider is `discord`  |
| `PUMPFUN_ALERT_SLACK_WEBHOOK_URL`   | Slack incoming webhook URL used when `PUMPFUN_ALERT_PROVIDER=slack`.                                     | Required if provider is `slack`    |
| `PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN`  | Telegram bot token used when `PUMPFUN_ALERT_PROVIDER=telegram`.                                          | Required if provider is `telegram` |
| `PUMPFUN_ALERT_TELEGRAM_CHAT_ID`    | Telegram chat ID to send alerts to when `PUMPFUN_ALERT_PROVIDER=telegram`.                               | Required if provider is `telegram` |

Example:

```bash
export PUMPFUN_PRIVATE_KEY="<base58-wallet-private-key>"
export PUMPFUN_RPC_URL="https://mainnet.helius-rpc.com/?api-key=<api-key>"
export PUMPFUN_AUDIT_LOG="${PWD}/.data/pumpfun_trading_audit.jsonl"
export PUMPFUN_BOT_STATUS_PATH="${PWD}/.data/bot_status.json"
```

## Discovering a mint address

Use the public frontend API to list recent coins and copy the `mint` field from the response:

```bash
pumpbot --mode latest-coins --limit 20 --offset 0
```

You can then inspect that mint without logging in:

```bash
pumpbot --mode market-info --mint <mint-address>
```

## Execution SDK

```python
from pumpfun_trading.sdk.execution import PumpFunExecutionClient

execution = PumpFunExecutionClient(
    private_key_b58="...",
    rpc_url="https://mainnet.helius-rpc.com/?api-key=...",
)
```

## Bot runtime and strategy presets

The package includes a live launch-monitoring bot that can watch for newly created tokens, buy based on a configurable strategy, and exit on take-profit or stop-loss thresholds. The bot also enforces portfolio-level risk limits and account reserve guards as part of the Phase 0 safety hardening.

```bash
# balanced preset (default)
pumpbot --mode bot --preset balanced

# conservative preset
pumpbot --mode bot --preset conservative

# aggressive preset
pumpbot --mode bot --preset aggressive

# dry run / no real transactions
pumpbot --mode bot --preset balanced --dry-run
```

You can also load a JSON config file instead of hardcoding values:

```bash
cp bot-config.example.json bot-config.json
# edit bot-config.json with your target settings
pumpbot --mode bot --config ./bot-config.json
```

Example bot config:

```json
{
  "strategy_preset": "balanced",
  "buy_amount_sol": 0.01,
  "take_profit": 1.5,
  "stop_loss": 0.85,
  "max_active_positions": 1,
  "max_positions_per_mint": 1,
  "min_market_cap_sol": 5.0,
  "max_buy_attempts_per_mint": 3,
  "min_balance_sol": 0.05,
  "min_sell_balance": 1,
  "recent_token_ttl_seconds": 600,
  "reconnect_delay_seconds": 2.0,
  "dry_run": true,
  "paper_trade": false,
  "verbose": true,
  "stream_url": "wss://pumpportal.fun/api/data",
  "api_base_url": "https://frontend-api-v3.pump.fun",
  "max_total_exposure_sol": 0.25,
  "max_position_size_sol": 0.05,
  "max_token_concentration_pct": 0.35,
  "max_loss_per_trade_sol": 0.02,
  "max_daily_drawdown_pct": 0.2,
  "reserve_balance_sol": 0.1,
  "health_check_timeout_seconds": 60
}
```

The JSON file is intentionally a sample: keep your real runtime values in a local untracked copy and do not commit secrets or live config to version control. The risk-limit values above are the current portfolio safety defaults used for the balanced preset.

## Audit trail investigation tool

The bot writes a JSONL audit trail for trades, lifecycle transitions, status changes, and operational events. You can inspect it with the built-in CLI tool:

```bash
pumpbot audit --path .data/pumpfun_trading_audit.jsonl
```

Common filters:

```bash
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --record-type trade
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --state holding
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --mint <mint-address>
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --reason take_profit
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --summary
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --json
pumpbot audit --path .data/pumpfun_trading_audit.jsonl --export ./audit-export.json
```

See [AUDIT-TOOL.md](./docs/AUDIT-TOOL.md) for the full audit investigation workflow and examples.

## Replay engine and historical strategy validation

The project now includes a dedicated replay engine for evaluating trading decisions against historical market snapshots without touching the live bot dashboard. This is implemented as a separate UI path so the live bot runtime remains unchanged while replay analysis runs in its own Rich panel flow.

```bash
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode dashboard
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode summary
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode trades
```

The replay mode loads JSON or JSONL snapshot data, runs a lightweight paper-trading engine with fee/slippage assumptions, and prints metrics such as:

- profit factor
- max drawdown
- win rate
- average trade return
- final equity and total trade count

See [REPLAY-ENGINE.md](./docs/REPLAY-ENGINE.md) for the full replay workflow, dataset format, and UI separation details.
