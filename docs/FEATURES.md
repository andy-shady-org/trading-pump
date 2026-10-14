# Features

This document provides a comprehensive and accurate overview of all features and architectural capabilities implemented in the `pumpfun-trading` repository. It covers the public API client, on-chain execution SDK, low-latency streaming pipeline, private mempool MEV protection, trading bot runtime, risk guards, historical replay engine, forensic audit tooling, and CLI suites.

---

## 1. Yellowstone Geyser gRPC Streaming Engine (FEAT-01)

- **Sub-Millisecond On-Chain Event Ingestion**: Bidirectional Solana Yellowstone Geyser gRPC streaming client (`YellowstoneGeyserClient`) bypassing standard JSON-RPC latency.
- **Zero-Copy Binary Bonding Curve Decoding**: Direct binary parsing (`BondingCurveBinaryParser`) using `memoryview` and struct unpacking to decode bonding curve states (`virtualTokenReserves`, `virtualSolReserves`, `realTokenReserves`, `realSolReserves`, `complete`, token supply, and live SOL price) without JSON serialization overhead.
- **Instruction Inner Data & Event Decoding**: Real-time trade instruction parser (`TradeInstructionBinaryParser`) decoding Buy/Sell instructions and Anchor program log events (`Program data: <base64>`) for instantaneous swap and curve graduation detection.
- **Resilient Connection Lifecycle**: Auto-reconnect handling with exponential backoff and randomized jitter (`0.85x`–`1.25x`), queue overflow drop tracking, and keepalive heartbeats.
- **Slot-Time Latency Telemetry**: Microsecond-precision benchmarking measuring slot-to-processing latencies displayed live in runtime telemetry.

---

## 2. Private Mempool MEV Bundling & Anti-Sandwich Protection (FEAT-02)

- **Jito Block Engine Integration**: Direct JSON-RPC client (`JitoClient`) interfacing with global Jito Block Engine endpoints (`mainnet`, `amsterdam`, `frankfurt`, `ny`, `tokyo`).
- **Toxic MEV & Sandwich Attack Protection**: Submits transactions via private validator mempools to prevent frontrunning and sandwich exploits.
- **Live Dynamic Tip Floor Estimation**: Queries real-time Jito tip stream percentiles (`p25`, `p50`, `p75`, `p95`, `p99`, `EMA`) with automatic TTL caching and fallback defaults.
- **Dynamic Tip Calculation**: Scales tip lamports dynamically (`calculate_dynamic_jito_tip`) based on trade size (e.g. 0.5% default) and trade conviction scores.
- **Validator Account Rotation**: Dynamic selection and round-robin rotation across active verified Jito tip recipient public keys.
- **Atomic Bundle Packaging**: Assembles atomic transaction bundles packing Compute Budget instructions, trade instructions, and validator tip transfers.
- **Fast Fallback to High-Priority RPC**: Automated failover routing (`send_jito_bundle_with_fallback`) submitting directly to Solana RPC with high priority fees on bundle timeout or block engine unreachability, guaranteeing no missed trading slots.
- **Environment & Runtime Configuration**:
  - `PUMPFUN_USE_JITO`: Toggle Jito bundle execution
  - `PUMPFUN_JITO_BLOCK_ENGINE_URL`: Custom Block Engine endpoint URL
  - `PUMPFUN_JITO_TIP_LAMPORTS`: Static tip override in Lamports
  - `PUMPFUN_JITO_CONFIRMATION_TIMEOUT`: Max seconds to await bundle confirmation (default: `12.0`)
  - `PUMPFUN_JITO_FALLBACK_TO_RPC`: Fast fallback to direct RPC on timeout (default: `true`)

---

## 3. Execution & On-Chain Solana SDK (FEAT-12)

- **Solana Keypair Management**: Secure base58 private key decoding and wallet public key derivation.
- **Exact Integer Lamports Precision**: Strict integer Lamports unit packing eliminating floating-point rounding errors across all buy/sell execution flows.
- **Solana Compute Budget Optimization**: Builds explicit priority fee instructions (`SetComputeUnitLimit`, `SetComputeUnitPrice`) for transaction inclusion.
- **PDA & Token Address Derivation**: Deterministic derivation of Pump.fun bonding curve PDAs and Associated Token Accounts (ATAs).
- **Instruction Construction**: Builds native Pump.fun buy and sell instructions with configurable slippage tolerance and minimum output guarantees.
- **On-Chain Bonding Curve State Decoding**: Queries and decodes bonding curve accounts directly from Solana RPC (`get_bonding_curve_state`, `decode_bonding_curve_data`).
- **Account & Balance Helpers**: Real-time wallet SOL balance queries, ATA existence checks, and automatic ATA creation on buy.
- **Transaction Compilation & Signing**: Compiles Versioned Transactions (`MessageV0`) with recent blockhashes and cryptographic signing.

---

## 4. Rug-Pull, Honeypot & Dev-Dumping Heuristic Screening (FEAT-04)

- **Pre-Trade Launch Screening Pipeline**: Automated multi-factor heuristic screening (`pumpfun_trading/strategies/filters.py`) protecting capital against malicious tokens, serial scams, and developer dump exploits before executing on-chain orders.
- **Developer Wallet Profiling**:
  - Queries creator historical token deployment records (`DevWalletProfile`, `evaluate_dev_wallet`).
  - Detects serial ruggers and penalizes creators launching excessive tokens (configurable, default `>5` launched coins in the preceding 24 hours).
  - Imposes severe risk score penalties (`>=50.0`) on developers with confirmed historical rug actions.
- **Creator Initial Holding Limit**:
  - Verifies creator launch-block purchase allocations (`evaluate_creator_holdings`).
  - Automatically flags and rejects tokens where the creator/developer bought `>10%` (configurable) of total circulating supply at mint creation to prevent catastrophic dev dumps.
- **Top Holder Concentration & Gini Coefficient**:
  - Measures wealth inequality and holder distribution (`HolderDistribution`, `calculate_gini_coefficient`, `evaluate_holder_distribution`).
  - Excludes bonding curve PDA reserves to evaluate true non-AMM circulating distribution.
  - Flags tokens where top 5 non-curve wallets control `>15%` of supply or exhibit extreme wealth inequality (`Gini > 0.85`).
- **Metadata & Social Presence Verification**:
  - Inspects token metadata URI and extracts links (`TokenMetadata`, `evaluate_metadata_socials`).
  - Verifies active community channels (Twitter/X, Telegram, Website, Discord) and penalizes missing or malformed social presences.
- **Composite Risk Scoring & Verdicts**:
  - Synthesizes heuristic flags into normalized composite risk scores ($0.0$ to $100.0$) (`TokenScreeningVerdict`, `evaluate_token_heuristics`).
  - Hard-fails toxic tokens and applies configurable risk tolerance thresholds across presets (`conservative`: max risk `30.0`, `balanced`: `50.0`, `aggressive`: `70.0`).
- **High-Performance In-Memory Screening Cache**:
  - Thread-safe TTL cache (`ScreeningCache`, default 60s TTL) preventing redundant API/RPC queries across high-frequency Geyser stream events.
- **Live Runtime Integration**:
  - Directly hooked into Geyser bonding curve event handlers (`_handle_bonding_curve_state_update`) and token discovery events (`_handle_new_token_event`) in `TradingBot`.
  - Transparently enriches candidates using `PumpFunApiClient.get_coin` and `get_creator_coins`.
  - Emits real-time screening telemetry in status snapshots (`screening_cache_size`, `enable_anti_rug_filters`) and audit logs.

---

## 5. Public Pump.fun API Client (FEAT-13)

- **REST & Analytics Client**: Async HTTP client (`PumpFunApiClient`) for Pump.fun endpoints with configurable timeouts and headers.
- **Coin Discovery & Pagination**: Fetches latest coin listings with offset and limit pagination.
- **Market & Metadata Queries**: Queries mint details with fallback lookup mechanisms for 404/401/403 responses.
- **Trade History & Candlesticks**: Retrieves trade history, trade volume counts, and OHLCV candlestick data across intervals.
- **Search & Filter Helpers**: Search, featured, and sorted coin queries.
- **SOL Price & Overview Helpers**: Real-time SOL/USD price checks and global market metrics.

---

## 6. Trading Bot Runtime & Execution Engine (FEAT-14)

- **State Machine Architecture**: Explicit lifecycle states (`idle`, `monitoring`, `buying`, `holding`, `selling`, `shutdown`) with signal handling.
- **Concurrency Mutex Protection**: Async trade locking (`_trade_lock`) ensuring thread-safe portfolio state mutations across simultaneous mint stream events.
- **On-Chain Startup Reconciliation**: Startup sync (`reconcile_onchain_positions`) discovering wallet token holdings, purging stale ghost positions, and synchronizing live valuations.
- **Exit Retry Queue & Emergency Escalation**: Automated retry queue (`_exit_retry_queue`) with escalating slippage limits and scheduled emergency liquidations for failed exits.
- **Candidate Evaluation**: Automated token discovery, bonding curve progress tracking, and market cap eligibility checks.
- **State Persistence & Recovery**: Periodic JSON status snapshots (`BotStatusStorage`) with automatic state restoration (positions, seen mints, buy attempts) on restart.
- **Structured Audit Logging**: Real-time JSONL audit logging (`AuditLogger`) capturing lifecycle transitions, order routing, PnL records, and reconciliation events.

---

## 7. Risk Controls & Capital Protection (FEAT-15)

- **Portfolio Exposure Caps**: Enforces global portfolio exposure limits and maximum simultaneous open positions.
- **Token Concentration Limits**: Caps single-token allocation as a percentage of total portfolio equity.
- **Drawdown & Loss Guards**: Circuit breaker triggers on maximum portfolio drawdown or individual per-trade stop-loss thresholds.
- **Minimum Wallet Balance Guard**: Reserves required SOL balances for transaction fees and rent before entering trades.
- **Rate-Limiting & Anti-Spam**: Buy attempt throttling per mint and configurable cooldown windows on recently seen mints.
- **Stale Stream Circuit Breaker**: Health timeout monitor tripping when stream or RPC data exceeds maximum age thresholds.
- **Dry-Run & Paper-Trading Modes**: Safe simulation execution without broadcasting live Solana transactions.

---

## 8. Strategy System, Presets & Dynamic Exit Engine (FEAT-03 & FEAT-16)

- **Preset Strategy Configurations**:
  - `conservative`: Tighter market cap filters, lower position sizing, strict take-profit/stop-loss thresholds, earlier trailing activation (+35%), and conservative scale-outs.
  - `balanced`: Default balanced risk-reward parameters with 2.0x Tier 1 and 3.5x Tier 2 take-profit scaling.
  - `aggressive`: Wider risk limits, higher slippage tolerance, momentum-focused entry/exit triggers, and extended runner targets.
- **Dynamic Trailing Stop-Loss Engine (FEAT-03)**:
  - Continuous peak market cap tracking per position (`PositionExitState`, `update_position_peak`, `track_position_peak`).
  - Activation threshold triggering after initial price gain (e.g. `+50%` / `1.5x`).
  - Configurable peak retracement liquidation (`trailing_stop_drop_pct`, default 15%) locking in accumulated upside before parabolic reversals.
- **Multi-Tier Take-Profit Scale-Out (FEAT-03)**:
  - **Tier 1**: Automatically liquidates initial principal allocation (e.g. 50% position quantity at `2.0x` / +100%) to de-risk capital.
  - **Tier 2**: Liquidates secondary allocation (e.g. 25% of position at `3.5x` / +250%).
  - **Tier 3 (Moonbag)**: Preserves residual 25% runner allocation protected by a dynamic trailing stop or configurable floor price (`2.5x`).
- **Config Dataclass Architecture**: Strongly-typed configuration (`TradingBotConfig`) supporting JSON file loading and environment overrides.
- **Modular Entry & Exit Logic**: Separated decision logic (`should_buy()`, `should_sell()`, `evaluate_exit_strategy()`) allowing custom strategy extensions.

---

## 9. CLI Tooling & Dedicated Entry Points (FEAT-17)

- **`pumpbot`**: Dedicated command-line entry point to launch the live trading bot with rich dashboard/headless options, strategy presets, and custom config paths.
- **`pumpfun-replay`**: Dedicated historical replay and backtesting tool with multiple rendering modes (`dashboard`, `summary`, `trades`) and token/mint filtering.
- **`pumpfun-audit`**: Dedicated forensic audit inspection CLI with filtering by mint address, mint name, record type, status, date windows, and JSON export.
- **`pumpfun-cli` / `pumpfun`**: Unified command-line interface providing subcommands:
  - `market-info`: Inspect on-chain and API market data for a specific mint.
  - `latest-coins`: Stream and list newly created tokens.
  - `bot`: Launch the automated trading bot.
  - `replay`: Run historical market data backtests.
  - `audit`: Query and inspect forensic audit logs.

---

## 10. Replay Engine & Strategy Backtesting (FEAT-18)

- **High-Fidelity Backtesting**: `PaperTradingEngine` and `run_replay()` simulating market data playback with fee and slippage awareness.
- **Dataset Ingestion**: Ingests JSON and JSONL market snapshot datasets (including virtual reserves, prices, and timestamps).
- **Observability & Analytics**: Calculates Profit Factor, Maximum Drawdown, Win Rate, Average Trade Return, and Final Equity.
- **Dual Mint/Name Display**: Displays both Mint Name and Mint Address in trade inspection tables.
- **Multiple Output Modes**: Rich live dashboard view, tabular trade logs, or summary statistical output.

---

## 11. Terminal UI, Alerting & Forensic Telemetry (FEAT-19)

- **Rich Live Terminal Dashboard**: Alternate-screen buffer rendering (`screen=True`) preventing cursor artifacts and header frame duplication.
- **Dual Identifier Representation**: Displays Token Name alongside Mint Address across dashboard positions, trade ledgers, and CLI tables.
- **ANSI & Non-TTY Compliance**: Built-in ANSI stripping (`AnsiStrippingFormatter`) respecting `NO_COLOR` and headless log environments.
- **Multi-Channel Alert Dispatcher**: Integrated alert notifications for trade executions, risk events, and state changes via:
  - Discord (webhooks)
  - Slack (webhooks)
  - Telegram (bot API)
- **Runtime Health Telemetry**: In-memory metrics tracking buy/sell counts, failure rates, connection drops, and slot latencies.

---

## 12. Testing & Code Quality Standards (FEAT-20)

- **Project-Wide Test Coverage**: 100% test pass rate with strict project-wide coverage enforcement ($\ge 95\%$ statement and branch coverage).
- **Automated Quality Pipeline**: Configured with `nox` covering code formatting (`black`), linting (`ruff`), and async test execution (`pytest`).
- **CI/CD Integration**: GitHub Actions workflows for automated testing and release artifact builds with Codecov coverage verification.

---

## 13. Full-Featured Web Control Dashboard, FastAPI Portal & Mobile Telegram Bot (FEAT-10)

- **FastAPI Asynchronous Backend**: High-performance ASGI service streaming real-time bot state, active positions, and telemetry over WebSockets.
- **Full Operational Control Center**: Web-based bot control interface supporting live start/pause/stop, emergency position liquidation (`sell_all`), and hot config mutation without bot process restarts.
- **Interactive Portfolio Visualization**: Real-time equity curves, drawdown monitoring, and live position inspection tables.
- **Embedded In-App Documentation Hub**: Direct in-dashboard browser and search for all project Markdown documentation (`User Guide`, `Strategy Logic`, `Risk Controls`, `Architecture`, `Runbooks`).
- **Integrated Telegram Bot**: Command-based remote control (`/status`, `/positions`, `/sell_all`, `/pause`, `/resume`, `/pnl`) with push alerts for key trade events.

---

## 14. Comprehensive Documentation Overhaul & Markdown Knowledge Hub (FEAT-11)

- **Exhaustive User Guide (`docs/USER-GUIDE.md`)**: Complete operator documentation covering installation, configuration, key security, and CLI command references.
- **Mathematical Strategy Guide (`docs/STRATEGY.md`)**: Formal formulation of bonding curve pricing, entry filtering, heuristic risk models, and exit algorithms.
- **Risk Management Specification (`docs/RISK.md`)**: Granular breakdown of portfolio exposure controls, concentration limits, drawdown rules, and emergency liquidation mechanisms.
- **Terminal UI & Monitoring Manual (`docs/TERMINAL-UI.md`)**: Detailed reference for dashboard panels, health checks, and alerting integrations.
- **Web UI Roadmap (`docs/WEB-UI.md`)**: Architectural blueprints and API specifications for the full-featured FastAPI web dashboard.

---

## 15. Real-Time Order Flow & Trade Velocity Momentum Signals (FEAT-07)

- **High-Performance Sliding Window Engine**: Thread-safe in-memory sliding window aggregation (`OrderFlowEngine`, `TokenOrderFlowTracker`) tracking 15s, 30s, and 60s windows with automatic timestamp-based eviction ($600\text{s TTL}$).
- **Real-Time Flow Analytics**: Instantaneous computation of Buy Volume (SOL), Sell Volume (SOL), Buy/Sell Volume Ratio, Net SOL Inflow, Unique Buyer Count, Unique Seller Count, and Trade Velocity ($\text{tx/s}$).
- **Statistical Anomaly Detection & Velocity Z-Scores**: Rolling baseline moving average ($\mu$) and standard deviation ($\sigma$) computation deriving statistical Z-scores ($Z = \frac{v - \mu}{\sigma}$) with safeguards against zero variance.
- **Sybil & Wash-Trading Guard**: Mandates unique buyer diversity ($\ge 3$ distinct wallets) and positive net SOL capital inflow ($\ge 0.5\text{ SOL}$) to prevent capital deployment on single-wallet churning.
- **Live Yellowstone Geyser Stream Integration**: Seamlessly routes live on-chain `TradeEventUpdate` and WebSocket trades into `OrderFlowEngine`, evaluating momentum signals for unowned tokens and triggering automated buy orders with reason `momentum_spike`.
- **Historical Paper Trading & Backtesting**: Full support in `PaperTradingEngine` for backtesting momentum strategies against multi-trade snapshot datasets.
- **Preset Sensitivity Profiles**: Configurable parameters across `conservative` ($Z \ge 3.0$, ratio $\ge 4.0$, 5 buyers), `balanced` ($Z \ge 2.5$, ratio $\ge 3.0$, 3 buyers), and `aggressive` ($Z \ge 2.0$, ratio $\ge 2.0$, 2 buyers).

---

## 16. Raydium Migration Sniping & Graduation Momentum Engine (FEAT-05)

- **Real-Time SOL Reserve & Completion Monitoring**: Sub-millisecond tracking of bonding curve real and virtual SOL reserves (`GraduationEngine`, `GraduationTracker`), automatically staging candidates reaching pre-migration threshold ($\ge 80.0\text{ SOL}$ or $\ge 95\%$ curve progress).
- **Sub-Slot Raydium AMM v4 Decoding**: Zero-copy binary parser and transaction decoder (`RaydiumPoolKeys`, `parse_raydium_initialize2_accounts`, `parse_raydium_pool_from_tx`) extracting AMM ID, token vaults, LP mint, and OpenBook market state from on-chain `Initialize2` transactions within $<0.2\text{ms}$.
- **Native Raydium Swap Instruction Serialization**: Constructs byte-exact Solana instructions (`build_raydium_swap_instruction`) for Raydium AMM v4 `SwapBaseIn` (discriminator `9`), handling associated token account creation, compute budget priority fees, and slippage calculations (`calculate_raydium_swap_out`).
- **Private Jito MEV Bundle Delivery**: Packages Raydium swaps into private atomic Jito bundles with dynamic validator tip calculation, completely bypassing the public mempool to prevent sandwich frontrunning during migration liquidity surges.
- **Unified Risk & Anti-Rug Guard**: Enforces complete pre-trade anti-rug screening (creator launch history, initial holdings cap, holder concentration Gini coefficient) and portfolio exposure limits before executing Raydium graduation buys.
- **Live Bot Stream Event Routing**: Directly connects Geyser `BondingCurveStateUpdate`, `CompleteEventUpdate`, and Raydium pool creation streams in `TradingBot`, triggering automated curve position liquidations on graduation and sniping newly initialized Raydium pools with reason `raydium_graduation_snipe`.
- **Historical Paper Trading Replay**: Simulates bonding curve graduation and Raydium pool entries in `PaperTradingEngine` for backtesting migration capture strategies.
- **Preset Sensitivity Profiles**: Configured thresholds across `conservative` (0.01 SOL buy, 300 bps slippage, 82 SOL threshold), `balanced` (0.02 SOL buy, 500 bps slippage, 80 SOL threshold), and `aggressive` (0.05 SOL buy, 800 bps slippage, 75 SOL threshold, 200k priority fee).

---

## 17. Smart Money Tracking & Copy-Trading Engine (FEAT-06)

- **Tracked Wallet Registry & Performance Profiling**: In-memory thread-safe registry (`TrackedWallet`, `WalletRegistry`, `CopyTradeEngine`) supporting dynamic performance tracking (historical win rate, total trade count, average ROI %, and risk scoring).
- **Sub-Millisecond On-Chain Swap Matching**: Intercepts on-chain trade events from Yellowstone Geyser gRPC (`TradeEventUpdate`) and WebSocket streams, identifying tracked smart money traders in $O(1)$ lookup time ($<0.05\text{ms}$).
- **Proportional Position Sizing**: Dynamically sizes entry orders proportional to the tracked wallet's trade size relative to their reference bankroll ($\text{Entry} = \text{Base} \times S_{\text{factor}} \times (\text{Trade} / \text{Bankroll}_{\text{ref}})$) with strict wallet allocation and portfolio position caps.
- **Scaled & Conviction-Weighted Sizing**: Supports alternative sizing modes (`proportional`, `fixed`, `scaled`), weighting allocation by historical win rate and conviction factors ($0.5\text{x}$ to $2.0\text{x}$).
- **Mirrored Sell & Exit Synchronization**: Immediately detects smart money sell transactions on active holdings and triggers automated position liquidation or scale-outs when `copy_trading_mirror_sells` is enabled.
- **Pre-Trade Anti-Rug Heuristic Screening**: Mandates anti-rug screening verification (developer launch history, creator initial supply cap, top holder concentration Gini coefficient) prior to executing any mirrored buy order.
- **Live Stream Event Routing in TradingBot**: Integrated directly into Geyser `_handle_trade_event_update` and WebSocket `_handle_trade_update`, dispatching buy orders with reason `copy_trade_<wallet>` and sell orders with `copy_trade_exit_<wallet>`.
- **Historical Paper Trading Replay**: Full support in `PaperTradingEngine` for simulating smart money entries and exits in historical market backtests.
- **Preset Sensitivity Profiles**: Tailored parameters across `conservative` (win rate $\ge 70\%$, risk score $\le 30$, 0.8x scale), `balanced` (win rate $\ge 60\%$, risk score $\le 40$, 1.0x scale), and `aggressive` (win rate $\ge 50\%$, risk score $\le 50$, 1.5x scale).

---

## 18. Multi-RPC Dynamic Load Balancing & Latency-Based Failover Engine (FEAT-08)

- **Native In-Process Connection Pooling**: Asynchronous connection pool (`RpcConnectionPool`, `RpcEndpoint`, `RpcPoolConfig` in `pumpfun_trading/infra/rpc_pool.py`) providing high-availability networking across multiple Solana RPC providers (e.g., Helius, QuickNode, Triton, Shyft, standard cluster).
- **Rolling Latency Percentile Profiling**: Bounded sliding window latency tracking ($N = 100$ samples) calculating rolling mean ($\mu$), median ($p_{50}$), $p_{95}$, and $p_{99}$ latency metrics in real time.
- **Dynamic Circuit Breaker State Machine**: Four-state circuit breaker (`HEALTHY`, `DEGRADED`, `OPEN`, `HALF_OPEN`) with immediate tripping on HTTP 429 rate limits or consecutive server errors ($\ge 3$), engaging a configurable cooldown backoff window ($60\text{s}$) with half-open recovery probes.
- **Intelligent Latency-Weighted Read Routing**: Automatically directs state reads (`getLatestBlockhash`, `getBalance`, `getTokenAccountsByOwner`, `getAccountInfo`, `getSignatureStatuses`) to the lowest-latency healthy endpoint with zero-overhead transparent failover to secondary endpoints upon transient errors.
- **Concurrent Multi-RPC Transaction Broadcasting**: Dispatches signed transactions concurrently across healthy endpoints using asynchronous scatter-gather (`broadcast_transaction`), deduplicating responses and confirming immediately upon the fastest signature response to maximize validator inclusion probability and minimize slot latency.
- **Execution Client & Builder Integration**: Fully wired into `PumpFunExecutionClient` and `ExecutionBuilder`, supporting multi-RPC configuration via comma-separated environment variables (`PUMPFUN_RPC_URLS`, `SOLANA_RPC_URLS`) alongside single `PUMPFUN_RPC_URL`.
- **Bot Lifecycle & Telemetry Integration**: Background periodic health checking and comprehensive telemetry reporting in `bot_status.json`, terminal dashboard metrics, and audit logs.
---

## 19. Core Runtime Decomposition & SOLID Architecture Refactoring (FEAT-12)

- **Decoupled SOLID Subsystem Architecture**: Fully decomposes the monolithic `TradingBot` runtime into dedicated, single-responsibility modules adhering strictly to Python design principles (SRP, OCP, LSP, ISP, DRY).
- **Position Lifecycle Manager (`PositionManager`)**: Encapsulates open positions, lot tracking, entry cost bases, peak price tracking, trailing stop activations, multi-tier partial take-profit state transitions, and disk serialization/restoration in `pumpfun_trading/bot/position_manager.py`.
- **Order Execution Subsystem (`OrderExecutor` & `OrderLiquidator`)**: Encapsulates single-token buy/sell order dispatching, Jito MEV bundling, slippage retries, per-token execution locks (`_trade_locks`), direct RPC fallbacks, and emergency portfolio liquidation in `pumpfun_trading/execution/executor.py` and `liquidator.py`.
- **Token Enrichment & Screening Engine (`TokenEnricher`)**: Encapsulates off-chain token metadata queries, creator deployment history profiling, top holder Gini concentration scoring, and thread-safe screening verdict caching (`ScreeningCache`) in `pumpfun_trading/bot/enrichment.py`.
- **Stream Event Routing (`EventRouter`)**: Decouples stream networking from business logic, routing Yellowstone Geyser gRPC updates (`BondingCurveStateUpdate`, `TradeEventUpdate`, `CompleteEventUpdate`) and WebSocket messages to registered strategy handlers in `pumpfun_trading/bot/event_router.py`.
- **Telemetry, Persistence & Multi-Channel Alerting**: Extracted `StatusPersistenceManager` (`pumpfun_trading/bot/persistence.py`) and `AlertDispatcher` (`pumpfun_trading/bot/alerts.py`) for atomic snapshot writing, append-only audit logging, and isolated webhook notifications.
- **Lightweight Orchestrator Facade**: Refactors `TradingBot` in `pumpfun_trading/bot/run.py` into a clean orchestrator facade retaining 100% backward compatibility for all public APIs, CLI commands, and test suites.

---

## 20. Asynchronous Market Stream Recorder & Historical Replay Dataset Generator (FEAT-21)

- **Non-Blocking Asynchronous Recorder (`ReplayRecorder`)**: Thread-safe, non-blocking queue (`asyncio.Queue`) buffer in `pumpfun_trading/bot/recorder.py` enqueuing market quotes and trade updates in $<0.05\text{ms}$, isolating live order execution from disk I/O contention.
- **Periodic Batch Disk Flushing**: Background worker coroutine aggregating enqueued records into chunks (configurable, default 50 records or 2.0–5.0 seconds) and performing batch appends to `.jsonl` files with graceful shutdown flush guarantees.
- **Live Bot Replay Recording Hook**: Integrated `--record-replay <path>` CLI option and environment variables (`PUMPFUN_REPLAY_LOG_PATH`, `PUMPFUN_RECORD_REPLAY`) for `pumpbot` and `TradingBot`, continuously capturing empirical market quotes, bonding curve states, and order flow.
- **Standalone Zero-Capital Harvester CLI (`pumpfun record` / `pumpfun-recorder`)**: Dedicated CLI utility (`pumpfun_trading/cli/record.py`) streaming Yellowstone Geyser gRPC and WebSocket trade feeds directly into standard `.jsonl` replay files without requiring a funded wallet or on-chain transaction execution.
- **Deterministic Synthetic Scenario Generator (`SyntheticReplayGenerator`)**: Parametric price trajectory generator in `pumpfun_trading/engines/generators.py` modeling extreme bonding curve market dynamics:
  - `pump_and_dump`: Rapid multi-tier surge (1.0x $\rightarrow$ 4.5x) followed by sharp collapse (0.2x).
  - `stagnant_curve`: Persistent flat launch valuation at 27.96 SOL market cap to test inactivity exit rules.
  - `multi_tier_take_profit`: Trajectory triggering Tier 1 TP (2.0x), Tier 2 TP (3.5x), and Moonbag trailing floor.
  - `gradual_grind`: Organic linear growth curve with realistic stochastic micro-volatility.
  - `flash_rug`: Sudden post-entry price collapse (1.0x $\rightarrow$ 1.3x $\rightarrow$ 0.05x).
- **Historical REST Trade Exporter (`RestHistoryExporter`)**: Extracts past trade histories and metadata for specific tokens via `PumpFunApiClient`, sorting chronologically and formatting into replay-compatible `.jsonl` records.
- **Seamless Replay & Backtest Interoperability**: Full schema compatibility with `PaperTradingEngine` and `pumpfun-replay` for immediate offline strategy calibration and risk stress-testing.

---

## 21. Adaptive Realized-Ratchet & Dual-Tier Portfolio Drawdown Engine (FEAT-29)

- **Realized Profit Ratchet & Dynamic Guaranteed Baseline**:
  - Decouples transient unrealized mark-to-market candle spikes on volatile bonding curves from permanent portfolio baseline ratcheting.
  - When positions close with net realized profit, a configurable fraction (`profit_ratchet_ratio`, default `0.50`) permanently ratchets the **Effective Baseline Floor**:
    $$\text{Baseline}_{\text{effective}} = \text{Starting Capital} + \alpha \times \max(0, \text{Cumulative Realized PnL})$$
  - Guarantees the baseline floor never degrades below initial principal or zero during subsequent losing trades.
- **Dual-Zone Risk Management**:
  - **Principal Protection Zone (`Current Equity < Starting Capital`)**: Strict capital preservation rules apply. If portfolio equity drops below $\text{Starting Capital} \times (1 - \text{max\_daily\_drawdown\_pct})$ (e.g. 15%–20% loss), emergency risk actions engage immediately.
  - **Profit Run Zone (`Current Equity >= Starting Capital`)**: Operating with "house money", the bot enforces a wider, configurable trailing drawdown buffer (`profit_drawdown_tolerance_pct`, default `35%`) from intraday peak equity relative to the effective baseline floor.
- **Tiered Two-Stage Circuit Breaker Actions**:
  - **Stage 1 (`HALT_NEW_BUYS`)**: Breaching profit run retracement limits soft-halts new token candidate entries while allowing open positions to continue exiting orderly via their configured trailing stops (`FEAT-03`) and take-profit targets.
  - **Stage 2 (`EMERGENCY_LIQUIDATE`)**: Emergency market liquidations (`sell_all`) are strictly reserved for hard Principal Protection Floor breaches.
- **Configurable Risk Policies & Presets**:
  - Configurable `drawdown_reference_mode`: `"adaptive_ratchet"` (recommended default), `"baseline"` (strict starting principal anchor), or `"trailing_hwm"` (legacy strict peak-to-trough tracking).
- **Runtime Telemetry & Persistence**:
  - Live circuit breaker action, effective baseline, and regime state are continuously published to `bot_status.json`, terminal telemetry, and structured diagnostic events.

---

## 22. Structured Diagnostic Event Logging & Runtime Telemetry Persistence (FEAT-30)

- **High-Throughput Microsecond Telemetry Persistence**: Dedicated asynchronous non-blocking event sink (`DiagnosticEventLogger` in `pumpfun_trading/ops/events.py`) recording structured JSONL events (`events.jsonl`) with nanosecond/microsecond timestamps (`timestamp_ns`, `iso_timestamp`).
- **Comprehensive Multi-Subsystem Instrumentation**:
  - **Streams (`stream`)**: Geyser gRPC / WebSocket slot latency, reconnection counters, dropped packet tracking, and binary decode runtimes.
  - **Anti-Rug Screening (`screening`)**: Off-chain metadata resolution, creator launch history profiling, top 5 holder Gini concentration scores, and exact reject/pass rationale strings.
  - **Strategy & Signals (`strategy`)**: Order flow momentum Z-scores, price velocity, trade volume ratios, and Kelly allocation sizing fractions.
  - **Execution & MEV (`execution`)**: Jito bundle assembly, priority tip calculations, confirmation latencies, and direct RPC fallback triggers.
  - **Risk & Lifecycle (`risk`, `lifecycle`)**: Position entry/exit triggers, partial take-profit fills, dynamic trailing stop ratchets, and dual-zone circuit breaker state transitions.
- **Non-Blocking Background Worker**: Bounded in-memory event queue (`asyncio.Queue`, 10,000 capacity) flushed in batches via background worker tasks, ensuring $<0.05\text{ms}$ critical path emission latency under heavy streaming bursts.
- **Configurable Subsystem Filters & Verbosity**: Environment variable and config support (`PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS`, `PUMPFUN_EVENT_LOG_PATH`, `PUMPFUN_EVENT_SUBSYSTEMS`).
- **Diagnostic Inspection CLI (`pumpfun-events` / `pumpfun events`)**:
  - Dedicated CLI tool (`pumpfun_trading/cli/events.py`) supporting live log tailing (`--tail`), mint filtering (`--mint <mint>`), category filtering (`--category <cat>`), error isolation (`--errors-only`), latency statistical distribution summaries (`--latency-stats`), and JSON output (`--json`).
