# Terminal UI & Operator Observability Guide

The Terminal User Interface (`pumpbot`) is an institutional-grade, low-overhead console command center powered by Rich. It is engineered specifically for system operators, algorithmic traders, and liquidity engineers who require zero-overhead local execution, sub-millisecond telemetry monitoring, and immediate cashflow generation to self-fund ongoing project development.

> **Operational Note & Lifecycle Strategy**: The Terminal UI serves as the primary self-funding and testing interface during early development sprints. As the full-featured FastAPI Web Dashboard (FEAT-10) reaches production maturity, the Terminal UI will be maintained as a lightweight diagnostic fallback and eventually retired.

---

## 1. Visual Layout & High-Fidelity Console Screenshot

The live console utilizes a structured, modular panel hierarchy rendered inside the terminal's alternate screen buffer (`screen=True`).

Below is an exact visual ASCII representation of the live dashboard during active trading execution:

```
╭─────────────────────────────────────────────────────────────────── Trading Bot ───────────────────────────────────────────────────────────────────╮
│ ╭──────────────────────────────────────────────────────────────────── Overview ───────────────────────────────────────────────────────────────────╮ │
│ │ ╭─────────────────── Strategy ───────────────────╮╭───────────────────── Risk ─────────────────────╮╭────────────────── Bot Status ──────────────────╮╭────────────────── Health Check ──────────────────╮ │ │
│ │ │ Preset: balanced                               ││ Max total exposure: 5.00 SOL                   ││ State: MONITORING                              ││ Heartbeat: 0.4s ago                              │ │ │
│ │ │ Buy amount: 0.1000 SOL                         ││ Max position size: 0.50 SOL                    ││ Uptime: 04h 12m 30s                            ││ Last message: 0.4s ago                           │ │ │
│ │ │ Take profit: 200.00%                           ││ Max loss / trade: 0.05 SOL                     ││ Health: ok                                     ││ Health timeout: 10s                              │ │ │
│ │ │ Stop loss: 85.00%                              ││ Daily drawdown: 20.00%                         ││ Risk killed: no                                ││ API/WS health: ok                                │ │ │
│ │ │ Max active: 3                                  ││ Reserve balance: 0.10 SOL                      ││ Active positions: 2                            ││ Risk killed: no                                  │ │ │
│ │ │ Min market cap: 20.00 SOL                      ││ Health timeout: 10s                            ││ Last event: quote received: SolCat             ││ Stop requested: no                               │ │ │
│ │ │ Dry run: no                                    ││ Risk killed: no                                ││ Status: monitoring                             ││ Last status: monitoring                          │ │ │
│ │ │ Paper trade: no                                ││ Equity guard: enabled                          ││ Last message: 0.4s ago                         ││ Last event: quote received: SolCat               │ │ │
│ │ │ Wallet value: 1.4520 SOL                       ││ Daily PnL: +0.2299 SOL                         ││ Stream URL: wss://pumpportal.fun/api/data      ││                                                  │ │ │
│ │ │ Stagnant timeout: 45.0s                        ││ Circuit breaker: ok                            ││ Geyser endpoint: grpc.solana.xyz:10000         ││                                                  │ │ │
│ │ │                                                ││                                                ││ Audit log: runtime/audit_trail.jsonl           ││                                                  │ │ │
│ │ │                                                ││                                                ││ Last new token: SolCat                         ││                                                  │ │ │
│ │ ╰────────────────────────────────────────────────╯╰─────────────────────────────────────────────────╯╰─────────────────────────────────────────────────╯╰───────────────────────────────────────────────────╯ │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭──────────────────────────────────────────────────────────────────── Run Time ───────────────────────────────────────────────────────────────────╮ │
│ │ ╭──────────────────────────────────────────────────────────────── Open Positions ─────────────────────────────────────────────────────────────╮ │ │
│ │ │ Name               │ Mint        │  Entry MC │ Current MC │ Cost / Spend │ Token Amount │ Unit Token Price │ Perf / PnL │ Reason            │ │ │
│ │ ├────────────────────┼─────────────┼───────────┼────────────┼──────────────┼──────────────┼──────────────────┼────────────┼───────────────────┤ │ │
│ │ │ SolCat             │ 7EYnh...    │ 28.50 SOL │  62.10 SOL │   0.1000 SOL │       2.45M  │      0.0408 µSOL │   +117.89% │ TP1_FILLED_MOON   │ │ │
│ │ │ MoonDog            │ 3xP9k...    │ 18.20 SOL │  22.40 SOL │   0.1000 SOL │       4.10M  │      0.0244 µSOL │    +23.08% │ watch             │ │ │
│ │ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ │ ╭────────────────────────────────────────────────────────────────── Coin Polling ──────────────────────────────────────────────────────────────╮ │ │
│ │ │ Last message: 0.4s ago                                                                                                                      │ │ │
│ │ │ Last token: SolCat                                                                                                                          │ │ │
│ │ │ Stream URL: wss://pumpportal.fun/api/data                                                                                                   │ │ │
│ │ │ Geyser endpoint: grpc.solana.xyz:10000                                                                                                      │ │ │
│ │ │ Observed: 1,482                                                                                                                             │ │ │
│ │ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭────────────────────────────────────────────────────────────────── Audit Trail ──────────────────────────────────────────────────────────────────╮ │
│ │ ╭──────────────────────────────────────────────────────────────────── Events ─────────────────────────────────────────────────────────────────╮ │ │
│ │ │ • 19:42:10 [RISK] Trailing stop ratcheted to 0.0520 SOL for SolCat (Peak: 0.0620 SOL)                                                        │ │ │
│ │ │ • 19:42:10 [SELL] Take-profit Tier 1 executed for SolCat (50% sold @ 0.1144 SOL)                                                             │ │ │
│ │ │ • 19:38:05 [BUY] Entry order confirmed for MoonDog (0.1000 SOL @ 18.20 SOL MC)                                                              │ │ │
│ │ │ • 19:35:12 [FILTER] Candidate rejected (creator dumped 3 tokens in 24h)                                                                      │ │ │
│ │ │ • 19:30:00 [HEARTBEAT] System healthy, 2 active positions, slot latency 380ms                                                                │ │ │
│ │ │ • 19:15:02 [BUY] Entry order confirmed for SolCat (0.1000 SOL @ 28.50 SOL MC)                                                               │ │ │
│ │ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ │ ╭───────────────────────────────────────────────────────────────── Trade Ledger ──────────────────────────────────────────────────────────────╮ │ │
│ │ │ SELL 7EYnh... -> 0.1144 SOL | take_profit_tier_1                                                                                            │ │ │
│ │ │ BUY  3xP9k... @ 0.0244 µSOL | new_candidate_entry                                                                                           │ │ │
│ │ │ BUY  7EYnh... @ 0.0408 µSOL | new_candidate_entry                                                                                           │ │ │
│ │ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭──────────────────────────────────────────────────────────────────── Metrics ────────────────────────────────────────────────────────────────────╮ │
│ │ buys: 2                                                                                                                                       │ │
│ │ sells: 1                                                                                                                                      │ │
│ │ failures: 0                                                                                                                                   │ │
│ │ retries: 0                                                                                                                                    │ │
│ │ connection_loss: 0                                                                                                                            │ │
│ │ stale_data: 0                                                                                                                                 │ │
│ │ latency avg: 382.4 ms                                                                                                                         │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

## 2. Comprehensive Panel & Field Reference

The dashboard is organized into four main vertical panels enclosing dedicated sub-grids:

### Panel 1: Overview Grid (Top Section)
The Overview section provides an immediate operational snapshot split across four horizontal quadrants:

#### A. Strategy Sub-Panel (`border_style="cyan"`)
* **`Preset`**: Active strategy profile (`conservative`, `balanced`, or `aggressive`). Defines default exit multipliers, filter strictness, and candidate scoring thresholds.
* **`Buy amount`**: Base SOL capital allocated to each buy order (e.g. `0.1000 SOL`).
* **`Take profit`**: Primary take-profit multiplier threshold formatted as a percentage (e.g. `200.00%` = 2.0x entry price).
* **`Stop loss`**: Hard stop-loss multiplier threshold formatted as a percentage (e.g. `85.00%` = -15% floor).
* **`Max active`**: Maximum concurrent open positions permitted simultaneously (e.g. `3`).
* **`Min market cap`**: Minimum bonding curve market cap in SOL required before triggering buy orders (e.g. `20.00 SOL`).
* **`Dry run`**: Indicates whether dry-run execution is active (`yes` / `no`). In dry-run mode, on-chain transactions are simulated.
* **`Paper trade`**: Indicates whether simulated paper trading balances are being tracked (`yes` / `no`).
* **`Wallet value`**: Current on-chain or simulated wallet balance in SOL available for trading (e.g. `1.4520 SOL`).
* **`Stagnant timeout`**: Configured stagnation exit timeout in seconds before closing flat positions without price momentum (e.g. `45.0s` or `120.0s`).

#### B. Risk Sub-Panel (`border_style="red"`)
* **`Max total exposure`**: Hard cap on total portfolio capital deployed across all open positions in SOL (e.g. `5.00 SOL`).
* **`Max position size`**: Maximum allowable SOL capital committed to a single token (e.g. `0.50 SOL`).
* **`Max loss / trade`**: Maximum permissible loss on an individual position before forcing emergency exit (e.g. `0.05 SOL`).
* **`Daily drawdown`**: Maximum daily portfolio drawdown threshold (e.g. `20.00%`).
* **`Reserve balance`**: Minimum SOL balance reserved in the hot wallet for transaction fees and account rent (e.g. `0.10 SOL`).
* **`Health timeout`**: Maximum permissible interval in seconds without stream messages before declaring data stale (e.g. `10s`).
* **`Risk killed`**: Displays `yes` if an emergency risk kill-switch has triggered, or `no` during normal execution.
* **`Equity guard`**: Status of the pre-trade equity guard (`enabled` for live trading, `dry-run` during simulation).
* **`Daily PnL`**: Cumulative realized profit/loss for the current UTC trading day (e.g. `+0.2299 SOL` or `+229.9000 µSOL`).
* **`Circuit breaker`**: Portfolio circuit breaker state: `ok` (healthy) or `LOCKED` (trading halted due to drawdown limit breach).

#### C. Bot Status Sub-Panel (`border_style="blue"`)
* **`State`**: Real-time lifecycle state machine value (`IDLE`, `MONITORING`, `BUYING`, `HOLDING`, `SELLING`, `SHUTDOWN`).
* **`Uptime`**: Elapsed duration since bot startup formatted dynamically (e.g. `04h 12m 30s`, `12m 30s`, `45s`).
* **`Health`**: High-level health status (`ok` or `degraded`).
* **`Risk killed`**: Immediate visual indicator if capital protection killed active execution (`yes` / `no`).
* **`Active positions`**: Current count of open token positions managed by the bot.
* **`Last event`**: Concise description of the most recent operational event (e.g. `quote received: SolCat`).
* **`Status`**: Current operational status string (e.g. `monitoring`, `holding 2 positions`).
* **`Last message`**: Time elapsed since the most recent stream payload arrived (e.g. `0.4s ago`).
* **`Stream URL`**: Active WebSocket endpoint URL used for streaming market updates.
* **`Geyser endpoint`**: Yellowstone Geyser gRPC server endpoint (displayed if configured and distinct from WebSocket URL).
* **`Audit log`**: Target filesystem path for the append-only JSONL audit trail (`runtime/audit_trail.jsonl`).
* **`Last new token`**: Name/symbol of the most recently discovered token on the bonding curve feed.

#### D. Health Check Sub-Panel (`border_style="yellow"`)
* **`Heartbeat`**: Seconds elapsed since the last automated system sanity check (e.g. `0.4s ago`).
* **`Last message`**: Timestamp latency of incoming stream messages.
* **`Health timeout`**: Configured health check expiration threshold.
* **`API/WS health`**: Real-time connection state for REST APIs and streaming WebSockets/gRPC (`ok` or `degraded`).
* **`Risk killed`**: Internal kill-switch validation flag.
* **`Stop requested`**: Displays `yes` if SIGINT / SIGTERM shutdown has been initiated.
* **`Last status`**: Internal state machine status code.
* **`Last event`**: Telemetry event string.

---

### Panel 2: Run Time Group (Middle Section)

#### A. Open Positions Table (`border_style="green"`)
A real-time table tracking all active open bonding curve positions:
* **`Name`**: Token display name (truncated to 18 characters for clean visual alignment).
* **`Mint`**: Truncated Base58 Solana mint address (e.g. `7EYnh...`).
* **`Entry MC`**: Bonding curve market capitalization in SOL at the moment of entry.
* **`Current MC`**: Latest mark-to-market bonding curve market cap in SOL.
* **`Cost / Spend`**: Total SOL capital committed to acquiring the position.
* **`Token Amount`**: Quantity of remaining token units held, formatted with metric suffixes (`2.45M`, `850.00K`, `1.20B`).
* **`Unit Token Price`**: Current price per token unit in SOL or micro-SOL (`µSOL` for values $< 0.001\text{ SOL}$).
* **`Perf / PnL`**: Unrealized percentage return based on market cap movement ($(\text{Current MC} - \text{Entry MC}) / \text{Entry MC}$). Color-coded in green (`+117.89%`) or red (`-8.50%`).
* **`Reason`**: Active strategy trigger or scale-out status (e.g. `watch`, `TP1_FILLED_MOON`, `TRAILING_STOP_ACTIVE`).

#### B. Coin Polling Sub-Panel (`border_style="yellow"`)
* **`Last message`**: Latency of the latest coin stream update.
* **`Last token`**: Name of the latest token detected on the network.
* **`Stream URL`**: Active stream endpoint.
* **`Geyser endpoint`**: Active Yellowstone gRPC endpoint.
* **`Observed`**: Total count of unique token mints screened by the anti-rug engine during the session.

---

### Panel 3: Audit Trail Group (Lower Section)

#### A. Events Sub-Panel (`border_style="cyan"`)
Displays the **6 most recent chronological system events** with subsystem prefixes:
* `[BUY]`: Token entry confirmations, transaction signatures, and initial fill sizes.
* `[SELL]`: Partial take-profit executions, trailing stop-loss triggers, and full liquidations.
* `[RISK]`: Trailing stop ratchet adjustments, drawdown calculations, and circuit breaker warnings.
* `[FILTER]`: Anti-rug rejection reasons (e.g. creator dump history, excessive dev holding, Gini concentration).
* `[HEARTBEAT]`: Periodic operational sanity checks and latency reports.

#### B. Trade Ledger Sub-Panel (`border_style="green"`)
Displays the **5 most recent buy/sell trade executions**:
* Format: `ACTION MINT_PREFIX @ PRICE | REASON`
* Example: `SELL 7EYnh... -> 0.1144 SOL | take_profit_tier_1`
* Example: `BUY 3xP9k... @ 0.0244 µSOL | new_candidate_entry`

---

### Panel 4: Metrics Panel (Bottom Section)
Displays cumulative counters across the entire active session:
* **`buys`**: Total number of successfully confirmed buy transactions.
* **`sells`**: Total number of successfully confirmed sell transactions.
* **`failures`**: Total count of failed on-chain transactions or rejected Jito bundles.
* **`retries`**: Number of automated slippage/RPC retry attempts.
* **`connection_loss`**: Total count of stream disconnection and reconnection events.
* **`stale_data`**: Count of dropped or expired quotes exceeding health timeout.
* **`latency avg`**: Rolling average slot latency in milliseconds (e.g. `382.4 ms`).

---

## 3. Visual Styling & Color Coding Rules

The console interface enforces strict color coding to maximize operational clarity:

| Color Style | Applied Subsystems | Operational Meaning |
| :--- | :--- | :--- |
| **Cyan** | Strategy Panel, Events Panel, Token Names | Strategy parameters, general telemetry, and active token identifiers. |
| **Red** | Risk Panel, Negative PnL, Circuit Breaker | Capital risk constraints, drawdown limits, loss metrics, and lockouts. |
| **Green** | Open Positions, Trade Ledger, Positive PnL | Active holdings, confirmed trade executions, and profitable returns. |
| **Blue** | Overview Container, Bot Status Panel | Core lifecycle state machine, uptime tracking, and endpoint status. |
| **Yellow** | Health Check, Coin Polling, Warnings | Connection heartbeats, stream latency, and non-fatal operational alerts. |
| **Magenta** | Audit Trail Container, Metrics Panel | Historical auditing, event logs, and cumulative execution counters. |
| **White / Bold** | Outer Dashboard Border, Headers | High-level container boundaries and primary screen titles. |

---

## 4. Operational Lifecycle States & Diagnostic Indicators

### Lifecycle State Machine (`bot.state`)
1. **`IDLE`**: Initializing runtime resources, connecting to Solana RPC nodes, and loading persisted state.
2. **`MONITORING`**: Streaming live market events, screening new bonding curve launches, and evaluating entry criteria.
3. **`BUYING`**: Building transaction instructions, securing Jito private mempool bundles, and confirming entry orders.
4. **`HOLDING`**: Managing open token positions, ratcheting dynamic trailing stops, and monitoring take-profit tiers.
5. **`SELLING`**: Dispatching partial scale-out sells or executing full position liquidations.
6. **`SHUTDOWN`**: Flushing pending audit records, canceling background workers, and safely closing websocket connections.

### Unit Formatting Rules
* **SOL Values**: Displayed to 4 decimal places for trade sizes and PnL (e.g. `0.1000 SOL`, `+0.2299 SOL`).
* **Micro-SOL (`µSOL`)**: Values smaller than `0.001 SOL` are automatically converted to micro-SOL (e.g. `0.0000408 SOL` $\rightarrow$ `0.0408 µSOL`) to prevent scientific notation and preserve table alignment.
* **Token Quantities**: Compact metric abbreviations (`K` for thousands, `M` for millions, `B` for billions).
* **Uptime Duration**: Clean human-readable intervals (`04h 12m 30s` or `1d 02h 15m 00s`).

---

## 5. Visual Stability & Terminal Compatibility (BUG-10 / BUG-29)

* **Alternate Screen Buffer (`screen=True`)**: Renders all live frame updates in the terminal's alternate buffer, preserving your normal shell history upon exit.
* **Console Logging Suppression (BUG-29)**: Uncaptured stderr/stdout logging handlers are suppressed during interactive TUI execution to prevent cursor line feeds and viewport jumping.
* **`NO_COLOR` Standard Compliance**: Setting the `NO_COLOR=1` environment variable automatically strips all ANSI styling and renders clean plaintext for accessibility or automated terminal capture.

---

## 6. Headless VPS & Background Daemon Execution

For 24/7 background operation on remote VPS servers or systemd services where interactive terminal rendering is unnecessary, run with the `--headless` flag:

```bash
pumpbot --preset balanced --headless --log-level INFO
```

In headless mode:
* Rich alternate-screen rendering is completely bypassed.
* Clean ANSI-stripped log messages are streamed directly to `sys.stderr` and log files (`bot.log`).
* Full compatibility with systemd journalctl, Grafana Loki, and remote log forwarders.
