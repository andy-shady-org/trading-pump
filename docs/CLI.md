# Commands

Running the module is trading-core's job; trading-pump adds its own tools.

| Command | From | What |
|---|---|---|
| `trading-core run --config F` | trading-core | Run the engine with the module named in `F` (`"module": "pumpfun"`). `--headless` for supervised runs, `--live` for live mode |
| `trading-core check --config F` | trading-core | Validate a settings file and build the module, so a bad `module_settings` key fails here |
| `trading-core modules` | trading-core | List installed modules (`pumpfun` must be there) |
| `trading-core-audit pnl / cuts / verdict` | trading-core | Read an audit trail: net PnL by reason or strategy, random-cut check, pre-registered verdict |
| `trading-core-events` | trading-core | Query and tail diagnostic events |
| `trading-pump record ...` | here | Research recorders (also `trading-pump-recorder`) |
| `trading-pump replay ...` | here | Replay captures through the engine with the module |
| `trading-pump lane-rows ...` | here | Write captures as trading-core's strategy library rows, for `trading-core-lanes sweep` |
| `trading-pump env` | here | Which `PUMPFUN_*` variables are set (names only) |

The trading-core commands are documented in trading-core's `docs/CLI.md`,
`docs/AUDIT-TOOL.md` and `docs/TERMINAL-UI.md`. pumpbot's commands
(`pumpbot`, `pumpfun-replay`, `pumpfun-audit`, `pumpfun-drill`, ...) are in
the [archived manual](archive/pumpfun-trading/CLI-COMMANDS.md); the table in
[USER-GUIDE.md §5](USER-GUIDE.md#5-from-pumpbot) maps each to its
replacement.

## Running the module

```bash
cp configs/paper.example.json configs/paper.json   # edit, then:
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json        # dashboard
trading-core run --config configs/paper.json --headless   # under a supervisor
```

`Ctrl-C` (or `SIGTERM`) stops it cleanly: the module stops its feed and
poller, the capture is flushed, the status file written. `SIGUSR1` toggles
the operator pause (no new entries; exits go on). A restart restores open
positions and the day's breaker state from the status file.

## `trading-pump replay`

```bash
trading-pump replay --config configs/paper.json \
    --capture data/paper/capture.jsonl.3.gz data/paper/capture.jsonl.2.gz data/paper/capture.jsonl \
    --out data/replays/2026-10-30 [--fee-bps 125]
```

Plays one or more captures (plain or gzipped; rows are put in time order)
through a fresh trading-core engine with the module, on a simulated clock:

* migrations reach the tracker at their recorded time;
* due pools are answered with the latest recorded reading at or before the
  simulated time, never a later one (no look-ahead);
* the engine cycles every `cycle_seconds` with its real risk gate, exits,
  circuit breaker and net-PnL accounting;
* a paper buy waits `paper_entry_delay_seconds` of simulated time before it
  reads the pool; a fill (buy or sell) takes the recorded reading nearest
  that moment, up to 3 s after it, because a live fill reads the pool afresh
  and that read is not in the capture (BUG-164);
* the swap fee is fixed at `--fee-bps` a side (125 by default), because a
  capture does not record the fee tier at each moment. Run it at 200 as well:
  at 0.02 SOL a trade the result moves with the fee (RESULTS §6.14).

The engine and module settings come from `--config`, the same file a paper
run uses, with three changes: mode is paper, every file goes into `--out`
(`status.json`, `audit.jsonl`; no events, log file or capture), and the
daily summary is off. `--out` must be a new directory: a status file left by
an earlier replay would be restored into this one.

It prints the span, migrations, engine cycles, closed positions, win rate,
net PnL and costs, then the next command:

```bash
trading-core-audit pnl --path data/replays/2026-10-30/audit.jsonl --group-by reason
trading-core-audit verdict --path data/replays/2026-10-30/audit.jsonl --rules configs/verdict_rules.json
```

Exit code 0, or 2 when the config or a capture cannot be read or holds no
graduation rows. pumpfun-trading rc.8 captures have the same rows and replay
as they are.

A replay judges a rule on recorded data. On the data a rule was found on, it
checks the code, not the rule.

## `trading-pump lane-rows`

```bash
trading-pump lane-rows \
    --capture data/paper/capture.jsonl.3.gz data/paper/capture.jsonl.2.gz data/paper/capture.jsonl \
    --out data/lanes/rc11.jsonl.gz [--source graduation new_pool damm]
trading-core-lanes sweep --capture rc11=data/lanes/rc11.jsonl.gz --fee-bps 125 --stress-fee-bps 200 \
  --haircut-bps 50 --delay 1.5 --out data/sweeps/rc11
```

Writes one or more captures (plain or gzipped parts, in any order) as the
venue-neutral rows of trading-core's strategy library (its ADR-011,
FEAT-133), the rows `trading-core-lanes sweep --capture NAME=FILE` reads
([FEATURES §5.1](FEATURES.md#51-the-strategy-librarys-records-trading-core-feat-133-and-feat-117)):

* a `listing` per graduate (`kind: "graduation"`, at the migration), per
  new PumpSwap pool (at its creation, with its creator) and per DAMM v2 pool
  (at its activation, with its creator);
* a `reading` per pool read: the price the module prices with (SOL per
  whole token), the SOL in the pool as `liquidity`;
* no `trade` or `holders` rows: the captures hold no swaps by wallet and no
  holder snapshots.

`--source` picks which pools are written (default: all three); a sweep judges
one venue at a time, so write graduates and DAMM v2 pools to separate files.
`--out` must be a new `.jsonl` or `.jsonl.gz` file; it is written whole or
not at all. Rows come in capture order, not time order (the sweep sorts
them). The command prints how many rows of each kind it wrote, the rows it
skipped and why (a reading of a coin whose listing is not in the capture, a
reading before its listing, a coin whose decimals were not read, a drained
pool), and the rows that are not market data (`migration`,
`observation_end`, `damm_decimals`, `damm_end`, other runs' rows). It needs
a trading-core with the strategy library (`trading_core.lanes`).

## `trading-pump record`

Record-only research recorders, each in its own process next to the engine
(never inside it). No wallet, no transactions. One mode per run:

| Mode | What | Default output |
|---|---|---|
| `--jupiter-quotes` | FEAT-65 phase 0: Jupiter round-trip quotes (0.02 / 0.1 / 0.5 SOL), prices and priority-fee samples for a token list, every 5 minutes | `slow_lane/jupiter_quotes.jsonl` |
| `--backfill-bars` | FEAT-65 phase 0: daily / hourly OHLCV bars from GeckoTerminal (about 6 months) or Binance (`--bar-source binance`, since listing), then exit | `slow_lane/bars.jsonl` (`binance_bars.jsonl`) |

Without a mode it prints an error and exits 2.

Common options: `-o/--output` (path), `-d/--duration` (seconds),
`--batch-size` (rows per write, 50), `--flush-interval` (2 s).

`--market` (FEAT-74, the cross-chain market recorder) moved to trading-scout
on 2026-10-30; the flag now prints where it went and exits 2.

`--jupiter-quotes` / `--backfill-bars`: `--tokens` (token list JSON, default
`configs/slow_lane_tokens.json`'s list), `--quote-interval` (300 s),
`--quote-sizes` (`0.02,0.1,0.5`), `--request-gap` (2 s quotes, 6 s
GeckoTerminal, 0.5 s Binance), `--no-fee-samples` (skip
`getRecentPrioritizationFees`, otherwise taken when an RPC variable is set),
`--bar-timeframes` (`day,hour`), `--bar-source` (`geckoterminal` or
`binance`), `--bar-base-url`, `--bar-max-pages`, `--bar-since YYYY-MM-DD`
(Binance).

`PUMPFUN_JUPITER_API_KEY` moves the quotes to Jupiter's keyed host
([ENVIRONMENT.md](ENVIRONMENT.md)). Operating notes (pacing, rate limits,
disk use) are in [dev/RUNBOOK.md §5](dev/RUNBOOK.md#5-research-recorders).

## `trading-pump env`

```bash
trading-pump env
```

A table of the seven variables the module reads, each `set`, `set as <alias>`
or `unset`, with what it is for; then one warning per other `PUMPFUN_*`
variable that is set, naming what replaces it. Values are never printed.
