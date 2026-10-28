# TODO

Open work only. Finished items move to [`DONE.md`](DONE.md) under their
heading, with their CHANGELOG release; evidence and results go to
[`STRATEGY-PIVOT.md` §6](STRATEGY-PIVOT.md#6-results-log). Check a
completion against the code before ticking or moving it.

This list continues pumpfun-trading's. On 2026-10-28 its TODO was split by
owner: venue work stayed here, engine and platform work (Phase 5 and 6, the
Web UI, typed state, the control channel, persistence, the docs site, the
funding gate) moved to trading-core's `docs/dev/TODO.md`, and the work tied
to code that was not ported is listed under [Not ported](#not-ported) with
where to find it. The list as it stood is archived unchanged:
[archive TODO](../archive/pumpfun-trading/dev/TODO.md).

## Now / Next / Later

| When | Work | Where |
|---|---|---|
| **Now** | Close the migration: CI on 3.11–3.14, a paper run on the new stack, then retire pumpfun-trading | [Migration gate](#migration-gate-before-pumpfun-trading-is-deleted) |
| **Next** | FEAT-76: a fresh 72 h paper run with a pre-registered verdict; the fee tier checked against a real swap | [FEAT-76](#feat-76-pumpswap-post-graduation-momentum-lane) |
| **Then** | Only if the lane passes: the PumpSwap buy builder, reconcile, one live round trip, Stage 0 / Stage 1 | [Live gate](#live-gate-for-the-pumpswap-lane) |
| **Later** | Research read-outs (graduation paths, cross-chain, slow lane); a second venue only with evidence | [Research](#research-record-only) |

## Migration gate (before pumpfun-trading is deleted)

Done: the history import, the module and lane, 100% coverage on 3.14, the
docs split, the replay of the rc.8 graduation rows through the new stack
([STRATEGY-PIVOT §6.14](STRATEGY-PIVOT.md#614-feat-76-on-the-new-stack-the-rc8-graduations-replayed-through-trading-core-2026-10-28)).

- [ ] `nox` green on Python 3.11, 3.12, 3.13 and 3.14 locally and in CI (`tests.yml` matrix), plus `nox -s package` (the wheel ships no tests)
- [ ] trading-core's `feat/pumpfun-module-support` merged and tagged (the module needs `CLOSES_POSITION` on sells and `trading-core check` building the module); then pin `trading-core>=` that version in `pyproject.toml`
- [ ] A paper run of at least 24 h on the new stack with `configs/paper.example.json` (copied to the runtime folder): check after an hour that the capture's oldest row is the start time (BUG-157), `degraded` conditions stay clear, the dashboard rows move, and the capture replays with `trading-pump replay` to the same positions as the run (fills at the same readings, within the fee difference)
- [ ] Move the runtime data that is still wanted (rc.6 to rc.8 captures, analysis scripts, `runtime/archive/`) out of the pumpfun-trading checkout, if it lives there
- [ ] Then archive the pumpfun-trading GitHub repository (read-only) rather than deleting it; its history is in this repository already

## FEAT-76 PumpSwap Post-Graduation Momentum Lane

Done: the paper lane, the PumpSwap paper executor priced from the pool and
the fee config, the replay, the pre-registered verdict file
(`configs/verdict_rules.json`) ([FEATURES.md §3–§5](../FEATURES.md#3-the-pumpswap_momentum-lane-feat-76-paper)).
The rc.9 build with BUG-157 fixed is superseded: the capture here is pruned
by its own policy only.

- [ ] 72 h paper run on fresh data with `configs/paper.example.json` (signal 60 s, ratio 1.2, standard pool, TP +20%, stop −15%, 30 min hold, 0.02 SOL): record the verdict rule's sha256 and the run provenance before it starts; judge with `trading-core-audit verdict --rules configs/verdict_rules.json`; pass = the verdict's GO (≥ 100 positions, both halves positive, 90% interval above 0, positive without the best 3), and better than a random entry on the same graduates
- [ ] Run the same capture through `trading-pump replay` at 125 and 200 bps, and with `paper_entry_delay_seconds` 0 and 2: the result must hold at the fee the fee config actually charges
- [ ] Check the PumpSwap fee: read the fee config tier for a fresh graduate (market cap about 410 SOL) and compare it with the fee paid by real PumpSwap swaps of graduates in their first minutes (on-chain transactions, read-only); set `fee_bps_floor` or fix the tier selection if they differ. Until then every replay states its fee
- [ ] Optional, if the RPC budget allows: a 1 s fast phase for the first 3 minutes (`fast_poll_interval_seconds`), since the result moved with one reading of delay (§6.13)
- [ ] Market recorder before it can pick a venue: a sell-quote check per followed pool (Jupiter on Solana), coverage of Raydium LaunchLab / stonkfun / memefun pools (GeckoTerminal OHLCV or on-chain reads), and per-chain cost and gas at the trade size

## Live gate for the PumpSwap lane

Only after the FEAT-76 paper run passes. The staged gate is
[`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate).

- [ ] PumpSwap buy builder (`sdk/pumpswap_execution.py`) checked against real mainnet transactions, as the sell was (BUG-123): account order, the fee recipients, the creator vault, Token-2022; pinned to real account bytes in tests
- [ ] `LiveExecutor`: build, send (Jito or RPC), confirm, and return the `Fill` with costs from the transaction meta (`sdk/costs.py`); refuse wherever the paper fill refuses; never a fallback price
- [ ] One live PumpSwap sell at the smallest size before any lane relies on it with real capital (carried from Sprint 24H: the sell instruction is pinned to mainnet accounts, but no transaction from this code has landed)
- [ ] Port `reconcile` (pumpbot's `bot/reconcile.py`, `pumpfun-audit reconcile`) as the module's implementation of trading-core's reconciliation contract (trading-core TODO): on-chain Δ SOL against the audit trail's realized PnL, every full exit showing a negative rent cost (carried from Sprint 24B, *partly done read-only*: the cost parser reads rent refund, fee and priority fee correctly on third-party sells)
- [ ] One live round trip at the smallest size, reconciled
- [ ] Stage 0: 72 h paper with replay recording on the release build (rule hash recorded first); Stage 1: live canary on a dedicated hot wallet at 0.02 SOL, daily wallet reconciliation logged every canary day, every discrepancy in `BUGS.md` and fixed before continuing (carried from Sprint 24A)
- [ ] Tip experiment before Stage 1: 0 / 25k / 50k lamports per side, on landing rates (carried from Sprint 24E; tips were 83% of the separately listed costs at 0.01 SOL on the curve)
- **Acceptance (Stage 1, from Sprint 24A):** ≥ 100 closed trades, net PnL after fees, tips and rent positive, reconciliation gap within tolerance every day, 0 lost or double-sold positions. Only then raise capital (Stage 2).

## Research (record-only)

### Graduation tracking (FEAT-73)
Built and ported ([FEATURES.md §2](../FEATURES.md#2-graduation-tracking-feat-73)). Carried over:
- [ ] Run a 24 h capture (`configs/capture.example.json`); check the followed count stays below `max_mints` and the RPC credit use matches [`COSTS.md` §3.1](COSTS.md#31-helius-rpc-credits)
- [ ] Read-out: per graduate the path over 4 h relative to the graduation price (410.88 SOL), split into coins complete at creation, curve filled within 5 minutes and slower; how often a crash below 0.5× comes back above 1× / 2×; and whether any entry rule (after the first crash, after a new high, by pool SOL) beats PumpSwap costs in both halves of the run and the next. Record it in `STRATEGY-PIVOT.md` §6
- [ ] PumpSwap buys on any rule other than FEAT-76 only if that read-out finds one
- The read-out of the curve *before* graduation (launch sample joined to graduation rows) needs the launch sample, which was not ported; see [Not ported](#not-ported)

### Cross-chain market recorder (FEAT-74)
Built and ported (`trading-pump record --market`). Carried over:
- [ ] Run it for at least 72 h ([`RUNBOOK.md` §5](RUNBOOK.md#5-research-recorders)); check `market_stats` (no rate limits, few discovery gaps, `following` below the cap) and the disk use in the first day
- [ ] Read-out per chain and launchpad: what share of new pools reach 2× / 5× from their first snapshot and when, how many die within an hour, and what liquidity a 0.02-SOL-sized trade would meet
- [ ] Momentum read-out: for pools entering a trending or top-volume list, the move over the next 1 / 6 / 24 h from the first snapshot after entry; whether list rank, age or liquidity at entry separate the runs from the dumps, in both halves of the run and on a second run
- [ ] A buy path on another chain or launchpad only if a rule beats realistic costs (swap fees, gas, slippage at the snapshot liquidity) in both halves and on a second run. It would be a new trading-core module, not a lane here

### FEAT-65 slow lane, phase 0 data
Built and ported (`trading-pump record --jupiter-quotes` / `--backfill-bars`). Carried over:
- [ ] Walk-forward test of the §6.12 trend rules on the Binance history (`--backfill-bars --bar-source binance`, 2020–2026), in SOL terms with the measured costs, against a random-entry baseline and on at least two unseen periods; only if it passes, build the FEAT-65 backtester and lane (as a trading-core module or lane)

## Module and tooling

- [ ] Status rows: per-endpoint RPC latency and breaker state, Jito bundle status once live (carried from "Terminal dashboard" in the archived roadmap; the dashboard itself is trading-core's)
- [ ] A `trading-pump capture-summary` (or `trading-core-audit` filter) for graduation captures: graduates, standard share, readings per graduate, observation causes; today the read-out uses scripts and `jq`

## Ongoing

Standing practices, not ticked (carried over):
- Keep module boundaries explicit: streams in `streams/`, chain maths and transactions in `sdk/`, decisions in `strategies/`; nothing here renders or owns risk.
- Keep the CLI docs and examples current as the tooling changes.
- Add a replay or read-out mode when a strategy question needs one, as the old `--sweep`, `--shadow-scan` and `--wallet-scores` were.
- Report profit net of fees, priority fees, tips and rent, and reconcile it against the wallet before believing it.

## Not ported

Code that was in pumpfun-trading v0.3.0rc8 and was not brought onto
trading-core. It is all in this repository's history:
`git show v0.3.0rc8:pumpfun_trading/<path>` or `git checkout v0.3.0rc8 -- <path>`.
Their open items are in the [archived TODO](../archive/pumpfun-trading/dev/TODO.md)
under the sprint named. A port must bring the fix and the tagged test of every
bug listed for that code in [`BUGS.md`](BUGS.md#where-each-fix-lives-after-the-move-to-trading-core).

| What | Where it was | Why not ported | Open items it had |
|---|---|---|---|
| Launch-mode buying, entry filters (FEAT-75), launch sample and post-exit tracking (FEAT-72) | `bot/handlers/new_token.py`, `execution/`, `strategies/observation.py` launch-sample parts | NO-GO: about 25,000 paper trades rc.5 to rc.8, every setting negative (§6.13) | rc.5 data A/B re-run, launch-sample read-out, trade data for sampled launches (rc.5 Data); FEAT-75 A/B was closed 2026-10-28 |
| Confirmed momentum lane, watch list, order-flow signals (FEAT-07, FEAT-51, FEAT-52, FEAT-56/57/59/60/61) | `strategies/momentum.py`, `bot/handlers/`, `bot/run.py` | NO-GO (§6.10, §6.11); needs the PumpPortal trade feed | Sprint 24G (closed, NO-GO), FEAT-56 / 57 / 59 / 60 / 61 gates |
| Pre-graduation lane, near-graduation discovery (FEAT-25, FEAT-53) | `strategies/graduation.py`, `bot/handlers/watch.py` | NO-GO, cannot fire (§6.11) | Sprint 24H 72 h pilot (the PumpSwap sell item moved to the live gate above) |
| Smart-wallet discovery and copy trading (FEAT-06, FEAT-54) | `strategies/copy_trading.py`, `engines/wallets.py` | Copying every captured wallet lost (§6.8); needs the trade feed | Sprint 24I, all phases |
| Raydium sniping and swaps (FEAT-05) | `sdk/raydium*.py`, `bot/handlers/raydium.py` | Pump.fun migrates to PumpSwap (BUG-123) | none |
| Cross-venue arbitrage and back-running (FEAT-28, FEAT-40) | `strategies/arbitrage.py`, `execution/arbitrage.py`, `cli/arbitrage.py` | Never executable on real reserves (BUG-59, BUG-90) | FEAT-40 |
| Capital rotation and displacement (FEAT-24), tiered take profit, stagnation exits, dynamic slippage (FEAT-23) | `strategies/exits.py`, `strategies/decision.py`, `execution/policy.py` | Tied to the curve lanes; the core's `ExitRules` cover the FEAT-76 exits | none |
| Yellowstone Geyser transport (FEAT-01, FEAT-39) | `streams/geyser.py` | Never production-ready (BUG-55); latency not shown to cost entries | Sprint 24D optional FEAT-39; "Geyser event pipeline" (carried-over roadmap) |
| The PumpPortal trade feed, its breaker and stream recorder | `bot/trade_feed.py`, `bot/run.py`, `cli/record.py --ws-url` | The lane needs migrations only (free, keyless) | none |
| Replay engine, sweeps, shadow scan, parity, optimizer (FEAT-18, FEAT-27, FEAT-58, FEAT-66) | `engines/`, `cli/replay.py`, `cli/optimize.py` | Built around pumpbot's event replay; `trading-pump replay` drives the real engine instead | Sprint 24C phase 5 (tuning on live captures, per-filter attribution) |
| Scripted risk drills (FEAT-69) | `ops/drills.py`, `cli/drill.py` | Drove pumpbot's `TradingBot`; the breaker is trading-core's now | Sprint 24A / 24D drills: to be rebuilt on the core engine (trading-core TODO) |
| Reconcile, profit sweep (FEAT-42, FEAT-49 reconcile part) | `bot/reconcile.py`, `bot/sweep.py` | Live only; reconcile is ported with live execution (live gate above) | Sprint 24B mainnet verification (live gate above) |
| Supervisor templates (FEAT-46 operator slice) | `deploy/` | Ran `pumpbot`; trading-core's `docs/OPERATIONS.md` §6 has a systemd unit for `trading-core run --headless` | none |
| Golden replay of bot decisions | `tests/integration/test_golden_replay.py`, `test-data/` | Pinned pumpbot's decisions; the module's integration test and the replay of rc.8 rows take its place | none |
| Phase 5 Sprint 28c (`bot/run.py` below 800 lines) | `bot/run.py` | Obsolete: the file is gone (finding R1 closed by the split) | none |

Closed with the migration (not moved anywhere, recorded so nothing is lost):
the Phase 4b funding gate and the "definition of done" moved to trading-core
with the Web UI; `min_holder_count: 6` on an unseen capture (Sprint 24A) was a
launch-lane screen setting and is closed with it (reopen it if
`lane.screen_entries` is ever turned on); the 72 h graduation-only
capture on rc.9 (FEAT-76 phase 1) is replaced by the 72 h paper run above,
which records the same rows.
