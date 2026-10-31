# User guide

trading-pump plugs Pump.fun graduates into trading-core. It follows every
coin that leaves its Pump.fun bonding curve for a PumpSwap pool, reads the
pool on chain, decides in one of two lanes whether to buy
(`pumpswap_momentum` for standard graduations, `pumpswap_instant` for
instant ones), and simulates the fill against the pool with every fee
(paper). Live orders are refused: no lane has passed the paper stage of the
capital gate yet ([dev/RELEASE-GATE.md](dev/RELEASE-GATE.md#1-current-status)).

This repository continues **pumpfun-trading**: its history, bug record,
results log and documents are kept here (the old guides are in
[archive/pumpfun-trading](archive/pumpfun-trading/INDEX.md)). Everything
that was not specific to Solana (risk, the circuit breaker, accounting, the
audit tools, alerts, the dashboard) is now trading-core's.

## 1. Concepts in one minute

* **Graduation.** A Pump.fun coin trades on a bonding curve until about 85
  SOL has gone in; the curve then completes and the coin migrates to a
  canonical **PumpSwap** pool (a constant-product AMM). PumpPortal's free
  WebSocket announces each migration.
* **Graduation tracking.** The module follows every graduate's pool for 4 h
  (every 2 s for the first 5 minutes, then 10 s) and records every reading,
  whether it trades or not.
* **The lanes.** A *lane* is one entry rule with its own exits and its own
  verdict; every signal and position carries its lane's name as its
  `strategy`. Each graduate goes to at most one lane, by its first reading
  ([STRATEGY.md](STRATEGY.md)):
  * `pumpswap_momentum` (FEAT-76): a standard graduate (first market cap
    near 410.88 SOL) still at ≥ 1.2× its first pool price a minute after
    the migration is bought; out at +20%, −15% or after 30 minutes, or at
    the lane's own exits (`lane.exits`, FEAT-79).
  * `pumpswap_instant` (FEAT-78, off by default): an instant graduate (first
    reading 1,000–2,000 SOL market cap, 130–200 SOL in the pool) still at
    1.00–1.10× its first price a minute later is bought; out at +50%, −15%
    or after 30 minutes.
* **New pools** (FEAT-80, off by default): new PumpSwap pools that are not
  graduations, followed and recorded like graduates; no lane trades them.
* **Paper fills** are computed from the pool's reserves with the swap fee and
  the network costs, from a fresh read for every fill.
* **The engine** (trading-core) runs the loop: sizing, the risk gate, the
  circuit breaker, exits, net-PnL accounting, the audit trail, the status
  file, alerts, the dashboard.

## 2. Install

trading-core is private and installed first, next to this repository:

```bash
cd ~/projects/git/trading
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11–3.14
pip install -e trading-core
pip install -e "trading-pump[dev]"
trading-core modules          # → pumpfun, simulated (and polymarket if installed)
```

## 3. Credentials

Only credentials are environment variables ([ENVIRONMENT.md](ENVIRONMENT.md)).
For paper, an RPC endpoint is all you need; the public mainnet RPC works for a
short test:

```bash
export PUMPFUN_RPC_URL="https://<your-rpc>/?api-key=..."
export PUMPFUN_RPC_URLS="https://<fallback-rpc>/..."   # optional, recommended
trading-pump env                                        # names and states only
```

No private key and no PumpPortal key are needed for paper.

## 4. Run

### 4.1 Record only (graduation capture)

```bash
cp configs/capture.example.json configs/capture.json
trading-core run --config configs/capture.json --headless
```

The lane is off; every migration and pool reading goes to
`data/capture/capture.jsonl` (rotated, gzipped). Use this to collect data
for a new rule without trading.

### 4.2 Paper trading

```bash
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json
```

The example runs the standard lane only. To run both lanes, merge these
keys into your copy: the instant lane on, the standard lane with its own
exits, and the engine's `exits` emptied (or the engine's +20% take-profit
closes positions before a lane's +50%):

```json
"exits": {},
"module_settings": {
  "lane": {"exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.15, "max_hold_seconds": 1800}},
  "instant": {"enabled": true}
}
```

The dashboard (trading-core `docs/TERMINAL-UI.md`) shows prices in µSOL and
the module's rows: PumpPortal connection and migrations, graduates followed,
pool reads, healthy RPC endpoints, capture rows, and the lane's rule. The
run writes `data/paper/status.json`, `audit.jsonl`, `events.jsonl`,
`trading-core.log` and `capture.jsonl`.

Before a run that counts, fix one verdict rule per lane and record the
hashes in the run's record before the start
([dev/RUNBOOK.md §3](dev/RUNBOOK.md#3-a-paper-run-that-counts)).

### 4.3 Judge it

```bash
trading-core-audit pnl --path data/paper/audit.jsonl --group-by reason
trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict_rules.json
```

`configs/verdict_rules.json` judges `pumpswap_momentum`; for the instant
lane, copy it with `"strategy": "pumpswap_instant"` and judge each lane with
its own file.

### 4.4 Replay a capture

```bash
trading-pump replay --config configs/paper.json \
    --capture data/capture/capture.jsonl* --out data/replays/try-1
```

The real engine and module on a replay clock ([CLI.md](CLI.md#trading-pump-replay)).
Use it to check a change or try a variant on recorded data, not to prove a
rule on the data it came from.

### 4.5 Research recorders

`trading-pump record --jupiter-quotes` / `--backfill-bars` (slow-lane data)
run in their own process ([CLI.md](CLI.md#trading-pump-record)). The
cross-chain market recorder (`--market`) moved to trading-scout on
2026-10-30.

## 5. From pumpbot

| pumpbot | Now |
|---|---|
| `pumpbot --config F` | `trading-core run --config F` with `"module": "pumpfun"` |
| `pumpbot --headless` | `trading-core run --headless` |
| `pumpbot --dry-run` | `"mode": "paper"` (the default) |
| `SIGUSR1` pause | the same, in the engine |
| `pumpfun-audit pnl / cuts / verdict` | `trading-core-audit pnl / cuts / verdict` (old trails are read: `mint` and `*_sol` names are accepted) |
| `pumpfun-audit reconcile` | not ported yet (needed before live, [dev/TODO.md](dev/TODO.md)) |
| `pumpfun-events` | `trading-core-events` |
| `pumpfun-recorder --market` | trading-scout (the `scout` module, since 2026-10-30) |
| `pumpfun-recorder --jupiter-quotes / --backfill-bars` | `trading-pump record ...` (same flags) |
| `pumpfun-recorder --ws-url ...` (stream capture) | not ported; the module's capture records the graduation rows |
| `pumpfun-replay` | `trading-pump replay` for graduation captures; the launch / momentum replay, sweeps and `--compare-audit` are not ported |
| `pumpfun-optimize`, `pumpfun-arb`, `pumpfun-drill` | not ported |
| `PUMPFUN_*` variables | seven are read ([ENVIRONMENT.md](ENVIRONMENT.md)); the rest warn with their replacement |
| the bot config file | engine keys + `module_settings` ([CONFIGURATION.md](CONFIGURATION.md#from-a-pumpbot-config)) |

Files:

* **Captures** keep pumpfun-trading's row shape; rc.8 graduation rows replay
  as they are.
* **Audit trails and event logs** are readable by the trading-core tools.
* **A pumpbot status file is not restored**: its positions have pumpbot's
  shape. Close positions before switching, or start a new data folder.

## 6. Day to day

* **Health.** No entries while market data is stale or the breaker is
  locked. A degraded feed, RPC or RPC network shows on the dashboard with
  its cause and alerts after `degradation_alert_minutes`
  ([dev/RUNBOOK.md §4](dev/RUNBOOK.md#4-when-something-goes-wrong)).
* **Pause** with `kill -USR1 <pid>`; again to resume. Exits continue.
* **Stop** with `Ctrl-C` or `SIGTERM`. Open positions are kept in the status
  file and restored on the next start (unless `close_positions_on_shutdown`).
* **Alerts** go to Discord, Slack or Telegram via `TRADING_CORE_ALERT_*`.
* **Disk.** A graduation capture is about 1–2 M rows a day; check the oldest
  row after the first day (BUG-157's lesson).

## 7. Where everything else is

| Page | For |
|---|---|
| [STRATEGY.md](STRATEGY.md) | Both lanes, their prices and costs, how they are judged |
| [CONFIGURATION.md](CONFIGURATION.md) | Every `module_settings` key, and the pumpbot key map |
| [ENVIRONMENT.md](ENVIRONMENT.md) | The seven variables, and what replaced the rest |
| [CLI.md](CLI.md) | Every command |
| [FEATURES.md](FEATURES.md) | What ships, and what became of every pumpbot feature |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the module implements trading-core's contract |
| [dev/RUNBOOK.md](dev/RUNBOOK.md) | Operating a run, incidents, the research recorders |
| [dev/RELEASE-GATE.md](dev/RELEASE-GATE.md) | What is running now, the release checklist and the capital gate's stages |
| [dev/RESULTS.md](dev/RESULTS.md) | The evidence: every run, replay and study since v0.2.3, with its verdict |
| [dev/runs/](dev/runs/README.md) | One record per run: what it was for and how it ended |
| [dev/TODO.md](dev/TODO.md), [dev/BUGS.md](dev/BUGS.md), [dev/TESTING.md](dev/TESTING.md) | Maintainers |
