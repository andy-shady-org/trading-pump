# Pre-Production Release Gate & Verification Framework

This document defines the strict, quantitative release gates required before any controlled deployment or capital allocation. Every gate is designed to maximize expected value, eliminate avoidable failure modes, protect capital reserves, and guarantee operational determinism under volatile market conditions.

---

## 1. Release Status & Staging Policy

- **Current Status:** Internal Pre-Production Candidate (Stage 3 Verification).
- **Execution Mandate:** Strictly non-funded execution (paper-trading or dry-run) until all 7 gates achieve 100% verified compliance.
- **Target Deployment:** Controlled single-instance runtime operating within hard-coded capital and drawdown boundaries.
- **Execution Environment Layout:**
  - **Working Directory:** `runtime/` (all test execution, background pilots, and CLI auditing run from the `runtime` root).
  - **Configuration Directory:** `configs/` (under `runtime/configs/` containing structured JSON profiles for all testing scenarios).
  - **Outputs & Telemetry Directory:** `test-data/` (under `runtime/test-data/` receiving runtime status snapshots `test-data/bot_status.json`, audit records `test-data/audit_trail.jsonl`, and replay captures `test-data/historical_captures.jsonl`).

---

## 2. Gate Overview & Flow

```
[ Gate 0: Code Quality & Unit Coverage ]
                   │
                   ▼
[ Gate 1: Strategy Benchmark & Historical Replay ]
                   │
                   ▼
[ Gate 2: Risk Controls, Exits & Circuit Breakers ]
                   │
                   ▼
[ Gate 3: Network Infrastructure, RPC & MEV Bundling ]
                   │
                   ▼
[ Gate 4: Security, Secrets & Wallet Isolation ]
                   │
                   ▼
[ Gate 5: Persistence, State Restoration & Audit Trail ]
                   │
                   ▼
[ Gate 6: 72-Hour Continuous Live Paper Pilot ]
                   │
                   ▼
        [ Controlled Go / No-Go Signoff ]
```

---

## 3. Detailed Gate Specifications & Verification Runbook

### Gate 0: Code Hygiene, Static Analysis & Test Coverage

Ensures the codebase is free of syntax errors, type regressions, dead code, and unhandled branches, maintaining high automated test coverage.

#### Verification Commands
```bash
# 1. Format and Linting Check
ruff check .

# 2. Strict Type Safety Analysis
mypy pumpfun_trading

# 3. Comprehensive Test Suite Execution with Coverage
pytest -v --cov=pumpfun_trading --cov-report=term-missing pumpfun_trading/tests
```

#### Quantitative Acceptance Criteria
- `ruff check .` passes with **0 errors and 0 warnings**.
- `mypy` completes with **0 type violations**.
- All **288+ unit and integration tests** pass cleanly with **0 failures and 0 skipped tests**.
- Total statement coverage across `pumpfun_trading` exceeds **90%** (with core risk and execution modules at **>95%**).

---

### Gate 1: Strategy Benchmark & Empirical Validation

Validates that trading strategies (discovery, momentum breakouts, graduation sniping, copy-trading) produce positive risk-adjusted expectancy and withstand choppy market regimes without catastrophic drawdowns.

#### Verification Commands
```bash
# 1. Historical Replay Benchmark on Standard Capture (from runtime directory)
python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl --mode dashboard --config configs/replay_test.json

# 2. Replay Verification across Strategy Presets and Configs
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/conservative_test.json
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/balanced_test.json
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/aggressive_test.json

# 3. Strategy Modularity & Heuristic Safety Tests
pytest -v pumpfun_trading/tests/test_replay_engine.py pumpfun_trading/tests/test_strategy_modularity.py pumpfun_trading/tests/test_strategy_safety.py
```

#### Quantitative Acceptance Criteria
- **Profit Factor:** $\ge 1.40$ on balanced preset across representative replay datasets.
- **Maximum Drawdown:** $\le 15.0\%$ of cumulative equity across backtest sessions.
- **Win Rate:** $\ge 45\%$ with an average win-to-loss payoff ratio $\ge 2.2:1$.
- **Wash-Trading Rejection Rate:** $100\%$ rejection of single-wallet volume manipulation in momentum tests (`test_order_flow_momentum.py`).
- **Anti-Rug Heuristic Accuracy:** $100\%$ rejection of creator-dump and high-Gini concentration tokens (`test_anti_rug_filters.py`).

---

### Gate 2: Risk Controls, Dynamic Exits & Circuit Breakers

Guarantees that capital preservation mechanisms (trailing stops, multi-tier partial scaling, daily drawdown circuit breakers, panic liquidations) operate with deterministic priority.

#### Verification Commands
```bash
# 1. Trailing Stop and Multi-Tier Take-Profit Verification
pytest -v pumpfun_trading/tests/test_trailing_and_tiered_exits.py pumpfun_trading/tests/test_position_manager.py

# 2. Portfolio Drawdown Circuit Breaker & Emergency Liquidation
pytest -v pumpfun_trading/tests/test_portfolio_circuit_breaker.py pumpfun_trading/tests/test_order_executor.py

# 3. Risk Engine State & Health Checks
pytest -v pumpfun_trading/tests/test_risk_health_execution.py
```

#### Quantitative Acceptance Criteria
- **Stop-Loss Enforcement:** Stop-loss executes within 1 tick upon breaching threshold (default $-15\%$).
- **Trailing Stop Activation:** Trailing stop engages at peak return $\ge +30\%$ and locks in profit on pullback (default $10\%$ drop from peak).
- **Tiered Profit Scaling:** 
  - Tier 1 (2.0x): Automatically liquidates 50% lot size.
  - Tier 2 (3.5x): Automatically liquidates 25% lot size.
  - Tier 3 (Moonbag): Retains 25% remaining position under active trailing stop.
- **Daily Equity Drawdown Limit:** All buy signals immediately blocked when daily realized + unrealized drawdown reaches configured cap (default $20\%$).
- **Panic Liquidation:** Emergency liquidation loop executes batch position sales across all holdings in $<3.0$ seconds without deadlocks.

---

### Gate 3: Network Infrastructure, Multi-RPC Load Balancing & MEV Protection

Verifies that the networking layer sustains high-throughput market streams (Yellowstone Geyser gRPC / WebSocket), automatically balances RPC loads, handles latency degradation, and routes private transactions via Jito Block Engine.

#### Verification Commands
```bash
# 1. Multi-RPC Connection Pool & Latency Failover Tests
pytest -v pumpfun_trading/tests/test_rpc_pool.py pumpfun_trading/tests/test_rpc_pool_bot_integration.py

# 2. Jito MEV Bundle & Fallback Execution Tests
pytest -v pumpfun_trading/tests/test_jito_sdk.py pumpfun_trading/tests/test_jito_execution_integration.py pumpfun_trading/tests/test_execution_sdk_full.py

# 3. Yellowstone Geyser Stream Resilience & Reconnection
pytest -v pumpfun_trading/tests/test_geyser_stream.py pumpfun_trading/tests/test_geyser_bot_integration.py pumpfun_trading/tests/test_market_data_resilience.py
```

#### Quantitative Acceptance Criteria
- **Multi-RPC Failover:** Dynamic circuit breaker transitions between `HEALTHY`, `DEGRADED`, `OPEN`, and `HALF_OPEN` within 3 consecutive probe failures.
- **Read Routing:** Fast routing directs $\ge 90\%$ of read queries to the lowest $p_{50}$ latency RPC provider.
- **Jito MEV Bundling:** Private bundle submission constructs valid tip instructions and adheres to tip caps (default 0.0001–0.001 SOL).
- **RPC Fallback:** If Jito confirmation times out ($>12.0$s), execution cleanly falls back to high-priority direct RPC without double-spending.
- **Stream Recovery:** Geyser/WebSocket stream reconnects within $\le 5.0$ seconds on simulated socket severance, resuming event consumption without unbounded memory growth.

---

### Gate 4: Security, Secrets Hygiene & Wallet Isolation

Ensures private keys, API credentials, and webhooks are never exposed, logged, or co-mingled with unprivileged processes.

#### Verification Commands
```bash
# 1. Git Repository Scan for Accidental Credentials
git grep -iE "(private_key|secret_key|api_key|token|password)" -- ":(exclude)*.sample" ":(exclude)*.md" ":(exclude)*tests*"

# 2. Filesystem Permissions Check for Environment Files
test -f .envrc && stat -f "%Sp %N" .envrc | grep -E "^-rw-------"

# 3. Validation of Keypair Loading Isolation
python -c "
from pumpfun_trading.config.env import load_keypair_from_env
kp = load_keypair_from_env()
print('Keypair loaded successfully:', kp is not None)
"
```

#### Quantitative Acceptance Criteria
- **Zero Committed Secrets:** 0 private keys, bearer tokens, or webhook URLs in tracked files.
- **File Permissions:** Local environment configuration (`.envrc` or deployment secrets) must have restricted permissions (`chmod 600`).
- **Hot Wallet Segregation:** Trading keypair must be an isolated hot wallet holding no more than operational trading capital (e.g., $\le 2.0$ SOL for test runs).
- **Sanitized Logging:** Audit trails and status snapshots must never serialize raw private keys or seed phrases.

---

### Gate 5: Persistence, State Restoration & Audit Trail Integrity

Validates that runtime status snapshots (`test-data/bot_status.json`) and append-only audit records (`test-data/audit_trail.jsonl`) maintain 100% accounting fidelity across unexpected process crashes and restarts.

#### Verification Commands
```bash
# 1. Persistence & Lifecycle Resilience Tests
pytest -v pumpfun_trading/tests/test_bot_subsystems.py pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py pumpfun_trading/tests/test_position_manager.py

# 2. Audit Trail Tool & Export CLI Verification
pytest -v pumpfun_trading/tests/test_audit_tool.py pumpfun_trading/tests/test_audit_full.py

# 3. Audit Log Summary Inspection on Test Output (from runtime directory)
python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --summary
```

#### Quantitative Acceptance Criteria
- **Atomic Snapshots:** `test-data/bot_status.json` written atomically via temporary file rename, eliminating partial-write file corruption.
- **Crash Recovery (`safe_startup`):** Restarting a terminated bot recovers all active positions, cost bases, peak prices, and partial exit tier states without duplicate buys or dropped positions.
- **Audit Completeness:** Every signal generation, anti-rug rejection, order submission, fill confirmation, and exit trigger logs a typed, ISO-timestamped JSONL entry to `test-data/audit_trail.jsonl`.
- **CLI Export:** `python -m pumpfun_trading.cli.main audit --path <file> --export <out.json>` produces valid JSON matching loaded record count.

---

### Gate 6: 72-Hour Continuous Live Paper Pilot

Executes a non-stop, 72-hour paper-trading pilot on live Solana mainnet/devnet streams within the `runtime/` environment to verify memory stability, real-time event loop latency, and alerting integration under real market traffic.

#### Execution Command
```bash
# Start 72-Hour Live Paper Pilot in Background from runtime/ directory
python -m pumpfun_trading.cli.bot \
  --paper-trade \
  --config configs/preprod_pilot.json
```

#### Operational Monitoring Checklist
```bash
# 1. Real-Time Status Verification
cat test-data/bot_status.json | jq '{status, active_positions: .active_positions | length, total_trades: .metrics.total_trades, uptime: .uptime_seconds}'

# 2. Audit Event Inspection
python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --limit 10

# 3. Memory & Process Stability
ps -o pid,vsz,rss,comm -p $(pgrep -f "pumpfun_trading.cli.bot")
```

#### Quantitative Acceptance Criteria
- **Continuous Uptime:** $100\%$ process uptime over 72 hours (0 unhandled crashes or fatal event loop deadlocks).
- **Memory Footprint:** Resident Set Size (RSS) stays stable $\le 250$ MB with no monotonic memory growth.
- **Event Latency:** Ingestion-to-evaluation pipeline processes streaming events in $\le 5.0$ ms.
- **Alert Dispatch:** $100\%$ of exit triggers and circuit breaker events deliver webhook alerts without blocking the event loop.

---

## 4. Master Release Gate Verification Checklist

| Gate ID | Domain | Primary Verification Command | Required Outcome | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Gate 0** | Code Quality | `pytest -v --cov=pumpfun_trading` & `ruff check .` | 0 errors, 288+ tests pass, >90% cov | [ ] |
| **Gate 1** | Strategy Benchmark | `python -m pumpfun_trading.cli.main replay --path test-data/...` | Profit Factor $\ge 1.40$, Max DD $\le 15\%$ | [ ] |
| **Gate 2** | Risk Controls | `pytest pumpfun_trading/tests/test_portfolio_circuit_breaker.py` | 100% stop-loss & tiered exit execution | [ ] |
| **Gate 3** | Network & MEV | `pytest pumpfun_trading/tests/test_rpc_pool.py test_jito_sdk.py` | Multi-RPC failover & Jito bundle pass | [ ] |
| **Gate 4** | Security & Secrets | `git grep -iE "(private_key|api_key)"` & `chmod 600 .envrc` | 0 committed keys, isolated hot wallet | [ ] |
| **Gate 5** | Persistence & Audit | `pytest pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py` | Atomic snapshot & crash recovery pass | [ ] |
| **Gate 6** | 72h Paper Pilot | `python -m pumpfun_trading.cli.bot --config configs/preprod_pilot.json` | 72h uptime, RSS $<250$MB, 0 deadlocks | [ ] |

---

## 5. Formal Go / No-Go Decision Policy

### Mandatory "GO" Conditions
A **GO** decision is authorized **only** when all of the following conditions are simultaneously satisfied:
1. All 7 release gates (Gate 0 through Gate 6) are marked as verified with documented logs.
2. Strategy benchmark demonstrates positive risk-adjusted expectancy across historical captures in `test-data/`.
3. 72-hour paper pilot concludes with zero unhandled exceptions and complete state recovery in `test-data/bot_status.json`.
4. Designated system operator signs off on runbook procedures and emergency stop protocols.

### Immediate "NO-GO" Triggers
Any of the following conditions triggers an immediate **NO-GO** and halts deployment:
- Any test failure in the 288+ test regression suite.
- Unhandled memory leak (RSS increasing continuously over pilot window).
- Discovered plaintext credential or improper file permissions on secret stores.
- Failure of trailing stop or stop-loss to trigger on adverse price movement in replay or pilot.
- Status snapshot corruption or inability to restore state during simulated crash recovery.

---

## 6. Incident Escalation & Rollback Plan

If an operational anomaly occurs during pre-production or initial live pilot:

1. **Immediate Halt:** Issue `SIGINT` (Ctrl+C) or execute emergency stop command.
2. **State Freeze:** Archive `test-data/bot_status.json` and `test-data/audit_trail.jsonl` with timestamp for forensic analysis.
3. **Wallet Inspection:** Query on-chain wallet balance and token accounts via RPC pool to verify zero leaked funds.
4. **Root Cause Analysis:** Replay the incident trade sequence using `python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl` to diagnose failure.
5. **Remediation & Gate Reset:** Apply code fix, re-run all regression test suites, and reset Gate 6 (72h pilot).

---

## 7. Related References

- `NEXT-30-DAYS.md` - 30-day pre-production milestone execution schedule.
- `RUNBOOK.md` - Operator procedures for startup, shutdown, and incident management.
- `TODO.md` - Sprint delivery roadmap and completed feature matrix.
- `../USER-GUIDE.md` - Comprehensive configuration and CLI operational guide.

