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

## Suggested sprint plan

### Sprint 1: Safe running bot [in progress]
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

## Definition of done for a “serious” bot

The bot is production-worthy when it can:
- safely manage risk at the portfolio level
- stop trading when health or risk conditions fail
- replay and validate decisions using historical data
- recover smartly after restarts
- maintain a clear, queryable trade ledger
- demonstrate consistent risk-adjusted performance over time

## Notes

This repo already has a solid base for a launch-monitoring bot. The next major move is not “more features”; it is turning the system into a disciplined risk-managed trading engine with measurable strategy quality and operational resilience.
