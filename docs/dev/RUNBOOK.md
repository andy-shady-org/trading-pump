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
5. **Log it:** open or update an entry in [`BUGS.md`](BUGS.md) and, if it was a missed assumption, a rule in the `AGENTS.md` Learnings Log.
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

**Action:** top up the PumpPortal key's wallet (keep well above 0.02 SOL; a busy run uses roughly 0.01 SOL per 10,000 trade messages). No restart is needed: the bot sends a probe subscription every `trade_feed_probe_seconds` (default 300 s) and, once PumpPortal confirms it or trade data arrives, closes the breaker, sends `trade-feed circuit breaker CLOSED` and resumes buying. A reconnect alone never closes it. If the key itself changed, update `PUMPFUN_STREAM_API_KEY` and restart.

```bash
jq '.trade_feed_breaker' data/bot_status.json
```

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
   Exit code 0 means the replay's net PnL is within tolerance of the audit trail. Explain every "exit differs", "live only" and "replay only" row in the release record before trusting replay for tuning. Live fills at executed prices and real (dynamic) tips, so small gaps are expected.
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
| `max_active_positions` / `max_total_exposure_sol` | `5` / `0.05` | `2` / `0.03` | More tokens with trade data per hour |
| `stagnant_timeout_seconds` | `120` | `45` | Trade data past 45 s, so replay can compare both timeouts |

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

## 7. Incident drills

Run these in paper mode before Stage 1 and after any release that touches lifecycle, persistence or execution.

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

Run the headless bot under a process supervisor so a crash or reboot does not quietly end a pilot or canary. Templates live in [`deploy/`](../../deploy/) (operator slice of FEAT-46; a container image is still planned):

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
| Supervised bot | `systemctl {status,stop,restart} pumpbot`, `journalctl -u pumpbot -f` |
| Status snapshot | `jq . data/bot_status.json` |
| Audit trail | `pumpfun-audit --path data/audit_trail.jsonl --summary` |
| Diagnostic events | `pumpfun-events --path data/events.jsonl --tail` |
| Replay a capture | `pumpfun-replay --path data/replay_capture.jsonl` |
| Record market data | `pumpfun-recorder --help` |

Full flag reference: [`../CLI-COMMANDS.md`](../CLI-COMMANDS.md).

## 10. Related documentation

- [`RELEASE-GATE.md`](RELEASE-GATE.md) – release checklist and live capital gate.
- [`BUGS.md`](BUGS.md) – defect tracker.
- [`TODO.md`](TODO.md) – sprint backlog, including Sprint 24A (paper pilot and live canary).
- [`../RISK.md`](../RISK.md) – risk controls and circuit breakers.
- [`../USER-GUIDE.md`](../USER-GUIDE.md) – configuration and onboarding.
