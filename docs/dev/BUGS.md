# Identified Code Issues and Bugs

This document details all identified bugs, edge-case vulnerabilities, logic flaws, and production-readiness blockers discovered during the comprehensive audit of `pumpfun-trading`.

---

## Status Tracking & Resolution Matrix

| Bug ID | Severity | Area | Status | Resolution Summary |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-01** | High | Execution / Unit Conversion | **RESOLVED** | Exact Lamports integer conversions & AMM sell calculation (`calculate_sell_sol_output`) |
| **BUG-02** | High | Execution / MEV Safety | **RESOLVED** | Added ComputeBudget priority fees & Jito tip transfer bundle submission (`send_jito_bundle`) |
| **BUG-03** | High | Bot / Price Discovery | **RESOLVED** | Binary on-chain bonding curve account decoding (`decode_bonding_curve_data`, `get_bonding_curve_state`) |
| **BUG-04** | High | Bot / Concurrency | **RESOLVED** | Async mutex locking (`_trade_lock`) prevents simultaneous mint race condition |
| **BUG-05** | Medium | UI / Clock Subtraction | **RESOLVED** | Replaced `time.time()` with `time.monotonic()` in dashboard uptime calculations |
| **BUG-06** | Medium | Bot / WebSocket Lifecycle | **RESOLVED** | Exponential backoff with jitter and circuit breaker on disconnections / HTTP 429 |
| **BUG-07** | Medium | Bot / State Recovery | **RESOLVED** | On-chain wallet balance reconciliation (`reconcile_onchain_positions`) at startup |
| **BUG-08** | Medium | Bot / Exit Queue | **RESOLVED** | Exit retry queue (`_exit_retry_queue`) with escalating slippage and emergency liquidation |
| **BUG-09** | Low | Tooling / Pytest Config | **RESOLVED** | Pytest addopts decoupled from forced pytest-cov flags in standalone environments |
| **BUG-10** | Low | Logging / Formatting | **RESOLVED** | Console ANSI stripping formatter (`AnsiStrippingFormatter`) & `NO_COLOR` / non-TTY compliance |
| **BUG-11** | Medium | UI / Terminal Rendering | **RESOLVED** | Alternate screen buffer (`screen=self.console.is_terminal`) & overview panel padding prevent duplicate header scroll artifacts |
| **BUG-12** | High | Bot / Risk Management | **RESOLVED** | Trailing peak equity denominator in portfolio drawdown calculation (`DailyEquityTracker.calculate_drawdown`) |
| **BUG-13** | High | SDK / Bonding Curve Math | **RESOLVED** | Exact constant-product price impact formulas & curve math in `sdk.curve` (`calculate_buy_price_impact`, `calculate_sell_price_impact`) |
| **BUG-14** | Critical | Bot / Risk Management | **RESOLVED** | Aggregate position capital outlay (`cost_sol` / `entry_sol`) in `check_risk_limits` and `check_daily_drawdown` |
| **BUG-15** | Critical | Bot / Circuit Breaker | **RESOLVED** | Calculate position holding valuation (`cost_sol * (current_mc / entry_mc)`) in `evaluate_portfolio_circuit_breaker` and `PositionManager` |
| **BUG-16** | High | Strategy / Exit Engine | **RESOLVED** | Stagnant curve timeout (`stagnant_timeout_seconds`) and max hold duration (`max_hold_time_seconds`) exit rules in `exits.py` and `position_manager.py` |
| **BUG-17** | Low | UI / Presentation | **RESOLVED** | Standardized micro-SOL (`µSOL`) unit price formatting in dashboard positions, trade ledger, and audit tables (`f"{price * 1_000_000:.4f} µSOL"`) |

---

## 1. Critical & High Severity Bugs (Capital Risk & Financial Loss)

### BUG-01: Solana Lamports vs SOL Unit Mismatch in Sell Execution [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`, `pumpfun_trading/sdk/execution.py`
* **Status:** **Fixed** — Implemented bidirectional conversion functions (`sol_to_lamports`, `lamports_to_sol`) and exact Lamports AMM calculations (`calculate_sell_sol_output`) with slippage protection in `build_sell_tx` and `TradingBot._sell_token`.
* **Description:** When evaluating a sell signal or taking profit/stop loss, `should_exit_position` / `should_sell` computes performance based on `current_price` vs `entry_price`. When calculating the minimum output SOL parameter (`min_sol_output`) or passing arguments to `build_sell_tx` / `execute_sell`, the calculation assumes price is in lamports/SOL or passes raw floating point SOL amounts without converting to integer Lamports (`1 SOL = 1,000,000,000 Lamports`). In `build_sell_tx`, `min_sol_output` is packed as a 64-bit integer (`u64`) of lamports.
* **Impact:** Sell transactions submitted on-chain will fail simulation or execute with `min_sol_output` set close to 0 (or fail integer casting), exposing exits to 100% MEV slippage sandwiching or immediate transaction reversion during fast dumps.
* **Remedy:** Ensure explicit conversion between base token units, UI decimals, SOL, and Lamports throughout the execution path, with unit tests validating the exact instruction byte layout against on-chain expectations.

### BUG-02: Missing Priority Fees & Jito / MEV Protection in Live Execution [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py`, `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Added Solana Compute Budget instructions (`SetComputeUnitLimit`, `SetComputeUnitPrice`) and Jito tip transfer instructions + bundle dispatch (`send_jito_bundle`) to protect execution against mempool frontrunning and network congestion.
* **Description:** `PumpFunExecutionClient.build_buy_tx` and `build_sell_tx` construct raw Solana transactions and broadcast them via standard RPC `send_raw_transaction`. They lack dynamic compute unit price instructions (`SetComputeUnitPrice`) and Jito tip transfer instructions for private bundle execution.
* **Impact:** In the high-competition Pump.fun mempool, standard RPC broadcast transactions without high priority fees or Jito bundles will either be dropped, sandwich-attacked by MEV searchers, or confirmed too late after prices have crashed.
* **Remedy:** Implement dynamic priority fee estimation and Jito bundle submission support for private, frontrun-protected transaction execution.

### BUG-03: Single-Point Price Polling and Lack of Bonding Curve State Decoding [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`, `pumpfun_trading/sdk/execution.py`
* **Status:** **Fixed** — Added binary decoding of on-chain bonding curve accounts (`decode_bonding_curve_data` and `get_bonding_curve_state`) directly querying RPC `getAccountInfo` for real-time virtual reserves, market cap, and accurate exit pricing.
* **Description:** The bot relies on polling the off-chain Pump.fun REST API or trade history endpoints (`get_trade_history` / `get_market_info`) to determine token prices and active position PnL. Off-chain REST APIs can lag by 5–30 seconds during peak trading congestion.
* **Impact:** Fast pumps and dumps (which happen in < 3 seconds on Pump.fun) will bypass take-profit and stop-loss logic entirely, causing the bot to hold crashing tokens to zero.
* **Remedy:** Fetch and parse the on-chain bonding curve account state directly via RPC `getAccountInfo` / WebSocket `accountSubscribe` and calculate real-time virtual reserves (`virtualSolReserves`, `virtualTokenReserves`).

### BUG-04: Unbounded Task Spawning and Concurrency Race on Simultaneous Mints [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Added `_trade_lock` async mutex locking in `TradingBot` to ensure atomic evaluation of active positions and token entries during simultaneous mint bursts.
* **Description:** In the main WebSocket loop, incoming trade/mint events trigger `asyncio.create_task(self.handle_event(data))` without limiting the number of concurrent tasks or checking active positions with an atomic lock. If multiple token mint events arrive in the same block or burst, multiple concurrent tasks can pass the `active_positions < max_active_positions` check simultaneously.
* **Impact:** The bot can exceed maximum active positions and commit excess wallet balance into positions, violating portfolio risk limits.
* **Remedy:** Use an `asyncio.Semaphore` or acquire `self._execution_lock` before evaluating active positions and initiating buy sequences.

### BUG-12: Erroneous Portfolio Drawdown Denominator Causes Premature Circuit Breaker Liquidation [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`DailyEquityTracker.calculate_drawdown`, `DailyEquityTracker.evaluate_circuit_breaker`)
* **Status:** **Fixed** — Updated `DailyEquityTracker.calculate_drawdown` to divide peak equity drop (`peak_daily_equity_sol - current_equity`) by `peak_daily_equity_sol` rather than `starting_equity_sol`.
* **Description:** When calculating portfolio drawdown percentage in `DailyEquityTracker.calculate_drawdown`, the numerator was calculated as the drop from the daily peak (`peak_daily_equity_sol - current_equity`), but the denominator used `starting_equity_sol` (baseline). If a portfolio achieved substantial intraday gains from a modest starting baseline (e.g., from 0.20 SOL up to 37.38 SOL), any minor normal pullback (e.g., 0.69 SOL, representing only a ~1.85% retracement from peak) was divided by the starting capital (0.20 SOL), yielding an artificially inflated drawdown percentage (345.18%).
* **Impact:** The inflated drawdown calculation falsely breached the configured `max_daily_drawdown_pct` threshold (e.g., 15–20%), prematurely triggering emergency circuit breakers, locking out trading, and force-liquidating active open positions during profitable runs.
* **Remedy:** Use `peak_daily_equity_sol` as the reference denominator for trailing peak drawdown calculations, ensuring drawdown percentage accurately reflects intraday equity retracement relative to peak equity.

### BUG-13: Inverted Bonding Curve Constant Product Price Impact Calculation [RESOLVED]
* **Location:** `pumpfun_trading/sdk/curve.py` (`calculate_buy_price_impact`, `calculate_sell_price_impact`), `pumpfun_trading/sdk/execution.py`
* **Status:** **Fixed** — Implemented deterministic constant-product ($k = x \cdot y$) pricing and price impact calculations in `pumpfun_trading/sdk/curve.py` and exported them across the SDK.
* **Description:** In previous formulas, post-trade price impact added purchased tokens to reserves upon buying ($y + \Delta y$) and subtracted tokens upon selling ($y - \Delta y$), inverting the constant-product AMM mechanics and depicting price decreasing after buys and increasing after sells.
* **Impact:** Inverted price impact estimates distorted execution slippage models, Kelly bankroll allocation sizing, and bonding curve trajectory forecasting.
* **Remedy:** Implemented `calculate_buy_price_impact` ($x' = x + \Delta x, y' = y - \Delta y$, yielding positive price impact $P_1 / P_0 - 1 > 0$), `calculate_sell_price_impact` ($x' = x - \Delta x, y' = y + \Delta y$, yielding negative price impact $P_1 / P_0 - 1 < 0$), `calculate_buy_tokens_out`, `calculate_sell_sol_out`, `calculate_spot_price`, and `calculate_market_cap_sol` in `sdk.curve`. Bound static delegates in `PumpFunExecutionClient` and added comprehensive unit test suite in `pumpfun_trading/tests/test_curve_math.py`.

### BUG-14: Risk Manager Conflates Token Market Cap with Position Cost in Exposure and Concentration Limits [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`check_risk_limits`, `check_daily_drawdown`)
* **Status:** **Fixed** — Updated `check_risk_limits` and `check_daily_drawdown` to aggregate position capital outlay (`cost_sol` / `entry_sol`) instead of token market capitalization (`entry_market_cap`).
* **Description:** In `check_risk_limits`, `total_exposure` was computed as `sum(float(pos.get("entry_market_cap", 0.0)) for pos in current_positions.values())`, treating the token's total on-chain bonding curve valuation (~27.96–30.0 SOL) as the bot's invested portfolio exposure. It then checked `if total_exposure + proposed_entry_sol > bot.config.max_total_exposure_sol` (default `0.25 SOL`). As soon as 1 position was opened (even for `0.01 SOL`), `total_exposure` evaluated to ~28 SOL, exceeding the `0.25 SOL` cap and causing all subsequent buy orders across the entire 12-hour runtime to be immediately rejected. Furthermore, `max_per_token_ratio` divided `entry_market_cap` (~28 SOL) by `max_total_exposure_sol` (`0.25 SOL`), computing an impossible concentration of 11,184% and triggering the concentration cap check (`> 35%`).
* **Impact:** Directly caused the soak test failure where the bot opened only 1 position in 12 hours and refused to enter any further trades, completely stalling runtime capital deployment.
* **Remedy:** Modified `check_risk_limits` to sum position capital investment (`pos.get("cost_sol") or pos.get("entry_sol", bot.config.buy_amount_sol)`) and compute concentration as `cost_sol / max_total_exposure_sol`. Updated `check_daily_drawdown` baseline equity calculation and added regression tests.

### BUG-15: Erroneous Open Position Valuation in Portfolio Circuit Breaker Sums Market Cap [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`evaluate_portfolio_circuit_breaker`), `pumpfun_trading/bot/position_manager.py` (`calculate_total_open_value`)
* **Status:** **Fixed** — Updated `evaluate_portfolio_circuit_breaker` and `PositionManager.calculate_total_open_value` to compute position holding valuation (`cost_sol * (current_mc / entry_mc)`) rather than raw token bonding curve market capitalization.
* **Description:** In `evaluate_portfolio_circuit_breaker`, `open_val_sol` was calculated as `sum(float(pos["current_market_cap"]) for pos in open_positions.values())`. When a trade opened, portfolio equity spiked from wallet balance (e.g. 0.10 SOL) to ~28.05 SOL. When the position closed (yielding ~0.01 SOL in proceeds), portfolio equity plunged from 28.05 SOL back to 0.10 SOL. The daily equity tracker calculated this as a 99.64% portfolio drawdown, immediately engaging `circuit_breaker_engaged = True`, triggering emergency circuit breakers, locking out trading for `emergency_hard_lock_hours` (24 hours), and halting the bot runtime.
* **Impact:** Any closed trade triggered a false-positive emergency circuit breaker hard lock, shutting down the bot for 24 hours.
* **Remedy:** Modified `evaluate_portfolio_circuit_breaker` to delegate to `bot.position_manager.calculate_total_open_value()` and evaluate position dictionaries using proportional cost holding valuation (`cost_sol * (current_mc / entry_mc)`). Fixed `calculate_total_open_value` to accurately value zero and missing market caps, and added regression tests modeling Pump.fun token lifecycles.

---

## 2. Medium Severity Issues (Runtime Safety & State Integrity)

### BUG-05: Incompatible Monotonic vs Epoch Clock in Dashboard UI [RESOLVED]
* **Location:** `pumpfun_trading/ui/dashboard.py` (lines 53, 71)
* **Status:** **Fixed** — Replaced `time.time()` with `time.monotonic()` in dashboard uptime and message heartbeat calculations to prevent clock mismatch.
* **Description:** The dashboard attempts to display elapsed time since the last message using `time.time() - bot._last_message_at`. However, in `TradingBot.__init__` and `TradingBot.run()`, `_last_message_at` is recorded using `time.monotonic()`.
* **Impact:** `time.time()` (epoch timestamp ~1.7e9) minus `time.monotonic()` (system uptime ~1e4) yields an erroneous value of ~1.7 billion seconds (~55 years ago), displaying broken metrics in the terminal UI and confusing operators.
* **Remedy:** Replace `time.time()` with `time.monotonic()` in `pumpfun_trading/ui/dashboard.py` for all relative uptime calculations.

### BUG-06: Unhandled WebSocket Disconnections and Missing Reconnection Backoff [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Added exponential reconnect backoff with random jitter (`0.85`–`1.25x`) and a circuit breaker that transitions the bot into a degraded health state and sends alerts after exceeding consecutive failure thresholds (`PUMPFUN_WS_MAX_RETRIES`). Automatically recovers and resets upon reconnect.
* **Description:** The WebSocket listener in `run.py` catches `Exception` in a simple loop without exponential backoff or jitter. If the endpoint responds with HTTP 429 (Rate Limit) or closes connections repeatedly, the bot tight-loops, saturating CPU and leading to IP bans from the node provider.
* **Impact:** Operator lockout and missing real-time trade signals during network instability.
* **Remedy:** Implement exponential backoff with jitter and a circuit breaker that transitions the bot into degraded health state.

### BUG-07: Incomplete State Recovery on Bot Restart [RESOLVED]
* **Location:** `pumpfun_trading/storage/status.py`, `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Implemented on-chain position reconciliation (`reconcile_onchain_positions`) executing upon startup to verify active token balances against on-chain wallet holdings (`get_token_balance`), purging closed/liquidated ghost positions and updating live bonding curve valuations.
* **Description:** While `bot_status.json` saves active positions, the restart routine restores dictionaries without re-verifying token account balances or open bonding curve statuses on-chain. If positions were sold externally or liquidated while the bot was offline, the internal ledger falls out of sync with actual wallet balances.
* **Impact:** Ghost positions remain locked in memory, preventing new trades from opening due to the `max_active_positions` limit.
* **Remedy:** Re-sync wallet token accounts (`getTokenAccountsByOwner` / `get_token_balance`) against on-chain balances during startup reconciliation.

### BUG-08: Stale Position Lockup in Execution Queue [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Implemented an exit retry queue (`_exit_retry_queue`, `_enqueue_exit_retry`, `_process_exit_retry_queue`) with escalating slippage (+500 bps per retry up to 5000 bps) and scheduled backoff retries when sell orders fail due to transient network congestion or simulation errors.
* **Description:** When an exit order fails due to network timeout or RPC simulation error, the position remains marked as `active` without an incremental retry counter or fallback emergency dump mechanism.
* **Impact:** The bot never retries selling if the failure reason is non-fatal (e.g., momentary blockhash expiry), leaving capital trapped in depreciating tokens.
* **Remedy:** Implement an exit retry queue with escalating slippage or fallback RPC routing for emergency liquidations.

### BUG-11: Console UI Refresh Scrolling & Duplicate Header Artifacts in Live Dashboard [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py`, `pumpfun_trading/ui/dashboard.py`
* **Status:** **Fixed** — Enabled fullscreen alternate screen buffer mode (`screen=self.console.is_terminal`) in `rich.live.Live` for interactive terminals, optimized atomic update refreshing (`live.update(..., refresh=True)`), and added proper border padding to overview height calculations to prevent row clipping and duplicate header scroll artifacts.
* **Description:** When launching the interactive bot console, `rich.live.Live` was initialized with `screen=False` on multi-panel layouts taller than standard terminal viewports. As the loop refreshed on incoming stream messages and tick intervals, Rich attempted to reposition the cursor above the visible viewport, causing the terminal to scroll continuously and stack duplicate `Trading Bot` and `Overview` header frames down the scrollback buffer. Furthermore, overview sub-panels specified `height=overview_height` without accounting for border padding (+2 lines), clipping inner metrics.
* **Impact:** Distorts console output, clutters operator scrollback with hundreds of repeating partial panels, and obscures live position monitoring.
* **Remedy:** Configure `Live` with `screen=self.console.is_terminal` for interactive terminal sessions, streamline atomic updates, and add border height padding in `build_dashboard`.

### BUG-16: Missing Stagnant / Inactivity Exit Condition Causes Indefinite Position Lockup on Dead Tokens [RESOLVED]
* **Location:** `pumpfun_trading/strategies/exits.py` (`evaluate_exit_strategy`), `pumpfun_trading/bot/position_manager.py` (`PositionExitState`, `PositionManager`), `pumpfun_trading/bot/run.py` (`_refresh_active_positions_market_caps`)
* **Status:** **Fixed** — Implemented stagnant curve inactivity exit rules (`stagnant_timeout_seconds`, `enable_stagnant_exit`, `stagnant_price_delta_threshold_pct`) and maximum hold duration timeouts (`max_hold_time_seconds`, `enable_max_hold_timeout`) across `TradingBotConfig`, `PositionExitState`, `PositionManager`, and `evaluate_exit_strategy`.
* **Description:** On Pump.fun, newly created bonding curves initialize with 30 virtual SOL and 1.073B virtual tokens, resulting in an exact initial creation market cap of $10^9 \times (30 / 1.073\times 10^9) \approx 27.95899\dots\text{ SOL} \approx 27.96\text{ SOL}$. Approximately 80% of newly launched tokens on Pump.fun receive no secondary order flow and remain permanently at 27.96 SOL. The exit evaluator in `exits.py` only checked stop-loss, take-profit, and trailing stops. When market cap remained unchanged at 27.96 SOL (`perf = 1.0` / 100%), no exit triggered. Without a time-based stagnation or inactivity exit rule (`stagnant_timeout_seconds` / `max_hold_time_seconds`), the bot held dead tokens indefinitely, permanently consuming active position slots (`max_active_positions = 1`) and preventing any new tokens from being bought during long soak tests.
* **Impact:** Capital and position slots remain trapped in inactive tokens indefinitely, stalling bot trading activity during multi-hour soak tests.
* **Remedy:** Implemented stagnant curve exit rules and max holding duration timeouts (`stagnant_timeout_seconds`, `max_hold_time_seconds`) in `evaluate_exit_strategy` and `TradingBotConfig`, triggering `FULL_EXIT` when market cap remains unchanged or exceeds maximum hold duration without progress. Configured preset defaults in `DEFAULT_PRESETS` and added unit test coverage.

---

## 3. Low Severity & Quality of Life Bugs

### BUG-09: Pytest / Tox / Nox Configuration Redundancy [RESOLVED]
* **Location:** `pyproject.toml`, `noxfile.py`
* **Status:** **Fixed** — Decoupled `pyproject.toml` `[tool.pytest.ini_options]` `addopts` (`-q`) from mandatory `--cov` flags, allowing standalone `pytest` runs in developer environments lacking `pytest-cov` while maintaining full project-wide coverage enforcement inside `nox -s tests`.
* **Description:** `pyproject.toml` contained `addopts` specifying `--cov` flags requiring `pytest-cov`, causing direct invocations of `pytest` in standard developer environments without `pytest-cov` installed to fail with exit code 4 unless overridden.
* **Impact:** Hinders developer onboarding and non-Nox CI runners.
* **Remedy:** Configure coverage options inside `[tool.pytest.ini_options]` with proper conditionals or run via standard scripts.

### BUG-10: Inconsistent Logging Formats Across Modules [RESOLVED]
* **Location:** `pumpfun_trading/ops/logging.py`, `pumpfun_trading/cli/main.py`, `pumpfun_trading/cli/audit.py`, `pumpfun_trading/cli/replay.py`, `pumpfun_trading/bot/run.py`
* **Status:** **Fixed** — Added `AnsiStrippingFormatter`, `strip_ansi`, `is_color_enabled`, and `get_configured_console` to ensure strict compliance with `NO_COLOR` environment variables and automatically strip ANSI escape sequences when piping logs or executing in non-interactive/non-TTY environments.
* **Description:** Some CLI commands print raw Rich formatted strings to stdout while core runtime writes structured JSON-like lines. When stdout is redirected to a log aggregation agent, ANSI escape sequences pollute log pipelines.
* **Remedy:** Honor `NO_COLOR` environment variable and ensure console handlers strip ANSI codes when stdout is not a TTY.

### BUG-17: UI Dashboard Buy Price Underflow & Column Header Typo [RESOLVED]
* **Location:** `pumpfun_trading/ui/dashboard.py` (lines 140–210), `pumpfun_trading/bot/audit.py` (lines 305–325), `NOTES.md`
* **Status:** **Fixed** — Standardized adaptive micro-SOL (`µSOL`) formatting across open positions tables, trade ledger records, and forensic audit reports (`f"{price * 1_000_000:.4f} µSOL"` for prices $< 0.001\text{ SOL}$), with clear delta percentage formatting (`0.00%`, `+50.00%`, `-20.00%`).
* **Description:** In terminal and status table renderings, token unit prices were formatted using fixed 6-decimal SOL formatting (`{buy_price:.6f} SOL` / `{buy_val:.4f} SOL`). Because standard Pump.fun unit prices are $\approx 0.000000028\text{ SOL}$ ($2.8\times 10^{-8}\text{ SOL}$), fixed 6-decimal rounding rendered unit prices as `0.000000 SOL` or `0.0000 SOL`. Additionally, performance columns rendered raw multiplier ratios instead of relative PnL percentage (`+0.00%` / `0.00%`), and summary table headers contained typos.
* **Impact:** Operators saw misleading `0.000000 SOL` buy prices and confusing performance metrics on flat positions in status tables.
* **Remedy:** Standardized adaptive micro-SOL (`µSOL`) formatting with 4 decimal places for unit prices $< 0.001\text{ SOL}$ (`f"{price * 1_000_000:.4f} µSOL"`) and standard SOL for $\ge 0.001\text{ SOL}$ (`f"{price:.4f} SOL"`) across `dashboard.py` and `audit.py`. Formatted performance as relative delta percentages and added comprehensive test coverage.
