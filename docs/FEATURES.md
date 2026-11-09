# Features

What trading-pump ships today (§1–§9), and what became of every feature
pumpfun-trading listed (§10). Only shipped code is listed here; unbuilt work
is in [dev/PROPOSED-FEATURES.md](dev/PROPOSED-FEATURES.md) and open items in
[dev/TODO.md](dev/TODO.md). "Shipped" means the code works and is tested, not
that a lane makes money: results are in
[dev/RESULTS.md §6](dev/RESULTS.md#6-results-log).

## 1. A trading-core module (`pumpfun`)

`trading_pump.module:PumpModule` implements trading-core's `TradingModule`
and is registered in the `trading_core.modules` entry-point group as
`pumpfun`, so `trading-core run --config F` with `"module": "pumpfun"` runs
it. The engine owns the loop, sizing, the risk gate, the circuit breaker,
exits, accounting, the audit trail, the status file, alerts and the
dashboard; the module owns everything that knows Pump.fun and PumpSwap,
on trading-solana's Solana plumbing (since 0.5.0, §8).

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
  redaction as public, so mints and pools are never masked as secrets
  (trading-solana's `is_solana_pubkey`, registered when it is imported).
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

### 2.0 Token names (FEAT-91)

Each graduate's name and symbol are read from its mint account: Pump.fun
coins are Token-2022 mints with the TokenMetadata extension, so one
`getMultipleAccounts` call (batched, up to 100 mints) after a pool read
covers every new graduate, with no third-party API. The name goes into the
lane's signal, so a position shows it in the dashboard's **Name** column
(`Fomo Family (FOMO)`; the symbol only when it adds something), in events
and the trade ledger, and in the audit trail's `instrument_name`; the
**Instrument** column shows the mint address, shortened (`7rAX7yVr…pump`;
trading-core 0.3.1 asks `instrument_label` for it without the name, its
TC-9). Names are display only: no lane, filter or fill
reads them, a failed read is counted (`name_errors`) and retried at most
three times, and a graduate without a name shows its address. The name is
whatever the coin's creator typed, so control characters are removed and it
is cut at 32 characters (symbols at 12); trading-core escapes it before
display (its TC-8, fixed in 0.3.1). Replays have no names (a capture holds
none). New pools that are not graduations (FEAT-80) are not named.

- **Needs:** trading-core ≥ 0.3.1 (TC-8: module text escaped on the
  dashboard; TC-9: the Instrument column shows the id); the next release
  raises the floor.

### 2.1 New PumpSwap pools that are not graduations (FEAT-80, record-only)

Off by default (`new_pools.enabled`). trading-scout's first run saw about
60 new PumpSwap pools an hour that never came through PumpPortal's migration
feed (other launchpads' tokens and hand-made SOL pairs, 91% of them not
Pump.fun mints), against about 35 graduations. This finds them on-chain and
follows them like graduates, so a later lane can be judged on a capture:

* **Feed:** `programSubscribe` on the PumpSwap program's pool accounts over
  the RPC WebSocket (`PUMPFUN_RPC_WS_URL`, by default the RPC URL with
  `wss://`): one subscription for 301-byte accounts (the current layout) and
  one for 287 bytes (an older layout many new pools still have). PumpSwap
  writes the pool account on every swap, so the stream carries every pool
  that trades: about 47–73 messages and 36 kB a second (measured on
  2026-10-31), not only new pools. Its idle timeout is 60 s and it reports
  `pumpswap pool feed` degraded while disconnected.
* **What is new:** the pools seen in the first `warmup_seconds` (30 min) are
  the busy existing ones and are only remembered. After that, a pool seen
  for the first time is looked up: one `getSignaturesForAddress` (up to
  `signature_limit`, 100) dates it, one `getMultipleAccounts` reads the
  mint's decimals. A SOL pair created at most `max_age_seconds` (10 min) ago
  is followed: `observation_start` with `source: "new_pool"`, its pool,
  `created_at` (exact when its whole history fitted), decimals, slot and
  `sol_is_base`, then `curve_poll` / `observation_end` rows on the
  graduation schedule. Most of these pools hold **SOL as the base and the
  coin as the quote**, the reverse of a graduation pool (GeckoTerminal shows
  them flipped); both orders are read as coin / SOL, and the virtual quote
  reserve (0 on almost all of them) is recorded, not priced. Readings assume
  6 decimals, so prices of other mints are off by a power of ten while their
  ratios are right.
* **Never traded:** a new pool is marked decided when it is added, so no
  lane sees it; replay skips its rows. A graduate's second pool is not
  followed separately.
* **Graduates' pools are skipped:** a canonical pool seen for the first
  time is almost always an old graduate trading again (hundreds a minute
  after start), not a migration, so it is only counted; FEAT-77 cannot be
  measured this way without dating each one.
* **Dashboard:** a `New pools` status row (state, new pools followed, old
  pools looked up, graduates' pools skipped).

### 2.2 New Meteora DAMM v2 pools (FEAT-107, record-only)

**Moved to trading-meteora in 0.5.0** (ADR-011, trading-core ADR-010 and
FEAT-113): trading-meteora records new DAMM v2 pools, replays them and
writes their lane rows. This repository's `v0.4.0` is the last with the
capture (`damm.py`, `damm_pools`, `configs/damm.example.json`); `damm-1`
runs on that release's own copy ([`runs/damm-1.md`](dev/runs/damm-1.md)),
and its rows are read by trading-meteora unchanged. What it recorded is in
[`CHANGELOG.md`](../CHANGELOG.md) 0.4.0 and the history at tag `v0.4.0`. A
settings file that still has `damm_pools` is refused as an unknown key.

### 2.3 A push feed beside the poller (FEAT-174, record-only)

Off by default (`push.enabled`, [CONFIGURATION.md](CONFIGURATION.md#push-a-push-feed-of-the-followed-pools-vaults-feat-174)).
The poller reads each followed pool every 2 s for its first 5 minutes, so a
move is about a second old when seen and a peak between reads is missed;
every pump arm is positive with a 1.5 s fill and negative with 3 s. This
feed has the RPC push each change instead, for the read-out to compare:

* **Feed:** one RPC WebSocket (`PUMPFUN_RPC_WS_URL`) with one
  `accountSubscribe` per vault of each followed pool (graduates and, when
  on, FEAT-80's new pools), at `processed` commitment, from the pool's first
  reading (when its vaults are known) until `push.seconds` (300) after its
  migration; then `accountUnsubscribe`. Not a stream over the whole
  PumpSwap program (FEAT-77 measured 47 messages a second there). A
  reconnect subscribes every live vault again; a send that fails is sent
  again on the next flush.
* **Rows:** `vault_push` beside the poller's `curve_poll` rows in the same
  capture: `timestamp` (receive time), `mint`, `source`, `side` (the pool's
  `base` or `quote`), `vault`, `amount` (raw token units, `null` for an
  unreadable account) and `slot`. A graduation pool's quote amount is the
  SOL in the vault; the poller's `pool_sol` adds the pool's virtual quote
  reserve.
* **Never traded on:** the lanes, the market book, `lane-rows` and replay
  read the poller's rows only.
* **Dashboard:** a `Push feed` status row (state, pools pushed, pushes) and
  `push feed` degraded while disconnected.

### 2.4 The Float capture (FEAT-179, record-only)

Off by default (`float_capture.enabled`, [CONFIGURATION.md](CONFIGURATION.md#float_capture-floats-launches-trades-and-graduates-feat-179)).
Float (floatlaunch.xyz) launches coins on Raydium LaunchLab curves, and a
filled curve migrates to a Raydium CPMM pool. Its coins traded more
naturally than pump.fun's in the first two weeks, and that may not last, so
the platform is recorded at the finest grain (run `float-1`, 14 days: 7 to
design, 7 to judge). Nothing trades on it.

* **Streams:** one RPC WebSocket with `logsSubscribe` mentioning Float's
  program (launches, fee cycles), each Float platform config (every
  LaunchLab trade on a Float curve names its platform config; these carry
  the curve trades and the migrations) and each followed graduate's CPMM
  pool for 2 hours. A transaction seen on two subscriptions is read once.
  The platform list is read again every hour from Float's config account.
* **Decoding** (`float_events.py`): LaunchLab's `TradeEvent` and
  `PoolCreateEvent` from its on-chain IDL, Float's launch event, CPMM's
  `SwapEvent`, and the accounts (curve, platform fees, Float's platform
  list, CPMM pool), pinned to mainnet records. Checked before building
  (2026-11-09): on 1,597 trades of 30 Float curves every event matched its
  reserves, fees and vault changes; on 656 swaps of 8 graduates' CPMM pools
  the vaults moved by the event's amounts.
* **Rows:**
  - `float_launch`: pool, mint, quote mint, launcher, name, symbol,
    decimals, the metadata URI's host, the curve's terms, then one read of
    the curve and the mint: platform and its fee a side, curve state, token
    program, mint and freeze authorities, Token-2022 extensions and the
    risks trading-solana's `mint_facts` names;
  - `float_trade`: each curve trade (side, amounts in and out, the four
    fees, the reserves before and after, the curve's status) with its slot
    and receive time;
  - `float_trader`: a trade's signers (fee payer first) and block time,
    looked up at `trader_lookups_per_second`, as the logs carry neither;
  - `float_migration`: at `MigrateToCpswap`, the curve and its final state,
    the CPMM pool and its vaults, and the largest token accounts with their
    owners (`pool: true` for the curve's and the CPMM pool's vaults);
  - `float_cpmm_trade`: each CPMM swap on a followed graduate's pool for
    2 hours (amounts, mints, vaults before, transfer, trade and creator
    fees);
  - `float_pool_reading`: the graduate's two vault amounts, the fees held in
    them (protocol, fund, creator) and the reserves (vault less fees), every
    2 s for 30 minutes;
  - `float_fee_cycle`: Float's fee claims, holder payouts and harvests,
    their instruction names and events as bytes (Float publishes no IDL);
  - `float_platforms`: each platform's fee a side, at every refresh.
* **Units:** raw. Non-SOL quotes (tokenized stocks, other tokens) keep
  their own units with the quote mint; their USD prices come from
  GeckoTerminal at the read-out.
* **Health:** each Float transaction is market data for the engine's
  health monitor (a Float-only run has no pool poller); `float feed` is
  degraded while the stream is down; a `Float` status row counts launches,
  trades, migrations and graduates followed.

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
minutes max hold) unless the lane sets its own (FEAT-79 below). Details and
evidence: [STRATEGY.md](STRATEGY.md).

Lane keys added in 0.4.0-rc.4 (all off by default, so a 0.4.0-rc.3 config
trades the same): `max_ratio` (an upper bound on the signal ratio),
`first_pool_min_sol` / `first_pool_max_sol` (a band on the first reading's
pool SOL), `slippage_bps` (the lane's own limit, over `execution`'s) and
`exits`.

### 3.1 The `pumpswap_instant` lane (FEAT-78, paper)

A second lane over the same graduates, for the **instant graduations**:
coins whose first pool reading already shows a market cap of 1,000–2,000 SOL
and 130–200 SOL in the pool (bought out of the curve in a block or two, not
the 410.88 SOL standard pool). It buys the ones that are **holding, not
running**: signal price 1.00–1.10× the first price at the same 60 s reading.
Off by default (`instant.enabled`).

* The scout tags each graduate with the lane whose first-reading band it is
  in (`pumpswap_instant` first, else the standard lane); the filter checks
  that lane's bands and the analyst its ratio band and slippage. Each signal
  and position carries its lane as its `strategy`, so the verdict and
  `trading-core-audit pnl --group-by strategy` judge them apart.
* Both lanes share the one graduation tracker, so they must use the same
  `signal_after_seconds` / `signal_window_seconds`, and their market-cap
  bands may not overlap (checked at start).
* Defaults are the replayed rule: ratio [1.0, 1.10), market cap 1,000–2,000,
  pool 130–200 SOL, exits +50% / −15% / 30 min.

### 3.2 Per-lane exits (FEAT-79)

`lane.exits` and `instant.exits` take trading-core's `ExitRules` keys
(`stop_loss_pct`, `take_profit_pct`, `take_profit_fraction`,
`trailing_activation_pct`, `trailing_drop_pct`, `max_hold_seconds`). The
module's `should_exit` evaluates a position's own lane's rules on its mark
(the exit value of selling into the pool), so the wider take-profit the
replay favours (+50% against the engine example's +20%) applies to the lanes
that asked for it. A stale mark only lets the time limit fire. A lane
without `exits` returns no decision and the engine's `exits` apply, so a
config that uses lane exits sets the engine's `exits` to `{}`: an engine
take-profit at +20% would otherwise close a position before the lane's +50%.

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
  only (BUG-157), written off the event loop by trading-core's capture
  writer (`trading_core.ops.capture.CaptureWriter`, FEAT-110; this
  module's own `recorder.py` until 0.5.0, unchanged in what it writes).
* **`trading-pump replay`** drives the real trading-core engine and the real
  module from one or more captures (plain or gzipped, in time order) on
  trading-core's replay harness (`trading_core.replay`, FEAT-110: the replay
  clock, the replay's settings, the engine and its loop): a capture-backed
  pool source that never looks ahead, fills at the recorded reading nearest
  the order (BUG-164), a fixed swap fee (`--fee-bps`, 125 by default), and
  the run's own status file, audit trail and events in a new directory. The summary gives the
  span, migrations, engine cycles, closed positions, win rate, net PnL and
  costs; `trading-core-audit` reads the trail
  ([CLI.md](CLI.md#trading-pump-replay)).

### 5.1 The strategy library's records (trading-core FEAT-133 and FEAT-117)

trading-core's strategy library (its ADR-011) runs venue-neutral entry
rules, gates and exits on four records: a listing, a reading, a trade print
and a holders snapshot (`trading_core.lanes.market`). This module turns its
captures into them (`lanes.py`), offline and live, on trading-core
`>=0.7.0`. Meteora DAMM v2 rows are trading-meteora's since 0.5.0 (§2.2).

* **`trading-pump lane-rows`** writes a capture as the library's rows for
  `trading-core-lanes sweep` ([CLI.md](CLI.md#trading-pump-lane-rows)). The
  capture is read twice, first for the listings, so its parts may come in
  any order. Generic rows only; nothing of the venue is left in
  them:

  | Capture row | Library row |
  |---|---|
  | `observation_start`, `source: "graduation"` | `listing`: `instrument` = `mint`, `at` = `migrated_at`, `kind: "graduation"` (no name or creator: the capture has none) |
  | `observation_start`, `source: "new_pool"` (FEAT-80) | `listing`: `instrument` = `mint`, `at` = `created_at` (else `migrated_at`), `kind: "listing"`, `creator` = `coin_creator` (none when it is the default key) |
  | `curve_poll` of either | `reading`: `instrument` = `mint`, `at` = `timestamp`, `price` = `PoolReading.price` from `pool_sol` / `pool_tokens` (SOL per whole token, as the module and its replay price; a new pool's by its recorded `decimals`), `liquidity` = `pool_sol` |

  **Skipped and counted:** a reading of a coin whose listing is not in the
  capture (followed before its oldest part; the library would take it for
  a new coin), a reading before its listing, a new pool whose decimals
  were not read, a drained pool (price 0: the row format
  carries no price 0), a malformed row. **Not written:** `trade` and
  `holders` rows (the captures record no swaps by wallet and no holder
  snapshots; the supply map's holder features are a study's CSV, not a
  capture), `progress` (graduates have left the curve). A coin followed
  twice keeps its first listing. On rc.9's capture the readings match
  `CaptureMarket` (the replay's reader) one for one, 1,429,111 of them.
* **The market book** (`PumpModule.market_book`, the `TradingModule` hook
  of trading-core FEAT-117): the graduates' listings and readings for the
  lanes the engine's settings compose. It is fed by the same translator on
  the capture rows as they are written, so a lane sees live what the sweep
  sees in the capture; new pools never enter it (they are record-only). It starts on the engine's first call (a graduate followed
  before that is left out: its listing is not known) and is trimmed on
  every call: a graduate with nothing new for
  `graduation.book_retention_seconds` (1 h) is dropped unless held
  ([CONFIGURATION.md](CONFIGURATION.md#graduation-following-graduates-feat-73)).
* **Not built:** the calibration (trading-core FEAT-133: the sweep must
  reproduce RESULTS §6.20 on the rc.8 to rc.11 rows before it judges a
  venue); it is run in trading-core.

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

`trading-pump record` and `trading-pump-recorder` are gone since 0.5.0.

* **Landing probe (FEAT-175, Unreleased):** `trading-pump land-probe` times
  transactions that trade nothing from a dedicated probe wallet, per send
  mode (`rpc`, `priority`, `jito`, `fast`), under a spending cap, and writes
  the delay sample trading-core's FEAT-176 replays draw from
  ([CLI.md](CLI.md#trading-pump-land-probe)). The probe is trading-solana's
  `land_probe`.

* **Cross-chain market recorder (FEAT-74)**: moved to trading-scout on
  2026-10-30 (its FEAT-1, with a sell check and per-launchpad read-outs).
* **Slow-lane data (FEAT-65 phase 0)**, `--jupiter-quotes` and
  `--backfill-bars` (`services/slow_lane.py`): **retired in 0.5.0**. The
  slow lane was judged NO-GO on 2026-10-29
  ([RESULTS §6.15](dev/RESULTS.md#615-feat-65-walk-forward-on-the-binance-history-no-go-2026-10-29));
  the recorders, `configs/slow_lane_tokens.json` and
  `PUMPFUN_JUPITER_API_KEY` are in the history at tag `v0.4.0`.

## 8. Solana and Pump.fun SDK

The Solana plumbing every Solana module shares is **trading-solana's** since
0.5.0 (FEAT-115; its `docs/API.md` lists each name and the file here it came
from): the RPC pool, the client core (wallet, account reads, balances), the
transaction transport and Jito, the cost parser, mint decoding (supply,
decimals, token names), wallet decoding and the program-subscribe feed base.
The Pump.fun and PumpSwap parts stay here:

* **Curve and pool maths** (`sdk/curve.py`, `sdk/pumpswap.py`): exact
  integer bonding-curve quotes with Pump.fun fees (BUG-01, BUG-13, BUG-66),
  curve decoding with sanity checks (BUG-104), PumpSwap pool and
  `global_config` decoding, canonical pool PDA, sell quotes.
* **Fee config** (`sdk/fee_config.py`): Pump.fun and PumpSwap fee tiers by
  market cap, checked against the modelled fee (BUG-138).
* **Transactions** (`sdk/pumpfun_execution.py`, `sdk/pumpswap_execution.py`,
  on trading-solana's `TransactionTransportMixin`): Pump.fun `BuyV2` / `SellV2` with Token-2022
  detection (BUG-69), creator vault (BUG-68), fee and volume accumulators,
  idempotent ATA creation (BUG-54), the account close on a full exit
  (BUG-96); the PumpSwap sell (BUG-123), refusing non-SOL quote mints
  (BUG-124); compute budget and priority fee; Jito bundles with on-chain
  error checks (BUG-53, trading-solana's). `PumpFunExecutionClient` keeps
  Pump.fun's `pump_fee_bps`. Kept for the live gate; nothing in the module
  sends a transaction yet.
* **Costs from transactions** (trading-solana's `costs`): fee, priority fee,
  tip and rent read from a transaction's meta (BUG-96, BUG-137).
* **RPC pool** (trading-solana's `rpc_pool`, FEAT-08): latency routing,
  failover, JSON-RPC errors counted as failures (BUG-67), a breaker that
  sends nothing while open, a doubling cooldown and a single half-open probe
  (BUG-151), provider keys redacted (BUG-102).
* **Pump.fun API client** (`api/client.py`, FEAT-13) with bounded retries.
* **PumpPortal WebSocket** (`streams/websocket.py`): the migration
  subscription and the API key kept out of every shown URL (BUG-117,
  BUG-118), on trading-core's stream loop (`trading_core.ops.stream`,
  FEAT-110): reconnect with doubling backoff, pings and an idle reconnect
  (BUG-150).
* **New-pool feed** (`pools.py`, FEAT-80): trading-solana's
  `ProgramSubscribeFeed` with PumpSwap's pool subscriptions.

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
| 2 | Jito bundling and anti-sandwich (FEAT-02) | trading-solana's `jito` since 0.5.0 (here, `sdk/jito.py`, until then); used once live execution is built |
| 3 | Execution and Solana SDK (FEAT-12) | Here (§8), without Raydium |
| 4 | Anti-rug screening (FEAT-04) | Here (§6), off by default |
| 5 | Pump.fun API client (FEAT-13) | Here (§8) |
| 6 | Trading bot runtime (FEAT-14) | Core: the engine replaces `pumpbot` |
| 7 | Risk controls (FEAT-15) | Core (`risk/`) |
| 8 | Strategy presets and dynamic exits (FEAT-03, FEAT-16) | Screening presets here; exits in the core (`ExitRules`); tiered take profit, stagnation and pre-graduation exits not ported |
| 9 | CLI entry points (FEAT-17) | `trading-core` (run, check, audit, events) and `trading-pump` (replay, lane-rows, env; `record` retired in 0.5.0) |
| 10 | Replay engine and backtesting (FEAT-18) | Rebuilt as `trading-pump replay` (§5); `pumpfun-replay` and its sweeps not ported |
| 11 | Terminal UI, alerting, telemetry (FEAT-19) | Core |
| 12 | Testing standards (FEAT-20) | Here and in the core (§9) |
| 13 | Web dashboard and Telegram bot (FEAT-10) | Never built; proposed in trading-core |
| 14 | Documentation hub (FEAT-11) | Here (this tree) and in the core |
| 15 | Order-flow momentum signals (FEAT-07) | Not ported (needs the trade feed) |
| 16 | Raydium migration sniping (FEAT-05) | Not ported (Pump.fun migrates to PumpSwap, BUG-123) |
| 17 | Smart money and copy trading (FEAT-06) | Not ported |
| 18 | Multi-RPC load balancing (FEAT-08) | trading-solana's since 0.5.0 (§8) |
| 19 | Runtime decomposition (FEAT-12) | Done by the split: `bot/run.py` is gone |
| 20 | Stream recorder and replay datasets (FEAT-21) | The capture (§5); the PumpPortal trade-stream recorder not ported |
| 21 | Adaptive ratchet drawdown (FEAT-29) | Core |
| 22 | Diagnostic events (FEAT-30) | Core |
| 23 | Log retention and compression (FEAT-22) | Core (`RotatedFileSink`), used by the capture |
| 24 | Dynamic slippage and priority fees (FEAT-23) | Not ported (fixed `slippage_bps` and priority fee) |
| 25 | Capital rotation and displacement (FEAT-24) | Not ported |
| 26 | Pre-graduation harvester (FEAT-25) | Not ported (NO-GO, RESULTS §6.11) |
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
| 37 | Recorded research inputs (FEAT-54 … FEAT-65) | The slow-lane recorder was here until 0.4.0 and is retired (§7); the order-flow inputs not ported |
| 38 | Circuit breaker in replay (FEAT-66) | `trading-pump replay` runs the core's breaker as a live run does |
| 39 | Pre-registered paper verdict (FEAT-67) | Core (`trading-core-audit verdict`); rules in `configs/verdict_rules.json` |
| 40 | Run provenance (FEAT-68) | Core, with the module's additions (§1) |
| 41 | Scripted risk drills (FEAT-69) | Not ported (`pumpfun-drill` drove `TradingBot`) |
| 42 | Launch sample and post-exit tracking (FEAT-72) | Not ported (launch mode is NO-GO, §6.13) |
| 43 | Graduation tracking (FEAT-73) | Here (§2) |
| 44 | Cross-chain market recorder (FEAT-74) | Moved to trading-scout (2026-10-30) |
| 45 | Launch entry filters (FEAT-75) | Not ported (launch mode) |
