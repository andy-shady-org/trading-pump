# Proposed Features & Architectural Enhancements

This document tracks candidate architectural enhancements, alpha generation strategies, execution optimizations, and production features under consideration for `pumpfun-trading`.

All features documented here represent proposed capabilities that have **not yet been implemented** and are evaluated for potential inclusion in future development sprints. For the catalog of completed and actively supported features, refer to [**`docs/FEATURES.md`**](../FEATURES.md).

---

## 1. High-Alpha Trading & Execution Enhancements

### FEAT-23: Dynamic Volatility-Aware Slippage & Adaptive Priority Fee Engine
* **Goal:** Maximize execution net yield, minimize MEV slippage extraction, and eliminate failed exit orders during extreme bonding curve price volatility.
* **Architecture:**
  - **Real-Time Bonding Curve Volatility Estimator:**
    - Computes instantaneous price velocity ($\Delta P / \Delta t$) and bonding curve depth consumption ($\Delta x / x_{\text{virtual}}$) from Yellowstone Geyser gRPC state updates.
    - Dynamically scales slippage tolerance ($S_{\text{dynamic}} = S_{\text{base}} + \alpha \cdot \sigma_{\text{volatility}} + \beta \cdot \text{PriceImpact}$) within configured minimum/maximum bounds.
  - **Congestion & Urgency-Adaptive Compute Budget Scaling:**
    - Dynamically calculates Solana compute unit priority fees (`SetComputeUnitPrice`) and Jito tip percentiles based on trade urgency (e.g. explosive momentum entry vs. emergency stop-loss liquidation).
    - Automatically tightens slippage during low-volatility regimes to prevent MEV sandwich attacks and widens slippage during parabolic spikes or dumps to guarantee 100% single-slot transaction inclusion.
* **Financial Impact:** Eliminates 30%–50% of unnecessary slippage drag on standard trades while saving 15%–25% in realized capital preservation by preventing transaction dropouts during fast market sell-offs.

### FEAT-24: Opportunistic Capital Rotation & High-Conviction Displacement Engine
* **Goal:** Maximize portfolio capital velocity and compounded expected return by continuously recycling capital out of stagnant or low-momentum positions into newly discovered high-alpha breakout opportunities.
* **Architecture:**
  - **Continuous Position Expected Value (EV) Scoring:**
    - Real-time ranking engine evaluating open positions and incoming stream candidates on composite alpha metrics: order flow Z-score, net capital inflow rate, holder distribution Gini coefficient, and curve velocity.
  - **Autonomous Capital Displacement & Reallocation:**
    - When maximum active positions (`max_active_positions`) or total exposure caps (`max_total_exposure_sol`) are reached, incoming 95th+ percentile conviction signals evaluate relative EV against active holdings.
    - If a candidate's expected return significantly exceeds the weakest stagnant position (taking into account round-trip exit/entry fees and slippage friction), the engine atomically initiates a graceful exit of the low-conviction asset and reallocates capital to the high-conviction breakout.
* **Financial Impact:** Eliminates deadweight capital lockup on flat/slow-moving bonding curves, multiplying portfolio capital turnover and dramatically accelerating cumulative ROI compounding.

### FEAT-25: Predictive Graduation Curve Acceleration & Pre-Migration Liquidity Harvester
* **Goal:** Identify, predict, and front-run the parabolic final acceleration phase of bonding curves approaching Raydium graduation (~80–85 SOL reserve / $69k market cap) to capture high-probability liquidity transition premiums.
* **Architecture:**
  - **Curve Supply Depletion & Inflow Acceleration Modeling:**
    - Real-time mathematical modeling of remaining curve token reserves, cumulative buy velocity, and unique buyer influx rate.
    - Classifies bonding curves nearing migration into deterministic trajectory regimes (e.g. steady organic accumulation, syndicate sweep, or volume exhaustion).
  - **Staged Pre-Graduation Entry & Scaled Take-Profit Tranches:**
    - Triggers automated entry when curve progress reaches 70%–85% with sustained net positive order flow.
    - Deploys limit-style take-profit scaling (e.g. 30% at 92% curve completion, 30% at 97% completion, 40% riding into the Raydium pool seeding event) to lock in gains before post-migration volatility.
* **Financial Impact:** Captures high-probability 30%–80% rapid capital gains during the terminal bonding curve rush with minimal downside exposure duration.

---

## 2. Advanced Market Analytics & Strategy Expansion

### FEAT-26: On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector
* **Goal:** Detect multi-wallet insider syndicates, distributed bundle trees, and synthetic volume churn before committing trading capital.
* **Architecture:**
  - **Graph-Based Wallet Relationship Mapping:**
    - Queries recent transaction graphs and funding origins (e.g. root SOL transfers, intermediary splitters, exchange withdrawal hot-wallets) for the top 10 holders and creator wallet at token creation block.
    - Computes an **Insider Cluster Concentration Index ($0.0–1.0$)** measuring what fraction of circulating supply is controlled by common-origin wallet clusters.
  - **Sybil Wash-Trading Filter:**
    - Identifies circular buy/sell patterns and coordinated micro-swaps between clustered wallets designed to artificially inflate trade velocity and order flow Z-scores.
    - Rejects tokens with high cluster concentration ($\ge 0.25$) or confirmed sybil volume, preventing entry into coordinated dump schemes.
* **Financial Impact:** Protects trading capital against organized syndicate dump schemes (which represent over 70% of fatal microcap rug-pull losses) and prevents false-positive momentum entries triggered by wash trading.

### FEAT-27: Automated Strategy Parameter Auto-Tuning & Hyperparameter Backtest Optimizer
* **Goal:** Continuously maximize strategy profitability and adapt to shifting market volatility regimes by automating hyperparameter tuning over empirical replay datasets.
* **Architecture:**
  - **Multi-Objective Optimization Engine:**
    - Integrates a Bayesian / Genetic optimization pipeline utilizing `PaperTradingEngine` and compressed `.jsonl.gz` datasets generated by `ReplayRecorder`.
    - Optimizes core strategy parameters simultaneously: fractional Kelly sizing ($f^*$), take-profit multiplier tiers (Tier 1/2), trailing stop peak drop percentages, inactivity exit timeouts, and order flow momentum Z-score thresholds.
  - **Fitness Function & Overfitting Guard:**
    - Evaluates performance using cross-validated objective functions targeting maximum Sharpe ratio, Sortino ratio, Profit Factor, and minimal Calmar drawdown under realistic on-chain fee and slippage friction.
    - Generates actionable configuration presets (`conservative`, `balanced`, `aggressive`, `high_volatility`) with automated export into `TradingBotConfig` JSON format.
* **Financial Impact:** Dynamically maintains optimal mathematical edge across changing market cycles, maximizing compounded portfolio returns while preventing strategy decay.

### FEAT-28: Atomic Jito Back-Running & Cross-Venue Arbitrage Engine
* **Goal:** Capture risk-free, delta-neutral arbitrage spreads between graduating Pump.fun bonding curves and external DEX liquidity pools (Raydium, Meteora, Orca) as well as mempool back-running opportunities.
* **Architecture:**
  - **Cross-Venue Spot Disparity Monitor:**
    - Sub-millisecond price discrepancy tracker comparing Pump.fun virtual curve spot prices with Raydium AMM pools during and immediately following token graduation.
  - **Atomic Multi-Hop Jito Bundle Execution:**
    - Constructs atomic transaction bundles executing simultaneous multi-leg swaps (e.g. Buy on Pump.fun bonding curve + Sell on Raydium AMM) with zero inventory risk.
    - Bundles are submitted exclusively through private Jito block engines with dynamic tip sharing, ensuring that if price parity shifts before execution, the entire bundle atomically fails with zero capital loss.
* **Financial Impact:** Unlocks an uncorrelated, zero-directional-risk revenue stream that monetizes liquidity inefficiencies during high-volume token graduations.

---

## 3. Reliability, Infrastructure & Risk Controls

### FEAT-22: Automated Log Retention, Multi-Sink Rollover & Dataset Compression Engine
* **Goal:** Eliminate unbounded disk growth and prevent OS I/O exhaustion, write latency spikes, or crashed trading sessions across continuous 24/7 runtime operations by implementing automated file rollover, background gzip compression, and lifecycle retention policies for application logs, forensic audit trails, and market replay streams.
* **Architecture & Capabilities:**
  - **Standardized Application Log Rollover & Gzip Compression:**
    - Size-based (`RotatingFileHandler`) and time-based (`TimedRotatingFileHandler`) rotation with custom non-blocking gzip compression hooks (`_gzip_rotator` / `_gzip_namer`) in `pumpfun_trading/ops/logging.py`.
    - Configurable file size limits (`PUMPFUN_LOG_MAX_BYTES`, default 10 MB) and backup retention counts (`PUMPFUN_LOG_BACKUP_COUNT`, default 5).
  - **Async Non-Blocking Sinks for High-Throughput Streams:**
    - Dedicated, thread-safe `RotatedFileSink` in `pumpfun_trading/ops/retention.py` used across forensic audit persistence (`StatusPersistenceManager` / `audit.jsonl`) and Geyser market stream recordings (`ReplayRecorder` / `market_replay.jsonl`).
    - Decoupled asynchronous background workers (`asyncio.to_thread`) executing atomic file rotations (`os.replace`) and inline gzip compression (`.gz`) without introducing latency jitter into critical trading event loops.
  - **Centralized Retention Engine & Storage Quota Enforcement:**
    - `LogRetentionManager` enforcing retention policies by age (e.g. `retention_days=30`), backup file count caps, and total directory byte limits with automatic expired archive pruning.
  - **Transparent Multi-File & Compressed Dataset Ingestion:**
    - Native decompression and multi-file glob ingestion across `load_audit_records` (`pumpfun-audit`) and `PaperTradingEngine.load_history` (`pumpfun-replay`), seamlessly querying across active `.jsonl` files and archived `.jsonl.gz` chunks.
  - **Operator Maintenance & Inspection CLI Surface:**
    - Unified CLI commands (`pumpfun ops prune --target <dir> --days <n>`, `pumpfun ops status`) for on-demand disk quota enforcement and storage telemetry.
* **System Utility & Reliability Impact:**
  - Protects 24/7 continuous trading execution from unexpected disk exhaustion, dropped transactions, and corrupted state snapshots.
  - Reduces disk storage consumption for historical market replays and audit trails by up to 80–90% through background gzip compression while preserving full historical queryability.

### FEAT-29: Adaptive Realized-Ratchet & Dual-Tier Portfolio Drawdown Engine
* **Goal:** Eliminate premature circuit breaker lockouts and false-positive panic liquidations on winning trading sessions (such as volatile multi-tier take-profit runners) while enforcing institutional-grade downside principal preservation and locking in accumulated profits.
* **Architecture & Capabilities:**
  - **Realized Profit Ratchet & Guaranteed Equity Baseline:**
    - Decouples volatile unrealized mark-to-market spikes from permanent portfolio baseline ratcheting.
    - When positions exit with net realized gains, a configurable profit retention ratio ($\alpha \in [0.0, 1.0]$, e.g. `profit_ratchet_ratio = 0.50`) permanently ratchets the **Effective Equity Baseline Floor**:
      $$\text{Baseline}_{\text{effective}} = \text{Starting Capital} + \alpha \times \max(0, \text{Cumulative Realized PnL})$$
  - **Dual-Zone Risk Evaluation Engine:**
    - **Principal Protection Zone (`Current Equity < Starting Capital`):** Strict capital preservation rules apply. If portfolio equity drops below $\text{Starting Capital} \times (1 - \text{max\_daily\_drawdown\_pct})$ (e.g. 15%–20% loss), emergency risk actions engage to preserve the initial bankroll.
    - **Profit Run Zone (`Current Equity >= Starting Capital`):** The bot operates with "house money" under a wider, configurable trailing drawdown buffer (`profit_drawdown_tolerance_pct`, e.g. 35%–45%) measured relative to the realized ratchet baseline. Transient mark-to-market pullbacks on open moonbag tranches no longer trip the daily circuit breaker.
  - **Tiered Two-Stage Circuit Breaker Actions:**
    - **Stage 1 (`HALT_NEW_BUYS`):** When the profit-zone trailing drawdown tolerance is breached, the bot pauses new token entries while allowing open positions to exit orderly via their dedicated trailing stop-loss rules (`FEAT-03`) and take-profit targets.
    - **Stage 2 (`EMERGENCY_LIQUIDATE`):** Full emergency market liquidation (`sell_all`) is strictly reserved for breaches of the hard **Principal Preservation Floor** or catastrophic market-wide dropouts.
  - **Configurable Risk Policies & Presets:**
    - Configurable `drawdown_reference_mode`: `"adaptive_ratchet"` (recommended default), `"baseline"` (strict starting principal anchor), or `"trailing_hwm"` (legacy strict peak-to-trough tracking).
* **System Utility & Financial Impact:**
  - Solves the critical drawdown lockout paradox where high-performing bots (+115% net PnL days) were prematurely frozen due to mark-to-market retracements on parabolic runners.
  - Guarantees complete capital preservation on losing streaks while giving winning trades the necessary breathing room to maximize upside compounding.

### FEAT-30: Structured Diagnostic Event Logging & Runtime Telemetry Persistence
* **Goal:** Capture comprehensive, microsecond-timestamped runtime events, internal state transitions, streaming network telemetry, and strategy decision matrices into dedicated, structured persistent log files (`events.jsonl` / `diagnostics.log`), enabling granular performance tuning, telemetry analysis, and rapid root-cause debugging far beyond standard financial audit ledgers and status snapshots.
* **Architecture & Capabilities:**
  - **Comprehensive Multi-Subsystem Event Instrumentation:**
    - Emits structured event payloads across all key engine phases:
      1. *Streaming Feed Telemetry:* Geyser gRPC / WebSocket slot latency, reconnection backoffs, dropped message counters, and parse latencies.
      2. *Candidate Discovery & Scoring:* Raw token detection, metadata resolution, anti-rug heuristic scoring breakdown (Gini coefficient, creator history, initial buy distribution), and exact pass/reject decision reasons.
      3. *Strategy & Sizing Pipeline:* Order flow momentum Z-scores, price velocity calculations, Kelly allocation fractions, and entry condition evaluations.
      4. *Execution SDK & MEV Routing:* Jito bundle assembly, tip tier calculations, confirmation timeouts, RPC fallback triggers, and on-chain compute unit usage.
      5. *Risk & Lifecycle Management:* Position state changes, trailing stop ratchet events, take-profit tier triggers, and circuit breaker evaluation snapshots.
  - **High-Throughput Non-Blocking JSONL Sink:**
    - Asynchronous event writer utilizing `RotatedFileSink` and background worker tasks (`asyncio.to_thread`), ensuring high-volume event emission (up to 5,000+ events/sec during volatile market bursts) introduces zero latency jitter into the critical trading execution loop.
  - **Configurable Subsystem Filters & Verbosity Levels:**
    - Granular environment and config variables (`PUMPFUN_EVENT_LOG_PATH`, `PUMPFUN_EVENT_LOG_LEVEL`, `PUMPFUN_EVENT_SUBSYSTEMS=stream,strategy,execution,risk`) allowing operators to toggle tracing depth without cluttering operational console logs.
  - **Seamless Rollover & Compression Integration (FEAT-22):**
    - Automatically integrates with `LogRetentionManager` for automated file size rollover, background `.gz` compression, and age-based pruning.
  - **Diagnostic Event Inspection CLI (`pumpfun-events` / `pumpfun ops events`):**
    - Dedicated CLI inspection commands supporting live tailing (`--tail`), mint filtering (`--mint <mint>`), error tracing (`--errors-only`), and timing latency analysis (`--latency-stats`).
* **System Utility & Reliability Impact:**
  - Provides complete, forensic-grade observability into *why* the bot entered or rejected specific tokens, *how* network latency affected execution, and *where* bottlenecks or failures occurred.
  - Drastically accelerates developer troubleshooting and algorithm calibration by providing empirical telemetry data that financial audit trails (`audit.jsonl`) and state snapshots (`bot_status.json`) cannot capture.

---

## 4. User Interface, Remote Control & Web Infrastructure

### FEAT-10: Full-Featured Web Control Dashboard, FastAPI Portal & Mobile Telegram Bot
* **Goal:** Provide a comprehensive, browser-based command center and remote operations portal for complete real-time bot management, hot configuration mutations, live portfolio analytics, and embedded documentation access, complemented by mobile Telegram alerts and command execution.
* **Architecture & Capabilities:**
  - **Full-Featured Web Dashboard vs. Lightweight Terminal UI:**
    - While the Terminal UI (`rich.live`) serves as a lightweight, zero-dependency console monitor for quick terminal checks, the Web Dashboard operates as the primary mission control portal.
    - Built on FastAPI with asynchronous WebSockets for sub-100ms real-time state streaming to a modern web frontend.
  - **Complete Bot Lifecycle & Operational Control:**
    - Live bot execution controls: start, pause, resume, emergency stop, and one-click panic liquidation (`sell_all`).
    - Hot strategy and risk configuration adjustments (updating buy sizing, take-profit tiers, trailing stops, anti-rug thresholds) in real time without requiring bot process restarts.
  - **Interactive Portfolio & Trade Management:**
    - Real-time equity curves, unrealized/realized PnL charts, active position inspection tables, and order execution latency telemetry.
    - Integrated forensic audit search interface for historical trade logs, state transitions, and incident review.
  - **Embedded In-App Documentation Hub:**
    - Natively renders and searches all project Markdown documentation (`User Guide`, `Strategy Logic`, `Risk Controls`, `Features Matrix`, `Terminal UI`, `API/SDK References`) directly within the web dashboard.
    - Ensures operators and developers have instant, context-aware access to system documentation, mathematical models, and operational runbooks.
  - **Mobile Telegram Bot Integration:**
    - Interactive Telegram bot commands (`/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/sell_all`, `/config`) with admin token authentication.
    - Instant push alerts for trade executions, trailing stop triggers, circuit breaker trips, and error warnings.
* **System & Financial Impact:** Enables instant remote interventions from mobile or browser, eliminates operator downtime during parameter tuning, and provides holistic multi-metric portfolio visibility to maximize capital safety and operational uptime.

---

## 5. Proposed Feature Prioritization & Execution Sequence

To maximize capital preservation, operational efficiency, and risk-adjusted alpha generation, candidate features are evaluated according to expected utility and dependency order:

1. **Priority 1: Sprint 16 — Full-Featured Web Control Dashboard, FastAPI Portal & Telegram Bot (FEAT-10)**
   - *Rationale:* Delivers the comprehensive browser-based command center, hot config management, remote Telegram commands, and embedded documentation reader for production operations.
2. **Priority 2: Sprint 18 — Automated Log Retention, Multi-Sink Rollover & Dataset Compression Engine (FEAT-22)**
   - *Rationale:* Hardens production infrastructure and long-term operational resilience by automating log/dataset rollover, background compression, and retention pruning across logging, audit, and market replay subsystems.
3. **Priority 3: Sprint 19 — Dynamic Volatility-Aware Slippage & Priority Fee Engine (FEAT-23)**
   - *Rationale:* Minimizes execution drag and toxic slippage leakage during high-volatility market bursts while guaranteeing instant transaction inclusion on emergency stop-loss exits.
4. **Priority 4: Sprint 20 — Opportunistic Capital Rotation & High-Conviction Displacement Engine (FEAT-24)**
   - *Rationale:* Maximizes capital compounding efficiency by recycling liquidity from flat or slow-moving bonding curves into newly detected 95th+ percentile breakout signals.
5. **Priority 5: Sprint 21 — Predictive Graduation Curve Acceleration & Pre-Migration Liquidity Harvester (FEAT-25)**
   - *Rationale:* Extracts high-conviction 30%–80% gains during the terminal bonding curve rush toward Raydium graduation with minimal downside exposure.
6. **Priority 6: Sprint 22 — On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)**
   - *Rationale:* Eliminates capital loss from multi-wallet insider dump syndicates and synthetic wash trading, protecting portfolio principal.
7. **Priority 7: Sprint 23 — Automated Strategy Parameter Auto-Tuning & Hyperparameter Backtest Optimizer (FEAT-27)**
   - *Rationale:* Automates continuous Bayesian/genetic calibration of Kelly allocations and trailing thresholds over historical replay datasets to prevent edge decay.
8. **Priority 8: Sprint 24 — Atomic Jito Back-Running & Cross-Venue Arbitrage Engine (FEAT-28)**
   - *Rationale:* Unlocks an uncorrelated, zero-directional-risk alpha stream capturing mispricings across Pump.fun bonding curves and external AMM pools.
9. **Priority 9: Sprint 25 — Adaptive Realized-Ratchet & Dual-Tier Drawdown Engine (FEAT-29)**
   - *Rationale:* Eliminates false-positive circuit breaker lockouts on highly profitable trading sessions while enforcing robust principal preservation and profit ratcheting.
10. **Priority 10: Sprint 26 — Structured Diagnostic Event Logging & Runtime Telemetry Persistence (FEAT-30)**
   - *Rationale:* Delivers forensic-grade runtime observability, candidate rejection logging, and streaming telemetry for rapid debugging and strategy fine-tuning.
