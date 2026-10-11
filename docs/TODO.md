# Production Trading Bot TODO

This backlog turns the earlier strategic suggestions into an executable engineering plan for this repository.

## Implementation roadmap

### Phase 0: Immediate / now (1-2 weeks)

These are the highest-value changes to make the bot safer, more operationally sane, and more testable before adding more trading complexity.

#### 1. Hard risk controls
- [x] Add portfolio-level risk limits in `pumpfun_trading/bot/run.py`
  - [x] max total exposure
  - [x] max active positions
  - [x] per-token concentration cap
  - [x] max daily drawdown
  - [x] max loss per trade
- [x] Add account equity guard before opening new positions
- [x] Add kill-switch if wallet balance falls below reserve
- [x] Add kill-switch if API/WebSocket health is stale
- [x] Add risk budget object to the bot config layer in `pumpfun_trading/bot/strategy.py`

#### 2. Cleaner execution lifecycle
- [x] Add explicit state machine for `idle -> monitoring -> buying -> holding -> selling -> shutdown`
- [x] Record exit reasons for each position (`take_profit`, `stop_loss`, `manual`, `stale_data`, `risk_kill`)
- [x] Persist recent actions in memory + optional disk-backed audit log
- [x] Add a structured trade ledger object for `position_id`, `mint`, `entry`, `exit`, `reason`, `timestamp`

#### 3. Better bot health and monitoring
- [x] Add metrics collection for: buys, sells, failures, retries, connection loss, stale data, latency
- [x] Add alert hooks for Discord/Slack/Telegram
- [x] Keep health check panel in terminal dashboard separate from log stream
- [x] Add a local `bot_status.json` snapshot file for restart recovery and debugging

#### 4. Audit trail investigation and forensic tooling
- [x] Add a dedicated audit-search CLI/tooling entry point under `pumpfun_trading/cli.py` or a new subcommand
- [x] Implement audit log search and filtering by:
  - record type
  - state
  - date / time window
  - mint address
  - token name / display name
  - trade reason (`take_profit`, `stop_loss`, `risk_kill`, etc.)
  - status / outcome (`success`, `failed`, `skipped`, `pending`)
- [x] Add summary and aggregation output for recent trades, failures, and state transitions
- [x] Add JSON and table output modes for quick inspection and automation
- [x] Add export / review helpers for incident analysis and debugging
- [x] Add tests for audit query filtering and CLI parsing

#### 5. Test coverage for safety-critical paths
- [x] Add unit tests for position sizing guard logic
- [x] Add tests for kill-switch conditions
- [x] Add tests for name resolution and active-position metadata
- [x] Add tests for failed API and failed websocket handling
- [x] Expand `pumpfun_trading/tests/` with risk and lifecycle tests

### Phase 1: Near-term improvements (2-4 weeks)

These improvements are about making the bot behave more like a real trading system rather than a launch monitor.


#### 6. Better execution quality
- [x] Add slippage tolerance handling in `pumpfun_trading/sdk/execution.py`
- [x] Add partial fill handling and re-evaluation logic
- [x] Add retry/backoff logic for transient RPC failures
- [x] Add transaction queue and execution lock to avoid overlapping actions
- [x] Add execution health scoring and failure classification


#### 7. Backtesting and replay foundation
- [x] Create a replay / simulation module under `pumpfun_trading/` for historical token data
- [x] Add a `PaperTradingEngine` that executes trades against stored market snapshots
- [x] Add realistic fee and slippage assumptions in simulation
- [x] Add a simple CLI command to run historical replay from a stored dataset
- [x] Add output metrics: profit factor, max drawdown, win rate, average trade return

#### 8. Persistent state and crash recovery
- [x] Add state persistence for open positions and metadata
- [x] Save last-seen mints and recent decisions to disk
- [x] Restore position state on bot startup
- [x] Add an event journal to support debugging and replay
- [x] Add safe startup routine that validates persisted state before resuming

#### 9. Runtime modularization and release-readiness
- [x] Split `pumpfun_trading/bot/run.py` into smaller modules for:
  - runtime orchestration
  - state machine / lifecycle management
  - risk controls and guard checks
  - event and audit record handling
  - execution builders / trade actions
  - terminal dashboard rendering
- [x] Introduce a clear API boundary between runtime orchestration and execution helpers so the bot is easier to test and extend
- [x] Add release gating criteria for a first public version:
  - safety checks pass in dry-run mode
  - risk limits and kill-switches are verified
  - audit trail is searchable and reviewable
  - core bot lifecycle is exercised in tests
  - [x] wallet and env configuration are documented
- [x] Define a first-release milestone / cutover checkpoint before Phase 1 strategy expansion
- [x] Add a dedicated sprint for runtime decomposition and release-readiness before broader strategy work

### Phase 2: Medium-term roadmap (1-2 months)

These changes turn the bot into a more serious production trading system.


#### 10. Add strategy modularity
- [x] Split strategy logic into:
  - signal generation
  - filter evaluation
  - risk validation
  - execution planning
  - exit evaluation
- [x] Create a `Strategy` protocol or base class
- [x] Add at least 2-3 strategy presets with different risk profiles
- [x] Add clean configuration objects for each preset
- [x] Move strategy logic out of the monolithic bot runtime into `pumpfun_trading/strategies/`
- [x] Add tests covering each strategy module and integration with the bot runtime

#### 11. Improve market data access
- [x] Add richer data fetches in `pumpfun_trading/api/client.py`
  - liquidity snapshots
  - volume history
  - holder counts
  - token age / supply data
- [x] Add data freshness checks before using a signal
- [x] Add fallback metadata paths when API endpoint fails
- [x] Add rate-limit and timeout handling in the client layer
- [x] Add provider / endpoint fallback logic for degraded market data availability
- [x] Add tests for stale data, fallback handling, and timeout/retry paths

### Phase 3: Long-term / production hardening (2+ months)

#### 12. Production reliability and ops
- [x] Add structured logging with timestamps, component names, and trade IDs
- [x] Add operational dashboard for health, risk, and performance
- [x] Add alerts for missed trades, stale data, broken RPCs, failed signatures
- [x] Add runbook for startup, shutdown, restart, and emergency stop
- [x] Document wallet secret management and secure deployment process

#### 13. Security and compliance
- [x] Move secrets to proper secret store (env injection, key vault, etc.)
- [x] Separate hot wallet and treasury wallet logic
- [x] Add wallet authentication checks before trade submission
- [x] Add transaction review and approval workflow for critical actions
- [x] Add audit log retention and periodic review

#### 14. Real strategy evaluation
- [x] Build historical benchmark set across multiple market conditions
- [x] Run walk-forward validation and out-of-sample testing
- [x] Require minimum strategy test thresholds before live use
- [x] Compare strategies using risk-adjusted metrics, not just raw profit

### Phase 4: High-Alpha Execution, Strategy Expansion & Enterprise Infrastructure (Post-v1 Alpha Expansion)

These enhancements build upon the hardened production v1 core to maximize risk-adjusted profit factor, eliminate frontrunning leakage, reduce execution latency to sub-second slots, and protect capital through multi-layered heuristic safety and failover controls.

#### 15. Sub-millisecond On-Chain Streaming & Geyser Integration (FEAT-01)
- [ ] Implement Solana Geyser (Yellowstone gRPC) client integration in `pumpfun_trading/streams/geyser.py`
  - [ ] Configure bidirectional gRPC streaming connection with automated keepalive and channel reconnection
  - [ ] Subscribe to transaction notifications targeting Pump.fun Program ID (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`)
  - [ ] Subscribe to real-time account data updates for active bonding curves
- [ ] Add zero-copy binary parser for Pump.fun Bonding Curve state:
  - [ ] Extract `virtualTokenReserves`, `virtualSolReserves`, `realTokenReserves`, `realSolReserves`, and `complete`
  - [ ] Decode on-chain trade events directly from instruction inner data
- [ ] Wire Geyser event emitter directly into the bot runtime event loop, bypassing REST/WebSocket polling delays
- [ ] Implement latency telemetry benchmarking slot-time vs. execution submission timestamp

#### 16. Private Mempool MEV Bundling & Anti-Sandwich Protection (FEAT-02)
- [ ] Implement Jito Block Engine JSON-RPC bundle client in `pumpfun_trading/sdk/jito.py`
  - [ ] Fetch dynamic tip floor percentiles (25th, 50th, 75th, 95th) from Jito tip stream API
  - [ ] Rotate active Jito validator tip recipient accounts dynamically
- [ ] Build atomic Jito bundles:
  - [ ] Pack Compute Budget instructions + Buy/Sell Instruction + Validator Tip Transfer into an atomic bundle
  - [ ] Set exact tip amounts scaled by trade size and signal conviction score
  - [ ] Submit bundle via `sendBundle` endpoint (`https://mainnet.block-engine.jito.wtf`)
- [ ] Implement bundle confirmation tracker and fallback routing:
  - [ ] Poll bundle status via `getBundleStatuses`
  - [ ] Implement fast fallback to high-priority direct RPC submission if bundle times out across slot boundaries
- [ ] Add anti-sandwich validation unit tests and simulation mocks

#### 17. Dynamic Trailing Exits & Multi-Tier Take-Profit Scaling (FEAT-03)
- [ ] Expand position tracking data model in `pumpfun_trading/bot/risk.py` and `pumpfun_trading/strategies/exits.py`:
  - [ ] Track `peak_price`, `peak_return_pct`, `trailing_stop_active`, and remaining position lots
  - [ ] Maintain realized exit tiers (`tier_1_executed`, `tier_2_executed`, `moonbag_active`)
- [ ] Implement multi-tier take-profit scale-out engine:
  - [ ] Tier 1: Liquidate 50% position quantity at +100% gain (`2.0x` initial entry price) to recover initial SOL principal
  - [ ] Tier 2: Liquidate 25% position quantity at +250% gain (`3.5x` initial entry price)
  - [ ] Tier 3 (Moonbag): Retain remaining 25% position with trailing stop pegged at +150% gain (`2.5x`)
- [ ] Implement dynamic trailing stop-loss logic:
  - [ ] Activate trailing stop once unrealized return exceeds activation threshold (+50%)
  - [ ] Trigger immediate exit if market price declines by `X%` (configurable, default 15%) below observed `peak_price`
- [ ] Add unit tests and historical replay validation for tiered scaling and trailing stop exits

#### 18. Rug-Pull, Honeypot & Dev-Dumping Heuristic Screening (FEAT-04)
- [ ] Implement pre-trade token screening pipeline in `pumpfun_trading/strategies/filters.py`:
  - [ ] **Dev Wallet Profiling:** Query creator historical token deployment records; reject creators with >5 launched tokens in preceding 24 hours
  - [ ] **Creator Initial Holding Limit:** Reject tokens where creator account purchased >10% of total supply in the creation block
  - [ ] **Top Holder Concentration Metric:** Calculate Gini coefficient and verify top 5 non-bonding-curve wallets hold <15% of circulating supply
  - [ ] **Metadata & Socials Verification:** Parse token metadata JSON URI; enforce presence of valid Twitter/X, Telegram, or website links
- [ ] Add risk score penalty weighting to reject high-risk launches automatically
- [ ] Implement screening caching layer (TTL: 60 seconds) to prevent redundant RPC calls on active tokens
- [ ] Add test suite with mock rug-pull and honeypot token metadata

#### 19. Raydium Migration Sniping & Graduation Momentum (FEAT-05)
- [ ] Implement bonding curve graduation monitor in `pumpfun_trading/strategies/signal.py`:
  - [ ] Track SOL reserve accumulation approaching threshold (~85 SOL / $69k market cap completion)
  - [ ] Detect bonding curve state transition `complete == True` in real-time
- [ ] Implement Raydium migration listener:
  - [ ] Monitor Solana transaction stream for Raydium AMM Program ID (`675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8`) `CreatePool` / `Initialize2` instructions
  - [ ] Extract initialized AMM pool address, base mint, and quote mint
- [ ] Build Raydium AMM swap execution builder in `pumpfun_trading/sdk/execution.py`
- [ ] Add momentum entry logic with high compute priority fee to capture post-migration liquidity surge
- [ ] Add simulation tests for graduation detection and AMM pool parsing

#### 20. Smart Money Tracking & Copy-Trading Engine (FEAT-06)
- [ ] Create wallet tracking repository and configuration in `pumpfun_trading/strategies/copy_trading.py`:
  - [ ] Support static address list and dynamic performance-ranked trader database
  - [ ] Store historical win rate, average return, and risk score per tracked wallet
- [ ] Implement real-time transaction mirror listener:
  - [ ] Stream incoming transactions for tracked wallets via Geyser or WebSocket filters
  - [ ] Parse token mint, transaction direction (buy/sell), and SOL capital committed
- [ ] Implement proportional position sizing and risk validation:
  - [ ] Scale trade sizing relative to bot equity vs. tracked wallet bankroll
  - [ ] Verify token passes all standard risk filters and concentration caps before executing mirrored buy
  - [ ] Trigger mirrored sell when tracked wallet closes or reduces position
- [ ] Add copy-trading unit tests and replay simulation harness

#### 21. Real-Time Order Flow & Trade Velocity Momentum Signals (FEAT-07)
- [ ] Implement rolling order flow analytics engine in `pumpfun_trading/strategies/momentum.py`:
  - [ ] Maintain sliding time windows (15s, 30s, 60s) of buy and sell transactions per token
  - [ ] Compute real-time `Buy Volume / Sell Volume` ratio and `Net SOL Inflow`
  - [ ] Track `Unique Buyer Count` and `Trade Velocity` (transactions per second)
- [ ] Implement statistical anomaly detection:
  - [ ] Compute moving average and standard deviation of trade velocity
  - [ ] Generate momentum entry trigger when trade velocity Z-score > 2.5 and buy ratio > 3.0
- [ ] Add integration with existing `Strategy` decision pipeline and paper-trading engine
- [ ] Add unit tests verifying order flow sliding window math and Z-score triggers

#### 22. Multi-RPC Dynamic Load Balancing & Latency-Based Failover (FEAT-08)
- [ ] Implement multi-provider RPC connection pool in `pumpfun_trading/infra/rpc_pool.py`:
  - [ ] Support simultaneous RPC endpoints (e.g. Helius, QuickNode, Triton, Shyft, standard cluster)
  - [ ] Perform background health checks and rolling latency measurements (p50, p95, p99)
- [ ] Implement intelligent query routing:
  - [ ] Route state reads and account queries to endpoint with lowest rolling latency
  - [ ] Implement automatic circuit breaking on HTTP 429 (rate limit) or 5xx errors
- [ ] Implement multi-RPC transaction broadcast:
  - [ ] Concurrently broadcast signed transactions across all healthy RPC endpoints to maximize validator inclusion probability
- [ ] Add comprehensive test suite covering RPC failover, latency scoring, and broadcast deduplication

#### 23. Portfolio Equity Loss Limits & Automated Daily Circuit Breaker (FEAT-09)
- [ ] Expand risk engine in `pumpfun_trading/bot/risk.py`:
  - [ ] Track daily baseline starting equity (reset at 00:00 UTC)
  - [ ] Track real-time cumulative daily realized and unrealized PnL
- [ ] Implement portfolio hard-stop circuit breaker:
  - [ ] Configure `max_daily_drawdown_pct` (default: 15% of starting equity)
  - [ ] If daily drawdown breaches threshold, engage emergency hard lock:
    - [ ] Immediately cancel all pending buy orders
    - [ ] Liquidate all open positions via aggressive exit orders
    - [ ] Pause new trading operations for 24 hours or until operator manual reset
  - [ ] Emit emergency alert notifications (Discord, Telegram, Slack) and record audit log event
- [ ] Add unit tests simulating severe market drops and verifying portfolio lock engagement

#### 24. Web Management Portal & Mobile Telegram Command Bot (FEAT-10)
- [ ] Implement Telegram interactive control bot in `pumpfun_trading/ui/telegram_bot.py`:
  - [ ] Command handlers: `/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/sell_all`, `/config`
  - [ ] Authenticated user whitelist and admin token verification
  - [ ] Push instant notifications on trade executions, trailing stop triggers, and risk alerts
- [ ] Implement lightweight FastAPI / WebSockets dashboard in `pumpfun_trading/ui/web/`:
  - [ ] Real-time portfolio equity curves, active position table, and audit trail stream
  - [ ] Dynamic risk parameter adjustment without requiring bot process restart
- [ ] Add integration tests verifying Telegram command authorization and Web UI state streaming

## Repo-specific work items

### `pumpfun_trading/bot/`
- [x] Split runtime responsibilities into dedicated modules: `run.py`, `lifecycle.py`, `risk.py`, `health.py`, `audit.py`, and `strategy.py`
- [x] Keep orchestration logic separate from execution and presentation concerns
- [x] Add a clear distinction between state transitions, guard checks, and audit/event handling
- [x] Remove stale root-level compatibility modules after refactor cleanup
- [ ] Continue narrowing runtime responsibilities as the bot grows, with explicit module boundaries retained

### `pumpfun_trading/strategies/`
- [x] Create a dedicated strategy package under `pumpfun_trading/strategies/`
- [x] Define a `Strategy` protocol or base class for shared signal and exit hooks
- [x] Split strategy logic by concern: signal generation, filter evaluation, risk validation, execution planning, and exits
- [x] Move reusable preset configuration out of the bot runtime into the strategy package
- [x] Add tests for each strategy component and integration with the runtime decision path

### `pumpfun_trading/cli/`
- [x] Add dedicated CLI entrypoints for bot, audit, and replay workflows under `pumpfun_trading/cli/`
- [x] Split command responsibilities so each script is purpose-specific instead of overloading a single `pumpbot` entrypoint
- [x] Move replay-related command logic into `cli/replay.py` and `engines/replay.py`
- [x] Keep command packaging aligned with the refactor target layout in `docs/REFACTOR.md`
- [ ] Expand CLI docs and examples for operators as release tooling matures

### `pumpfun_trading/engines/`
- [x] Move replay and historical evaluation logic into the `engines/` package namespace
- [x] Keep engine logic separate from live runtime execution and terminal rendering
- [x] Add reusable replay entrypoints and execution summary output
- [ ] Add additional simulation/backtest modes when strategy evaluation matures

### `pumpfun_trading/ui/`
- [x] Isolate dashboard rendering under `pumpfun_trading/ui/`
- [x] Keep terminal display code separate from the core runtime lifecycle and trade logic
- [ ] Expand the dashboard to cover more operational health and performance metrics over time

### `pumpfun_trading/api/client.py`
- [x] Add quality checks for API payloads and metadata freshness
- [x] Add fallback request paths for 4xx/5xx or missing data
- [x] Add timeouts, retry logic, and circuit-break behavior
- [x] Add richer market data fetches and provider fallback logic
- [x] Add methods for richer token data needed by signal quality filters

### `pumpfun_trading/sdk/execution.py`
- [x] Add execution health checks
- [x] Add slippage and fee validation
- [x] Add transaction queue or lock to prevent duplicate sends
- [x] Add safer confirmation handling and error classification

### `pumpfun_trading/bot/strategy.py`
- [x] Expand strategy config with risk limits and signal thresholds
- [x] Add strategy presets with different risk profiles
- [x] Add scoring thresholds and cooldown logic
- [x] Migrate the canonical strategy config and decision helpers into the dedicated `pumpfun_trading/strategies/` package

### `pumpfun_trading/tests/`
- [x] Add tests for risk limit enforcement
- [x] Add tests for state restoration and restart recovery
- [x] Add tests for audit CLI and audit filtering workflows
- [x] Add tests for replay and package-level runtime integration
- [x] Add tests for API fallback behavior
- [x] Add tests for execution failure paths and retry logic
- [x] Add strategy-module unit tests for signal generation, filters, risk checks, and exits
- [x] Add tests for strategy scoring and buy filters
- [ ] Add unit and mock integration tests for Yellowstone Geyser gRPC streaming and binary bonding curve parsing
- [ ] Add tests for Jito tip calculations, bundle packing, and fallback RPC routing
- [ ] Add tests for dynamic trailing stop and multi-tier partial exit calculations
- [ ] Add tests for dev wallet screening, holder concentration limits, and metadata verification filters
- [ ] Add tests for Raydium AMM graduation detection and pool initialization parsers
- [ ] Add tests for smart money copy-trading signal extraction and proportional position sizing
- [ ] Add tests for rolling order flow window aggregations and trade velocity Z-score anomalies
- [ ] Add tests for multi-RPC latency scoring, health checks, failover routing, and broadcast deduplication
- [ ] Add tests for daily equity baseline tracking, drawdown limits, and portfolio emergency lock triggers
- [ ] Add tests for Telegram command authentication and FastAPI/WebSocket status streaming

### `pumpfun_trading/streams/` (Geyser & On-Chain Event Ingestion)
- [ ] Create Yellowstone gRPC streaming client module with auto-reconnection and exponential backoff
- [ ] Implement zero-copy binary parser for Pump.fun bonding curve account data and swap instruction events
- [ ] Implement event pipeline routing parsed updates directly into bot state and strategy decision loops
- [ ] Add slot-level latency metrics and dropped message counters

### `pumpfun_trading/sdk/` & `pumpfun_trading/execution/`
- [ ] Implement Jito JSON-RPC bundle client with tip account rotation and dynamic fee percentile estimation
- [ ] Implement atomic bundle packaging for buy/sell instructions + compute budget + validator tip transfer
- [ ] Add Raydium AMM pool swap instruction builder for post-graduation liquidity trades
- [ ] Implement bundle status polling with fallback fast-path execution on bundle timeouts

### `pumpfun_trading/filters/` & `pumpfun_trading/strategies/`
- [ ] Implement pre-trade screening pipeline: dev wallet history, creator supply cap (<10%), top 5 holder cap (<15%), and social links
- [ ] Implement dynamic trailing stop-loss (activation at +50%, trail drop 15%) and multi-tier profit taking (50% at 2x, 25% at 3.5x, 25% moonbag)
- [ ] Implement Raydium migration monitor tracking curve completion and AMM pool initialization
- [ ] Implement smart money copy-trading module with wallet performance ranking and proportional sizing
- [ ] Implement order flow momentum strategy computing rolling buy/sell volume ratios, buyer counts, and trade velocity Z-scores

### `pumpfun_trading/infra/` & `pumpfun_trading/ops/`
- [ ] Implement multi-provider RPC connection pool with health probes and latency-based read routing
- [ ] Implement multi-RPC transaction broadcast engine for simultaneous validator dispatch
- [ ] Implement portfolio-level daily equity loss tracker and 24-hour hard-lock circuit breaker (liquidate all & pause on >15% daily drawdown)
- [ ] Add alerting dispatchers for emergency circuit breakers, liquidation events, and RPC degradation

### `pumpfun_trading/ui/`
- [ ] Implement Telegram interactive bot for remote commands (`/status`, `/positions`, `/sell_all`, `/pause`, `/resume`, `/pnl`)
- [ ] Implement FastAPI / WebSockets web dashboard for real-time portfolio visualization and hot config updates
- [ ] Expand terminal dashboard to display active RPC latencies, Jito bundle status, and Geyser stream health

## Suggested sprint plan

### Sprint 1: Safe running bot
- [x] risk limits
- [x] kill-switches
- [x] trade ledger
- [x] health monitoring
- [x] test coverage for safety logic

### Sprint 2: Audit trail investigation and forensic tooling
- [x] audit log search and filtering CLI
- [x] record-type, state, mint, date, name, and reason filters
- [x] JSON + table output and summary views
- [x] export helpers for incident review

### Sprint 3: Runtime decomposition and first-release gate
- [x] split bot runtime into orchestrator, lifecycle, risk, audit, execution, dashboard modules
- [x] define release-gating checklist for v1
- [x] dry-run safety validation and environment documentation
- [x] ensure audit trail is searchable and reviewable before public release

### Sprint 4: Strategy modularity and decision pipeline
- [x] split strategy logic into signal generation, filtering, risk validation, execution planning, and exits
- [x] create a shared strategy base / protocol
- [x] move preset config and strategy-specific helpers into `pumpfun_trading/strategies/`
- [x] unit test each strategy component and runtime integration path

### Sprint 5: Market data quality and resilience
- [x] richer market data fetches
- [x] stale-data detection and freshness checks
- [x] fallback metadata paths and provider resilience
- [x] rate-limit and timeout handling
- [x] market-data tests for degraded and failed responses

### Sprint 6: Replay and validation
- [x] backtesting engine
- [x] paper-trading mode
- [x] historical replay and metrics
- [x] strategy comparisons

### Sprint 7: Production readiness
- [x] persistence and restoration
- [x] alerting and observability
- [x] security hardening
- [x] operational playbook and deployment checklist

### Sprint 8: Operational scale and resilience
- [x] broader monitoring stack
- [x] deployment hardening
- [x] incident response runbooks
- [x] ongoing performance tuning

### Sprint 9: Ultra-Low Latency Ingestion & Anti-MEV Bundling
- [ ] Integrate Yellowstone Geyser gRPC streaming client for sub-second bonding curve creation and swap detection (FEAT-01)
- [ ] Implement zero-copy binary parser for bonding curve reserves and on-chain swap events
- [ ] Integrate Jito Block Engine bundle client with dynamic tip estimation and validator tip rotation (FEAT-02)
- [ ] Implement atomic transaction bundling to eliminate sandwich attacks and toxic MEV leakage
- [ ] Add bundle confirmation polling with automatic fallback routing to direct RPC
- [ ] Add unit and integration tests for gRPC streaming, binary account decoding, and Jito bundle submission

### Sprint 10: Dynamic Exits & Scam Protection Filters
- [ ] Implement dynamic trailing stop-loss engine with configurable activation threshold and trailing drop percentage (FEAT-03)
- [ ] Implement multi-tier take-profit scaling (50% exit at 2.0x, 25% exit at 3.5x, 25% trailing moonbag) (FEAT-03)
- [ ] Implement dev wallet historical deployment analysis and serial rugger rejection filter (FEAT-04)
- [ ] Implement creator initial holding cap (<10%) and top 5 holder supply concentration (<15%) filters (FEAT-04)
- [ ] Implement token metadata URI parsing and social media link presence validation (FEAT-04)
- [ ] Add unit tests and historical replay validation for tiered exits and anti-scam heuristic filters

### Sprint 11: Order Flow Momentum & Graduation Sniping
- [ ] Implement sliding window order flow analytics computing buy/sell volume ratios and net SOL inflow (FEAT-07)
- [ ] Implement trade velocity tracker and Z-score anomaly detector for momentum entry triggers (FEAT-07)
- [ ] Implement bonding curve completion monitor tracking SOL reserve threshold (~85 SOL / $69k cap) (FEAT-05)
- [ ] Implement Raydium AMM pool initialization listener (`CreatePool`/`Initialize2`) and swap execution builder (FEAT-05)
- [ ] Integrate momentum and graduation signals into modular strategy decision engine
- [ ] Add unit and replay simulation tests for order flow velocity metrics and Raydium migration sniping

### Sprint 12: Smart Money Copy-Trading & High-Availability Infrastructure
- [ ] Create smart money wallet tracking registry with historical win rates and performance ranking (FEAT-06)
- [ ] Implement real-time transaction mirror listener with proportional position sizing and risk validation (FEAT-06)
- [ ] Implement multi-provider RPC connection pool with latency-based query routing (FEAT-08)
- [ ] Implement multi-RPC concurrent transaction broadcast engine for high-reliability validator inclusion (FEAT-08)
- [ ] Implement automatic RPC rate-limit circuit breaking and failover fallback logic (FEAT-08)
- [ ] Add unit and integration tests for copy-trading trade mirroring and multi-RPC connection pooling

### Sprint 13: Enterprise Circuit Breakers & Remote Management
- [ ] Implement real-time daily baseline equity tracking and cumulative realized/unrealized PnL monitoring (FEAT-09)
- [ ] Implement portfolio hard-stop circuit breaker: emergency order cancellation, position liquidation, and 24-hour pause on >15% drawdown (FEAT-09)
- [ ] Implement interactive Telegram bot for remote monitoring and mobile trade management (`/status`, `/positions`, `/sell_all`, `/pause`, `/resume`) (FEAT-10)
- [ ] Implement lightweight FastAPI / WebSockets dashboard for live portfolio streaming and hot configuration updates (FEAT-10)
- [ ] Add comprehensive test suites for circuit breaker liquidation flows, Telegram command security, and Web UI endpoints

## Definition of done for a “serious” bot

The bot is production-worthy and alpha-ready when it can:
- safely manage risk at the portfolio level with automated equity circuit breakers
- stop trading instantly when health, risk, or daily drawdown thresholds fail
- ingest market events with sub-millisecond latency via on-chain Geyser gRPC streams
- execute transactions via private Jito bundles to eliminate toxic MEV sandwiching
- screen out scams, dev dumps, and honeypots using multi-layer heuristic filters
- scale out profits dynamically using multi-tier take-profits and trailing stop-losses
- capture momentum from order flow velocity spikes and Raydium graduation events
- track and mirror proven smart money wallets with proportional risk budgeting
- maintain 99.99% operational uptime via multi-RPC latency pooling and failover
- replay and validate all strategy decisions against historical datasets
- recover smartly after restarts with verified state reconciliation
- maintain a clear, queryable audit ledger and provide remote mobile control via Telegram/Web
- demonstrate consistent risk-adjusted returns (Sharpe ratio > 2.0, Profit Factor > 1.8) across diverse market regimes

## Notes

This repo has established a solid, modular, and fully tested production v1 foundation. Phase 4 directs engineering focus toward maximizing capital efficiency, capturing high-alpha market opportunities, eliminating execution leakage, and hardening infrastructure for institutional reliability.
