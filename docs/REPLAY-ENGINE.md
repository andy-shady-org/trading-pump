# Replay Engine

The replay engine is a historical paper-trading subsystem for evaluating strategy behavior against stored market snapshots without changing the live bot runtime. It is intentionally separated from the active dashboard in `pumpfun_trading/bot/run.py`, so the existing live trading UI stays exactly as-is and the replay workflow becomes a completely separate interface.

## Design goals

- Run historical strategy simulations from saved JSON or JSONL snapshots
- Evaluate buy/sell decisions using realistic fee + slippage assumptions
- Separate replay output from the live bot dashboard so operational monitoring remains stable
- Produce concise performance metrics for strategy comparison and debugging
- Keep the replay path available from the same `pumpbot` CLI entrypoint as the rest of the project
- Preserve the live bot’s crash-recovery and persisted state features while replay runs independently from runtime state

## Architecture

The replay logic lives in `pumpfun_trading/replay.py` and is intentionally independent from the execution bot lifecycle:

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

## Command usage

The replay feature is exposed through the `pumpbot` CLI as a separate mode:

```bash
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode dashboard
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode summary
pumpbot --mode replay --replay-path ./historical_snapshots.json --replay-mode trades
```

### Arguments

- `--mode replay`: switches to the historical replay flow
- `--replay-path`: path to the JSON or JSONL dataset to replay
- `--replay-mode`: one of `dashboard`, `summary`, or `trades`

The replay flow is intentionally isolated from the live bot execution flow:

- no wallet keys are required
- no websocket or RPC connection is required
- the layout does not alter the existing live bot dashboard UI

## Example output

### Dashboard mode

```text
Replay Engine
╭────────────────────────────────────────────────────────────────────────────╮
│ Replay Status                                                           │
│ Trades: 7                                                               │
│ Buys: 4                                                                │
│ Sells: 3                                                               │
│ Final cash: 91.3241                                                     │
╰────────────────────────────────────────────────────────────────────────────╯

Replay summary
Metric             Value
initial_cash       100.0
final_equity       108.2
total_trades       7
profit_factor      1.84
max_drawdown       0.12
win_rate           0.66
average_trade_return 0.12
open_positions     0
```

### Trade ledger

```text
Replay trades
Index  Timestamp  Mint  Action  Qty  P&L  Return  Reason
0      1710000000 ...  buy     ...
1      1710000600 ...  sell    ...  ...   ...    take_profit
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

The repo already contains a live bot dashboard in `pumpfun_trading/bot/run.py`. This replay engine deliberately does not modify that code path. Instead, the historical replay feature is presented as a separate UI surface only when `--mode replay` is selected. This preserves the existing operational layout while enabling a research and backtesting workflow on top of the same repository.

## Python API usage

```python
from pumpfun_trading.replay import PaperTradingEngine, run_replay

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

## Recommended workflow

1. Export historical token snapshots as JSON or JSONL
2. Run the replay command against that dataset
3. Review the strategy summary dashboard
4. Inspect the individual trade ledger for exit reasons and path quality
5. Compare candidate configurations across multiple replay datasets before moving to live trading
6. Keep restart-state recovery and live bot persistence separate from historical replay analysis so each workflow remains deterministic

This makes the replay engine an operational companion to the live bot rather than a replacement for it.
