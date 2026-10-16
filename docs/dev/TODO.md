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
- [x] Add a dedicated audit-search CLI/tooling entry point (now `pumpfun_trading/cli/audit.py` / `pumpfun-audit`)
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
- [x] Implement modern Pump.fun `BuyV2` (27 accounts) and `SellV2` (26 accounts) on-chain instruction architecture
- [x] Add dynamic Token-2022 vs SPL Token program resolution (`get_token_program_for_mint`)
- [x] Derive on-chain volume accumulators, fee program `fee_config` PDAs, and creator vaults from bonding curve state (`data[49:81]`)


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
- [x] Implement Solana Geyser (Yellowstone gRPC) client integration in `pumpfun_trading/streams/geyser.py`
  - [x] Configure bidirectional gRPC streaming connection with automated keepalive and channel reconnection
  - [x] Subscribe to transaction notifications targeting Pump.fun Program ID (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`)
  - [x] Subscribe to real-time account data updates for active bonding curves
- [x] Add zero-copy binary parser for Pump.fun Bonding Curve state:
  - [x] Extract `virtualTokenReserves`, `virtualSolReserves`, `realTokenReserves`, `realSolReserves`, and `complete`
  - [x] Decode on-chain trade events directly from instruction inner data
- [x] Wire Geyser event emitter directly into the bot runtime event loop, bypassing REST/WebSocket polling delays
- [x] Implement latency telemetry benchmarking slot-time vs. execution submission timestamp

#### 16. Private Mempool MEV Bundling & Anti-Sandwich Protection (FEAT-02)
- [x] Implement Jito Block Engine JSON-RPC bundle client in `pumpfun_trading/sdk/jito.py`
  - [x] Fetch dynamic tip floor percentiles (25th, 50th, 75th, 95th) from Jito tip stream API
  - [x] Rotate active Jito validator tip recipient accounts dynamically
- [x] Build atomic Jito bundles:
  - [x] Pack Compute Budget instructions + Buy/Sell Instruction + Validator Tip Transfer into an atomic bundle
  - [x] Set exact tip amounts scaled by trade size and signal conviction score
  - [x] Submit bundle via `sendBundle` endpoint (`https://mainnet.block-engine.jito.wtf`)
- [x] Implement bundle confirmation tracker and fallback routing:
  - [x] Poll bundle status via `getBundleStatuses` and `getInflightBundleStatuses`
  - [x] Implement fast fallback to high-priority direct RPC submission if bundle times out across slot boundaries
- [x] Add anti-sandwich validation unit tests and simulation mocks

#### 17. Dynamic Trailing Exits & Multi-Tier Take-Profit Scaling (FEAT-03)
- [x] Expand position tracking data model in `pumpfun_trading/bot/risk.py` and `pumpfun_trading/strategies/exits.py`:
  - [x] Track `peak_price`, `peak_return_pct`, `trailing_stop_active`, and remaining position lots (`PositionExitState`)
  - [x] Maintain realized exit tiers (`tier_1_executed`, `tier_2_executed`, `moonbag_active`)
- [x] Implement multi-tier take-profit scale-out engine in `pumpfun_trading/strategies/exits.py`:
  - [x] Tier 1: Liquidate 50% position quantity at +100% gain (`2.0x` initial entry price) to recover initial SOL principal
  - [x] Tier 2: Liquidate 25% position quantity at +250% gain (`3.5x` initial entry price)
  - [x] Tier 3 (Moonbag): Retain remaining 25% position with trailing stop pegged at +150% gain (`2.5x`)
- [x] Implement dynamic trailing stop-loss logic:
  - [x] Activate trailing stop once unrealized return exceeds activation threshold (+50%)
  - [x] Trigger immediate exit if market price declines by `X%` (configurable, default 15%) below observed `peak_price`
- [x] Add unit tests and historical exit validation for tiered scaling and trailing stop exits (`test_trailing_and_tiered_exits.py`)
- [x] Wire tiered partial order fills into live bot execution loop and on-chain trade reconciler (Stage 2)

#### 18. Rug-Pull, Honeypot & Dev-Dumping Heuristic Screening (FEAT-04)
- [x] Implement pre-trade token screening pipeline in `pumpfun_trading/strategies/filters.py` (Stage 1):
  - [x] **Dev Wallet Profiling:** Query creator historical token deployment records; reject creators with >5 launched tokens in preceding 24 hours
  - [x] **Creator Initial Holding Limit:** Reject tokens where creator account purchased >10% of total supply in the creation block
  - [x] **Top Holder Concentration Metric:** Calculate Gini coefficient and verify top 5 non-bonding-curve wallets hold <15% of circulating supply
  - [x] **Metadata & Socials Verification:** Parse token metadata JSON URI; enforce presence of valid Twitter/X, Telegram, or website links
- [x] Add risk score penalty weighting to reject high-risk launches automatically
- [x] Implement screening caching layer (TTL: 60 seconds) to prevent redundant RPC calls on active tokens
- [x] Add test suite with mock rug-pull and honeypot token metadata (`test_anti_rug_filters.py`)
- [x] Wire heuristic screening directly into live bot buy evaluation and metadata enrichers (Stage 2)
  - [x] Pre-buy screening hook inside Geyser `_handle_bonding_curve_state_update` and `_handle_new_token_event`
  - [x] Token metadata & creator profile enrichment via `PumpFunApiClient.get_coin` and `get_creator_coins`
  - [x] Telemetry reporting of screening verdicts and cache size in status snapshots and operational audit events
  - [x] Comprehensive integration test suite (`test_anti_rug_bot_integration.py`)

#### 19. Comprehensive Project Documentation Overhaul & Markdown Knowledge Hub (FEAT-11)
- [x] Create Operator & User Guide in `docs/USER-GUIDE.md`:
  - [x] System requirements, Python environment setup, and installation steps
  - [x] Environment variable configuration guide (`PUMPFUN_PRIVATE_KEY`, `PUMPFUN_RPC_URL`, `PUMPFUN_GEYSER_ENDPOINT`, `PUMPFUN_USE_JITO`, etc.)
  - [x] Keypair security and non-custodial wallet management best practices
  - [x] Live trading bot launch guide using `pumpbot` (presets, headless mode, dry-run mode)
  - [x] Historical replay backtesting workflow and commands (`pumpfun-replay`)
  - [x] Forensic audit search and log analysis workflows (`pumpfun-audit`)
  - [x] Unified CLI subcommand syntax and complete flag reference table
- [x] Create Strategy & Mathematical Logic Guide in `docs/STRATEGY.md`:
  - [x] Bonding curve constant-product AMM pricing formulas ($P = \Delta y / \Delta x$, virtual vs. real reserves)
  - [x] Candidate eligibility criteria and market cap threshold rules
  - [x] Dynamic trailing stop-loss mathematical model (peak tracking, activation offsets, peak drawdown liquidation)
  - [x] Multi-tier take-profit scale-out mechanics (Tier 1 @ 2.0x, Tier 2 @ 3.5x, Moonbag trailing floor @ 2.5x)
  - [x] Anti-rug and scam heuristic models (Gini coefficient, creator holding penalties, serial deployer thresholds)
  - [x] Preset profiles detailed breakdown (`conservative`, `balanced`, `aggressive`) and customization instructions
- [x] Create Risk Management & Capital Protection Guide in `docs/RISK.md`:
  - [x] Multi-tier risk control hierarchy (order level, position level, portfolio level)
  - [x] Maximum portfolio exposure and active position limits
  - [x] Single-token concentration caps and minimum wallet reserve buffers
  - [x] Rate limits, seen-mint cooldown windows, and stale stream circuit breakers
  - [x] On-chain startup reconciliation and exit retry queue escalation
- [x] Create Terminal UI & Monitoring Manual in `docs/TERMINAL-UI.md`:
  - [x] Dashboard visual layout (Overview, Strategy, Risk, Bot Status, Health Check, Active Positions, Recent Trades)
  - [x] Alternate-screen buffer architecture and `NO_COLOR` compliance
  - [x] Real-time health metrics, slot latency benchmarks, and error classifications
  - [x] Webhook alerting setup and payload schemas for Discord, Slack, and Telegram
- [x] Create Web UI Architecture & Roadmap Specification in `docs/WEB-UI.md`:
  - [x] Specification for the upcoming FastAPI web control portal and WebSocket streaming layer
  - [x] Blueprint for browser-based bot control (start/pause/stop, hot config changes, emergency liquidation)
  - [x] Design for the embedded in-app Markdown documentation viewer and search interface
  - [x] Comparison between the lightweight Terminal UI and the full-featured Web Dashboard
- [x] Standardize and audit `docs/FEATURES.md` ensuring all features carry explicit FEAT identifiers (FEAT-01 through FEAT-20)

#### 20. Portfolio Equity Loss Limits & Automated Daily Circuit Breaker (FEAT-09)
- [x] Expand risk engine in `pumpfun_trading/bot/risk.py`:
  - [x] Track daily baseline starting equity (reset at 00:00 UTC)
  - [x] Track real-time cumulative daily realized and unrealized PnL
- [x] Implement portfolio hard-stop circuit breaker:
  - [x] Configure `max_daily_drawdown_pct` (default: 15% of starting equity)
  - [x] If daily drawdown breaches threshold, engage emergency hard lock:
    - [x] Immediately cancel all pending buy orders
    - [x] Liquidate all open positions via aggressive exit orders
    - [x] Pause new trading operations for 24 hours or until operator manual reset
  - [x] Emit emergency alert notifications (Discord, Telegram, Slack) and record audit log event
- [x] Add unit tests simulating severe market drops and verifying portfolio lock engagement

#### 21. Real-Time Order Flow & Trade Velocity Momentum Signals (FEAT-07)
- [x] Implement rolling order flow analytics engine in `pumpfun_trading/strategies/momentum.py`:
  - [x] Maintain sliding time windows (15s, 30s, 60s) of buy and sell transactions per token
  - [x] Compute real-time `Buy Volume / Sell Volume` ratio and `Net SOL Inflow`
  - [x] Track `Unique Buyer Count` and `Trade Velocity` (transactions per second)
- [x] Implement statistical anomaly detection:
  - [x] Compute moving average and standard deviation of trade velocity
  - [x] Generate momentum entry trigger when trade velocity Z-score > 2.5 and buy ratio > 3.0
- [x] Add integration with existing `Strategy` decision pipeline and paper-trading engine
- [x] Add unit tests verifying order flow sliding window math and Z-score triggers

#### 22. Raydium Migration Sniping & Graduation Momentum (FEAT-05)
- [x] Implement bonding curve graduation monitor in `pumpfun_trading/strategies/graduation.py` and `signal.py`:
  - [x] Track SOL reserve accumulation approaching threshold (~85 SOL / $69k market cap completion)
  - [x] Detect bonding curve state transition `complete == True` in real-time
- [x] Implement Raydium migration listener:
  - [x] Monitor Solana transaction stream for Raydium AMM Program ID (`675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8`) `CreatePool` / `Initialize2` instructions
  - [x] Extract initialized AMM pool address, base mint, and quote mint
- [x] Build Raydium AMM swap execution builder in `pumpfun_trading/sdk/execution.py`
- [x] Add momentum entry logic with high compute priority fee to capture post-migration liquidity surge
- [x] Add simulation tests for graduation detection and AMM pool parsing

#### 23. Smart Money Tracking & Copy-Trading Engine (FEAT-06)
- [x] Create wallet tracking repository and configuration in `pumpfun_trading/strategies/copy_trading.py`:
  - [x] Support static address list and dynamic performance-ranked trader database
  - [x] Store historical win rate, average return, and risk score per tracked wallet
- [x] Implement real-time transaction mirror listener:
  - [x] Stream incoming transactions for tracked wallets via Geyser or WebSocket filters
  - [x] Parse token mint, transaction direction (buy/sell), and SOL capital committed
- [x] Implement proportional position sizing and risk validation:
  - [x] Scale trade sizing relative to bot equity vs. tracked wallet bankroll
  - [x] Verify token passes all standard risk filters and concentration caps before executing mirrored buy
  - [x] Trigger mirrored sell when tracked wallet closes or reduces position
- [x] Add copy-trading unit tests and replay simulation harness

#### 24. Multi-RPC Dynamic Load Balancing & Latency-Based Failover (FEAT-08)
- [x] Implement multi-provider RPC connection pool in `pumpfun_trading/infra/rpc_pool.py`:
  - [x] Support simultaneous RPC endpoints (e.g. Helius, QuickNode, Triton, Shyft, standard cluster)
  - [x] Perform background health checks and rolling latency measurements (p50, p95, p99)
- [x] Implement intelligent query routing:
  - [x] Route state reads and account queries to endpoint with lowest rolling latency
  - [x] Implement automatic circuit breaking on HTTP 429 (rate limit) or 5xx errors
- [x] Implement multi-RPC transaction broadcast:
  - [x] Concurrently broadcast signed transactions across all healthy RPC endpoints to maximize validator inclusion probability
- [x] Add comprehensive test suite covering RPC failover, latency scoring, and broadcast deduplication

#### 25. Core Runtime Decomposition & SOLID Architecture Refactoring (FEAT-12)
- [x] Decompose `TradingBot` in `pumpfun_trading/bot/run.py` to adhere strictly to Python design principles, SOLID, SRP, DRY, OCP, LSP, and ISP
- [x] Extract `PositionManager` in `pumpfun_trading/bot/position_manager.py` to isolate position lifecycles, lot scaling tiers, and trailing stop metrics
- [x] Extract `OrderExecutor` and `OrderLiquidator` in `pumpfun_trading/execution/executor.py` and `liquidator.py` for buy/sell order dispatch and emergency exits
- [x] Extract `TokenEnricher` in `pumpfun_trading/bot/enrichment.py` for anti-rug screening, creator profiling, and Gini holder analysis
- [x] Extract `EventRouter` in `pumpfun_trading/bot/event_router.py` to decouple Geyser/WebSocket stream ingestion from trade execution
- [x] Extract `StatusPersistenceManager` in `pumpfun_trading/bot/persistence.py` and `AlertDispatcher` in `pumpfun_trading/bot/alerts.py`
- [ ] **Re-opened:** Refactor `TradingBot` in `pumpfun_trading/bot/run.py` into a lightweight facade and orchestrator adhering to SRP and OCP
  - The original extraction landed, but `bot/run.py` has since regrown to ~3,770 lines (`__init__` ~500 lines, `_sell_token_locked`, all stream handlers and the WebSocket loop). It is not a lightweight facade. Tracked in **Sprint 28** (Runtime decomposition II).
- [x] Update existing unit and integration test suites to verify complete behavioral equivalence and 100% test pass rate

#### 26. Full-Featured Web Control Dashboard, FastAPI Portal & Mobile Telegram Bot (FEAT-10) — **SUPERSEDED**
> Superseded by Phase 6 (Sprints 32–35) and the re-scoped FEAT-10 umbrella (FEAT-31…37) in [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md). The Telegram bot moved to **FEAT-45** (P3). The FastAPI backend no longer lives in `pumpfun_trading/ui/web/`; it is a separate control plane (see [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md)). Items below are kept for history only.
- [ ] Implement interactive Telegram bot in `pumpfun_trading/ui/telegram_bot.py`:
  - [ ] Remote commands: `/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/sell_all`, `/config`
  - [ ] Admin token and chat ID whitelist verification
  - [ ] Instant push alerts for trade fills, trailing stops, circuit breakers, and errors
- [ ] Implement full-featured FastAPI web backend in `pumpfun_trading/ui/web/`:
  - [ ] REST API and asynchronous WebSockets streaming live state, open positions, and telemetry
  - [ ] Complete operational controls: start, pause, resume, emergency stop, and one-click panic liquidation
  - [ ] Hot strategy and risk configuration mutation without process restarts
  - [ ] Real-time interactive portfolio equity curves, drawdown charts, and order execution latency graphs
  - [ ] Forensic audit search and log viewer interface with JSON export
  - [ ] Embedded in-app Markdown documentation viewer serving all project guides with search and table of contents
- [ ] Add comprehensive integration tests verifying Web UI endpoints, WebSocket streams, and Telegram command authentication

#### 27. Asynchronous Market Stream Recorder & Historical Replay Dataset Generator (FEAT-21)
- [x] Implement non-blocking, asynchronous replay stream recorder in `pumpfun_trading/bot/run.py` & `TradingBotConfig`:
  - [x] Add runtime config flags `--record-replay <path>` and `PUMPFUN_RECORD_REPLAY` / `PUMPFUN_REPLAY_LOG_PATH`
  - [x] Implement background `asyncio.Queue` buffer and batch flusher (e.g. 50–100 records / 5s) to eliminate disk I/O latency contention from live trade execution
  - [x] Filter and record token trajectories, market caps, buy/sell flags, and volume for active bonding curve candidates
- [x] Implement dedicated standalone market data harvester CLI (`pumpfun record` / `pumpfun-recorder`):
  - [x] Stream and serialize Yellowstone Geyser gRPC and WebSocket trade feeds directly into standard JSONL replay datasets without live trading account overhead
- [x] Build synthetic scenario & REST API dataset generators in `pumpfun_trading/engines/generators.py`:
  - [x] Synthetic trajectory generator modeling extreme price dynamics (e.g. 5x surges, flash rugs, flat stagnant curves at 27.96 SOL) for deterministic exit rule stress-testing
  - [x] Historical token trade exporter fetching chronological trades via `PumpFunApiClient` and converting to standard `.jsonl` replay format
- [x] Integrate generated datasets with `pumpfun-replay` / `PaperTradingEngine` and add comprehensive unit test suite (`test_market_recorder.py`)

## Repo-specific work items

### `pumpfun_trading/bot/`
- [x] Split runtime responsibilities into dedicated modules: `run.py`, `lifecycle.py`, `risk.py`, `health.py`, `audit.py`, and `strategy.py`
- [x] Keep orchestration logic separate from execution and presentation concerns
- [x] Add a clear distinction between state transitions, guard checks, and audit/event handling
- [x] Remove stale root-level compatibility modules after refactor cleanup
- [x] Add asynchronous replay recording queue (`replay_log_path`) with non-blocking batched disk flush worker (FEAT-21)
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
- [x] Keep command packaging aligned with the package layout in `AGENTS.md` (the former `docs/REFACTOR.md` target layout has been retired)
- [x] Add `record` subcommand (`pumpfun record`) and `--record-replay` runtime option for headless market harvesting (FEAT-21)
- [ ] Expand CLI docs and examples for operators as release tooling matures

### `pumpfun_trading/engines/`
- [x] Move replay and historical evaluation logic into the `engines/` package namespace
- [x] Keep engine logic separate from live runtime execution and terminal rendering
- [x] Add reusable replay entrypoints and execution summary output
- [x] Add synthetic scenario generation and historical REST dataset exporter modules under `engines/` (FEAT-21)
- [ ] Add additional simulation/backtest modes when strategy evaluation matures

### `pumpfun_trading/ui/`
- [x] Isolate dashboard rendering under `pumpfun_trading/ui/`
- [x] Keep terminal display code separate from the core runtime lifecycle and trade logic
- [ ] Maintain terminal dashboard as a lightweight, zero-dependency console monitor (FEAT-19)
- [ ] ~~Implement Telegram interactive bot~~ — superseded, now FEAT-45 (P3)
- [ ] ~~Implement FastAPI / WebSockets web dashboard in `ui/`~~ — superseded by Phase 6 (Sprints 32–35); the web tier is a separate control plane, `ui/` keeps the terminal dashboard only

### `docs/` (Comprehensive Documentation Architecture)
- [x] Create `docs/USER-GUIDE.md` covering setup, environment configuration, key security, launching `pumpbot`, replay workflows, and CLI flag references (FEAT-11)
- [x] Create `docs/STRATEGY.md` detailing bonding curve math, entry filters, anti-rug heuristics, dynamic trailing stop-loss, and multi-tier take-profit scaling (FEAT-11)
- [x] Create `docs/RISK.md` detailing multi-tier risk controls, exposure limits, concentration caps, drawdown rules, and emergency liquidation queues (FEAT-11)
- [x] Create `docs/TERMINAL-UI.md` documenting terminal dashboard panels, alternate-screen buffering, health metrics, and multi-channel alerting integrations (FEAT-11)
- [x] Create `docs/WEB-UI.md` detailing architectural blueprints, API endpoints, hot configuration mutations, and embedded in-app documentation browser (FEAT-11)
- [x] Maintain `docs/FEATURES.md` ensuring all features carry explicit FEAT identifiers (FEAT-01 through FEAT-20) (FEAT-11)

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
- [x] Add unit and mock integration tests for Yellowstone Geyser gRPC streaming and binary bonding curve parsing
- [x] Add tests for Jito tip calculations, bundle packing, and confirmation polling
- [x] Add tests for dynamic trailing stop and multi-tier partial exit calculations
- [x] Add tests for dev wallet screening, holder concentration limits, and metadata verification filters
- [x] Add tests for Raydium AMM graduation detection and pool initialization parsers
- [x] Add tests for smart money copy-trading signal extraction and proportional position sizing
- [x] Add tests for rolling order flow window aggregations and trade velocity Z-score anomalies
- [x] Add tests for multi-RPC latency scoring, health checks, failover routing, and broadcast deduplication
- [x] Add tests for daily equity baseline tracking, drawdown limits, and portfolio emergency lock triggers
- [ ] Add tests for Telegram command authentication and FastAPI/WebSocket status streaming — superseded, see Sprints 32–33 and FEAT-45
- [ ] Restructure the suite to mirror the source tree with shared `support/` factories — see Sprints 26–27 and [`TESTING.md`](TESTING.md)
- [ ] Add unit and mock integration tests for asynchronous stream recording, batch flushing, and replay dataset schema compliance (FEAT-21)

### `pumpfun_trading/streams/` (Geyser & On-Chain Event Ingestion)
- [x] Create Yellowstone gRPC streaming client module with auto-reconnection and exponential backoff
- [x] Implement zero-copy binary parser for Pump.fun bonding curve account data and swap instruction events
- [ ] Implement event pipeline routing parsed updates directly into bot state and strategy decision loops
- [x] Add slot-level latency metrics and dropped message counters

### `pumpfun_trading/sdk/` & `pumpfun_trading/execution/`
- [x] Implement Jito JSON-RPC bundle client with tip account rotation and dynamic fee percentile estimation
- [x] Implement atomic bundle packaging for buy/sell instructions + compute budget + validator tip transfer
- [x] Add Raydium AMM pool swap instruction builder for post-graduation liquidity trades
- [x] Implement bundle status polling with fallback fast-path execution on bundle timeouts

### `pumpfun_trading/strategies/` (screening filters live in `strategies/filters.py`)
- [x] Implement pre-trade screening pipeline: dev wallet history, creator supply cap (<10%), top 5 holder cap (<15%), and social links
- [x] Implement dynamic trailing stop-loss (activation at +50%, trail drop 15%) and multi-tier profit taking (50% at 2x, 25% at 3.5x, 25% moonbag)
- [x] Implement Raydium migration monitor tracking curve completion and AMM pool initialization
- [x] Implement smart money copy-trading module with wallet performance ranking and proportional sizing
- [x] Implement order flow momentum strategy computing rolling buy/sell volume ratios, buyer counts, and trade velocity Z-scores

### `pumpfun_trading/infra/` & `pumpfun_trading/ops/`
- [x] Implement multi-provider RPC connection pool with health probes and latency-based read routing
- [x] Implement multi-RPC transaction broadcast engine for simultaneous validator dispatch
- [x] Implement portfolio-level daily equity loss tracker and 24-hour hard-lock circuit breaker (liquidate all & pause on >15% daily drawdown)
- [x] Add alerting dispatchers for emergency circuit breakers, liquidation events, and RPC degradation

### `pumpfun_trading/ui/` (terminal dashboard follow-ups)
- [ ] ~~Implement Telegram interactive bot~~ — superseded, now FEAT-45
- [ ] ~~Implement FastAPI / WebSockets web dashboard~~ — superseded by Phase 6 (Sprints 32–35)
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
- [x] Integrate Yellowstone Geyser gRPC streaming client for sub-second bonding curve creation and swap detection (FEAT-01)
- [x] Implement zero-copy binary parser for bonding curve reserves and on-chain swap events (FEAT-01)
- [x] Integrate Jito Block Engine bundle client with dynamic tip estimation and validator tip rotation (FEAT-02)
- [x] Implement atomic transaction bundling to eliminate sandwich attacks and toxic MEV leakage
- [x] Add bundle confirmation polling with automatic fallback routing to direct RPC
- [x] Add unit and integration tests for gRPC streaming, binary account decoding, and Jito bundle submission

### Sprint 10: Dynamic Exits & Scam Protection Filters
- [x] Implement dynamic trailing stop-loss engine with configurable activation threshold and trailing drop percentage (FEAT-03)
- [x] Implement multi-tier take-profit scaling (50% exit at 2.0x, 25% exit at 3.5x, 25% trailing moonbag) (FEAT-03)
- [x] Implement dev wallet historical deployment analysis and serial rugger rejection filter (FEAT-04)
- [x] Implement creator initial holding cap (<10%) and top 5 holder supply concentration (<15%) filters (FEAT-04)
- [x] Implement token metadata URI parsing and social media link presence validation (FEAT-04)
- [x] Add unit tests and runtime integration for tiered exits and anti-scam heuristic filters (`test_trailing_and_tiered_exits.py`, `test_anti_rug_filters.py`, `test_anti_rug_bot_integration.py`)

### Sprint 11: Comprehensive Documentation Overhaul & Knowledge Architecture (FEAT-11)
- [x] Create Operator & User Manual in `docs/USER-GUIDE.md`:
  - [x] Prerequisites, Python environment setup, package installation, and quickstart commands
  - [x] Complete environment variable reference (`PUMPFUN_PRIVATE_KEY`, `PUMPFUN_RPC_URL`, `PUMPFUN_GEYSER_ENDPOINT`, `PUMPFUN_USE_JITO`, etc.)
  - [x] Non-custodial keypair security, wallet funding guidelines, and dry-run paper trading execution
  - [x] Guide to running `pumpbot` with strategy presets (`conservative`, `balanced`, `aggressive`), headless flags, and custom JSON configs
  - [x] Historical replay backtesting guide (`pumpfun-replay`) with dataset schemas and metric interpretation
  - [x] Forensic audit investigation guide (`pumpfun-audit`) with querying, filtering, and export workflows
  - [x] Complete CLI reference manual covering all subcommands, arguments, and default values
- [x] Create Mathematical Strategy & Logic Manual in `docs/STRATEGY.md`:
  - [x] Bonding curve constant-product AMM invariant math ($x \cdot y = k$, virtual/real reserves, instantaneous spot pricing)
  - [x] Candidate eligibility screening rules and market cap bounds
  - [x] Anti-rug and scam heuristic screening algorithms (Gini inequality coefficient, creator holding caps, serial developer penalties)
  - [x] Dynamic trailing stop-loss algorithmic model (peak market cap tracking, activation threshold offsets, peak drawdown liquidation)
  - [x] Multi-tier take-profit scale-out mechanics (Tier 1 principal de-risking @ 2.0x, Tier 2 @ 3.5x, Moonbag trailing floor @ 2.5x)
  - [x] Preset strategy matrix comparing parameters across `conservative`, `balanced`, and `aggressive`
- [x] Create Risk Management & Capital Safety Manual in `docs/RISK.md`:
  - [x] Multi-tier risk control hierarchy: per-order validation, position sizing limits, and portfolio-wide exposure caps
  - [x] Single-token concentration limits and minimum wallet rent/SOL reserve buffers
  - [x] Stale data stream circuit breakers, seen-mint throttling, and buy cooldown windows
  - [x] On-chain position reconciliation at startup and automated exit retry queue with escalating slippage
- [x] Create Terminal UI & Operations Guide in `docs/TERMINAL-UI.md`:
  - [x] Terminal dashboard visual panel breakdown (Overview, Strategy, Risk, Bot Status, Health Check, Active Positions, Recent Trades)
  - [x] Alternate-screen buffer architecture, live refresh intervals, and ANSI/`NO_COLOR` compliance
  - [x] Real-time operational telemetry: slot latency benchmarking, stream drop tracking, and error categorization
  - [x] Multi-channel webhook alert integration guide for Discord, Slack, and Telegram
- [x] Create Web UI Architecture & Embedded Documentation Roadmap in `docs/WEB-UI.md`:
  - [x] Architectural blueprint for full-featured FastAPI web backend and WebSocket real-time state streaming
  - [x] Interactive bot control specification: live start/pause/stop, hot configuration mutations without restarts, one-click panic liquidations
  - [x] Embedded in-app Markdown documentation viewer and search portal design
  - [x] Architectural contrast between the lightweight Terminal UI and the primary Web Control Dashboard
- [x] Maintain `docs/FEATURES.md` ensuring all capabilities carry standardized FEAT identifiers (FEAT-01 through FEAT-20)

### Sprint 12: Enterprise Circuit Breakers & Portfolio Risk Hard-Stop
- [x] Implement real-time daily baseline equity tracking and cumulative realized/unrealized PnL monitoring (FEAT-09)
- [x] Implement portfolio hard-stop circuit breaker: emergency order cancellation, position liquidation, and 24-hour pause on >15% drawdown (FEAT-09)
- [x] Implement multi-channel emergency alert dispatch (Discord, Telegram, Slack) on hard circuit breaker engagement (FEAT-09)
- [x] Add unit and integration tests simulating catastrophic market drops and verifying portfolio lock engagement

### Sprint 13: Order Flow Momentum & Raydium Graduation Sniping
- [x] Implement sliding window order flow analytics computing buy/sell volume ratios and net SOL inflow (FEAT-07)
- [x] Implement trade velocity tracker and Z-score anomaly detector for momentum entry triggers (FEAT-07)
- [x] Implement bonding curve completion monitor tracking SOL reserve threshold (~85 SOL / $69k cap) (FEAT-05)
- [x] Implement Raydium AMM pool initialization listener (`CreatePool`/`Initialize2`) and swap execution builder (FEAT-05)
- [x] Integrate momentum and graduation signals into modular strategy decision engine
- [x] Add unit and replay simulation tests for order flow velocity metrics and Raydium migration sniping

### Sprint 14: Smart Money Copy-Trading & High-Availability Infrastructure
- [x] Create smart money wallet tracking registry with historical win rates and performance ranking (FEAT-06)
- [x] Implement real-time transaction mirror listener with proportional position sizing and risk validation (FEAT-06)
- [x] Implement multi-provider RPC connection pool with latency-based query routing (FEAT-08)
- [x] Implement multi-RPC concurrent transaction broadcast engine for high-reliability validator inclusion (FEAT-08)
- [x] Implement automatic RPC rate-limit circuit breaking and failover fallback logic (FEAT-08)
- [x] Add unit and integration tests for copy-trading trade mirroring and multi-RPC connection pooling

### Sprint 15: Core Runtime Decomposition & SOLID Architecture Refactoring
- [x] Extract `PositionManager` in `pumpfun_trading/bot/position_manager.py` to isolate position lifecycles, partial scaling tiers, and trailing stop metrics
- [x] Extract `OrderExecutor` and `OrderLiquidator` in `pumpfun_trading/execution/executor.py` and `liquidator.py` for buy/sell order dispatch and emergency exits
- [x] Extract `TokenEnricher` in `pumpfun_trading/bot/enrichment.py` for anti-rug screening, creator profiling, and Gini holder analysis
- [x] Extract `EventRouter` in `pumpfun_trading/bot/event_router.py` to decouple Geyser/WebSocket stream ingestion from trade execution
- [x] Extract `StatusPersistenceManager` in `pumpfun_trading/bot/persistence.py` and `AlertDispatcher` in `pumpfun_trading/bot/alerts.py`
- [ ] **Re-opened:** Refactor `TradingBot` in `pumpfun_trading/bot/run.py` into a lightweight facade and orchestrator adhering to SRP and OCP — `run.py` regrew to ~3,770 lines; see **Sprint 28**
- [x] Update existing unit and integration test suites to verify complete behavioral equivalence and 100% test pass rate

### Sprint 16: Full-Featured Web Control Dashboard, FastAPI Portal & Mobile Telegram Bot — **SUPERSEDED**
> Replaced by Phase 6 (Sprints 32–35). Telegram moved to FEAT-45; the in-app Markdown viewer is replaced by the static docs portal (FEAT-37). Items kept for history only.
- [ ] Implement interactive Telegram bot for remote mobile control (`/status`, `/positions`, `/sell_all`, `/pause`, `/resume`, `/config`) (FEAT-10)
- [ ] Implement full-featured FastAPI web backend with asynchronous WebSocket state streaming (FEAT-10)
- [ ] Build interactive browser dashboard for full bot control, live portfolio equity curves, and hot config adjustment (FEAT-10)
- [ ] Implement embedded in-app Markdown documentation viewer and search portal directly within the web dashboard (FEAT-10, FEAT-11)
- [ ] Add comprehensive test suites for Web UI endpoints, WebSocket streams, and Telegram command authentication (FEAT-10)

### Sprint 17: Asynchronous Market Stream Recorder & Historical Replay Dataset Generator (FEAT-21)
- [x] Implement non-blocking asynchronous replay recording hook with batch queue flushing in `TradingBot` (FEAT-21)
- [x] Expose `--record-replay` flag on `pumpbot` CLI and environment configuration (FEAT-21)
- [x] Build dedicated standalone market data harvester CLI subcommand (`pumpfun record` / `pumpfun-recorder`) (FEAT-21)
- [x] Implement deterministic synthetic scenario generator and REST historical trade exporter (FEAT-21)
- [x] Add unit tests and replay engine compatibility validation (`test_market_recorder.py`) (FEAT-21)

### Sprint 18: Automated Log File Retention, Rollover & Multi-Sink Compression (FEAT-22)
- [x] Implement size-based and time-based application log rotation with custom gzip rotator and namer in `pumpfun_trading/ops/logging.py` (FEAT-22)
- [x] Add log rotation environment variables (`PUMPFUN_LOG_MAX_BYTES`, `PUMPFUN_LOG_BACKUP_COUNT`, `PUMPFUN_LOG_ROTATION_TYPE`, `PUMPFUN_LOG_COMPRESS`) to `pumpfun_trading/config/env.py` and `TradingBotConfig` (FEAT-22)
- [x] Create centralized retention management engine and async-safe rotating file sink in `pumpfun_trading/ops/retention.py` (`RetentionPolicy`, `RotatedFileSink`, `LogRetentionManager`) (FEAT-22)
- [x] Integrate `RotatedFileSink` with configurable rollover and retention into `StatusPersistenceManager` for `audit.jsonl` in `pumpfun_trading/bot/persistence.py` (FEAT-22)
- [x] Integrate `RotatedFileSink` into `ReplayRecorder` in `pumpfun_trading/bot/recorder.py` for chunked market replay recordings and background compression (FEAT-22)
- [x] Wire retention management and periodic background pruning into `TradingBot` runtime lifecycle in `pumpfun_trading/bot/run.py` (FEAT-22)
- [x] Upgrade `load_audit_records` in `pumpfun_trading/bot/audit.py` and `pumpfun_trading/cli/audit.py` to transparently read `.gz` files and directory datasets (FEAT-22)
- [x] Upgrade `PaperTradingEngine.load_history` and `run_replay` in `pumpfun_trading/engines/replay.py` and `pumpfun_trading/cli/replay.py` to support compressed `.jsonl.gz` datasets and multi-part replay directories (FEAT-22)
- [x] Add storage maintenance CLI commands (`pumpfun ops prune`, `pumpfun ops status`) in `pumpfun_trading/cli/main.py` (FEAT-22)
- [x] Add comprehensive test suites for log rotation, retention manager, compressed audit querying, and chunked replay datasets (`test_logging_rotation.py`, `test_ops_retention.py`, `test_audit_tool.py`, `test_market_recorder.py`, `test_ops_cli.py`) (FEAT-22)

### Sprint 19: Comprehensive CLI Commands Reference & Terminal UI Observability Documentation
- [x] Create comprehensive CLI reference manual in `docs/CLI-COMMANDS.md`:
  - [x] Document CLI architecture: dedicated binaries (`pumpbot`, `pumpfun-recorder`, `pumpfun-replay`, `pumpfun-audit`) vs unified `pumpfun` dispatcher
  - [x] Clarify operational purpose and multi-mode utility of `pumpfun-recorder` / `pumpfun record` (zero-capital live stream harvesting, synthetic dataset generation, and REST trade exports)
  - [x] Document complete parameter and flag matrices across all CLI commands with types, defaults, and aliases
  - [x] Provide practical execution recipes and real-world workflows for each tool
- [x] Overhaul and expand Terminal UI manual in `docs/TERMINAL-UI.md`:
  - [x] Create high-fidelity ASCII visual representation of the active Rich dashboard layout
  - [x] Document complete field-by-field breakdown for Strategy, Risk, Bot Status, Health Check, Open Positions, Coin Polling, Events, Trade Ledger, and Metrics panels
  - [x] Document visual styling, color codes, unit formatting (SOL / µSOL), lifecycle states, and headless execution
- [x] Link `docs/CLI-COMMANDS.md` and `docs/TERMINAL-UI.md` in `docs/USER-GUIDE.md`, `AGENTS.md`, and `docs/dev/README.md`

### Sprint 20: Adaptive Realized-Ratchet Drawdown Engine & Diagnostic Event Telemetry (FEAT-29 & FEAT-30)
- [x] Add configuration fields to `TradingBotConfig` and environment parser (`drawdown_reference_mode`, `profit_ratchet_ratio`, `profit_drawdown_tolerance_pct`, `enable_diagnostic_events`, `event_log_path`, `event_log_subsystems`) (FEAT-29, FEAT-30)
- [x] Implement realized profit ratcheting and dual-zone risk evaluation (`Principal Protection Zone` vs `Profit Run Zone`) in `DailyEquityTracker` in `pumpfun_trading/bot/risk.py` (FEAT-29)
- [x] Implement tiered two-stage circuit breaker actions (`NONE`, `HALT_NEW_BUYS`, `EMERGENCY_LIQUIDATE`) in `pumpfun_trading/bot/risk.py` (FEAT-29)
- [x] Wire two-tier circuit breaker status into token screening, entry loops, and position exits in `pumpfun_trading/bot/run.py` and `position_manager.py` (FEAT-29)
- [x] Implement high-throughput async non-blocking `DiagnosticEventLogger` with background queue flushing in `pumpfun_trading/ops/events.py` (FEAT-30)
- [x] Instrument core subsystems with structured diagnostic telemetry events (`streams/`, `enrichment.py`, `strategy.py`, `executor.py`, `sdk/jito.py`, `position_manager.py`, `risk.py`) (FEAT-30)
- [x] Build standalone `pumpfun-events` CLI tool and unified `pumpfun events` subcommand with Rich formatting, tailing, filters, and latency analytics (FEAT-30)
- [x] Add comprehensive test suites for realized-ratchet drawdown math, dual-tier circuit breakers, event logger stress tests, and CLI querying (`test_risk_adaptive_ratchet.py`, `test_diagnostic_events.py`, `test_events_cli.py`) (FEAT-29, FEAT-30)

### Sprint 21: Quantitative Alpha Engines (FEAT-23, FEAT-24 & FEAT-25)
- [x] Implement `BondingCurveVolatilityEstimator` in `pumpfun_trading/sdk/curve.py` calculating price velocity, rolling volatility, depth consumption, and price impact (FEAT-23)
- [x] Implement `AdaptiveExecutionPolicy` in `pumpfun_trading/execution/policy.py` resolving dynamic slippage bounds and urgency-tiered compute unit / Jito tip scaling (FEAT-23)
- [x] Integrate dynamic slippage and priority fees into `OrderExecutor`, `PumpFunExecutionClient`, and `OrderLiquidator` (FEAT-23)
- [x] Implement `PositionEvEvaluator` in `pumpfun_trading/strategies/decision.py` calculating Expected Value (EV) scores based on momentum Z-scores, net inflows, duration, and stagnation factors (FEAT-24)
- [x] Implement `CapitalDisplacementEngine` in `pumpfun_trading/bot/position_manager.py` evaluating candidate EV vs. weakest holding EV overcoming roundtrip friction (FEAT-24)
- [x] Integrate atomic capital displacement and position rotation into `TradingBot` runtime event loop in `pumpfun_trading/bot/run.py` (FEAT-24)
- [x] Implement curve reserve accumulation acceleration ($a_{\text{curve}} = \Delta^2 \text{SOL} / \Delta t^2$) and trajectory classification in `pumpfun_trading/strategies/graduation.py` (FEAT-25)
- [x] Implement staged pre-graduation entry triggers (70%–85% progress with positive acceleration) and multi-tranche take-profit scaling (92%, 97%, moonbag) in `pumpfun_trading/strategies/exits.py` (FEAT-25)
- [x] Add configuration parameters to `TradingBotConfig`, presets, environment variables, and historical replay simulator in `PaperTradingEngine` (FEAT-23, FEAT-24, FEAT-25)
- [x] Add comprehensive unit and integration test suites (`test_dynamic_execution_policy.py`, `test_capital_displacement.py`, `test_graduation_harvester.py`) (FEAT-23, FEAT-24, FEAT-25)

### Sprint 22: On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)
- [x] Implement `FundingClusterGraph` in `pumpfun_trading/strategies/cluster.py` resolving root funding origins, common ancestor chains, and calculating the Insider Cluster Concentration Index ($0.0–1.0$) (FEAT-26)
- [x] Implement `SybilWashTradingDetector` in `pumpfun_trading/strategies/cluster.py` detecting circular buy/sell patterns, alternating ping-pong swaps, and rapid zero-profit wallet churn (FEAT-26)
- [x] Implement `FundingClusterAnalyzer` in `pumpfun_trading/strategies/cluster.py` producing composite screening verdicts with risk penalties and hard rejection flags (`insider_cluster_detected`, `dominant_cluster_detected`, `sybil_wash_detected`) (FEAT-26)
- [x] Integrate cluster and sybil wash heuristics into `evaluate_cluster_heuristics`, `evaluate_token_heuristics`, and `passes_anti_rug_screening` in `pumpfun_trading/strategies/filters.py` (FEAT-26)
- [x] Integrate cluster graph evaluation into `TradingStrategy` (`strategies/decision.py`) and `TokenEnricher` (`bot/enrichment.py`) (FEAT-26)
- [x] Add configuration parameters to `TradingBotConfig` (`strategies/base.py`), strategy presets (`conservative`, `balanced`, `aggressive`), and environment variable parser in `config/env.py` (FEAT-26)
- [x] Add unit and integration test suite in `pumpfun_trading/tests/test_funding_cluster_and_sybil.py` verifying graph building, cycle protection, sybil detection, anti-rug integration, and presets (FEAT-26)

### Sprint 23: Automated Strategy Parameter Auto-Tuning & Hyperparameter Backtest Optimizer (FEAT-27)
- [x] Implement `Hyperparameter`, `FloatParam`, `IntParam`, `CategoricalParam`, `BoolParam`, and `ParameterSpace` in `pumpfun_trading/engines/optimizer.py` (FEAT-27)
- [x] Implement `build_default_strategy_search_space` providing standard search domains covering entry sizing, momentum Z-scores, multi-tier take-profits, trailing stops, stagnation exits, adaptive ratchets, and anti-rug cluster caps (FEAT-27)
- [x] Implement `FitnessScore` and multi-objective fitness evaluators computing Sharpe Ratio, Sortino Ratio, Profit Factor, Calmar Ratio, Win Rate, and Total Return (FEAT-27)
- [x] Implement `RandomSearchOptimizer`, `GridSearchOptimizer`, and evolutionary `GeneticOptimizer` with tournament selection, blend crossover, Gaussian mutation, and elitism preservation (FEAT-27)
- [x] Implement `WalkForwardValidator` providing in-sample (train) and out-of-sample (test) dataset partitioning and overfitting penalty tracking (FEAT-27)
- [x] Implement `StrategyOptimizer` facade coordinating search algorithms, dataset evaluation, progress callbacks, and configuration exports (FEAT-27)
- [x] Implement standalone `pumpfun-optimize` binary and unified `pumpfun optimize` CLI subcommand in `pumpfun_trading/cli/optimize.py` and `main.py` (FEAT-27)
- [x] Add `pumpfun-optimize` script entry point in `pyproject.toml` (FEAT-27)
- [x] Add comprehensive unit and integration test suite in `pumpfun_trading/tests/test_strategy_optimizer.py` (FEAT-27)

### Sprint 24: Atomic Jito Back-Running & Cross-Venue Arbitrage Engine (FEAT-28)
- [x] Implement `CrossVenueDisparityMonitor` and `calculate_cross_venue_spread` in `pumpfun_trading/strategies/arbitrage.py` tracking spot price disparities between Pump.fun virtual curves and Raydium AMM v4 pools (FEAT-28)
- [x] Implement closed-form mathematical optimal swap sizing solver (`OptimalArbitrageCalculator`) deriving $x^*$ subject to dual AMM reserves and protocol fee friction (FEAT-28)
- [x] Implement `MempoolBackrunEngine` in `pumpfun_trading/strategies/arbitrage.py` detecting large whale transactions and generating counter-trade back-run signals (FEAT-28)
- [x] Implement `AtomicArbitrageBuilder` in `pumpfun_trading/execution/arbitrage.py` assembling dual-leg atomic transactions (Pump.fun + Raydium) and dynamic Jito validator tip transfers (FEAT-28)
- [x] Implement `AtomicArbitrageExecutor` in `pumpfun_trading/execution/arbitrage.py` orchestrating Jito bundle submission, simulated dry-run execution, and reversion handling (FEAT-28)
- [x] Integrate cross-venue arbitrage evaluation and transient flash capital accounting into `TradingBot` runtime event loop (`_handle_bonding_curve_state_update`, `_handle_trade_event_update`, `_handle_raydium_pool_update`) and telemetry logging (`DiagnosticEventLogger`) (FEAT-28)
- [x] Add configuration parameters to `TradingBotConfig` (`strategies/base.py`), presets (`conservative`, `balanced`, `aggressive`), and environment variable parsers in `config/env.py` (FEAT-28)
- [x] Implement standalone `pumpfun-arb` binary and unified `pumpfun arb` / `pumpfun arbitrage` CLI subcommand in `pumpfun_trading/cli/arbitrage.py` and `main.py` (FEAT-28)
- [x] Add `pumpfun-arb` script entry point in `pyproject.toml` (FEAT-28)
- [x] Integrate multi-venue arbitrage simulation into `PaperTradingEngine` in `pumpfun_trading/engines/replay.py` (FEAT-28)
- [x] Add comprehensive unit and integration test suite in `pumpfun_trading/tests/test_cross_venue_arbitrage.py` (FEAT-28)

## Phase 4b: Terminal Income Track (highest priority)

**Funding model.** The terminal UI (`pumpbot`) must generate the income that pays for the Web UI. Phase 6 does not start until the funding gate below passes, so every sprint in this phase outranks Phases 5 and 6.

The bot can trade live, but there is no evidence yet that it is profitable after fees and Jito tips (no completed paper pilot; replay benchmark recorded `Trades: 0`; most money-path fixes BUG-35…94 are unit-tested but not observed on mainnet). It also cannot yet *measure* net income: trade records from `TradingBot._record_trade` (`bot/run.py`) and the realized PnL fed to the daily circuit breaker are gross (`sell_p - entry`) with no transaction fee, priority fee, Jito tip or signature fields, and the snapshot ledger keeps only the last 50 trades. Sprints 24A–24D close those gaps in order of impact on income.

| Sprint | Goal | Touches money path? |
|---|---|---|
| 24A | Paper pilot and live canary (evidence) | No (operations only) |
| 24B | Net PnL accounting and reconciliation (measurement) | Accounting only; restarts Stage 0 for 24h |
| 24C | Backtest fidelity and strategy tuning (edge); BUG-102 secret redaction | Config only, unless BUG-61 fixes change live code; BUG-102 touches telemetry/logging only |
| 24D | Unattended operation and capital protection (uptime, safety) | Partly (pause / sweep) |

**Rules while the income track runs**
- Money-path changes (execution, SDK, sizing, exits, risk, stream handlers) are limited to bug fixes and Phase 4b items. Each one goes back through Stage 0 ([`RELEASE-GATE.md` §3.1](RELEASE-GATE.md#31-stages)).
- Phase 5 Sprints 25–27 (packaging and tests only) may run in parallel. Sprints 28–30 change runtime code and wait until Stage 1 has passed; they are then released between canary windows, each with its own Stage 0 run.
- Web UI work (Phase 6) waits for the funding gate.

**Funding gate (entry condition for Phase 6)**
- [ ] Live capital gate Stage 1 passed and the bot is at Stage 2 or above ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate))
- [ ] Cumulative **net** profit (after fees and tips, reconciled against the wallet) covers the agreed Phase 6 budget (hosting, domain, security review) plus a reserve of at least one month of running costs
- [ ] Net profit positive for at least 4 consecutive weeks at the current capital stage
- [ ] Decision and figures recorded in the release record ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui))

### Sprint 24A: Paper Pilot & Live Canary — see [`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate) and [`RUNBOOK.md`](RUNBOOK.md)
- [ ] Tag the current `main` as a release (`v0.x.y`) after it passes the release gate ([`RELEASE-GATE.md` §2](RELEASE-GATE.md#2-release-gate-every-release))
- [ ] Set up a dedicated runtime directory outside the repo with explicit `PUMPFUN_STATUS_PATH` / `PUMPFUN_AUDIT_LOG_PATH` / `PUMPFUN_EVENT_LOG_PATH` ([`RUNBOOK.md` §1](RUNBOOK.md#1-runtime-directory-layout))
- [ ] Run the incident drills in paper mode ([`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills))
- [ ] Stage 0: 72h paper pilot on the live stream with replay recording; record the summary in the release record
- [ ] Stage 1: live canary on a dedicated hot wallet with the canary config (0.01 SOL buys, ≤ 2 positions, 10% daily drawdown; arbitrage, back-running, pre-graduation harvesting, Raydium sniping and copy trading off)
- [ ] Daily wallet reconciliation (on-chain Δ SOL vs audit realized PnL) logged for every canary day ([`RUNBOOK.md` §5.3](RUNBOOK.md#53-daily-wallet-reconciliation))
- [ ] Log every discrepancy or failure in `BUGS.md`; fix before continuing
- **Acceptance:** Stage 1 exit criteria met — ≥ 100 closed trades, net PnL after fees and tips positive, reconciliation gap within tolerance every day, 0 lost or double-sold positions. Only then increase capital (Stage 2) or plan Phase 5–6 spending around bot income.
- **Dependency:** the canary's net-PnL criterion needs Sprint 24B. Start Stage 0 straight away; do not start Stage 1 live trading until 24B has landed (or reconcile fees and tips by hand from the transaction signatures each day).

### Sprint 24B: Net PnL Accounting & Reconciliation (FEAT-49, BUG-96)
Branch `sprint-24b-net-pnl`.
- [x] **BUG-96:** close the token account on every full exit (`CloseAccount` in the sell transaction, only when the sell empties the account; retry without the close if a closing sell fails), recovering ~0.002 SOL rent per trade (`sdk/execution.py`, `execution/executor.py`, `bot/run.py`; `close_token_account_on_full_exit`, default on)
- [x] Capture per-transaction costs at confirmation: signature, network fee, priority fee (fee − 5,000 lamports per signature), Jito tip (transfer to a tip account), token-account rent paid/refunded, and the exact swap amount from the `getTransaction` pre/post balances (`sdk/costs.py`, `PumpFunExecutionClient.get_transaction_costs`, `OrderExecutor._capture_costs`). Live buys use the SOL actually paid as cost basis; live sells use the exact swap output as proceeds (BUG-48)
- [x] Paper mode models the same costs (base + priority fee, static Jito tip, rent) and the Pump.fun fee on both legs, so paper PnL is comparable with live
- [x] Extend the trade record (`TradingBot._record_trade`) and the audit trail with `signature`, `fee_sol`, `priority_fee_sol`, `tip_sol`, `rent_sol`, `costs_sol`, `cost_source`, `gross_pnl_sol`, `net_pnl_sol`, `cash_flow_sol`, `dry_run`, `strategy`; existing fields keep their meaning (`bot/pnl.py`)
- [x] Feed **net** realized PnL to `DailyEquityTracker` (buys book their costs as a realized loss, sells book gross minus costs); `realized_daily_costs_sol` / `realized_daily_gross_pnl_sol` added and reset with the day
- [x] `pumpfun-audit pnl [--group-by day|reason|strategy|mint] [--json]` — gross, fees, tips, rent, net, win rate, expectancy, costs as a share of gross; per exit reason with `--group-by reason`
- [x] `pumpfun-audit reconcile --wallet <pubkey> [--start-balance SOL]` — per-signature wallet SOL change vs. audit `cash_flow_sol`, closed positions still holding tokens (lost), open positions holding none (phantom), optional whole-wallet check; exit code 1 above the `RELEASE-GATE.md` §3.4 tolerance (`bot/reconcile.py`)
- [x] Terminal dashboard Risk panel: net and gross PnL today, costs today, session net PnL (`ui/dashboard.py`); session totals persist in `bot_status.json` (`pnl_totals`)
- [x] Reconciliation status on the dashboard: `pumpfun-audit reconcile` stores its result in `reconcile_status.json` next to the audit trail (`--status-file`, `--no-status-file`, `PUMPFUN_RECONCILE_STATUS_PATH`); the Risk panel shows `Reconciliation: OK / GAP / STALE (> 36 h) / not run` and `bot_status.json` carries it as `reconciliation` (`bot/reconcile.py`, `ui/dashboard.py`). Running reconcile on a schedule and alerting on a gap stays with the Sprint 24D daily summary alert
- [x] Persist the full trade history to the audit trail — already the case: every trade is appended to `audit_trail.jsonl`; the 50-entry snapshot ledger stays a display buffer only
- [x] Tests in the mirrored layout ([`TESTING.md`](TESTING.md)): `unit/sdk/test_costs.py`, `unit/sdk/test_execution.py`, `unit/execution/test_executor.py`, `unit/bot/test_pnl.py`, `unit/bot/test_reconcile.py`, `unit/bot/test_risk.py`, `unit/bot/test_run.py`, `unit/cli/test_audit.py`, `unit/ui/test_dashboard.py`; `tests/conftest.py` blocks the cost RPC so partly mocked clients never reach mainnet; `RUNBOOK.md` §5.3 switched to the new commands
- [x] Coverage back to ≥ 95%: **96.3%** (911 tests; `nox -s lint mypy tests` green). New mirrored tests: `unit/bot/test_run.py`, `unit/bot/test_position_manager.py`, `unit/cli/test_record.py`, `unit/cli/test_events.py`, `unit/cli/test_main.py`, `unit/ops/test_events.py`, `unit/ops/test_retention.py`, `unit/engines/test_optimizer.py`, `unit/sdk/test_execution.py`; `tests/unit/**/__init__.py` added so same-named modules in different packages don't collide. The pass found BUG-97…101 (`BUGS.md` §8)
- [x] Fix the test-pass findings BUG-97…101 (`BUGS.md` §8): log rotation keeps plain archives plain and waits for the previous gzip (`ops/retention.py`); `emit` never raises on unknown categories (`ops/events.py`); landed arbitrage is booked net of fee, priority fee and tip (`bot/run.py`, `bot/pnl.py`); an explicit `stream_url=` wins (`bot/run.py`); Pump.fun builders refuse to quote on zero curve reserves (`sdk/execution.py`). Gate still green: 922 tests, coverage 96.3%
- [ ] Verify on mainnet with the first canary trades: `pumpfun-audit reconcile` passes and every full exit shows a negative `rent_sol`. *Partly done (read-only):* the cost parser was run on real third-party Pump.fun sells that close the token account and reads the rent refund, fee and priority fee correctly; this also showed mainnet rent is now ~0.0015 SOL, so the modelled paper rent was corrected. Only the bot's own canary trades can close this item
- **Acceptance:** for a paper/devnet session, `pumpfun-audit reconcile` reproduces the wallet delta within tolerance; net PnL on the dashboard equals the audit `pnl` total; coverage ≥ 95%

### Sprint 24C: Backtest Fidelity & Strategy Tuning (BUG-61, BUG-102)
Branch: `sprint-24c-backtest-fidelity`. Delivered in small phases, each a self-contained change with its own tests and docs, so a phase can be reviewed (and paused) without the next one:

| Phase | Scope | Touches live code? | Status |
|---|---|---|---|
| 1 | BUG-102 `redact_url()` and its use in telemetry, config dicts and log/event messages | Telemetry/logging only | Done |
| 2 | BUG-61: replay uses live sizing (`buy_amount_sol`, exposure caps) and the live exit stack (`strategies/exits.py`) | No (replay only) | Done |
| 3 | Replay deducts modelled costs (Pump.fun fee both sides, network/priority fee, Jito tip, ATA rent/refund) and reports net PnL | No | Done |
| 4 | Replay-vs-live parity report (`pumpfun-replay --compare-audit`) and the optimizer search space widened again to what replay now honours | No | Tooling done; first run needs a capture |
| 5 | Tuning on live captures and filter/exit attribution: operator procedure (`RUNBOOK.md` §6.1), run on Stage 0/1 data | No (operations) | Procedure documented; needs ≥ 2 days of capture |
- [x] **BUG-102 (phase 1, done):** stop writing RPC API keys to disk. Add a `redact_url()` helper (`ops/redact.py`) that masks credential query values (`api-key`, `token`, `key`, …), `user:pass@` userinfo and key-like path segments; use it in `RpcEndpoint.to_dict` / `RpcPoolConfig.to_dict` (`infra/rpc_pool.py`), `TradingBotConfig.to_dict` (`stream_url`, `api_base_url`) and every log/event/alert message that prints an endpoint or stream URL (`bot/run.py`, `streams/geyser.py`). Tests: `unit/ops/test_redact.py`, `unit/infra/test_rpc_pool.py`, and a snapshot test asserting no secret appears in `get_status_snapshot()`. See BUG-102 in [`BUGS.md`](BUGS.md) §9. *Done:* applied at the chokepoints (pool/config `to_dict`, the log formatter, `_record_event`, the `events.jsonl` writer) so new call sites are covered automatically
- [x] **(phase 2)** Resolve BUG-61: `PaperTradingEngine` (`engines/replay.py`) uses the live sizing (`buy_amount_sol`, exposure caps) and the live exit stack (tiered take-profits, trailing stops, max-hold, stagnant exits) from `strategies/exits.py`. *Done:* `live_fidelity=True` (on by default for `pumpfun-replay --config/--preset` and every optimizer trial; `--simple-exits` for the old model); risk-limit rejections counted in `entry_rejections`; time-based exits run on the replay clock. Tests: `unit/engines/test_replay.py`
- [x] **(phase 3)** Model fees, priority fees, Jito tips and slippage in replay from the 24B cost data, so backtests report **net** PnL. *Done:* `engines/costs.py` `ReplayCostModel` (same model as paper mode: 125 bps each side, base + priority fee, tip from `PUMPFUN_JITO_TIP_LAMPORTS`, rent paid on buy and refunded on a closing full exit); sells carry `gross_pnl_sol` / `costs_sol` / `net_pnl_sol`, `pnl` is net; `--no-costs`, `--tip-lamports`, `--priority-fee-lamports`. Optimizer trials start with `reserve + 2 × max exposure` instead of 100 SOL. Tests: `unit/engines/test_costs.py`, `unit/engines/test_replay.py`, `unit/engines/test_optimizer.py`
- [ ] **(phase 4 tooling done; run pending)** Replay-vs-live parity check: replay the Stage 0 / Stage 1 capture and compare decisions and PnL with the audit trail; differences explained. *Done:* `engines/parity.py` and `pumpfun-replay --compare-audit` (per-mint entries, normalised exit reasons, net PnL gap, exit 1 outside `--parity-tolerance-sol/-pct`); captures replay the bot's own recorded fills as entries. Optimizer search space widened again to the live exit stack. Tests: `unit/engines/test_parity.py`. *Open:* run it on the v0.2.x Stage 0 capture and record the result ([`RUNBOOK.md` §6.1](RUNBOOK.md#61-replay-parity-and-tuning-on-captures-sprint-24c))
- [ ] **(phase 5, operations)** Tune with `pumpfun-optimize` on recorded **live** captures (train/test split by day; BUG-60 selection on `train_fitness` only); promote a tuned config only through Stage 0. Procedure: [`RUNBOOK.md` §6.1](RUNBOOK.md#61-replay-parity-and-tuning-on-captures-sprint-24c); needs ≥ 2 days of capture and a passing parity check first
- [ ] **(phase 5, partly)** Per-filter and per-exit attribution report (which filters reject winners, which exits leave money on the table) via `pumpfun-audit pnl --by reason`. *Available:* per-exit net PnL from `pumpfun-audit pnl --group-by reason` and the replay ledger (`reason`, `hold_seconds`), per-risk-limit entry rejections in the replay summary. *Not possible yet:* per-**filter** attribution, because captures don't record the screener's enrichment data (socials, holders, creator history); recording it is a follow-up
- **Acceptance:** `bot_status.json`, `bot.log`, `events.jsonl` and alerts from a Stage 0 run contain no RPC/stream credential (BUG-102); replay of a live capture matches live net PnL within an agreed tolerance; a tuned config beats the canary config out-of-sample before it is promoted

### Sprint 24D: Unattended Operation & Capital Protection (FEAT-50, FEAT-42)
- [ ] Operator pause without a restart: `SIGUSR1` toggles "no new buys, keep managing exits" (early, terminal-only slice of the Sprint 29 `PAUSED` state); state shown on the dashboard and written to the audit trail
- [ ] Daily PnL summary alert (net PnL, trades, fees + tips, breaker state, reconciliation result) through `bot/alerts.py`, plus alerts on stream/RPC degradation lasting > N minutes
- [ ] Supervised headless deployment: documented systemd unit / launchd plist with restart limits and log retention (operator slice of FEAT-46); `RUNBOOK.md` updated
- [ ] FEAT-42 profit sweep (disabled by default): move realized profit above a hot-wallet floor to a cold wallet, audited
- [ ] Optional, if latency is shown to cost entries: FEAT-39 Yellowstone gRPC transport (isolated in `streams/`)
- **Acceptance:** 7 days unattended at the current capital stage with no manual restarts; pause and sweep exercised in drills ([`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills))

## Phase 5: Platform Refactor (required before the Web UI)

**Scheduling around income:** Sprints 25–27 may run in parallel with Phase 4b; Sprints 28–30 change runtime code and start only after live capital Stage 1 has passed (see the Phase 4b rules).

The bot is in production. Phase 5 pays down the structural debt that blocks the hosted Web UI without touching trading behaviour. Every sprint keeps the standard gates: **coverage ≥ 95% (`fail_under` never lowered)**, `nox -s lint`, `nox -s format`, `nox -s mypy` clean, and replay parity (identical decisions on the recorded datasets in `test-data/`) for any runtime change. Finding IDs (R1–R12, T1–T9) are defined in [`TESTING.md`](TESTING.md) and [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md).

| Finding | Summary | Sprint |
|---|---|---|
| R1 | `bot/run.py` regrew to ~3,770 lines | 28 |
| R2 | No typed read-model; `storage/status.py` reads private attributes via `getattr` | 29 |
| R3 | No `PAUSED` / `HALTED` lifecycle states | 29 |
| R4 | No command/control interface or event bus | 29 |
| R5 | Hot config has no validated patch path through the risk pipeline | 29 |
| R6 | WebSocket ingestion lives in `bot/run.py`, not `streams/` | 28 |
| R7 | `sdk/execution.py` (~1,650 lines) mixes Pump.fun, Raydium and confirmation logic | 28 |
| R8 | Packaging hygiene (unused `requests`, Django classifier, no extras, nox only on 3.14, version 0.1.0 vs "Production/Stable") | 25 |
| R9 | Runtime artifacts and stale `__pycache__` in the repo | 25 |
| R10 / T1–T9 | Flat, unstructured test suite | 26, 27 |
| R11 | No real Yellowstone gRPC transport | FEAT-39 (parallel track) |
| R12 | JSON/JSONL-only persistence; ledger inlined in the snapshot | 30 |

### Sprint 25: Packaging & Repo Hygiene (R8, R9, T8)
- [ ] `pyproject.toml`: remove unused `requests` dependency; replace the `Framework :: Django` classifier; align `Development Status` with the version
- [ ] Add optional extras: `[web]` (FastAPI, Uvicorn), `[db]` (SQLAlchemy, Alembic, asyncpg, aiosqlite), `[geyser]` (grpcio, protobuf)
- [ ] Exclude `pumpfun_trading.tests*` from the wheel (`[tool.setuptools.packages.find] exclude`) (T8)
- [ ] `noxfile.py`: test matrix for Python 3.11–3.14
- [ ] `.gitignore` runtime artifacts (`bot.log`, `events.jsonl`, `cov.json`, `coverage.xml`, `*.egg-info`); remove stale root `__pycache__` for retired `audit`/`bot`/`cli`/`replay` modules
- [x] Add `CHANGELOG.md` (Keep a Changelog) following the SemVer policy in [`RELEASE-GATE.md` §6](RELEASE-GATE.md#6-versioning-policy): [`CHANGELOG.md`](../../CHANGELOG.md) covers v0.1.0, v0.1.1 and v0.2.0 (Sprint 24B, merged as `754822d`), each with its release record
- **Acceptance:** `pip install .` wheel contains no `tests/`; nox matrix green on 3.11–3.14; coverage ≥ 95%

### Sprint 26: Test Foundation (T1, T4, T6, T7) — see [`TESTING.md`](TESTING.md)
- [ ] Create `pumpfun_trading/tests/support/` (`factories.py`, `payloads.py`, `fakes.py`, `constants.py`) and per-package `conftest.py` files
- [ ] Replace the 136 inline `TradingBotConfig(` constructions and 13 duplicated private-key constants with `make_config()` / `SAMPLE_PRIVATE_KEY`; unify `make_bot` / `_make_bot` and the three `make_*pool_keys` variants
- [ ] Register markers (`unit`, `integration`, `regression`, `slow`, `property`) with `--strict-markers`; remove the 216 redundant `@pytest.mark.asyncio` marks (`asyncio_mode = "auto"`)
- [ ] Replace `time.sleep` (3 files) and nested `asyncio.run` (4 files) with `FakeClock` / awaits
- [ ] Move clean single-module files into `tests/unit/<pkg>/test_<module>.py` and `*_bot_integration.py` into `tests/integration/` per the migration map
- [ ] Add `nox -s tests-fast` (`-m "not slow and not integration"`)
- **Acceptance:** collected test count unchanged (`pytest --collect-only -q`), coverage ≥ 95%, suite runtime not slower

### Sprint 27: Test Consolidation (T2, T3, T5, T9) — see [`TESTING.md`](TESTING.md)
- [ ] Dissolve the six coverage-padding files (`test_coverage_95_*.py`, `test_coverage_boost_*.py`, `test_runtime_coverage_boost.py`) into their module tests; delete tests that only assert trivia and replace them with behaviour tests
- [ ] Merge base / `_full` / `_regressions` pairs (`api_client`, `audit`, `execution_sdk`, `bot_runtime`)
- [ ] Tag regressions `@pytest.mark.regression("BUG-xx")` beside the guarded module; add a check that every resolved BUG in `BUGS.md` has ≥ 1 tagged test
- [ ] Convert repeated cases to `parametrize`
- [ ] Add `hypothesis` to the `[dev]` extra and Hypothesis property tests for `sdk/curve.py` and the `streams/geyser.py` parsers (`tests/property/`)
- [ ] Add characterisation (golden replay) tests pinning `TradingBot` decisions through public entry points (T5 safety net for Sprint 28)
- [ ] Add the layout guard test (every source module has a `unit/` counterpart)
- **Acceptance:** no file in the tests root except `conftest.py`; 1:1 mirror verified; coverage ≥ 95%

### Sprint 28: Runtime Decomposition II (R1, R6, R7)
- [ ] `bot/factory.py`: composition root extracted from `TradingBot.__init__`
- [ ] `bot/handlers/` (`curve.py`, `trade.py`, `raydium.py`, `new_token.py`) extracted from the stream handlers in `run.py`
- [ ] `execution/sell_pipeline.py` extracted from `_sell_token_locked`
- [ ] `ops/metrics.py` for runtime counters and latency telemetry
- [ ] `streams/websocket.py` for `_run_websocket_stream` (restores the `streams/` boundary)
- [ ] Split `sdk/execution.py` into Pump.fun, Raydium and confirmation modules (public re-exports kept)
- [ ] Each extracted module gets its mirrored `tests/unit/<pkg>/test_<module>.py` in the same PR ([`TESTING.md`](TESTING.md))
- **Acceptance:** `bot/run.py` < 800 lines; golden replay tests from Sprint 27 unchanged; coverage ≥ 95%; mypy clean

### Sprint 29: Typed State, Lifecycle Control & Event Bus (R2–R5)
- [ ] `bot/state_model.py`: Pydantic `BotStatusView`, `PositionView`, `TradeView`, `HealthView`; `storage/status.py` and `ui/dashboard.py` consume views instead of `getattr(bot, "_…")`
- [ ] `bot/lifecycle.py`: add `PAUSED` (manage exits, no new buys) and `HALTED` (circuit breaker) states and transitions; the Sprint 24D `SIGUSR1` pause becomes a thin trigger for `BotController.pause()` / `resume()`
- [ ] `bot/control.py`: `BotController` with `pause()`, `resume()`, `stop()`, `sell_all()`, `apply_config_patch(ConfigPatch)`; each command validated, audited, and routed through the unified risk pipeline
- [ ] `ops/bus.py`: in-process typed event bus; terminal dashboard subscribes to it
- [ ] Replace the `TradingBot.config` setter with validated `ConfigPatch` application
- **Acceptance:** zero `getattr(bot, "_…")` in `storage/` and `ui/`; terminal UI behaviour unchanged; coverage ≥ 95%

### Sprint 30: Persistence Layer (FEAT-35, R12)
- [ ] `storage/db/` with SQLAlchemy 2.0 async models and Alembic migrations (tables: `tenants`, `users`, `sessions`, `instances`, `config_versions`, `positions`, `trades`, `audit_events`, `equity_snapshots`, `alerts`)
- [ ] PostgreSQL for hosted mode, SQLite (WAL) for operator/dev mode; selected by URL
- [ ] Move the trade ledger out of the status snapshot; JSONL dual-write during migration
- [ ] DB tests on SQLite in-memory plus an opt-in `postgres` marker
- **Acceptance:** terminal mode runs with and without `[db]`; migrations up/down tested; coverage ≥ 95%

### Sprint 31: Documentation Site & Gap Closure (FEAT-37 build) — see [`DOCUMENTATION-PLAN.md`](DOCUMENTATION-PLAN.md)
- [ ] Add `mkdocs.yml` (Material-compatible) and a Zensical build; `docs/index.md` landing page
- [ ] Close every open gap listed in `DOCUMENTATION-PLAN.md` (FEAT-12 duplicate, FEAT-10 status, rest of the RUNBOOK expansion, missing pages); NEXT-30-DAYS is already retired
- [ ] Convert ASCII diagrams to Mermaid; add front matter, admonitions and tabs
- [ ] mkdocstrings API/SDK reference; strict build in CI
- **Acceptance:** `zensical build` (or `mkdocs build --strict`) passes with zero warnings

## Phase 6: Hosted Web UI (replaces Sprint 16)

**Entry condition:** the Phase 4b funding gate has passed. Until then the terminal UI is the only product and Phase 6 stays planned, not started.

Architecture: [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) and [`docs/WEB-UI.md`](../WEB-UI.md). Features: FEAT-31…FEAT-37 in [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md).

### Sprint 32: Agent API & Control Plane, Single Tenant (FEAT-31, FEAT-32)
- [ ] `pumpfun_trading/agent/` aiohttp Agent API (`/health`, `/status`, `/commands/*`, `/config`, `/events` WS) backed by `BotController` and `ops/bus.py`
- [ ] FastAPI control plane (separate deployable, `[web]` extra): auth (OIDC/JWT + passkeys), RBAC, REST/WSS, OpenAPI
- [ ] Contract tests between control plane and Agent API
- **Acceptance:** pause/resume/stop/sell-all/config patch work end-to-end against a dry-run bot; trading-loop latency unchanged

### Sprint 33: Vuetify MD3 PWA MVP (FEAT-33)
- [ ] `web/` Vue 3 + TypeScript + Vite + Vuetify 3 (`md3` blueprint) + Pinia + generated OpenAPI client + `vite-plugin-pwa`
- [ ] Views: Overview, Positions, Trades, Controls, Settings
- [ ] Vitest component tests and Playwright desktop + mobile smoke tests, mirrored under `web/`
- **Acceptance:** Lighthouse PWA installable; usable at 360 px width; light/dark follows the system

### Sprint 34: Multi-Tenant Orchestrator & Zero-Knowledge Keys (FEAT-34, FEAT-36, FEAT-46)
- [ ] Docker image (FEAT-46) and orchestrator service (`InstanceBackend`: Docker first) with quotas and private networking
- [ ] X25519 key envelope; worker-only decryption; buffers zeroed after signer setup
- [ ] Tenant isolation tests (no cross-tenant reads; no key material in logs, DB or disk)
- **Acceptance:** two tenants run isolated bots concurrently; security checklist in `RELEASE-GATE.md` signed off

### Sprint 35: Analytics, Audit Search, Embedded Docs & Terminal-UI Deprecation Gate (FEAT-37)
- [ ] Equity/PnL analytics and audit search views
- [ ] Serve the docs site at `/docs` with contextual help links from settings
- [ ] Terminal-UI deprecation gate: Web UI has parity for every operator workflow; terminal UI moves to "maintenance only"
- **Acceptance:** operator runs one full trading week from the Web UI only

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

Additional rules from Phase 4b onward:
- The terminal UI (`pumpbot`) is the income path that funds the Web UI. It stays the primary interface until the **Sprint 35** deprecation gate, and no refactor or Web UI work may regress it.
- Income-track work (Phase 4b) outranks Phases 5 and 6; Phase 6 starts only after the Phase 4b funding gate.
- Profit is always reported **net** of network fees, priority fees, Jito tips and rent, and reconciled against the wallet.
- New tests follow the layout and conventions in [`TESTING.md`](TESTING.md) (mirrored `unit/<pkg>/test_<module>.py`, shared `support/` factories, no coverage-named files).

## Notes

This repo has established a solid, modular, and fully tested production v1 foundation and can trade live. Phase 4b turns the terminal mode into a measured, reconciled income source; that income funds the rest of the roadmap. Phase 5 pays down structural debt (runtime monolith, test-suite structure, typed state, persistence, docs site) without risking the terminal mode, and Phase 6 delivers the hosted Material Design 3 Web UI once the funding gate has passed.
