# PumpFun Trading System: User Guide & Operations Portal

Welcome to the **PumpFun Trading System** knowledge and operations portal. This system is an institutional-grade, low-latency automated trading engine built for Solana microcap liquidity on Pump.fun bonding curves.

This manual serves as the central entry point and operational playbook for both **End-Users** (utilizing hosted Web UI instances) and **System Operators** (deploying console bots for live liquidity operations and project self-funding).

---

## 1. Documentation Knowledge Graph

All system documentation radiates from this guide in a structured star topology:

``` mermaid
graph TD
    UG["docs/USER-GUIDE.md<br/>(Central Knowledge & User Portal)"]
    CLI["docs/CLI-COMMANDS.md<br/>(Complete CLI Reference)"]
    ENV["docs/ENVIRONMENTAL-VARIABLES.md<br/>(Environment Variables Reference)"]
    STRAT["docs/STRATEGY.md<br/>(Wealth Generation & Math Strategy)"]
    RISK["docs/RISK.md<br/>(Capital Protection & Circuit Breakers)"]
    WUI["docs/WEB-UI.md<br/>(Web Dashboard & Hosted Instances)"]
    TUI["docs/TERMINAL-UI.md<br/>(Terminal UI & Operator Self-Funding)"]
    FEAT["docs/FEATURES.md<br/>(Complete Feature Catalog FEAT-01..30)"]
    REPLAY["docs/REPLAY-ENGINE.md<br/>(Backtesting & Strategy Playback)"]
    AUDIT["docs/AUDIT-TOOL.md<br/>(Forensic Audit & Trade Accounting)"]

    UG --> CLI
    UG --> ENV
    UG --> STRAT
    UG --> RISK
    UG --> WUI
    UG --> TUI
    UG --> FEAT
    UG --> REPLAY
    UG --> AUDIT
```

### Specialized Documentation Directory
* [**Complete CLI Reference Manual (`docs/CLI-COMMANDS.md`)**](CLI-COMMANDS.md): Exhaustive command-line documentation for all dedicated binaries (`pumpbot`, `pumpfun-recorder`, `pumpfun-replay`, `pumpfun-audit`, `pumpfun-events`, `pumpfun-optimize`, `pumpfun-arb`) and unified `pumpfun` subcommands, including parameter tables, options, and operational recipes.
* [**Environment Variables Reference Manual (`docs/ENVIRONMENTAL-VARIABLES.md`)**](ENVIRONMENTAL-VARIABLES.md): Exhaustive reference for all environment variables, fallback aliases, data types, requirement rules, retention policies, and production deployment templates.
* [**Terminal Operations & Self-Funding Guide (`docs/TERMINAL-UI.md`)**](TERMINAL-UI.md): Zero-dependency console monitor (`pumpbot`), sub-millisecond slot latency telemetry, complete visual dashboard field descriptions, alternate-screen buffer rendering, and multi-channel alerting (Discord, Slack, Telegram).
* [**Financial Strategy & Wealth Generation Blueprint (`docs/STRATEGY.md`)**](STRATEGY.md): Constant-product bonding curve mathematics, fractional Kelly bankroll management, dynamic trailing stop-loss mechanics, multi-tier take-profit scaling (2.0x / 3.5x / Moonbag), and anti-rug heuristic filters.
* [**Capital Protection & Risk Management (`docs/RISK.md`)**](RISK.md): Multi-tier risk hierarchy, maximum portfolio exposure caps, daily hard-stop circuit breakers (FEAT-09), private mempool Jito MEV protection, and startup on-chain position reconciliation.
* [**Web Dashboard & Hosted User Blueprint (`docs/WEB-UI.md`)**](WEB-UI.md): Modern FastAPI browser control center (FEAT-10), isolated user sandboxes, volatile in-memory key upload architecture (zero plaintext disk storage), hot configuration mutation, and live equity analytics.
* [**Standardized Feature Catalog (`docs/FEATURES.md`)**](FEATURES.md): Comprehensive reference catalog for completed architectural capabilities (FEAT-01 through FEAT-30).
* [**Replay Engine & Backtesting (`docs/REPLAY-ENGINE.md`)**](REPLAY-ENGINE.md): Historical market simulation tool (`pumpfun-replay`) for backtesting strategies and tuning parameter profiles against recorded bonding curve datasets.
* [**Forensic Audit Tool (`docs/AUDIT-TOOL.md`)**](AUDIT-TOOL.md): Trade accounting and telemetry inspector (`pumpfun-audit`) for analyzing execution performance, slippage, and state transitions.
* [**Developer & Internal Engineering Portal (`docs/dev/README.md`)**](dev/README.md): Internal sprint backlog, bug resolution tracking, architectural suggestions, release gate checklists, and operations runbook for contributors.

---

## 2. Wealth Generation Mission & Algorithmic Edge

In decentralized microcap markets, retail participants consistently lose capital due to three core deficiencies:
1. **Human Reaction Latency**: Manual evaluation and transaction signing take 5–20 seconds, during which early entrants and bonding curve slippage erode upside.
2. **Toxic MEV Exploitation**: Public mempool transactions are systematically frontrun and sandwiched by predatory searchers.
3. **Emotional Exit Failures**: Traders hold through parabolic spikes without locking in initial capital or fail to cut losses during developer dumps.

The `pumpfun-trading` engine delivers a systematic, mathematical edge:
* **Sub-Millisecond On-Chain Streaming (FEAT-01)**: Ingests raw account data directly via Yellowstone Geyser gRPC, evaluating bonding curve state updates in sub-millisecond timeframes.
* **Private Mempool Bundling (FEAT-02)**: Routes orders directly to Jito Block Engines, bypassing the public mempool to eliminate frontrunning and sandwich attacks.
* **Dynamic Trailing Stops & Multi-Tier Scale-Out (FEAT-03)**: Automatically locks in principal at `2.0x` (50% sale), takes profit at `3.5x` (25% sale), and trails residual runner moonbags to capture asymmetric upside while strictly capping downside drawdown.
* **Pre-Trade Anti-Rug Heuristics (FEAT-04)**: Evaluates developer launch history, initial supply allocations, holder concentration (Gini coefficient), and social metadata before risking capital.

---

## 3. Operational Modalities

The system accommodates two distinct operating paradigms:

### A. End-User Web Portal Mode (Hosted Instances — Future Architecture)
* **Target Audience**: End-users accessing dedicated bot instances hosted in cloud infrastructure via the modern FastAPI Web UI (FEAT-10).
* **Access Model**: Users do not have shell access, terminal interfaces, or permissions to view/modify host environment variables.
* **Credential Security**: Private keys are securely uploaded through the authenticated web interface and stored **strictly in volatile, ephemeral memory**. Keys are never written to plaintext files or persistent disk storage.
* **Operational Capabilities**: Complete browser-based lifecycle control (Start, Pause, Resume, Emergency Liquidate All), hot parameter tuning, live interactive equity charts, and embedded documentation viewing.

### B. Operator Terminal Mode (Current Development & Self-Funding Engine)
* **Target Audience**: Core developers and system operators running direct CLI instances (`pumpbot`).
* **Access Model**: Configured via local `.env` environment variables or CLI flags and executed directly in the terminal with Rich live dashboard rendering.
* **Mission**: Immediate live trading and alpha generation to validate trading algorithms, accumulate capital, and self-fund ongoing project development.
* **Lifecycle Plan**: Maintained and optimized during early development phases; planned for deprecation and retirement once the Web UI reaches production maturity.

---

## 4. System Prerequisites & Installation

### System Requirements
* **Operating System**: Linux (Ubuntu 22.04+ recommended), macOS (12.0+), or Windows (WSL2).
* **Python Runtime**: Python 3.11, 3.12, 3.13, or 3.14.
* **Hardware Requirements**: Minimum 2 CPU cores, 4 GB RAM, and a stable, low-latency network connection to Solana RPC and Geyser nodes.

### Installation Steps

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/andy-shady-org/pumpfun-trading.git
   cd pumpfun-trading/pumpfun-trading
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Package and Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -e .
   ```

4. **Verify Quality & Test Suite**:
   ```bash
   pip install nox
   nox -s lint
   nox -s tests
   ```

---

## 5. Environment Variables & Configuration Overview

Terminal operators configure the bot using a `.env` file in the project root or standard shell environment variables. Configuration is automatically loaded on startup via `python-dotenv`.

> 📖 **Full Reference Manual**: For an exhaustive, authoritative breakdown of all 50+ configuration parameters, fallback aliases, data types, automated retention rules, and copy-paste production templates, see [**`docs/ENVIRONMENTAL-VARIABLES.md`**](ENVIRONMENTAL-VARIABLES.md).

### Core Environment Variables Quick Reference

| Variable Name | Alias / Fallback | Required | Default | Description |
| :--- | :--- | :---: | :---: | :--- |
| `PUMPFUN_PRIVATE_KEY` | `SOLANA_PRIVATE_KEY` | **Yes** (Live) | `None` | Base58-encoded private key of the active trading wallet. |
| `PUMPFUN_RPC_URL` | `HELIUS_RPC_URL` | **Yes** | `https://api.mainnet-beta.solana.com` | Primary Solana JSON-RPC HTTP endpoint. |
| `PUMPFUN_RPC_URLS` | `SOLANA_RPC_URLS` | Optional | `None` | Comma-separated secondary/failover Solana RPC endpoints for dynamic load balancing. |
| `PUMPFUN_GEYSER_ENDPOINT` | — | **Required\*** | `None` | Yellowstone Geyser gRPC streaming endpoint for sub-millisecond market data ingestion. |
| `PUMPFUN_STREAM_URL` | `PUMPFUN_WS_URL` | **Required\*** | `wss://pumpportal.fun/api/data` | WebSocket streaming endpoint for event-driven market data ingestion. Keep it key-free. |
| `PUMPFUN_STREAM_API_KEY` | — | **Yes** (PumpPortal trading) | `None` | PumpPortal API key, sent only when connecting to `pumpportal.fun`; never shown on the dashboard (BUG-118). |
| `PUMPFUN_USE_JITO` | — | Optional | `true` | Enables private mempool bundle routing via Jito Block Engine to prevent sandwich attacks. |
| `PUMPFUN_BASE_BUY_SOL` | `PUMPFUN_BUY_AMOUNT_SOL` | Optional | `0.1` | Base buy allocation per trade in SOL. |
| `PUMPFUN_STRATEGY_PRESET` | `PUMPFUN_PRESET` | Optional | `balanced` | Preconfigured strategy profile: `conservative`, `balanced`, or `aggressive`. |
| `PUMPFUN_DRAWDOWN_MODE` | — | Optional | `adaptive_ratchet` | Portfolio drawdown reference mode (`adaptive_ratchet`, `baseline`, `trailing_hwm`). |
| `PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS` | — | Optional | `true` | Enables high-throughput asynchronous JSONL diagnostic event telemetry (FEAT-30). |
| `PUMPFUN_LOG_MAX_BYTES` | — | Optional | `10485760` (10 MB) | Maximum size before application log rotates with automated gzip compression (FEAT-22). |
| `PUMPFUN_ALERT_PROVIDER` | — | Optional | `none` | Notification provider: `none`, `discord`, `slack`, or `telegram`. |
| `PUMPFUN_HEADLESS` | — | Optional | `false` | Run in non-interactive headless mode without the interactive Rich TUI dashboard. |

*\*Note*: Live trading requires at least one stream source (`PUMPFUN_GEYSER_ENDPOINT` or `PUMPFUN_STREAM_URL`).

### Wallet Security & Capital Management Best Practices

1. **Hot Wallet Isolation**: Never use your primary storage wallet or vault as the trading keypair. Maintain an isolated hot wallet funded with only the active trading bankroll.
2. **Cold Storage Sweep Workflows**: Routinely extract accumulated profits from the hot wallet to an offline hardware wallet (e.g., Ledger).
3. **Minimum SOL Reserve Floor**: The system automatically enforces a `0.1 SOL` reserve buffer to guarantee funds remain available for gas fees and account rent.
4. **Non-Custodial Design**: The software never transmits private keys to third-party servers. In Web UI mode, keys reside exclusively in volatile instance memory.
5. **Masked Secret Telemetry**: All secret variables (`KEY`, `TOKEN`, `SECRET`, `WEBHOOK`) are automatically masked in diagnostic dumps and state logs.

---

## 6. Quickstart Operational Workflows

### Workflow 1: Live Wealth Generation via `pumpbot`
Execute live trading with real-time alternate-screen console monitoring:

```bash
# Launch with balanced preset and live Rich dashboard
pumpbot --preset balanced

# Launch from a config in headless mode (systemd / launchd templates in deploy/)
pumpbot --config configs/canary.json --headless

# Launch with custom buy size and aggressive strategy (slippage: PUMPFUN_SLIPPAGE_BPS)
pumpbot --preset aggressive --buy-amount-sol 0.25

# Pause new buys without stopping (open positions keep being managed); again to resume
kill -USR1 "$(jq .pid data/bot_status.json)"
```

### Workflow 2: Dry-Run Paper Trading
Validate market data ingestion, candidate screening, and simulated order fills with zero financial risk:

```bash
pumpbot --dry-run --preset balanced
```

### Workflow 3: Strategy Backtesting via `pumpfun-replay`
Replay recorded historical market datasets through the strategy engine to measure win rates, drawdown, and profit factors:

```bash
# Full interactive replay dashboard
pumpfun-replay --path runtime/replay_market_data.jsonl --mode dashboard

# Condensed financial performance summary
pumpfun-replay --path runtime/replay_market_data.jsonl --mode summary

# Granular trade execution ledger filtered by token name
pumpfun-replay --path runtime/replay_market_data.jsonl --mode trades --mint-name SolCat

# Replay with the bot's sizing, exits, costs and circuit breaker, from the paper wallet
pumpfun-replay --path runtime/replay_market_data.jsonl --config configs/canary.json --mode summary
```

With `--config` or `--preset` the replay behaves like the paper bot: same sizing, exits and modelled costs, and the same circuit breaker (daily loss limit, profit ratchet floor, cumulative cap), starting from the paper wallet. The summary shows how often the breaker tripped and how many buys it refused. Add `--no-circuit-breaker` to see the strategy without it ([`REPLAY-ENGINE.md`](REPLAY-ENGINE.md#live-fidelity-replay-sprint-24c-bug-61)).

### Workflow 4: Forensic Audit & Accounting via `pumpfun-audit`
Inspect historical execution records, state transitions, slippage, and on-chain reconciliation events:

```bash
# Inspect complete audit ledger
pumpfun-audit --path runtime/audit_trail.jsonl

# Generate structured operational summary
pumpfun-audit --path runtime/audit_trail.jsonl --summary

# Filter audit records by specific token or mint
pumpfun-audit --path runtime/audit_trail.jsonl --mint-name SolCat --limit 20

# Go / no-go on a paper run, with the rule fixed before the run (exit code 0 = GO)
pumpfun-audit verdict --path runtime/audit_trail.jsonl --rules configs/verdict_rules.json --strategy momentum
```

`verdict` only says GO when a paper run's profit survives a margin for live costs, holds in both halves and on most days, does not rest on a few lucky trades, and is statistically above zero. See [`AUDIT-TOOL.md`](AUDIT-TOOL.md#go--no-go-verdict-feat-67).

### Workflow 5: Market Stream Harvesting & Replay Dataset Generation (FEAT-21)
Capture live market quotes or generate deterministic synthetic price curves for strategy calibration without financial risk:

```bash
# Record live stream during bot operations (non-blocking async queue)
pumpbot --preset balanced --record-replay runtime/live_harvest.jsonl

# Standalone market stream harvester (zero capital required)
pumpfun record --output runtime/market_stream.jsonl --duration 300

# Generate deterministic synthetic scenario (e.g. multi-tier take-profit or stagnant curve)
pumpfun record --synthetic multi_tier_take_profit --output runtime/synth_tp.jsonl --synthetic-steps 100

# Export historical trades for a specific token via REST API
pumpfun record --from-mint <MINT_ADDRESS> --output runtime/token_history.jsonl --limit 200
```

---

## 7. Complete CLI Command & Flag Matrix

The system provides dedicated binary entry points as well as the unified `pumpfun-cli` interface. For comprehensive parameter documentation, recipe guides, and advanced examples, see [**Complete CLI Reference Manual (`docs/CLI-COMMANDS.md`)**](CLI-COMMANDS.md).

| Command | Subcommand / Option | Allowed Values | Description |
| :--- | :--- | :--- | :--- |
| `pumpbot` | `--preset` | `conservative`, `balanced`, `aggressive` | Selects predefined risk and strategy parameters. |
| | `--buy-amount-sol` | Float (e.g. `0.1`) | Overrides base buy allocation in SOL per trade. |
| | `--take-profit` | Float (e.g. `2.0`) | Overrides take-profit multiplier threshold. |
| | `--stop-loss` | Float (e.g. `0.85`) | Overrides stop-loss multiplier threshold. |
| | `--record-replay` | File path (`.jsonl`) | Asynchronously persists live market quotes and trade events into replay dataset (FEAT-21). |
| | `--dry-run` | Flag | Simulates order execution without submitting transactions. |
| | `--paper-trade` | Flag | Runs bot in paper trading mode. |
| | `--headless` | Flag | Runs without interactive terminal UI (structured logs). |
| | `--config` | File path (`.json`) | Loads a custom strategy and risk configuration file. |
| `pumpfun-replay` | `--path` | File path (`.json`, `.jsonl`) | Path to historical market data snapshot dataset. |
| | `--mode` | `dashboard`, `summary`, `trades` | Visual output mode for replay results. |
| | `--mint` | Base58 string | Filters replay evaluation to a specific mint address. |
| | `--mint-name` | String | Filters replay evaluation by token name. |
| `pumpfun-recorder` / `pumpfun record` | `--output`, `-o` | File path (`.jsonl`) | Destination file for recorded replay dataset (default: `market_replay.jsonl`). |
| | `--duration`, `-d` | Float (seconds) | Maximum recording duration before stopping. |
| | `--limit`, `-l` | Integer | Maximum snapshot record count before stopping. |
| | `--synthetic` | `pump_and_dump`, `stagnant_curve`, `multi_tier_take_profit`, `gradual_grind`, `flash_rug` | Generates parametric synthetic price curves for strategy validation. |
| | `--from-mint` | Base58 string | Exports historical trades for a specific token via REST API. |
| | `--geyser-endpoint` | URL | Yellowstone Geyser gRPC stream endpoint. |
| `pumpfun-audit` | `--path` | File path (`.jsonl`) | Path to audit trail log file. |
| | `--summary` | Flag | Displays aggregated financial and execution metrics. |
| | `--limit` | Integer (e.g. `50`) | Limits the number of audit records displayed. |
| | `--mint-name` | String | Filters audit trail by token name. |
| `pumpfun-cli` / `pumpfun` | `bot` / `replay` / `record` / `audit` / `latest-coins` / `market-info` | Subcommands | Unified CLI interface routing to all system modules. |

---

## 8. Navigating to Next Steps

To maximize your risk-adjusted returns and operational safety, review the specialized guides in sequence:
1. Review all command-line options and recipes in [**Complete CLI Reference Manual (`docs/CLI-COMMANDS.md`)**](CLI-COMMANDS.md).
2. Understand the core mathematical algorithms in [**Strategy & Wealth Generation Blueprint (`docs/STRATEGY.md`)**](STRATEGY.md).
3. Configure your capital safeguards in [**Risk Controls & Capital Protection (`docs/RISK.md`)**](RISK.md).
4. Master terminal monitoring and panel fields in [**Terminal UI & Observability (`docs/TERMINAL-UI.md`)**](TERMINAL-UI.md).
5. Review the hosted instance roadmap in [**Web Dashboard Architecture (`docs/WEB-UI.md`)**](WEB-UI.md).
6. Explore the full architectural capabilities in [**Standardized Feature Catalog (`docs/FEATURES.md`)**](FEATURES.md).
7. If contributing to or operating internal infrastructure, consult the [**Developer & Internal Engineering Portal (`docs/dev/README.md`)**](dev/README.md).
