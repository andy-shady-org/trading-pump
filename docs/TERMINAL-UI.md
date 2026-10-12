# Terminal UI & Operator Observability Guide

The Terminal User Interface (`pumpbot`) is a high-performance, lightweight console command center powered by Rich. It is designed for system operators and quantitative traders who require zero-overhead local execution, sub-millisecond telemetry monitoring, and immediate cashflow generation to fund ongoing project development.

> **Operational Note & Lifecycle Strategy**: The Terminal UI serves as the immediate self-funding and testing interface during early development sprints. As the full-featured FastAPI Web Dashboard (FEAT-10) reaches production maturity, the Terminal UI will be maintained as a lightweight diagnostic fallback and eventually retired.

---

## 1. Visual Layout & Panel Hierarchy

The live console utilizes a structured panel hierarchy rendered inside the terminal's alternate screen buffer:

```
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Trading Bot ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Overview ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ ╭───────────────────────── Strategy ─────────────────────────╮╭─────────────────────────── Risk ───────────────────────────╮╭──────────────────────── Bot Status ────────────────────────╮╭────────────────────── Health Check ───────────────────────╮ │ │
│ │ │ Preset: balanced                                           ││ Max Positions: 3                                            ││ State: MONITORING                                          ││ Status: HEALTHY                                            │ │ │
│ │ │ Buy Size: 0.100 SOL                                        ││ Max Exposure: 25.0%                                         ││ Uptime: 04h 12m 30s                                        ││ Stream: GEYSER_GRPC (Connected)                            │ │ │
│ │ │ Slippage: 2.50%                                            ││ Min Reserve: 0.100 SOL                                      ││ Trades Executed: 14                                        ││ Slot Latency: 412 ms                                       │ │ │
│ │ │ Trailing Stop: Active (15%)                                ││ Drawdown Limit: 15.0%                                       ││ Win Rate: 71.4%                                            ││ Errors: 0                                                  │ │ │
│ │ ╰────────────────────────────────────────────────────────────╯╰─────────────────────────────────────────────────────────────╯╰────────────────────────────────────────────────────────────╯╰───────────────────────────────────────────────────────────╯ │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Active Positions (2/3) ────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Mint Address                                 Mint Name    Entry Price (SOL)    Current Price (SOL)    Peak Price (SOL)    PnL (SOL)       PnL (%)      Scale-Out Tiers     Exit Signal                                                                 │ │
│ │ 7EYnh...pump                                 SolCat       0.000000028          0.000000059            0.000000062         +0.110 SOL      +110.7%      Tier 1 [FILLED]     TRAILING_ACTIVE                                                             │ │
│ │ 3xP9k...pump                                 MoonDog      0.000000015          0.000000018            0.000000019         +0.020 SOL      +20.0%       Pending             HOLDING                                                                     │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Recent Trades ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Timestamp                  Type     Mint Name    Mint Address        Amount (SOL)    Price (SOL)          PnL (SOL)     PnL (%)      Reason                                                                                                                 │ │
│ │ 2026-10-12T19:42:10        SELL     PepePump     4kLM7...pump        0.210 SOL       0.000000072          +0.110 SOL    +110.0%      TAKE_PROFIT_TIER_1                                                                                                     │ │
│ │ 2026-10-12T19:15:02        BUY      SolCat       7EYnh...pump        0.100 SOL       0.000000028          --            --           NEW_CANDIDATE_ENTRY                                                                                                    │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Panel Descriptions

1. **Strategy Panel**: Displays the active preset (`conservative`, `balanced`, `aggressive`), base buy size in SOL, max slippage tolerance, and trailing stop configuration.
2. **Risk Panel**: Displays maximum allowed open positions, single-token concentration percentage cap, minimum wallet SOL buffer floor, and daily drawdown stop threshold.
3. **Bot Status Panel**: Real-time lifecycle state (`MONITORING`, `BUYING`, `HOLDING`, `SELLING`, `SHUTDOWN`), uptime counter, executed trade count, and historical win rate.
4. **Health Check Panel**: Ingestion stream status (`GEYSER_GRPC` / `REST`), latest Solana slot latency benchmark, connection state, and categorized error counts.
5. **Active Positions Table**: Real-time table displaying Mint Address, Token Name, entry valuation, current valuation, peak market cap, unrealized PnL (SOL / %), executed take-profit tiers, and current exit signals.
6. **Recent Trades Ledger**: Execution log detailing timestamp, trade side (BUY / SELL), Token Name, executed volume, realized PnL, and exit trigger rationale (e.g. `TAKE_PROFIT_TIER_1`, `TRAILING_STOP_EXIT`).

---

## 2. Rendering Technology & Visual Stability (BUG-10 / BUG-11)

To ensure seamless operation on both local developer workstations and remote cloud VPS terminals:

* **Alternate Screen Buffer (`screen=True`)**: Renders all live frame updates in the terminal's alternate screen buffer. This eliminates scrollback pollution and prevents repeated header printing when resizing viewports.
* **ANSI Stripping & `NO_COLOR` Compliance (BUG-10)**: Respects the `NO_COLOR` standard and non-interactive TTY environments by automatically stripping ANSI escape codes when piping output to log files or automated monitoring daemons.
* **Border Height Clamping**: Dynamically calculates terminal rows and columns, clamping panel dimensions to prevent row truncation or table overflowing.

---

## 3. Real-Time Telemetry & Slot Latency Benchmarks

The Terminal UI surfaces sub-millisecond execution telemetry to ensure network and RPC connections remain competitive against institutional MEV searchers:

* **Slot Latency Benchmark**: Calculates time difference between on-chain block slot production time and local Geyser deserialization time (target: $< 600\text{ ms}$).
* **Queue Ingestion Overflow**: Tracks dropped or queued stream messages under high transaction velocity.
* **Jito Bundle Confirmation Timing**: Tracks latency from bundle dispatch to validator block inclusion.

---

## 4. Multi-Channel Alerting & Webhook Payloads

System operators can configure instant push notifications to remote communication channels by setting environment variables in `.env`.

### Supported Notification Providers

* **Discord**: Standard Webhook integration supporting rich color-coded embeds.
* **Slack**: Incoming Webhook JSON blocks with structured trade metrics.
* **Telegram**: Direct bot messaging with Markdown formatting and sound alerts for critical circuit breaker trips.

### Example Webhook JSON Schema (Discord Embed)

```json
{
  "username": "PumpFun Trading Bot",
  "avatar_url": "https://pump.fun/logo.png",
  "embeds": [
    {
      "title": "🎯 Take-Profit Scale-Out Executed (Tier 1)",
      "color": 65280,
      "fields": [
        {"name": "Token", "value": "SolCat (`7EYnh...pump`)", "inline": true},
        {"name": "Sold Fraction", "value": "50% (0.100 SOL Principal Extracted)", "inline": true},
        {"name": "Realized PnL", "value": "+0.110 SOL (+110.7%)", "inline": true},
        {"name": "Status", "value": "Free Ride Active (Moonbag Trailing)", "inline": false}
      ],
      "timestamp": "2026-10-12T19:42:10.000Z"
    }
  ]
}
```

---

## 5. Headless & Background Daemon Execution

For continuous operation on remote VPS servers or systemd services where visual terminal rendering is unnecessary, run `pumpbot` in headless mode:

```bash
# Run headless with structured INFO logging
pumpbot --preset balanced --headless --log-level INFO
```

In headless mode, Rich live screen updates are disabled, and structured JSON/ANSI-stripped log records are emitted directly to stdout and log files for aggregation via Grafana Loki, Datadog, or systemd journalctl.
