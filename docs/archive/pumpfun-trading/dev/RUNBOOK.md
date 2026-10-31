# Operations Runbook

How to run, monitor, test and recover the bot in operator mode (terminal UI, `pumpbot`). The bot is in production: it places real trades whenever `dry_run` and `paper_trade` are both off. **When** a build or a capital increase is allowed is decided by [`RELEASE-GATE.md`](RELEASE-GATE.md); this runbook only covers **how** to operate.

---

## 1. Runtime directory layout

Always run the bot from a dedicated runtime directory, **never from the repository root**. Default relative paths (`events.jsonl`, `bot.log`) are resolved from the working directory, so running from the repo root mixes test runs with real sessions and makes the record unusable.

```text
~/pumpfun-runtime/<instance>/      # one directory per wallet / capital stage
├── .envrc                         # secrets, chmod 600, never committed
├── configs/<instance>.json        # bot config (see RELEASE-GATE.md §3.3 for the canary)
└── data/                          # status snapshot, audit trail, events, logs, replay captures
```

Point every output file into `data/` explicitly:

```bash
export PUMPFUN_STATUS_PATH=data/bot_status.json
export PUMPFUN_AUDIT_LOG_PATH=data/audit_trail.jsonl
export PUMPFUN_EVENT_LOG_PATH=data/events.jsonl
export PUMPFUN_BOT_LOG_PATH=data/bot.log
```

All variables are documented in [`../ENVIRONMENTAL-VARIABLES.md`](../ENVIRONMENTAL-VARIABLES.md).

## 2. Preflight checks

- The wallet is a **dedicated hot wallet** holding only the capital allowed for the current stage ([`RELEASE-GATE.md` §3.1](RELEASE-GATE.md#31-stages)). Profits above that are moved to a cold wallet by hand, or by the profit sweep (§5.6, FEAT-42) once it has passed its drill.
- `PUMPFUN_PRIVATE_KEY` comes from `.envrc` or a secret manager, never from a tracked file; `.envrc` is `chmod 600` (`stat -f "%Sp %N" .envrc` shows `-rw-------`).
- `PUMPFUN_RPC_URL` (and `PUMPFUN_RPC_URLS` if pooling), `PUMPFUN_STREAM_URL` (key-free) and `PUMPFUN_STREAM_API_KEY` are set. Without a stream URL the bot connects to the offline stub `http://127.0.0.1:10000` and sees no market events. Do not rely on `PUMPFUN_GEYSER_ENDPOINT` yet: without a real gRPC transport it falls back to WebSocket (BUG-55, FEAT-39).
- The config keeps the features listed in [`RELEASE-GATE.md` §3.5](RELEASE-GATE.md#35-features-that-must-stay-off-until-proven) disabled.
- `PUMPFUN_ALERT_PROVIDER` is set only when its webhook/token secrets are present; send a test alert. Unattended runs depend on alerts: the bot alerts on start and stop, after `degradation_alert_minutes` (default 5) of stream or RPC degradation, on a new reconciliation gap and with the daily summary (§5.5).
- The release you are about to run is a tagged version that passed the release gate.

## 3. Startup procedure

1. `cd` into the runtime directory and load the environment (`direnv allow` or `source .envrc`).
2. Start the bot:
   ```bash
   pumpbot --config configs/<instance>.json            # interactive terminal UI
   pumpbot --config configs/<instance>.json --headless # under systemd/tmux/nohup
   ```
   Add `--paper-trade` for the paper pilot or `--dry-run` for a smoke test.
3. Check the startup logs: logger initialized, configuration printed (mode `live` / `paper` / `dry-run` is what you expect), health state initialized, startup reconciliation finished.
4. Confirm `data/bot_status.json` is created and shows the expected state and positions.
   Check the run provenance stamp (FEAT-68) is the build and config you meant to run, and copy it into the release record:
   ```bash
   jq '.run_provenance | {package_version, git_commit, git_dirty, mode, config_path, config_file_sha256, fee_launch_bps, cost_env}' data/bot_status.json
   sha256sum configs/<instance>.json     # must equal config_file_sha256
   ```
   `git_dirty: true` means the checkout the bot runs from has modified tracked files: stop and pin a clean tag before any run whose result will be used. `fee_launch_bps` other than 125 means the on-chain fee schedule changed (BUG-138); `null` means it could not be read.
5. Confirm `data/audit_trail.jsonl` receives state and trade entries.

## 4. Normal runtime checks

At least twice a day, and after any alert:

```bash
jq '{state, health_ok, risk_killed, active_positions: (.active_positions | length)}' data/bot_status.json
pumpfun-audit --path data/audit_trail.jsonl --limit 20
pumpfun-events --path data/events.jsonl --tail      # live diagnostic stream
ps -o pid,rss,etime,comm -p "$(pgrep -f pumpbot)"   # memory and uptime
```

Watch for: reconnect loops, stale-stream or RPC-error health flags, the circuit breaker engaging, growing exit-retry queue, RSS growing steadily.

## 5. Shutdown, incidents and rollback

### 5.1 Orderly shutdown / emergency stop
- Send `SIGINT` (Ctrl+C) or `SIGTERM`. Confirm the bot writes a final snapshot and audit events before it exits.
- To stop **new buys** but keep managing open positions, use the operator pause (§5.5) instead of a shutdown.
- If behaviour is wrong, stop immediately; do not try to fix it while it trades.

### 5.2 Incident response
1. **Halt** the process.
2. **Freeze state:** copy `data/` to `incidents/<timestamp>/` before anything else touches it.
3. **Check the wallet on-chain:** SOL balance and every token account; compare against `active_positions` in the snapshot. Sell any untracked tokens by hand if needed.
4. **Find the cause:** last valid state transition and trade in the audit trail; matching events in `events.jsonl`; replay the session from the replay capture if one was recorded.
5. **Log it:** open or update an entry in [`BUGS.md`](../../../dev/BUGS.md) and, if it was a missed assumption, a rule in the `AGENTS.md` Learnings Log.
6. **Restart** only in `--paper-trade` mode until the fix is released and the release gate passes again. Apply the stage rules in [`RELEASE-GATE.md` §3.6](RELEASE-GATE.md#36-stop-triggers-any-stage).

### 5.3 Daily wallet reconciliation
Required every day of the live canary, recommended afterwards.

```bash
# On-chain SOL balance (lamports) at the start of the day (keep it for --start-balance)
curl -s "$PUMPFUN_RPC_URL" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getBalance","params":["<wallet-pubkey>"]}' | jq '.result.value'

# Net PnL for the day: gross, fees, Jito tips, rent, net, win rate, per exit reason
pumpfun-audit pnl --path data/audit_trail.jsonl --date-from <YYYY-MM-DD> --date-to <YYYY-MM-DD> --group-by reason

# Wallet vs. audit trail: every trade signature, lost/phantom positions and the
# whole-wallet change since the start balance. Exit code 1 means a gap.
pumpfun-audit reconcile --path data/audit_trail.jsonl --wallet <wallet-pubkey> \
  --date-from <YYYY-MM-DD> --date-to <YYYY-MM-DD> --start-balance <SOL at start of day>
```

Since Sprint 24B (FEAT-49) every trade record carries `signature`, `fee_sol`, `priority_fee_sol`, `tip_sol`, `rent_sol`, `costs_sol`, `gross_pnl_sol`, `net_pnl_sol` and `cash_flow_sol`, and the daily breaker runs on net PnL. `cost_source` says where the costs came from: `transaction_meta` (read from the confirmed transaction), `modelled` (paper mode, or a live trade whose transaction could not be read) or `none` (records written before Sprint 24B; live sells measured from the wallet delta, which is already net of fee and tip). `reconcile` skips paper trades. Each run stores its result in `data/reconcile_status.json` (next to the audit trail), and the running bot shows it on the dashboard as `Reconciliation` (`GAP` in red, `STALE` after 36 h). Full exits close the token account and refund its rent (BUG-96), so a closed position shows a negative `rent_sol`.

Record: wallet Δ SOL, audit realized PnL, the gap between them, closed trades, fees and Jito tips. The gap must stay within the tolerance in [`RELEASE-GATE.md` §3.4](RELEASE-GATE.md#34-stage-1--daily-reconciliation-and-exit-criteria); a larger gap is an incident (§5.2).

Under a supervisor, run it on a timer instead (§8: `pumpfun-reconcile.timer` at 23:40 UTC, or cron with `deploy/pumpfun-reconcile.sh`). The running bot reads the stored result, alerts once on each new `GAP` and puts the last result in the daily summary. `audit` `sweep` records (§5.6) are counted in the whole-wallet check, so a profit sweep is not a gap.

### 5.4 Rollback
1. Stop the bot (§5.1) and freeze `data/` (§5.2 step 2).
2. Reinstall the previous tagged version (`git checkout v<prev> && pip install -e .` in the runtime copy; releases are private tags only, never PyPI).
3. Start in `--paper-trade` for at least one hour, confirm the snapshot restores cleanly, then resume at the previous capital stage.
4. Note the rollback in the release record of the failed version.

### 5.5 Operator pause and unattended alerts (Sprint 24D, FEAT-50)

**Pause new buys without a restart.** `SIGUSR1` toggles the pause:

```bash
kill -USR1 "$(jq .pid data/bot_status.json)"   # or: systemctl kill -s USR1 pumpbot
```

While paused the bot opens nothing (no buys, no capital rotation) but keeps managing every open position: exits, the exit retry queue and the circuit breaker run as normal. The dashboard shows `Buying: PAUSED (reason, minutes)`; `bot_status.json` carries `buying_paused` and `operator_pause`; each change is an `operator_pause` audit record and an alert. The pause **survives restarts** (a supervisor restart never resumes buying by itself); send `SIGUSR1` again to resume. Use it before maintenance, when an alert needs investigating, or to let positions run off before a stop.

**Cumulative loss cap (BUG-128).** When the loss from the reference equity passes `max_cumulative_drawdown_pct`, the bot liquidates (if `auto_liquidate_on_circuit_breaker`) and sets this pause itself (reason `cumulative loss cap`). Find out why before resuming: resuming with `SIGUSR1` resets the cap, so it is measured again from the equity at that moment. A deposit raises equity above the reference and loosens the cap; pause and resume (`SIGUSR1` twice) after topping up the wallet to measure from the new balance.

**Alerts an unattended operator gets** (provider from §2; delivery never blocks trading, BUG-110):

| Alert | When | Config |
|---|---|---|
| `bot started (… pid N …)` / `bot stopped (…)` | every start and stop; repeated starts mean the supervisor is restarting it | always |
| `ALERT stream degraded for Nm` / `ALERT rpc degraded for Nm` and `RECOVERED …` | the stream breaker is tripped or no message for `health_check_timeout_seconds`, or no RPC endpoint is healthy, for longer than the threshold; once per outage | `degradation_alert_minutes` (default 5; 0 = off) |
| `ALERT reconciliation GAP for <wallet>` | a new `reconcile_status.json` result reports a gap | always |
| Daily summary | once per UTC day at the configured hour: net / gross PnL, fees, tips, rent, trades, win rate, expectancy, session net, wallet, breaker, drawdown, reconciliation, buying state; also written to the audit trail as `daily_summary` | `daily_summary_alert` (default on), `daily_summary_hour_utc` (default 0) |
| `profit sweep: …` / `ALERT profit sweep failed` | each sweep (§5.6) | `profit_sweep_*` |

The summary covers the period since the previous summary (the difference of the persisted session totals), so restarts do not lose or double-count trades. A first start waits for the next slot.

### 5.6 Profit sweep to a cold wallet (FEAT-42, off by default)

```json
"profit_sweep_enabled": true,
"profit_sweep_destination": "<cold wallet public key>",
"profit_sweep_hot_floor_sol": 0.25,
"profit_sweep_min_sol": 0.05,
"profit_sweep_interval_seconds": 3600
```

Every interval the bot moves the wallet's SOL above the floor to the cold wallet in one system transfer (with compute-budget instructions, no Jito tip). The floor is never below `reserve_balance_sol + max_total_exposure_sol + 0.01`, so trading is never starved; less than `profit_sweep_min_sol` above the floor is left alone. The sweep holds the trade lock, so no buy spends the balance meanwhile.

- **Fail-fast config:** the bot refuses to start if the sweep is on and the destination is missing, invalid or the trading wallet itself, or if the minimum or interval is not positive.
- **Books:** each sweep is a `sweep` audit record (`signature`, `amount_sol`, `fee_sol`, `cash_flow_sol`, `destination`, `dry_run`). The daily breaker's baseline drops by the amount (a withdrawal is not a drawdown); the fee is booked as a cost. `pumpfun-audit reconcile --start-balance` subtracts live sweeps. Session net PnL is unaffected.
- **Paper / dry-run:** the transfer is simulated against the paper wallet (`dry_run_sweep_…` signatures), which is how the drill (§7) is run.
- **Failure:** an RPC error or an unconfirmed transfer alerts `ALERT profit sweep failed`, records `last_error` (dashboard: `Profit sweep: ERROR`) and books nothing; check the signature in the error on-chain before the next interval.

### 5.7 Trade-feed circuit breaker (PumpPortal API key funds, BUG-116)

PumpPortal meters token-trade data against the API key's linked wallet (0.01 SOL per 10,000 messages) and refuses `subscribeTokenTrade` once that wallet holds less than 0.02 SOL. The bot then opens the trade-feed circuit breaker:

- one alert, `ALERT trade-feed circuit breaker OPEN …`, saying the key's wallet has probably run out of funds when the key had worked earlier in the run;
- dashboard `Trade feed: REFUSED (key funds?)`, `bot_status.json` → `trade_feed_breaker.open: true`;
- no new buys (`require_trade_feed`); held positions keep exiting on the 1 s curve refresh.

**Action:** top up the PumpPortal key's wallet. Only the balance above 0.02 SOL pays for messages, so keep the run's expected use on top of that floor (two launch-mode bots used about 0.0024 SOL an hour in rc.7; [`COSTS.md` §3.2](../../../dev/COSTS.md#32-pumpportal-trade-data)). No restart is needed: every `trade_feed_probe_seconds` (default 300 s) the bot retries. A connection that has already refused is not asked again (PumpPortal did not accept a top-up on it, BUG-156): the bot closes it (`trade-feed breaker open: reconnecting the stream …` in the events, `trade_feed_breaker.reconnects` in `bot_status.json`), and the fresh connection resubscribes the held coins and probes. Once PumpPortal confirms a subscription or trade data arrives, the breaker closes: `trade-feed circuit breaker CLOSED` is sent, buying resumes, and the dashboard shows `Trade feed: ok`, `Last status: monitoring active tokens` and the CLOSED notice as `Last event`. A reconnect alone never closes it. If the key itself changed, update `PUMPFUN_STREAM_API_KEY` and restart.

```bash
jq '.trade_feed_breaker | {open, refusals, reconnects, next_probe_at, last_confirmed_at}' data/bot_status.json
```

### 5.8 RPC and stream outages (BUG-145 to BUG-151)

Every price, paper fill and sell goes through the RPC pool. In the rc.5 launch-mode run two bots shared one Helius key; the key stopped answering at 07:01 UTC and both bots carried on blind for an hour (§26 of [`BUGS.md`](../../../dev/BUGS.md#26-rc5-paper-run-findings-2026-10-25)). What the bot does now when the RPC fails:

- **The breaker stops traffic.** An endpoint that rate limits (HTTP 429) or fails three times in a row gets no requests for 1 s, then 2, 4 … up to `rpc_pool_circuit_breaker_cooldown_seconds` (60 s) while it keeps failing, with one probe request when each wait ends. Requests made meanwhile fail at once without being sent (`RpcPoolUnavailableError`, counted as `rejected_requests`).
- **No buys** while every endpoint is open (`last_event` "buy blocked: no healthy RPC endpoint", `entry_refusals.rpc_unavailable`). Exits keep trying.
- **New curves get time to appear.** A launch's curve account reaches the RPC a few hundred milliseconds after the create event; a buy re-reads it every 0.25 s for up to `entry_curve_wait_seconds` (3 s) before refusing it (`curve_missing`). `entry_curve_wait` in the status shows how long fills waited; raise the setting if `curve_missing` is more than a few percent of buy attempts (BUG-154).
- **No invented paper fills.** A paper buy whose curve read fails is refused (`curve_unreadable`), as a live buy would be; so is a paper sell, which goes to the exit retry queue and is retried as the same exit (BUG-152, BUG-153). A coin whose create event already shows a full curve (410.88 SOL market cap) is never bought (`complete_at_create`), and a complete curve at the fill is refused (`curve_complete`).
- **Graduated positions** are priced from their PumpSwap pool only. While the pool can't be read the position is marked `price_stale` (dashboard `… SOL (stale)`), the read is retried after 2 s doubling to 60 s, and `bot.log` gets a warning naming the cause (`PumpSwap pool for … unreadable (n tries): …`).
- **Record-only polls** (launch sample, post-exit, reject sample, discovery) wait while no endpoint is open or for 30 s after any rate limit (`watch_list.stats.observation_polls_deferred`).
- **Stream silence**: the PumpPortal socket is pinged every `stream_heartbeat_seconds` (20 s; 0 = off) and dropped and reconnected after twice `health_check_timeout_seconds` (120 s) without a message (`No WebSocket message for 120s: the connection is stale; reconnecting`); trading still pauses after 60 s of silence, as before. "Cannot write to closing transport" is logged at INFO and reconnects like a remote close. Neither needs a restart any more.

**Capacity.** Give **each bot its own RPC key**, and add at least one fallback endpoint: `PUMPFUN_RPC_URLS="<primary>,<fallback>"` ([`ENVIRONMENTAL-VARIABLES.md`](../ENVIRONMENTAL-VARIABLES.md)). Startup warns when a bot has a single endpoint. Launch mode holds up to `max_active_positions` coins; the refresh reads them all in one call per `position_refresh_seconds`, and each graduated coin adds two calls per pool read. Check the provider plan's request-per-second and monthly credit limits against `requests_by_method` over a few minutes before a long run.

```bash
# Endpoint health, the cause of the last failures and which calls carry the load
jq '.rpc_pool_telemetry | {healthy_endpoints, rejected_requests, requests_by_method,
    endpoints: [.endpoints[] | {label, state, rate_limited_count, consecutive_failures,
    open_streak, last_success_time, last_rate_limited_time}]}' data/bot_status.json
# Entries refused, by cause
jq '.entry_refusals' data/bot_status.json
# How filled buys found their curve; curve_missing above counts launches still missing (BUG-154)
jq '.entry_curve_wait' data/bot_status.json
grep -E "unreadable|rate limited|One RPC endpoint|connection is stale" data/bot.log | tail
```

**When it happens:** data recorded while `healthy_endpoints` is 0 is not a valid paper sample; note the window when archiving and leave it out of the verdict. If a 429 body says the plan's credits are used up (`max usage reached` or similar), the key will not recover by waiting: switch the bot to another key and restart.

## 6. Paper pilot procedure

Stage 0 of the live capital gate. Exit criteria: [`RELEASE-GATE.md` §3.2](RELEASE-GATE.md#32-stage-0--paper-pilot-exit-criteria).

1. Create a fresh runtime directory (§1) for the pilot so its files start empty.
2. Use the same config you intend to run live, with `"paper_trade": true`, and enable replay recording so the session can be replayed later:
   ```bash
   pumpbot --config configs/<instance>.json --paper-trade --headless --record-replay data/replay_capture.jsonl
   ```
3. **First 48 hours:** check stream connectivity and reconnects, RSS and CPU, and that the snapshot updates (§4).
4. **During volatile hours:** confirm entry/exit alerts arrive, dynamic slippage and exit retries behave, and paper fills look plausible against on-chain prices.
5. **Continue to 72 hours** without restarting. Run the drills in §7 on a separate paper instance, not on the pilot itself, so uptime is not reset.
6. Summarise: uptime, peak RSS, number of entries and exits by reason, breaker trips, simulated PnL. Put the summary in the release record.

### 6.1 Replay parity and tuning on captures (Sprint 24C)

Run these on a **copy** of the capture, from a second runtime directory, never against the running pilot's files.

1. **Parity check** (after Stage 0, and again on the first Stage 1 canary days):
   ```bash
   pumpfun-replay --path data/replay_capture.jsonl --config configs/canary.json \
     --compare-audit data/audit_trail.jsonl --mode summary
   ```
   Exit code 0 means the replay's net PnL is within tolerance of the audit trail. Explain every "exit differs", "live only" and "replay only" row in the release record before trusting replay for tuning. Live fills at executed prices and real (dynamic) tips, so small gaps are expected. From rc.4 the replay models the circuit breaker and starts from the paper wallet (FEAT-66): a halted paper day halts in replay too, and the replay summary's `circuit_breaker.locks` should match the paper run's `circuit_breaker` events. Compare a pre-rc.4 result only with `--no-circuit-breaker --initial-cash 100`.
2. **Exit attribution:** `pumpfun-audit pnl --group-by reason` (live) and the replay `--mode trades` ledger (`reason`, `hold_seconds`) show which exits earn and which give money back. The replay summary's `entry_rejections` shows which risk limit blocked entries.
3. **Tune** only once parity passes, on at least two days of capture, with the split on a day boundary:
   ```bash
   pumpfun-optimize --dataset data/replay_capture.jsonl --config configs/canary.json \
     --method genetic --train-split 0.5 --seed 7 --export-config configs/canary-tuned.json
   ```
   Fitness is net of modelled costs. Promote the tuned config only if its **test** (out-of-sample) score beats the canary config's, and only through a fresh Stage 0 run (`RELEASE-GATE.md` §3). The exported file masks any credential in URLs (BUG-102), so keep endpoints in the environment.

### 6.2 24 h capture run

A paper run whose only job is to record trade flow with the funded API key, so the entry confirmation (TODO Sprint 24A) and exits can be tuned by replay. It is **not** a Stage 0 run and its PnL is not evidence of anything.

`configs/capture.json` is the canary config with these changes:

| Key | Capture | Canary | Why |
|---|---|---|---|
| `paper_trade` | `true` | `false` (set by `--paper-trade`) | The file can never trade live by accident |
| `paper_starting_balance_sol` | `2.0` | default (0.25) | A 0.25 SOL paper wallet hits the breaker within hours |
| `max_daily_drawdown_pct` | `0.5` | `0.10` | Keep recording all day |
| `max_cumulative_drawdown_pct` | `0.0` (off) | default (0.30) | Keep recording across days (BUG-128) |
| `max_active_positions` / `max_total_exposure_sol` | `5` / `0.05` | `2` / `0.03` | More tokens with trade data per hour |
| `stagnant_timeout_seconds` | `120` | `45` | Trade data past 45 s, so replay can compare both timeouts |
| `profit_ratchet_ratio` | `0.0` | default (0.50) | The ratchet floor (BUG-127) would halt buys after a small winning stretch; a capture keeps buying |

Run it from the runtime directory into its own folder (the `.envrc` paths point at `data/`):

```bash
mkdir -p capture
PUMPFUN_STATUS_PATH=capture/bot_status.json \
PUMPFUN_AUDIT_LOG_PATH=capture/audit_trail.jsonl \
PUMPFUN_EVENT_LOG_PATH=capture/events.jsonl \
PUMPFUN_BOT_LOG_PATH=capture/bot.log \
pumpbot --config configs/capture.json --paper-trade --headless \
  --record-replay capture/replay_capture.jsonl
```

Type all four path variables: the v0.2.3 capture was started without the `PUMPFUN_STATUS_PATH` line, so it restored (and sold) a position from `data/bot_status.json` and wrote its status there. The second line of `capture/bot.log` must name `capture/bot_status.json` (or say nothing was restored).

In the first minutes check that `capture/bot.log` has "Successfully subscribed to keys", `Trade feed` is `ok`, and `capture/replay_capture.jsonl` holds `buy`/`sell` market trades, not only creates. Watch `trade_feed_breaker` (§5.7) and `mayhem_rejections` in the status file. Afterwards run §6.1 against `capture/` and replay with `configs/canary.json` as well, so the 45 s and 120 s timeouts can be compared on the same data.

### 6.3 Confirmed entries: capture → Stage 0 → Stage 1 at 0.02 SOL (v0.3.0, Phase 4c)

From v0.3.0 the repository ships `configs/capture.json` and `configs/canary.json` with `entry_mode: "confirmed"` ([`STRATEGY-PIVOT.md`](../../../dev/STRATEGY-PIVOT.md)). Copy both into the runtime `configs/` (keep the v0.2.x files as `*.v0.2.json` for rollback, §5.4). Each step starts only if the one before passed; record every result in `STRATEGY-PIVOT.md` §6.

0. **Before a new run.** Archive the previous run folders (`runtime/archive/paper-<tag>/capture/` and `.../pilot/`; `run-paper.sh` refuses a non-empty folder), pin `runtime/pumpfun-trading` to the new tag and reinstall it into the runtime venv, and copy `configs/capture.json`, `configs/canary.json`, `configs/pregrad_pilot.json` and `configs/verdict_rules.json` into the runtime `configs/`. After each run starts, check its `run_provenance` in the status file (§3 step 4).
1. **Capture (48 h from rc.3, paper).** Run `configs/capture.json` as in §6.2. One day was too few trades to tell a 0.0001 SOL-per-position edge from noise or to test the time-of-day effect ([`STRATEGY-PIVOT.md` §6.10](../../../dev/RESULTS.md#610-v030-rc2-capture-and-pilot-momentum-no-go-stop-092-adopted-2026-10-21)). Checks while it runs:
   - dashboard `Watch list: N watched, S/20 subscribed`: N stays ≤ `watch_max_mints` (300) and S ≤ `watch_max_trade_subscriptions`;
   - `watch_list.stats` in `capture/bot_status.json`: `watched` and `promoted` grow, `poll_errors` stays near 0, `dropped_not_pump_fun` / `dropped_non_standard` are counted, not bought;
   - no `watch_poll_failed` events for more than a few minutes (`pumpfun-events --path capture/events.jsonl --tail`), no loop stalls (`Last status` keeps changing);
   - PumpPortal message count well below the v0.2.3 capture (only promoted and held mints are subscribed);
   - from rc.2: `capture/replay_capture.jsonl` holds `event: "curve_poll"` rows (`source` `watch`, `position`, `entry_fill`, `shadow_fill`; about 1 KB/s) and `event: "shadow_entry"` rows for the config's `shadow_variants` (eight in rc.3); `watch_list.near_graduation` stays ≤ `near_graduation_max_mints` (50) and `watch_list.stats.shadow_skipped` near 0 (FEAT-58).
2. **Replay gate.** Replay the new capture with `configs/canary.json` **unchanged**:
   ```bash
   PUMPFUN_JITO_TIP_LAMPORTS=25000 pumpfun-replay --path capture/replay_capture.jsonl \
     --config configs/canary.json --initial-cash 2.0 --mode summary
   ```
   Go only if `net_pnl_sol` > 0 and `entries_from` is `confirmed`. From rc.4 this replay also runs canary's circuit breaker (10% daily limit, ratchet floor, 30% cumulative cap; FEAT-66), as Stage 1 would: read `circuit_breaker` in the summary, and treat a cumulative-cap trip as NO-GO. If not, do not start Stage 0: re-tune on this capture, then wait for a third one to confirm.

   **Read-out (rc.2 captures on).** The recorder rotates the capture (`replay_capture.jsonl.1.gz` is the newest archived part), so first join the parts, oldest first, into one file and read that:
   ```bash
   (for f in $(ls -r capture/replay_capture.jsonl.*.gz); do gzcat "$f"; done
    cat capture/replay_capture.jsonl) > capture/full_capture.jsonl
   C=capture/full_capture.jsonl
   pumpfun-replay --path $C --config configs/capture.json --tip-lamports 0 \
     --compare-audit capture/audit_trail.jsonl --mode summary       # parity first
   pumpfun-replay --path $C --config configs/capture.json \
     --shadow-report --split-at mid                                  # shadow variants
   pumpfun-audit pnl --path capture/audit_trail.jsonl --group-by strategy
   pumpfun-audit pnl --path capture/audit_trail.jsonl --group-by hour   # time of day
   pumpfun-audit cuts --path capture/audit_trail.jsonl --strategy momentum --split-at mid \
     --keep 'top_buyer_share<0.3' --keep 'wallet_diversity>=0.3' \
     --keep 'early_holder_pct<=0.25' --keep 'early_holders<=8'      # FEAT-56 / FEAT-61 inputs
   pumpfun-replay --path $C --config configs/canary.json \
     --sweep stop_loss=0.85,0.9,0.92,0.95                             # stop-loss check (§6.8)
   pumpfun-replay --path $C --config configs/canary.json \
     --wallet-scores --validate-path archive/paper-v0.3.0rc2/capture/full_capture.jsonl  # FEAT-54
   pumpfun-audit pnl --path pilot/audit_trail.jsonl --group-by strategy  # pre-graduation pilot
   # rc.3 record-only inputs (no CLI yet; jq over the joined captures and trails):
   jq -c 'select(.event=="observation_end" and .source=="reject_sample")
          | {mint, cause, peak_real_sol}' $C                          # screen-rejected sample
   jq -c 'select(.event=="observation_start" and .source=="reject_sample")
          | {mint, reject_reasons}' $C                                # ... and why each was rejected
   jq -c 'select(.event=="observation_end" and .source=="discovery")
          | {mint, cause, first_real_sol, peak_real_sol}' pilot/full_capture.jsonl  # discovered curves (join pilot/ as above)
   jq -c 'select(.type=="trade") | .payload | select(.exit_metrics)
          | {mint, reason, exit_metrics}' capture/audit_trail.jsonl   # stop crossings vs fills
   # rc.5 record-only inputs (FEAT-72): all launches and what happened after each exit
   jq -c 'select(.event=="observation_start" and .source=="launch_sample")
          | {mint, created_at, creator, creator_buy_sol}' $C          # sampled launches
   jq -c 'select(.event=="curve_poll" and .source=="launch_sample")
          | {mint, timestamp, market_cap_sol}' $C                     # ... their curves from creation
   jq -c 'select(.event=="curve_poll" and .source=="post_exit")
          | {mint, timestamp, market_cap_sol, exit_market_cap_sol, exit_reason}' $C  # after each sell
   # FEAT-73 record-only input: every graduated coin's PumpSwap pool for 4 h,
   # and sampled launches followed past 15 min until they graduate or fade
   jq -c 'select(.event=="observation_end" and .source=="launch_sample" and .extended)
          | {mint, cause, observed_seconds, peak_real_sol}' $C       # followed to graduation?
   jq -c 'select(.event=="observation_start" and .source=="graduation")
          | {mint, migrated_at, pool, held}' $C                       # graduations followed
   jq -c 'select(.event=="curve_poll" and .source=="graduation")
          | {mint, timestamp, x: (.market_cap_sol / 410.88), pool_sol}' $C  # move since graduation
   ```
   Compare the sample's `peak_real_sol` and `cause: "complete"` share per rejection reason with the watched mints' (`curve_poll` rows with `source: "watch"`); a cap is worth relaxing only if its rejects do better on this capture **and** the next. For the stops, compare `trade_feed_cross_ratio`, `refresh_cross_ratio` and `fill_ratio` on `stop_loss` exits: a trade-feed trigger is worth building only if the feed crosses first and materially above the fill. While the runs are up, `watch_list.reject_sample`, `watch_list.discovery` and the `discovery_scan_errors` / `observation_poll_errors` counters in `bot_status.json` should look sane (lists below their caps, errors near 0); a rising `discovery_scan_errors` means the Pump.fun API query changed.
   A variant or rule counts only if it beats the random cut in both halves, on this capture **and** the one before; set the tip variables as for the capture, and record every result in `STRATEGY-PIVOT.md` §6. `--compare-audit` agrees only when the config sets `paper_exit_slippage_bps` (BUG-126): on trails written before rc.3 paper sells took no slippage, so replay comes out about 1% per exit below paper.
3. **Stage 0 (72 h, paper)** with `configs/canary.json --paper-trade` and `--record-replay`, per §6 and `RELEASE-GATE.md` §3.1. Before it starts, record the rule hash in the release record (`pumpfun-audit verdict --path /dev/null --rules configs/verdict_rules.json --json | jq -r .rules_sha256`) and do not touch `configs/verdict_rules.json` until the run ends. Judge it with the pre-registered rule, per lane and per position, never per sell (FEAT-67):
   ```bash
   pumpfun-audit verdict --path pilot/audit_trail.jsonl --rules configs/verdict_rules.json --strategy momentum
   ```
   Exit code 0 (GO) with an unchanged hash is the Stage 0 profit criterion; `pumpfun-audit pnl --group-by strategy` stays the breakdown. The same command judges the capture run and the pre-graduation pilot (`--strategy pre_graduation`), as evidence only.
4. **Stage 1 (live canary)** with `configs/canary.json` on the dedicated hot wallet: 0.02 SOL buys, ≤ 2 positions, 0.05 SOL exposure (`RELEASE-GATE.md` §3.3). Exit criteria: ≥ 100 trades, net > 0, daily reconciliation clean (§5.3).

**Tip experiment.** Replay already shows the tip is small next to the edge on this lane (0 / 25k / 50k / 100k lamports: +0.139 / +0.132 / +0.124 / +0.109 SOL over the v0.2.3 day). What replay cannot show is landing. During Stage 0 and the first canary days compare `PUMPFUN_JITO_TIP_LAMPORTS` 0 (direct RPC, `PUMPFUN_USE_JITO=false`), 25,000 and 50,000 for at least one day each, and keep the lowest tip whose buys land within the `paper_entry_delay_seconds` assumption (1.5 s) and whose net per position does not drop. Record landing time and net per position for each setting.

Entries and exits can be tested apart. `PUMPFUN_JITO_ENTRY_TIP_LAMPORTS` and `PUMPFUN_JITO_EXIT_TIP_LAMPORTS` set a fixed tip for buys or sells only (unset = the shared tip; `0` = that side goes over plain RPC with no tip). A late entry only costs a skipped buy (drift guard), while a late stop loss sells lower, so also try entry `0` with exit 25,000 and 50,000. Paper costs and `pumpfun-replay` read the same variables, so set them for the replay too. Record landing time per side.

**Pre-graduation lane (FEAT-53).** It runs from the same poller on watched and held curves, but stays `enable_pre_graduation_harvesting: false` in `canary.json`. To test it, run `configs/pregrad_pilot.json` as a separate 72 h paper instance (own runtime folder and paths as in §6.2, e.g. `pilot/`, with `--record-replay pilot/replay_capture.jsonl`) and judge the `pre_graduation` row of `pumpfun-audit pnl --group-by strategy`. The pilot turns the lane on, sets `watch_max_trade_subscriptions: 0` (no momentum buys, no billed trade feed for watched mints) and keeps up to 100 coins past the 10 min watch TTL in the near-graduation set (`near_graduation_*`: ≥ 50% of the curve and still growing, polled every 6 s until they near the 75% entry band, dropped after 5 min without growth or 1 h in total). Its capture can be replayed with the same config, since the lane now runs on the recorded `curve_poll` rows. Enable it in the canary only after that pilot is net positive (`RELEASE-GATE.md` §3.5). Confirmed-mode exits apply to these positions too, so check how many `stagnant_buy_flow` exits fire before the tranches.

**Graduated positions (BUG-123).** A held coin whose curve completes is sold into its PumpSwap pool (`enable_pumpswap_exit`, on by default). Look for `graduated while held` in the events and `bonding_curve_graduated` sells in the audit trail; `awaiting pool <mint>` on the dashboard means the pool was not readable yet and the next position refresh retries. Paper prices these exits from the pool. Before any lane that can reach graduation runs with real capital, send one live PumpSwap sell at the smallest size and reconcile it. A third source checks held mints against the Pump.fun API every `graduation_backfill_seconds` (30 s); a hit shows as `graduation backfill: <mint> completed (missed by stream)` in the events and `watch_list.stats.graduation_backfill` in `bot_status.json`. Regular hits mean the stream is missing migrations: check reconnects and `subscribeMigration`.

### 6.4 Slow-lane data recorder (FEAT-65 phase 0, from rc.3)

Record-only data for the slow lane ([`PROPOSED-FEATURES.md` FEAT-65](PROPOSED-FEATURES.md#feat-65-slow-lane-daily-bar-trend-on-liquid-solana-tokens-via-jupiter)), in case the rc.3 Pump.fun lanes are NO-GO too. It is a separate process: no wallet, no transactions, nothing shared with `pumpbot`, so it cannot change the rc.3 runs. Both APIs are used keyless (no Jupiter API key needed).

1. Start the quote recorder with the rc.3 runs, in its own folder, and leave it running until the rc.3 verdict (weeks of samples are worth more than 48 h):
   ```bash
   cd runtime && mkdir -p slow_lane
   pumpfun-recorder --jupiter-quotes --tokens configs/slow_lane_tokens.json \
     -o slow_lane/jupiter_quotes.jsonl          # every 300 s; Ctrl-C / SIGTERM stops it cleanly
   ```
   With `PUMPFUN_RPC_URL` (or `PUMPFUN_RPC_URLS`) in the environment it also samples priority fees (about 13 RPC calls per 5 min); add `--no-fee-samples` to skip them. Under a supervisor, run it as a second unit next to `pumpbot` (§8), with the same `.envrc`.
2. Download the bar history once (about 15 min for the default list):
   ```bash
   pumpfun-recorder --backfill-bars --tokens configs/slow_lane_tokens.json -o slow_lane/bars.jsonl
   ```
   The public API serves about 6 months; re-run it monthly into a new file to extend the series and de-duplicate on `mint`, `timeframe`, `timestamp` when reading.

   For a multi-year history use Binance's public spot klines (keyless; each `<SYMBOL>USDT` pair from its listing; for the default list about 3 min, 315,000 bars, one ~100 MB file):
   ```bash
   pumpfun-recorder --backfill-bars --bar-source binance --tokens configs/slow_lane_tokens.json \
     -o slow_lane/binance_bars.jsonl
   ```
   Expect SOL from August 2020, RAY from August 2021, JTO and BONK from late 2023, JUP, PYTH and WIF from early 2024, ORCA from December 2024. mSOL and jitoSOL have no Binance pair (`"binance": null` in the token list); a token without a pair shows as `Pairs missing` and is skipped. Binance prices are the centralised-exchange market in USDT, not the Solana pool a swap would fill in: use them for the trend signal and keep the Jupiter quotes for costs. Keep the two venues in separate files (`bars_in_sol` only divides bars of the same `venue`). If the run stops with `Binance refused this host` (HTTP 451 = restricted region, 403 = firewall, 418 = IP ban after rate limiting), try another network or `--bar-base-url https://api.binance.com` (which itself answers 451 in some regions, e.g. the US); after a 418, wait before retrying. A few missing hours (SOL 10, RAY 3 since listing) are Binance's own trading outages, not download errors. Top up later with `--bar-since YYYY-MM-DD` into a new file. A backfill always writes one file: unlike the quote recorder, it does not rotate at 50 MB.
3. Health checks while it runs: rows keep arriving, and errors stay rare.
   ```bash
   tail -n 1 slow_lane/jupiter_quotes.jsonl | jq '{timestamp, event, symbol}'
   jq -c 'select(.event=="quote_error") | {symbol, side, size_sol, status}' slow_lane/jupiter_quotes.jsonl | tail
   jq -c 'select(.event=="quote" and .side=="sell") | {symbol, size_sol, round_trip_cost_bps}' \
     slow_lane/jupiter_quotes.jsonl | tail -n 30            # round-trip cost per token and size
   ```
   Many `status: 429` rows mean the keyless limit changed: raise `--request-gap` or `--quote-interval`. Edit the token list only between runs, and keep the edited file with the data.
4. Reading the data (BUG-139). The sell leg is quoted a pacing gap after the buy leg, so each `round_trip_cost_bps` also holds the price move in between; sell rows carry `buy_gap_seconds` and `buy_gap_slots`. Judge costs on the distribution, `pumpfun_trading.services.slow_lane.round_trip_cost_summary(rows)` (median and quartiles per token and size), never on one row. Bars are USD (`currency: "usd"`): GeckoTerminal's from each token's top pool as chosen when the backfill ran, Binance's from the `<SYMBOL>USDT` pair (`quote_asset: "USDT"`, closed bars only); `bars_in_sol(rows)` re-prices them against SOL's own bar from the same venue, the baseline a SOL wallet has to beat.

### 6.5 Cross-chain market recorder (FEAT-74, from rc.8)

Record-only data on the coins the Pump.fun lanes never see: other Solana launchpads (Meteora, Raydium LaunchLab, PumpSwap pools), Base and BSC, and old coins when they start trending ([`FEATURES.md` §44](../FEATURES.md#44-cross-chain-market-recorder-feat-74)). It is a separate process with no wallet and no RPC: GeckoTerminal and DexScreener, keyless and paced, so it costs no Helius credits and cannot change the paper runs.

1. Start it next to the bots, in its own window, and leave it running:
   ```bash
   cd runtime && mkdir -p market
   .venv/bin/pumpfun-recorder --market -o market/market.jsonl     # Ctrl-C / SIGTERM stops it cleanly
   ```
   Defaults: Solana, Base and BSC (`--market-chains solana,base,bsc,eth` adds Ethereum); every new pool followed except Pump.fun curves, of which 10% are (`--market-sample solana:pump-fun=0.1`); trending (5 min, 1 h) and top 24 h volume lists every 5 minutes (`--market-no-lists` turns them off). The follow list is saved to `market/state.json` every minute, so a restart resumes it; the first minutes after a start fill the lists at GeckoTerminal's pace (about one chain a minute).
2. Health checks: a `market_stats` row every 10 minutes.
   ```bash
   jq -c 'select(.event=="market_stats") | {following, by_chain, snapshots, errors, rate_limited, discovery_gaps, token_matched}' market/market.jsonl | tail -n 3
   ```
   `rate_limited` climbing means a free limit changed: stop it and raise the gaps in `services/market_recorder.py`. `discovery_gaps` counts discovery passes where every page was new (Solana launches outran four pages a minute); a few a day are fine. `following` should settle in the thousands, below the 20,000 cap (`--market-max-followed`).
3. Disk: about 600 bytes a row, roughly 1 GB a day before compression; parts rotate at 100 MB and are gzipped, and all 300 are kept (no age limit). Move old parts into `archive/` with the paper runs they belong to.
4. Reading the data:
   ```bash
   jq -c 'select(.event=="market_pool" and .followed) | {chain, source, dex, pool, created_at, liquidity_usd}' market/market.jsonl   # what was picked, and why
   jq -c 'select(.event=="market_snapshot") | {timestamp, chain, pool, age_seconds, price_usd, liquidity_usd, txns}' market/market.jsonl
   jq -c 'select(.event=="market_end") | {chain, pool, source, cause, followed_seconds}' market/market.jsonl
   ```
   A rule counts only on what it could have seen when it fired: join snapshots to `market_pool` rows by `chain` + `pool`, enter at the first snapshot that meets the rule, use the later snapshots for the outcome, and include the pools that ended `dead`. Rows with `matched: "token"` price the coin's most liquid pair (`pair_address`), not the pool GeckoTerminal listed.

## 7. Incident drills

Run these in paper mode before Stage 1 and after any release that touches lifecycle, persistence or execution.

### 7.1 Scripted risk drills (FEAT-69)

Four drills that are hard to force on a running instance are scripted. `pumpfun-drill` (or `pumpfun ops drill`) builds a real paper bot per drill in a scratch folder, drives its risk code on a simulated clock and wallet, and checks the outcome. It opens no stream, signs nothing with a real key (a throwaway keypair), replaces the balance RPC and the sell executor with fakes, captures alerts instead of sending them, and ignores the operator's `PUMPFUN_*` environment. It takes seconds:

```bash
pumpfun-drill --report releases/v0.3.0rc4-drills.json      # all four; exit 1 if any fails
pumpfun-drill --only midnight_lock --workdir /tmp/drills   # one drill, keep its files
pumpfun-drill --list
```

| Drill | What it does | Pass condition |
|---|---|---|
| `cumulative_cap` | 1.0 SOL wallet loses 14% on day 1 and 12% more on day 2 (25% cap, 15% daily limit); restart; 25 h later; `SIGUSR1` | Day 1 within the daily limit; day 2 trips the cumulative cap (BUG-128) and pauses buying with reason `cumulative loss cap`; paused and capped after a restart and after the 24 h lock expires; `SIGUSR1` resumes and moves the reference to the current equity; two `operator_pause` audit records |
| `midnight_lock` | 20% loss at 23:55 UTC (15% limit, 24 h hard lock); check at 00:05 and 24 h later | Emergency lock; `lockout_until` 24 h after the lock; still locked after the 00:00 rollover; released 24 h after the lock with the baseline at the equity then |
| `balance_rpc_down` | Live-mode bot (throwaway key, no transactions possible) whose balance RPC fails, then answers 0.20 SOL | No day baseline from the simulated start balance; breaker "waiting for the first live wallet balance read"; equity guard refuses the buy; status file shows no baseline; after recovery the baseline is 0.20 SOL (BUG-130) |
| `slow_tier_sell` | Tier-1 sell held in flight while the exit stack emits tier 1 again (the 60 s pending latch has run out) | First sell `True`, repeat `False`; one executor call; tier 1 marked executed with half the tokens left (BUG-140) |

Attach the `--report` JSON to the release record. The scripted drills cover the breaker paths; the manual drills below still have to run on the paper deployment itself, because they test the process, the supervisor, the stream and the alert channel.

### 7.2 Manual drills

| Drill | How | Pass condition |
|---|---|---|
| Orderly shutdown | `SIGINT`, then `SIGTERM` on a second run | Final snapshot and audit events written; clean exit |
| Kill and restart | `kill -9` while a position is open, then restart | Position, cost basis, tier state and exit-retry queue restored; no duplicate buy |
| Stream loss | Block the stream host (firewall or wrong URL) for 2 minutes | Reconnect with backoff; health flags clear on recovery without a restart (BUG-46) |
| RPC failure | Point `PUMPFUN_RPC_URL` at a dead endpoint, or use a pool with one bad member | Failover or degraded health; no position removed as "dust" (BUG-35) |
| Circuit breaker | Set a very low `max_daily_drawdown_pct` on a paper instance | New buys blocked; liquidation as configured; alert sent |
| Forensics | Pick a closed trade and trace it through audit, events and replay | Entry reason, exits and PnL reconstructable from files alone |
| Operator pause | `kill -USR1 <pid>` with a position open, wait for its exit, restart, then `kill -USR1` again | No new buys while paused; the open position still exits; pause survives the restart; `operator_pause` audit records and alerts for both changes |
| Profit sweep | Paper instance with `profit_sweep_enabled`, a test destination and a paper wallet above the floor | One `sweep` audit record and alert; paper wallet at the floor minus the fee; no circuit-breaker trip; nothing swept below the floor |
| Supervisor restart | Under systemd / launchd (§8), `kill -9` the bot process | Restarted within the restart delay; `bot started` alert; snapshot restored; pause state kept |
| Degradation alert | Stream drill above for longer than `degradation_alert_minutes` | One `ALERT stream degraded` and one `RECOVERED stream` alert |
| Trade-feed breaker | Paper instance without `PUMPFUN_STREAM_API_KEY` (or with an empty-wallet key), until the first buy | One `trade-feed circuit breaker OPEN` alert naming the key's funds; no new buys; `trade_feed_breaker.open` true; still open after a reconnect |

## 8. Supervised deployment and hardening (Sprint 24D)

Run the headless bot under a process supervisor so a crash or reboot does not quietly end a pilot or canary. Templates lived in `deploy/` (retired with the pumpbot runtime; in the history at tag `v0.3.0rc8`) (operator slice of FEAT-46; a container image is still planned):

| File | Purpose |
|---|---|
| `deploy/pumpbot-run.sh` | Wrapper: `cd` into the runtime directory, source `.envrc` (with or without `export`), `exec pumpbot --config … --headless …`. Exits 78 if `.envrc` is missing |
| `deploy/systemd/pumpbot.service` | systemd unit: `Restart=always` after 15 s, at most 5 starts in 30 min, no restart on exit 78, 60 s graceful stop, writes only inside the runtime directory, `MemoryMax=1G` |
| `deploy/systemd/pumpfun-reconcile.{service,timer}` + `deploy/pumpfun-reconcile.sh` | Daily `pumpfun-audit reconcile` at 23:40 UTC, before the 00:00 UTC summary (§5.3) |
| `deploy/launchd/com.pumpfun.pumpbot.plist` | macOS user agent: `KeepAlive`, restarts at least 30 s apart, logs into `data/` |

Setup (systemd shown; launchd steps are in the plist header):

1. Copy `pumpbot-run.sh` (and `pumpfun-reconcile.sh`) into the runtime directory, `chmod 700`; keep `.envrc` `chmod 600`.
2. Edit the unit: `User`, the paths, `PUMPBOT_BIN` (the venv's `pumpbot`), `PUMPBOT_CONFIG`, and `PUMPBOT_EXTRA_ARGS` (`--paper-trade --record-replay data/replay_capture.jsonl` for Stage 0; drop `--paper-trade` for the live canary).
3. `sudo systemctl daemon-reload && sudo systemctl enable --now pumpbot`; check `journalctl -u pumpbot -f` and the `bot started` alert.
4. For the timer set `PUMPBOT_WALLET` (public key only) in `pumpfun-reconcile.service`, then `systemctl enable --now pumpfun-reconcile.timer`.

Operate: pause `systemctl kill -s USR1 pumpbot` (§5.5), stop `systemctl stop pumpbot` (SIGTERM, graceful). `pumpbot` exits **1** when its stream loop ends without a shutdown request and **0** after SIGINT/SIGTERM, so the supervisor restarts real failures only (launchd's `KeepAlive` restarts on any exit). Each restart sends a `bot started` alert; after 5 starts in 30 min systemd gives up, which is the signal to investigate (§5.2) rather than keep trading.

**Log retention:** the bot rotates `bot.log`, the audit trail and replay captures itself (`PUMPFUN_LOG_*`, `PUMPFUN_AUDIT_*`, `PUMPFUN_REPLAY_*`, [`../ENVIRONMENTAL-VARIABLES.md`](../ENVIRONMENTAL-VARIABLES.md)); cap the journal with `SystemMaxUse=` in `journald.conf`, and on macOS the launchd `data/launchd.*.log` files with `pumpfun ops prune` or newsyslog.

Hardening checklist:

- Run under a minimal-privilege user, one runtime directory per instance.
- Secrets in a secret manager or `chmod 600` `.envrc`; never in configs, unit files or the repo (the unit only holds the wallet's **public** key).
- Hot wallet separate from treasury; sweep profits to cold storage (§5.6) or by hand.
- Keep `data/` on a monitored, backed-up filesystem; configure log retention (`pumpfun ops prune` limited to the logs directory).
- Supervisor restart limits as above, so a crash loop does not keep trading.

## 9. Command reference

| Goal | Command |
|---|---|
| Lint / format / types | `nox -s lint`, `nox -s format`, `nox -s mypy` |
| Full test suite with coverage gate | `nox -s tests` |
| Live bot | `pumpbot --config configs/<instance>.json [--headless]` |
| Paper pilot | `pumpbot --config configs/<instance>.json --paper-trade --headless` |
| Pause / resume new buys | `kill -USR1 "$(jq .pid data/bot_status.json)"` |
| Scripted risk drills | `pumpfun-drill --report <file>` (§7.1) |
| Paper go / no-go | `pumpfun-audit verdict --path <trail> --rules configs/verdict_rules.json --strategy <lane>` (§6.3) |
| Supervised bot | `systemctl {status,stop,restart} pumpbot`, `journalctl -u pumpbot -f` |
| Status snapshot | `jq . data/bot_status.json` |
| Audit trail | `pumpfun-audit --path data/audit_trail.jsonl --summary` |
| Diagnostic events | `pumpfun-events --path data/events.jsonl --tail` |
| Replay a capture | `pumpfun-replay --path data/replay_capture.jsonl` |
| Record market data | `pumpfun-recorder --help` |
| Slow-lane quotes / bars (FEAT-65) | `pumpfun-recorder --jupiter-quotes`, `pumpfun-recorder --backfill-bars` (§6.4) |
| Cross-chain market data (FEAT-74) | `pumpfun-recorder --market` (§6.5) |

Full flag reference: [`../CLI-COMMANDS.md`](../CLI-COMMANDS.md).

## 10. Related documentation

- [`RELEASE-GATE.md`](RELEASE-GATE.md) – release checklist and live capital gate.
- [`BUGS.md`](../../../dev/BUGS.md) – defect tracker.
- [`TODO.md`](TODO.md) – sprint backlog, including Sprint 24A (paper pilot and live canary).
- [`../RISK.md`](../RISK.md) – risk controls and circuit breakers.
- [`../USER-GUIDE.md`](../USER-GUIDE.md) – configuration and onboarding.
