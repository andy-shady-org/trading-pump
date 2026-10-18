# Replay Engine

> **Navigation**: [User Guide](USER-GUIDE.md) | [Financial Strategy](STRATEGY.md) | [Risk Controls](RISK.md) | [Terminal UI](TERMINAL-UI.md) | [Web UI](WEB-UI.md) | [Feature Catalog](FEATURES.md) | [Audit Tool](AUDIT-TOOL.md)

The replay engine is a historical paper-trading subsystem for evaluating strategy behavior against stored market snapshots without changing the live bot runtime. It is intentionally separated from the active dashboard in `pumpfun_trading/bot/run.py`, so the existing live trading UI stays exactly as-is and the replay workflow becomes a completely separate interface.

## Design goals

- Run historical strategy simulations from saved JSON or JSONL snapshots
- Evaluate buy/sell decisions using realistic fee + slippage assumptions
- Separate replay output from the live bot dashboard so operational monitoring remains stable
- Produce concise performance metrics for strategy comparison and debugging
- Provide a dedicated `pumpfun-replay` CLI entrypoint alongside the live trading bot
- Preserve the live bot’s crash-recovery and persisted state features while replay runs independently from runtime state

## Architecture

The replay logic lives in `pumpfun_trading/engines/replay.py` (and is exposed via `pumpfun_trading`) and is intentionally independent from the execution bot lifecycle:

- `PaperTradingEngine` handles market-snapshot processing and trade execution logic
- `ReplayEngine` is a compatibility alias retained for future extension
- `run_replay()` loads a dataset and produces a full summary object
- `render_replay_summary()` prints the core metrics table
- `render_replay_trades()` prints the trade ledger table
- `render_replay_dashboard()` renders a dedicated replay-only dashboard panel

The live bot UI remains in `pumpfun_trading/bot/run.py` and is not modified to support historical replay execution. Replay output is instead routed through its own display path from the CLI. The persisted bot status snapshot is also kept separate from replay data: replay reads historical market data, while the live runtime independently maintains its restart-state file for active positions and recent operational memory.

## Supported dataset shape

The engine accepts either JSON or JSONL files containing snapshot records. Records may contain any of the following common keys:

- `timestamp`, `time`, `event_time`, `ts`, `created_at`, `createdAt`
- `mint`, `address`, `token_mint`, `tokenMint`
- `name`, `token_name`, `display_name`, `displayName`
- `price`, `price_usd`, `priceUsd`, `last_price`, `lastPrice`
- `signal`, `buy_signal`, `sell_signal`, `should_buy`, `should_sell`

The engine will also accept object wrappers like:

- `{ "data": [...] }`
- `{ "items": [...] }`
- `{ "records": [...] }`
- `{ "snapshots": [...] }`
- `{ "results": [...] }`

The simulator is intentionally tolerant of slightly different payload structures so it is easy to run replay datasets captured from local research or debug exports.

## Execution model

The replay engine evaluates each snapshot in order and applies a simple paper-trading strategy:

1. If a record is flagged as a buy signal and the portfolio is below the configured max active positions, it opens a position using a fraction of available cash.
2. If a position is already open, the engine checks for a sell signal or a percentage threshold hit against the configured take-profit / stop-loss multipliers.
3. Position exits are recorded with reason tags such as `buy_signal`, `sell_signal`, `take_profit`, and `stop_loss`.
4. Cash, open positions, equity, and realized trade outcomes are updated through the full sequence.

The replay engine also includes a realistic fee/slippage assumption via:

- `fee_bps` for estimated trading fees
- `slippage_bps` for estimated fill impact

This keeps the simulation more realistic than a pure zero-cost trade model while still remaining lightweight enough for quick replay runs.

The steps above describe the **simple** model, used when no config or preset is given (or with `--simple-exits`).

## Live-fidelity replay (Sprint 24C, BUG-61)

With `--config` or `--preset`, replay runs the same sizing, risk limits and exits as the live bot, and books the same modelled costs as paper mode:

- **Sizing and limits:** every entry spends `buy_amount_sol`. It is skipped, with the reason counted in `entry_rejections`, when the live limits would refuse it: `max_buy_attempts_per_mint`, `max_total_exposure_sol`, `max_position_size_sol`, `max_token_concentration_pct` or `reserve_balance_sol`.
- **Exits:** the live exit stack from `strategies/exits.py`: stop-loss, stagnant-curve and max-hold timeouts, tiered take-profits (partial sells), moonbag floor, trailing stop, or single take-profit when tiers are off. Time-based exits run on the replay clock for every open position, like the live refresh loop. A graduated curve exits as `bonding_curve_graduated`. Each sell records `reason` (the exit type), `exit_detail`, `partial` and `hold_seconds`.
- **Costs** (`engines/costs.py`; turn off with `--no-costs`): Pump.fun's fee on each side (125 bps), the 5,000-lamport network fee plus `--priority-fee-lamports`, the Jito tip (`--tip-lamports`, default `PUMPFUN_JITO_TIP_LAMPORTS` when `PUMPFUN_USE_JITO` is on) and the token-account rent, paid on the buy and refunded when a full exit closes the account. Sells carry `gross_pnl_sol`, `costs_sol` and `net_pnl_sol`; `pnl` is net, so win rate, profit factor and the optimizer's fitness are all after costs.
- **Entries:** on a capture recorded by `pumpbot --record-replay`, replay buys only where the live bot bought (its recorded fills), so exits, sizing and costs can be compared with the audit trail. On datasets without fills (synthetic scenarios, harvester output) it buys on buy signals. The bot's own fills and other wallets' trades are price points, never exit orders.

!!! warning "What live-fidelity replay does not replay"
    The entry screener (social links, holder distribution, creator history) needs enrichment data that a capture does not record, so replay cannot say which tokens the screener would pass. Treat replay results as a test of **sizing, exits and costs**, not of token selection.

### Confirmed entries (`entry_mode: "confirmed"`, FEAT-52)

When the config sets `entry_mode: "confirmed"` (the `momentum` preset, `configs/canary.json`), replay models the watch → confirm path instead of mirroring recorded fills (`entries_from: confirmed` in the summary):

1. A recorded create event whose `screening` record passed (or has no record) goes onto the watch list (`watch_ttl_seconds`, `watch_max_mints`). Mints already bought are never watched again.
2. The curve's real SOL reserve is derived from each recorded market cap. A mint is promoted once it grew by `watch_promote_min_sol_growth`, within `watch_max_trade_subscriptions`. The trade that promotes it is not counted: live, trades only arrive after the subscription.
3. Trades after promotion feed the order-flow check. A buy needs the age window, the `min_market_cap_sol`–`momentum_max_market_cap_sol` band, `momentum_min_unique_buyers` distinct buyers (the creator left out), net inflow, buy ratio and z-score, plus the cost guard (`max_entry_cost_share_pct`, same `ReplayCostModel`).
4. Buys carry `reason: momentum_confirmed`, `strategy: momentum` and `entry_metrics`; the momentum exits (buy-flow stagnation with `stagnant_min_buy_sol`, break-even ratchet) run on the replay clock.

`watch_stats` in the summary counts `watched`, `screen_rejected`, `promoted`, `budget_full`, `expired`, `cost_guard_refused` and `confirmed`. `pumpfun-optimize` with a confirmed base config also searches the watch, band and momentum-exit keys.

!!! warning "Confirmed replay on launch-mode captures"
    A capture from a launch-mode bot only has trade flow for the mints that bot bought, so confirmed replay can only buy among them. Use it to compare thresholds, and confirm on a capture recorded in confirmed mode (`configs/capture.json`) before trusting the PnL. Results and the train/test split are in [`dev/STRATEGY-PIVOT.md` §6](dev/STRATEGY-PIVOT.md#6-results-log).

### Replay-vs-live parity (`--compare-audit`)

```bash
pumpfun-replay --path data/replay_capture.jsonl --config configs/canary.json \
  --compare-audit data/audit_trail.jsonl --mode summary
```

Lines up the replay trades with the audit trail per mint: entries in both / live only / replay only, exit reasons (live reason text is normalised to the exit type), and net PnL. It exits with code 1 when the net PnL gap is larger than `max(--parity-tolerance-sol, --parity-tolerance-pct × |live net PnL|)` (defaults 0.002 SOL and 10%). Expected, explainable differences: live fills at the executed price while replay fills at the recorded market cap, live costs come from the transaction (dynamic tips) while replay uses the model, and live exits can lag by one refresh.

## Command usage

The replay feature is exposed through the dedicated `pumpfun-replay` CLI command:

```bash
pumpfun-replay --path ./historical_snapshots.json --mode dashboard
pumpfun-replay --path ./historical_snapshots.json --mode summary
pumpfun-replay --path ./historical_snapshots.json --mode trades
```

### Arguments

- `--path`: path to the JSON or JSONL dataset to replay
- `--mode`: output mode, one of `dashboard` (default), `summary`, or `trades`
- `--mint`: filter replay snapshots by token mint address
- `--mint-name`: filter replay snapshots by token / mint name
- `--token-name`: alias to filter replay snapshots by token name

The replay flow is intentionally isolated from the live bot execution flow:

- no wallet keys are required
- no websocket or RPC connection is required
- the layout does not alter the existing live bot dashboard UI

## Example output

### Dashboard mode

```text
Replay Engine
╭────────────────────────────────────────────────────────────────────────────╮
│ Replay Status                                                              │
│ Trades: 7                                                                  │
│ Buys: 4                                                                    │
│ Sells: 3                                                                   │
│ Final cash: 91.3241                                                        │
╰────────────────────────────────────────────────────────────────────────────╯

Replay summary
Metric                Value
initial_cash          100.0
final_equity          108.2
total_trades          7
profit_factor         1.84
max_drawdown          0.12
win_rate              0.66
average_trade_return  0.12
open_positions        0
```

### Trade ledger

```text
Replay trades
Index  Timestamp   Mint Name  Mint  Action  Qty  P&L  Return  Reason
0      1710000000  SolCat     ...   buy     ...
1      1710000600  SolCat     ...   sell    ...  ...  ...     take_profit
```

## Metrics returned by the replay engine

The `run_replay()` summary includes:

- `initial_cash`
- `final_cash`
- `final_equity`
- `total_trades`
- `buy_count`
- `sell_count`
- `open_positions`
- `profit_factor`
- `max_drawdown`
- `win_rate`
- `average_trade_return`
- `total_return`
- `trades`
- `equity_history`
- `positions`

These outputs are useful for:

- validating whether a strategy would have survived a historical regime
- comparing different risk / entry thresholds
- debugging path-dependent behavior across token lifecycle snapshots
- creating a lightweight research workflow before enabling a strategy in live mode

## A note on file structure and UI separation

The repo already contains a live bot dashboard in `pumpfun_trading/bot/run.py`. This replay engine deliberately does not modify that code path. Instead, the historical replay feature is presented as a separate UI surface via the dedicated `pumpfun-replay` command. This preserves the existing operational layout while enabling a research and backtesting workflow on top of the same repository.

## Python API usage

```python
from pumpfun_trading.engines.replay import PaperTradingEngine, run_replay
# or: from pumpfun_trading import PaperTradingEngine, run_replay

summary = run_replay("./historical_snapshots.json")
print(summary["profit_factor"])
print(summary["win_rate"])
print(len(summary["trades"]))
```

```python
engine = PaperTradingEngine(
    initial_cash=100.0,
    max_positions=2,
    fee_bps=100,
    slippage_bps=125,
    buy_fraction=0.35,
    take_profit=1.5,
    stop_loss=0.85,
)
summary = engine.run(records)
```

## Dataset Generation Pipelines (FEAT-21)

To generate valid `.jsonl` replay files for backtesting and parameter tuning, the repository provides three integrated dataset generation methods:

### 1. Live Bot Non-Blocking Stream Recording
Enable background stream recording during live or paper trading without execution latency penalties:

```bash
pumpbot --preset balanced --record-replay ./datasets/live_session.jsonl
```

Besides market ticks and the bot's own fills, the capture holds one record per screened token with what the screener saw. These records have no price, and the replay engine skips them; use them to see which filters rejected tokens that later ran:

```json
{"timestamp": 1760700000.1, "mint": "…pump", "name": "Tok", "event": "screening",
 "screening": {"passed": false, "risk_score": 60.0, "reasons": ["…"], "market_cap_sol": 31.2,
   "latency_ms": 1104.2, "social_links": 1, "twitter": true, "telegram": false, "website": false,
   "holders_available": true, "holder_count": 12, "top5_pct": 0.21, "gini": 0.62,
   "creator_pct": 0.04, "creator": "…", "creator_launches_24h": 3, "creator_total_launches": 9,
   "creator_rugs": 0, "flags": {"missing_holder_data": false}}}
```

### 2. Standalone Harvester CLI (`pumpfun record` / `pumpfun-recorder`)
Collect market quote streams and trade events directly from Yellowstone Geyser or WebSockets without a funded trading wallet:

```bash
# Ingest live market data for 10 minutes
pumpfun-recorder --output ./datasets/market_10m.jsonl --duration 600

# Ingest up to 5,000 snapshots from Yellowstone Geyser gRPC stream
pumpfun record --geyser-endpoint http://127.0.0.1:10000 --output ./datasets/geyser_stream.jsonl --limit 5000
```

### 3. Synthetic Price Scenario Generator
Generate deterministic price curves to stress-test exit rules, stop-losses, and stagnation timeouts:

```bash
# Generate 100-step multi-tier take profit scenario
pumpfun-recorder --synthetic multi_tier_take_profit --output ./datasets/synth_tp.jsonl --synthetic-steps 100

# Available scenarios:
# - pump_and_dump: Multi-tier run-up (1.0x -> 4.5x) followed by sharp collapse (0.2x)
# - stagnant_curve: Flat launch MC at 27.96 SOL to test inactivity timeouts
# - multi_tier_take_profit: Escalates through Tier 1 (2.0x), Tier 2 (3.5x), and Moonbag
# - gradual_grind: Organic linear growth curve (1.0x -> 2.5x)
# - flash_rug: Rapid drop to 0.05x to test stop-loss execution
```

Programmatic generation via Python:
```python
from pumpfun_trading.engines.generators import SyntheticReplayGenerator

# Generate synthetic curve in memory
records = SyntheticReplayGenerator.generate(scenario="multi_tier_take_profit", steps=60)

# Write directly to JSONL file
SyntheticReplayGenerator.generate_to_file(
    "synth_tp.jsonl", scenario="flash_rug", steps=50
)
```

### 4. Historical REST Trade Exporter
Extract past trade histories for specific tokens via Pump.fun REST API:

```bash
pumpfun-recorder --from-mint <MINT_ADDRESS> --output ./datasets/token_trades.jsonl --limit 200
```

Programmatic export via Python:
```python
import asyncio
from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.engines.generators import RestHistoryExporter


async def export():
    async with PumpFunApiClient() as client:
        await RestHistoryExporter.export_token_trades_to_file(
            client=client,
            mint="YOUR_MINT_ADDRESS",
            output_path="token_trades.jsonl",
            limit=200,
        )


asyncio.run(export())
```

## Recommended workflow

1. Export historical token snapshots as JSON or JSONL
2. Run the replay command against that dataset
3. Review the strategy summary dashboard
4. Inspect the individual trade ledger for exit reasons and path quality
5. Compare candidate configurations across multiple replay datasets before moving to live trading
6. Keep restart-state recovery and live bot persistence separate from historical replay analysis so each workflow remains deterministic

This makes the replay engine an operational companion to the live bot rather than a replacement for it.
