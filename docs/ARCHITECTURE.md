# Architecture

trading-pump is a trading-core module. trading-core owns the run (the loop,
sizing, risk, the circuit breaker, exits, accounting, persistence, alerts,
the dashboard, the audit tools); this package owns everything that knows
Solana, Pump.fun and PumpSwap. The contract between the two is trading-core's
`docs/MODULE-GUIDE.md`.

## 1. How the module meets the contract

| `TradingModule` | `PumpModule` (`module.py`) |
|---|---|
| `name`, `quote` | `"pumpfun"`; SOL, 9 decimals, µSOL for prices |
| `start(host)` / `stop()` | Opens the capture, records unread-variable warnings, starts the migration feed and the pool poller as tasks; `stop` ends both and flushes the capture |
| `get_quote(id)` | The latest pool reading, re-read when older than `quote_max_age_seconds`; bid / ask = price ∓ the swap fee; stale (`QuoteUnavailable`) when the read fails or the pool is drained |
| `get_balance()` | Wallet SOL via `getBalance` (live); raises without a key or a balance (BUG-158) |
| `execute(order, paper=)` | `PaperExecutor` (pool-priced fills, every cost) or `LiveExecutor` (refuses until the live gate) |
| `exit_value(position, quote)` | The SOL a sell of the position would return after the fee (BUG-136) |
| `pipeline()` | `graduations → standard_pool → [anti_rug] → momentum` (`strategies/pumpswap_momentum.py`), or none when the lane is off |
| `format_price`, `status_rows`, `strategy_rows` | µSOL prices; feed, graduates, pool reads, RPC, capture rows; the lane's rule |
| `provenance()` | Lane, graduation and execution settings, capture path, RPC endpoint count, fees seen |
| `is_public_identifier` | Solana public keys (mints, pools) are public, not secrets |
| host callbacks | `notify_market_data()` on every good pool read; `set_degraded("pumpportal feed" / "solana rpc" / "rpc network", ...)` |
| start-up checks | Every RPC endpoint's genesis hash: an endpoint not on mainnet-beta is dropped, or `rpc network` degraded when none is (BUG-160) |

`module_settings` are validated by `PumpSettings` (`config/settings.py`),
credentials read by `config/env.py`; the two never mix.

## 2. Data flow

```text
PumpPortal subscribeMigration ──> MigrationFeed (feed.py) ──> GraduateTracker (graduates.py)
                                                                  │  follows each pool 4 h
                       PoolPoller (feed.py) <─────── due mints ───┘
                            │ batch reads (RpcPoolSource, market.py → sdk.get_pumpswap_pool_states)
                            ├──> PoolReading per pool ──> tracker.update ──> capture rows (recorder.py)
                            └──> host.notify_market_data / set_degraded
TradingEngine cycle ──> pipeline: GraduationScout → StandardPoolFilter → MomentumAnalyst ──> Signal
                    ──> risk gate ──> PumpModule.execute ──> PaperExecutor (fresh pool read, fee, costs) ──> Fill
                    ──> marks and exits: get_quote / exit_value ──> sell ──> Fill (rent refunded on the full exit)
```

Replay (`replay.py`) replaces the feed with the capture's migrations and the
pool source with `CapturePoolSource`, and drives the same engine and module
on a `ReplayClock`.

## 3. Package layout

```text
trading_pump/
├── module.py            # PumpModule: the TradingModule implementation
├── market.py            # PoolReading, SwapFee, pool maths, RpcPoolSource
├── graduates.py         # GraduateTracker: who is followed, readings, capture rows
├── feed.py              # MigrationFeed (PumpPortal) and PoolPoller
├── execution.py         # PaperExecutor, LiveExecutor, Holdings
├── replay.py            # capture playback through the engine
├── recorder.py          # ReplayRecorder: the capture file (core RotatedFileSink)
├── identifiers.py       # is_solana_pubkey (registered with core redaction)
├── config/              # env.py (credentials only), settings.py (PumpSettings)
├── strategies/          # pumpswap_momentum (the lane), filters / enrichment / cluster (screening), observation
├── sdk/                 # curve and PumpSwap maths, fee config, transaction builders, costs, Jito, transport
├── infra/rpc_pool.py    # multi-endpoint RPC pool with breaker and failover
├── api/client.py        # Pump.fun public API
├── streams/websocket.py # PumpPortal WebSocket host (reconnect, pings, key handling)
├── services/            # slow_lane (FEAT-65); the FEAT-74 market recorder moved to trading-scout
├── cli/                 # trading-pump (main.py), the recorders (record.py)
└── tests/               # unit/ (mirrors the source), integration/, property/, support/
```

Boundaries kept from pumpfun-trading: streaming and decoding stay in
`streams/`; on-chain maths and transaction building in `sdk/`; strategy
decisions and screening in `strategies/`; CLI handlers delegate to library
functions. Nothing in this package renders a dashboard or owns risk.

## 4. Decisions

The migration's decisions are recorded in
[dev/ARCHITECTURE-DECISIONS.md](dev/ARCHITECTURE-DECISIONS.md) (ADR-009):
why the venue layer was ported and the lanes rebuilt, why credentials are
environment-only, why the capture keeps pumpfun-trading's row shape, and why
live execution waits.
