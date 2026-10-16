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
```

All variables are documented in [`../ENVIRONMENTAL-VARIABLES.md`](../ENVIRONMENTAL-VARIABLES.md).

## 2. Preflight checks

- The wallet is a **dedicated hot wallet** holding only the capital allowed for the current stage ([`RELEASE-GATE.md` §3.1](RELEASE-GATE.md#31-stages)). Profits above that are moved to a cold wallet by hand (until FEAT-42).
- `PUMPFUN_PRIVATE_KEY` comes from `.envrc` or a secret manager, never from a tracked file; `.envrc` is `chmod 600` (`stat -f "%Sp %N" .envrc` shows `-rw-------`).
- `PUMPFUN_RPC_URL` (and `PUMPFUN_RPC_URLS` if pooling) and `PUMPFUN_STREAM_URL` are set. Without a stream URL the bot connects to the offline stub `http://127.0.0.1:10000` and sees no market events. Do not rely on `PUMPFUN_GEYSER_ENDPOINT` yet: without a real gRPC transport it falls back to WebSocket (BUG-55, FEAT-39).
- The config keeps the features listed in [`RELEASE-GATE.md` §3.5](RELEASE-GATE.md#35-features-that-must-stay-off-until-proven) disabled.
- `PUMPFUN_ALERT_PROVIDER` is set only when its webhook/token secrets are present; send a test alert.
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
# On-chain SOL balance (lamports) at the start and end of the day
curl -s "$PUMPFUN_RPC_URL" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getBalance","params":["<wallet-pubkey>"]}' | jq '.result.value'

# Realized PnL and trade counts for the day from the audit trail
pumpfun-audit --path data/audit_trail.jsonl --date-from <YYYY-MM-DD> --date-to <YYYY-MM-DD> --summary
```

The audit realized PnL is **gross** until Sprint 24B (FEAT-49): it has no fee, priority-fee, tip or rent fields. Until then, sum the day's costs from the transaction signatures (`getTransaction` → `meta.fee`, plus the Jito tip transfer) and subtract them yourself. Sprint 24B replaces this section with `pumpfun-audit pnl` and `pumpfun-audit reconcile`.

Record: wallet Δ SOL, audit realized PnL, the gap between them, closed trades, fees and Jito tips. The gap must stay within the tolerance in [`RELEASE-GATE.md` §3.4](RELEASE-GATE.md#34-stage-1--daily-reconciliation-and-exit-criteria); a larger gap is an incident (§5.2).

### 5.4 Rollback
1. Stop the bot (§5.1) and freeze `data/` (§5.2 step 2).
2. Reinstall the previous tagged version (`pip install "pumpfun-trading==<prev>"` or `git checkout v<prev> && pip install .`).
3. Start in `--paper-trade` for at least one hour, confirm the snapshot restores cleanly, then resume at the previous capital stage.
4. Note the rollback in the release record of the failed version.

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

## 8. Deployment hardening checklist

- Run under a minimal-privilege user, one runtime directory per instance.
- Secrets in a secret manager or `chmod 600` `.envrc`; never in configs or the repo.
- Hot wallet separate from treasury; sweep profits to cold storage regularly.
- Keep `data/` on a monitored, backed-up filesystem; configure log retention (`pumpfun ops prune` limited to the logs directory).
- Process supervisor (systemd, launchd or tmux + watchdog) with restart limits, so a crash loop does not keep trading. A container image is planned (FEAT-46).

## 9. Command reference

| Goal | Command |
|---|---|
| Lint / format / types | `nox -s lint`, `nox -s format`, `nox -s mypy` |
| Full test suite with coverage gate | `nox -s tests` |
| Live bot | `pumpbot --config configs/<instance>.json [--headless]` |
| Paper pilot | `pumpbot --config configs/<instance>.json --paper-trade --headless` |
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
