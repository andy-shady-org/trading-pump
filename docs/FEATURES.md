# Features

This document provides a comprehensive and accurate overview of all features and architectural capabilities implemented in the `pumpfun-trading` repository. It covers the public API client, on-chain execution SDK, low-latency streaming pipeline, private mempool MEV protection, trading bot runtime, risk guards, historical replay engine, forensic audit tooling, and CLI suites.

Only shipped code belongs here. Unbuilt features and the unbuilt parts of a shipped one are tracked in [`dev/PROPOSED-FEATURES.md`](dev/PROPOSED-FEATURES.md); each section below says what is still missing under **Not built**.

---

## 1. Yellowstone Geyser gRPC Streaming Engine (FEAT-01)

- **Sub-Millisecond On-Chain Event Ingestion**: Bidirectional Solana Yellowstone Geyser gRPC streaming client (`YellowstoneGeyserClient`) bypassing standard JSON-RPC latency.
- **Zero-Copy Binary Bonding Curve Decoding**: Direct binary parsing (`BondingCurveBinaryParser`) using `memoryview` and struct unpacking to decode bonding curve states (`virtualTokenReserves`, `virtualSolReserves`, `realTokenReserves`, `realSolReserves`, `complete`, token supply, and live SOL price) without JSON serialization overhead.
- **Instruction Inner Data & Event Decoding**: Real-time trade instruction parser (`TradeInstructionBinaryParser`) decoding Buy/Sell instructions and Anchor program log events (`Program data: <base64>`) for instantaneous swap and curve graduation detection.
- **Resilient Connection Lifecycle**: Auto-reconnect handling with exponential backoff and randomized jitter (`0.85x`–`1.25x`), queue overflow drop tracking, and keepalive heartbeats.
- **Slot-Time Latency Telemetry**: Microsecond-precision benchmarking measuring slot-to-processing latencies displayed live in runtime telemetry.
- **Not built**: a production Yellowstone gRPC transport. Without an injected `custom_transport` the client raises `GeyserTransportUnavailableError` and the bot runs on the PumpPortal WebSocket stream; the transport is [FEAT-39](dev/PROPOSED-FEATURES.md#feat-39-production-yellowstone-grpc-transport).

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
- **Modern Pump.fun V2 Instruction Architecture**: Native support for modern Pump.fun `BuyV2` (discriminator `0xb817ee6167c5d33d`, 27 accounts) and `SellV2` (discriminator `0x5df6823ce7e940b2`, 26 accounts) instructions with configurable slippage tolerance and minimum output guarantees.
- **Dynamic Token-2022 & SPL Token Program Detection**: Automatic detection of token mint owner program (`get_token_program_for_mint`), dynamically wiring either Token-2022 or legacy SPL Token program IDs for Associated Token Account (ATA) derivation and instruction account keys.
- **Creator Vault & Fee / Volume Accumulator PDAs**: Deterministic derivation and inclusion of `creator-vault`, `global_volume_accumulator`, `user_volume_accumulator`, and fee program configuration PDAs (`fee_config` under Pump Fee Program `pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ`), alongside primary fee and buyback fee recipient accounts.
- **Creator Public Key Decoding**: Direct binary unpacking of creator public key from bonding curve account data (`data[49:81]`) to construct exact creator vault accounts.
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
- **CI Integration**: GitHub Actions workflow (`tests.yml`) running the test matrix on Python 3.11–3.14 plus lint, mypy, audit and package checks, with a Codecov upload. There is no release or publish workflow (proprietary, private tags only).

---

## 13. Web Control Dashboard & Telegram Bot (FEAT-10): moved to proposed

Not implemented: the package has no FastAPI service, web dashboard, in-app docs browser or Telegram command bot. This section was removed on 2026-10-20; the work is tracked in [`PROPOSED-FEATURES.md` §3](dev/PROPOSED-FEATURES.md#3-web-ui-platform-required) as FEAT-10 (umbrella) and FEAT-31…37, with the Telegram bot as FEAT-45. What ships today is the terminal dashboard and push alerts (§11) and the `SIGUSR1` operator pause (§31).

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

> **Off by default (rc.4, BUG-131):** `enable_raydium_migration_sniping` is `false` in every preset, because Pump.fun migrates into PumpSwap, not Raydium (BUG-123). A Raydium position takes its entry market cap from the live fill (or from the first price it sees), no longer a fixed 69 SOL.

- **Real-Time SOL Reserve & Completion Monitoring**: Sub-millisecond tracking of bonding curve real and virtual SOL reserves (`GraduationEngine`, `GraduationTracker`), automatically staging candidates reaching pre-migration threshold ($\ge 80.0\text{ SOL}$ or $\ge 95\%$ curve progress).
- **Sub-Slot Raydium AMM v4 Decoding**: Zero-copy binary parser and transaction decoder (`RaydiumPoolKeys`, `parse_raydium_initialize2_accounts`, `parse_raydium_pool_from_tx`) extracting AMM ID, token vaults, LP mint, and OpenBook market state from on-chain `Initialize2` transactions within $<0.2\text{ms}$.
- **Native Raydium Swap Instruction Serialization**: Constructs byte-exact Solana instructions (`build_raydium_swap_instruction`) for Raydium AMM v4 `SwapBaseIn` (discriminator `9`), handling associated token account creation, compute budget priority fees, and slippage calculations (`calculate_raydium_swap_out`).
- **Private Jito MEV Bundle Delivery**: Packages Raydium swaps into private atomic Jito bundles with dynamic validator tip calculation, completely bypassing the public mempool to prevent sandwich frontrunning during migration liquidity surges.
- **Unified Risk & Anti-Rug Guard**: Enforces complete pre-trade anti-rug screening (creator launch history, initial holdings cap, holder concentration Gini coefficient) and portfolio exposure limits before executing Raydium graduation buys.
- **Live Bot Stream Event Routing**: Directly connects Geyser `BondingCurveStateUpdate`, `CompleteEventUpdate`, and Raydium pool creation streams in `TradingBot`, triggering automated curve position liquidations on graduation and sniping newly initialized Raydium pools with reason `raydium_graduation_snipe`.
- **Historical Paper Trading Replay**: Simulates bonding curve graduation and Raydium pool entries in `PaperTradingEngine` for backtesting migration capture strategies.
- **Preset Sensitivity Profiles**: Configured thresholds across `conservative` (0.01 SOL buy, 300 bps slippage, 82 SOL threshold), `balanced` (0.02 SOL buy, 500 bps slippage, 80 SOL threshold), and `aggressive` (0.05 SOL buy, 800 bps slippage, 75 SOL threshold, 200k priority fee).
- **Limits**: Pump.fun now migrates graduated coins to PumpSwap, not Raydium (BUG-123), so the Raydium snipe path does not fire on current graduations, and the Raydium pool feed needs Geyser (FEAT-39). Held coins exit on PumpSwap (§35). **Not built**: buying on PumpSwap after graduation.

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
- **Composition Root & Stream Handlers** (Sprints 28a/28b): `bot/factory.py` builds the components, `streams/websocket.py` owns the PumpPortal loop, `ops/metrics.py` the counters, `execution/sell_pipeline.py` the sell maths, and `bot/handlers/` the stream handlers, with one-line delegates kept on `TradingBot` so public APIs, CLI commands and tests are unchanged.
- **Not built**: a lightweight `TradingBot` facade. `bot/run.py` is still ~3,570 lines (buy / sell paths, status snapshot, supervision loops); the < 800-line target is Sprint 28c in [`TODO.md`](dev/TODO.md).

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

---

## 23. Automated Log Retention, Multi-Sink Rollover & Dataset Compression Engine (FEAT-22)

- **Configurable Application Log Rollover & Inline Gzip Compression**:
  - Size-based (`RotatingFileHandler`) and time-based (`TimedRotatingFileHandler`) rotation with custom non-blocking gzip compression hooks (`_gzip_rotator` / `_gzip_namer`) in `pumpfun_trading/ops/logging.py`.
  - Configurable file size limits (`PUMPFUN_LOG_MAX_BYTES`, default 10 MB) and backup retention counts (`PUMPFUN_LOG_BACKUP_COUNT`, default 5).
- **Async Non-Blocking Rotating Sinks (`RotatedFileSink`)**:
  - Thread-safe, non-blocking file sink in `pumpfun_trading/ops/retention.py` used across forensic audit persistence (`StatusPersistenceManager` / `audit_trail.jsonl`) and Geyser market stream recordings (`ReplayRecorder` / `market_replay.jsonl`).
  - Decoupled asynchronous background workers (`asyncio.to_thread`) executing atomic file rotations (`os.replace`) and inline gzip compression (`.gz`) without introducing latency jitter into critical trading event loops.
- **Unified Retention Management Engine (`LogRetentionManager`)**:
  - Centralized retention policy engine in `pumpfun_trading/ops/retention.py` enforcing retention policies by age (`max_age_days=30`), backup file count caps, and total directory byte limits with automatic expired archive pruning.
  - Periodic background pruning during bot runtime health loops and graceful shutdown flushing.
- **Transparent Multi-File & Compressed Dataset Ingestion**:
  - Native `.gz` decompression and multi-file directory / glob pattern loading across `load_audit_records` (`pumpfun-audit`) and `PaperTradingEngine.load_history` (`pumpfun-replay`).
- **Storage Operations & Maintenance CLI (`pumpfun ops`)**:
  - Unified CLI commands (`pumpfun ops prune --target <dir> --days <n>`, `pumpfun ops status`) for on-demand disk quota inspection and archive pruning.

---

## 24. Dynamic Volatility-Aware Slippage & Adaptive Priority Fee Engine (FEAT-23)

- **Real-Time Bonding Curve Volatility Estimator (`BondingCurveVolatilityEstimator`)**:
  - Computes instantaneous price velocity ($\Delta P / \Delta t$) and rolling standard deviation ($\sigma_{\text{vol}}$) from high-frequency Geyser gRPC state updates.
  - Computes virtual reserve depth consumption ($\Delta x / x_{\text{virtual}}$) and exact buy/sell price impact in basis points.
- **Urgency-Tiered Compute Budget & Jito Tip Scaling (`AdaptiveExecutionPolicy`)**:
  - Resolves dynamic slippage:
    $$S_{\text{dynamic}} = \operatorname{clamp}\left(S_{\text{base}} + \alpha \cdot \sigma_{\text{volatility}} + \beta \cdot \text{PriceImpact}, S_{\text{min}}, S_{\text{max}}\right)$$
  - Dynamically scales Solana compute unit limits, compute unit prices, priority fees, and Jito validator tips across urgency tiers:
    - `NORMAL_ENTRY` (1.0x compute price, 100k tip)
    - `HIGH_CONVICTION` (1.5x compute price, 150k tip)
    - `GRADUATION_SNIPE` (2.5x compute price, 250k tip)
    - `EMERGENCY_EXIT` (4.0x compute price, 400k tip, up to 5000 BPS exit slippage).
- **Execution & Liquidation Wiring**: Integrated directly into `OrderExecutor`, `PumpFunExecutionClient`, and `OrderLiquidator` with environment variables (`PUMPFUN_DYNAMIC_SLIPPAGE_ENABLED`, `PUMPFUN_MIN_SLIPPAGE_BPS`, `PUMPFUN_MAX_SLIPPAGE_BPS`, `PUMPFUN_MAX_EXIT_SLIPPAGE_BPS`, `PUMPFUN_PRIORITY_FEE_MODE`).

---

## 25. Opportunistic Capital Rotation & High-Conviction Displacement Engine (FEAT-24)

- **Continuous Expected Value (EV) Position Scoring (`PositionEvEvaluator`)**:
  - Computes multi-factor EV scores across open holdings:
    $$\text{EV}_{\text{position}} = w_z \cdot Z_{\text{norm}} + w_{\text{inflow}} \cdot \text{Inflow}_{\text{norm}} + w_p \cdot \text{PnL}_{\text{norm}} - w_{\text{stag}} \cdot \text{Stagnation}$$
  - Enforces minimum holding protection (`min_hold_before_displacement_seconds = 45.0s`), protecting young positions from premature displacement.
- **Autonomous Capital Displacement Engine (`CapitalDisplacementEngine`)**:
  - Continuously monitors portfolio saturation (`len(positions) >= max_active_positions` or `total_exposure >= max_total_exposure_sol`).
  - Evaluates candidate breakout EV against the weakest displaceable holding, requiring the EV delta to overcome roundtrip execution friction ($2 \times \text{slippage} + \text{hurdle\_rate}$).
- **Atomic Rotation & Telemetry**:
  - Gracefully exits the weakest stagnant position with high urgency, confirms exit fill, and immediately dispatches entry for the high-conviction candidate with structured telemetry events (`capital_displacement`).

---

## 26. Predictive Graduation Curve Acceleration & Pre-Migration Liquidity Harvester (FEAT-25)

- **Curve Supply Depletion & Acceleration Modeling (`GraduationTracker`)**:
  - Computes reserve accumulation velocity ($v = \Delta \text{SOL} / \Delta t$) and curve acceleration ($a_{\text{curve}} = \Delta^2 \text{SOL} / \Delta t^2$).
  - Classifies bonding curves into deterministic trajectory regimes: `organic` (steady positive acceleration), `syndicate_sweep` (single massive whale buy), or `exhaustion` (decelerating volume / sell-off).
- **Pre-Graduation Acceleration Harvesting Triggers (`GraduationEngine`)**:
  - Triggers automated entry when curve progress reaches 70%–85% with positive acceleration ($a_{\text{curve}} > 0$) prior to Raydium pool seeding.
- **Staged Multi-Tranche Take-Profit Scaling (`evaluate_exit_strategy`)**:
  - Executes limit-style take-profit tranches as the curve completes (e.g. 30% sold at 92% completion, 30% sold at 97% completion, 40% moonbag riding into Raydium AMM seeding).
- **Paper Trading & Historical Replay**: Fully simulated in `PaperTradingEngine` across empirical datasets.

---

## 27. On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)

- **Graph-Based Wallet Relationship Mapping (`FundingClusterGraph`)**:
  - Traverses directed funding flows (`funder -> recipient`) and root funding origins (e.g. root SOL transfers, intermediary splitters, exchange withdrawal hot-wallets) for top holders and creator wallet at token creation block.
  - Resolves common ancestors, tracks cluster depths, and calculates the **Insider Cluster Concentration Index ($0.0–1.0$)** measuring what fraction of circulating supply is controlled by common-origin wallet clusters.
- **Insider Syndicate & Dominant Cluster Rejection**:
  - Automatically identifies multi-wallet syndicates and flags tokens where multi-wallet clusters exceed configured thresholds (`max_cluster_concentration_pct = 0.25`, `max_single_cluster_pct = 0.20`).
  - Imposes severe risk penalties and hard-fails screening for tokens with insider syndicate concentration (`insider_cluster_detected`, `dominant_cluster_detected`).
- **Sybil Wash-Trading & Churn Detector (`SybilWashTradingDetector`)**:
  - Analyzes trade streams on bonding curves for circular buy/sell patterns, coordinated micro-swaps between clustered wallets, and rapid round-trip churn designed to artificially inflate volume and Z-scores.
  - Rejects tokens with confirmed sybil volume or wash trading ratios exceeding limits (`max_sybil_wash_ratio = 0.20`).
- **Composite Screening & Enrichment Integration (`FundingClusterAnalyzer`)**:
  - Seamlessly integrated into `TokenEnricher` (`bot/enrichment.py`), `TradingStrategy.screen_token` (`strategies/decision.py`), `passes_anti_rug_screening` (`strategies/filters.py`), and `TradingBotConfig` presets.
  - Configurable via environment variables (`PUMPFUN_CLUSTER_ANALYSIS_ENABLED`, `PUMPFUN_MAX_CLUSTER_CONCENTRATION_PCT`, `PUMPFUN_MAX_SINGLE_CLUSTER_PCT`, `PUMPFUN_MAX_SYBIL_WASH_RATIO`, `PUMPFUN_CLUSTER_TRACE_DEPTH`).
- **Not built**: a source of funding links. `TokenEnricher` only runs the analyser when the API record carries `funding_links`, and the Pump.fun API never sends that field, so the analyser never runs on live tokens. The funder lookup is [FEAT-63](dev/PROPOSED-FEATURES.md#feat-63-funding-source-lookup-for-the-cluster-analyser).

---

## 28. Automated Strategy Parameter Auto-Tuning & Hyperparameter Backtest Optimizer (FEAT-27)

- **Declarative Hyperparameter Space & Domain Framework (`ParameterSpace`)**:
  - Modular hyperparameter primitives (`FloatParam`, `IntParam`, `CategoricalParam`, `BoolParam`) supporting continuous, discrete, logarithmic (`log_scale`), and bounded domains with step intervals and neighbor perturbation.
  - Built-in default search space (`build_default_strategy_search_space`) covering entry sizing, momentum Z-scores, multi-tier take-profits, dynamic trailing stops, stagnation exits, adaptive ratchets, and anti-rug cluster caps.
- **Multi-Objective Fitness & Risk Evaluation (`FitnessScore`)**:
  - Mathematical computation of Sharpe Ratio, Sortino Ratio, Profit Factor, Calmar Ratio, Win Rate, Total Return, Maximum Drawdown, and Net Expectancy ($EV$) from simulated trade series.
  - Configurable composite fitness scoring with custom weights balancing risk-adjusted return maximization and drawdown penalties.
- **Advanced Optimization Algorithms (`BaseOptimizer`)**:
  - **Genetic Algorithm (`GeneticOptimizer`)**: Evolutionary population optimization with tournament selection ($k=3$), uniform blend crossover, adaptive Gaussian mutation, and elitism preservation.
  - **Random Search (`RandomSearchOptimizer`)**: Uniform and log-uniform stochastic exploration across multi-dimensional parameter spaces.
  - **Grid Search (`GridSearchOptimizer`)**: Combinatorial product exploration across discrete parameter sub-grids.
- **Walk-Forward Cross-Validation & Overfitting Guard (`WalkForwardValidator`)**:
  - In-sample (train) vs. out-of-sample (test/validation) dataset partitioning to evaluate generalization across unseen market conditions and compute overfitting deltas ($\text{Overfit Delta} = \max(0, \text{TrainScore} - \text{TestScore})$).
- **Direct Configuration Exporter & Preset Generator (`OptimizationResult`)**:
  - Direct export of top-ranking parameter configurations to `TradingBotConfig` JSON files (`--export-config <file>`) and custom preset dictionaries.
- **Interactive Optimizer CLI (`pumpfun-optimize` / `pumpfun optimize`)**:
  - Rich console UI with live convergence progress bars, performance summaries, and top-k candidate ranking tables.

---

## 29. Atomic Jito Back-Running & Cross-Venue Arbitrage Engine (FEAT-28)

- **Sub-Millisecond Cross-Venue Disparity Monitor (`CrossVenueDisparityMonitor`)**:
  - Real-time price tracking comparing Pump.fun virtual bonding curve spot prices ($P_{\text{pump}} = y_{\text{virtual}} / x_{\text{virtual}}$) against Raydium AMM v4 pool reserves ($P_{\text{raydium}} = R_{\text{quote}} / R_{\text{base}}$).
  - Continuous calculation of gross percentage spread ($S_{\text{gross}} = |P_a - P_b| / \min(P_a, P_b)$) and direction identification (`pump_to_raydium` vs. `raydium_to_pump`) across all graduating and migrated tokens.
- **Closed-Form Optimal Arbitrage Sizing Math (`OptimalArbitrageCalculator`)**:
  - Mathematical derivation of optimal input swap size ($x^*$) maximizing net profit across dual AMM curves subject to protocol fee friction (1% Pump.fun fee, 0.25% Raydium fee) and pool depth:
    $$x^* = \frac{\sqrt{A \cdot C} - C}{B}$$
  - Sizing constraints and caps (`min_arbitrage_input_sol`, `max_arbitrage_input_sol`, `min_arbitrage_profit_sol`, `min_arbitrage_spread_pct`).
- **Atomic Multi-Hop Jito Bundle Execution (`AtomicArbitrageBuilder`, `AtomicArbitrageExecutor`)**:
  - Assembly of dual-leg atomic swap instructions (Leg 1: Buy on Venue A, Leg 2: Sell on Venue B) bundled with a dynamic Jito tip transfer instruction in a single atomic transaction.
  - Dynamic Jito validator tip floor scaling and profit-sharing model (allocating 40%–60% of gross profit to validator tips to guarantee top-of-block priority inclusion).
  - Guarantees zero directional capital risk: if price parity shifts or competitor transactions slip pool reserves, the entire atomic bundle reverts on-chain with zero capital loss.
- **Mempool & Stream Whale Back-Running Engine (`MempoolBackrunEngine`)**:
  - Detection of large whale buy/sell orders (> 1.0 SOL or > 2% curve impact) streamed via Yellowstone Geyser gRPC.
  - Sub-slot counter-trade signal generation to capture post-whale mean-reversion and cross-venue spread balancing.
- **Transient Flash Capital Accounting & Runtime Integration**:
  - Seamlessly integrated with `TradingBot`, `PositionManager`, and `DailyEquityTracker` for risk validation, flash capital allocation, and instantaneous cash recycling.
- **Dedicated Arbitrage CLI (`pumpfun-arb` / `pumpfun arb`) & Replay Backtesting**:
  - Standalone and unified CLI tooling for live spread monitoring, dry-run simulation, and JSON history exports.
  - Multi-venue arbitrage simulation support in `PaperTradingEngine` (`pumpfun-replay`).
- **Not built**: a live reserve feed. `pumpfun-arb --monitor/--live` evaluate sample reserves (BUG-90, mitigated), and arbitrage stays off for the canary ([`RELEASE-GATE.md` §3.5](dev/RELEASE-GATE.md)); the chain-read feed is [FEAT-40](dev/PROPOSED-FEATURES.md#feat-40-live-cross-venue-arbitrage-feed).

---

## 30. Net PnL Accounting & Wallet Reconciliation (FEAT-49)

Shipped in v0.2.0 (Sprint 24B), with BUG-96 token-account rent recovery.

- **Per-Trade Costs**: `sdk/costs.py` reads the network fee, priority fee, Jito tip, token-account rent and the exact SOL swapped from the confirmed transaction (`getTransaction`, capped at 8 s). Paper and dry-run trades use the same cost model.
- **Net PnL On Every Record**: `bot/pnl.py`; trade records carry `signature`, the fee / tip / rent fields, `costs_sol`, `gross_pnl_sol`, `net_pnl_sol` and `cash_flow_sol`. The daily circuit breaker runs on net PnL.
- **Rent Recovery**: the sell that empties a token account closes it in the same transaction (`close_token_account_on_full_exit`, default `true`).
- **`pumpfun-audit pnl`**: realized profit after costs per closed position, `--group-by` day, reason, strategy, mint or hour, `--json`.
- **`pumpfun-audit reconcile --wallet`**: checks live trades against the chain (token balances, whole-wallet SOL change within `--tolerance-sol`), exit code 1 on a gap; the result is stored in `reconcile_status.json` and shown on the dashboard Risk panel.

---

## 31. Operator Pause, Unattended Alerts & Supervised Deployment (FEAT-50)

Shipped in v0.2.1 (Sprint 24D). See [`RUNBOOK.md` §5.5, §8](dev/RUNBOOK.md).

- **Operator Pause**: `SIGUSR1` toggles "no new buys, keep managing exits" (`bot/operator.py`); persisted in `bot_status.json`, audited, alerted and shown on the dashboard.
- **Unattended Alerts** (`bot/supervision.py`): daily summary at `daily_summary_hour_utc`, prolonged stream / RPC degradation (`degradation_alert_minutes`) and recovery, new reconciliation gaps, `bot started` / `bot stopped`.
- **Supervisor Templates** (`deploy/`): `pumpbot-run.sh`, systemd `pumpbot.service` and `pumpfun-reconcile.{service,timer}`, launchd `com.pumpfun.pumpbot.plist`. `pumpbot` exits with code 1 when its stream loop ends without a shutdown request, so a supervisor restarts it.
- **Not yet done**: the RUNBOOK §7 drills and a 7-day unattended run.

---

## 32. Automated Treasury Profit Sweep (FEAT-42)

Shipped in v0.2.1 (Sprint 24D), **off by default**. See [`RUNBOOK.md` §5.6](dev/RUNBOOK.md).

- **Policy** (`bot/sweep.py`): `profit_sweep_enabled`, `profit_sweep_destination`, `profit_sweep_hot_floor_sol`, `profit_sweep_min_sol`, `profit_sweep_interval_seconds`; the floor never drops below `reserve_balance_sol + max_total_exposure_sol + 0.01`.
- **Transfer**: `PumpFunExecutionClient.transfer_sol` with compute-budget instructions and no Jito tip, under the trade lock; paper / dry-run simulate it.
- **Accounting**: a `sweep` audit record per sweep, counted by `pumpfun-audit reconcile`; the breaker treats it as a withdrawal (`DailyEquityTracker.record_withdrawal`), not a drawdown.
- **Limits**: sweeps all SOL above the floor (deposits too); needs its paper drill before use on a funded wallet.

---

## 33. Watch List & Batch Curve Poller (FEAT-51)

Shipped in v0.3.0-rc.1 (Sprint 24F); extended in rc.2.

- **Watch Instead Of Buy**: with `entry_mode: "confirmed"` a screened launch goes onto a bounded TTL watch list (`OrderFlowEngine.watch`, `WatchEntry`; `watch_ttl_seconds`, `watch_max_mints`) instead of being bought. `"launch"` stays the default for back-compat.
- **Batch Curve Poller** (`bot/handlers/watch.py`): reads all watched curves with one `getMultipleAccounts` call per 100 mints every `watch_poll_interval_seconds` (`PumpFunExecutionClient.get_bonding_curve_states`, with the BUG-104/108/124 owner, reserve and quote-mint checks) and feeds the watch list and `GraduationEngine`.
- **Subscription Budget**: only mints whose real SOL grew by `watch_promote_min_sol_growth` get a billed trade subscription, at most `watch_max_trade_subscriptions`; expired or rejected mints are unsubscribed.
- **Near-Graduation Set** (rc.2, `near_graduation_*`, off by default): keeps growing curves past the watch TTL, polled more slowly, for the pre-graduation lane.
- **Curve Reads In The Capture** (rc.2, `capture_curve_polls`): every curve read is written to the `--record-replay` capture as an `event: "curve_poll"` row, so replay prices fills and the drift guard from the reads paper used.
- **Telemetry**: watch-list size, subscribed mints and funnel counters in `bot_status.json` and on the dashboard.

---

## 34. Confirmed Momentum Entry & Momentum Exits (FEAT-52)

Shipped in v0.3.0-rc.1 (Sprint 24G); drift guard in rc.2. The lane is still a paper-only **NO-GO** ([`STRATEGY-PIVOT.md` §6](dev/STRATEGY-PIVOT.md)).

- **Confirmation** (`bot/handlers/trade.py`): a promoted watched mint is bought only inside the token-age window and market-cap band (`momentum_min/max_token_age_seconds`, `min_market_cap_sol` to `momentum_max_market_cap_sol`), when `OrderFlowEngine` confirms buyers, inflow, buy ratio and z-score (creator and our wallet left out), and `_should_buy` passes.
- **Cost Guard**: refuses buys whose modelled fixed round-trip costs exceed `max_entry_cost_share_pct` of the position.
- **Drift Guard** (`momentum_max_entry_drift_pct`): paper re-reads the curve after the entry delay and skips the buy above the limit; live refuses or caps slippage at the room left; replay models the same rule.
- **Momentum Exits** (`strategies/exits.py`): buy-flow stagnation exit (`stagnant_min_buy_sol`), break-even ratchet (`breakeven_ratchet_activation_pct`, `breakeven_buffer_pct`), and the stop-loss redesign keys (`stop_loss_arm_seconds`, `stop_loss_demand_hold_seconds`, `stop_loss_hard_floor`; all `0` = plain stop).
- **Reporting**: buys record `strategy: "momentum"` and `entry_metrics`; `momentum` preset; confirmed-entry replay (`entries_from: confirmed`) and optimizer search space.

---

## 35. Pre-Graduation Lane Via The RPC Poller & PumpSwap Exit (FEAT-53, BUG-123)

Shipped in v0.3.0-rc.1 (Sprint 24H); near-graduation set and PumpSwap exit in rc.2. **Off in `configs/canary.json`** until its 72 h paper pilot passes ([`RELEASE-GATE.md` §3.5](dev/RELEASE-GATE.md)).

- **One Entry Helper** (`bot/handlers/curve.py`): the pre-graduation entry runs from the Geyser curve handler and from the watch poller, so it works on the WebSocket deployment; polled entries need enough readings in the acceleration window. Buys record `strategy: "pre_graduation"` with curve progress and acceleration.
- **Tranche Exits**: sell before the curve completes.
- **PumpSwap Exit** (`sdk/pumpswap.py`, `sdk/pumpswap_execution.py`, `enable_pumpswap_exit`): a held position whose coin graduates is priced from its PumpSwap pool and sold there. Completion is seen from the position refresh, Geyser, PumpPortal `subscribeMigration` and the graduation backfill (`graduation_backfill_seconds`). No live PumpSwap sell built by this code has landed yet.
- **Pilot Config**: `configs/pregrad_pilot.json` (paper, lane and near-graduation set on, no momentum subscriptions).

---

## 36. Shadow Variants & Capture Read-Out Tooling (FEAT-58)

Shipped in v0.3.0-rc.2; read-out tooling and rc.3 additions in v0.3.0-rc.3. Shadow variants never trade.

- **Shadow Variants** (`strategies/shadow.py`, `shadow_variants`): momentum rules logged on paper with their own thresholds, drift guard and flow filters; when one fires, the bot reads the curve after the paper delay and writes an `event: "shadow_entry"` row (fill, drift, refusal). Kinds `pullback` / `pullback_curve` (FEAT-59) were added for rc.3.
- **`pumpfun-replay --shadow-report`** (`engines/shadow_report.py`): per variant signals, refusals, fill drift and a modelled net PnL against a random cut of the baseline, per half with `--split-at`; `--shadow-scan` (`engines/shadow_scan.py`) rebuilds the rows from an older capture.
- **Rule Checks Against A Random Cut**: `pumpfun-audit cuts` (`bot/selection.py`) on audit trails and `pumpfun-replay --keep RULE` (`engines/cuts.py`) on replayed positions.
- **Parameter Sweeps**: `pumpfun-replay --sweep KEY=V1,V2` (`engines/sweep.py`), net per half against the base config.

---

## 37. Recorded Entry Research Inputs (FEAT-54 Phase 1, FEAT-56, FEAT-57, FEAT-60, FEAT-61, FEAT-65 Phase 0)

Measurement only: these inputs are recorded and can be used as shadow filters and `--keep` rules, but **no buy is gated on them**. The gating rules and later phases stay in [`PROPOSED-FEATURES.md`](dev/PROPOSED-FEATURES.md).

- **Wallet Scores (FEAT-54 phase 1)**: `pumpfun-replay --wallet-scores [--validate-path]` (`engines/wallets.py`) ranks wallets by our simulated copy net after delay, penalty and costs.
- **Buy-Flow Concentration (FEAT-56)**: `top_buyer_share`, `wallet_diversity`, `first_poll_sol_growth`, `first_poll_age_seconds` (`OrderFlowEngine.buy_flow_concentration`).
- **Wash-Trade Inputs (FEAT-57)**: `round_trip_wallets`, `round_trip_share`, `quick_flips` (`OrderFlowEngine.round_trip_flow`).
- **Buy Timing (FEAT-60)**: `timing_buys`, `buy_gap_median_seconds`, `buy_gap_cv`, `burst_share`, `buy_size_cv`, `small_buy_share` (`OrderFlowEngine.buy_timing`).
- **Bundle Proxy (FEAT-61)**: `early_holders`, `early_holder_pct` (`HolderDistribution.early_holder_cluster`) in screening capture records.
- **Market Regime**: `market_regime` (UTC hour and weekday, launch and graduation rates) on buys, screening records and the status file (`strategies/regime.py`).
- **Record-Only Curve Observations (rc.3)** (`strategies/observation.py`, `bot/handlers/observe.py`): a deterministic sample of screen-rejected launches (`screen_reject_sample_pct`, rows tagged `reject_sample` with the screen's `reject_reasons`) and curves past `graduation_discovery_min_real_sol` found by a bounded Pump.fun API scan (`graduation_discovery_scan_seconds`, rows tagged `discovery`), polled in their own task as `curve_poll` rows with `observation_start` / `observation_end` records. Never watched, promoted or bought; replay and the shadow tools skip the rows. **Not built**: any rule that relaxes the screen or lets the pre-graduation lane buy discovered curves ([`TODO.md`](dev/TODO.md) Sprints 24G / 24H).
- **Stop Crossings (rc.3)** (`record_stop_crossings`, `execution/sell_pipeline.py`): the first trade-feed and curve-refresh price at or below `stop_loss` per position, and `exit_metrics` (trigger, fill and crossing ratios, lead seconds) on full-exit sell records. **Not built**: a stop triggered on trade-feed prices.
- **Slow-Lane Data (FEAT-65 phase 0, rc.3)** (`services/slow_lane.py`, `pumpfun-recorder --jupiter-quotes` / `--backfill-bars`): a separate, keyless recorder for liquid Solana tokens (`configs/slow_lane_tokens.json`): Jupiter round-trip quotes at 0.02 / 0.1 / 0.5 SOL with route, pools, price impact and round-trip cost, Jupiter prices and liquidity, priority-fee samples for the quoted pools, and GeckoTerminal daily / hourly OHLCV bars. No wallet, no transactions; rows stay out of the Pump.fun captures ([`RUNBOOK.md` §6.4](dev/RUNBOOK.md)). **Not built**: the bar backtester, the strategy, the Jupiter swap client and everything else in [FEAT-65](dev/PROPOSED-FEATURES.md#feat-65-slow-lane-daily-bar-trend-on-liquid-solana-tokens-via-jupiter).
