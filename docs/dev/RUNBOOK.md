# Operations runbook

How to run, watch and recover the Pump.fun module on trading-core. The
engine's own operation (modes, signals, files, restarts, alerts, supervision,
the incident checklist) is trading-core's `docs/OPERATIONS.md`; this page
adds what is specific to this module. **When** a build or a capital increase
is allowed is decided by [`RELEASE-GATE.md`](RELEASE-GATE.md).

pumpbot's runbook, with the launch-lane procedures, the trade-feed breaker,
the profit sweep, the drills and the systemd templates, is
[archived](../archive/pumpfun-trading/dev/RUNBOOK.md).

## 1. Runtime layout

Run from a dedicated runtime folder, never from the repository: relative
paths resolve from the working directory, and test runs mixed into a real
run's files make the record unusable.

```text
~/projects/git/trading/runtime/<run>/   # one folder per run (paper-feat76-1, capture-1, ...)
├── .envrc                              # PUMPFUN_RPC_URL(S), TRADING_CORE_ALERT_*; chmod 600, never committed
├── configs/<run>.json                  # copied from configs/*.example.json, then frozen
├── configs/verdict_rules.json          # the pre-registered rule, copied before the start
└── data/                               # status, audit, events, log, capture (paths in the config)
```

Keep one status file per module and mode (trading-core refuses another's).

## 2. Preflight

- `trading-pump env`: the RPC variables are set, nothing unexpected is
  warned about. Each run has its **own RPC key** and a fallback in
  `PUMPFUN_RPC_URLS` (BUG-149, BUG-151).
- `trading-core check --config configs/<run>.json` passes (it builds the
  module, so a bad `module_settings` key fails here).
- The RPC endpoints are on **mainnet-beta**: the module checks this at start
  (BUG-160), and a smoke run must capture `curve_poll` rows and replay before
  a counted run starts.
- `trading-core modules` lists `pumpfun`, and the installed versions are the
  tags you mean to run (`pip show trading-core trading-pump`).
- Alerts: one `TRADING_CORE_ALERT_*` provider set and a test alert received.
- Disk: a graduation capture is about 1.2 M rows, about 320 MB, a day before
  compression (rc.8); `capture.max_files` × `max_bytes` must hold the whole
  run (BUG-157's lesson). The default, 100 × 50 MB, holds about two weeks.
- For live (not built yet): a dedicated hot wallet holding only the stage's
  capital ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate)).

## 3. A paper run that counts

1. Copy the config and `configs/verdict_rules.json` into the runtime folder.
   Write down `sha256sum configs/<run>.json configs/verdict_rules.json` in the
   release record **before** the start; never edit either after it.
2. Start it under a supervisor (trading-core `docs/OPERATIONS.md` §6) or in
   `tmux`:
   ```bash
   trading-core run --config configs/<run>.json --headless
   ```
3. In the first hour:
   ```bash
   zcat -f data/paper/capture.jsonl* | head -1 | jq .timestamp       # oldest row ≈ start time (BUG-157)
   jq '.run_provenance | {package_version, git_commit, git_dirty, module_version, module_git, config_file_sha256}' \
     data/paper/status.json      # both builds clean (git_dirty false) and the frozen config
   trading-core-events --path data/paper/events.jsonl --errors-only --limit 50
   ```
   The dashboard's module rows should move: PumpPortal `connected` with a
   growing migration count, graduates followed (tens at a time at about 900
   migrations a day), pool reads ok with few failures, all RPC endpoints
   healthy, capture rows growing.
4. Twice a day: the dashboard's Health panel (no degraded conditions), the
   capture's newest row, `trading-core-audit pnl --path data/paper/audit.jsonl`.
5. At the end (72 h for FEAT-76): stop with `SIGTERM`, then
   ```bash
   trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict_rules.json
   trading-core-audit pnl --path data/paper/audit.jsonl --group-by reason
   trading-pump replay --config configs/<run>.json --capture data/paper/capture.jsonl* --out data/replay-check
   ```
   The replay should land on the same positions within the fee difference;
   a gap means the replay or the run is wrong, and it is a bug until
   explained. Record the verdict, both hashes and the provenance in the
   release record and the result in [`STRATEGY-PIVOT.md` §6](STRATEGY-PIVOT.md#6-results-log).
   Leave out of the verdict any window with no healthy RPC endpoint (§4).

## 4. When something goes wrong

Start with trading-core's incident checklist (`docs/OPERATIONS.md` §7: pause,
read Health, events, money). Module specifics:

| What you see | What it means | What to do |
|---|---|---|
| Health: `pumpportal feed` degraded; PumpPortal `disconnected` | The migration socket is down. It reconnects on its own with a doubling wait (to 30 s), pings every 20 s, and drops a socket silent for 300 s (BUG-150) | Nothing, unless it lasts: check PumpPortal's status. No migrations means no new graduates, so no entries; held positions are still priced from their pools |
| Health: `rpc network` degraded, or an event `RPC endpoint on the wrong network` | An endpoint serves devnet, testnet or an unknown network (BUG-160). With a mainnet endpoint left it was dropped from the pool; with none, every pool reads as missing and nothing is captured | Fix `PUMPFUN_RPC_URL(S)` (a provider gives each key a mainnet and a devnet URL), check with `runtime-pump/diag-rpc.py`, restart |
| Every observation ends `missing`, no `curve_poll` rows, "market data stale" | The pools could not be read: a wrong-network endpoint (above) or an endpoint failing every read (`solana rpc`, BUG-159) | As above; `trading-pump replay` on such a capture says it holds no pool readings |
| Health: `solana rpc` degraded; pool reads failing | Pool reads fail. The RPC pool stops sending to an endpoint that rate limits or fails three times (doubling cooldown, one probe at a time, BUG-151); entries stop while reads fail (BUG-149); held quotes go stale, so exits are refused and retried with the engine's backoff | Check the key's plan and usage. A 429 saying the credits are used up will not recover by waiting: switch to another key and restart. Data recorded with no healthy endpoint is not a valid paper sample: note the window |
| Pool reads ok, graduates followed stays at `max_mints` | The follow list is full; new graduates are skipped (`list_full` in the tracker stats) | Raise `graduation.max_mints` if the RPC budget allows; the lane only sees graduates that are followed |
| Observations end `missing` | The RPC did not have the pool within `pool_missing_grace_seconds` (60 s) | A few are normal (empty or unrelated migration events). Many mean a lagging RPC node: try another endpoint |
| `exit failed ×N` on a position | The sell was refused (stale quote, failed read, zero SOL out) | The engine retries with backoff; it sells once the pool reads again. A drained pool sells for nothing: that is the result, not a bug |
| Warning `PUMPFUN_X is set but not read` | A pumpbot variable is still in the environment | Move the setting to the config ([`ENVIRONMENT.md` §2](../ENVIRONMENT.md#2-variables-that-are-no-longer-read)) and unset it |
| Warning `PUMPFUN_STREAM_URL carries api-key` | The PumpPortal key is in the URL | Move it to `PUMPFUN_STREAM_API_KEY` (BUG-118); the key is not needed for migrations at all |

## 5. Research recorders

Each recorder is a separate process: no wallet, no transactions, nothing
shared with the engine, so it cannot change a paper run. Run them in their
own folder and window, next to the runs.

### 5.1 Slow-lane data (FEAT-65 phase 0)

Record-only data for the slow lane
([`PROPOSED-FEATURES.md` FEAT-65](PROPOSED-FEATURES.md#feat-65-slow-lane-daily-bar-trend-on-liquid-solana-tokens-via-jupiter)).
Both APIs are used keyless (no Jupiter key needed).

1. Start the quote recorder and leave it running (weeks of samples are worth
   more than 48 h):
   ```bash
   cd runtime && mkdir -p slow_lane
   trading-pump record --jupiter-quotes --tokens configs/slow_lane_tokens.json \
     -o slow_lane/jupiter_quotes.jsonl          # every 300 s; Ctrl-C / SIGTERM stops it cleanly
   ```
   With `PUMPFUN_RPC_URL` (or `PUMPFUN_RPC_URLS`) in the environment it also
   samples priority fees (about 13 RPC calls per 5 min); add
   `--no-fee-samples` to skip them.
2. Download the bar history once (about 15 min for the default list):
   ```bash
   trading-pump record --backfill-bars --tokens configs/slow_lane_tokens.json -o slow_lane/bars.jsonl
   ```
   The public API serves about 6 months; re-run it monthly into a new file
   to extend the series and de-duplicate on `mint`, `timeframe`, `timestamp`
   when reading.

   For a multi-year history use Binance's public spot klines (keyless; each
   `<SYMBOL>USDT` pair from its listing; for the default list about 3 min,
   315,000 bars, one ~100 MB file):
   ```bash
   trading-pump record --backfill-bars --bar-source binance --tokens configs/slow_lane_tokens.json \
     -o slow_lane/binance_bars.jsonl
   ```
   Expect SOL from August 2020, RAY from August 2021, JTO and BONK from late
   2023, JUP, PYTH and WIF from early 2024, ORCA from December 2024. mSOL and
   jitoSOL have no Binance pair (`"binance": null` in the token list); a token
   without a pair shows as `Pairs missing` and is skipped. Binance prices are
   the centralised-exchange market in USDT, not the Solana pool a swap would
   fill in: use them for the trend signal and keep the Jupiter quotes for
   costs. Keep the two venues in separate files (`bars_in_sol` only divides
   bars of the same `venue`). If the run stops with `Binance refused this
   host` (HTTP 451 = restricted region, 403 = firewall, 418 = IP ban after
   rate limiting), try another network or `--bar-base-url
   https://api.binance.com` (which itself answers 451 in some regions, e.g.
   the US); after a 418, wait before retrying. A few missing hours (SOL 10,
   RAY 3 since listing) are Binance's own trading outages, not download
   errors. Top up later with `--bar-since YYYY-MM-DD` into a new file. A
   backfill always writes one file: unlike the quote recorder, it does not
   rotate at 50 MB.
3. Health checks while it runs: rows keep arriving, and errors stay rare.
   ```bash
   tail -n 1 slow_lane/jupiter_quotes.jsonl | jq '{timestamp, event, symbol}'
   jq -c 'select(.event=="quote_error") | {symbol, side, size_sol, status}' slow_lane/jupiter_quotes.jsonl | tail
   jq -c 'select(.event=="quote" and .side=="sell") | {symbol, size_sol, round_trip_cost_bps}' \
     slow_lane/jupiter_quotes.jsonl | tail -n 30            # round-trip cost per token and size
   ```
   Many `status: 429` rows mean the keyless limit changed: raise
   `--request-gap` or `--quote-interval`. Edit the token list only between
   runs, and keep the edited file with the data.
4. Reading the data (BUG-139). The sell leg is quoted a pacing gap after the
   buy leg, so each `round_trip_cost_bps` also holds the price move in
   between; sell rows carry `buy_gap_seconds` and `buy_gap_slots`. Judge
   costs on the distribution,
   `trading_pump.services.slow_lane.round_trip_cost_summary(rows)` (median
   and quartiles per token and size), never on one row. Bars are USD
   (`currency: "usd"`): GeckoTerminal's from each token's top pool as chosen
   when the backfill ran, Binance's from the `<SYMBOL>USDT` pair
   (`quote_asset: "USDT"`, closed bars only); `bars_in_sol(rows)` re-prices
   them against SOL's own bar from the same venue, the baseline a SOL wallet
   has to beat.

### 5.2 Cross-chain market recorder (FEAT-74)

Record-only data on the coins Pump.fun lanes never see: other Solana
launchpads (Meteora, Raydium LaunchLab, PumpSwap pools), Base and BSC, and
old coins when they start trending
([`FEATURES.md` §7](../FEATURES.md#7-research-recorders)). No wallet and no
RPC: GeckoTerminal and DexScreener, keyless and paced, so it costs no RPC
credits.

1. Start it and leave it running:
   ```bash
   cd runtime && mkdir -p market
   trading-pump record --market -o market/market.jsonl     # Ctrl-C / SIGTERM stops it cleanly
   ```
   Defaults: Solana, Base and BSC (`--market-chains solana,base,bsc,eth` adds
   Ethereum); every new pool followed except Pump.fun curves, of which 10%
   are (`--market-sample solana:pump-fun=0.1`); trending (5 min, 1 h) and
   top 24 h volume lists every 5 minutes (`--market-no-lists` turns them
   off). The follow list is saved to `market/state.json` every minute, so a
   restart resumes it; the first minutes after a start fill the lists at
   GeckoTerminal's pace (about one chain a minute).
2. Health checks: a `market_stats` row every 10 minutes.
   ```bash
   jq -c 'select(.event=="market_stats") | {following, by_chain, snapshots, errors, rate_limited, discovery_gaps, token_matched}' market/market.jsonl | tail -n 3
   ```
   `rate_limited` climbing means a free limit changed: stop it and raise the
   gaps in `services/market_recorder.py`. `discovery_gaps` counts discovery
   passes where every page was new (Solana launches outran four pages a
   minute); a few a day are fine. `following` should settle in the
   thousands, below the 20,000 cap (`--market-max-followed`).
3. Disk: about 600 bytes a row, roughly 1 GB a day before compression; parts
   rotate at 100 MB and are gzipped, and all 300 are kept (no age limit).
   Move old parts into `archive/` with the runs they belong to.
4. Reading the data:
   ```bash
   jq -c 'select(.event=="market_pool" and .followed) | {chain, source, dex, pool, created_at, liquidity_usd}' market/market.jsonl   # what was picked, and why
   jq -c 'select(.event=="market_snapshot") | {timestamp, chain, pool, age_seconds, price_usd, liquidity_usd, txns}' market/market.jsonl
   jq -c 'select(.event=="market_end") | {chain, pool, source, cause, followed_seconds}' market/market.jsonl
   ```
   A rule counts only on what it could have seen when it fired: join
   snapshots to `market_pool` rows by `chain` + `pool`, enter at the first
   snapshot that meets the rule, use the later snapshots for the outcome,
   and include the pools that ended `dead`. Rows with `matched: "token"`
   price the coin's most liquid pair (`pair_address`), not the pool
   GeckoTerminal listed.

## 6. Drills

pumpbot's scripted drills (`pumpfun-drill`) drove its own runtime and were
not ported; the breaker they tested is trading-core's, and rebuilding them
on the engine is in trading-core's TODO. Until then, before a run that
counts and after any release that touches the module's feed, poller or
executor, run these by hand on a paper config in a scratch folder:

| Drill | How | Pass |
|---|---|---|
| Restart with a position open | Stop with `SIGTERM` while holding; start again | The position is restored and priced from its pool; no second buy of it |
| Feed loss | Block `pumpportal.fun` (firewall or a wrong `PUMPFUN_STREAM_URL`) for 10 minutes | `pumpportal feed` degraded, an alert after `degradation_alert_minutes`, recovery when unblocked, no restart needed |
| RPC loss | Point `PUMPFUN_RPC_URL` at a dead endpoint and restart | `solana rpc` degraded, no entries, exits refused and retried; recovery once a good endpoint is back |
| Operator pause | `kill -USR1 <pid>` twice | Entries stop and resume; exits continue |

## 7. Command reference

| Goal | Command |
|---|---|
| Lint / format / types / tests | `nox -s lint`, `nox -s format`, `nox -s mypy`, `nox -s tests` (3.11–3.14) |
| Package check | `nox -s package` |
| Validate a config | `trading-core check --config configs/<run>.json` |
| Paper run | `trading-core run --config configs/<run>.json [--headless]` |
| Record only | `trading-core run --config configs/capture.json --headless` |
| Pause / resume entries | `kill -USR1 <pid>` |
| Paper go / no-go | `trading-core-audit verdict --path <trail> --rules configs/verdict_rules.json` |
| Net PnL by exit reason | `trading-core-audit pnl --path <trail> --group-by reason` |
| Diagnostic events | `trading-core-events --path data/<run>/events.jsonl --tail` |
| Replay a capture | `trading-pump replay --config F --capture C... --out DIR` |
| Variables in use | `trading-pump env` |
| Slow-lane quotes / bars | `trading-pump record --jupiter-quotes`, `--backfill-bars` (§5.1) |
| Cross-chain market data | `trading-pump record --market` (§5.2) |
