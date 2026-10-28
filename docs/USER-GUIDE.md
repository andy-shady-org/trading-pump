# User guide

trading-pump plugs Pump.fun graduates into trading-core. It follows every
coin that leaves its Pump.fun bonding curve for a PumpSwap pool, reads the
pool on chain, decides in one lane (`pumpswap_momentum`) whether to buy, and
simulates the fill against the pool with every fee (paper). Live orders are
refused until the lane has passed paper ([dev/RELEASE-GATE.md](dev/RELEASE-GATE.md)).

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
* **The lane.** One minute after the migration, a coin still at 1.2× its
  first pool price is bought; out at +20%, −15% or after 30 minutes
  ([STRATEGY.md](STRATEGY.md)).
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

### 4.2 Paper trading (FEAT-76)

```bash
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json
```

The dashboard (trading-core `docs/TERMINAL-UI.md`) shows prices in µSOL and
the module's rows: PumpPortal connection and migrations, graduates followed,
pool reads, healthy RPC endpoints, capture rows, and the lane's rule. The
run writes `data/paper/status.json`, `audit.jsonl`, `events.jsonl`,
`trading-core.log` and `capture.jsonl`.

Before a run that counts, fix the verdict rule and record its hash
([dev/RUNBOOK.md §3](dev/RUNBOOK.md#3-a-paper-run-that-counts)).

### 4.3 Judge it

```bash
trading-core-audit pnl --path data/paper/audit.jsonl --group-by reason
trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict_rules.json
```

### 4.4 Replay a capture

```bash
trading-pump replay --config configs/paper.json \
    --capture data/capture/capture.jsonl* --out data/replays/try-1
```

The real engine and module on a replay clock ([CLI.md](CLI.md#trading-pump-replay)).
Use it to check a change or try a variant on recorded data, not to prove a
rule on the data it came from.

### 4.5 Research recorders

`trading-pump record --market` (cross-chain pools) and `--jupiter-quotes` /
`--backfill-bars` (slow-lane data) run in their own process
([CLI.md](CLI.md#trading-pump-record)).

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
| `pumpfun-recorder --market / --jupiter-quotes / --backfill-bars` | `trading-pump record ...` (same flags) |
| `pumpfun-recorder --ws-url ...` (stream capture) | not ported; the module's capture records the graduation rows |
| `pumpfun-replay` | `trading-pump replay` for graduation captures; the launch / momentum replay, sweeps and `--compare-audit` are not ported |
| `pumpfun-optimize`, `pumpfun-arb`, `pumpfun-drill` | not ported |
| `PUMPFUN_*` variables | six are read ([ENVIRONMENT.md](ENVIRONMENT.md)); the rest warn with their replacement |
| the bot config file | engine keys + `module_settings` ([CONFIGURATION.md](CONFIGURATION.md#from-a-pumpbot-config)) |

Files:

* **Captures** keep pumpfun-trading's row shape; rc.8 graduation rows replay
  as they are.
* **Audit trails and event logs** are readable by the trading-core tools.
* **A pumpbot status file is not restored**: its positions have pumpbot's
  shape. Close positions before switching, or start a new data folder.

## 6. Day to day

* **Health.** No entries while market data is stale, the feed or the RPC is
  degraded, or the breaker is locked; the dashboard says which. A degraded
  condition alerts after `degradation_alert_minutes`
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
| [STRATEGY.md](STRATEGY.md) | The lane, its prices and costs, how it is judged |
| [CONFIGURATION.md](CONFIGURATION.md) | Every `module_settings` key, and the pumpbot key map |
| [ENVIRONMENT.md](ENVIRONMENT.md) | The six variables, and what replaced the rest |
| [CLI.md](CLI.md) | Every command |
| [FEATURES.md](FEATURES.md) | What ships, and what became of every pumpbot feature |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the module implements trading-core's contract |
| [dev/RUNBOOK.md](dev/RUNBOOK.md) | Operating a run, incidents, the research recorders |
| [dev/RELEASE-GATE.md](dev/RELEASE-GATE.md) | Release checklist and the live capital gate |
| [dev/STRATEGY-PIVOT.md](dev/STRATEGY-PIVOT.md) | The evidence: every result since v0.2.3 |
| [dev/TODO.md](dev/TODO.md), [dev/BUGS.md](dev/BUGS.md), [dev/TESTING.md](dev/TESTING.md) | Maintainers |
