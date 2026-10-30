# Features

What trading-pump ships today (§1–§9), and what became of every feature
pumpfun-trading listed (§10). Only shipped code is listed here; unbuilt work
is in [dev/PROPOSED-FEATURES.md](dev/PROPOSED-FEATURES.md) and open items in
[dev/TODO.md](dev/TODO.md). "Shipped" means the code works and is tested, not
that a lane makes money: results are in
[dev/STRATEGY-PIVOT.md §6](dev/STRATEGY-PIVOT.md#6-results-log).

## 1. A trading-core module (`pumpfun`)

`trading_pump.module:PumpModule` implements trading-core's `TradingModule`
and is registered in the `trading_core.modules` entry-point group as
`pumpfun`, so `trading-core run --config F` with `"module": "pumpfun"` runs
it. The engine owns the loop, sizing, the risk gate, the circuit breaker,
exits, accounting, the audit trail, the status file, alerts and the
dashboard; the module owns everything that knows Solana, Pump.fun and
PumpSwap.

* **Quote currency** SOL (9 decimals), prices shown in µSOL.
* **Quotes** from the latest pool reading; re-read when older than
  `execution.quote_max_age_seconds`; stale when the read fails or the pool is
  drained. Never a placeholder price (BUG-129's lesson).
* **Exit value** is what selling the position into the pool returns after the
  swap fee, not the spot price (BUG-136).
* **Health**: every successful pool read tells the engine market data is
  flowing, and entries pause once it goes stale (`health_timeout_seconds`);
  with no working RPC there are no entries (BUG-149). The migration feed,
  the RPC and the RPC network report degraded conditions (`pumpportal feed`,
  `solana rpc`, `rpc network`) through `set_degraded`: shown on the dashboard
  with their cause and alerted after `degradation_alert_minutes`. An RPC
  error is a failed read, never "pool missing" (BUG-159).
* **RPC network check** at start: every endpoint's genesis hash is checked;
  one on devnet, testnet or an unknown network is dropped from the pool, and
  when none is on mainnet `rpc network` is reported degraded (BUG-160).
* **Status rows** on the dashboard: PumpPortal connection and migrations
  seen, graduates followed and readings, pool reads ok / failed with the last
  error, healthy RPC endpoints, capture rows written; the lane's rule.
* **Provenance**: the lane, graduation and execution settings, the capture
  path, the number of RPC endpoints and the fees seen are added to the
  engine's run provenance.
* **Public identifiers**: Solana public keys are registered with the core's
  redaction as public, so mints and pools are never masked as secrets.
* **Balance** (live only) from `getBalance`; a missing balance is an error,
  not 0 SOL (BUG-158).

## 2. Graduation tracking (FEAT-73)

Every coin PumpPortal's free `subscribeMigration` feed reports as migrated is
followed in its canonical PumpSwap pool, held or not: every 2 s for its first
5 minutes, every 10 s after that, for 4 hours (`graduation` settings). Pools
are read in batches through `get_pumpswap_pool_states`. A pool the RPC does
not have yet is retried for `pool_missing_grace_seconds`; a pool that is not
a SOL pair or does not decode ends the observation with that cause. At most
`max_mints` pools at once, and a full list never evicts.

Every migration and reading is written to the capture in pumpfun-trading's
row shape (`migration`, `observation_start`, `curve_poll` with
`source: "graduation"`, `observation_end` with cause, polls and first / last /
peak pool SOL), so the rc.8 read-out scripts work on it.

## 3. The `pumpswap_momentum` lane (FEAT-76, paper)

The pre-registered rule from the rc.8 read-out, as a trading-core pipeline
(Scout → Filters → Analyst):

* **Scout** `graduations`: proposes each graduate once, when its first reading
  at least `signal_after_seconds` (60) after the migration is in; a reading
  later than `signal_window_seconds` past that is too late and no decision is
  made.
* **Filter** `standard_pool`: the first reading's market cap within 0.5–2× of
  410.88 SOL (a just-completed curve), a live pool, optional `min_pool_sol`.
* **Filter** `anti_rug` (optional, `screen_entries`): the screen of §6.
* **Analyst** `momentum`: buy when the signal price is at least `min_ratio`
  (1.2) times the first price; confidence `min(1, ratio − 1)`; limit price
  the signal price plus `slippage_bps`.

Exits are the engine's (paper example: +20% take profit, −15% stop, 30
minutes max hold). Details and evidence: [STRATEGY.md](STRATEGY.md).

## 4. PumpSwap paper execution and costs

* **Fills through the pool**: a buy pays the swap fee on the SOL side and
  swaps the rest against the pool's reserves (constant product); a sell
  swaps tokens for SOL and pays the fee on what comes out
  (`pumpswap_sell_quote`). Every fill reads the pool afresh.
* **Fee**: the pool's tier from the PumpSwap fee config (by market cap) when
  it can be read, else the AMM `global_config` total (30 bps when checked),
  never below `fee_bps_floor`; cached for 5 minutes; recorded on each fill
  with its source.
* **Refused like a live order would be** (BUG-145, BUG-152): no pool, not a
  SOL pair, a failed read, an unknown fee, a drained pool, zero tokens or
  zero SOL out, a fill above the limit price. The engine counts refusals and
  retries exits with backoff.
* **Costs on every fill** (`TradeCosts`): `swap_fee`, the 5,000-lamport base
  `fee`, `priority_fee`, Jito `tip` when on, and Token-2022 account `rent`
  (1,513,840 lamports) on the first buy, refunded on the full exit (BUG-96).
  The engine tells the module when a sell closes the position, so the refund
  is booked on the right sell.
* **Entry latency**: `paper_entry_delay_seconds` waits before a paper buy
  reads the pool (BUG-121's lesson).
* **Live** orders are refused ("live PumpSwap trading is not built yet")
  until the live gate ([dev/RELEASE-GATE.md](dev/RELEASE-GATE.md)).

## 5. Capture and replay

* **Capture** (`capture` settings): rotated, gzipped, pruned by its own policy
  only (BUG-157), written off the event loop.
* **`trading-pump replay`** drives the real trading-core engine and the real
  module from one or more captures (plain or gzipped, in time order): a
  capture-backed pool source that never looks ahead, a fixed swap fee
  (`--fee-bps`, 125 by default), a replay clock, and the run's own status
  file, audit trail and events in a new directory. The summary gives the
  span, migrations, engine cycles, closed positions, win rate, net PnL and
  costs; `trading-core-audit` reads the trail
  ([CLI.md](CLI.md#trading-pump-replay)).

## 6. Anti-rug screening (FEAT-04, FEAT-26)

Ported from pumpbot with its keys, defaults and presets
([CONFIGURATION.md](CONFIGURATION.md#screening-the-anti-rug-screen-feat-04-feat-26)):
creator launch history, creator holding, top-5 concentration, Gini (a hard
reject, BUG-56), social links, holder data with retries for unindexed mints
(BUG-107), missing data never passes (BUG-57), funding-cluster graph and
Sybil / wash-trade ratios, bounded per-lookup timeouts, cached verdicts.
Enrichment reads the Pump.fun API record, the metadata URI and
`getTokenLargestAccounts` (BUG-95). **Off by default** in the lane: the
FEAT-76 rule was pre-registered without it.

## 7. Research recorders

`trading-pump record` (also `trading-pump-recorder`), each in its own
process, record-only, no wallet:

* **Cross-chain market recorder (FEAT-74)**: moved to trading-scout on
  2026-10-30 (its FEAT-1, with a sell check and per-launchpad read-outs);
  `--market` now only says so.
* **Slow-lane data (FEAT-65 phase 0)**, `--jupiter-quotes` and
  `--backfill-bars`: Jupiter round-trip quotes and prices for liquid Solana
  tokens (`configs/slow_lane_tokens.json`), priority-fee samples, and daily /
  hourly bars from GeckoTerminal or Binance.

## 8. Solana and Pump.fun SDK

* **Curve and pool maths** (`sdk/curve.py`, `sdk/pumpswap.py`): exact
  integer bonding-curve quotes with Pump.fun fees (BUG-01, BUG-13, BUG-66),
  curve decoding with sanity checks (BUG-104), PumpSwap pool and
  `global_config` decoding, canonical pool PDA, sell quotes.
* **Fee config** (`sdk/fee_config.py`): Pump.fun and PumpSwap fee tiers by
  market cap, checked against the modelled fee (BUG-138).
* **Transactions** (`sdk/pumpfun_execution.py`, `sdk/pumpswap_execution.py`,
  `sdk/transport.py`): Pump.fun `BuyV2` / `SellV2` with Token-2022
  detection (BUG-69), creator vault (BUG-68), fee and volume accumulators,
  idempotent ATA creation (BUG-54), the account close on a full exit
  (BUG-96); the PumpSwap sell (BUG-123), refusing non-SOL quote mints
  (BUG-124); compute budget and priority fee; Jito bundles with on-chain
  error checks (BUG-53). Kept for the live gate; nothing in the module sends
  a transaction yet.
* **Costs from transactions** (`sdk/costs.py`): fee, priority fee, tip and
  rent read from a transaction's meta (BUG-96, BUG-137).
* **RPC pool** (`infra/rpc_pool.py`, FEAT-08): latency routing, failover,
  JSON-RPC errors counted as failures (BUG-67), a breaker that sends nothing
  while open, a doubling cooldown and a single half-open probe (BUG-151),
  provider keys redacted (BUG-102).
* **Pump.fun API client** (`api/client.py`, FEAT-13) with bounded retries.
* **PumpPortal WebSocket host** (`streams/websocket.py`): reconnect with
  doubling backoff, pings and an idle reconnect (BUG-150), the API key kept
  out of every shown URL (BUG-117, BUG-118).

## 9. Quality

100% statement and branch coverage on Python 3.11–3.14, Ruff, Black, flake8
and mypy clean, a mirrored test layout with a regression-tag guard on
[dev/BUGS.md](dev/BUGS.md), no network in tests
([dev/TESTING.md](dev/TESTING.md)).

## 10. What became of pumpfun-trading's features

pumpfun-trading's catalogue, §1–45, is archived unchanged
([archive FEATURES](archive/pumpfun-trading/FEATURES.md)). **Here** means
this repository ships it (above); **core** means it moved to trading-core;
**not ported** means the code is in the history at tag `v0.3.0rc8` and the
reason is in [dev/TODO.md, Not ported](dev/TODO.md#not-ported).

| § | Feature | Status |
|---|---|---|
| 1 | Yellowstone Geyser gRPC streaming (FEAT-01) | Not ported (the transport was never production-ready, BUG-55; FEAT-39) |
| 2 | Jito bundling and anti-sandwich (FEAT-02) | Here: `sdk/jito.py` and tip costs; used once live execution is built |
| 3 | Execution and Solana SDK (FEAT-12) | Here (§8), without Raydium |
| 4 | Anti-rug screening (FEAT-04) | Here (§6), off by default |
| 5 | Pump.fun API client (FEAT-13) | Here (§8) |
| 6 | Trading bot runtime (FEAT-14) | Core: the engine replaces `pumpbot` |
| 7 | Risk controls (FEAT-15) | Core (`risk/`) |
| 8 | Strategy presets and dynamic exits (FEAT-03, FEAT-16) | Screening presets here; exits in the core (`ExitRules`); tiered take profit, stagnation and pre-graduation exits not ported |
| 9 | CLI entry points (FEAT-17) | `trading-core` (run, check, audit, events) and `trading-pump` (record, replay, env) |
| 10 | Replay engine and backtesting (FEAT-18) | Rebuilt as `trading-pump replay` (§5); `pumpfun-replay` and its sweeps not ported |
| 11 | Terminal UI, alerting, telemetry (FEAT-19) | Core |
| 12 | Testing standards (FEAT-20) | Here and in the core (§9) |
| 13 | Web dashboard and Telegram bot (FEAT-10) | Never built; proposed in trading-core |
| 14 | Documentation hub (FEAT-11) | Here (this tree) and in the core |
| 15 | Order-flow momentum signals (FEAT-07) | Not ported (needs the trade feed) |
| 16 | Raydium migration sniping (FEAT-05) | Not ported (Pump.fun migrates to PumpSwap, BUG-123) |
| 17 | Smart money and copy trading (FEAT-06) | Not ported |
| 18 | Multi-RPC load balancing (FEAT-08) | Here (§8) |
| 19 | Runtime decomposition (FEAT-12) | Done by the split: `bot/run.py` is gone |
| 20 | Stream recorder and replay datasets (FEAT-21) | The capture (§5); the PumpPortal trade-stream recorder not ported |
| 21 | Adaptive ratchet drawdown (FEAT-29) | Core |
| 22 | Diagnostic events (FEAT-30) | Core |
| 23 | Log retention and compression (FEAT-22) | Core (`RotatedFileSink`), used by the capture |
| 24 | Dynamic slippage and priority fees (FEAT-23) | Not ported (fixed `slippage_bps` and priority fee) |
| 25 | Capital rotation and displacement (FEAT-24) | Not ported |
| 26 | Pre-graduation harvester (FEAT-25) | Not ported (NO-GO, STRATEGY-PIVOT §6.11) |
| 27 | Funding cluster graph and Sybil detector (FEAT-26) | Here, inside screening (§6) |
| 28 | Hyperparameter optimizer (FEAT-27) | Not ported |
| 29 | Jito back-running and arbitrage (FEAT-28) | Not ported |
| 30 | Net PnL accounting and wallet reconciliation (FEAT-49) | Net PnL in the core; `pumpfun-audit reconcile` not ported yet (needed before live) |
| 31 | Operator pause, unattended alerts, supervised deployment (FEAT-50) | Core (pause, alerts, `--headless`); the `deploy/` templates not ported |
| 32 | Treasury profit sweep (FEAT-42) | Not ported |
| 33 | Watch list and batch curve poller (FEAT-51) | The batch reads are here (§2, §8); the launch watch list not ported |
| 34 | Confirmed momentum entry (FEAT-52) | Not ported (NO-GO, §6.11) |
| 35 | Pre-graduation lane and PumpSwap exit (FEAT-53, BUG-123) | The PumpSwap sell builder is here; the lane not ported |
| 36 | Shadow variants and read-out tooling (FEAT-58) | Not ported |
| 37 | Recorded research inputs (FEAT-54 … FEAT-65) | The slow-lane recorder is here (§7); the order-flow inputs not ported |
| 38 | Circuit breaker in replay (FEAT-66) | `trading-pump replay` runs the core's breaker as a live run does |
| 39 | Pre-registered paper verdict (FEAT-67) | Core (`trading-core-audit verdict`); rules in `configs/verdict_rules.json` |
| 40 | Run provenance (FEAT-68) | Core, with the module's additions (§1) |
| 41 | Scripted risk drills (FEAT-69) | Not ported (`pumpfun-drill` drove `TradingBot`) |
| 42 | Launch sample and post-exit tracking (FEAT-72) | Not ported (launch mode is NO-GO, §6.13) |
| 43 | Graduation tracking (FEAT-73) | Here (§2) |
| 44 | Cross-chain market recorder (FEAT-74) | Moved to trading-scout (2026-10-30) |
| 45 | Launch entry filters (FEAT-75) | Not ported (launch mode) |
