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
