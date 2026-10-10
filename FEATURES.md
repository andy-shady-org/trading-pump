# Features

This document is a snapshot of the features currently implemented in this repository as of the current codebase state. It includes both the public API client surface and the live trading bot/runtime features.

## Public Pump.fun API access

- HTTP client for Pump.fun frontend and analytics endpoints
- Fetch latest coin listings with limit/offset paging
- Fetch market info for a specific mint
- Fallback mint lookup when a direct coin endpoint returns 404/401/403
- Support for advanced API endpoints and alternate endpoint sources
- Search, featured, and personalized-style coin queries via API helper methods
- Fetch trade history and trade count for a mint
- Fetch candlestick data by mint and interval
- Fetch SOL price and market overview helpers

## Execution / on-chain SDK

- Solana wallet key handling from base58 private keys
- Validation helpers for public keys and mint addresses
- Derivation of Pump.fun bonding curve PDAs and associated token addresses
- Build buy and sell instructions for Pump.fun program interactions
- Wallet balance queries via Solana RPC
- ATA existence checks
- Transaction signing and broadcast helpers
- Optional priority fee and default slippage configuration
- Built-in validation for wallet addresses, minter addresses, and instruction payloads

## CLI tooling

- `market-info` mode for inspecting a mint
- `latest-coins` mode for listing recent coins
- `bot` mode for running the live trading bot
- Rich console rendering for API outputs and market summaries
- JSON raw output mode
- Bot config file loading from JSON
- Strategy preset selection through command-line flags
- Dry-run and paper-trade options

## Trading bot runtime

- Live Pump.fun token stream monitoring over websocket
- New token detection and candidate evaluation
- Buy decision pipeline based on token market cap and strategy rules
- Sell decision pipeline based on take-profit and stop-loss thresholds
- Explicit bot lifecycle state machine:
  - idle
  - monitoring
  - buying
  - holding
  - selling
  - shutdown
- Reconnection handling for websocket failures
- Graceful shutdown hooks and signal handling
- Bot status snapshots written to JSON
- Audit trail recording to JSONL
- Trade ledger tracking for buy/sell records, reasons, timestamps, and position IDs
- Recent action memory for debugging and runtime introspection

## Risk controls and safety guards

- Per-wallet minimum balance checks before opening positions
- Portfolio-level max total exposure cap
- Max active positions limit
- Per-token concentration cap
- Maximum drawdown guard
- Maximum loss-per-trade guard
- Buy attempt throttle per mint
- Recent mint cooldown / spam prevention
- Reserve balance / equity guard before trade execution
- Health timeout enforcement for stale websocket/API state
- Risk kill-switch behavior when safety conditions fail
- Dry-run operation mode for safe testing
- Paper-trade mode flag

## Strategy system

- Preset strategy configs:
  - conservative
  - balanced
  - aggressive
- Config dataclass for trading bot settings
- JSON config file parsing and override support
- Strategy summary snapshots for bot monitoring
- Buy eligibility checks via `TradingStrategy.should_buy()`
- Sell eligibility checks via `TradingStrategy.should_sell()`

## Monitoring and observability

- In-memory metrics tracking for:
  - buys
  - sells
  - failures
  - retries
  - connection loss
  - stale data
  - latency
- Latency sampling and summary statistics
- Runtime dashboard rendering with Rich tables and panels
- Bot health status and recent event tracking
- Active position reporting in the dashboard
- Recent trade ledger display in the UI

## Alerting

- Alert provider selection via environment variables
- Supported providers:
  - Discord
  - Slack
  - Telegram
  - none
- Webhook-based delivery for Discord and Slack
- Telegram chat-based delivery using bot token and chat ID
- Alerting tied to bot lifecycle events and operational state transitions
- Safe failure handling so alert errors do not crash the bot

## Audit and forensic tooling

- JSONL audit log output for state transitions and trades
- Structured event-and-trade write path for runtime investigation
- Status snapshot export for debugging and restart analysis
- Trade ledger with mint, entry, exit, reason, position IDs, and timestamps
- Bot history retained in memory for recent action review

## Environment/configuration support

- `.envrc`-style environment variable configuration
- Private key and RPC URL environment configuration
- Optional audit log path configuration
- Optional bot status snapshot path configuration
- Optional alert provider configuration
- Configurable stream URL and API base URL

## Testing

- Unit tests covering:
  - strategy safety logic
  - risk-related validation behavior
  - audit log trade record behavior
  - metrics collection behavior
  - bot configuration and strategy summary checks

## Notes

This repository is not only a raw API wrapper; it includes a live bot runtime, execution helpers, strategy presets, risk guardrails, monitoring, and operational event logging. The codebase is structured as a foundation for a launch-monitoring and execution-focused Pump.fun trading system, with several roadmap items still pending beyond the implemented core features.

