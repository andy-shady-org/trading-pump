# TODO

Open work only. Finished items move to [`DONE.md`](DONE.md) under their
heading, with their CHANGELOG release; evidence and results go to
[`RESULTS.md`](RESULTS.md#6-results-log), and a counted run's
pre-registration and read-out to its record in [`runs/`](runs/README.md).
Check a completion against the code before ticking or moving it. Capital
stages are numbered as in [`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate)
(1 paper, 2 live canary, 3 scale-up); items carried from pumpfun-trading say
which old stage they meant.

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
| **Now** | `ee-1` (FEAT-160 to FEAT-163, record-only on `v0.5.0`) runs to 2026-11-13 12:06 UTC; then its pre-registered replays and read-out, and the exploratory launch-and-dump features on its capture (the November roadmap) | [`runs/ee-1.md`](runs/ee-1.md) |
| **Next** | Close the migration: a capture that replays to its run's positions, the runtime data moved, pumpfun-trading archived | [Migration gate](#migration-gate-before-pumpfun-trading-is-deleted) |
| **Then** | Only if a PumpSwap lane is reopened with a new design that passes on new data: the PumpSwap buy builder, `LiveExecutor`, reconcile, one live round trip, then Stage 2 (live canary) | [Live gate](#live-gate-for-the-pumpswap-lane) |
| **Later** | Research read-outs (pools-1's new pools, graduation paths); a second migration source (FEAT-77); a second venue only with evidence (the slow lane was NO-GO, [RESULTS §6.15](RESULTS.md#615-feat-65-walk-forward-on-the-binance-history-no-go-2026-10-29)) | [Research](#research-record-only) |

## Migration gate (before pumpfun-trading is deleted)

Done: the history import, the module and lane, the docs split, the replay
of the rc.8 graduation rows through the new stack
([RESULTS §6.14](RESULTS.md#614-feat-76-on-the-new-stack-the-rc8-graduations-replayed-through-trading-core-2026-10-28)),
CI green on 3.11–3.14, and the rc.9 tags installed in the runtime folder
([DONE.md](DONE.md#migration-onto-trading-core-2026-10-28-changelogmd-unreleased--040)).

- [ ] A paper run of at least 24 h on the new stack with `configs/paper.example.json` (copied to the runtime folder; the 72 h rc.9 run below counts): check after an hour that the capture's oldest row is the start time (BUG-157), `degraded` conditions stay clear, the dashboard rows move, and the capture replays with `trading-pump replay` to the same positions as the run (fills at the same readings, within the fee difference) — **2026-11-03:** rc.11's capture replays to the run's instant positions (245 of 245, entry the same at the median) and momentum entries within 0.04% at the median after BUG-164; 48 of 52 momentum positions are the same coins and a few stops fill at another reading (`BUGS.md`, BUG-164). The PumpSwap lanes are closed, so this item now matters only for the module's own replays
- [ ] Move the runtime data that is still wanted (rc.6 to rc.8 captures, analysis scripts, `runtime/archive/`) out of the pumpfun-trading checkout, if it lives there
- [ ] Then archive the pumpfun-trading GitHub repository (read-only) rather than deleting it; its history is in this repository already

## FEAT-76 PumpSwap Post-Graduation Momentum Lane

Done: the paper lane, the PumpSwap paper executor priced from the pool and
the fee config, the replay, the pre-registered verdict file
(`configs/verdict_rules.json`) ([FEATURES.md §3–§5](../FEATURES.md#3-the-pumpswap_momentum-lane-feat-76-paper)), and the fee check against real swaps
([RESULTS §6.16](RESULTS.md#616-pumpswap-fee-check-the-cost-model-holds-on-the-mints-real-supply-2026-10-29)).
pumpfun-trading's planned rc.9 build (BUG-157 fixed) is superseded: the
capture here is pruned by its own policy only, and "rc.9" now names the first
run on the new stack (`v0.4.0rc1`).

- **pump-12 is not run, and both lanes are closed (2026-11-03).** The deep analysis (A1–A7, [RESULTS §6.20](RESULTS.md#620-rc11-and-rc11-tp20-read-outs-no-exit-passes-pump-12s-design-gate-2026-11-03)) and everything tried after it (short holds, an adaptive gate and selector, the supply map of 902 instant graduates, section B on each supply-map group, [RESULTS §6.21](RESULTS.md#621-after-the-deep-analysis-no-pumpswap-lane-can-pass-the-lanes-are-closed-2026-11-03)) found no design that passes the gate on every capture. The plan's build items (FEAT-96 to FEAT-98, FEAT-63's creator funder, trading-core FEAT-92 to FEAT-95) and the pump-13 candidates (FEAT-105, FEAT-106) are not built. A PumpSwap lane comes back only with a new design judged on new data; the supply map's crash signal ([RESULTS §6.21](RESULTS.md#621-after-the-deep-analysis-no-pumpswap-lane-can-pass-the-lanes-are-closed-2026-11-03)) is the place to start.
- The cross-chain market recorder's items (sell checks, launchpad coverage, per-chain costs) are trading-scout's: see [Cross-chain market recorder (FEAT-74)](#cross-chain-market-recorder-feat-74)

## Live gate for the PumpSwap lane

Only after a lane's Stage 1 (paper) verdict is GO. The staged gate is
[`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate); these items are its
§4.2.

- [ ] PumpSwap buy builder (`sdk/pumpswap_execution.py`) checked against real mainnet transactions, as the sell was (BUG-123): account order, the fee recipients, the creator vault, Token-2022; pinned to real account bytes in tests
- [ ] `LiveExecutor` (with FEAT-99, Jito bundles): build, send (Jito or RPC), confirm, and return the `Fill` with costs from the transaction meta (trading-solana's `costs`, `sdk/costs.py` until 0.5.0); refuse wherever the paper fill refuses; never a fallback price
- [ ] One live PumpSwap sell at the smallest size before any lane relies on it with real capital (carried from Sprint 24H: the sell instruction is pinned to mainnet accounts, but no transaction from this code has landed)
- [ ] Port `reconcile` (pumpbot's `bot/reconcile.py`, `pumpfun-audit reconcile`) as the module's implementation of trading-core's reconciliation contract (trading-core TODO): on-chain Δ SOL against the audit trail's realized PnL, every full exit showing a negative rent cost (carried from Sprint 24B, *partly done read-only*: the cost parser reads rent refund, fee and priority fee correctly on third-party sells)
- [ ] One live round trip at the smallest size, reconciled
- [ ] Stage 1: 72 h paper with replay recording on the release build (rule hashes in the run record first); Stage 2: live canary on a dedicated hot wallet at 0.02 SOL, daily wallet reconciliation logged every canary day, every discrepancy in `BUGS.md` and fixed before continuing (carried from Sprint 24A, where these were Stage 0 and Stage 1)
- [ ] Tip experiment before Stage 2: 0 / 25k / 50k lamports per side, on landing rates (carried from Sprint 24E; tips were 83% of the separately listed costs at 0.01 SOL on the curve)
- **Acceptance (Stage 2, Sprint 24A's Stage 1):** ≥ 100 closed positions, net PnL after fees, tips and rent positive, reconciliation gap within tolerance every day, 0 lost or double-sold positions. Only then raise capital (Stage 3).

## Research (record-only)

### Graduation tracking (FEAT-73)
Built and ported ([FEATURES.md §2](../FEATURES.md#2-graduation-tracking-feat-73)). Carried over:
- [ ] Run a 24 h capture (`configs/capture.example.json`); check the followed count stays below `max_mints` and the RPC credit use matches [`COSTS.md` §3.1](COSTS.md#31-helius-rpc-credits)
- [ ] Read-out: per graduate the path over 4 h relative to the graduation price (410.88 SOL), split into coins complete at creation, curve filled within 5 minutes and slower; how often a crash below 0.5× comes back above 1× / 2×; and whether any entry rule (after the first crash, after a new high, by pool SOL) beats PumpSwap costs in both halves of the run and the next. Record it in `RESULTS.md` §6
- [ ] PumpSwap buys on any rule other than FEAT-76 only if that read-out finds one
- The read-out of the curve *before* graduation (launch sample joined to graduation rows) needs the launch sample, which was not ported; see [Not ported](#not-ported)

### On-chain migration feed (FEAT-77, fallback for PumpPortal)
PumpPortal is the only source of migrations, and it has failed twice (a silent half-open socket for 3 h, BUG-150; refusals a reconnect did not clear, BUG-156). Its events arrive about 1 s after the migration block (rc.9: 0.3–1.1 s on five graduates, block times to the second), so speed is not the reason: with a 60 s signal, millisecond detection changes nothing.
Done (2026-10-31): (b) measured for 15 minutes on the public RPC: `programSubscribe` on PumpSwap pool accounts (`dataSize` 301) carries every swap's pool write, 47 messages and 36 kB a second for 832 pools. A canonical pool first seen is almost always an old graduate trading again (about 60 a minute after a 5-minute warm-up), so the subscription alone cannot say "migration" without dating each pool (one `getSignaturesForAddress` each).
- [ ] Cheaper on-chain migration signal: `logsSubscribe` mentioning the Pump.fun program (its `migrate` instruction), measured for volume first, or dating only the canonical pools whose first reading looks like a fresh graduation (about 85 SOL in the pool); the provider's WebSocket cost for FEAT-80's 3 GB a day decides whether one stream can serve both
- [ ] If one is cheap enough: a second migration source in `feed.py` behind the same tracker (de-duplicated by mint), with its own degraded condition, so a PumpPortal outage stops neither the follow list nor the capture. Geyser / Yellowstone (paid, lower latency) stays out unless live fills show latency costs entries (FEAT-39)

### Meteora DAMM v2 new pools (FEAT-107)
Moved to trading-meteora in `0.5.0` ([DONE.md](DONE.md#release-v050-onto-trading-solana-and-trading-core-070-feat-115)); `damm-1` runs on `v0.4.0` until 2026-11-06 and its read-out is trading-meteora's.

### New PumpSwap pools that are not graduations (FEAT-80)
Closed 2026-11-03: pools-1 found no edge (DONE.md). Built record-only ([FEATURES.md §2.1](../FEATURES.md#21-new-pumpswap-pools-that-are-not-graduations-feat-80-record-only)).

### Cross-chain market recorder (FEAT-74)
Not this repository's: the recorder and every open item it had moved to **trading-scout** on 2026-10-30 (its `docs/dev/TODO.md`; trading-scout's own FEAT-1 is FEAT-74 in the shared series). A chain that passes its read-out there gets a module of its own, not a lane here.

## Module and tooling

Done: FEAT-115, `0.5.0` ([DONE.md](DONE.md#release-v050-onto-trading-solana-and-trading-core-070-feat-115)); its release gate is the Now row above.
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
capture planned for pumpfun-trading's rc.9 (FEAT-76 phase 1) is replaced by
the 72 h rc.9 paper run above, which records the same rows.
