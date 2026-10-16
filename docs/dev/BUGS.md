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
| **BUG-18** | Medium | Bot / Audit Trail | **RESOLVED** | Populate amount_sol on ExecutionResult & fallback proceeds calculation in `_sell_token` |
| **BUG-19** | Medium | UI / Risk Management | **RESOLVED** | Record trade PnL in `DailyEquityTracker` & adaptive micro-SOL Daily PnL display |
| **BUG-20** | High | Engines / Replay Math | **RESOLVED** | Exact price multiplier exits (`price / entry`) and fee/slippage friction math in `PaperTradingEngine` |
| **BUG-21** | High | Bot / Position Valuation | **RESOLVED** | Scale open holding valuation and unrealized PnL by remaining token fraction (`rem_tokens / init_tokens`) |
| **BUG-22** | Medium | Bot / Risk Controls | **RESOLVED** | Include candidate trade outlay (`proposed_entry_sol`) in per-token concentration limit check |
| **BUG-23** | Low | UI / Presentation | **RESOLVED** | Prioritize `remaining_token_amount` over `initial_token_amount` in dashboard active positions table |
| **BUG-24** | High | Execution / Dry-Run Accounting | **RESOLVED** | Dynamic bonding curve token estimation and proportional exit proceeds scaling (`(cost * frac) * (curr_mc / entry_mc)`) |
| **BUG-25** | Medium | Bot / Replay Recording | **RESOLVED** | Hook internal bot buy and sell executions (`_buy_token`, `_sell_token`) to `ReplayRecorder.record_snapshot()` |
| **BUG-26** | Medium | Bot / Audit Trail | **RESOLVED** | Preserve originating parent `position_id` across partial and full exits in `_record_trade` |
| **BUG-27** | Low | Bot / Audit Trail | **RESOLVED** | Differentiate total SOL capital (`cost_sol`, `proceeds_sol`, `sol_amount`) from token unit prices (`unit_price_sol`) |
| **BUG-28** | Low | Bot / Position Valuation | **RESOLVED** | Scale integer base units by UI decimals (`10^6`) in `PositionManager.record_buy` to eliminate `1e-10` unit price underflow |
| **BUG-29** | Medium | UI / Logging Output | **RESOLVED** | Suppress uncaptured `StreamHandler` console logging while interactive `rich.live.Live` dashboard is active & add `--headless` mode |
| **BUG-30** | High | Bot / Dry-Run Cash Accounting | **RESOLVED** | Synchronize simulated wallet cash flows (`wallet_balance_sol`) on dry-run buy/sell executions to prevent false drawdown circuit breaker lockouts |
| **BUG-31** | High | Execution / Buy Token Amount | **RESOLVED** | Dynamic bonding curve token estimation in `build_buy_tx` & wallet balance query in `OrderExecutor.execute_buy` |
| **BUG-32** | Medium | Bot / Config Lifecycle | **RESOLVED** | Preserved full configuration properties using `dataclasses.replace` in `TradingBot.__init__` |
| **BUG-33** | Critical | Execution / On-Chain V2 Instruction Layout | **SUPERSEDED** | Upgraded to Pump.fun BuyV2/SellV2 instructions, Token-2022 compatibility, and dynamic volume/fee/creator PDAs (layout rejected on-chain, see BUG-34) |
| **BUG-34** | Critical | Execution / Live Buy Failures | **RESOLVED** | Mainnet-verified `buy`/`sell` account layout with `bonding-curve-v2` PDA, mayhem-mode fee recipient routing, and `base64` Jito bundle encoding |
| **BUG-35** | Critical | Bot / Position State | **RESOLVED** | RPC token-balance failure reads as zero, so live positions are deleted as "dust" |
| **BUG-36** | Critical | SDK / Raydium Sell | **RESOLVED** | `build_raydium_sell_tx` uses buy-direction token accounts (WSOL → token) |
| **BUG-37** | Critical | Execution / Atomic Arbitrage | **OPEN** | Arb bundle Raydium legs use the token ATA as both source and destination |
| **BUG-38** | Critical | Strategy / Pre-Graduation Exits | **RESOLVED** | Curve progress of ~1% is read as 92–100%, so pre-graduation tranches fire immediately |
| **BUG-39** | High | Bot / Exit Retry Queue | **RESOLVED** | `_process_exit_retry_queue` is never called from the runtime |
| **BUG-40** | High | Bot / Geyser Dispatch | **RESOLVED** | Geyser events are handled twice (callbacks and `listen()`) |
| **BUG-41** | High | Bot / Concurrency | **RESOLVED** | Sells are not covered by `_trade_lock`, so the same mint can be sold twice at once |
| **BUG-42** | High | Strategy / Exit Engine | **RESOLVED** | Take-profit tiers are not latched on emit; pre-graduation tranches are latched before the fill |
| **BUG-43** | High | Strategy / Exit Engine | **RESOLVED** | Pre-graduation `target_tier` 1/2 marks the 2.0x/3.5x take-profit tiers as done |
| **BUG-44** | High | Bot / Graduation | **RESOLVED** | Graduated positions cannot be sold on Raydium |
| **BUG-45** | High | Bot / Persistence | **RESOLVED** | Status snapshot drops `cost_sol` and `pool_keys`; after restart, unit `buy_price` is used as position cost |
| **BUG-46** | High | Bot / Health | **RESOLVED** | `_risk_killed` stays set after transient stream or RPC problems; only a restart clears it |
| **BUG-47** | High | Bot / Daily Circuit Breaker | **RESOLVED** | Daily equity tracker does not roll over at UTC midnight while the breaker is latched |
| **BUG-48** | High | Execution / Sell Proceeds | **RESOLVED** | Live sell proceeds are the slippage floor (`min_sol_lamports`), not actual SOL received |
| **BUG-49** | High | Execution / Buy Fill Size | **RESOLVED** | Buy fill size is the whole ATA balance; fallback estimate uses the post-trade curve |
| **BUG-50** | High | Execution / Raydium Buy | **RESOLVED** | Live Raydium buys record `token_amount=0` |
| **BUG-51** | High | SDK / Raydium Buy | **RESOLVED** | Raydium buy never wraps SOL into WSOL and ignores `slippage_bps` |
| **BUG-52** | High | Execution / Slippage Policy | **RESOLVED** | Dynamic slippage never gets live curve reserves; sells are sized as 0.01 SOL |
| **BUG-53** | High | SDK / Jito Confirmation | **RESOLVED** | Bundles that landed with an on-chain error are reported as successful |
| **BUG-54** | High | SDK / ATA Creation | **RESOLVED** | An ATA lookup error adds a non-idempotent `create_associated_token_account` |
| **BUG-55** | High | Streams / Geyser | **OPEN** | Yellowstone client never opens a gRPC stream and subscribes to mint keys instead of curve PDAs |
| **BUG-56** | High | Strategy / Anti-Rug | **RESOLVED** | `max_gini_coefficient` (0.85) is only a soft penalty; hard reject happens only above 0.95 |
| **BUG-57** | High | Strategy / Anti-Rug | **RESOLVED** | Anti-rug checks pass when holder or dev data is missing |
| **BUG-58** | High | Bot / Dev Wallet Enrichment | **RESOLVED** | `tokens_launched_24h` of 0 falls back to the creator's lifetime launch count |
| **BUG-59** | High | Bot / Cross-Venue Arbitrage | **OPEN** | Arbitrage is quoted and executed on made-up pool reserves |
| **BUG-60** | High | Engines / Optimizer | **RESOLVED** | Holdout (test) fitness is used to select trials (train/test leakage) |
| **BUG-61** | High | Engines / Replay | **OPEN** | Paper replay ignores most parameters the optimizer searches |
| **BUG-62** | High | Engines / Replay Metrics | **RESOLVED** | Profit factor is computed from return percentages, not SOL PnL |
| **BUG-63** | High | Engines / Replay Arbitrage | **RESOLVED** | Replay arbitrage adds profit on every snapshot without committing capital |
| **BUG-64** | High | Ops / Retention | **RESOLVED** | `ops prune` can delete any file in the target directory; `--max-files` is ignored |
| **BUG-65** | Medium | Bot / Token Amount Fallbacks | **RESOLVED** | Remaining balance of `0` is treated as missing and replaced with 100,000,000 raw tokens |
| **BUG-66** | Medium | SDK / Curve Math | **RESOLVED** | Buy/sell curve quotes ignore Pump.fun protocol and creator fees |
| **BUG-67** | Medium | Infra / RPC Pool | **RESOLVED** | JSON-RPC error responses are recorded as endpoint successes |
| **BUG-68** | Medium | SDK / Creator Vault | **RESOLVED** | Creator vault falls back to the trader's own wallet when the creator is unknown |
| **BUG-69** | Medium | SDK / Token Program | **RESOLVED** | Token-2022 detection errors silently fall back to SPL Token |
| **BUG-70** | Medium | Bot / Risk Limits | **RESOLVED** | `check_loss_per_trade` never fires with defaults and can divide by zero |
| **BUG-71** | Medium | Bot / Risk Limits | **RESOLVED** | Exposure cap uses full `cost_sol` after partial exits |
| **BUG-72** | Medium | Storage / Status Snapshot | **RESOLVED** | `storage.write_status_snapshot` is non-atomic and persists a monotonic clock value |
| **BUG-73** | Medium | Execution / Confirmation | **RESOLVED** | Confirmation timeouts are treated as definite failures (untracked fills, possible double sells) |
| **BUG-74** | Medium | Bot / Resource Lifecycle | **RESOLVED** | `start()`/`run()` and `get_coins_by_mints` leave aiohttp sessions open (both fixed) |
| **BUG-75** | Medium | Bot / WebSocket Market Cap | **RESOLVED** | WebSocket market-cap unit check can inflate market cap by ~1e6 |
| **BUG-76** | Medium | Strategy / Exit Engine | **RESOLVED** | Stop-loss and take-profit cannot fire when `entry_market_cap <= 0` |
| **BUG-77** | Medium | Strategy / Memory | **RESOLVED** | Per-mint screening, order-flow, and graduation caches grow without limit |
| **BUG-78** | Medium | Strategy / Risk Validation | **RESOLVED** | `validate_risk_limits` ignores exposure, position size, and concentration caps |
| **BUG-79** | Medium | Strategy / Sybil Detection | **RESOLVED** | When no trades fall inside the wash-trade window, the full trade history is used instead |
| **BUG-80** | Medium | Services / Market Data | **RESOLVED** | Missing market cap defaults to 30 SOL |
| **BUG-81** | Medium | SDK / Raydium Parsing | **RESOLVED** | `parse_raydium_initialize2_accounts` never reads `pc_mint` from the account list |
| **BUG-82** | Medium | Engines / Replay | **RESOLVED** | Pre-graduation harvesting in replay only runs when cross-venue arbitrage is enabled |
| **BUG-83** | Medium | Engines / Replay | **RESOLVED** | Replay can sell and buy again in the same snapshot at an already-known price |
| **BUG-84** | Medium | Engines / Replay | **RESOLVED** | ISO-8601 timestamps sort as time 0 |
| **BUG-85** | Medium | CLI / Replay | **RESOLVED** | `--replay-mode` is never used, and the unified CLI's `--mode` collides with replay's `--mode` |
| **BUG-86** | Medium | CLI / Recorder | **RESOLVED** | `pumpfun-recorder --ws-url` is never used; every API poll is recorded as a buy signal |
| **BUG-87** | Medium | Config / Env Aliases | **RESOLVED** | Status and audit path env var names differ between `get_runtime_env()`, the bot, and the docs |
| **BUG-88** | Medium | UI / Dashboard | **RESOLVED** | Position reason always shows `watch` (reads `reason`, not `entry_reason`) |
| **BUG-89** | Medium | CLI / Events | **RESOLVED** | `pumpfun-events --tail` exits instead of waiting for the file to appear |
| **BUG-90** | Medium | CLI / Arbitrage | **OPEN** | `pumpfun-arb --monitor` / `--live` only evaluate hardcoded sample reserves |
| **BUG-91** | Low | Bot / Lifecycle | **RESOLVED** | An in-flight buy that finishes after shutdown tries to move SHUTDOWN → MONITORING |
| **BUG-92** | Low | Bot / Config | **MITIGATED** | `max_positions_per_mint` is stored but never used (values other than 1 are now clamped to 1 with a warning; per-mint pyramiding is a follow-up) |
| **BUG-93** | Low | SDK / PDA Helpers | **RESOLVED** | Associated bonding-curve helper uses `FEE_RECIPIENT` as the token-program seed |
| **BUG-94** | Low | Bot / Persistence | **RESOLVED** | Failed atomic status writes leave stray `.tmp.<pid>` files |

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

### BUG-20: Replay Engine Mathematical Inversions in Exit Multipliers, Fees, and Token Allocation [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (`PaperTradingEngine.run`)
* **Status:** **Fixed** — Reconciled exit multiplier evaluation (`price_multiplier = price / entry_price`) against `take_profit` and `stop_loss`, corrected fee/slippage cash deduction and token allocation math, and applied fee/slippage deductions on sell proceeds.
* **Description:** In `PaperTradingEngine.run`, three critical mathematical inconsistencies distorted backtest results:
  1. *Exit Multiplier vs Delta Percentage Mismatch:* The replay engine computed position performance as a relative delta `performance = (price - entry) / entry` ($0.0 = \text{breakeven}$, $-0.15 = -15\%$), but evaluated exit conditions using raw strategy multiplier thresholds (`take_profit = 2.0`, `stop_loss = 0.85`). Checking `performance <= -abs(self.stop_loss)` checked `performance <= -0.85` (requiring an 85% catastrophic collapse rather than a 15% stop loss at $0.85\times$), while `performance >= self.take_profit` required a $+200\%$ surge ($3.0\times$) instead of the configured $2.0\times$ take-profit level.
  2. *Inverted Fee and Slippage Quantity Scaling:* When computing buy quantity, `gross_cost = buy_amount * (1.0 + (fee_bps + slippage_bps) / 10_000.0)` was used in `quantity = gross_cost / price`. Multiplying `buy_amount` by the fee ratio increased `gross_cost`, which erroneously *increased* the quantity of tokens received rather than reducing tokens acquired after fees and slippage.
  3. *Negative Cash Balance & Missing Sell Fees:* Deducting `cash -= gross_cost` when `buy_fraction = 1.0` caused `gross_cost > cash`, driving portfolio cash into negative values. In addition, sell exits calculated `exit_value = quantity * price` without deducting sell fees or execution slippage.
* **Impact:** Distorts historical strategy backtests and replay simulations, hiding true strategy drawdown and overestimating simulated token returns.
* **Remedy:** Normalized exit evaluation to multiplier space (`price_multiplier = price / entry`) matching live execution logic in `exits.py`, scaled purchased tokens inversely with fees/slippage (`net_spend = spend_budget / (1 + fee_rate)`, `quantity = net_spend / (price * (1 + slippage))`), clamped spend budget to available cash (`spend_budget = min(cash, cash * buy_fraction)`), deducted fees/slippage from sell proceeds (`exit_value = (quantity * exec_sell_price) * (1 - fee_rate)`), and added regression test coverage.

### BUG-21: Position Valuation & Unrealized PnL Ignore Token Balance Reductions After Partial Exits [RESOLVED]
* **Location:** `pumpfun_trading/bot/position_manager.py` (`Position`, `PositionManager.calculate_total_open_value`, `calculate_unrealized_pnl`), `pumpfun_trading/bot/risk.py` (`evaluate_portfolio_circuit_breaker`, `check_daily_drawdown`)
* **Status:** **Fixed** — Scaled active position cost basis by `remaining_token_amount / initial_token_amount` across `PositionManager` and portfolio risk evaluators.
* **Description:** When positions undergo multi-tier partial exits (e.g. Tier 1 take-profit selling 50% of tokens, Tier 2 selling 25%), `PositionManager.calculate_total_open_value()` and `calculate_unrealized_pnl()` compute holding value as `cost_sol * (curr_mc / entry_mc)`. Because `cost_sol` remains at the full initial capital outlay, open positions that have already realized partial profits continue to be valued at 100% of their initial capital allocation rather than their remaining fractional holding (e.g. 50% or 25%).
* **Impact:** Open portfolio valuation is artificially inflated after partial exits, distorting daily equity tracking, unrealized PnL metrics, and portfolio circuit breaker drawdown computations.
* **Remedy:** Added `remaining_fraction` and `effective_cost_sol` properties to `Position` dataclass, implemented `_extract_position_fraction` helper, scaled active cost basis by `remaining_token_amount / initial_token_amount` in `calculate_total_open_value`, `calculate_unrealized_pnl`, `evaluate_portfolio_circuit_breaker`, and `check_daily_drawdown`, and added regression tests modeling multi-tier partial exit lifecycles.

### BUG-24: Dry-Run Paper Trading Token Sizing and Exit Valuation Mismatch [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (`execute_buy`, `execute_sell`), `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`)
* **Status:** **Fixed** — Computed realistic purchased token quantities from bonding curve virtual reserves on dry-run buys and derived dry-run exit proceeds proportionally as `(cost_sol * frac) * (curr_mc / entry_mc)`.
* **Description:** In dry-run / paper-trading mode (`OrderExecutor.execute_buy`), purchases previously assigned a hardcoded static dummy placeholder of `token_amount = 100_000_000` (100 tokens with 6 decimals) regardless of the actual SOL spent (e.g. `0.01 SOL`) or token market cap (~28–30 SOL). On a real Pump.fun bonding curve, spending `0.01 SOL` purchases approximately ~357,000,000,000 units (~357,000 tokens). When `OrderExecutor.execute_sell` executed in dry-run mode, it queried live on-chain bonding curve reserves and computed the constant-product payout for selling only those 100 tokens (`0.000002916 SOL` / 2.9 µSOL). In `TradingBot._sell_token`, because `exec_res.amount_sol` was `2.916 µSOL` (> 0), the bot took this tiny fraction as the actual total exit proceeds against the `0.005` or `0.01 SOL` cost basis, recording a net loss of `-0.004997 SOL` (-99.94% loss) even when tokens surged +160% to 2.71x.
* **Impact:** In paper-trading mode, all profitable trades (including tokens surging +160% to 2.71x) recorded catastrophic ~99.9% losses in realized PnL, distorting performance validation, daily equity tracking, and strategy calibration.
* **Remedy:** Implemented dynamic token quantity estimation from bonding curve reserves (and default Pump.fun curve fallback of 30 SOL / 1.073B tokens) in `execute_buy`, and scaled dry-run sell exit proceeds proportionally (`(cost_sol * frac) * (curr_mc / entry_mc)`) in `_sell_token`. Added comprehensive regression tests in `test_order_executor.py`.

### BUG-31: Zero Expected Token Amount in Pump.fun Buy Instruction Payload & Unresolved Live Buy Token Balance [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`PumpFunExecutionClient.build_buy_tx`), `pumpfun_trading/execution/executor.py` (`OrderExecutor.execute_buy`)
* **Status:** **Fixed** — Computed expected token output from on-chain virtual reserves (with fallback to default Pump.fun curve reserves of 30 SOL / 1.073B tokens) in `build_buy_tx`, and queried on-chain token balance via `get_token_balance` (with curve calculation fallbacks) upon live transaction confirmation in `OrderExecutor.execute_buy`.
* **Description:** In `PumpFunExecutionClient.build_buy_tx`, the parameter `token_amount` defaulted to `0` when not explicitly supplied by caller routines. In the Pump.fun smart contract instruction layout, passing a `token_amount` of `0` without minimum token output constraints caused on-chain simulation and execution rejections during transaction broadcast. Furthermore, in `OrderExecutor.execute_buy`, live confirmed buy orders returned a static dummy placeholder of `token_amount = 0` in `ExecutionResult`, leaving the bot unable to record actual tokens acquired or track holding quantities on live positions without secondary reconciliation.
* **Impact:** Buy transactions failed on-chain confirmation (`buy_confirmation_failed`) or recorded zero token balances upon live execution, preventing position tracking and downstream take-profit or stop-loss management.
* **Remedy:** Implemented automated bonding curve token output calculation (`calculate_buy_tokens_out`) in `build_buy_tx` using live on-chain virtual reserves or default initial reserves (30 SOL / 1.073B tokens). In `OrderExecutor.execute_buy`, queried confirmed wallet token balances via `get_token_balance` with fallback to curve estimation when live balances are pending RPC indexing. Added comprehensive test coverage in `test_execution_sdk_full.py` and `test_order_executor.py`.

### BUG-33: Legacy Pump.fun V1 Instruction Layout Rejection on Mainnet [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`PumpFunExecutionClient.build_buy_instruction_v2`, `build_sell_instruction_v2`, `build_buy_tx`, `build_sell_tx`, `get_token_program_for_mint`, `decode_bonding_curve_data`)
* **Status:** **Fixed** — Upgraded on-chain instruction assembly to modern Pump.fun `BuyV2` (discriminator `0xb817ee6167c5d33d`, 27 accounts) and `SellV2` (discriminator `0x5df6823ce7e940b2`, 26 accounts), dynamically resolved Token-2022 vs SPL Token programs, decoded bonding curve creator pubkeys (`data[49:81]`) for `creator-vault` PDAs, and derived fee/volume accumulator PDAs.
* **Description:** The Pump.fun smart contract program (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) migrated from legacy 12-account V1 instructions to modern V2 instructions requiring dynamic fee program verification (`pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ`), global and user volume accumulator accounts, creator vaults, and buyback fee accounts. Submitting legacy V1 buy/sell instructions caused validators and Jito block builders to reject transaction simulation with `InstructionError: Custom(6000)` / invalid accounts layout. Additionally, token mints deployed with Solana's Token-2022 program failed Associated Token Account (ATA) derivation and instruction routing when hardcoded to legacy SPL Token program.
* **Impact:** All live buy and sell orders broadcast to Solana mainnet were dropped by validators or rejected during pre-flight simulation, resulting in persistent `buy_confirmation_failed` timeouts (~22.2s polling exhaustion).
* **Remedy:** Implemented `build_buy_instruction_v2` and `build_sell_instruction_v2` with byte-exact discriminators and full account metastructures. Added `get_token_program_for_mint` to dynamically resolve Token-2022 vs SPL Token program IDs. Unpacked creator pubkeys from bonding curve account byte arrays (`data[49:81]`) to derive `creator-vault` PDAs. Derived `global_volume_accumulator`, `user_volume_accumulator`, and fee program `fee_config` PDAs. Added unit and integration test coverage across `test_execution_sdk_full.py`.

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

### BUG-18: Missing Sell Price and Exit Proceeds in Audit Log Records [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (`execute_sell`), `pumpfun_trading/bot/run.py` (`_sell_token`, `_record_trade`), `pumpfun_trading/bot/audit.py` (`_extract_sell_price`)
* **Status:** **Fixed** — Populated `amount_sol` on `ExecutionResult` in `execute_sell` for dry-run and live executions, established proportional market-cap / cost basis fallback exit calculations in `_sell_token`, and ensured matching SOL-denominated trade records in audit logs.
* **Description:** When `_sell_token` executes a sell order via `self.executor.execute_sell(...)`, the returned `ExecutionResult` was constructed without populating `amount_sol` (for both dry-run and live executions). In `TradingBot._sell_token`, `sell_p` was extracted via `getattr(exec_res, "amount_sol", 0.0) or getattr(exec_res, "sol_amount", 0.0) or ...`, which evaluated to `0.0`. Furthermore, there was no fallback calculation (e.g. `pos_entry * (current_market_cap / entry_market_cap)` or bonding curve output estimation `calculate_sell_sol_out`) when `exec_res.amount_sol` was missing or 0. Consequently, `_record_trade` received `exit_value = 0.0` and `sell_price = 0.0`, persisting `0.0` values into the audit log JSONL file (`audit_trail.jsonl`). In `pumpfun_trading/bot/audit.py`, `_extract_sell_price` enforced `f > 0`, causing audit tables rendered by `pumpfun-audit` to display `-` for all sell prices and rendering CLI price filtering flags ineffective.
* **Impact:** Operators could not inspect realized sell prices, exit valuations, or historical sell execution costs in audit logs or via the `pumpfun-audit` CLI tool.
* **Remedy:** Populated `amount_sol` on `ExecutionResult` in `execute_sell` (calculated from min output lamports or simulated curve output in dry-run and live modes), added fallback in `_sell_token` using position market cap ratios / fractional cost bases when `amount_sol` is unset or zero, and ensured `sell_price`, `exit`, and `entry` fields are faithfully written to `_record_trade`. Added unit and regression tests in `test_order_executor.py`.

### BUG-19: Unincremented Daily PnL Counter in Risk Panel & Micro-SOL Display Underflow [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token`), `pumpfun_trading/bot/risk.py` (`DailyEquityTracker.record_realized_trade`), `pumpfun_trading/ui/dashboard.py` (lines 55–62)
* **Status:** **Fixed** — Hooked `record_realized_trade` into trade exit routines and adaptively formatted micro-SOL (`µSOL`) in the dashboard Risk panel to prevent fixed 4-decimal underflow.
* **Description:** In the live terminal UI's Risk panel, the `Daily PnL` counter remained permanently at `+0.0000 SOL`. This stemmed from two compounding issues:
  1. *Missing Realized Trade Recording:* When positions were exited or partially sold in `_sell_token`, the bot never calculated realized trade PnL (`exit_sol - entry_sol`) or invoked `self.daily_equity_tracker.record_realized_trade(pnl_sol)`. As a result, `tracker.realized_daily_pnl_sol` was never incremented during trading and stayed at `0.0`.
  2. *Fixed SOL Decimal Formatting Underflow:* In `pumpfun_trading/ui/dashboard.py`, the Daily PnL row formatted `tracker.realized_daily_pnl_sol` using fixed 4-decimal formatting (`f"{tracker.realized_daily_pnl_sol:+.4f} SOL"`). Even when microcap positions generated non-zero profit/loss (e.g. `+0.000045 SOL`), fixed 4-decimal rounding caused the UI to display `+0.0000 SOL`.
* **Impact:** Operators could not monitor cumulative realized PnL in real time, obscuring daily trading performance, strategy profitability, and intraday capital delta.
* **Remedy:** In `_sell_token` (and position closing routines), calculate realized profit/loss on closed or partial trades and call `self.daily_equity_tracker.record_realized_trade(pnl_sol)`. In `dashboard.py`, update Daily PnL formatting to adaptively render micro-SOL (`f"{pnl * 1_000_000:+.4f} µSOL"`) for non-zero small amounts (`0 < abs(pnl) < 0.001 SOL`) and standard SOL (`f"{pnl:+.4f} SOL"`) otherwise. Added regression tests in `test_ui_and_storage.py` and `test_order_executor.py`.

### BUG-22: Per-Token Concentration Limit Check Ignores Proposed Trade Capital [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`check_risk_limits`)
* **Status:** **Fixed** — Evaluated candidate trade capital outlay (`proposed_entry_sol`) in addition to existing positions against `max_token_concentration_pct`.
* **Description:** In `check_risk_limits`, the per-token concentration check evaluates `max_per_token_ratio = max(_extract_position_cost(pos) / max_total_exposure_sol for pos in current_positions.values())` only across existing positions inside `if current_positions:`. It omitted the `proposed_entry_sol` of the candidate trade currently being screened. Consequently, if `current_positions` was empty or held small positions, a proposed trade that exceeded `max_token_concentration_pct` (e.g. proposed entry 0.10 SOL against 0.25 SOL max exposure = 40% > 35% cap) was not blocked and opened anyway, bypassing portfolio risk allocation safeguards.
* **Impact:** The bot could open oversized single positions that exceed configured per-token portfolio concentration caps.
* **Remedy:** Included `proposed_entry_sol` alongside existing active position costs when calculating `max_per_token_ratio = max(candidate_costs) / max_total_exposure_sol`, rejecting any candidate trade whose capital allocation breaches `max_token_concentration_pct`. Added regression unit test in `test_risk_health_execution.py`.

### BUG-25: Replay Recorder Omits Internal Bot Buy/Sell Executions [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`), `pumpfun_trading/bot/recorder.py` (`ReplayRecorder`)
* **Status:** **Fixed** — Dispatched structured buy and sell execution snapshots into `ReplayRecorder.record_snapshot()` upon successful trade executions.
* **Description:** When asynchronous replay recording was enabled (`--record-replay` / `PUMPFUN_REPLAY_LOG_PATH`), `TradingBot` recorded incoming market ticks and coin discovery updates (`_handle_new_token_created`) to `ReplayRecorder.record_snapshot()`. However, `_buy_token` and `_sell_token` did not dispatch executed trade snapshots to `ReplayRecorder`. In addition, discovery stream updates default to `"is_buy": true, "signal": "buy"`. Consequently, for tokens without secondary network stream trade updates, the recorded `.jsonl` replay file contained only initial buy signals and never recorded any sells or exit events.
* **Impact:** Replay logs generated during live or paper trading omitted trade exit signals and bot trade executions, preventing `pumpfun-replay` from reconstructing and evaluating actual trading session outcomes.
* **Remedy:** Dispatched structured trade execution snapshots (`mint`, `timestamp`, `price`, `market_cap_sol`, `is_buy`, `signal`, `sol_amount`, `token_amount`, `reason`) from `_buy_token` and `_sell_token` into `self.replay_recorder.record_snapshot()`. Added regression test coverage in `test_order_executor.py`.

### BUG-26: Position ID Discorrelation in Audit Trail Exits [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`, `_record_trade`)
* **Status:** **Fixed** — Preserved originating parent `position_id` across partial and full exits in `_sell_token` and `_record_trade`.
* **Description:** In `TradingBot._sell_token`, when `self._record_trade` was called for `partial_sell` and full `sell` actions, neither `position_id` nor the original entry `trade_id` was passed. Inside `_record_trade`, because `position_id` was omitted, the method incremented `self._trade_sequence` and assigned a newly generated identifier as both `trade_id` and `position_id`. Consequently, partial and full exits received new decoupled position IDs (e.g. `trade-000005`, `trade-000008`) rather than inheriting the entry position ID (`trade-000001`).
* **Impact:** Audit consumers, forensic inspectors (`pumpfun-audit`), and performance attribution tools could not correlate partial and full exits back to their originating entry trade by `position_id`, breaking lifecycle trade grouping and per-position PnL reconciliation.
* **Remedy:** Passed originating entry position ID (`position_id` / `trade_id`) into `_sell_token` and `_record_trade` when executing partial or full exits, and generated unique `trade_id` per action while preserving the parent `position_id`.

### BUG-29: Uncaptured Console StreamHandler Logging Underneath Live Terminal UI Causes Viewport Jitter & Jumping [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (lines 400–415, 854–868, 2904–2949), `pumpfun_trading/ops/logging.py` (lines 56–94), `pumpfun_trading/cli/bot.py`, `pumpfun_trading/cli/main.py`
* **Status:** **Fixed** — Suppressed direct console `StreamHandler` logging during interactive `rich.live.Live` rendering sessions and added explicit `--headless` / `PUMPFUN_HEADLESS` support for non-interactive environments.
* **Description:** When running `TradingBot` in interactive terminal mode with `verbose=True` (default), `TradingBot.__init__` configures structured logging via `setup_structured_logging(..., console=self.verbose)`. In `pumpfun_trading/ops/logging.py`, `console=True` attaches a raw `logging.StreamHandler()` writing to `sys.stderr`. While `_render_loop()` executes `rich.live.Live` in alternate screen buffer mode (`screen=True`), runtime operations—such as `self._log()` calls on state transitions, startup reconciliation, health check logs, buy/sell notices, circuit breaker checks, and exception handlers—write unstructured text directly to standard error/output. Because these stream writes bypass the active `Live` context manager rather than being routed through Rich's console print queue (`Live.console.print` / `RichHandler`) or suppressed when interactive fullscreen UI is active, the raw log lines force terminal cursor line feeds, causing the entire dashboard layout to continuously scroll and jump up and down on each refresh tick.
* **Impact:** Visually corrupts terminal UI monitoring, introduces severe display jumping/flicker during trade executions and state events, and obscures real-time active position oversight for operators.
* **Remedy:** Suppressed console `StreamHandler` attachment when interactive `Live` UI rendering is active (`enable_console_logging = bool(self.headless or not self.verbose)`), directing logs exclusively to configured file sinks while allowing console log output in headless mode. Added `--headless` CLI flag and `PUMPFUN_HEADLESS` environment variable support. Added comprehensive unit tests in `test_bugfixes_lifecycle_resilience.py`.

### BUG-30: Missing Simulated Cash Flow Accounting in Dry-Run Mode Triggers False Drawdown Circuit Breakers [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`, `_buy_raydium_token`)
* **Status:** **Fixed** — Synchronized simulated cash flows in dry-run and paper-trading mode by deducting effective buy amounts from `self.wallet_balance_sol` upon buy confirmation and crediting trade proceeds (`sell_p`) upon partial and full sell confirmations. Added unit test in `test_risk_adaptive_ratchet.py`.
* **Description:** In `dry_run` mode, `TradingBot` initializes `self.wallet_balance_sol` with a static starting allocation (e.g., `0.2000 SOL`). When dry-run buy orders executed, `self.wallet_balance_sol` was not decremented by the purchase outlay (`cost_sol`), and when dry-run sell orders executed (e.g., multi-tier take-profits or stop losses), `self.wallet_balance_sol` was not credited with the trade exit proceeds (`sell_p`). In `_refresh_active_positions_market_caps`, `self.wallet_balance_sol` was only refreshed from on-chain RPC when `not self.dry_run`, leaving the simulated wallet balance permanently frozen at its initial level. When a position experienced an explosive run (e.g., 22x) and subsequently closed with substantial realized profits (e.g., +0.1899 SOL banked into realized daily PnL), `DailyEquityTracker` previously recorded a peak portfolio valuation inflated by unrealized paper gains (e.g., 0.3219 SOL). Once the profitable trade concluded and subsequent smaller positions were opened, portfolio equity was evaluated as `frozen_wallet_balance (0.2000 SOL) + open_positions (0.0091 SOL) = 0.2091 SOL` rather than `actual_simulated_cash (0.3899 SOL) + open_positions (0.0091 SOL) = 0.3990 SOL`. Because `(0.3219 - 0.2091) / 0.3219 = 35.03% > 35.00%` (`profit_drawdown_tolerance_pct`), the bot erroneously concluded that portfolio equity had suffered a catastrophic retracement, tripping the `halt_new_buys` circuit breaker despite operating at an all-time account equity high.
* **Impact:** Long-running dry-run, paper-trading, and soak test simulations falsely locked out new trade entries after large profitable runner trades, halting automated trading and distorting simulated performance benchmarks.
* **Remedy:** Synchronized simulated cash flows in `dry_run` and paper-trading modes: deduct capital outlay (`effective_buy_amount`) from `self.wallet_balance_sol` upon buy execution, and credit trade exit proceeds (`sell_p`) to `self.wallet_balance_sol` upon sell execution in `_buy_token`, `_buy_raydium_token`, and `_sell_token`. Added comprehensive regression test in `test_risk_adaptive_ratchet.py`.

### BUG-32: Hardcoded Field Reconstruction in TradingBot Config Initialization Overwrites Custom Settings [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`TradingBot.__init__`)
* **Status:** **Fixed** — Replaced manual constructor parameter mapping with `dataclasses.replace(base, ...)` to preserve all configuration fields loaded from JSON files, presets, and `TradingBotConfig` instances.
* **Description:** In `TradingBot.__init__`, `self.config` was reconstructed by explicitly passing a hardcoded subset of fields to `TradingBotConfig(...)`. Any configuration properties defined outside this explicit parameter mapping—such as `stagnant_timeout_seconds`, `stagnant_price_delta_threshold_pct`, `enable_capital_rotation`, `displacement_hurdle_rate_pct`, `max_cluster_concentration_pct`, etc.—were silently dropped and replaced with system defaults. For example, setting `"stagnant_timeout_seconds": 45.0` in a configuration file or dataclass instance resulted in the runtime and UI dashboard displaying and using the default `120.0s`.
* **Impact:** Custom user configurations, fine-tuned risk controls, and strategy adjustments were silently overwritten with default values upon bot initialization, causing unexpected runtime behavior and UI discrepancies.
* **Remedy:** Refactored `TradingBot.__init__` to use `dataclasses.replace(base, ...)` to override only runtime-injected options (such as `dry_run`, `paper_trade`, `verbose`, `headless`, `stream_url`, `api_base_url`, `replay_log_path`) while preserving 100% of the loaded configuration settings. Added regression tests in `test_ui_and_storage.py`.

### BUG-34: Every Live Buy Fails With `buy_confirmation_failed` [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py`, `pumpfun_trading/sdk/jito.py`
* **Status:** **Fixed** — Buy/sell instructions now mirror successful mainnet Pump.fun `buy` (18 accounts) and `sell` (16 accounts) instructions, mayhem-mode curves route fees to `Global.reserved_fee_recipient`, and Jito `sendBundle` declares `{"encoding": "base64"}`.
* **Description:** Live runs logged `buy_executed` with `error: buy_confirmation_failed` after ~22s for every token, and the reported signatures never appeared on-chain. Simulating the generated transactions showed three causes: (1) the `BuyV2` layout passed the curve creator where the program expects the `sharing_config` PDA, so it failed with `ConstraintSeeds` (error 2006); (2) mayhem-mode curves (bonding curve byte 81) reject the standard fee recipient with `NotAuthorized` (error 6000); (3) Jito `sendBundle` got base64 transactions without an encoding parameter, so it tried to read them as base58 and every bundle was rejected (`transaction #0 could not be decoded`). The bot then fell back to RPC with `skipPreflight`, and the failing transaction never landed.
* **Impact:** The bot could not open any live position.
* **Remedy:** Rebuilt the instruction account lists from decoded mainnet transactions, including the `bonding-curve-v2` PDA and buyback fee recipient. Added `is_mayhem_mode` to `decode_bonding_curve_data` and passed it to the instruction builders. Fixed Jito bundle encoding. Added regression tests in `test_pump_instruction_layout.py`.

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

### BUG-23: Dashboard Positions Table Displays Initial Token Amount Instead of Remaining Balance [RESOLVED]
* **Location:** `pumpfun_trading/ui/dashboard.py` (lines 162–167)
* **Status:** **Fixed** — Updated `raw_tokens` extraction in `build_dashboard` to prioritize `remaining_token_amount` and `token_amount` over `initial_token_amount`, with support for both dictionary representations and `Position` dataclass instances.
* **Description:** In `pumpfun_trading/ui/dashboard.py`, the active positions table extracted token quantity as `raw_tokens = position.get("initial_token_amount") or position.get("token_amount") or position.get("remaining_token_amount") or 0`. Because `initial_token_amount` was evaluated first and never decremented when partial sells occurred, the positions table continued to display the full initial token balance (e.g. 100M tokens) even after Tier 1 or Tier 2 take-profit executions had sold 50% or 75% of the position.
* **Impact:** Misled operators about actual remaining position quantities held after partial exits.
* **Remedy:** Prioritized `remaining_token_amount` and `token_amount` before falling back to `initial_token_amount` across dictionary and dataclass position structures in `dashboard.py`. Added regression test in `test_ui_and_storage.py`.

### BUG-27: Conflation of Token Unit Price and Transaction SOL Capital in Audit Records [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_record_trade`), `pumpfun_trading/bot/audit.py` (`_extract_buy_price`, `_extract_sell_price`, `render_audit_table`)
* **Status:** **Fixed** — Added explicit `cost_sol`, `proceeds_sol`, `sol_amount`, and `unit_price_sol` fields to trade records, and updated audit table extractors to prioritize token unit spot prices.
* **Description:** In `_record_trade`, buy trades previously recorded total SOL spent (`cost_sol`, e.g. `0.01`) as `buy_price`, and sell trades recorded total exit proceeds (`proceeds_sol`, e.g. `2.916e-06`) as `sell_price`. The data schema conflated token unit price (SOL per token, e.g. $\sim 2.8 \times 10^{-8}\text{ SOL}$) with total transaction SOL outlay/proceeds. In `pumpfun_trading/bot/audit.py`, `_extract_buy_price` and `_extract_sell_price` treated these fields as token spot prices and applied micro-SOL formatting (`f"{sell_p * 1_000_000:.4f} µSOL"`), rendering total trade exit proceeds as token spot prices.
* **Impact:** Audit table queries and price filters (`--min-buy-price`, `--max-sell-price`) evaluated against total capital outlay rather than actual execution spot prices, producing distorted table reports.
* **Remedy:** Explicitly differentiated total capital amounts (`sol_amount`, `cost_sol`, `proceeds_sol`) from token unit prices (`unit_price_sol`, `execution_price`) in audit record payloads and table extractors.

### BUG-28: Position Unit Price Underflow via Unscaled Integer Token Division [RESOLVED]
* **Location:** `pumpfun_trading/bot/position_manager.py` (`PositionManager.record_buy`)
* **Status:** **Fixed** — Scaled integer base units by UI token decimals (`10^6`) when calculating effective buy price from `cost_sol` and `token_amount`.
* **Description:** In `PositionManager.record_buy`, when computing effective buy price from `cost_sol` and `token_amount`: `effective_buy_price = float(cost_sol) / int(token_amount)`. Because `token_amount` is passed in raw integer base units ($100 \times 10^6 = 10^8$ base units for 100 tokens with 6 decimals), dividing `0.01 SOL` by $10^8$ without adjusting for SPL token decimals ($10^{-6}$) yielded $10^{-10}\text{ SOL}$, rather than $0.0001\text{ SOL}$ per token ($100\text{ µSOL/token}$).
* **Impact:** Any component relying on `Position.buy_price` or `Position.entry_price` to assess unit price movements or calculate slippage computed an artificially depressed valuation ($10^{-10}$ SOL), leading to erroneous display values in status snapshots and export payloads.
* **Remedy:** Scaled integer `token_amount` by $10^6$ (or derived spot price from `entry_market_cap / 1e9`) in `PositionManager.record_buy`. Added unit test coverage in `test_order_executor.py`.

---

## 4. Open Issues — Project-Wide Audit (2026-10-16): Critical & High Severity

These were found by reading the code. They have not been reproduced or fixed yet. Line numbers are from the working copy at the time of the audit and may drift.

### BUG-35: RPC Token-Balance Failure Treated as Zero, Live Positions Deleted as Dust [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`get_token_balance`, ~L1450–1500), `pumpfun_trading/bot/run.py` (`_sell_token` ~L1910–1916, `_reconcile_positions_on_startup` ~L1983–2005)
* **Description:** `get_token_balance` catches every exception from both of its RPC paths (`except Exception: pass`) and returns `0`. `_sell_token` and startup reconciliation trust that value. If it is at or below `min_sell_balance`, they call `remove_position` and report success.
* **Impact:** A single RPC timeout, a 429, or a parse failure makes the bot forget a real position. The tokens stay in the wallet and are never sold.
* **Remedy:** Return `None` or raise on RPC failure so it is distinct from a real zero balance. Only remove a position after a successful fetch shows dust; otherwise put it in the exit retry queue.

### BUG-36: Raydium Sell Uses Buy-Direction Token Accounts [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`build_raydium_swap_instruction` ~L1028–1044, `build_raydium_sell_tx` ~L1089–1106)
* **Description:** `build_raydium_swap_instruction` defaults the source to the `pc_mint` (WSOL) ATA and the destination to the `coin_mint` (token) ATA, which is the buy direction. `build_raydium_sell_tx` passes `None` for both, so it gets those defaults.
* **Impact:** Every Raydium "sell" (graduation exits, `swap_raydium(is_buy=False)`) either fails or spends WSOL to buy more of the token.
* **Remedy:** For sells, use the token ATA as source and the WSOL ATA as destination, then close the WSOL ATA to unwrap.

### BUG-37: Atomic Arbitrage Raydium Legs Use the Token ATA as Both Source and Destination [OPEN]
* **Location:** `pumpfun_trading/execution/arbitrage.py` (~L74–109)
* **Description:** In both `pump_to_raydium` and `raydium_to_pump`, the Raydium leg sets `user_source_token_account` and `user_destination_token_account` to the same mint ATA. The bundle also never wraps or unwraps WSOL, never creates ATAs, and always derives ATAs with the classic `TOKEN_PROGRAM_ID`, which is wrong for Token-2022 mints.
* **Impact:** Live arbitrage bundles fail or do nothing. Tips and fees are still at risk.
* **Remedy:** Choose WSOL ATA vs token ATA by direction, add create/wrap/unwrap instructions, and derive ATAs with the mint's real token program.

### BUG-38: Pre-Graduation Progress of ~1% Read as 92–100% [RESOLVED]
* **Location:** `pumpfun_trading/strategies/exits.py` (`evaluate_exit_strategy` ~L242–252)
* **Description:** `GraduationCandidate.progress_pct` is a 0–100 percentage. The exit engine only divides by 100 when the value is `> 1.0`. Values from 0.92 to 1.0 (under 1 SOL of real reserves) are left as-is and compared to the fractional tranche targets (`0.92` / `0.97`). They pass, and at exactly `1.0` every tranche fires.
* **Impact:** With `enable_pre_graduation_harvesting`, positions are partly sold right after entry at about 1% curve progress. Together with BUG-43, this can turn into a full exit.
* **Remedy:** Use one scale everywhere: always pass a fraction, or always compare percent to percent. Do not guess the unit from `> 1.0`.

### BUG-39: Exit Retry Queue Is Never Processed [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_process_exit_retry_queue` ~L1870; enqueued at ~L1831–1868, 1992, 2055; never called from `start()` / `_run_health_loop()`)
* **Description:** Failed sells go into `_exit_retry_queue` with backoff and slippage that rises to `max_exit_slippage_bps`, but only tests call `_process_exit_retry_queue`. `get_status_snapshot` also leaves the queue out, so the restore code for it never runs.
* **Impact:** The escalating-slippage exit path (BUG-08) is dead in production. During a fast dump, sells keep failing at base slippage.
* **Remedy:** Drain the queue from the health loop and after stream reconnects. Persist it using wall-clock `next_retry_at` values.

### BUG-40: Geyser Events Are Handled Twice [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`start()` ~L3489–3520), `pumpfun_trading/streams/geyser.py` (`dispatch_*` ~L641–697)
* **Description:** `start()` registers `on_bonding_curve` / `on_trade` / `on_complete` callbacks that call the event router, and it also iterates `listen()` into the same router. Geyser's `dispatch_*` both triggers the callbacks and enqueues the event.
* **Impact:** Every curve, trade, and complete event is processed twice. `order_flow_engine.record_trade` double-counts trades, which skews the buy ratio and z-score and can trigger false momentum entries. Exit evaluation runs twice, which leads to concurrent sells (BUG-41).
* **Remedy:** Use either callbacks or `listen()`, not both.

### BUG-41: Sells Are Not Covered by `_trade_lock` [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token` callers ~L1290–1302, 2351, 2527–2549, 2697–2701, 3085–3108, 3340–3377)
* **Description:** `_trade_lock` only wraps buy paths. The health-loop market-cap refresh, Geyser/WebSocket exit checks, graduation exits, copy-trade mirrors, and emergency liquidation all call `_sell_token` without a lock.
* **Impact:** Two tasks can read the same balance and submit overlapping full or partial sells for the same mint. The second one fails or oversells, and position accounting ends up out of sync.
* **Remedy:** Add a per-mint lock (or reuse `_trade_lock`) that covers the whole balance-check → sell → `record_sell` sequence.

### BUG-42: Take-Profit Tiers Not Latched on Emit; Pre-Grad Tranches Latched Before the Fill [RESOLVED]
* **Location:** `pumpfun_trading/strategies/exits.py` (~L247–253 vs ~L307–366), `pumpfun_trading/strategies/base.py` (`TradingStrategy.evaluate_exit`)
* **Description:** Tier 1/2 decisions only set `tier_X_executed` later in `record_partial_exit`. If the exit is evaluated again before the fill, the same 50%/25% sell is issued again. Pre-graduation tranches do the opposite: they add to `executed_pre_grad_tranches` before the sell lands, so a failed sell is never retried. `TradingStrategy.evaluate_exit` builds a throwaway `PositionExitState` from a dict, so state changes are lost.
* **Impact:** Duplicate partial sells, or tranches that silently get skipped.
* **Remedy:** Set a pending flag when the decision is made, mark it executed only when the fill is confirmed, and clear it on failure. Write the state back when the caller passed a dict.

### BUG-43: Pre-Graduation `target_tier` Marks the Take-Profit Ladder as Done [RESOLVED]
* **Location:** `pumpfun_trading/strategies/exits.py` (~L83–89, ~L247–278)
* **Description:** Pre-graduation tranches return `target_tier = idx + 1` (1 or 2). `record_partial_exit(tier=1/2)` then sets `tier_1_executed` / `tier_2_executed` and turns on `moonbag_active`. On the next evaluation the moonbag check (`perf <= moonbag_trailing_floor` = 2.5x) is true for a position still near 1.x.
* **Impact:** After two harvest fills, the rest of the position is fully sold right away and the 2.0x / 3.5x tiers never run.
* **Remedy:** Give pre-graduation tranches their own tier IDs (e.g. `"pre_grad_1"`) or a separate flag.

### BUG-44: Graduated Positions Cannot Exit on Raydium [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`CompleteEvent` handling ~L2697–2701, `_handle_raydium_pool_update` ~L2716–2717)
* **Description:** When a curve completes, the bot tries to sell through the Pump.fun bonding curve, which no longer accepts trades. The position stays open. When the Raydium pool shows up, `_handle_raydium_pool_update` returns early for any mint that is already held, so it never attaches `pool_keys` or sells through the AMM.
* **Impact:** Positions held through migration get stuck. BUG-35 and BUG-39 make it worse.
* **Remedy:** Mark the position as `migrating` on completion. When pool keys arrive, attach them and sell through Raydium (after BUG-36/51 are fixed).

### BUG-45: Persisted Positions Drop Cost Basis and Raydium Metadata [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`get_status_snapshot` ~L1320–1361, restore ~L673–676, PnL in `_sell_token` ~L2059–2074, 2128–2131, 2189–2192)
* **Description:** The snapshot's `active_positions` keeps `buy_price` (a per-token unit price) but drops `cost_sol` / `entry_sol` / `position_id` / `pool_keys`. After a restart, `_sell_token` falls back to `buy_price` as if it were the total SOL spent.
* **Impact:** Realized PnL after a restart is roughly the full sale proceeds, which inflates daily PnL and skews the circuit breaker. Restored Raydium positions can't find their pool.
* **Remedy:** Persist `position_manager.to_dict()` (or at least `cost_sol`, remaining tokens, `position_id`, `pool_keys`). Never use unit `buy_price` as position cost.

### BUG-46: `_risk_killed` Stays Set After Transient Stream or RPC Problems [RESOLVED]
* **Location:** `pumpfun_trading/bot/health.py` (~L9–24, ~L28–48), `pumpfun_trading/bot/run.py` (`_check_account_equity_guard` ~L1189–1217)
* **Description:** A stale stream or health check sets `_risk_killed = True`. When the stream recovers, `mark_health_check` only resets `_health_ok`. `_check_account_equity_guard` also sets `_risk_killed = True` on any exception from `get_balance_sol()`. Only `start()` or a manual circuit-breaker reset clears the flag.
* **Impact:** A 60s Geyser gap or one flaky balance call stops all new entries until the process restarts.
* **Remedy:** Track the "stream stale" and "RPC error" causes separately from real risk-limit breaches, and clear them automatically on recovery or after a cooldown.

### BUG-47: Daily Equity Tracker Does Not Roll Over at UTC Midnight While the Breaker Is Latched [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`DailyEquityTracker.evaluate_circuit_breaker` ~L140–189, `initialize_or_rollover` ~L84–90)
* **Description:** While `circuit_breaker_engaged` is set and the lock hasn't expired, `evaluate_circuit_breaker` returns early and never calls `initialize_or_rollover`. When a rollover does happen, it resets `circuit_breaker_action` but not `circuit_breaker_engaged` / `locked_at_timestamp`. The unlock path doesn't reset `realized_daily_pnl_sol`.
* **Impact:** A lock at 23:00 UTC with `emergency_hard_lock_hours=24` carries into the next trading day, and the new day's baseline and PnL never start.
* **Remedy:** Always roll over on a UTC date change, and reset the lock state and daily PnL together.

### BUG-48: Live Sell Proceeds Are the Slippage Floor, Not Actual SOL Received [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (`execute_sell` ~L425–436), `pumpfun_trading/bot/run.py` (`_sell_token` ~L2087–2103)
* **Description:** After a confirmed live sell, `amount_sol` is set to `min_sol_lamports / 1e9`, which already has the slippage haircut applied (up to 50% on emergency exits). `_sell_token` uses this as `sell_p`. If it is 0, it falls back to `cost * frac * (curr_mc / entry_mc)`, which is also an estimate.
* **Impact:** Realized PnL, wallet cash, drawdown, and audit records are all systematically understated or modeled rather than based on what actually happened on-chain.
* **Remedy:** Read the actual lamports received (pre/post SOL balance from `getTransaction` meta) and record that as the proceeds.

### BUG-49: Buy Fill Size Is the Whole ATA Balance; Fallback Uses the Post-Trade Curve [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (`execute_buy` ~L212–244)
* **Description:** On success, `acquired_tokens = get_token_balance(mint)` is read without a balance snapshot from before the trade, so dust from earlier positions or airdrops counts as part of this fill. If the balance reads 0 (RPC lag), the fallback calls `calculate_buy_tokens_out` on the current, already-moved reserves with the slippage haircut.
* **Impact:** `initial_token_amount` and cost basis are wrong. Sells can be oversized and fail, or leave tokens untracked.
* **Remedy:** Snapshot the balance before the trade and record `post - pre`, or decode the fill from the transaction meta. Retry the balance read before estimating.

### BUG-50: Live Raydium Buys Record `token_amount=0` [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (`execute_raydium_buy` ~L460, ~L512–519)
* **Description:** A confirmed live Raydium buy returns `ExecutionResult(token_amount=0)`. There is no balance query like the one in `execute_buy`. The dry-run path hardcodes 100,000,000.
* **Impact:** `record_buy(token_amount=0)` creates positions that later exits skip or size with the 100M fallback (BUG-65).
* **Remedy:** Read the token balance difference (or the swap output) after confirmation.

### BUG-51: Raydium Buy Never Wraps SOL and Ignores `slippage_bps` [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`build_raydium_buy_tx` ~L1055–1087)
* **Description:** The swap spends from the WSOL ATA, but the transaction never creates it, transfers lamports into it, or calls `SyncNative`. `slippage_bps` is accepted but never used: `min_amount_out` stays at the caller default of `1`, and `calculate_raydium_swap_out` is never called.
* **Impact:** Raydium buys fail unless a pre-funded WSOL ATA already exists. When they do go through, they have no slippage protection and can be sandwiched for almost the whole input.
* **Remedy:** Add create-ATA → transfer → `SyncNative` → swap → close-account instructions. Compute `min_out` from the pool reserves and `slippage_bps`.

### BUG-52: Dynamic Slippage Never Gets Live Curve Reserves; Sells Sized as 0.01 SOL [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (~L76–87, ~L277–287), `pumpfun_trading/execution/policy.py` (`resolve_parameters` ~L110–184)
* **Description:** `execute_buy` / `execute_sell` call `resolve_parameters` without `virtual_sol_reserves` / `virtual_token_reserves`, so the policy always falls back to the initial 30 SOL curve. Sells also pass a hardcoded `0.01` SOL notional, and `record_curve_update` is never called.
* **Impact:** Price-impact-based slippage is effectively disabled. Late-curve or large trades get slippage that is too tight (exits fail) or too loose.
* **Remedy:** Pass the current reserves and the real trade size in SOL, and feed curve updates into `record_curve_update`.

### BUG-53: Jito Bundles That Landed With an On-Chain Error Count as Success [RESOLVED]
* **Location:** `pumpfun_trading/sdk/jito.py` (`JitoBundleStatus.is_landed` ~L114–125, `wait_for_bundle_confirmation` ~L451–457), `pumpfun_trading/sdk/execution.py` (~L1222–1229)
* **Description:** `is_landed` is true whenever `confirmation_status` is `confirmed`/`finalized`, without looking at `err`. Callers check `is_landed` before `is_failed`. Jito reports success as `{"Ok": null}`, so a plain `err is not None` check would also be wrong.
* **Impact:** A bundle that landed but failed on-chain (slippage exceeded, insufficient funds) is reported as a successful trade.
* **Remedy:** Count a bundle as landed only if it is confirmed and `err` is null or `{"Ok": null}`. Check for failure first.

### BUG-54: ATA Lookup Error Adds a Non-Idempotent ATA Create [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`get_ata_exists` ~L487–526, `build_buy_tx` ~L903–921, `build_raydium_buy_tx` ~L1068–1076)
* **Description:** `get_ata_exists` returns `False` on any exception, and the builder then adds `create_associated_token_account`. If the ATA already exists, the transaction fails with "account already in use".
* **Impact:** Any RPC hiccup during a buy turns a valid buy into a failed transaction, which costs a fee and the entry.
* **Remedy:** Use the idempotent ATA create instruction (`CreateIdempotent`), or treat lookup errors as unknown instead of "missing".

### BUG-55: Yellowstone Geyser Client Never Connects and Subscribes to the Wrong Accounts [OPEN]
* **Location:** `pumpfun_trading/streams/geyser.py` (`_stream_loop` / `_run_mock_or_grpc_stream` ~L741–780, `subscribe_bonding_curves` ~L550–555)
* **Description:** Without a `custom_transport`, the client marks itself `CONNECTED` and then just loops on `asyncio.sleep(0.5)`. It never opens a Yellowstone subscription. `subscribe_bonding_curves(mints)` also filters on mint pubkeys instead of the `["bonding-curve", mint]` PDAs, and `dispatch_raw_account` labels curve PDAs as mints.
* **Impact:** Setting a Geyser endpoint makes the bot sit idle with no market data while showing a healthy connection. Even with a real transport, curve reserves would not be received.
* **Remedy:** Implement the gRPC subscribe (or fail fast when no transport is available), and subscribe to the curve PDAs.

### BUG-56: Configured Gini Cap Is Not a Hard Reject [RESOLVED]
* **Location:** `pumpfun_trading/strategies/filters.py` (`evaluate_holder_distribution` ~L378–387)
* **Description:** `docs/STRATEGY.md` and `max_gini_coefficient` (0.85) say tokens with G > 0.85 are rejected. The code only sets `passed = False` when G > 0.95, and only checks Gini at all when there are at least 5 top holders. For 0.85 < G ≤ 0.95 it adds about 16 penalty points, which is well under `max_acceptable_risk_score` (50).
* **Impact:** Highly concentrated tokens pass the anti-rug screen.
* **Remedy:** Reject when `gini > max_gini`, and fail closed when the holder sample is too small.

### BUG-57: Anti-Rug Checks Pass When Data Is Missing [RESOLVED]
* **Location:** `pumpfun_trading/strategies/filters.py` (~L311–313, 342–343, 362–363, 423–424; `calculate_gini_coefficient`; `token_is_eligible`)
* **Description:** `evaluate_dev_wallet(None)`, `evaluate_creator_holdings(0)`, `evaluate_holder_distribution(None / empty)`, and `evaluate_cluster_heuristics(None)` all pass. `calculate_gini_coefficient([])` returns `0.0` (perfect equality), and `token_is_eligible(screening_verdict=None)` passes.
* **Impact:** When enrichment fails or times out, serial ruggers and concentrated tokens get through, which is exactly when the screen matters most.
* **Remedy:** When `enable_anti_rug_filters` is on, missing data should reject the token or add a large penalty.

### BUG-58: 24h Launch Count of 0 Falls Back to the Lifetime Count [RESOLVED]
* **Location:** `pumpfun_trading/bot/enrichment.py` (~L87–109)
* **Description:** `tokens_launched_24h=count_24h or len(creator_coins)` turns a real `0` into the creator's lifetime launch count. The dict-response branch sets the 24h count to `len(coins_list)` without any time filter. Timestamps are also compared to `now_ms` without checking whether they are in seconds or milliseconds.
* **Impact:** Legitimate developers with past launches are flagged as serial launchers and rejected. The 24h serial-launcher signal is unreliable.
* **Remedy:** Use `count_24h` even when it is 0, normalize timestamps (s vs ms), and apply the 24h filter to both response shapes.

### BUG-59: Cross-Venue Arbitrage Executes on Made-Up Reserves [OPEN]
* **Location:** `pumpfun_trading/bot/run.py` (~L2762–2768, ~L2786–2812)
* **Description:** Raydium reserves are taken from `candidate.real_sol_reserves` (the bonding curve's SOL) plus a hardcoded `200_000_000_000_000` token amount. Pump virtual reserves are also invented (`real_sol + 30` SOL and the same token constant). `arb_executor.execute_arbitrage` can still submit live Jito bundles based on these numbers.
* **Impact:** With `enable_cross_venue_arbitrage` on, the bot can trade on spreads that don't exist.
* **Remedy:** Read the real Raydium vault balances and Pump curve reserves before quoting, and never execute on placeholder values.

### BUG-60: Optimizer Selects Trials Using Holdout Fitness [RESOLVED]
* **Location:** `pumpfun_trading/engines/optimizer.py` (`OptimizationTrial.composite_score` ~L726–732; selection at ~L924, 981, 1023, 1106)
* **Description:** When `test_fitness` exists, `composite_score` is computed from the test objective minus an overfit penalty. Genetic tournament selection, elitism, and the final `best_trial` all rank by this score.
* **Impact:** The walk-forward holdout is used during selection, so the reported out-of-sample scores are optimistically biased.
* **Remedy:** Select on `train_fitness` only, and use test metrics only for reporting.

### BUG-61: Paper Replay Ignores Most Parameters the Optimizer Searches [OPEN]
* **Location:** `pumpfun_trading/engines/replay.py` (~L40–54, ~L478–561), `pumpfun_trading/engines/optimizer.py` (~L352–509, ~L802–828)
* **Description:** The search space varies `buy_amount_sol`, tiered take-profits, trailing stops, drawdown caps, market-cap filters, and more. `PaperTradingEngine` only uses `take_profit` / `stop_loss` / `max_active_positions` and a few flags. It sizes positions with `buy_fraction` of cash and never runs the tiered or trailing exits.
* **Impact:** Fitness is mostly flat across these parameters, and exported "calibrated" configs don't match what was actually simulated.
* **Remedy:** Run the live `TradingStrategy` sizing and exit logic in replay, or limit the search space to fields the engine actually uses.

### BUG-62: Profit Factor Computed From Return Percentages [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (~L605–617), consumed by `pumpfun_trading/engines/optimizer.py` (~L636–645)
* **Description:** `gross_profit` / `gross_loss` add up `return_pct` values instead of SOL `pnl`. For example, +100% on 1 SOL and −50% on 50 SOL gives a profit factor of 2.0 instead of 0.04.
* **Impact:** The `profit_factor` and `composite` optimizer objectives and the CLI summaries are wrong.
* **Remedy:** Sum winning and losing `pnl` in SOL, and skip zero-PnL buy records.

### BUG-63: Replay Arbitrage Adds Profit Every Snapshot Without Committing Capital [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (~L396–446)
* **Description:** On every snapshot with Raydium reserves, a profitable spread does `cash += opp.net_profit_sol` without deducting `optimal_input_sol`, checking that enough cash is available, or applying a per-mint cooldown.
* **Impact:** Replay equity and trade counts can grow without limit, and with arbitrage enabled (the default) this leaks into optimizer fitness.
* **Remedy:** Require `cash >= input`, book each opportunity once, and apply a cooldown.

### BUG-64: `ops prune` Can Delete Any File; `--max-files` Is Ignored [RESOLVED]
* **Location:** `pumpfun_trading/ops/retention.py` (~L257, ~L282–313), `pumpfun_trading/cli/main.py` (~L165–213)
* **Description:** The age-based pass deletes any `*.log*` / `*.jsonl*` older than `--days` under `--target` (default `.`), including active `events.jsonl` and replay datasets. The size-quota pass then lists `glob("*")` and deletes the oldest files of any type (source code, configs, `.env`) until the directory is under `--max-bytes`. `RetentionPolicy.max_files` is never read.
* **Impact:** A routine prune run can delete project files or secrets.
* **Remedy:** Limit both passes to rotated archives that match the log patterns, skip active log files, enforce `max_files`, and default the target to a logs directory.

---

## 5. Open Issues — Project-Wide Audit (2026-10-16): Medium Severity

### BUG-65: Remaining Balance of `0` Replaced With 100,000,000 Raw Tokens [RESOLVED]
* **Location:** `pumpfun_trading/execution/liquidator.py` (~L38–40), `pumpfun_trading/bot/position_manager.py` (`Position.from_dict` ~L131–136, `record_sell` ~L356–357), `pumpfun_trading/strategies/exits.py` (`PositionExitState.from_dict` ~L119–130, `effective_balance` ~L199–211)
* **Description:** These places use `x or y or 100_000_000`. A real `0` is falsy, so a fully sold position falls back to `token_amount` / `initial_token_amount`, or to the 100M default.
* **Impact:** Emergency liquidation or exit logic submits sells for tokens that aren't there. Combined with BUG-50, this always happens for live Raydium positions.
* **Remedy:** Check `is None` instead of using `or`, and never make up a balance. Hold or skip when the balance is 0.

### BUG-66: Curve Quotes Ignore Pump.fun Fees [RESOLVED]
* **Location:** `pumpfun_trading/sdk/curve.py` (`calculate_buy_tokens_out`, `calculate_sell_sol_out` ~L80–141), used in `pumpfun_trading/sdk/execution.py` (`build_buy_tx` ~L890–899, `build_sell_tx` ~L987–998)
* **Description:** Both quotes are pure constant-product (`k = x·y`) and leave out protocol and creator fees. The results are written into the buy `amount` / sell `min_sol_output`, so the fee comes out of the slippage budget.
* **Impact:** With tight slippage (e.g. 250 bps or less), trades can revert with "too much SOL required" / "too little SOL received". The mainnet simulation used 1000 bps, which hid this.
* **Remedy:** Apply the fees from `fee_config` before running the constant-product formula.

### BUG-67: RPC Pool Records JSON-RPC Errors as Successes [RESOLVED]
* **Location:** `pumpfun_trading/infra/rpc_pool.py` (~L448–468)
* **Description:** After an HTTP 200, only errors with code 429 or messages containing `"rate"` / `"limit"` cause a failover. Every other JSON-RPC error (`Blockhash not found`, `-32602`, node behind) calls `record_success` and returns the error payload. A compute-budget error message that contains "limit" can also be mistaken for a rate limit.
* **Impact:** Unhealthy endpoints keep a good health score, and callers misread `result: null` as "account missing".
* **Remedy:** When `"error"` is present, call `record_failure` and fail over (except for deterministic client errors). Detect rate limits by code or HTTP status only.

### BUG-68: Creator Vault Falls Back to the Trader's Wallet [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (~L572–576, ~L659–663, ~L861)
* **Description:** If decoding the bonding curve fails or `creator` is missing, `creator_pubkey = self.wallet`, so the `creator-vault` PDA is derived from the trader's own key.
* **Impact:** The instruction fails on-chain with a seeds constraint error. This is a confusing failure instead of a clear "curve fetch failed".
* **Remedy:** Stop with a clear error when the creator can't be decoded.

### BUG-69: Token-2022 Detection Errors Silently Fall Back to SPL Token [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`get_token_program_for_mint` ~L452–469)
* **Description:** All RPC errors are swallowed and `TOKEN_PROGRAM_ID` is returned.
* **Impact:** For Token-2022 Pump mints, a transient error produces the wrong ATA seeds and the wrong token program in the instruction, so the trade fails.
* **Remedy:** Retry, and abort the trade if the mint owner can't be read. Cache successful results.

### BUG-70: `check_loss_per_trade` Never Fires With Defaults and Can Divide by Zero [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (~L569–574)
* **Description:** The check compares a market-cap loss ratio (at most 1.0) to `max_loss_per_trade_sol / buy_amount_sol` (default `0.02 / 0.01 = 2.0`), so it can never trigger. If `buy_amount_sol == 0`, it raises `ZeroDivisionError` on the hot path.
* **Impact:** The per-trade loss cap does nothing.
* **Remedy:** Compare `cost_sol * loss_ratio` to `max_loss_per_trade_sol`, and guard against a zero denominator.

### BUG-71: Exposure Cap Uses Full `cost_sol` After Partial Exits [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`check_risk_limits` ~L474–476), compare `pumpfun_trading/bot/position_manager.py` (~L524–537)
* **Description:** Exposure adds up the full original `cost_sol` without scaling by the remaining token fraction. `PositionManager.total_cost_sol()` scales correctly (BUG-21), but this path was not updated.
* **Impact:** After take-profit partial sells, `max_total_exposure_sol` and the concentration checks block new entries that should be allowed.
* **Remedy:** Scale cost by `remaining / initial` using the same helper as the valuation code.

### BUG-72: `storage.write_status_snapshot` Is Non-Atomic and Persists a Monotonic Clock [RESOLVED]
* **Location:** `pumpfun_trading/storage/status.py` (~L11–21)
* **Description:** The file is truncated in place with `open(path, "w")`, with no temp file, `fsync`, or `os.replace` (unlike `bot/persistence.py`). It also stores `_last_message_at`, a `time.monotonic()` value that has no meaning after a restart.
* **Impact:** A crash during the write leaves truncated JSON, and crash recovery is lost (`safe_read_status_snapshot` returns `None`).
* **Remedy:** Reuse the atomic write in `StatusPersistenceManager`, and store wall-clock times only.

### BUG-73: Confirmation Timeouts Treated as Definite Failures [RESOLVED]
* **Location:** `pumpfun_trading/execution/executor.py` (~L197–210, ~L410–423, ~L497–510, ~L576–589), `pumpfun_trading/sdk/execution.py` (RPC fallback with `skipPreflight=True`)
* **Description:** When `confirm_transaction` returns `False`, the executor returns `success=False` with a signature. Callers then skip `record_buy` or queue a sell retry, even though the transaction may still land. Because the RPC fallback sends with `skipPreflight=True`, an invalid transaction also waits silently for about 20s before failing.
* **Impact:** A buy that lands late leaves tokens untracked, and a sell that lands late can be sold again.
* **Remedy:** After a timeout, check the signature status and balances again before deciding. Key retries by signature. Run a preflight on the RPC fallback, or simulate first.

### BUG-74: aiohttp Sessions Left Open [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`start()` `finally` ~L3550–3567, `close()` ~L610–626, `run()` ~L3569–3574), `pumpfun_trading/api/client.py` (`get_coins_by_mints` ~L263–267)
* **Description:** On shutdown, `start()` never calls `execution.close()` or `api.close()`, and `run()` never calls `close()`. `get_coins_by_mints` creates a new `PumpFunApiClient` on every call and never closes it, and also ignores `self`'s settings.
* **Impact:** Sockets and file descriptors leak during long sessions ("Unclosed client session" warnings).
* **Remedy:** Call `await self.close()` from `start()`'s `finally`, and use `self.post(...)` in `get_coins_by_mints`.

### BUG-75: WebSocket Market-Cap Unit Check Can Inflate Market Cap ~1e6× [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (~L2892–2898, ~L3030–3035)
* **Description:** If `v_tokens > 1_000_000_000`, the code assumes raw base units and divides by 1e6. PumpPortal reports about 1.073e9 virtual tokens in UI units, which also passes that threshold.
* **Impact:** Entry filters, TP/SL, and trailing stops can run on market caps that are wrong by a factor of about a million. (Medium confidence: depends on the payload format.)
* **Remedy:** Use separate ranges for raw vs UI units (raw is ≳ 1e12), or use on-chain curve reserves.

### BUG-76: Stop-Loss Cannot Fire When `entry_market_cap <= 0` [RESOLVED]
* **Location:** `pumpfun_trading/strategies/exits.py` (~L35–37, ~L226–234)
* **Description:** `performance` is hardcoded to `1.0` when entry MC is 0 or missing, so neither the stop-loss (`<= 0.85`) nor take-profit (`>= 2.0`) can trigger. Time-based exits also fail when `now` is a replay timestamp and `entry_time` defaulted to `time.time()`, because the negative duration is clamped to 0.
* **Impact:** Positions with no stop-loss.
* **Remedy:** Fall back to unit price, or force an exit when there is no valid entry MC, and use the same clock for `entry_time` and `now`.

### BUG-77: Per-Mint Caches Grow Without Limit [RESOLVED]
* **Location:** `pumpfun_trading/strategies/filters.py` (`ScreeningCache` ~L248–299), `pumpfun_trading/strategies/momentum.py` (`OrderFlowEngine` ~L339–354, ~L469–487), `pumpfun_trading/strategies/graduation.py` (~L411–440, ~L652–670)
* **Description:** `evict_expired()`, `cleanup_inactive_tokens()`, and `cleanup_expired_candidates()` are only called from tests. Every mint seen gets a permanent entry.
* **Impact:** Memory keeps growing over long Geyser or WebSocket sessions.
* **Remedy:** Evict on insert (size cap and TTL), and run the cleanups from the health loop.

### BUG-78: `validate_risk_limits` Ignores Exposure Caps [RESOLVED]
* **Location:** `pumpfun_trading/strategies/risk_validation.py` (~L8–27)
* **Description:** It only checks `max_active_positions` and the wallet reserve. `max_total_exposure_sol`, `max_position_size_sol`, `max_token_concentration_pct`, and `max_loss_per_trade_sol` are not checked.
* **Impact:** Anything that relies on `TradingStrategy.validate_risk` (replay, optimizer, external callers) has much weaker protection than the live bot.
* **Remedy:** Delegate to `bot/risk.check_risk_limits`, or implement the same caps here.

### BUG-79: Sybil Wash-Trade Window Falls Back to the Full History [RESOLVED]
* **Location:** `pumpfun_trading/strategies/cluster.py` (~L329–340)
* **Description:** If no trades fall inside `now - window`, the function uses all trades. With replay timestamps and the default `now = time.time()`, the window is always empty.
* **Impact:** In replay, wash ratios are computed over the full history, so time-windowed detection is silently disabled.
* **Remedy:** Return "no wash activity" when the window is empty, and take `now` from the trade clock.

### BUG-80: Missing Market Cap Defaults to 30 SOL [RESOLVED]
* **Location:** `pumpfun_trading/services/market_data.py` (`get_market_cap_sol` ~L40–48)
* **Description:** When no market-cap key parses, the function returns `30.0`, which looks like a real initial curve.
* **Impact:** Tokens with missing or malformed API data can pass min-MC filters or fail max-MC filters, and can be used as an entry MC.
* **Remedy:** Return `None` or `0.0` and let callers skip those tokens.

### BUG-81: `parse_raydium_initialize2_accounts` Never Reads `pc_mint` [RESOLVED]
* **Location:** `pumpfun_trading/sdk/raydium.py` (~L172–225)
* **Description:** `pc_mint` defaults to `WSOL_MINT`, which is truthy, so `accounts[9] if not pc_mint else pc_mint` always keeps WSOL.
* **Impact:** Pools quoted in something other than SOL (and the 18-account fallback layout) get the wrong `pc_mint` and the wrong ATAs.
* **Remedy:** Default `pc_mint` to `""`, like `coin_mint`.

### BUG-82: Replay Pre-Graduation Harvesting Only Runs When Arbitrage Is Enabled [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (~L396–469)
* **Description:** The `evaluate_pre_graduation_harvesting_entry` block is indented inside `if self.enable_cross_venue_arbitrage`.
* **Impact:** Turning arbitrage off silently turns pre-graduation entries off in replay.
* **Remedy:** Unindent the block so only `enable_pre_graduation_harvesting` controls it.

### BUG-83: Replay Sells and Re-Enters in the Same Snapshot [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (~L478–588)
* **Description:** After a TP, SL, or signal sell, the same loop iteration can buy again at the same snapshot price.
* **Impact:** Inflated trade counts and drawdowns that look smoother than they really are (look-ahead bias).
* **Remedy:** Block new entries on a mint until the next snapshot after an exit.

### BUG-84: ISO-8601 Timestamps Sort as Time 0 [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (`_snapshot_float` ~L113–118, sort ~L192–199)
* **Description:** `_snapshot_float` returns `0.0` on `ValueError`, so ISO `created_at` / `timestamp` strings all sort before epoch timestamps.
* **Impact:** Replay ordering and walk-forward splits are wrong for typical API exports.
* **Remedy:** Parse epoch seconds, epoch milliseconds, and ISO datetimes. Keep the original order when parsing fails.

### BUG-85: `--replay-mode` Never Used; Unified CLI `--mode` Collision [RESOLVED]
* **Location:** `pumpfun_trading/cli/replay.py` (~L36–45, ~L121), `pumpfun_trading/cli/main.py` (~L272–276, ~L343–347)
* **Description:** The replay CLI uses `args.mode or args.replay_mode`, but `--mode` always has a default, so `--replay-mode summary` is ignored. `pumpfun replay --mode summary` can also fail validation against the parent parser's `--mode` choices.
* **Impact:** Operators can't select the replay output mode they documented.
* **Remedy:** Give the replay option its own `dest` and remove `--mode` from the parent parser.

### BUG-86: `pumpfun-recorder --ws-url` Never Used; Polls Recorded as Buys [RESOLVED]
* **Location:** `pumpfun_trading/cli/record.py` (~L101–104, ~L272–277)
* **Description:** When Geyser isn't used, harvesting always polls `get_latest_coins()` and stamps every coin with `is_buy=True` / `signal="buy"` at the same wall-clock time. `--ws-url` is parsed but never used.
* **Impact:** Recorded datasets are not trade tapes. In replay, every poll counts as an entry signal.
* **Remedy:** Use `--ws-url` for the PumpPortal subscription, and record quotes without made-up signals.

### BUG-87: Status and Audit Path Env Var Names Inconsistent [RESOLVED]
* **Location:** `pumpfun_trading/config/env.py` (~L103–104), `pumpfun_trading/bot/run.py` (~L378–379), `docs/ENVIRONMENTAL-VARIABLES.md`
* **Description:** The docs list `PUMPFUN_STATUS_PATH` / `PUMPFUN_AUDIT_LOG_PATH` as primary names, with `PUMPFUN_BOT_STATUS_PATH` / `PUMPFUN_AUDIT_LOG` as aliases. `get_runtime_env()` reads only the aliases, and the bot reads only the primary names.
* **Impact:** Depending on which name is set, the setting is ignored by one of the two components.
* **Remedy:** Read primary-or-alias in both places, as the docs describe.

### BUG-88: Dashboard Position Reason Always Shows `watch` [RESOLVED]
* **Location:** `pumpfun_trading/ui/dashboard.py` (~L256, ~L286)
* **Description:** Positions expose `entry_reason`, but the dashboard reads `reason` and falls back to `"watch"`.
* **Impact:** Operators can't see why a position was opened.
* **Remedy:** Read `entry_reason` first, then `reason`.

### BUG-89: `pumpfun-events --tail` Does Not Wait for the File [RESOLVED]
* **Location:** `pumpfun_trading/cli/events.py` (~L340–377)
* **Description:** It prints "Waiting for events file … to be created…" and then immediately calls `open()`. If the file doesn't exist yet, the generic error handler runs and the command exits.
* **Impact:** You can't start `--tail` before the bot.
* **Remedy:** Poll until the file exists (with an optional timeout), then follow it.

### BUG-90: `pumpfun-arb --monitor` / `--live` Only Evaluate Hardcoded Samples [OPEN]
* **Location:** `pumpfun_trading/cli/arbitrage.py` (~L49–60, ~L143–199)
* **Description:** `run_arbitrage_cli` always evaluates two hardcoded reserve tuples. It never reads a stream, wallet, or Jito connection, and `--mint` is only used as a label.
* **Impact:** The advertised monitor and live-execution modes don't work, and the output can be mistaken for real opportunities.
* **Remedy:** Connect `--monitor` to the disparity monitor and real reserve reads, and only execute bundles when `--live` is set. Otherwise label the output as a demo.

---

## 6. Open Issues — Project-Wide Audit (2026-10-16): Low Severity

### BUG-91: In-Flight Buy After Shutdown Attempts SHUTDOWN → MONITORING [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token` ~L1598–1601, `_buy_raydium_token` ~L1697–1700, `_transition_to` ~L807–811)
* **Description:** Observed in `runtime/bot.log` on 2026-10-16: "Ignored invalid state transition from SHUTDOWN to MONITORING due to buy_failed". Shutdown does not cancel or wait for buy tasks that are still running. When one of them fails, it tries to move the bot back to `MONITORING`.
* **Impact:** The state machine blocks it, but a buy can still be sent after shutdown was requested, and if it fills, the result is never recorded.
* **Remedy:** Check `_stop_requested` before sending and before transitioning, and cancel or wait for in-flight trade tasks during shutdown.

### BUG-92: `max_positions_per_mint` Is Ignored [MITIGATED]
* **Location:** `pumpfun_trading/bot/run.py` (stored ~L186, `_should_buy` ~L1472–1473)
* **Description:** `_should_buy` rejects any mint already in `active_positions`, so values above 1 have no effect.
* **Impact:** This config setting does nothing.
* **Remedy:** Count open lots per mint, or remove the field.

### BUG-93: Associated Bonding-Curve PDA Helper Uses Wrong Seeds [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (~L535–539)
* **Description:** ATA seeds must be `[owner, token_program, mint]`, but the helper uses `[bonding_curve, FEE_RECIPIENT, mint]`. The instruction builders currently use `get_associated_token_address(...)` and callers ignore this return value, so live trades are not affected yet.
* **Impact:** A latent bug: any future caller would get the wrong account.
* **Remedy:** Use `get_associated_token_address(bonding_curve, mint, token_program)`.

### BUG-94: Failed Atomic Status Writes Leave Stray Temp Files [RESOLVED]
* **Location:** `pumpfun_trading/bot/persistence.py` (~L61–76)
* **Description:** The `.tmp.<pid>` file is not deleted when the dump or `os.replace` fails.
* **Impact:** Leftover files pile up next to `bot_status.json`. The status file itself is not corrupted.
* **Remedy:** Delete the temp file in a `finally` block if it still exists.
