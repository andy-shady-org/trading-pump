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
- [ ] Add a dedicated audit-search CLI/tooling entry point under `pumpfun_trading/cli.py` or a new subcommand
- [ ] Implement audit log search and filtering by:
  - record type
  - state
  - date / time window
  - mint address
  - token name / display name
  - trade reason (`take_profit`, `stop_loss`, `risk_kill`, etc.)
  - status / outcome (`success`, `failed`, `skipped`, `pending`)
- [ ] Add summary and aggregation output for recent trades, failures, and state transitions
- [ ] Add JSON and table output modes for quick inspection and automation
- [ ] Add export / review helpers for incident analysis and debugging
- [ ] Add tests for audit query filtering and CLI parsing

#### 5. Test coverage for safety-critical paths
- [x] Add unit tests for position sizing guard logic
- [ ] Add tests for kill-switch conditions
- [ ] Add tests for name resolution and active-position metadata
- [ ] Add tests for failed API and failed websocket handling
- [ ] Expand `pumpfun_trading/tests/` with risk and lifecycle tests

### Phase 1: Near-term improvements (2-4 weeks)

These improvements are about making the bot behave more like a real trading system rather than a launch monitor.


#### 6. Better execution quality
- [ ] Add slippage tolerance handling in `pumpfun_trading/sdk/execution.py`
- [ ] Add partial fill handling and re-evaluation logic
- [ ] Add retry/backoff logic for transient RPC failures
- [ ] Add transaction queue and execution lock to avoid overlapping actions
- [ ] Add execution health scoring and failure classification

#### 7. Backtesting and replay foundation
- [ ] Create a replay / simulation module under `pumpfun_trading/` for historical token data
- [ ] Add a `PaperTradingEngine` that executes trades against stored market snapshots
- [ ] Add realistic fee and slippage assumptions in simulation
- [ ] Add a simple CLI command to run historical replay from a stored dataset
- [ ] Add output metrics: profit factor, max drawdown, win rate, average trade return

#### 8. Persistent state and crash recovery
- [ ] Add state persistence for open positions and metadata
- [ ] Save last-seen mints and recent decisions to disk
- [ ] Restore position state on bot startup
- [ ] Add an event journal to support debugging and replay
- [ ] Add safe startup routine that validates persisted state before resuming

#### 9. Runtime modularization and release-readiness
- [ ] Split `pumpfun_trading/bot/run.py` into smaller modules for:
  - runtime orchestration
  - state machine / lifecycle management
  - risk controls and guard checks
  - event and audit record handling
  - execution builders / trade actions
  - terminal dashboard rendering
- [ ] Introduce a clear API boundary between runtime orchestration and execution helpers so the bot is easier to test and extend
- [ ] Add release gating criteria for a first public version:
  - safety checks pass in dry-run mode
  - risk limits and kill-switches are verified
  - audit trail is searchable and reviewable
  - core bot lifecycle is exercised in tests
  - [x] wallet and env configuration are documented
- [ ] Define a first-release milestone / cutover checkpoint before Phase 1 strategy expansion
- [ ] Add a dedicated sprint for runtime decomposition and release-readiness before broader strategy work

### Phase 2: Medium-term roadmap (1-2 months)

These changes turn the bot into a more serious production trading system.


#### 10. Add strategy modularity
- [ ] Split strategy logic into:
  - signal generation
  - filter evaluation
  - risk validation
  - execution planning
  - exit evaluation
- [ ] Create a `Strategy` protocol or base class
- [ ] Add at least 2-3 strategy presets with different risk profiles
- [ ] Add clean configuration objects for each preset

#### 11. Improve market data access
- [ ] Add richer data fetches in `pumpfun_trading/api/client.py`
  - liquidity snapshots
  - volume history
  - holder counts
  - token age / supply data
- [ ] Add data freshness checks before using a signal
- [ ] Add fallback metadata paths when API endpoint fails
- [ ] Add rate-limit and timeout handling in the client layer

### Phase 3: Long-term / production hardening (2+ months)

#### 12. Production reliability and ops
- [ ] Add structured logging with timestamps, component names, and trade IDs
- [ ] Add operational dashboard for health, risk, and performance
- [ ] Add alerts for missed trades, stale data, broken RPCs, failed signatures
- [ ] Add runbook for startup, shutdown, restart, and emergency stop
- [ ] Document wallet secret management and secure deployment process

#### 13. Security and compliance
- [ ] Move secrets to proper secret store (env injection, key vault, etc.)
- [ ] Separate hot wallet and treasury wallet logic
- [ ] Add wallet authentication checks before trade submission
- [ ] Add transaction review and approval workflow for critical actions
- [ ] Add audit log retention and periodic review

#### 14. Real strategy evaluation
- [ ] Build historical benchmark set across multiple market conditions
- [ ] Run walk-forward validation and out-of-sample testing
- [ ] Require minimum strategy test thresholds before live use
- [ ] Compare strategies using risk-adjusted metrics, not just raw profit

## Repo-specific work items

### `pumpfun_trading/bot/run.py`
- [ ] Add risk guard before every buy and sell
- [ ] Add execution state machine and trade ledger
- [ ] Add graceful shutdown, restart, and health-monitoring paths
- [ ] Add compact but informative health dashboard with risk metrics
- [ ] Add alerting hooks for stale data or failed execution

### `pumpfun_trading/api/client.py`
- [ ] Add quality checks for API payloads and metadata freshness
- [ ] Add fallback request paths for 4xx/5xx or missing data
- [ ] Add timeouts, retry logic, and circuit-break behavior
- [ ] Add methods for richer token data needed by signal quality filters

### `pumpfun_trading/sdk/execution.py`
- [ ] Add execution health checks
- [ ] Add slippage and fee validation
- [ ] Add transaction queue or lock to prevent duplicate sends
- [ ] Add safer confirmation handling and error classification

### `pumpfun_trading/bot/strategy.py`
- [ ] Expand strategy config with risk limits and signal thresholds
- [ ] Add strategy presets with different risk profiles
- [ ] Add scoring thresholds and cooldown logic

### `pumpfun_trading/tests/`
- [ ] Add tests for risk limit enforcement
- [ ] Add tests for state restoration and restart recovery
- [ ] Add tests for API fallback behavior
- [ ] Add tests for execution failure paths and retry logic
- [ ] Add tests for strategy scoring and buy filters

## Suggested sprint plan

### Sprint 1: Safe running bot [in progress]
- [x] risk limits
- [x] kill-switches
- [x] trade ledger
- [ ] health monitoring
- [x] test coverage for safety logic

### Sprint 2: Audit trail investigation and forensic tooling
- audit log search and filtering CLI
- record-type, state, mint, date, name, and reason filters
- JSON + table output and summary views
- export helpers for incident review

### Sprint 3: Runtime decomposition and first-release gate
- split bot runtime into orchestrator, lifecycle, risk, audit, execution, dashboard modules
- define release-gating checklist for v1
- dry-run safety validation and environment documentation
- ensure audit trail is searchable and reviewable before public release

### Sprint 4: Better entry quality
- richer token scoring
- signal filters
- better market data checks
- execution retries and re-evaluation

### Sprint 5: Replay and validation
- backtesting engine
- paper-trading mode
- historical replay and metrics
- strategy comparisons

### Sprint 6: Production readiness
- persistence and restoration
- alerting and observability
- security hardening
- operational playbook and deployment checklist

### Sprint 7: Operational scale and resilience
- broader monitoring stack
- deployment hardening
- incident response runbooks
- ongoing performance tuning

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
