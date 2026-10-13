# Next 30 Days: Pre-Production Testing & Deployment Execution Plan

This document establishes the active, day-by-day 30-day pre-production testing roadmap. Its primary objective is to maximize operational reliability, minimize downside risk, and empirically validate the trading platform before authorizing any capital deployment.

---

## 1. Executive Summary & Core Objective

The next 30 days transition the platform from **Stage 2 (Completed Modular Development)** to **Stage 3 (Pre-Production Empirical Verification)**. All activities focus on proving that the trading bot is:
- **Mathematically Sound:** Generates positive risk-adjusted expectancy ($PF \ge 1.40$) without curve-fitting.
- **Resilient to Hostile Environments:** Seamlessly handles RPC dropouts, sandwich MEV attacks, stream disconnects, and volatile market crashes.
- **Operationally Deterministic:** Executes trailing stops, tiered scaling, and circuit breakers with zero state loss or memory leaks.
- **Strictly Audited:** Enforces zero-credential leakage and complete JSONL audit accountability.

### Testing Environment Layout & Output Routing
- **Execution Working Directory:** `runtime/` (all CLI executions, test pilot processes, and audit inspections run inside the `runtime` directory).
- **Configuration Directory:** `configs/` (under `runtime/configs/`, storing dedicated test profiles such as `configs/preprod_pilot.json`, `configs/conservative_test.json`, `configs/balanced_test.json`, `configs/aggressive_test.json`, `configs/replay_test.json`, and `configs/devnet_test.json`).
- **Test Data & Outputs Directory:** `test-data/` (under `runtime/test-data/`, where all status snapshots `test-data/bot_status.json`, audit logs `test-data/audit_trail.jsonl`, and historical market captures `test-data/historical_captures.jsonl` are routed).

---

## 2. 30-Day Execution Timeline Overview

```
Phase 1 (Days 1–7):   Deterministic Code Quality & Historical Strategy Benchmark
Phase 2 (Days 8–15):  Subsystem Fault-Injection, MEV Hardening & Security Audit
Phase 3 (Days 16–25): Long-Running Continuous Paper-Trading Pilot (Live Feeds)
Phase 4 (Days 26–30): Incident Drills, Gate Sign-Off & Micro-Deployment Readiness
```

---

## 3. Phase-by-Phase Day-by-Day Workstreams

### Phase 1: Deterministic Quality & Strategy Benchmark (Days 1–7)

#### Days 1–2: Test Suite Baselines & Static Analysis Hardening (Gate 0)
- **Objective:** Verify 100% test passing status, zero type regressions, and strict code formatting across all modules.
- **Daily Tasks:**
  1. Execute `ruff check .` and resolve any stylistic or unused variable warnings.
  2. Execute `mypy pumpfun_trading` under strict mode to ensure type safety.
  3. Execute full 288+ test suite with code coverage analysis (`pytest --cov=pumpfun_trading`).
- **Commands to Run:**
  ```bash
  ruff check .
  mypy pumpfun_trading
  pytest -v --cov=pumpfun_trading --cov-report=term-missing pumpfun_trading/tests
  ```
- **Exit Criteria:** 0 lint errors, 0 type errors, 288/288 passing tests, total code coverage $\ge 90\%$.

#### Days 3–5: Historical Replay Validation & Strategy Optimization (Gate 1)
- **Objective:** Run historical replay simulations across bull, bear, and choppy bonding curve market captures.
- **Daily Tasks:**
  1. Compile a multi-session capture dataset (`test-data/historical_captures.jsonl`) encompassing $\ge 10,000$ trade events.
  2. Execute replay simulations for `conservative`, `balanced`, and `aggressive` presets using corresponding configs in `configs/`.
  3. Calculate and document Sharpe ratio, Profit Factor, Maximum Drawdown, and Win Rate.
  4. Perform out-of-sample walk-forward validation across partitioned time blocks.
- **Commands to Run:**
  ```bash
  # Run baseline replay dashboard (from runtime directory)
  python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl --mode dashboard --config configs/replay_test.json

  # Benchmark presets using sample configuration files
  python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/conservative_test.json
  python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/balanced_test.json
  python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/aggressive_test.json
  ```
- **Exit Criteria:** Profit Factor $\ge 1.40$, Max Drawdown $\le 15\%$, win rate $\ge 45\%$.

#### Days 6–7: Anti-Rug & Wash-Trading Heuristic Stress Testing
- **Objective:** Calibrate creator history profiling, Gini concentration limits, and order flow velocity Z-scores.
- **Daily Tasks:**
  1. Stress-test `TokenEnricher` against known creator dump histories and blacklist lookups.
  2. Test `OrderFlowEngine` against synthetic wash-trading traffic (single wallet churn).
  3. Run unit tests for anti-rug filters and momentum triggers.
- **Commands to Run:**
  ```bash
  pytest -v pumpfun_trading/tests/test_anti_rug_filters.py pumpfun_trading/tests/test_order_flow_momentum.py
  ```
- **Exit Criteria:** $100\%$ rejection of single-wallet volume manipulation and creator-dump candidates.

---

### Phase 2: Subsystem Fault-Injection, MEV Hardening & Security Audit (Days 8–15)

#### Days 8–9: Risk Engine, Dynamic Exits & Circuit Breakers (Gate 2)
- **Objective:** Validate stop-loss, trailing stops, tiered scaling, and daily portfolio drawdown locks under extreme price movements.
- **Daily Tasks:**
  1. Simulate sudden $-50\%$ price drops to verify instant stop-loss triggering.
  2. Simulate parabolic $+500\%$ pumps to verify 2.0x (50%), 3.5x (25%), and trailing moonbag execution.
  3. Trigger daily equity drawdown limits ($20\%$) to verify automatic cessation of buy operations.
  4. Test emergency panic liquidation of all active positions.
- **Commands to Run:**
  ```bash
  pytest -v pumpfun_trading/tests/test_trailing_and_tiered_exits.py
  pytest -v pumpfun_trading/tests/test_portfolio_circuit_breaker.py
  pytest -v pumpfun_trading/tests/test_order_executor.py
  ```
- **Exit Criteria:** 100% stop-loss fidelity, panic liquidation batch closure $<3.0$ seconds.

#### Days 10–11: Multi-RPC Load Balancing & Jito MEV Execution (Gate 3)
- **Objective:** Stress test high-availability RPC pooling and private mempool transaction routing.
- **Daily Tasks:**
  1. Simulate RPC node timeouts and 429 rate limits; verify circuit breaker state transitions (`HEALTHY` $\to$ `DEGRADED` $\to$ `OPEN`).
  2. Verify transaction broadcast across multiple RPC endpoints concurrently.
  3. Validate Jito bundle construction, validator tip calculation, and fallback to direct RPC.
- **Commands to Run:**
  ```bash
  pytest -v pumpfun_trading/tests/test_rpc_pool.py pumpfun_trading/tests/test_rpc_pool_bot_integration.py
  pytest -v pumpfun_trading/tests/test_jito_execution_integration.py pumpfun_trading/tests/test_execution_sdk_full.py
  ```
- **Exit Criteria:** Read queries routed to lowest-latency RPC with 0 dropped events, Jito tip retry & RPC fallback cleanly executed.

#### Days 12–13: Security Audit, Secrets Hygiene & Keypair Isolation (Gate 4)
- **Objective:** Ensure complete isolation of sensitive keys and credentials across the codebase and runtime environments.
- **Daily Tasks:**
  1. Execute automated grep scans across git history and untracked files for key leaks.
  2. Verify environment file permission enforcement (`chmod 600 .envrc`).
  3. Validate hot wallet boundary controls and treasury isolation.
- **Commands to Run:**
  ```bash
  git grep -iE "(private_key|secret_key|api_key|token|password)" -- ":(exclude)*.sample" ":(exclude)*.md" ":(exclude)*tests*"
  test -f .envrc && stat -f "%Sp %N" .envrc | grep -E "^-rw-------"
  ```
- **Exit Criteria:** 0 exposed credentials, `.envrc` permissions strictly 600, hot wallet trading balance cap $\le 2.0$ SOL.

#### Days 14–15: Persistence Crash Recovery & Audit Trail Integrity (Gate 5)
- **Objective:** Confirm 100% state restoration on unexpected bot process termination.
- **Daily Tasks:**
  1. Verify atomic writing of `test-data/bot_status.json` via file rename semantics.
  2. Test `safe_startup()` position and cost-basis restoration from saved snapshots.
  3. Validate JSONL audit trail formatting and summary export tools.
- **Commands to Run:**
  ```bash
  pytest -v pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py
  pytest -v pumpfun_trading/tests/test_audit_tool.py pumpfun_trading/tests/test_audit_full.py
  python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --summary
  ```
- **Exit Criteria:** 100% state restoration with zero phantom orders, audit log export matches record count.

---

### Phase 3: Automated Long-Running Paper Trading Pilot (Days 16–25)

#### Days 16–18: Initial 48-Hour Live Paper Run (Gate 6 - Phase A)
- **Objective:** Deploy bot in paper-trading mode on live Yellowstone Geyser / WebSocket feeds to observe real-time stream ingestion.
- **Execution Command:**
  ```bash
  # Start from runtime directory using preprod pilot configuration
  python -m pumpfun_trading.cli.bot --paper-trade --config configs/preprod_pilot.json
  ```
- **Daily Tasks:**
  1. Monitor active WebSocket / Geyser stream connectivity and reconnect logs.
  2. Inspect memory usage (`ps -o rss`) and CPU utilization.
  3. Confirm snapshot updates in `test-data/bot_status.json`.

#### Days 19–22: Volatility Stress & Multi-Channel Alert Verification
- **Objective:** Evaluate bot performance during volatile market hours and verify webhook alerts.
- **Daily Tasks:**
  1. Verify entry and exit alerts delivered to Discord / Telegram webhooks with zero event loop lag.
  2. Audit all paper trade executions against on-chain transaction pricing.
  3. Validate dynamic slippage adjustments and retry loops on volatile price spikes.

#### Days 23–25: Unbroken 72-Hour Continuous Run (Gate 6 - Phase B)
- **Objective:** Complete an uninterrupted 72-hour paper pilot satisfying Gate 6 criteria.
- **Commands to Run:**
  ```bash
  # Check status snapshot health
  cat test-data/bot_status.json | jq '{status, active_positions: .active_positions | length, total_trades: .metrics.total_trades, uptime: .uptime_seconds}'

  # Audit recent events
  python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --limit 20
  ```
- **Exit Criteria:** Continuous 72-hour uptime, RSS memory $\le 250$ MB, zero unhandled errors, 100% audit logging.

---

### Phase 4: Release Readiness, Incident Drills & Sign-Off (Days 26–30)

#### Days 26–27: Operational Runbook Drills & Incident Response Simulation
- **Objective:** Train operators on emergency procedures, kill switches, and post-incident forensics.
- **Daily Tasks:**
  1. Practice emergency shutdown (`SIGINT` and `SIGTERM`) and confirm clean state flushing.
  2. Simulate network disconnect and verify bot state preservation.
  3. Replay simulated bad trades using the audit trail export CLI.
- **Reference:** Follow `docs/dev/RUNBOOK.md` Step 4 & 5.

#### Days 28–29: Master Release Gate Evaluation
- **Objective:** Conduct formal audit against all 7 gates in `docs/dev/RELEASE-GATE.md`.
- **Daily Tasks:**
  1. Compile test logs, coverage reports, replay benchmark outputs, and 72-hour pilot telemetry.
  2. Audit checklist items in `docs/dev/RELEASE-GATE.md`.
  3. Draft final Pre-Production Verification Report.

#### Day 30: Formal Go / No-Go Decision & Staged Rollout Approval
- **Objective:** Make evidence-based Go / No-Go decision for controlled live staging.
- **Decision Outcome:**
  - **GO:** Authorize controlled micro-pilot ($\le 0.5$ SOL bankroll, strictly limited position caps) under active operator monitoring.
  - **NO-GO:** If any gate fails, revert to tuning cycle and reschedule pilot.

---

## 4. Pre-Production Command Reference Matrix

| Goal | Command | Primary Validation Target |
| :--- | :--- | :--- |
| **Lint & Format** | `ruff check .` | 0 errors |
| **Type Check** | `mypy pumpfun_trading` | 0 type violations |
| **Full Test Suite** | `pytest -v --cov=pumpfun_trading pumpfun_trading/tests` | 288+ tests pass, $>90\%$ cov |
| **Historical Replay** | `python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl --config configs/replay_test.json` | Profit Factor $\ge 1.40$ |
| **Risk & Circuit Breakers** | `pytest -v pumpfun_trading/tests/test_portfolio_circuit_breaker.py` | 100% stop-loss & DD stops |
| **Audit Log Inspection** | `python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --summary` | 100% audit accounting |
| **Live Paper Pilot** | `python -m pumpfun_trading.cli.bot --config configs/preprod_pilot.json` | 72h continuous uptime |

---

## 5. Related Documentation

- `RELEASE-GATE.md` - Formal 7-gate acceptance criteria and signoff checklist.
- `RUNBOOK.md` - Operator runtime procedures and emergency response workflows.
- `TODO.md` - Historical backlog and completed engineering sprints.
- `../USER-GUIDE.md` - Configuration parameters, environment variables, and CLI reference.

