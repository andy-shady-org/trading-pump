# Terminal UI & Operator Observability Guide

The Terminal User Interface (`pumpbot`) is an institutional-grade, low-overhead console command center powered by Rich. It is engineered specifically for system operators, algorithmic traders, and liquidity engineers who require zero-overhead local execution, sub-millisecond telemetry monitoring, and immediate cashflow generation to self-fund ongoing project development.

> **Operational Note & Lifecycle Strategy**: The Terminal UI is the **income path** for the project: profits made with it fund the hosted Web Dashboard (FEAT-10). Web UI work starts only after the funding gate in [`dev/RELEASE-GATE.md` §3.7](dev/RELEASE-GATE.md#37-funding-gate-for-the-web-ui) passes, and the Terminal UI stays the primary interface until the Sprint 35 deprecation gate; after that it is kept as a lightweight diagnostic fallback. Planned terminal improvements for income (net PnL after fees and tips, wallet reconciliation, pause without restart, daily PnL digest) are in Phase 4b of [`dev/TODO.md`](dev/TODO.md#phase-4b-terminal-income-track-highest-priority).
>
> **Note on PnL:** since Sprint 24B (FEAT-49) the Risk panel shows `Daily PnL (net)` (after network fees, priority fees, Jito tips and token-account rent), `Daily PnL (gross)`, `Costs today` and `Session net PnL`. In paper mode the costs and the Pump.fun fee are modelled; live trades read them from the confirmed transaction. Check the numbers against the wallet with `pumpfun-audit reconcile` ([`dev/RUNBOOK.md` §5.3](dev/RUNBOOK.md#53-daily-wallet-reconciliation)).

---

## 1. Visual Layout & High-Fidelity Console Screenshot

The live console utilizes a structured, modular panel hierarchy rendered inside the terminal's alternate screen buffer (`screen=True`).

Below is the dashboard rendered by `ui/dashboard.py` at 150 columns with two open positions (dry run, `balanced` preset). The configured limits sit in the Strategy panel, and Coin Polling and Metrics share one row inside Run Time so open positions don't push the metrics off the screen:

```
╭─────────────────────────────────────────────────────────────────── Trading Bot ────────────────────────────────────────────────────────────────────╮
│ ╭─────────────────────────────────────────────────────────────────── Overview ───────────────────────────────────────────────────────────────────╮ │
│ │ ╭──────────── Strategy ────────────╮╭────────────── Risk ──────────────╮╭────────── Bot Status ───────────╮╭───────── Health Check ──────────╮ │ │
│ │ │ Preset                  balanced ││ Reserve balance         0.10 SOL ││ State                      idle ││ Heartbeat              0.0s ago │ │ │
│ │ │ Buy amount            0.0100 SOL ││ Risk killed                   no ││ Buying                   active ││ Last message           0.0s ago │ │ │
│ │ │ Take profit              150.00% ││ Equity guard             dry-run ││ Uptime                       0s ││ Health timeout              60s │ │ │
│ │ │ Stop loss                 85.00% ││ Daily PnL (net)      +0.0000 SOL ││ Health                       ok ││ API/WS health                ok │ │ │
│ │ │ Max active                     1 ││ Daily PnL (gross)    +0.0000 SOL ││ Risk killed                  no ││ Trade feed                   ok │ │ │
│ │ │ Min market cap          5.00 SOL ││ Costs today          +0.0000 SOL ││ Active positions              2 ││ Risk killed                  no │ │ │
│ │ │ Dry run                      yes ││ Session net PnL      +0.0000 SOL ││ Last event      waiting for new ││ Stop requested               no │ │ │
│ │ │ Paper trade                   no ││ Circuit breaker               ok ││                    token stream ││ Last status        initializing │ │ │
│ │ │ Wallet value          0.2000 SOL ││ Reconciliation           not run ││ Status             initializing ││ Last event      waiting for new │ │ │
│ │ │ Stagnant timeout          120.0s ││                                  ││ Last message           0.0s ago ││                    token stream │ │ │
│ │ │ Max total exposure      0.25 SOL ││                                  ││ Stream URL      wss://pumpport… ││                                 │ │ │
│ │ │ Max position size       0.05 SOL ││                                  ││ Audit log       data/audit_tr… ││                                 │ │ │
│ │ │ Max loss / trade        0.02 SOL ││                                  ││ Last new token                - ││                                 │ │ │
│ │ │ Daily drawdown            20.00% ││                                  ││                                 ││                                 │ │ │
│ │ ╰──────────────────────────────────╯╰──────────────────────────────────╯╰─────────────────────────────────╯╰─────────────────────────────────╯ │ │
│ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────────────────────────────────────────────────────── Run Time ───────────────────────────────────────────────────────────────────╮ │
│ │ ╭────────────────────────────────────────────────────────────── Open Positions ──────────────────────────────────────────────────────────────╮ │ │
│ │ │ ┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┓ │ │ │
│ │ │ ┃ Name                ┃ Mint         ┃   Entry MC ┃  Current MC ┃  Cost / Spend ┃  Token Amount ┃ Unit Token Price ┃ Perf / PnL ┃ Reason ┃ │ │ │
│ │ │ ┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━┩ │ │ │
│ │ │ │ So1CatMint11111111  │ So1CatMi...  │  30.00 SOL │   30.00 SOL │    0.0100 SOL │       350.00B │      0.0286 µSOL │      0.00% │ entry  │ │ │ │
│ │ │ ├─────────────────────┼──────────────┼────────────┼─────────────┼───────────────┼───────────────┼──────────────────┼────────────┼────────┤ │ │ │
│ │ │ │ MoonDogMint1111111  │ MoonDogM...  │  30.00 SOL │   30.00 SOL │    0.0100 SOL │       350.00B │      0.0286 µSOL │      0.00% │ entry  │ │ │ │
│ │ │ └─────────────────────┴──────────────┴────────────┴─────────────┴───────────────┴───────────────┴──────────────────┴────────────┴────────┘ │ │ │
│ │ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ │ ╭─────────────────────────── Coin Polling ────────────────────────────╮╭────────────────────────────── Metrics ──────────────────────────────╮ │ │
│ │ │ Last message                                               0.0s ago ││ buys                                                              0 │ │ │
│ │ │ Last token                                                        - ││ sells                                                             0 │ │ │
│ │ │ Stream URL                            wss://pumpportal.fun/api/data ││ failures                                                          0 │ │ │
│ │ │ Observed                                                          0 ││ retries                                                           0 │ │ │
│ │ │                                                                     ││ connection_loss                                                   0 │ │ │
│ │ │                                                                     ││ stale_data                                                        0 │ │ │
│ │ │                                                                     ││ latency avg                                                  0.0 ms │ │ │
│ │ ╰─────────────────────────────────────────────────────────────────────╯╰─────────────────────────────────────────────────────────────────────╯ │ │
│ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭───────────────────────────────────────────────────────────────── Audit Trail ──────────────────────────────────────────────────────────────────╮ │
│ │ ╭────────────────────────────────────────────────────────────────── Events ──────────────────────────────────────────────────────────────────╮ │ │
│ │ │ No events yet.                                                                                                                             │ │ │
│ │ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ │ ╭─────────────────────────────────────────────────────────────── Trade Ledger ───────────────────────────────────────────────────────────────╮ │ │
│ │ │ No trades recorded yet.                                                                                                                    │ │ │
│ │ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │ │
│ ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
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
* **`Max total exposure`**: Hard cap on total portfolio capital deployed across all open positions in SOL (e.g. `5.00 SOL`).
* **`Max position size`**: Maximum allowable SOL capital committed to a single token (e.g. `0.50 SOL`).
* **`Max loss / trade`**: Maximum permissible loss on an individual position before forcing emergency exit (e.g. `0.05 SOL`).
* **`Daily drawdown`**: Maximum daily portfolio drawdown threshold (e.g. `20.00%`).

#### B. Risk Sub-Panel (`border_style="red"`)
Live risk state only; the configured limits above are in the Strategy panel.
* **`Reserve balance`**: Minimum SOL balance reserved in the hot wallet for transaction fees and account rent (e.g. `0.10 SOL`).
* **`Risk killed`**: Displays `yes` if an emergency risk kill-switch has triggered, or `no` during normal execution.
* **`Equity guard`**: Status of the pre-trade equity guard (`enabled` for live trading, `dry-run` during simulation).
* **`Daily PnL`**: Cumulative realized profit/loss for the current UTC trading day (e.g. `+0.2299 SOL` or `+229.9000 µSOL`).
* **`Circuit breaker`**: Portfolio circuit breaker state: `ok` (healthy) or `LOCKED` (trading halted due to drawdown limit breach).
* **`Reconciliation`**: Last `pumpfun-audit reconcile` result for this audit trail: `OK (n trades, age)` in green, `GAP (n problem(s), age)` in red, `STALE` when the last OK is older than 36 hours, or `not run`. The bot doesn't reconcile by itself; run the command daily ([`dev/RUNBOOK.md` §5.3](dev/RUNBOOK.md#53-daily-wallet-reconciliation)) or on the supervised timer. A new `GAP` result is also sent as an alert.
* **`Profit sweep`** (only when `profit_sweep_enabled`): total swept to the cold wallet and the number of sweeps (`0.2500 SOL in 1`), `none yet`, or `ERROR (…)` after a failed transfer (FEAT-42, [`dev/RUNBOOK.md` §5.6](dev/RUNBOOK.md#56-profit-sweep-to-a-cold-wallet-feat-42-off-by-default)).

#### C. Bot Status Sub-Panel (`border_style="blue"`)
* **`State`**: Real-time lifecycle state machine value (`IDLE`, `MONITORING`, `BUYING`, `HOLDING`, `SELLING`, `SHUTDOWN`).
* **`Buying`**: `active`, or `PAUSED (reason, minutes)` in yellow while the operator pause is on. `kill -USR1 <pid>` toggles it: no new buys or capital rotation, open positions keep being managed. The pause survives restarts ([`dev/RUNBOOK.md` §5.5](dev/RUNBOOK.md#55-operator-pause-and-unattended-alerts-sprint-24d-feat-50)).
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
* **`Trade feed`**: `ok`, or `REFUSED (key funds?)` while the trade-feed circuit breaker is open: PumpPortal refuses per-token trade subscriptions because the stream URL has no API key or its wallet has run out of funds (BUG-112, BUG-116). While open, new buys are blocked (`require_trade_feed`), a probe subscription is sent every `trade_feed_probe_seconds`, and alerts are sent on trip and recovery.
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

#### B. Coin Polling and Metrics Row
Coin Polling (left) and Metrics (right) share one row at half the width each, so a long Open Positions table no longer pushes the metrics off the bottom of the screen.

Coin Polling (`border_style="yellow"`):
* **`Last message`**: Latency of the latest coin stream update.
* **`Last token`**: Name of the latest token detected on the network.
* **`Stream URL`**: Active stream endpoint.
* **`Geyser endpoint`**: Active Yellowstone gRPC endpoint.
* **`Observed`**: Total count of unique token mints screened by the anti-rug engine during the session.

Metrics (`border_style="magenta"`, right half of the row) shows cumulative counters for the session:
* **`buys`**: Total number of successfully confirmed buy transactions.
* **`sells`**: Total number of successfully confirmed sell transactions.
* **`failures`**: Total count of failed on-chain transactions or rejected Jito bundles.
* **`retries`**: Number of automated slippage/RPC retry attempts.
* **`connection_loss`**: Total count of stream disconnection and reconnection events.
* **`stale_data`**: Count of dropped or expired quotes exceeding health timeout.
* **`latency avg`**: Rolling average slot latency in milliseconds (e.g. `382.4 ms`).

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

## 3. Visual Styling & Color Coding Rules

The console interface enforces strict color coding to maximize operational clarity:

| Color Style | Applied Subsystems | Operational Meaning |
| :--- | :--- | :--- |
| **Cyan** | Strategy Panel, Events Panel, Token Names | Strategy parameters, general telemetry, and active token identifiers. |
| **Red** | Risk Panel, Negative PnL, Circuit Breaker | Capital risk constraints, drawdown limits, loss metrics, and lockouts. |
| **Green** | Open Positions, Trade Ledger, Positive PnL | Active holdings, confirmed trade executions, and profitable returns. |
| **Blue** | Overview Container, Bot Status Panel | Core lifecycle state machine, uptime tracking, and endpoint status. |
| **Yellow** | Health Check, Coin Polling, Warnings | Connection heartbeats, stream latency, and non-fatal operational alerts. |
| **Magenta** | Audit Trail Container, Metrics | Historical auditing, event logs, and cumulative execution counters. |
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
pumpbot --config configs/canary.json --headless
```

In headless mode:
* Rich alternate-screen rendering is completely bypassed.
* Clean ANSI-stripped log messages are streamed directly to `sys.stderr` and log files (`bot.log`, or `PUMPFUN_BOT_LOG_PATH`).
* Full compatibility with systemd journalctl, Grafana Loki, and remote log forwarders.
* Nobody watches the dashboard, so set an alert provider: the bot alerts on start and stop, on stream / RPC degradation lasting longer than `degradation_alert_minutes`, on a new reconciliation gap, and sends a daily net-PnL summary.
* Ready-made systemd and launchd templates (restart limits, reconciliation timer) are in `deploy/`; see [`dev/RUNBOOK.md` §8](dev/RUNBOOK.md#8-supervised-deployment-and-hardening-sprint-24d). `pumpbot` exits 1 when its stream loop ends without a shutdown request, so the supervisor restarts it.
