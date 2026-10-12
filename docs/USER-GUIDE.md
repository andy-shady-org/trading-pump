# PumpFun Trading System: User Guide & Operations Portal

Welcome to the **PumpFun Trading System** knowledge and operations portal. This system is an institutional-grade, low-latency automated trading engine built for Solana microcap liquidity on Pump.fun bonding curves.

This manual serves as the central entry point and operational playbook for both **End-Users** (utilizing hosted Web UI instances) and **System Operators** (deploying console bots for live liquidity operations and project self-funding).

---

## 1. Documentation Knowledge Graph

All system documentation radiates from this guide in a structured star topology:

``` mermaid
graph TD
    UG["docs/USER-GUIDE.md<br/>(Central Knowledge & User Portal)"]
    STRAT["docs/STRATEGY.md<br/>(Wealth Generation & Math Strategy)"]
    RISK["docs/RISK.md<br/>(Capital Protection & Circuit Breakers)"]
    WUI["docs/WEB-UI.md<br/>(Web Dashboard & Hosted Instances)"]
    TUI["docs/TERMINAL-UI.md<br/>(Terminal UI & Operator Self-Funding)"]
    FEAT["docs/FEATURES.md<br/>(Complete Feature Catalog FEAT-01..20)"]
    REPLAY["docs/REPLAY-ENGINE.md<br/>(Backtesting & Strategy Playback)"]
    AUDIT["docs/AUDIT-TOOL.md<br/>(Forensic Audit & Trade Accounting)"]

    UG --> STRAT
    UG --> RISK
    UG --> WUI
    UG --> TUI
    UG --> FEAT
    UG --> REPLAY
    UG --> AUDIT
```

### Specialized Documentation Directory
* [**Financial Strategy & Wealth Generation Blueprint (`docs/STRATEGY.md`)**](STRATEGY.md): Constant-product bonding curve mathematics, fractional Kelly bankroll management, dynamic trailing stop-loss mechanics, multi-tier take-profit scaling (2.0x / 3.5x / Moonbag), and anti-rug heuristic filters.
* [**Capital Protection & Risk Management (`docs/RISK.md`)**](RISK.md): Multi-tier risk hierarchy, maximum portfolio exposure caps, daily hard-stop circuit breakers (FEAT-09), private mempool Jito MEV protection, and startup on-chain position reconciliation.
* [**Web Dashboard & Hosted User Blueprint (`docs/WEB-UI.md`)**](WEB-UI.md): Modern FastAPI browser control center (FEAT-10), isolated user sandboxes, volatile in-memory key upload architecture (zero plaintext disk storage), hot configuration mutation, and live equity analytics.
* [**Terminal Operations & Self-Funding Guide (`docs/TERMINAL-UI.md`)**](TERMINAL-UI.md): Zero-dependency console monitor (`pumpbot`), sub-millisecond slot latency telemetry, alternate-screen buffer rendering, and multi-channel alerting (Discord, Slack, Telegram).
* [**Standardized Feature Catalog (`docs/FEATURES.md`)**](FEATURES.md): Comprehensive reference catalog for all architectural capabilities (FEAT-01 through FEAT-20).
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

## 5. Environment Variables & Key Configuration (Terminal Operators)

Terminal operators configure the bot using a `.env` file in the project root or through standard shell environment variables.

### Environment Variable Matrix

| Variable Name | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `PUMPFUN_PRIVATE_KEY` | **Yes** (Live) | `None` | Base58-encoded private key of the trading wallet. |
| `PUMPFUN_RPC_URL` | **Yes** | `https://api.mainnet-beta.solana.com` | High-performance Solana JSON-RPC HTTP endpoint. |
| `PUMPFUN_GEYSER_ENDPOINT` | Optional | `None` | Yellowstone Geyser gRPC endpoint for sub-millisecond streaming. |
| `PUMPFUN_GEYSER_TOKEN` | Optional | `None` | Authentication / X-Token header for Yellowstone Geyser gRPC. |
| `PUMPFUN_USE_JITO` | Optional | `true` | Enables private mempool bundle submission via Jito Block Engine. |
| `PUMPFUN_JITO_BLOCK_ENGINE_URL` | Optional | `https://mainnet.block-engine.jito.wtf` | Jito Block Engine URL for MEV protection. |
| `PUMPFUN_JITO_TIP_LAMPORTS` | Optional | `100000` | Base validator tip in Lamports (0.0001 SOL minimum recommended). |
| `PUMPFUN_JITO_CONFIRMATION_TIMEOUT` | Optional | `15.0` | Timeout in seconds before falling back to direct RPC submission. |
| `PUMPFUN_JITO_FALLBACK_TO_RPC` | Optional | `true` | Automatically fallback to high-priority RPC if Jito bundle times out. |
| `PUMPFUN_BASE_BUY_SOL` | Optional | `0.1` | Default trade buy allocation in SOL. |
| `PUMPFUN_SLIPPAGE_BPS` | Optional | `250` | Maximum slippage tolerance in basis points (`250` = 2.5%). |
| `PUMPFUN_STRATEGY_PRESET` | Optional | `balanced` | Strategy profile: `conservative`, `balanced`, or `aggressive`. |
| `PUMPFUN_DRY_RUN` | Optional | `false` | Paper trading mode: simulates executions without broadcasting transactions. |
| `PUMPFUN_ALERT_PROVIDER` | Optional | `None` | Alert channel: `discord`, `slack`, or `telegram`. |
| `PUMPFUN_ALERT_WEBHOOK_URL` | Optional | `None` | Webhook URL for Discord or Slack trade event notifications. |
| `PUMPFUN_TELEGRAM_BOT_TOKEN` | Optional | `None` | Telegram Bot API token for mobile push alerts. |
| `PUMPFUN_TELEGRAM_CHAT_ID` | Optional | `None` | Authorized Telegram Chat ID for alerts and command access. |

### Wallet Security & Capital Management Best Practices

1. **Hot Wallet Isolation**: Never use your primary storage wallet or vault as the trading keypair. Maintain an isolated hot wallet funded with only the active trading bankroll.
2. **Cold Storage Sweep Workflows**: Routinely extract accumulated profits from the hot wallet to an offline hardware wallet (e.g., Ledger).
3. **Minimum SOL Reserve Floor**: The system automatically enforces a `0.1 SOL` reserve buffer to guarantee funds remain available for gas fees and account rent.
4. **Non-Custodial Design**: The software never transmits private keys to third-party servers. In Web UI mode, keys reside exclusively in volatile instance memory.

---

## 6. Quickstart Operational Workflows

### Workflow 1: Live Wealth Generation via `pumpbot`
Execute live trading with real-time alternate-screen console monitoring:

```bash
# Launch with balanced preset and live Rich dashboard
pumpbot --preset balanced

# Launch with conservative preset in headless mode (suitable for background systemd services)
pumpbot --preset conservative --headless --log-level INFO

# Launch with custom buy size and aggressive strategy
pumpbot --preset aggressive --buy-sol 0.25 --slippage-bps 350
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
```

### Workflow 4: Forensic Audit & Accounting via `pumpfun-audit`
Inspect historical execution records, state transitions, slippage, and on-chain reconciliation events:

```bash
# Inspect complete audit ledger
pumpfun-audit --path runtime/audit_trail.jsonl

# Generate structured operational summary
pumpfun-audit --path runtime/audit_trail.jsonl --summary

# Filter audit records by specific token or mint
pumpfun-audit --path runtime/audit_trail.jsonl --mint-name SolCat --limit 20
```

---

## 7. Complete CLI Command & Flag Matrix

The system provides dedicated binary entry points as well as the unified `pumpfun-cli` interface:

| Command | Subcommand / Option | Allowed Values | Description |
| :--- | :--- | :--- | :--- |
| `pumpbot` | `--preset` | `conservative`, `balanced`, `aggressive` | Selects predefined risk and strategy parameters. |
| | `--buy-sol` | Float (e.g. `0.1`) | Overrides base buy allocation in SOL per trade. |
| | `--slippage-bps` | Integer (e.g. `250`) | Maximum slippage tolerance in basis points. |
| | `--headless` | Flag | Disables Rich alternate-screen UI for headless daemon logging. |
| | `--dry-run` | Flag | Simulates order execution without submitting transactions. |
| | `--config` | File path (`.json`) | Loads a custom strategy and risk configuration file. |
| | `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Sets terminal and file logging verbosity. |
| `pumpfun-replay` | `--path` | File path (`.json`, `.jsonl`) | Path to historical market data snapshot dataset. |
| | `--mode` | `dashboard`, `summary`, `trades` | Visual output mode for replay results. |
| | `--mint` | Base58 string | Filters replay evaluation to a specific mint address. |
| | `--mint-name` | String | Filters replay evaluation by token name. |
| `pumpfun-audit` | `--path` | File path (`.jsonl`) | Path to audit trail log file. |
| | `--summary` | Flag | Displays aggregated financial and execution metrics. |
| | `--limit` | Integer (e.g. `50`) | Limits the number of audit records displayed. |
| | `--mint-name` | String | Filters audit trail by token name. |
| `pumpfun-cli` | `run` / `replay` / `audit` / `api` | Subcommands | Unified CLI interface routing to all system modules. |

---

## 8. Navigating to Next Steps

To maximize your risk-adjusted returns and operational safety, review the specialized guides in sequence:
1. Understand the core mathematical algorithms in [**Strategy & Wealth Generation Blueprint (`docs/STRATEGY.md`)**](STRATEGY.md).
2. Configure your capital safeguards in [**Risk Controls & Capital Protection (`docs/RISK.md`)**](RISK.md).
3. Master terminal monitoring in [**Terminal UI & Observability (`docs/TERMINAL-UI.md`)**](TERMINAL-UI.md).
4. Review the hosted instance roadmap in [**Web Dashboard Architecture (`docs/WEB-UI.md`)**](WEB-UI.md).
5. Explore the full architectural capabilities in [**Standardized Feature Catalog (`docs/FEATURES.md`)**](FEATURES.md).
6. If contributing to or operating internal infrastructure, consult the [**Developer & Internal Engineering Portal (`docs/dev/README.md`)**](dev/README.md).
