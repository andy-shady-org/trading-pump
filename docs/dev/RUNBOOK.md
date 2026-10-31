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

Runs happen in **`runtime-pump`**, a folder beside the repositories, never
in a checkout: relative paths resolve from the working directory, and each
run must keep the code it was registered with while the repositories move
on. Every run uses a tagged copy of trading-core and trading-pump in its own
venv.

```text
~/projects/git/trading/runtime-pump/
├── bin/
│   ├── install-release.sh   # bin/install-release.sh <core tag> <pump tag>: clones both tags, builds venvs/pump-<tag>/
│   └── run.sh               # bin/run.sh <config> <venv> [run args]: starts one run in this terminal
├── configs/
│   ├── pump-12.json         # one per run, named after it; never edited once it has run
│   ├── verdict-pump-12-standard.json   # one pre-registered verdict file per lane ("strategy" set)
│   ├── verdict-pump-12-instant.json
│   └── smoke.json           # the 30-minute check before a counted run
├── releases/                # trading-core-<tag>/, trading-pump-<tag>/ (never edited)
├── venvs/                   # pump-<tag>/, current -> the newest install
├── data/
│   └── pump-12/             # every file one run writes: status, audit, events, log, capture
└── .envrc                   # credentials only: PUMPFUN_RPC_URL(S), TRADING_CORE_ALERT_*; chmod 600, never committed
```

- **Run names** follow trading-core's `docs/dev/DOCUMENTATION.md` §7:
  `pump-<n>` for a run of the lanes, counting on from rc.11 (the next
  counted run is `pump-12`), or what a record-only run is for (`pools-1`).
  A number is never reused, even for a run that was stopped. Older runs
  keep their names (`data/rc9/`, `configs/rc11-paper.json`).
- **One run, one folder, one config.** Every path in the config
  (`status_path`, `audit_log_path`, `event_log_path`, `log_file`,
  `module_settings.capture.path`) points into the run's own `data/<run>/`.
  When you copy a config for a new run, change every path, the module's
  included: rc.10 kept rc.9's capture path and the two runs rotated one
  file from under each other (trading-core TC-7; a second writer now stops
  at start). trading-core refuses a status file of another module or mode.
- **Install a release** once per pair of tags:
  ```bash
  cd ~/projects/git/trading/runtime-pump
  bin/install-release.sh v0.2.2 v0.4.0rc5     # trading-core tag, trading-pump tag
  ```
  Running it again with the same tags changes nothing; a moved tag or an
  edited copy is an error.

## 2. Preflight

- `trading-pump env`: the RPC variables are set, nothing unexpected is
  warned about. Each run has its **own RPC key** and a fallback in
  `PUMPFUN_RPC_URLS` (BUG-149, BUG-151).
- `trading-core check --config configs/<run>.json` passes (it builds the
  module, so a bad `module_settings` key fails here).
- The RPC endpoints are on **mainnet-beta**: the module checks this at start
  (BUG-160) and `bin/run.sh` refuses to start without an RPC endpoint.
- `trading-core modules` lists `pumpfun`, and the venv holds the tags you
  mean to run (`venvs/pump-<tag>/bin/pip show trading-core trading-pump`).
- Alerts: one `TRADING_CORE_ALERT_*` provider set and a test alert received.
- Disk: a graduation capture is about 1.2 M rows, about 320 MB, a day before
  compression (rc.8); `capture.max_files` × `max_bytes` must hold the whole
  run (BUG-157's lesson). The default, 100 × 50 MB, holds about two weeks.
  With `new_pools` on, the RPC WebSocket also streams about 3 GB a day
  ([`COSTS.md` §3.3](COSTS.md#33-on-the-new-stack-trading-pump-040-from-2026-10-28)).
- For live (not built yet): a dedicated hot wallet holding only the stage's
  capital ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate)).

### 2.1 Smoke run (30 minutes, not counted)

Before every counted run, on the venv the run will use, check that the
runtime sees the market and that its capture replays:

```bash
bin/run.sh configs/smoke.json pump-v0.4.0rc5 --headless --max-cycles 1800
grep -c '"curve_poll"' data/smoke/capture.jsonl          # pool readings: must be well above 0
venvs/pump-v0.4.0rc5/bin/trading-pump replay --config configs/smoke.json \
    --capture data/smoke/capture.jsonl* --out data/smoke-replay
```

`bin/run.sh` will not reuse a data folder: move the last smoke run's
`data/smoke/` aside first. A smoke run with no pool readings is a failed
smoke run (BUG-159, BUG-160), whatever else it shows.

## 3. A paper run that counts

1. **Write the config and the verdict files.** Copy the previous run's
   config to `configs/<run>.json` and change only what the run record will
   say, every file path included (§1). Write one verdict file per lane, the
   pre-registered rule with `"strategy"` set to the lane.
2. **Write the run record before the start.** Take the hashes:
   ```bash
   shasum -a 256 configs/pump-12.json configs/verdict-pump-12-*.json
   ```
   and commit `docs/dev/runs/<run>.md` with the question, both tags and
   commits, the hashes, the rule in words, the planned start and end, and
   each lane's stage ([`runs/README.md`](runs/README.md)). Never edit the
   config, the verdict files or that half of the record after the start.
3. **Start it in tmux**, so it outlives the terminal window:
   ```bash
   tmux new -s pump-12
   cd ~/projects/git/trading/runtime-pump      # direnv loads .envrc
   bin/run.sh configs/pump-12.json pump-v0.4.0 --headless
   ```
   72 h at 1 s cycles is `--max-cycles 259200`; without it, stop the run with
   `SIGTERM` at the planned end.
4. **In the first hour:**
   ```bash
   zcat -f data/pump-12/capture.jsonl* | head -1 | jq .timestamp       # oldest row ≈ start time (BUG-157)
   jq '.run_provenance | {package_version, git_commit, git_dirty, module_version, module_git, config_file_sha256}' \
     data/pump-12/status.json      # both builds clean (git_dirty false) and the frozen config
   trading-core-events --path data/pump-12/events.jsonl --errors-only --limit 50
   ```
   The dashboard's module rows should move: PumpPortal `connected` with a
   growing migration count, graduates followed (tens at a time at about 900
   migrations a day), pool reads ok with few failures, all RPC endpoints
   healthy, capture rows growing, and one strategy row per lane.
5. **Twice a day:** the dashboard's Health panel (no degraded conditions),
   the Strategies panel (a paused lane says why), the capture's newest row,
   `trading-core-audit pnl --path data/pump-12/audit.jsonl --group-by strategy`.
6. **At the end** (72 h): stop with `SIGTERM`, then for each lane
   ```bash
   trading-core-audit verdict --path data/pump-12/audit.jsonl --rules configs/verdict-pump-12-standard.json
   trading-core-audit verdict --path data/pump-12/audit.jsonl --rules configs/verdict-pump-12-instant.json
   trading-core-audit pnl --path data/pump-12/audit.jsonl --group-by reason
   trading-pump replay --config configs/pump-12.json --capture data/pump-12/capture.jsonl* --out data/pump-12-replay
   ```
   The replay should land on the same positions within the fee difference;
   a gap means the replay or the run is wrong, and it is a bug until
   explained. Add the read-out to the run record (per lane: positions, net,
   win rate, verdict and the checks that failed) and a new section to
   [`RESULTS.md`](RESULTS.md). Name in the read-out any window with no
   healthy RPC endpoint (§4).

## 4. When something goes wrong

Start with trading-core's incident checklist (`docs/OPERATIONS.md` §7: pause,
read Health, events, money). Module specifics:

| What you see | What it means | What to do |
|---|---|---|
| Health: `pumpportal feed` degraded; PumpPortal `disconnected` | The migration socket is down. It reconnects on its own with a doubling wait (to 30 s), pings every 20 s, and drops a socket silent for `stream.idle_timeout_seconds` (1,800 s by default: the migration feed is quiet between graduations, BUG-150, BUG-163) | Nothing, unless it lasts: check PumpPortal's status. No migrations means no new graduates, so no entries; held positions are still priced from their pools |
| Health: `rpc network` degraded, or an event `RPC endpoint on the wrong network` | An endpoint serves devnet, testnet or an unknown network (BUG-160). With a mainnet endpoint left it was dropped from the pool; with none, every pool reads as missing and nothing is captured | Fix `PUMPFUN_RPC_URL(S)` (a provider gives each key a mainnet and a devnet URL), check with `runtime-pump/diag-rpc.py`, restart |
| Every observation ends `missing`, no `curve_poll` rows, "market data stale" | The pools could not be read: a wrong-network endpoint (above) or an endpoint failing every read (`solana rpc`, BUG-159) | As above; `trading-pump replay` on such a capture says it holds no pool readings |
| Health: `solana rpc` degraded; pool reads failing | Pool reads fail. The RPC pool stops sending to an endpoint that rate limits or fails three times (doubling cooldown, one probe at a time, BUG-151); entries stop while reads fail (BUG-149); held quotes go stale, so exits are refused and retried with the engine's backoff | Check the key's plan and usage. A 429 saying the credits are used up will not recover by waiting: switch to another key and restart. Data recorded with no healthy endpoint is not a valid paper sample: note the window |
| Health: `pumpswap pool feed` degraded (only with `new_pools` on) | The RPC WebSocket for new pools is down or silent for 60 s (`new_pools.idle_timeout_seconds`); it reconnects on its own | Nothing, unless it lasts: check `PUMPFUN_RPC_WS_URL` (or the RPC URL it is built from) and the provider's WebSocket limits. Graduates and the lanes are not affected |
| A lane shows `paused` in the Strategies panel | trading-core's per-lane pause (FEAT-81, `strategies` in the engine settings): the lane's last closed positions lost more than `pause_below`; it resumes on its own after `pause_minutes` | Nothing: exits continue and the other lane keeps trading. A pause is a `strategy_paused` event and audit record |
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

Moved to trading-scout on 2026-10-30: it runs as that repository's `scout`
module under `trading-core run`, with a sell check of every followed pool and
a per-launchpad read-out (its `docs/dev/RUNBOOK.md`). `trading-pump record
--market` now only says so. The rc.8 data it wrote (`market/market.jsonl`)
reads the same way with `trading-scout readout`.

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
| Install a release | `bin/install-release.sh <core tag> <pump tag>` (in `runtime-pump`) |
| Start a run | `bin/run.sh configs/<run>.json pump-<tag> [--headless] [--max-cycles N]` |
| Paper run (outside `runtime-pump`) | `trading-core run --config configs/<run>.json [--headless]` |
| Record only | the same, with every lane off (`configs/capture.example.json`, or `new_pools` on as in pools-1) |
| Pause / resume entries | `kill -USR1 <pid>` |
| A lane's verdict | `trading-core-audit verdict --path <trail> --rules configs/verdict-<run>-<lane>.json` |
| Net PnL by lane / exit reason | `trading-core-audit pnl --path <trail> --group-by strategy` / `--group-by reason` |
| Diagnostic events | `trading-core-events --path data/<run>/events.jsonl --tail` |
| Replay a capture | `trading-pump replay --config F --capture C... --out DIR` |
| Variables in use | `trading-pump env` |
| Slow-lane quotes / bars | `trading-pump record --jupiter-quotes`, `--backfill-bars` (§5.1) |
| Cross-chain market data | trading-scout (moved 2026-10-30, §5.2) |
