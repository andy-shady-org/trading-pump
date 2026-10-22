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
| **BUG-37** | Critical | Execution / Atomic Arbitrage | **MITIGATED** | Arb bundle Raydium legs use the token ATA as both source and destination |
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
| **BUG-55** | High | Streams / Geyser | **MITIGATED** | Yellowstone client never opens a gRPC stream and subscribes to mint keys instead of curve PDAs |
| **BUG-56** | High | Strategy / Anti-Rug | **RESOLVED** | `max_gini_coefficient` (0.85) is only a soft penalty; hard reject happens only above 0.95 |
| **BUG-57** | High | Strategy / Anti-Rug | **RESOLVED** | Anti-rug checks pass when holder or dev data is missing |
| **BUG-58** | High | Bot / Dev Wallet Enrichment | **RESOLVED** | `tokens_launched_24h` of 0 falls back to the creator's lifetime launch count |
| **BUG-59** | High | Bot / Cross-Venue Arbitrage | **MITIGATED** | Arbitrage is quoted and executed on made-up pool reserves |
| **BUG-60** | High | Engines / Optimizer | **RESOLVED** | Holdout (test) fitness is used to select trials (train/test leakage) |
| **BUG-61** | High | Engines / Replay | **RESOLVED** | Live-fidelity replay runs the live sizing, risk limits, exit stack and modelled costs; the optimizer searches the exit stack again (Sprint 24C) |
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
| **BUG-90** | Medium | CLI / Arbitrage | **MITIGATED** | `pumpfun-arb --monitor` / `--live` only evaluate hardcoded sample reserves |
| **BUG-91** | Low | Bot / Lifecycle | **RESOLVED** | An in-flight buy that finishes after shutdown tries to move SHUTDOWN → MONITORING |
| **BUG-92** | Low | Bot / Config | **MITIGATED** | `max_positions_per_mint` is stored but never used (values other than 1 are now clamped to 1 with a warning; per-mint pyramiding is a follow-up) |
| **BUG-93** | Low | SDK / PDA Helpers | **RESOLVED** | Associated bonding-curve helper uses `FEE_RECIPIENT` as the token-program seed |
| **BUG-94** | Low | Bot / Persistence | **RESOLVED** | Failed atomic status writes leave stray `.tmp.<pid>` files |
| **BUG-95** | Critical | Bot / Screening | **RESOLVED** | Stream-fed tokens are now enriched from the Pump.fun API, the metadata URI and `getTokenLargestAccounts`; dashboard shows every rejection reason |
| **BUG-96** | High | Execution / Rent Recovery | **RESOLVED** | A full Pump.fun exit now closes the token account in the same transaction (`CloseAccount`), refunding ~0.0015 SOL rent per trade (mainnet rent, 2026-10); rent is tracked in the net PnL (Sprint 24B) |
| **BUG-97** | Medium | Ops / Log Retention | **RESOLVED** | Rotation shifts archives by their on-disk name (`.N` stays plain, `.N.gz` stays compressed) and waits for the previous background gzip before shifting |
| **BUG-98** | Low | Ops / Diagnostics | **RESOLVED** | `emit` normalises unknown category/severity strings to LIFECYCLE/INFO (as `DiagnosticEvent` does) instead of raising |
| **BUG-99** | Medium | Bot / Arbitrage Accounting | **RESOLVED** | Landed arbitrage is booked net: fee, priority fee and tip read from the bundle transaction (modelled when unavailable or in dry-run) and fed to the daily breaker |
| **BUG-100** | Low | Bot / Config | **RESOLVED** | An explicit `stream_url=` argument now wins; config, then env, then default (unchanged for `pumpbot`, which never passes it) |
| **BUG-101** | Medium | SDK / Quoting | **RESOLVED** | Pump.fun builders raise `CurveStateUnavailableError` instead of quoting against initial-curve placeholder reserves |
| **BUG-102** | High | Security / Telemetry | **RESOLVED** | `ops/redact.py` masks credentials in every URL written to `bot_status.json`, config dicts, `bot.log`, `events.jsonl`, dashboard events and alerts (Sprint 24C phase 1) |
| **BUG-103** | Medium | Recorder / Replay data | **RESOLVED** | `ReplayRecorder.close()` no longer drops the batch being written at shutdown; the write is shielded and finished before the cancel is honoured |
| **BUG-104** | High | Paper pricing / Curve decoding | **RESOLVED** | Curves whose `virtual_sol − real_sol` is not the 30 SOL initial reserve raise `NonStandardCurveError` and are never bought or priced; paper entries are priced from the same curve read as exits |
| **BUG-105** | Medium | Audit / PnL reporting | **RESOLVED** | Win rate and expectancy are per closed position (buy + all sells); per-sell win rate kept as `sell_win_rate` |
| **BUG-106** | Low | Lifecycle | **RESOLVED** | `HOLDING → BUYING` allowed; a buy or sell that ends with positions open settles in `HOLDING` |
| **BUG-107** | Medium | Screening / Enrichment | **RESOLVED** | Empty `getTokenLargestAccounts` answers (RPC index flapping) are retried within the lookup budget; outcomes counted in `holder_lookup_stats`; `require_holder_data` makes missing holders a hard reject |
| **BUG-108** | High | Entry screening / Execution | **RESOLVED** | Tokens from other launchpads (PumpPortal `pool` ≠ `pump`, mints without the `…pump` suffix) are rejected before screening; buys require a bonding curve that exists and is owned by the Pump.fun program (`NotPumpFunCurveError`), in paper mode too |
| **BUG-109** | Medium | Entry / Position lifecycle | **RESOLVED** | Every bought mint is kept in `traded_mints` (persisted, capped at 10,000); a mint whose position is closed is never bought again unless `allow_mint_reentry` is set |
| **BUG-110** | Medium | Alerts / Event loop | **RESOLVED** | Webhook alerts sent from the running bot are delivered in a worker thread (`asyncio.to_thread`) instead of a blocking `urlopen` (up to 10 s) on the trading loop; shutdown waits up to 5 s for alerts in flight |
| **BUG-111** | Low | Lifecycle | **RESOLVED** | A sell that starts while a buy is in flight (paper entry delay) hits a rejected `BUYING → SELLING` transition, and its completion sets `MONITORING` under the in-flight buy; state and audit trail wrong for about a second, money and accounting unaffected |
| **BUG-112** | High | Streams / Exits | **RESOLVED** | PumpPortal refuses `subscribeTokenTrade` without a funded API key and the refusal message is dropped, so held positions get no trade data: exits only see the price on the 5 s curve poll, order flow is empty and captures hold no market trades |
| **BUG-113** | Medium | Screening | **RESOLVED** | The creator is taken from the API record before the stream's `traderPublicKey`; when the API returns the system program `1111…1111`, the serial-launcher and rug-history checks run against nothing (10% of screened tokens) |
| **BUG-114** | Low | Risk / Telemetry | **RESOLVED** | `circuit_breaker_trips` grows every 5 s while the breaker stays locked (394 for one trip), and `circuit_breaker_lockout_until` holds the lock time, not the unlock time |
| **BUG-115** | Low | Audit / Reporting | **RESOLVED** | `pumpfun-audit pnl --group-by reason` books every buy's costs (rent, tip, fee) on an `entry` row, so each exit reason shows a positive net while the positions lost money |
| **BUG-116** | High | Streams / Trade feed | **RESOLVED** | A refused `subscribeTokenTrade` was cleared by any reconnect, so buys resumed blind while the PumpPortal API key was still unfunded; now a trade-feed circuit breaker stays open until a probe subscription is confirmed or trade data arrives, and its alert names the likely cause (the key's wallet ran out of funds) |
| **BUG-117** | High | Config / Streams | **RESOLVED** | A `strategy_preset` config filled in the public PumpPortal URL, which beat `PUMPFUN_STREAM_URL`, so the funded API key was never sent and every `subscribeTokenTrade` was refused while the alert blamed the key's funds |
| **BUG-118** | Medium | Security / UI | **RESOLVED** | The dashboard's Coin Polling and Bot Status panels printed the raw stream URL, so the PumpPortal `?api-key=` was shown on screen; the key now lives in its own `PUMPFUN_STREAM_API_KEY` |
| **BUG-119** | Medium | Replay / Parity | **RESOLVED** | `pumpfun-replay --compare-audit` summed only live sell records, so the fee, tip and rent booked on each live buy were left out: the 24 h capture showed live +2.06 SOL against a real −0.579 SOL |
| **BUG-120** | Medium | Streams / Cost | **RESOLVED** | Trade subscriptions were only cancelled when an exit ran from the trade-message path; exits from the 1 s refresh loop, retry queue and other paths left them open, so 538 exited mints kept streaming (54% of all trade messages, billed by PumpPortal) |
| **BUG-121** | Medium | Replay / Parity | **RESOLVED** | Replay filled confirmed (and signal) entries at the signal price and ignored `paper_entry_delay_seconds` / `paper_entry_slippage_bps`, so it ran 0.016–0.023 SOL better than the paper bot on the v0.3.0-rc.1 capture and made the momentum lane look profitable |
| **BUG-122** | Low | Telemetry / Streams | **RESOLVED** | The `connection_loss` counter never moves: `TradingBot._record_connection_loss` has no caller on the stream path, so the rc.1 capture showed 0 while the PumpPortal stream connected 7 times (6 reconnects) |
| **BUG-123** | High | Execution / Graduation | **RESOLVED** | A position held through graduation could not exit: Pump.fun migrates completed curves into PumpSwap, not Raydium, the bot waited for a `RaydiumPoolKeys` pool that never comes, and the WebSocket deployment never even noticed the completion. Now detected from the curve refresh and the free `subscribeMigration` feed and sold into the canonical PumpSwap pool (`sdk/pumpswap.py`) |
| **BUG-124** | Medium | SDK / Curve Decoding | **RESOLVED** | The bonding-curve decoder ignored the new `quote_mint` field, so a USDC-quoted curve would have been priced as if its reserves were lamports; such curves are now refused as non-standard |
| **BUG-125** | Medium | Config | **RESOLVED** | `resolve_strategy_config` dropped 11 fields, so `enable_pumpswap_exit`, `replay_log_path`, the FEAT-50 alert keys and every FEAT-42 `profit_sweep_*` key were ignored in a config file without a warning |
| **BUG-126** | Medium | Replay / Parity | **RESOLVED** | Paper sells took no slippage while replay took 100 bps, so replay ran 0.028 SOL below paper on the rc.2 capture; new `paper_exit_slippage_bps` (100 in the momentum configs) is applied by both |
| **BUG-127** | High | Risk / Circuit breaker | **OPEN** | The adaptive ratchet never protects profit: `effective_baseline_sol` is only displayed, and the profit-run halt compares drawdown against 35% of total equity, so it fires only after equity is already below the start and the principal rule has taken over |
| **BUG-128** | High | Risk / Circuit breaker | **OPEN** | The daily loss limit is not a hard cap: a lock ends at the next 00:00 UTC (not after 24 h), an auto-unlock resets the baseline to post-loss equity, and nothing caps the loss across days |
| **BUG-129** | High | Execution / Parity | **OPEN** | Live entries record the stream's signal market cap as `entry_market_cap` instead of the fill, so stops fire late and take-profits early by the entry drift; only paper fills set `entry_market_cap_sol` |
| **BUG-130** | High | Risk / Startup | **OPEN** | The day's starting equity can be taken from the simulated balance (reserve + 10 buys) when the first live balance read fails, giving a spurious emergency liquidation or a looser limit for the whole UTC day |
| **BUG-131** | Medium | Bot / Raydium lane | **OPEN** | Raydium migration buys hard-code `entry_market_cap=69.0` (likely the USD "$69k" graduation figure read as SOL), so every stop and take-profit on those positions is meaningless; the lane is on by default in conservative / balanced / aggressive |
| **BUG-132** | Medium | Streams / Entry | **OPEN** | The legacy `momentum_spike` entry in the Geyser trade handler is not gated by `entry_mode`, so with a Geyser stream in confirmed mode it can buy without the age window, market-cap band or FEAT-56/57/60 screens |
| **BUG-133** | Medium | Strategy / Maths | **OPEN** | The velocity z-score includes the current slice in its own baseline, capping z at sqrt(N-1) = 3.0 for 30/300 s, and empty pre-creation slices inflate it for young tokens; the conservative threshold of 3.0 passes only after 270 s with no trades |
| **BUG-134** | Medium | Execution / Slippage | **OPEN** | The dynamic-slippage volatility term is effectively always 0 (the estimator is only fed at execution time), and the impact term uses post-trade spot impact (about 2x the execution slippage) |
| **BUG-135** | Medium | Optimizer / Statistics | **OPEN** | Optimizer "Sharpe" is scaled by sqrt(n) (a t-statistic), which biases the 70/30 overfit delta; returns are per sell and skip `partial_sell` (BUG-105 was fixed in `pnl.py` only); Calmar with no drawdown returns 10x the return |
| **BUG-136** | Low | Risk / Valuation | **OPEN** | Open positions are valued at cost times the market-cap ratio, ignoring the sell fee and exit impact, so equity is overstated and the breaker triggers late |
| **BUG-137** | Low | SDK / Units | **OPEN** | `calculate_market_cap_sol` guesses lamports when the reserve is at least 1,000,000, and the `or 30.0` entry fallback is the virtual SOL reserve, not a market cap (about 27.96 SOL) |
| **BUG-138** | Low | Costs / Fees | **OPEN** | `PUMP_DEFAULT_FEE_BPS` is a fixed 125 bps; to be checked against Pump.fun's current fee schedule, which may vary by market cap (not verified) |
| **BUG-139** | Low | Slow lane / Data | **OPEN** | The FEAT-65 sell quote is taken about 2 s after the buy quote, so `round_trip_cost_bps` includes price drift; bars are USD from each token's top pool as of today |
| **BUG-140** | Low | Exits / Concurrency | **OPEN** | Not verified: the exit-pending TTL is 60 s, so a sell that runs through Jito timeout, RPC fallback and retries for longer may let the same take-profit tier fire again |

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
* **Remedy:** Implemented `calculate_buy_price_impact` ($x' = x + \Delta x, y' = y - \Delta y$, yielding positive price impact $P_1 / P_0 - 1 > 0$), `calculate_sell_price_impact` ($x' = x - \Delta x, y' = y + \Delta y$, yielding negative price impact $P_1 / P_0 - 1 < 0$), `calculate_buy_tokens_out`, `calculate_sell_sol_out`, `calculate_spot_price`, and `calculate_market_cap_sol` in `sdk.curve`. Bound static delegates in `PumpFunExecutionClient` and added comprehensive unit test suite in `pumpfun_trading/tests/unit/sdk/test_curve.py`.

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
* **Remedy:** Implemented dynamic token quantity estimation from bonding curve reserves (and default Pump.fun curve fallback of 30 SOL / 1.073B tokens) in `execute_buy`, and scaled dry-run sell exit proceeds proportionally (`(cost_sol * frac) * (curr_mc / entry_mc)`) in `_sell_token`. Added comprehensive regression tests in `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

### BUG-31: Zero Expected Token Amount in Pump.fun Buy Instruction Payload & Unresolved Live Buy Token Balance [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`PumpFunExecutionClient.build_buy_tx`), `pumpfun_trading/execution/executor.py` (`OrderExecutor.execute_buy`)
* **Status:** **Fixed** — Computed expected token output from on-chain virtual reserves (with fallback to default Pump.fun curve reserves of 30 SOL / 1.073B tokens) in `build_buy_tx`, and queried on-chain token balance via `get_token_balance` (with curve calculation fallbacks) upon live transaction confirmation in `OrderExecutor.execute_buy`.
* **Description:** In `PumpFunExecutionClient.build_buy_tx`, the parameter `token_amount` defaulted to `0` when not explicitly supplied by caller routines. In the Pump.fun smart contract instruction layout, passing a `token_amount` of `0` without minimum token output constraints caused on-chain simulation and execution rejections during transaction broadcast. Furthermore, in `OrderExecutor.execute_buy`, live confirmed buy orders returned a static dummy placeholder of `token_amount = 0` in `ExecutionResult`, leaving the bot unable to record actual tokens acquired or track holding quantities on live positions without secondary reconciliation.
* **Impact:** Buy transactions failed on-chain confirmation (`buy_confirmation_failed`) or recorded zero token balances upon live execution, preventing position tracking and downstream take-profit or stop-loss management.
* **Remedy:** Implemented automated bonding curve token output calculation (`calculate_buy_tokens_out`) in `build_buy_tx` using live on-chain virtual reserves or default initial reserves (30 SOL / 1.073B tokens). In `OrderExecutor.execute_buy`, queried confirmed wallet token balances via `get_token_balance` with fallback to curve estimation when live balances are pending RPC indexing. Added comprehensive test coverage in `tests/unit/sdk/test_execution.py` and `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

### BUG-33: Legacy Pump.fun V1 Instruction Layout Rejection on Mainnet [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`PumpFunExecutionClient.build_buy_instruction_v2`, `build_sell_instruction_v2`, `build_buy_tx`, `build_sell_tx`, `get_token_program_for_mint`, `decode_bonding_curve_data`)
* **Status:** **Fixed** — Upgraded on-chain instruction assembly to modern Pump.fun `BuyV2` (discriminator `0xb817ee6167c5d33d`, 27 accounts) and `SellV2` (discriminator `0x5df6823ce7e940b2`, 26 accounts), dynamically resolved Token-2022 vs SPL Token programs, decoded bonding curve creator pubkeys (`data[49:81]`) for `creator-vault` PDAs, and derived fee/volume accumulator PDAs.
* **Description:** The Pump.fun smart contract program (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) migrated from legacy 12-account V1 instructions to modern V2 instructions requiring dynamic fee program verification (`pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ`), global and user volume accumulator accounts, creator vaults, and buyback fee accounts. Submitting legacy V1 buy/sell instructions caused validators and Jito block builders to reject transaction simulation with `InstructionError: Custom(6000)` / invalid accounts layout. Additionally, token mints deployed with Solana's Token-2022 program failed Associated Token Account (ATA) derivation and instruction routing when hardcoded to legacy SPL Token program.
* **Impact:** All live buy and sell orders broadcast to Solana mainnet were dropped by validators or rejected during pre-flight simulation, resulting in persistent `buy_confirmation_failed` timeouts (~22.2s polling exhaustion).
* **Remedy:** Implemented `build_buy_instruction_v2` and `build_sell_instruction_v2` with byte-exact discriminators and full account metastructures. Added `get_token_program_for_mint` to dynamically resolve Token-2022 vs SPL Token program IDs. Unpacked creator pubkeys from bonding curve account byte arrays (`data[49:81]`) to derive `creator-vault` PDAs. Derived `global_volume_accumulator`, `user_volume_accumulator`, and fee program `fee_config` PDAs. Added unit and integration test coverage across `tests/unit/sdk/test_execution.py`.

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
* **Remedy:** Populated `amount_sol` on `ExecutionResult` in `execute_sell` (calculated from min output lamports or simulated curve output in dry-run and live modes), added fallback in `_sell_token` using position market cap ratios / fractional cost bases when `amount_sol` is unset or zero, and ensured `sell_price`, `exit`, and `entry` fields are faithfully written to `_record_trade`. Added unit and regression tests in `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

### BUG-19: Unincremented Daily PnL Counter in Risk Panel & Micro-SOL Display Underflow [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token`), `pumpfun_trading/bot/risk.py` (`DailyEquityTracker.record_realized_trade`), `pumpfun_trading/ui/dashboard.py` (lines 55–62)
* **Status:** **Fixed** — Hooked `record_realized_trade` into trade exit routines and adaptively formatted micro-SOL (`µSOL`) in the dashboard Risk panel to prevent fixed 4-decimal underflow.
* **Description:** In the live terminal UI's Risk panel, the `Daily PnL` counter remained permanently at `+0.0000 SOL`. This stemmed from two compounding issues:
  1. *Missing Realized Trade Recording:* When positions were exited or partially sold in `_sell_token`, the bot never calculated realized trade PnL (`exit_sol - entry_sol`) or invoked `self.daily_equity_tracker.record_realized_trade(pnl_sol)`. As a result, `tracker.realized_daily_pnl_sol` was never incremented during trading and stayed at `0.0`.
  2. *Fixed SOL Decimal Formatting Underflow:* In `pumpfun_trading/ui/dashboard.py`, the Daily PnL row formatted `tracker.realized_daily_pnl_sol` using fixed 4-decimal formatting (`f"{tracker.realized_daily_pnl_sol:+.4f} SOL"`). Even when microcap positions generated non-zero profit/loss (e.g. `+0.000045 SOL`), fixed 4-decimal rounding caused the UI to display `+0.0000 SOL`.
* **Impact:** Operators could not monitor cumulative realized PnL in real time, obscuring daily trading performance, strategy profitability, and intraday capital delta.
* **Remedy:** In `_sell_token` (and position closing routines), calculate realized profit/loss on closed or partial trades and call `self.daily_equity_tracker.record_realized_trade(pnl_sol)`. In `dashboard.py`, update Daily PnL formatting to adaptively render micro-SOL (`f"{pnl * 1_000_000:+.4f} µSOL"`) for non-zero small amounts (`0 < abs(pnl) < 0.001 SOL`) and standard SOL (`f"{pnl:+.4f} SOL"`) otherwise. Added regression tests in `tests/unit/ui/test_dashboard.py` and `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

### BUG-22: Per-Token Concentration Limit Check Ignores Proposed Trade Capital [RESOLVED]
* **Location:** `pumpfun_trading/bot/risk.py` (`check_risk_limits`)
* **Status:** **Fixed** — Evaluated candidate trade capital outlay (`proposed_entry_sol`) in addition to existing positions against `max_token_concentration_pct`.
* **Description:** In `check_risk_limits`, the per-token concentration check evaluates `max_per_token_ratio = max(_extract_position_cost(pos) / max_total_exposure_sol for pos in current_positions.values())` only across existing positions inside `if current_positions:`. It omitted the `proposed_entry_sol` of the candidate trade currently being screened. Consequently, if `current_positions` was empty or held small positions, a proposed trade that exceeded `max_token_concentration_pct` (e.g. proposed entry 0.10 SOL against 0.25 SOL max exposure = 40% > 35% cap) was not blocked and opened anyway, bypassing portfolio risk allocation safeguards.
* **Impact:** The bot could open oversized single positions that exceed configured per-token portfolio concentration caps.
* **Remedy:** Included `proposed_entry_sol` alongside existing active position costs when calculating `max_per_token_ratio = max(candidate_costs) / max_total_exposure_sol`, rejecting any candidate trade whose capital allocation breaches `max_token_concentration_pct`. Added regression unit test in `tests/unit/bot/test_risk.py`.

### BUG-25: Replay Recorder Omits Internal Bot Buy/Sell Executions [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`), `pumpfun_trading/bot/recorder.py` (`ReplayRecorder`)
* **Status:** **Fixed** — Dispatched structured buy and sell execution snapshots into `ReplayRecorder.record_snapshot()` upon successful trade executions.
* **Description:** When asynchronous replay recording was enabled (`--record-replay` / `PUMPFUN_REPLAY_LOG_PATH`), `TradingBot` recorded incoming market ticks and coin discovery updates (`_handle_new_token_created`) to `ReplayRecorder.record_snapshot()`. However, `_buy_token` and `_sell_token` did not dispatch executed trade snapshots to `ReplayRecorder`. In addition, discovery stream updates default to `"is_buy": true, "signal": "buy"`. Consequently, for tokens without secondary network stream trade updates, the recorded `.jsonl` replay file contained only initial buy signals and never recorded any sells or exit events.
* **Impact:** Replay logs generated during live or paper trading omitted trade exit signals and bot trade executions, preventing `pumpfun-replay` from reconstructing and evaluating actual trading session outcomes.
* **Remedy:** Dispatched structured trade execution snapshots (`mint`, `timestamp`, `price`, `market_cap_sol`, `is_buy`, `signal`, `sol_amount`, `token_amount`, `reason`) from `_buy_token` and `_sell_token` into `self.replay_recorder.record_snapshot()`. Added regression test coverage in `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

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
* **Remedy:** Suppressed console `StreamHandler` attachment when interactive `Live` UI rendering is active (`enable_console_logging = bool(self.headless or not self.verbose)`), directing logs exclusively to configured file sinks while allowing console log output in headless mode. Added `--headless` CLI flag and `PUMPFUN_HEADLESS` environment variable support. Added comprehensive unit tests in `tests/unit/bot/test_run.py` / `tests/unit/ops/test_logging.py` (formerly `test_bugfixes_lifecycle_resilience.py`).

### BUG-30: Missing Simulated Cash Flow Accounting in Dry-Run Mode Triggers False Drawdown Circuit Breakers [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_buy_token`, `_sell_token`, `_buy_raydium_token`)
* **Status:** **Fixed** — Synchronized simulated cash flows in dry-run and paper-trading mode by deducting effective buy amounts from `self.wallet_balance_sol` upon buy confirmation and crediting trade proceeds (`sell_p`) upon partial and full sell confirmations. Added unit test in `tests/unit/bot/test_risk.py`.
* **Description:** In `dry_run` mode, `TradingBot` initializes `self.wallet_balance_sol` with a static starting allocation (e.g., `0.2000 SOL`). When dry-run buy orders executed, `self.wallet_balance_sol` was not decremented by the purchase outlay (`cost_sol`), and when dry-run sell orders executed (e.g., multi-tier take-profits or stop losses), `self.wallet_balance_sol` was not credited with the trade exit proceeds (`sell_p`). In `_refresh_active_positions_market_caps`, `self.wallet_balance_sol` was only refreshed from on-chain RPC when `not self.dry_run`, leaving the simulated wallet balance permanently frozen at its initial level. When a position experienced an explosive run (e.g., 22x) and subsequently closed with substantial realized profits (e.g., +0.1899 SOL banked into realized daily PnL), `DailyEquityTracker` previously recorded a peak portfolio valuation inflated by unrealized paper gains (e.g., 0.3219 SOL). Once the profitable trade concluded and subsequent smaller positions were opened, portfolio equity was evaluated as `frozen_wallet_balance (0.2000 SOL) + open_positions (0.0091 SOL) = 0.2091 SOL` rather than `actual_simulated_cash (0.3899 SOL) + open_positions (0.0091 SOL) = 0.3990 SOL`. Because `(0.3219 - 0.2091) / 0.3219 = 35.03% > 35.00%` (`profit_drawdown_tolerance_pct`), the bot erroneously concluded that portfolio equity had suffered a catastrophic retracement, tripping the `halt_new_buys` circuit breaker despite operating at an all-time account equity high.
* **Impact:** Long-running dry-run, paper-trading, and soak test simulations falsely locked out new trade entries after large profitable runner trades, halting automated trading and distorting simulated performance benchmarks.
* **Remedy:** Synchronized simulated cash flows in `dry_run` and paper-trading modes: deduct capital outlay (`effective_buy_amount`) from `self.wallet_balance_sol` upon buy execution, and credit trade exit proceeds (`sell_p`) to `self.wallet_balance_sol` upon sell execution in `_buy_token`, `_buy_raydium_token`, and `_sell_token`. Added comprehensive regression test in `tests/unit/bot/test_risk.py`.

### BUG-32: Hardcoded Field Reconstruction in TradingBot Config Initialization Overwrites Custom Settings [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`TradingBot.__init__`)
* **Status:** **Fixed** — Replaced manual constructor parameter mapping with `dataclasses.replace(base, ...)` to preserve all configuration fields loaded from JSON files, presets, and `TradingBotConfig` instances.
* **Description:** In `TradingBot.__init__`, `self.config` was reconstructed by explicitly passing a hardcoded subset of fields to `TradingBotConfig(...)`. Any configuration properties defined outside this explicit parameter mapping—such as `stagnant_timeout_seconds`, `stagnant_price_delta_threshold_pct`, `enable_capital_rotation`, `displacement_hurdle_rate_pct`, `max_cluster_concentration_pct`, etc.—were silently dropped and replaced with system defaults. For example, setting `"stagnant_timeout_seconds": 45.0` in a configuration file or dataclass instance resulted in the runtime and UI dashboard displaying and using the default `120.0s`.
* **Impact:** Custom user configurations, fine-tuned risk controls, and strategy adjustments were silently overwritten with default values upon bot initialization, causing unexpected runtime behavior and UI discrepancies.
* **Remedy:** Refactored `TradingBot.__init__` to use `dataclasses.replace(base, ...)` to override only runtime-injected options (such as `dry_run`, `paper_trade`, `verbose`, `headless`, `stream_url`, `api_base_url`, `replay_log_path`) while preserving 100% of the loaded configuration settings. Added regression tests in `tests/unit/ui/test_dashboard.py`.

### BUG-34: Every Live Buy Fails With `buy_confirmation_failed` [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py`, `pumpfun_trading/sdk/jito.py`
* **Status:** **Fixed** — Buy/sell instructions now mirror successful mainnet Pump.fun `buy` (18 accounts) and `sell` (16 accounts) instructions, mayhem-mode curves route fees to `Global.reserved_fee_recipient`, and Jito `sendBundle` declares `{"encoding": "base64"}`.
* **Description:** Live runs logged `buy_executed` with `error: buy_confirmation_failed` after ~22s for every token, and the reported signatures never appeared on-chain. Simulating the generated transactions showed three causes: (1) the `BuyV2` layout passed the curve creator where the program expects the `sharing_config` PDA, so it failed with `ConstraintSeeds` (error 2006); (2) mayhem-mode curves (bonding curve byte 81) reject the standard fee recipient with `NotAuthorized` (error 6000); (3) Jito `sendBundle` got base64 transactions without an encoding parameter, so it tried to read them as base58 and every bundle was rejected (`transaction #0 could not be decoded`). The bot then fell back to RPC with `skipPreflight`, and the failing transaction never landed.
* **Impact:** The bot could not open any live position.
* **Remedy:** Rebuilt the instruction account lists from decoded mainnet transactions, including the `bonding-curve-v2` PDA and buyback fee recipient. Added `is_mayhem_mode` to `decode_bonding_curve_data` and passed it to the instruction builders. Fixed Jito bundle encoding. Added regression tests in `tests/unit/sdk/test_execution.py` (`test_buy_instruction_matches_mainnet_layout`, `test_sell_instruction_matches_mainnet_layout`).

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
* **Remedy:** Prioritized `remaining_token_amount` and `token_amount` before falling back to `initial_token_amount` across dictionary and dataclass position structures in `dashboard.py`. Added regression test in `tests/unit/ui/test_dashboard.py`.

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
* **Remedy:** Scaled integer `token_amount` by $10^6$ (or derived spot price from `entry_market_cap / 1e9`) in `PositionManager.record_buy`. Added unit test coverage in `tests/unit/execution/test_executor.py` / `tests/unit/bot/test_run.py` (formerly `test_order_executor.py`).

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

### BUG-37: Atomic Arbitrage Raydium Legs Use the Token ATA as Both Source and Destination [MITIGATED]
* **Location:** `pumpfun_trading/execution/arbitrage.py` (~L74–109)
* **Description:** In both `pump_to_raydium` and `raydium_to_pump`, the Raydium leg sets `user_source_token_account` and `user_destination_token_account` to the same mint ATA. The bundle also never wraps or unwraps WSOL, never creates ATAs, and always derives ATAs with the classic `TOKEN_PROGRAM_ID`, which is wrong for Token-2022 mints.
* **Impact:** Live arbitrage bundles fail or do nothing. Tips and fees are still at risk.
* **Remedy:** Choose WSOL ATA vs token ATA by direction, add create/wrap/unwrap instructions, and derive ATAs with the mint's real token program.
* **Resolution (MITIGATED):** Raydium legs now swap token ATA ↔ WSOL ATA by direction, with idempotent ATA creation, WSOL wrap/unwrap and the mint's real token program. Not verified on mainnet; live execution stays blocked by the BUG-59 guard. Follow-up: mainnet simulate of both directions.

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

### BUG-55: Yellowstone Geyser Client Never Connects and Subscribes to the Wrong Accounts [MITIGATED]
* **Location:** `pumpfun_trading/streams/geyser.py` (`_stream_loop` / `_run_mock_or_grpc_stream` ~L741–780, `subscribe_bonding_curves` ~L550–555)
* **Description:** Without a `custom_transport`, the client marks itself `CONNECTED` and then just loops on `asyncio.sleep(0.5)`. It never opens a Yellowstone subscription. `subscribe_bonding_curves(mints)` also filters on mint pubkeys instead of the `["bonding-curve", mint]` PDAs, and `dispatch_raw_account` labels curve PDAs as mints.
* **Impact:** Setting a Geyser endpoint makes the bot sit idle with no market data while showing a healthy connection. Even with a real transport, curve reserves would not be received.
* **Remedy:** Implement the gRPC subscribe (or fail fast when no transport is available), and subscribe to the curve PDAs.
* **Resolution (MITIGATED):** `YellowstoneGeyserClient.start()` raises `GeyserTransportUnavailableError` when no gRPC transport is wired in (no fake CONNECTED state), and `TradingBot` falls back to the WebSocket stream with an error event. Curve subscriptions use the bonding-curve PDA and map updates back to the mint. Follow-up: implement the real Yellowstone gRPC subscribe transport.

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

### BUG-59: Cross-Venue Arbitrage Executes on Made-Up Reserves [MITIGATED]
* **Location:** `pumpfun_trading/bot/run.py` (~L2762–2768, ~L2786–2812)
* **Description:** Raydium reserves are taken from `candidate.real_sol_reserves` (the bonding curve's SOL) plus a hardcoded `200_000_000_000_000` token amount. Pump virtual reserves are also invented (`real_sol + 30` SOL and the same token constant). `arb_executor.execute_arbitrage` can still submit live Jito bundles based on these numbers.
* **Impact:** With `enable_cross_venue_arbitrage` on, the bot can trade on spreads that don't exist.
* **Remedy:** Read the real Raydium vault balances and Pump curve reserves before quoting, and never execute on placeholder values.
* **Resolution (MITIGATED):** `ArbitrageOpportunity.reserves_verified` (default False) gates execution: `AtomicArbitrageExecutor` refuses live bundles and `TradingBot` neither executes nor banks dry-run profit on placeholder reserves. Follow-up: read Raydium vault balances and live curve reserves, then set `reserves_verified=True`.

### BUG-60: Optimizer Selects Trials Using Holdout Fitness [RESOLVED]
* **Location:** `pumpfun_trading/engines/optimizer.py` (`OptimizationTrial.composite_score` ~L726–732; selection at ~L924, 981, 1023, 1106)
* **Description:** When `test_fitness` exists, `composite_score` is computed from the test objective minus an overfit penalty. Genetic tournament selection, elitism, and the final `best_trial` all rank by this score.
* **Impact:** The walk-forward holdout is used during selection, so the reported out-of-sample scores are optimistically biased.
* **Remedy:** Select on `train_fitness` only, and use test metrics only for reporting.

### BUG-61: Paper Replay Ignores Most Parameters the Optimizer Searches [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (~L40–54, ~L478–561), `pumpfun_trading/engines/optimizer.py` (~L352–509, ~L802–828)
* **Description:** The search space varies `buy_amount_sol`, tiered take-profits, trailing stops, drawdown caps, market-cap filters, and more. `PaperTradingEngine` only uses `take_profit` / `stop_loss` / `max_active_positions` and a few flags. It sizes positions with `buy_fraction` of cash and never runs the tiered or trailing exits.
* **Impact:** Fitness is mostly flat across these parameters, and exported "calibrated" configs don't match what was actually simulated.
* **Remedy:** Run the live `TradingStrategy` sizing and exit logic in replay, or limit the search space to fields the engine actually uses.
* **Resolution (MITIGATED):** `build_default_strategy_search_space` now searches only what replay reads (`take_profit`, `stop_loss_pct`, `max_active_positions`, momentum thresholds). Follow-up: port live sizing and tiered/trailing exits into `PaperTradingEngine`, then widen the space again.
* **Resolution (2026-10-16, Sprint 24C phases 2–4):** `PaperTradingEngine(live_fidelity=True)` spends `buy_amount_sol` per entry behind the live risk limits (`max_buy_attempts_per_mint`, exposure, position cap, concentration, reserve) and manages exits with `strategies/exits.evaluate_exit_strategy` (stop-loss, stagnant/max-hold on the replay clock, tiered partial sells, moonbag floor, trailing stop). `engines/costs.py` books the paper-mode cost model, so `pnl` is net. `pumpfun-replay --config/--preset` and every optimizer trial use it; trials start with `reserve + 2 × max exposure` of cash. The search space again includes the tier, moonbag, trailing and timeout parameters. Captures from `--record-replay` replay the bot's own fills as entries; the screener is not replayed (no enrichment data in captures).
* **Verification:** `tests/unit/engines/test_replay.py`, `test_costs.py`, `test_parity.py`, `test_optimizer.py::test_trial_fitness_responds_to_live_exit_parameters`; `tests/unit/engines/test_optimizer.py::test_build_default_strategy_search_space` updated to the widened space.

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

### BUG-90: `pumpfun-arb --monitor` / `--live` Only Evaluate Hardcoded Samples [MITIGATED]
* **Location:** `pumpfun_trading/cli/arbitrage.py` (~L49–60, ~L143–199)
* **Description:** `run_arbitrage_cli` always evaluates two hardcoded reserve tuples. It never reads a stream, wallet, or Jito connection, and `--mint` is only used as a label.
* **Impact:** The advertised monitor and live-execution modes don't work, and the output can be mistaken for real opportunities.
* **Remedy:** Connect `--monitor` to the disparity monitor and real reserve reads, and only execute bundles when `--live` is set. Otherwise label the output as a demo.
* **Resolution (MITIGATED):** `pumpfun-arb --live` exits with code 2; output, `--raw` and exports are labelled as demo data and `--monitor` warns that it is not implemented. Follow-up: wire a real disparity monitor once BUG-59's reserve reads exist.

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

---

## 7. Open Issues — Paper Pilot (2026-10-16)

### BUG-95: Screening Rejects Every Stream-Fed Token Because Enrichment Is Skipped [RESOLVED]
* **Location:** `pumpfun_trading/bot/enrichment.py` (`TokenEnricher.enrich_and_screen`), `pumpfun_trading/bot/run.py` (`screen_rejected` events)
* **Description:** Observed in the Stage 0 paper pilot: 26 of 26 tokens rejected with "Holder distribution data unavailable" and "Insufficient social links: found 0". `enrich_and_screen` only called `api.get_coin` when it received **no** stream data. The PumpPortal `newToken` payload is always passed in and carries no socials or holders, and nothing queried holders on-chain. The dashboard event only showed `reasons[0]`.
* **Impact:** With the `conservative` preset (2 social links required, risk score ≤ 30) no token could ever pass, so the bot never traded. With laxer presets the top-5, Gini and creator-holding checks never ran. Unbounded lookups (API retries took ~20 s in tests) also held the trade lock.
* **Remedy:** Always enrich, bounded by a per-lookup timeout.
* **Resolution (RESOLVED):**
  * `TokenEnricher` fetches the Pump.fun record and the mint's largest token accounts in parallel, then merges them with the stream payload (non-empty stream values win).
  * If there are still no socials, it reads them from the token's metadata `uri` (`PumpFunApiClient.fetch_token_metadata`, single attempt, outside the API circuit breaker).
  * Holders come from `PumpFunExecutionClient.get_token_largest_accounts`. The curve's associated token account is relabelled with the curve PDA so the top-5 and Gini checks exclude it. Creator holding falls back to the stream's `initialBuy`.
  * Every lookup is capped at 2.5 s (`lookup_timeout_seconds`); failures fall back to the missing-data penalties (BUG-57).
  * Live check: `GET /coins/{mint}` answers 404 for many mints and the client retried it three times (~3.5 s of backoff) before its `coins-v2` fallback, so the lookup always exceeded its budget. `PumpFunApiClient.request` no longer retries non-transient 4xx responses (only 408/425/429 and 5xx) and they don't count towards the circuit breaker. Screening now takes about 1 s per token.
  * Live check: `ipfs.io` and `dweb.link` now return HTTP 429 ("service worker gateway only"). Metadata URIs on public gateways are read through `pump.mypinata.cloud` (`resolve_metadata_uri`).
  * `screen_rejected` events list all reasons.
  * Tests: `tests/unit/bot/test_enrichment.py`, `tests/unit/api/test_client.py`, `tests/unit/sdk/test_execution.py`. `tests/integration/test_geyser_bot.py` no longer depends on the live Pump.fun API.

### BUG-96: Token-Account Rent Is Never Recovered After a Full Exit [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`build_sell_tx`, `sell`), `pumpfun_trading/execution/executor.py` (`execute_sell`), `pumpfun_trading/bot/run.py` (`_sell_token_locked`)
* **Description:** Found while planning Sprint 24B from the Stage 0 paper run. Every buy of a new token creates the wallet's associated token account (idempotent create, BUG-54), which locks the rent-exempt minimum (2,039,280 lamports for a 165-byte SPL account when the bug was found; mainnet rent has since been lowered to 1,513,840 lamports for the 170-byte Token-2022 accounts Pump.fun uses, about 0.0015 SOL). The sell path never closed that account: `close_account` was only used for the temporary WSOL account in Raydium swaps. Each closed position therefore left an empty token account holding its rent.
* **Impact:** At canary size (0.01 SOL buys) the stranded rent is about 15–20% of every position, and it was invisible because trade records were gross (no fee, tip or rent fields). Over the 100+ trades of a canary that is 0.2+ SOL locked in empty accounts, enough on its own to turn a small gross profit into a net loss.
* **Remedy:** Close the token account in the same transaction as the final sell, only when the sell empties it.
* **Resolution (RESOLVED):**
  * `build_sell_tx(..., close_token_account=True)` appends an SPL `CloseAccount` (rent to the wallet, owner the wallet) after the sell and before the Jito tip, using the mint's real token program (SPL Token or Token-2022).
  * `OrderExecutor.execute_sell(..., close_token_account=True)` only closes when the pre-trade balance read equals the amount sold, because closing a non-empty account fails the whole transaction. If a closing sell fails or is not confirmed, the mint is flagged and the retry sells without the close.
  * `TradingBot._sell_token_locked` requests the close on every full exit; partial exits never close. `close_token_account_on_full_exit` (default `true`) turns it off.
  * Rent is recorded per trade (`rent_sol`: positive when paid on a buy, negative when refunded on a close), read from the transaction meta in live mode and modelled in paper mode (FEAT-49).
  * Not covered: dust left after a full sell (balance ≤ `min_sell_balance`) and Raydium exits still leave the account open; a burn-and-close sweep is a follow-up.
  * Tests: `tests/unit/sdk/test_execution.py`, `tests/unit/execution/test_executor.py`, `tests/unit/bot/test_run.py`. Mainnet check (read-only, 2026-10-16): `parse_transaction_costs` run on three recent third-party Pump.fun sells that close the token account reads the refund as negative rent (−1,488,440 / −1,513,840 lamports, matching `getMinimumBalanceForRentExemption` for 165/170 bytes) and splits fee and priority fee correctly. The bot's own sells still need checking on the first canary trades with `pumpfun-audit reconcile`.
  * The modelled paper rent (`sdk/costs.TOKEN_ACCOUNT_RENT_LAMPORTS`) was updated from 2,039,280 to 1,513,840 lamports after that check.

## 8. Sprint 24B Test Pass Findings (2026-10-16, resolved)

Found while writing behaviour tests to bring coverage back to 95%. None is on the canary's money path with the canary config (arbitrage is off, the stream URL comes from the config). All five were fixed in Sprint 24B on `sprint-24b-net-pnl`.

### BUG-97: Rotation Can Store Plain Text Under a `.gz` Name [RESOLVED]
* **Location:** `pumpfun_trading/ops/retention.py` (`RotatedFileSink.rotate_now`)
* **Description:** With compression on, `X.1` is gzipped by a background thread. If the next rotation runs before that finishes (or the gzip failed), the shift loop moves `X.1` to `_get_rotated_filename(2)`, which is `X.2.gz`. Reproduced in a test: `b.log.2.gz` contained `pending-raw`. The compression thread can also still be reading `X.1` while it is shifted or deleted.
* **Impact:** Corrupt-looking archives; `pumpfun-events` / `zcat` fail on them. No trading impact.
* **Remedy:** Shift by actual on-disk name (keep `.N` vs `.N.gz` as found) and serialise compression with rotation (a lock, or compress synchronously).
* **Resolution (2026-10-16):** `rotate_now` shifts each backup by its actual name, so an uncompressed `X.1` becomes `X.2` and `X.N.gz` becomes `X.(N+1).gz`; both overflow forms are pruned. The background compression thread is tracked and joined (up to 60 s, with a warning) before the next shift, and a failed gzip is logged and leaves the plain archive in place.
* **Verification:** `tests/unit/ops/test_retention.py` (`…uncompressed_backup_keeps_plain_name`, `…waits_for_previous_compression`, `…still_running_after_timeout_warns`, `test_compress_quietly_…`).

### BUG-98: Unknown Diagnostic Category Raises From `emit` [RESOLVED]
* **Location:** `pumpfun_trading/ops/events.py` (`DiagnosticEventLogger.emit`)
* **Description:** `enabled_categories=["foo"]` with `emit(category="foo", ...)` raises `ValueError` from `EventCategory("foo")`, although `emit` is documented as never raising on the hot path. `DiagnosticEvent.__post_init__` already falls back to a default category.
* **Remedy:** Use the same fallback in `emit` (or validate `enabled_categories` at construction).
* **Resolution (2026-10-16):** `emit` resolves the category and severity with the same fallback as `DiagnosticEvent` (unknown → `LIFECYCLE` / `INFO`) before the category filter.
* **Verification:** `tests/unit/ops/test_events.py` (`test_emit_unknown_enabled_category_falls_back_instead_of_raising`, `test_emit_unknown_category_respects_lifecycle_filter`).

### BUG-99: Arbitrage Trades Are Booked Gross [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_evaluate_and_execute_arbitrage`)
* **Description:** A landed arbitrage bundle is recorded with `_record_trade(action="ARBITRAGE", ...)` without `costs`, and its profit goes to `DailyEquityTracker` without `costs_sol`, so network fees and the Jito tip are not deducted (FEAT-49 rule: never report or gate on gross PnL).
* **Impact:** None while arbitrage stays off (`RELEASE-GATE.md` §3.5, BUG-37/59/90). Must be fixed before arbitrage is enabled.
* **Remedy:** Read the bundle transactions' costs with `get_transaction_costs` (or model them in dry-run) and pass them through `build_pnl_fields`.
* **Resolution (2026-10-16):** `TradingBot._arbitrage_costs` reads the landed bundle's fee, priority fee, tip and rent with `get_transaction_costs` (8 s cap); in dry-run, or if the lookup fails, it books the opportunity's modelled gas and tip. The record carries `signature` and the cost fields, `build_pnl_fields` treats `ARBITRAGE` as a round trip (gross = output − input, cash flow = gross − costs), and `_book_trade_costs` feeds the net result to the daily breaker. Dry-run wallets are credited gross and charged the costs.
* **Verification:** `tests/unit/bot/test_run.py` (`test_arbitrage_whale_backrun_landed_books_net_profit_in_dry_run`, `test_arbitrage_landed_live_books_transaction_costs`), `tests/unit/bot/test_pnl.py` (`test_build_pnl_fields_arbitrage_is_a_net_round_trip`). Arbitrage stays off for the canary (BUG-37/59/90).

### BUG-100: Explicit `stream_url` Argument Is Overridden [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`TradingBot.__init__`, stream URL resolution)
* **Description:** `TradingBotConfig.stream_url` defaults to `wss://pumpportal.fun/api/data`, which is not the "default" sentinel, so the config value wins over the constructor's `stream_url=`; with the sentinel, `PUMPFUN_STREAM_URL` / `PUMPFUN_WS_URL` also beat the explicit argument.
* **Impact:** Low: `pumpbot` passes the URL through the config. Surprising for library callers and tests.
* **Remedy:** Precedence explicit argument → env → config → default; a test pins the current order and must be updated with the fix.
* **Resolution (2026-10-16):** precedence is now explicit argument → config URL → `PUMPFUN_STREAM_URL` / `PUMPFUN_WS_URL` → default. Config-over-env was kept on purpose: `pumpbot` never passes the argument, so a running pilot resolves the same URL as before.
* **Verification:** `tests/unit/bot/test_run.py` (`test_init_stream_url_resolution_prefers_env_over_default`, explicit-argument case).

### BUG-101: Builders Quote Against Placeholder Reserves on a Drained Curve [RESOLVED]
* **Location:** `pumpfun_trading/sdk/execution.py` (`build_buy_tx`, `build_sell_tx`)
* **Description:** When the curve account reports zero virtual reserves (completed or graduated curve), both builders fall back to the initial-curve constants (30 SOL / 1.073e15 tokens) to compute the minimum output, against the Learnings Log rule to quote slippage only from live reserves.
* **Impact:** A sell on a drained curve can carry a wrong `min_sol_output`; normally the program rejects trades on a completed curve, so the risk is a misleading quote rather than a loss.
* **Remedy:** Raise `CurveStateUnavailableError` on zero reserves and let the graduation / Raydium path handle the exit; tests currently pin the fallback.
* **Resolution (2026-10-16):** `PumpFunExecutionClient._live_curve_reserves` raises `CurveStateUnavailableError` when the curve reports no virtual reserves, so `build_buy_tx` / `build_sell_tx` never quote against the 30 SOL / 1.073e15 constants. Callers that pass their own `token_amount` / `min_sol_output` (quoted from stream reserves) are unaffected; a failed sell goes to the exit retry queue as before.
* **Verification:** `tests/unit/sdk/test_execution.py` (`test_build_tx_zero_reserves_refuses_to_quote`, `test_build_tx_zero_reserves_with_explicit_limits_still_builds`).

---

## 9. Stage 0 on v0.2.0 (2026-10-16)

### BUG-102: RPC API Key Written in Plain Text to `bot_status.json` [RESOLVED]
* **Location:** `pumpfun_trading/infra/rpc_pool.py` (`RpcEndpoint.to_dict` → `"url"`, `RpcPoolConfig.to_dict` → `"endpoints"`), `pumpfun_trading/bot/run.py` (`get_status_snapshot` → `rpc_pool_telemetry`, ~L1557)
* **Description:** Found while diagnosing the Stage 0 restart on v0.2.0 (PumpPortal HTTP 502 outage). `data/bot_status.json` → `rpc_pool_telemetry.endpoints[].url` holds the full Helius URL including `?api-key=…`. `RpcEndpoint.to_dict` serialises `self.url` unmasked, and the snapshot copies it verbatim. The same pattern can affect any other URL that carries a credential (`stream_url` in `TradingBotConfig.to_dict`, the Geyser endpoint in log/event messages, `aiohttp` error strings that include `url=`).
* **Impact:** Anyone who sees the status file, a screenshot of the dashboard/status, a shared log or incident bundle, or (later) a Web UI view built from the snapshot gets the RPC key and can spend the operator's RPC quota or get the account rate-limited. No direct loss of funds (the wallet key is not exposed), but it breaks the key-handling rules for the hosted Web UI (`AGENTS.md` Security & Key Management) and must be fixed before any status data leaves the operator's machine.
* **Workaround until fixed:** don't share `bot_status.json`, `bot.log` or incident bundles unredacted; rotate the RPC key if they were already shared.
* **Remedy:**
  * Add a single `redact_url()` helper (e.g. `ops/redact.py`) that keeps scheme, host and path but replaces credential-bearing parts: query values (`api-key`, `apikey`, `token`, `key`, `x-token`, …), `user:password@` userinfo, and long path segments that are keys (QuickNode / Alchemy style `/v2/<key>`) with `***`.
  * Use it in `RpcEndpoint.to_dict`, `RpcPoolConfig.to_dict`, `TradingBotConfig.to_dict` (`stream_url`, `api_base_url`), and in every log, event and alert message that includes an endpoint or stream URL (`bot/run.py`, `streams/geyser.py`, `infra/rpc_pool.py`). Keep the raw URL only in memory for making requests.
  * Keep the existing `label` (host) as the human-readable identifier.
  * Tests in the mirrored layout: `tests/unit/ops/test_redact.py` (table of provider URL shapes), `tests/unit/infra/test_rpc_pool.py` (telemetry has no key), and a snapshot test asserting no `api-key=` / known secret appears anywhere in `get_status_snapshot()` output.
* **Scheduled:** Sprint 24C (`docs/dev/TODO.md`). Not on the money path; needs a 24h Stage 0 re-run only if it lands together with other runtime changes.
* **Resolution (2026-10-16, Sprint 24C phase 1):** new `ops/redact.py` with `redact_url()` (masks `user:pass@`, credential query values such as `api-key`/`token`/`key`, and key-like path segments; Solana addresses in API paths are kept) and `redact_text()` (every URL inside a message). Applied at the persistence chokepoints rather than per call site:
  * `RpcEndpoint.to_dict` / `RpcPoolConfig.to_dict` (status `rpc_pool_telemetry`); endpoint labels drop userinfo and query strings.
  * `TradingBotConfig.to_dict` (`stream_url`, `api_base_url`, `rpc_endpoints`). Note: a config exported by `pumpfun-optimize` therefore carries `***` in place of a key; keep keys in the environment, not in config files.
  * `AnsiStrippingFormatter` (every line of `bot.log` and console logs, including `aiohttp` errors with `url=`).
  * `TradingBot._record_event` (dashboard events, `last_event` in the status file, alerts).
  * `DiagnosticEventLogger` JSONL writer (`events.jsonl`).
  * Raw URLs stay in memory for making requests.
* **Verification:** `tests/unit/ops/test_redact.py` (provider URL shapes, free-text messages, log formatter, events file), `tests/unit/infra/test_rpc_pool.py` (endpoint dicts, labels, telemetry), `tests/unit/bot/test_run.py::test_status_snapshot_and_events_contain_no_url_credentials`.


---

## 10. CI Interpreter Matrix (2026-10-16)

### BUG-103: `ReplayRecorder.close()` Drops the Batch Being Written at Shutdown [RESOLVED]
* **Location:** `pumpfun_trading/bot/recorder.py` (`ReplayRecorder._write_batch`, `close`)
* **Description:** Found when `unit/cli/test_record.py::test_harvester_websocket_feed_closed_runs_until_duration` failed on Python 3.11 in CI (`['WsMint1'] == ['WsMint1', 'WsMint2']`). `close()` cancels the flush worker. If the worker had already taken a batch off the queue and was awaiting `asyncio.to_thread(self._sync_append, …)`, the cancel propagated to the executor job: a job the thread pool had not started yet was cancelled and never ran, and a running job kept writing while `close()` went on to close the sink. Either way the batch was gone from the queue, so the final `flush()` could not recover it. Timing-dependent, so it showed up on the slower CI runner first.
* **Impact:** the last records before shutdown could be missing from `--record-replay` captures and `pumpfun-recorder` datasets (replay parity and tuning input, Sprint 24C). No effect on trading, the audit trail or the status file.
* **Resolution:** the write runs as a future awaited through `asyncio.shield`; on cancellation the worker waits for it to finish, counts it in `records_written`, then re-raises. Write errors are still logged, not raised.
* **Verification:** `tests/unit/bot/test_recorder.py` (`regression("BUG-103")`): a write still queued in a busy executor and a write already running when `close()` is called are both kept and counted; both failed before the fix on 3.14 too. Full suite on 3.12 and 3.14: 1,040 passed, coverage 96.30%.

---

## 11. Stage 0 Pilot on v0.2.0, Checkpoint 1 (2026-10-17)

Found in the first 14 h of the official Stage 0 paper pilot. Evidence and figures: [`releases/v0.2.0-stage0.md`](releases/v0.2.0-stage0.md).

### BUG-104: Phantom Paper Profit From Mismatched Entry and Exit Prices on Non-Standard Curves [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_handle_new_token_event` → `_buy_token(mint, current_market_cap)` uses the stream's `marketCapSol` or the 27.96 SOL default; `_refresh_active_positions_market_caps` and `_handle_trade_update` then price the position from `get_bonding_curve_state`), `pumpfun_trading/sdk/execution.py` (`decode_bonding_curve_data`)
* **Description:** the paper entry price and the exit price come from different sources. For most tokens they agree. For one curve variant they don't: the curve account (166 bytes, same discriminator) has extra non-zero data after byte 81, `virtual_sol_reserves` of 764–105,860 SOL while `real_sol_reserves` is 0 and `real_token_reserves` is still 793.1M, and the account has only its creation signature (never traded). `decode_bonding_curve_data` reads that field as SOL, so the first refresh, about 1–5 s after entry, reports a 25×–3,500× market cap. Tier 1, tier 2 and the trailing stop then fire at prices nobody could sell at.
* **Impact:** Stage 0 reported +63.5 SOL net on 11.6 SOL deployed; 137 positions (12%) produced +64.5 SOL of it. Without them the run lost about 0.75 SOL. Paper results, replay parity and any tuning on this capture are invalid. On a live run, the bot would buy curves that nobody trades, and its exit maths would misfire on them; whether the buy instruction even succeeds on this variant is unverified (one such curve shows failed transactions with `Custom: 6000`).
* **Remedy:**
  * Price paper fills from the same source as exits: read the curve before the paper buy and fill against its reserves.
  * Reject curves that fail sanity checks before screening: `virtual_sol_reserves` ≠ initial virtual SOL + `real_sol_reserves` (within a tolerance), unknown data after the documented layout, or a constant-product price inconsistent with the stream's.
  * Find out what the variant is (layout of bytes 81+, quote asset) before trading it; until then skip it.
  * Tests in `tests/unit/sdk/test_execution.py` and `tests/unit/bot/test_run.py` with the four recorded curve accounts as fixtures (`tests/support/payloads.py`).
* **Scheduled:** before the next Stage 0 (Sprint 24A, `docs/dev/TODO.md`). Money path: needs a fresh Stage 0.
* **Resolution:** new `sdk/curve.py::curve_reserve_anomaly`: on an active (not `complete`) curve, `virtual_sol_reserves − real_sol_reserves` must be the 30 SOL initial virtual reserve within 1%. Every mainnet sample fits (standard curves: exactly 30.000000 SOL); the variant gives 764–105,860 SOL. `get_bonding_curve_state` and `build_buy_tx` raise `NonStandardCurveError` (a `CurveStateUnavailableError`) on a failing curve. `OrderExecutor.execute_buy` refuses the buy in both live and paper mode (`non_standard_curve: …`, counted as a buy attempt); `_refresh_active_positions_market_caps` and `_handle_trade_update` already fall back to the stored price when the curve read raises; sells still go through without a curve quote. Paper buys record the market cap of the curve read before the fill (`ExecutionResult.metadata["entry_market_cap_sol"]`) instead of the stream's `marketCapSol`. The variant itself (bytes 81+, quote asset) is still unidentified; it is skipped, not traded.
* **Verification:** `tests/unit/sdk/test_curve.py` and `tests/unit/sdk/test_execution.py` (the recorded mainnet reserves in `tests/support/payloads.py`), `tests/unit/execution/test_executor.py`, `tests/unit/bot/test_run.py` (`regression("BUG-104")`): non-standard curves are reported and refused, standard ones decode to 27.96 SOL, a paper entry takes the curve price over a 55 SOL stream price, and a refresh on a non-standard curve keeps the stored price.

### BUG-105: Per-Sell Win Rate Counts the Rent Refund as Profit [RESOLVED]
* **Location:** `pumpfun_trading/cli/audit.py` / `pumpfun_trading/bot/pnl.py` (`pnl` summary), `bot_status.json` `pnl_totals.win_rate` / `expectancy_sol`, `engines/parity.py` per-mint net
* **Description:** a buy books its rent (0.0015 SOL) and tip as costs on the buy row; the closing sell books the rent refund as a negative cost. Win rate and expectancy are computed per sell, so a flat exit nets +0.00096 SOL and counts as a win. The total net PnL is right; the per-trade statistics are not.
* **Impact:** Stage 0 reported a 97% win rate; per position it was 29% (19% without BUG-104 artefacts). Anyone judging the strategy from the dashboard or `pnl` summary is misled.
* **Remedy:** compute win rate, expectancy and per-reason net per **position** (buy plus all its sells, keyed by `position_id`); keep per-sell rows for detail only. Tests in `tests/unit/bot/test_pnl.py` and `tests/unit/cli/test_audit.py`.
* **Resolution:** `PnlTotals` tracks the net booked by each open position (`open_position_net`, persisted in `bot_status.json`) and counts a position when its full exit (`sell`, not `partial_sell`) or arbitrage round trip lands: `positions_closed`, `winning_positions`, `closed_net_pnl_sol`. `win_rate` and `expectancy_sol` are per closed position; `sell_win_rate` keeps the old figure for detail. In `summarize_pnl` groups each position counts once: under its first exit reason (`reason`), closing day (`day`) or its mint/strategy. `pumpfun-audit pnl` labels the rows per position and adds a `Positions` column. Total net PnL is unchanged.
* **Verification:** `tests/unit/bot/test_pnl.py` and `tests/unit/cli/test_audit.py` (`regression("BUG-105")`): a flat exit with a rent refund is a winning sell but a losing position; a tiered exit counts one position under `take_profit_tier_1`; an open position survives a status-file restart.

### BUG-106: Concurrent Positions Produce Invalid Lifecycle Transitions [RESOLVED]
* **Location:** `pumpfun_trading/bot/lifecycle.py`, `pumpfun_trading/bot/run.py` (`_buy_token` transition to `BUYING`)
* **Description:** the bot has one global lifecycle state. With a position open the state is `HOLDING`, and `HOLDING → BUYING` is not an allowed transition, so every further buy logs a warning and the state shown is wrong while the buy runs.
* **Impact:** 276 warnings in 14 h; the dashboard/status state is misleading during buys. No trading effect seen.
* **Remedy:** allow `HOLDING → BUYING` (and back), or track lifecycle per position and derive the bot state; fold into the Sprint 29 lifecycle work if not fixed earlier. Test in `tests/unit/bot/test_lifecycle.py`.
* **Resolution:** `HOLDING → BUYING` is a valid transition, and `bot/lifecycle.py::settled_state` turns a `BUYING`/`SELLING` → `MONITORING` transition into `HOLDING` while any position is open, so a failed second buy or a full exit of one of two positions no longer shows `monitoring`. Per-position lifecycle remains Sprint 29 work. The golden replay `position_cap_and_unheld_trades` now ends in `holding` (one position still open), the only golden change.
* **Verification:** `tests/unit/bot/test_lifecycle.py` (`regression("BUG-106")`): a second buy while holding logs no invalid transition and a failed buy settles in `HOLDING`.

### BUG-107: Holder Data Unavailable for Most Screened Tokens [RESOLVED]
* **Location:** `pumpfun_trading/bot/enrichment.py` (`getTokenLargestAccounts` lookup, 2.5 s cap), `pumpfun_trading/sdk/execution.py` (`get_token_largest_accounts`)
* **Description:** after BUG-95 the holder lookup runs, but in Stage 0 2,839 rejections and 776 of the 1,165 passes (67%) still carried `Holder distribution data unavailable`. Those passes scored exactly 30, the `max_acceptable_risk_score`, so the top-5 concentration and Gini checks never ran for two thirds of the buys.
* **Impact:** the anti-rug screen is much weaker than configured; creator-controlled supply goes unchecked.
* **Remedy:** log why the lookup fails (timeout, RPC error, empty result for a brand-new mint), retry once after a short delay for new mints, and treat "unavailable" as a reject in the canary config until the cause is fixed. Test in `tests/unit/bot/test_enrichment.py`.
* **Root cause:** the lookup succeeds at the RPC level but the answer flaps. Probing six fresh PumpPortal mints on the pilot's RPC (read-only, at 0.5/1.5/3/6 s after creation) returned e.g. 2, 0, 2, 0 and 13, 0, 0, 20 accounts for the same mint, each in ~0.1 s: the load-balanced nodes' token-account index lags. One empty answer was taken as "no holders".
* **Resolution:** `TokenEnricher._fetch_largest_holders` retries an empty or failed answer up to 4 times (0.25 s apart, each call capped at half the 2.5 s budget, the whole lookup at the budget). Outcomes are counted in `TokenEnricher.holder_lookup_stats` and written to `bot_status.json` → `holder_lookup_stats` (`ok`, `ok_after_retry`, `empty`, `error`, `timeout`) so the next pilot shows the miss rate. New config key `require_holder_data` (default `false`; set `true` in `canary.json`) makes "Holder distribution data unavailable" a hard reject instead of 30 risk points.
* **Verification:** `tests/unit/bot/test_enrichment.py` and `tests/unit/strategies/test_presets.py` (`regression("BUG-107")`): two empty answers then holders give a full distribution; bounded attempts on persistent `[]` or errors; a timeout is counted; `require_holder_data` rejects a token that otherwise scores exactly the 30-point threshold.

---

## 12. Entry Hardening Before the Next Stage 0 (2026-10-17)

Found in the v0.2.0 Stage 0 checkpoint-1 data ([`releases/v0.2.0-stage0.md`](releases/v0.2.0-stage0.md)). Fixed on `fix/stage0-entry-hardening` together with two paper-fidelity changes (latency penalty, screening data in captures) listed in `TODO.md` Sprint 24A.

### BUG-108: Bot Buys Tokens That Are Not Pump.fun Launches [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_handle_new_token_event`), `pumpfun_trading/execution/executor.py` (`execute_buy`, paper path), `pumpfun_trading/sdk/execution.py` (`get_bonding_curve_state`, `_fetch_trade_curve_state`)
* **Description:** 263 of the 1,159 Stage 0 entries had mints that don't end in `pump`, including the USDC mint (bought twice), and 39 of them produced most of the BUG-104 phantom profit. PumpPortal's new-token feed also carries other launchpads (`pool: "bonk"` etc.), and the bot trusted every create event. In paper mode a missing curve was not an error: `_fetch_curve_reserves` returned `None` and the paper fill went ahead with a simulated token amount at the stream's market cap. `get_bonding_curve_state` never checked who owns the curve account.
* **Impact:** paper results polluted by tokens the live bot could never buy on Pump.fun; live, a buy on such a mint fails and costs fees, and a funded look-alike PDA could be decoded as a curve.
* **Resolution:**
  * `bot/enrichment.py::non_pump_launch_reason` rejects a stream token before screening when PumpPortal's `pool` is set and isn't `pump`, or (config `require_pump_mint_suffix`, default `true`) the mint doesn't end in `pump`. Rejections are counted by reason in `bot_status.json` → `non_pump_rejections` and emitted as `token_rejected_not_pump_fun` events; the mint is marked seen.
  * `get_bonding_curve_state` and `_fetch_trade_curve_state` raise `NotPumpFunCurveError` (a `CurveStateUnavailableError`) when the curve PDA has no account or its `owner` isn't the Pump.fun program.
  * `OrderExecutor.execute_buy` refuses the buy on that error in live and paper mode (`not_pump_fun: …`).
* **Not covered:** a transient RPC error on the curve read still lets a paper buy fill at the stream price (live would fail at build time). The suffix filter also drops genuine Pump.fun tokens created without a vanity mint; set `require_pump_mint_suffix: false` if that matters.
* **Verification:** `tests/unit/bot/test_enrichment.py`, `tests/unit/sdk/test_execution.py`, `tests/unit/execution/test_executor.py`, `tests/unit/bot/test_run.py`, `tests/unit/strategies/test_presets.py` (`regression("BUG-108")`).

### BUG-109: An Exited Mint Is Bought Again Hours Later [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_should_buy`, `_buy_token`, `_buy_raydium_token`)
* **Description:** a successful buy resets `_buy_attempts[mint]` to 0 and the only other guard, `_seen_mints`, expires after `recent_token_ttl_seconds`. Once it expired a token the bot had already exited could be bought again; Stage 0 bought two mints twice, about 6 h apart.
* **Impact:** repeat entries into tokens that already failed the exit rules, and doubled exposure to one creator's token.
* **Resolution:** every filled buy adds the mint to `_traded_mints` (wall-clock time, oldest first, capped at `TRADED_MINTS_LIMIT` = 10,000), saved in `bot_status.json` → `traded_mints` and restored on start; older snapshots seed it from the trade ledger and open positions. `_should_buy` rejects a traded mint that has no open position, so adding to an open position (`max_positions_per_mint` > 1) still works. New config key `allow_mint_reentry` (default `false`) turns the guard off.
* **Verification:** `tests/unit/bot/test_run.py` (`regression("BUG-109")`): a closed mint is refused after the seen-mints cache is cleared, a paper buy marks the mint, the set survives a restart, old snapshots seed it, the cap drops the oldest, and `allow_mint_reentry` allows it.

## 13. Sprint 24D: Unattended Operation (2026-10-17)

Found while wiring the daily summary and degradation alerts. Fixed on `sprint-24d-income-ops`.

### BUG-110: Alerts Block the Trading Event Loop [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_send_alert`, called from `_record_event`), `pumpfun_trading/bot/alerts.py` (`AlertDispatcher.send_alert`)
* **Description:** `_send_alert` called the synchronous `AlertDispatcher.send_alert`, which does a `urllib.request.urlopen` with a 10 s timeout. `_record_event` alerts by default, including on every buy (`bought momentum …`), circuit-breaker change and state change, so each alert stopped the asyncio loop until the webhook answered. No alert provider was configured in Stage 0, so it never showed; it would have from the first run with Slack set up.
* **Impact:** with alerts on, every alert froze stream ingestion, exit evaluation and the exit retry queue for the webhook's round trip (100 ms to 10 s on a slow or unreachable webhook). That breaks the Local Norm on never blocking the streaming loop and delays exits on the money path.
* **Resolution:** inside a running loop `_send_alert` schedules `AlertDispatcher.send_alert_async` (the webhook call runs in a worker thread) as a tracked task and returns at once; outside a loop it still sends synchronously. `start()` waits up to 5 s (`_flush_alerts`) for alerts in flight after the final `bot stopped` alert, so the last alerts are not cancelled by `asyncio.run`.
* **Verification:** `tests/unit/bot/test_run.py` (`regression("BUG-110")`): with a webhook that blocks until released, `_record_event` returns while the delivery is still pending, and `_flush_alerts` completes it once released.

## 14. Stage 0 Pilot on v0.2.1 (2026-10-17)

Found in the first minutes of the v0.2.1 Stage 0 run ([`releases/v0.2.1-stage0.md`](releases/v0.2.1-stage0.md)). Left open during the run, because a fix would restart the 72 h clock.

### BUG-111: A Sell During an In-Flight Buy Breaks the Lifecycle State [RESOLVED]
* **Location:** `pumpfun_trading/bot/lifecycle.py` (`VALID_STATE_TRANSITIONS`, `settled_state`), `pumpfun_trading/bot/run.py` (sell and buy state transitions)
* **Description:** the bot has one lifecycle state but runs a buy and an exit of another position at the same time. With `paper_entry_delay_seconds` 1.5, a buy stays in `BUYING` for about 1.6 s, and twice in the first 7 minutes a stagnant exit of the open position started inside that window. `BUYING → SELLING` isn't a valid transition, so it was rejected with `Ignored invalid state transition from TradingBotState.BUYING to TradingBotState.SELLING`. The sell then completed from `BUYING` and settled in `MONITORING`, because at that moment no position was open (the in-flight buy isn't recorded yet); the buy then moved `MONITORING → HOLDING`. BUG-106 fixed the `HOLDING → BUYING` half of the same problem.
* **Impact:** low. Both positions were tracked, sold and booked correctly. For about a second the dashboard state, `bot_status.json` `state` and the audit trail's state transitions are wrong, and the warning adds log noise. A live buy waits for confirmation, so the overlap will happen there too.
* **Workaround:** none needed; ignore the warning when it sits between a `buying …` and a `buy_confirmed …` record.
* **Fix:** allow `BUYING → SELLING` and `SELLING → BUYING`, and make `settled_state` count operations in flight (pending buys as well as open positions), so a finishing sell settles in `BUYING` while a buy is still running. Longer term, Sprint 29's typed state model should report per-operation states instead of one global state.
* **Resolution:** `BUYING ↔ SELLING` are valid transitions. `TradingBot` counts buys and sells in flight (`_inflight_operations`); a finishing operation doesn't settle the state to `HOLDING`/`MONITORING` while another is still running, so the last one to finish settles it.
* **Verification:** `tests/unit/bot/test_lifecycle.py::test_buy_and_sell_may_overlap` and `tests/unit/bot/test_run.py::test_overlapping_buy_and_sell_keep_lifecycle_valid` (buy first and sell first; no invalid-transition log, ends in `HOLDING`), tagged `regression("BUG-111")`.

## 15. Stage 0 Close-out on v0.2.1 (2026-10-17)

Found when the v0.2.1 Stage 0 run was closed after its circuit breaker tripped at T + 60 min ([`releases/v0.2.1-stage0.md`](releases/v0.2.1-stage0.md#close-out--2026-10-17-1314-t--1-h-33-min)).

### BUG-112: Token-Trade Subscription Silently Refused [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_subscribe_to_token_trades`, `_handle_message`, `_run_health_loop`), `pumpfun_trading/bot/event_router.py`
* **Description:** after a buy the bot sends `subscribeTokenTrade` for the mint. PumpPortal only serves that method to connections opened with an API key whose linked wallet holds at least 0.02 SOL (metered at 0.01 SOL per 10,000 messages); otherwise it replies `{"message": "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only available when connecting with an API key funded with at least 0.02 SOL."}`. That reply has no `mint`, so `_handle_trade_update` returns and nothing is logged. Checked after the run: 3 subscriptions, 0 trade messages, 3 refusals.
* **Impact:** high. Exits run only on the curve read every 5 s in the health loop, so the 10% stop-loss filled at −12.5% to −14.7% gross; the order-flow and momentum engines receive no trades; replay captures contain no market trades for held mints, so replay cannot evaluate exits and `--compare-audit` compares nothing. The v0.2.0 run had the same gap.
* **Workaround:** add a funded PumpPortal API key to `PUMPFUN_STREAM_URL` (`wss://pumpportal.fun/api/data?api-key=…`; `ops/redact.py` masks it).
* **Fix:** log and count PumpPortal `message` replies; mark the stream degraded and alert when a trade subscription is refused; poll held curves every `position_refresh_seconds` (default 1 s) in their own task instead of the 5 s health loop; document the API key in `ENVIRONMENTAL-VARIABLES.md`.
* **Resolution:** mint-less PumpPortal `message` replies are logged (first occurrence at INFO, repeats at DEBUG, redacted) and counted. A `subscribeTokenTrade` refusal logs an ERROR, sends one alert, sets `trade_feed_available` false (status file, dashboard `Trade feed: REFUSED`, a `trade_feed` degradation condition) and, with the new `require_trade_feed` (default `true`), blocks new buys; a new connection clears it. Held positions are re-priced from the curve every `position_refresh_seconds` (new, default 1 s) in their own task. The API key is documented under `PUMPFUN_STREAM_URL` in `ENVIRONMENTAL-VARIABLES.md`. The refusal is only seen after the first trade subscription, so the first position after a start can still be opened before buys are blocked; it is then watched by the 1 s curve poll.
* **Verification:** `tests/unit/bot/test_run.py` (`regression("BUG-112")`): refusal logged, alerted once and buys blocked; ordinary server messages don't block; the refresh loop re-prices held positions at the interval; interval parsing; `tests/unit/ui/test_dashboard.py` shows `Trade feed REFUSED`.

### BUG-113: Creator Resolved To The System Program [RESOLVED]
* **Location:** `pumpfun_trading/bot/enrichment.py` (`TokenEnricher.enrich_and_screen`, creator lookup)
* **Description:** the creator is read as `creator or user or creatorAddress or dev_wallet or traderPublicKey` from the merged record, and the API record's `creator` comes first. For some new mints the API returns `11111111111111111111111111111111`, which is truthy, so the stream's real `traderPublicKey` is never used and the creator history lookup asks about the system program. 34 of 333 screened tokens had this creator; 4 of them passed.
* **Impact:** medium. The serial-launcher (the second most common reject) and rug-history checks are skipped for about 10% of tokens.
* **Fix:** ignore the system program and empty values, prefer the stream's `traderPublicKey`, and add a `creator_unknown` penalty (or reject) when no creator can be resolved.
* **Resolution:** new `resolve_creator()` in `bot/enrichment.py` prefers the create event's `creator` / `traderPublicKey` (only for `txType: create`; on copy-trade buys the signer is the trader), then the API record, and ignores the system program and empty values. With no valid creator, the screen adds the existing "Dev wallet data unavailable" penalty (+30) instead of passing.
* **Verification:** `tests/unit/bot/test_enrichment.py` (`regression("BUG-113")`): the system-program creator falls back to `traderPublicKey`; a buy event's signer isn't taken as the creator; no creator adds the penalty.

### BUG-114: Breaker Trip Counter And Lockout Field Misreport [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_check_and_enforce_circuit_breaker`, status snapshot)
* **Description:** `_record_metric("circuit_breaker_trips")` runs on every 5 s health-loop pass while the breaker is engaged, so one trip showed as 394. `circuit_breaker_lockout_until` is filled from `locked_at_timestamp`, the time the lock began.
* **Impact:** low; telemetry and the dashboard only. A daily summary or Web UI view would report hundreds of trips.
* **Fix:** count a trip only on the transition into the locked state; report the real unlock time (the next 00:00 UTC reset) as `circuit_breaker_lockout_until` and keep `locked_at` separately.
* **Resolution:** a trip is counted once per lock (by `locked_at_timestamp`; a lock restored from the status file isn't counted again). The status snapshot has `circuit_breaker_locked_at` and a real `circuit_breaker_lockout_until` from `DailyEquityTracker.lockout_until()`: the next 00:00 UTC, or the end of `emergency_hard_lock_hours` if sooner. Old snapshots that only have the lockout field are read as the lock time.
* **Verification:** `tests/unit/bot/test_run.py` (`regression("BUG-114")`, repeated checks while locked record one trip, restore doesn't recount) and `tests/unit/bot/test_risk.py::test_lockout_until_reports_release_time`.

### BUG-115: Per-Reason PnL Shows Profitable Exits For Losing Positions [RESOLVED]
* **Location:** `pumpfun_trading/bot/pnl.py` (grouping), `pumpfun_trading/cli/audit.py` (`pnl --group-by reason`)
* **Description:** the buy record carries the position's rent, tip and fee, and the sell carries the rent refund. Grouping by reason puts each buy under an `entry` row, so in the v0.2.1 run every exit reason showed a positive net (stagnant +0.023 SOL) while the positions lost 0.023 SOL in total.
* **Impact:** low; reporting only (totals and per-position win rate are correct). It invites tuning in the wrong direction.
* **Fix:** attribute the buy leg to the position's first exit reason, so each row's net is the net of its positions; drop the `entry` row for closed positions.
* **Resolution:** with `--group-by reason`, a position's buy legs are booked under the reason of its first exit, so each row's net is the net of the positions it closed; buys of positions still open stay under their entry reason. Other groupings are unchanged.
* **Verification:** `tests/unit/bot/test_pnl.py::test_summarize_pnl_reason_groups_sum_to_closed_net` (`regression("BUG-115")`): per-reason nets sum to the closed net, losing stagnant exits show a loss; `tests/unit/cli/test_audit.py` updated for the new rows.

## 16. Trade Feed and Mayhem Mode (2026-10-17)

Found while preparing the 24 h capture run on v0.2.2, after a funded PumpPortal API key was added.

### BUG-116: Trade-Feed Refusal Cleared By Any Reconnect [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_run_websocket_stream`, `_handle_server_message`, `_subscribe_to_token_trades`)
* **Description:** the BUG-112 fix reset `_trade_feed_refused_at` on every new WebSocket connection, on the assumption that a reconnect might carry a new key. The stream URL is fixed for the process, so a reconnect never brings a new key. PumpPortal meters the key's linked wallet (0.01 SOL per 10,000 messages) and refuses `subscribeTokenTrade` once it holds less than 0.02 SOL; after the first reconnect the bot would buy again and hold that position without trade data. Failed subscription sends were also swallowed without a log line.
* **Impact:** high once the key runs dry mid-run: the same blind exits as BUG-112 (stop-loss filled 2.5–4.7 points late in the v0.2.1 run), and the alert only said an API key was needed, not that its funds had run out.
* **Resolution:** new `bot/trade_feed.py::TradeFeedBreaker`. The first refusal opens it (one alert, counted in `trips`); new buys stay blocked while it is open (`require_trade_feed`). It closes only on proof of delivery: PumpPortal's "Successfully subscribed to keys." reply or a buy/sell message for a subscribed mint, with a recovery alert. A reconnect leaves it open and schedules a probe; while open the health loop sends a probe `subscribeTokenTrade` every `trade_feed_probe_seconds` (default 300 s) on a held mint, or on the latest new mint (unsubscribed again once answered), so a top-up is noticed without a restart. The alert says the key's wallet has probably run out of funds when the key had worked earlier in the run. Send failures are logged and counted. State is in `bot_status.json` → `trade_feed_breaker`.
* **Not covered:** the first position after a start still opens before any subscription has been confirmed.
* **Verification:** `tests/unit/bot/test_trade_feed.py`, `tests/unit/bot/test_run.py` (`regression("BUG-116")`): the breaker survives a reconnect, blocks buys, closes on trade data or a confirmed probe, unsubscribes a probe mint but not a held one, and alerts once per trip.

## 17. Stream URL Precedence (2026-10-17)

Found in the first minute of the v0.2.2 24 h capture run: the trade-feed breaker opened although the PumpPortal key's wallet held 0.03 SOL.

### BUG-117: Preset Stream URL Hides The API Key In `PUMPFUN_STREAM_URL` [RESOLVED]
* **Location:** `pumpfun_trading/strategies/presets.py` (`resolve_strategy_config` defaults `stream_url` to `wss://pumpportal.fun/api/data`), `pumpfun_trading/bot/run.py` (`TradingBot.__init__` stream URL precedence)
* **Description:** any config with `strategy_preset` and no `stream_url` (both `canary.json` and `capture.json`) came back with the public PumpPortal URL. The BUG-100 order (argument > config > env) treated that as a deliberate config URL, so `PUMPFUN_STREAM_URL` with `?api-key=…` was ignored. The bot connected without a key (`bot.log`: `Connecting to WebSocket stream at wss://pumpportal.fun/api/data`, no `?api-key=***`), PumpPortal refused the first `subscribeTokenTrade`, and the BUG-116 alert said the key was missing or out of funds. The BUG-100 note that `pumpbot` "behaves exactly as before" was wrong for preset configs.
* **Impact:** high: no trade data for held positions and buys blocked by `require_trade_feed`, with a misleading "add funds" message. The pre-run key check passed because it connected with the env URL directly, not through the bot's config.
* **Resolution:** the public PumpPortal URL and the `http://127.0.0.1:10000` sentinel are both placeholders: an env URL now beats them, and any other config URL still beats the env. `TradeFeedBreaker.stream_has_api_key` records whether the PumpPortal URL in use has an `api-key`; without one the bot logs a warning at stream start, and the breaker's alert, `likely_cause` and `bot_status.json` → `trade_feed_breaker.stream_has_api_key` say the URL carries no key instead of blaming funds.
* **Verification:** `tests/unit/bot/test_run.py` and `tests/unit/bot/test_trade_feed.py` (`regression("BUG-117")`): a preset config plus the keyed env URL connects with the key, a different config URL still wins, no env keeps the public URL and the alert names the missing key; `stream_url_has_api_key` table. Loading the runtime `capture.json` with the runtime `.envrc` now gives `wss://pumpportal.fun/api/data?api-key=***`.

## 18. Stream API Key On The Dashboard (2026-10-17)

Seen on the dashboard during the v0.2.3 capture run, right after the BUG-117 fix started sending the key.

### BUG-118: Coin Polling Panel Shows The PumpPortal API Key [RESOLVED]
* **Location:** `pumpfun_trading/ui/dashboard.py` (`Stream URL` rows in the Coin Polling and Bot Status panels), `pumpfun_trading/bot/run.py` (`TradingBot.stream_url`), `PUMPFUN_STREAM_URL`
* **Description:** the only way to give the bot a PumpPortal key was `PUMPFUN_STREAM_URL=wss://pumpportal.fun/api/data?api-key=…`. The bot kept that URL as `stream_url` and the dashboard printed it with `bot.stream_url`, without the BUG-102 redaction that logs, status files and alerts get. Once BUG-117 made the keyed env URL win, the key was on screen in full.
* **Impact:** medium: anyone who sees the terminal, a screenshot or a screen share gets a key that spends the linked wallet's SOL (PumpPortal meters trade messages against it). No wallet key is exposed.
* **Workaround:** none needed after the fix; before it, don't share the dashboard and rotate the key if it was shown.
* **Resolution:** the key is a separate secret, `PUMPFUN_STREAM_API_KEY`. `TradingBot.stream_url` (and `config.stream_url`) is always key-free, and the key is only joined to the URL in `_stream_connect_url()` at `ws_connect` time, and only for `pumpportal.fun` hosts, so it is never sent to another provider (`bot/trade_feed.py`: `split_stream_api_key`, `stream_connect_url`). A key still embedded in `PUMPFUN_STREAM_URL` is split out and used, with a start-up warning to move it. The dashboard also passes the stream and Geyser URLs through `redact_url` as a second guard. `sanitize_env_for_logging` masks the new variable (its name contains `KEY`).
* **Verification:** `regression("BUG-118")` tests: `unit/ui/test_dashboard.py` (no key on the rendered dashboard with the new variable, with a legacy keyed URL, or with a key set straight on `stream_url`), `unit/bot/test_trade_feed.py` (`split_stream_api_key` and `stream_connect_url` tables, no key for other hosts), `unit/bot/test_run.py` (`ws_connect` gets the keyed URL while logs and the status snapshot never contain the key; a legacy keyed URL is split out with a warning).

## 19. 24 h Capture Findings (2026-10-18)

Found while analysing the v0.2.3 24 h capture run (`runtime/capture/`).

### BUG-119: Parity Check Ignores Live Buy-Side Costs [RESOLVED]
* **Location:** `pumpfun_trading/engines/parity.py` (`_collect`)
* **Description:** the live side of `compare_replay_to_audit` added up `trade_net_pnl` for sell records only. Since FEAT-49 a live buy books its own fee, Jito tip and token-account rent as a negative `net_pnl_sol` on the buy record, while replay sells already carry the buy-side costs. The live total therefore left out every buy's costs.
* **Impact:** medium: the replay-vs-live check reported live +2.06 SOL for a run that lost 0.579 SOL, flagged a 2.8 SOL "gap" and made replay look far too pessimistic. No trading decision used it.
* **Resolution:** `_collect` adds the net of every buy and sell record on both sides (replay buys book 0). Mint status, entry and exit counts are unchanged.
* **Verification:** `regression("BUG-119")` in `tests/unit/engines/test_parity.py`: live buys with and without a `net_pnl_sol` field are netted, and a replay that matches live exactly gives a zero gap. On the capture the corrected live figure for mints bought on both sides is −0.561 SOL against replay −0.757 SOL.

### BUG-120: Trade Subscriptions Outlive Their Positions [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token`, `_evaluate_and_execute_exit`, `_process_exit_retry_queue`, the copy-trade mirror exit)
* **Description:** `unsubscribeTokenTrade` was only sent `if sold and websocket`, and five of the six exit call sites (the 1 s position refresh loop, curve updates, retry queue, breaker liquidation) passed no websocket. `_unsubscribe_from_token_trades` could have fallen back to the live socket but was never called.
* **Impact:** medium: 538 of 1,676 exited mints kept streaming trades for hours (median 12 min, p90 73 min after the exit), 54% of all trade messages. PumpPortal bills the key's wallet per message, and the subscription list grew all day.
* **Resolution:** `_sell_token` unsubscribes (through the active socket) whenever the call closed a held position, so every exit path is covered; the per-call-site unsubscribes are gone so nothing is sent twice. Partial and failed sells keep the subscription.
* **Verification:** `regression("BUG-120")` in `tests/unit/bot/test_run.py`: full exit unsubscribes once, partial and failed sells don't, an unheld mint sends nothing, and an exit from the refresh-loop path (no websocket argument) still unsubscribes.

## 20. v0.3.0-rc.1 Capture Findings (2026-10-19)

Found while analysing the first 12.7 h of the v0.3.0-rc.1 capture (`runtime/capture/`, `configs/capture.json`).

### BUG-121: Replay Ignores The Paper Entry Delay And Penalty [RESOLVED]
* **Location:** `pumpfun_trading/engines/replay.py` (`PaperTradingEngine.run`, live-fidelity entries)
* **Description:** the paper executor waits `paper_entry_delay_seconds` (1.5 s in `capture.json` / `canary.json`), re-reads the curve and cuts the fill by `paper_entry_slippage_bps` (100), because a live buy lands after screening and confirmation. Replay bought at the price of the snapshot that confirmed the signal and could exit on the very next snapshot.
* **Impact:** medium: `--compare-audit` showed replay 0.016 SOL better than paper over 62 positions (allowed ±0.010), and every confirmed-lane replay result was optimistic: the v0.2.3 capture went from +0.139 to +0.062 SOL with the fix, and the 8-buyer variant that looked positive on the new capture (+0.021) is −0.003. No trading decision used replay directly, but the go/no-go does.
* **Resolution:** entries that are not mirrored from recorded fills are booked at the signal and filled at the last recorded price at signal + delay; until then the position takes no exits. A penalty keeps `1 − bps/10,000` of the tokens and raises the entry market cap to match, replacing the engine's own entry slippage; without the two settings nothing changes. Buys still landing at the end of the data fill at the last price. `entry_metrics` gain `fill_market_cap_sol` and `fill_drift_pct`.
* **Verification:** `regression("BUG-121")` tests in `tests/unit/engines/test_replay.py`: a dip during the delay does not stop out the unfilled position and the fill uses the price at signal + delay, a penalty without a delay, a fill at the end of the data, and no change without the settings. On the capture the parity gap fell from +0.023 to +0.014 SOL; the rest is curve reads that see trades the capture's trade stream does not, plus unmatched positions ([`STRATEGY-PIVOT.md` §6.3](STRATEGY-PIVOT.md#63-v030-rc1-capture-no-go-2026-10-19)).

### BUG-122: Stream Reconnects Are Not Counted [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_record_connection_loss`, the `WebSocketStreamHost` hooks `on_stream_exception` / `on_stream_ended`)
* **Description:** `_record_connection_loss` increments `connection_loss` and records an event, but only tests call it. The WebSocket loop (`streams/websocket.py`) reports errors and remote closes through the host hooks, which log and reconnect without touching the counter.
* **Impact:** low: the full 24 h rc.1 capture has 7 `Connecting to WebSocket stream` lines in `bot.log` and `connection_loss: 0` in `bot_status.json`, so the dashboard and the daily summary under-report stream health. Trading is not affected; each reconnect resubscribes as before.
* **Fix:** `on_stream_exception` and `on_stream_ended` call `_record_connection_loss` unless a shutdown was requested; `on_stream_error` does not, because an ERROR frame always ends in `on_stream_ended`, so each disconnect counts once (rc.3, with Sprint 28b).
* **Verification:** `regression("BUG-122")` tests in `tests/unit/bot/test_run.py`: `test_websocket_disconnects_count_one_connection_loss_each` drives the real `run_websocket_stream` through an ERROR frame, a remote close, a failed connect and a clean shutdown and expects exactly 3 losses (counter and recent events); `test_stream_hooks_skip_connection_loss_once_shutdown_requested` checks neither hook counts after a shutdown request.

## 21. Third-Party Code Review (2026-10-20)

Found while reviewing `pumpfun-bonkfun-bot` (Apache-2.0), `pumpfun-sniper-bot` and `PumpGrok` for ideas. Only bonkfun-bot's layouts were used as a reference; no code was copied.

### BUG-123: Positions Held Through Graduation Cannot Exit [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token_locked`, `_handle_complete_event_update`, `_refresh_active_positions_market_caps`), `pumpfun_trading/sdk/`
* **Description:** a completed bonding curve rejects every trade (BUG-44), so a held coin that graduates must be sold on the AMM it migrated to. The bot marked the mint as migrating and then waited for a Raydium AMM v4 pool (`RaydiumPoolKeys`). Pump.fun has migrated into its own **PumpSwap** AMM (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`) since 2025, so that pool never appears. On the PumpPortal WebSocket deployment it was worse: the completion event only exists on Geyser, so the bot never marked the mint at all, kept pricing it from a curve with zero reserves (falling back to the last stored market cap) and retried curve sells that fail on-chain until `max_exit_retries`, leaving the tokens in the wallet.
* **Impact:** high for the pre-graduation lane (FEAT-53), which buys at 75–88% curve progress, and possible for any momentum position that runs to ~85 SOL. Paper hides it: the paper sell "succeeds" at a stale price. No rc.1 position graduated, so no capture shows it yet.
* **Resolution:**
  - `sdk/pumpswap.py`: canonical pool PDA (`pool-authority` of the mint under the Pump.fun program, index 0, WSOL quote), pool and `global_config` decoders, the constant-product sell quote net of the LP / protocol / creator fees, market cap on the bonding-curve basis, and the PumpSwap `sell` instruction (the IDL's 21 accounts plus the cashback pair, `pool-v2` and the buyback recipient tail).
  - `sdk/pumpswap_execution.py` (`PumpFunExecutionClient` mixin): pool lookup with owner and pair checks (`PumpSwapPoolUnavailableError` while the pool is missing), `get_pumpswap_market_state`, `quote_pumpswap_sell`, `build_pumpswap_sell_tx` (WSOL ATA in, unwrap, and on a full exit the token-account close for the rent, BUG-96) and `pumpswap_sell` (Jito or RPC).
  - `OrderExecutor.execute_pumpswap_sell`: paper fills at the pool quote; live fills book proceeds from the transaction meta, else the wallet delta, else the quote.
  - `bot/run.py`: a held curve that reads `complete` in the position refresh, a Geyser complete event, or a PumpPortal `subscribeMigration` message (free, now subscribed on every connect) marks the mint migrating and sells it. A migrating mint without a Raydium pool is priced from the PumpSwap pool and sold there (`enable_pumpswap_exit`, default on); while the pool is missing the sell waits and the next refresh retries. A migrating watched mint is dropped from the watch list.
* **Verification:** `regression("BUG-123")` tests: `unit/sdk/test_pumpswap.py` pins the pool PDA, both layouts and the sell instruction to mainnet accounts of a graduated coin and to the accounts of a real PumpSwap sell (23 of 24 keys equal; the 24th is that seller's non-ATA token account); `unit/sdk/test_pumpswap_execution.py`; `unit/execution/test_executor.py` (paper, missing pool, live proceeds sources and failure paths); `unit/bot/test_run.py` (a held curve that completes exits on PumpSwap, waits for a missing pool, can be switched off, and a migration message exits a held mint and drops a watched one). `unit/bot/test_risk.py` now expects the graduation handler to call `_sell_token`. No live PumpSwap sell has been sent yet: run one at the smallest size before relying on it with real capital.

### BUG-124: Non-SOL Quote Mints Decoded As Lamports [RESOLVED]
* **Location:** `pumpfun_trading/sdk/pumpfun_execution.py` (`decode_bonding_curve_data`, `_reject_non_standard_curve`)
* **Description:** the Pump.fun `BondingCurve` account now carries `is_cashback_coin` and a `quote_mint` (bytes 82–115) after `is_mayhem_mode`, and the SOL reserve fields became quote reserves. The decoder stopped at `is_mayhem_mode`, so a curve quoted in USDC (6 decimals) would have been read as SOL lamports (9 decimals) and priced roughly 1,000× wrong. Mainnet SOL curves carry a zeroed quote mint.
* **Impact:** medium: every price, slippage bound and paper fill assumes lamports. Whether any of the 13 `non_standard` drops in the rc.1 capture were USDC curves is not known (the capture does not store the raw account).
* **Resolution:** the decoder returns `quote_mint` (`None` on accounts too short to carry it), and `_reject_non_standard_curve` raises `NonStandardCurveError` for any quote mint other than the zeroed key or WSOL, so the watch poller drops it as `non_standard` and the buy path refuses it before the reserve checks.
* **Verification:** `regression("BUG-124")` test in `unit/sdk/test_pumpfun_execution.py`: zeroed, WSOL and missing quote mints pass; a USDC quote mint is refused by the sanity check and by `get_bonding_curve_states`.

## 22. Config Keys Ignored In Config Files (2026-10-20)

Found while adding `graduation_backfill_seconds`: `TradingBotConfig.from_dict({"enable_pumpswap_exit": false})` came back with `true`.

### BUG-125: Config Resolver Drops Fields Without A Warning [RESOLVED]
* **Location:** `pumpfun_trading/strategies/presets.py` (`resolve_strategy_config`)
* **Description:** the resolver builds `TradingBotConfig(...)` by listing every field with its own `base.get(...)`, and anything not listed keeps the dataclass default. Eleven fields were missing: `enable_pumpswap_exit` (BUG-123), `replay_log_path`, `daily_summary_alert`, `daily_summary_hour_utc`, `degradation_alert_minutes` (FEAT-50) and all five `profit_sweep_*` keys (FEAT-42). `pumpbot --config` and `TradingBot(config=dict)` both go through it. Unit tests passed because they build configs with `make_config` / `dataclasses.replace`, which never touch the resolver.
* **Impact:** medium: the profit sweep could not be turned on from a config file, the daily summary hour and degradation alert delay could not be changed, and `enable_pumpswap_exit: false` would not have switched the PumpSwap exit off. No shipped or runtime config sets any of these keys, so no run so far behaved differently from its config.
* **Resolution:** the resolver reads all eleven. A guard test sets every scalar field to a non-default value through `resolve_strategy_config` and fails on any field that comes back unchanged (fields the resolver normalises on purpose are listed in the test).
* **Verification:** `regression("BUG-125")` test in `unit/strategies/test_presets.py`; it fails with 11 dropped fields on the old resolver.

## 23. Paper Exits Skip The Sell Slippage Replay Charges (2026-10-21)

Found reading out the rc.2 momentum capture: `pumpfun-replay --compare-audit` put replay 0.028 SOL below paper (tip 0, allowed ±0.002) on the same 105 positions, with 102 of them closing on the same exit.

### BUG-126: Paper Sells Take No Slippage, Replay Takes 100 bps [RESOLVED]
* **Location:** `pumpfun_trading/bot/run.py` (`_sell_token_locked` → `execution/sell_pipeline.py::estimate_sell_proceeds`), `pumpfun_trading/engines/replay.py` (`_sell_value`)
* **Description:** a paper sell is priced as the sold share of the cost basis times the market-cap move times the round-trip Pump.fun fee, with no price impact or latency. Replay prices the same sell at the recorded price less the engine's `slippage_bps` (100) and the fee. On the rc.2 capture every replayed sell came out about 1% below the paper one (e.g. 0.01636 against 0.01650 SOL on the same stop-loss). BUG-121 gave entries a shared model (`paper_entry_delay_seconds` / `paper_entry_slippage_bps`); exits never got one.
* **Impact:** medium: paper results were about 1% per exit too optimistic against a live sell, and paper and replay could not be compared. On rc.2 that is about 0.021 SOL of the 0.028 gap and turns the paper result of +0.014 SOL into roughly −0.007 SOL. With the exit haircut matched, the same-exit positions agree to −0.002 SOL (median per position +0.00001); the rest is one position where replay hit the stop and paper the trailing stop (−0.006), from prices the capture did not record.
* **Resolution:** new config key `paper_exit_slippage_bps` (default `0`, clamped to 0–5,000; `100` in the `momentum` preset, `configs/canary.json`, `configs/capture.json` and `configs/pregrad_pilot.json`). Paper sells take it off their proceeds (`TradingBot._paper_exit_factor`), and live-fidelity replay uses it instead of the engine's `slippage_bps` when it is set. Configs without the key behave as before, so old captures replay unchanged and the golden replay is unchanged.
* **Verification:** `regression("BUG-126")` tests in `unit/bot/test_run.py` (paper sell at 0 / 100 / 9,000 bps), `unit/engines/test_replay.py` (replay sell proceeds follow the key) and `unit/strategies/test_presets.py` (defaults, clamp, momentum preset).

## 24. Code Review: Risk, Execution And Maths (2026-10-22)

Found by reading the code during the rc.3 / FEAT-65 72 h run; nothing was run or reproduced, and no code was changed. Line numbers are from the working copy on 2026-10-22 and may drift. BUG-127 to BUG-130 should be fixed before any live capital.

### BUG-127: Adaptive Ratchet Never Protects Profit [OPEN]
* **Location:** `pumpfun_trading/bot/risk.py` (`DailyEquityTracker.effective_baseline_sol` ~L48–61, `evaluate_circuit_breaker` profit-run zone ~L311–324)
* **Description:** `effective_baseline_sol` (start + `profit_ratchet_ratio` × realized gain) is only written to status snapshots and the lock reason; no decision uses it. The profit-run zone halts buys when `peak_drawdown_pct` exceeds `profit_drawdown_tolerance_pct` (0.35), but `peak_drawdown_pct` is the drop as a share of **total** peak equity, not of the profit. Starting at 1.0 SOL with a peak of 1.1 SOL, the halt needs equity at 0.715 SOL, which is already below the start, so the principal zone (15%) is evaluated instead and the profit-run halt never fires.
* **Impact:** high: RISK.md §3 promises that half of the day's realized profit is ratcheted into a floor; in practice a winning day can be given back in full before any protection applies.
* **Suggested fix:** in the profit-run zone, halt new buys when current equity falls below `effective_baseline_sol`, and/or measure the retracement against `peak − start` (the profit) rather than the peak. Decide whether the ratchet uses daily or cumulative realized PnL and make RISK.md match.
* **Verification to add:** a test where equity runs 1.0 → 1.2 → 1.08 with realized +0.2 must halt buys (floor 1.1 at ratio 0.5).

### BUG-128: Daily Loss Lock Ends At UTC Midnight And Has No Cumulative Cap [OPEN]
* **Location:** `pumpfun_trading/bot/risk.py` (`initialize_or_rollover` ~L91–102, `lockout_until` ~L105–123, auto-unlock in `evaluate_circuit_breaker` ~L222–241)
* **Description:** the rollover at 00:00 UTC clears any lock and resets starting and peak equity to the current (post-loss) value; `lockout_until` returns the earlier of next midnight and the hard-lock end. A lock at 23:55 UTC therefore lifts five minutes later. The hard-lock auto-unlock also resets the baseline to post-loss equity. No limit spans days.
* **Impact:** high: RISK.md describes a 24-hour lockout. In practice the bot can lose up to `max_daily_drawdown_pct` every UTC day (or every lock period), compounding, with no overall stop.
* **Suggested fix:** make the lock last its full duration across the rollover (do not clear `circuit_breaker_engaged` in the rollover while the hard lock is running), and add a cumulative cap (for example a max loss from the all-time or session starting equity, persisted across restarts) that needs a manual reset.
* **Verification to add:** a lock at 23:55 UTC stays engaged at 00:05 UTC; two losing days in a row trip the cumulative cap.

### BUG-129: Live Entries Use The Signal Market Cap As Entry Price [OPEN]
* **Location:** `pumpfun_trading/execution/executor.py` (paper path sets `entry_market_cap_sol` ~L466–472; live path does not), `pumpfun_trading/bot/run.py` (`_buy_token` ~L1930–1956)
* **Description:** `_buy_token` overrides the stream market cap with `exec_metadata["entry_market_cap_sol"]` only when it is present, and only the paper path sets it (BUG-104 / BUG-121 fixed paper). A live buy records the market cap of the signal, before screening, confirmation and the bot's own price impact. Exits measure `performance` against that value.
* **Impact:** high once live: with an entry drift of a few percent, the stop-loss fires that much further below the real fill and take-profits fire early. Paper and replay results do not carry over to live.
* **Suggested fix:** derive the live entry market cap from the fill (swap SOL from transaction meta and tokens received, or the curve read just after confirmation), and record both values so the drift is visible.
* **Verification to add:** a live-mode executor test where the fill price differs from the signal; the position's `entry_market_cap` must follow the fill.

### BUG-130: Day Baseline Can Come From The Simulated Balance [OPEN]
* **Location:** `pumpfun_trading/bot/run.py` (`self.wallet_balance_sol = self._initial_simulated_balance()` ~L322, `_check_and_enforce_circuit_breaker` ~L1341–1357), `pumpfun_trading/bot/risk.py` (`initialize_or_rollover`)
* **Description:** the bot starts every run with the simulated balance (reserve + 10 × buy size, or `paper_starting_balance_sol`) and does not fetch the real balance before the first breaker check. If that first `get_balance_sol` raises, the exception is logged at DEBUG and `evaluate_portfolio_circuit_breaker` still runs with the simulated figure, which sets `starting_equity_sol` for the whole UTC day.
* **Impact:** high in live mode: a simulated figure above the real balance (for example 0.3 against 0.2 SOL) looks like a 33% loss on the next check and triggers `EMERGENCY_LIQUIDATE`; one below it loosens the limit all day.
* **Suggested fix:** in live mode, fetch the balance at startup and refuse to trade (and skip breaker initialisation) until a real read succeeds; never initialise the baseline from a simulated or stale value.
* **Verification to add:** a live-mode test where the first balance read fails must leave `starting_equity_sol` unset and buys blocked.

### BUG-131: Raydium Migration Buys Use A Hard-Coded Entry Market Cap [OPEN]
* **Location:** `pumpfun_trading/bot/run.py` (Raydium buy, `entry_market_cap=69.0` ~L2092)
* **Description:** every Raydium migration position records an entry market cap of 69.0 SOL, which looks like Pump.fun's "$69k" graduation market cap in USD read as SOL. Exits compute `current / entry` against it.
* **Impact:** medium: stops and take-profits on these positions are meaningless (a real post-graduation market cap of several hundred SOL reads as a multi-x gain). `enable_raydium_migration_sniping` is true in the conservative, balanced and aggressive presets and in the resolver default, false in momentum and canary. Pump.fun migrates to PumpSwap (BUG-123), so the lane may never fire.
* **Suggested fix:** take the entry market cap from the fill or pool state, or remove the Raydium sniping lane and default the flag to false.
* **Verification to add:** a Raydium buy records the market cap derived from its fill.

### BUG-132: Legacy Momentum Entry On The Geyser Path Ignores Entry Mode [OPEN]
* **Location:** `pumpfun_trading/bot/handlers/trade.py` (`handle_trade_event_update`, "Momentum Spikes Evaluation" ~L177–232)
* **Description:** the Geyser trade handler buys on `evaluate_momentum_signal` (`reason="momentum_spike"`) whenever `enable_momentum_signals` is true, without checking `entry_mode`. The momentum preset inherits `enable_momentum_signals: true` from conservative. The PumpPortal handler routes confirmed mode to `maybe_buy_confirmed_momentum`, but the Geyser one does not, and its call passes no `token_creation_timestamp`, so the age gate is skipped too.
* **Impact:** medium, latent: no `momentum_spike` buy appears in the current captures (PumpPortal stream). Switching to Geyser in confirmed mode would open positions that bypass the age window, market-cap band and the FEAT-56/57/60 flow screens.
* **Suggested fix:** in confirmed mode, route the Geyser path through `maybe_buy_confirmed_momentum` (or skip the legacy block), and pass the creation time.
* **Verification to add:** a Geyser trade event in confirmed mode never produces a `momentum_spike` buy.

### BUG-133: Velocity Z-Score Is Capped And Biased For Young Tokens [RESOLVED]
* **Location:** `pumpfun_trading/strategies/momentum.py` (`TokenOrderFlowTracker.get_velocity_z_score` ~L258–309)
* **Description:** slice 0 (the current window) is part of the baseline mean and standard deviation. With N slices the largest possible z is sqrt(N − 1): 3.0 for 30 s windows over 300 s. Slices before the token existed count as zero velocity, which inflates z for any young token with rising activity.
* **Impact:** medium, latent: the conservative preset's `momentum_min_z_score` of 3.0 passes only when the previous 270 s had no trades at all, and balanced's 2.5 is close to the cap. The momentum preset and canary set it to 0.0, so rc.3 is not affected.
* **Resolution:** `get_velocity_z_score` now computes the mean and standard deviation from the earlier slices only (1..N−1), and with `token_creation_timestamp` (now passed through by `evaluate_momentum_signal` and `OrderFlowEngine.get_velocity_z_score`) leaves out slices that start before the token existed. Fewer than `MIN_Z_SCORE_BASELINE_SLICES` (2) give 0.0. The score is no longer capped at sqrt(N − 1), and a young token's steady flow no longer reads as a spike. Behaviour change for the conservative / balanced / aggressive presets (z thresholds 3.0 / 2.5 / 2.0): they now need at least 90 s of trade history after creation before the z-score can pass; the momentum preset and canary (threshold 0) are unaffected. STRATEGY.md §8 describes the baseline.
* **Verification:** `regression("BUG-133")` tests in `unit/strategies/test_momentum.py`: a burst over an alternating 1/2-trade baseline scores the exact (10 − 13/9)/σ, above the old cap of 3; a 90 s old token with steady flow scores 0 with its creation time (1.9 without), and under two baseline slices gives 0; the signal passes the creation time through.

### BUG-134: Dynamic Slippage Volatility Term Is Dead, Impact Double Counted [OPEN]
* **Location:** `pumpfun_trading/execution/policy.py` (`record_curve_update`, `resolve_parameters`), `pumpfun_trading/execution/executor.py` (`_resolve_dynamic_slippage` ~L253–279), `pumpfun_trading/sdk/curve.py` (`estimate_dynamic_slippage` ~L421–479)
* **Description:** the per-mint volatility estimator is only fed from `_resolve_dynamic_slippage`, once per execution, so its 30 s window rarely holds two observations and `calculate_volatility` returns 0. The impact term uses `calculate_buy_price_impact` (post-trade spot change, about 2·Δx/x) rather than the execution slippage (Δx/x).
* **Impact:** medium: slippage tolerances are base + roughly twice the real impact, with no response to volatility, so entries in fast markets fail more often and calm ones are looser than needed.
* **Suggested fix:** feed the estimator from the trade stream (or drop the term), and use `calculate_buy_execution_slippage` / `calculate_sell_execution_slippage` for the impact component.
* **Verification to add:** after a burst of recorded trades the resolved slippage includes a non-zero volatility component.

### BUG-135: Optimizer Fitness Statistics [OPEN]
* **Location:** `pumpfun_trading/engines/optimizer.py` (`calculate_sharpe_ratio` / `calculate_sortino_ratio` ~L495–531, `calculate_calmar_ratio` ~L533–542, `evaluate_fitness` ~L544–600, `WalkForwardValidator.split_snapshots` ~L709–723)
* **Description:** the "Sharpe" and "Sortino" are multiplied by sqrt(n), which makes them t-statistics; scoring a 70% train split against a 30% test split shrinks the test value by about 0.65 for the same edge, which biases `overfit_delta` and `validation_score`. Returns come from records with `action == "sell"` only, so `partial_sell` exits are skipped and each sell is scored on its own (the problem BUG-105 fixed in `bot/pnl.py`). Calmar with zero drawdown returns 10× the return, which favours configs with very few trades.
* **Impact:** medium: optimizer rankings and the overfit check are distorted, and heavy-tailed results (a few runners) are scored poorly by mean/std.
* **Suggested fix:** use per-position net returns (buy plus all sells), drop the sqrt(n) scaling or compare train and test on the same scale, require a minimum trade count instead of the zero-drawdown bonus, and report a bootstrap interval alongside the score.
* **Verification to add:** identical per-trade return distributions on 70% and 30% splits give equal scores.

### BUG-136: Open Positions Marked At Spot [OPEN]
* **Location:** `pumpfun_trading/bot/position_manager.py` (`calculate_total_open_value` ~L505–527), `pumpfun_trading/bot/risk.py` (`evaluate_portfolio_circuit_breaker` fallback ~L415–439)
* **Description:** open value is cost × fraction × current/entry market cap, with no sell fee (1.25%), exit price impact or exit slippage.
* **Impact:** low: equity is slightly overstated, so drawdown checks trigger a little late.
* **Suggested fix:** value open positions at their estimated liquidation proceeds (`estimate_sell_proceeds` with the paper exit haircut).

### BUG-137: Fragile Market-Cap Units And Fallback [OPEN]
* **Location:** `pumpfun_trading/sdk/curve.py` (`calculate_market_cap_sol` ~L86–108), `pumpfun_trading/bot/run.py` (`entry_market_cap=float(market_cap_sol or 30.0)` ~L1956)
* **Description:** `calculate_market_cap_sol` treats any reserve of at least 1,000,000 as lamports, while `total_supply` defaults to raw units, so a caller passing token reserves in whole tokens would be off by 10^6. The `or 30.0` fallback is the virtual SOL reserve, not a market cap (about 27.96 SOL at launch).
* **Impact:** low: current callers pass consistent units.
* **Suggested fix:** take explicit units (lamports and raw token units only) and use the launch market cap constant for the fallback, or refuse to open a position with no market cap.

### BUG-138: Fixed Pump.fun Fee Not Checked Against The Current Schedule [OPEN]
* **Location:** `pumpfun_trading/sdk/execution_types.py` (`PUMP_DEFAULT_FEE_BPS = 125`)
* **Description:** every modelled fee (paper, replay, cost guard) uses a flat 125 bps per side. Pump.fun's fees may now vary with market cap; this has not been verified.
* **Impact:** low to medium depending on the real schedule: paper and replay costs would be off by the difference on every trade.
* **Suggested fix:** confirm the current fee from the program's global/fee config accounts or a few confirmed transactions, and read it at runtime if it varies.

### BUG-139: FEAT-65 Round-Trip Quotes Include Price Drift [OPEN]
* **Location:** `pumpfun_trading/services/slow_lane.py` (`QuoteRecorder.sample_quotes`, `quote_row`, `backfill_bars`)
* **Description:** the sell quote is requested about `DEFAULT_QUOTE_REQUEST_GAP_SECONDS` (2 s) after the buy quote, so `round_trip_cost_bps` includes the price move in between. Bars are USD prices from each token's top pool as chosen today.
* **Impact:** low: the cost estimate is unbiased but noisy (more so for BONK and WIF); SOL-denominated results need SOL's own USD bars, and the token list carries survivorship bias.
* **Suggested fix:** analyse round-trip cost as a median over many samples per token and size; convert bars to SOL terms; note the pool choice in the analysis.

### BUG-140: Possible Repeat Take-Profit After A Slow Sell (Unverified) [OPEN]
* **Location:** `pumpfun_trading/strategies/exits.py` (`PENDING_EXIT_TTL_SECONDS = 60.0`, `is_exit_pending` / `mark_exit_pending`), exit retry queue in `pumpfun_trading/bot/run.py`
* **Description:** a tier is marked pending for 60 s. A sell that runs through the Jito confirmation timeout (12 s), the RPC fallback and the retry queue's escalating attempts could take longer, after which the same tier can be emitted again while the first sell is still in flight.
* **Impact:** low if the retry queue or the trade lock already prevents it; not verified.
* **Suggested fix:** check whether an in-flight or queued sell blocks a repeat of its tier; if not, clear the pending mark only when the sell completes or is abandoned.
* **Verification to add:** a test where the first tier-1 sell takes longer than 60 s must not produce a second tier-1 sell.
