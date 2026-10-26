# Production Trading Bot TODO

Open work only. Finished phases, sprints and items are archived in [`DONE.md`](DONE.md) under their original headings; release-by-release changes are in [`CHANGELOG.md`](../../CHANGELOG.md), and strategy evidence and results in [`STRATEGY-PIVOT.md` §6](STRATEGY-PIVOT.md#6-results-log). This file says what to do, not what was found.

**Keeping it current.** When a sprint's last box is ticked, move it to `DONE.md` with its CHANGELOG release. In a sprint that is only partly done, move the ticked items to `DONE.md` and leave one "Done:" line here. Check a completion against the code before ticking or moving it.

## Now / Next / Later

| When | Work | Where |
|---|---|---|
| **Now** | rc.7 fix release (BUG-145 to BUG-155: no paper fills or sells without a curve read, RPC breaker that stops traffic, stream reconnect, launch buys wait for the new curve) and the 24 h launch-mode A/B re-run on it (the rc.5 runs are void, the rc.6 run covers a biased fifth of launches); rc.5 data features (FEAT-72: a sample of all launches from creation, and every closed position followed after its sell); momentum and pre-graduation are NO-GO on rc.3 ([`STRATEGY-PIVOT.md` §6.11](STRATEGY-PIVOT.md#611-v030-rc3-interim-read-out-455-h-both-pumpfun-lanes-no-go-2026-10-23)) | [rc.5 data](#rc5-data-launch-sample-and-post-exit-tracking-feat-72), [Sprint 24A](#sprint-24a-paper-pilot--live-canary--see-release-gatemd-3-and-runbookmd) |
| **Next** | Read out the launch A/B and the launch sample; Stage 0 only for a lane that passes the replay go / no-go (none on Pump.fun today); drills | [Sprint 24A](#sprint-24a-paper-pilot--live-canary--see-release-gatemd-3-and-runbookmd), [24D](#sprint-24d-unattended-operation--capital-protection-feat-50-feat-42-bug-110) |
| **Then** | Smart-wallet evidence (24I), Phase 5 runtime and platform sprints (28c–31) | [Sprint 24I](#sprint-24i-smart-wallet-discovery--reviewed-watch-list-feat-54), [Phase 5](#phase-5-platform-refactor-required-before-the-web-ui) |
| **Later** | Phase 6 Hosted Web UI, only after the funding gate | [Phase 6](#phase-6-hosted-web-ui-replaces-sprint-16) |

## Phase 4b: Terminal Income Track (highest priority)

**Funding model.** The terminal UI (`pumpbot`) must generate the income that pays for the Web UI. Phase 6 does not start until the funding gate below passes, so every sprint in this phase outranks Phases 5 and 6.

Done: net PnL accounting and reconciliation (24B), backtest fidelity (24C), unattended operation (24D) and the v0.2.x Stage 0 fixes; see [`DONE.md`](DONE.md#phase-4b-terminal-income-track-highest-priority).

**Rules while the income track runs**
- Money-path changes (execution, SDK, sizing, exits, risk, stream handlers) are limited to bug fixes and Phase 4b / 4c items. Each one goes back through Stage 0 ([`RELEASE-GATE.md` §3.1](RELEASE-GATE.md#31-stages)).
- Phase 5 sprints that change runtime code wait until Stage 1 has passed, unless they change no behaviour (golden replay unchanged); they are then released between canary windows, each with its own Stage 0 run.
- Web UI work (Phase 6) waits for the funding gate.

**Funding gate (entry condition for Phase 6)**
- [ ] Live capital gate Stage 1 passed and the bot is at Stage 2 or above ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate))
- [ ] Cumulative **net** profit (after fees and tips, reconciled against the wallet) covers the agreed Phase 6 budget (hosting, domain, security review) plus a reserve of at least one month of running costs
- [ ] Net profit positive for at least 4 consecutive weeks at the current capital stage
- [ ] Decision and figures recorded in the release record ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui))

### Sprint 24A: Paper Pilot & Live Canary — see [`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-live-capital-gate) and [`RUNBOOK.md`](RUNBOOK.md)
Done: release tagging, runtime directory, the v0.2.0 / v0.2.1 Stage 0 runs (invalid / FAIL) and their fixes, the v0.2.3 capture run ([`DONE.md`](DONE.md#sprint-24a-paper-pilot--live-canary--see-release-gatemd-3-and-runbookmd)).
- [ ] Run the incident drills in paper mode ([`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills)): `pumpfun-drill --report` for the scripted breaker drills (§7.1, FEAT-69) on the release build, then the manual drills (§7.2) on the paper deployment
- [ ] Stage 0: 72 h paper pilot on the live stream with replay recording, on the build and lane that pass the replay go/no-go ([`STRATEGY-PIVOT.md` §5](STRATEGY-PIVOT.md#5-go--no-go)); record the rule hash before it starts and judge it with `pumpfun-audit verdict --rules configs/verdict_rules.json` (FEAT-67); record the summary and the run's `run_provenance` (FEAT-68) in the release record
- [ ] Test `min_holder_count: 6` on a capture it was not picked from; only if it stays positive in replay put it in `canary.json`
- [ ] Stage 1: live canary on a dedicated hot wallet with the canary config ([`RELEASE-GATE.md` §3.3](RELEASE-GATE.md#33-stage-1--live-canary-configuration): 0.02 SOL buys, `entry_mode: confirmed`, lower tip; arbitrage, back-running, pre-graduation harvesting, Raydium sniping and copy trading off until their own paper runs)
- [ ] Daily wallet reconciliation (on-chain Δ SOL vs audit realized PnL) logged for every canary day ([`RUNBOOK.md` §5.3](RUNBOOK.md#53-daily-wallet-reconciliation))
- [ ] Log every discrepancy or failure in `BUGS.md`; fix before continuing
- **Acceptance:** Stage 1 exit criteria met — ≥ 100 closed trades, net PnL after fees and tips positive, reconciliation gap within tolerance every day, 0 lost or double-sold positions. Only then increase capital (Stage 2) or plan Phase 5–6 spending around bot income.

### Sprint 24B: Net PnL Accounting & Reconciliation (FEAT-49, BUG-96)
Done: per-trade costs, net PnL records, `pumpfun-audit pnl` / `reconcile`, dashboard and reconciliation status ([`DONE.md`](DONE.md#sprint-24b-net-pnl-accounting--reconciliation-feat-49-bug-96)).
- [ ] Verify on mainnet with the first canary trades: `pumpfun-audit reconcile` passes and every full exit shows a negative `rent_sol`. *Partly done (read-only):* the cost parser reads rent refund, fee and priority fee correctly on third-party Pump.fun sells; only the bot's own canary trades can close this item
- **Acceptance:** for a paper/devnet session, `pumpfun-audit reconcile` reproduces the wallet delta within tolerance; net PnL on the dashboard equals the audit `pnl` total; coverage ≥ 95%

### Sprint 24C: Backtest Fidelity & Strategy Tuning (BUG-61, BUG-102)
Done: phases 1–4 (secret redaction, live-fidelity replay, replay costs, parity tooling and its first run) ([`DONE.md`](DONE.md#sprint-24c-backtest-fidelity--strategy-tuning-bug-61-bug-102)).
- [ ] **(phase 5, operations)** Tune with `pumpfun-optimize` on recorded **live** captures (train/test split by day; BUG-60 selection on `train_fitness` only); promote a tuned config only through Stage 0. Procedure: [`RUNBOOK.md` §6.1](RUNBOOK.md#61-replay-parity-and-tuning-on-captures-sprint-24c); needs ≥ 2 days of capture and a passing parity check first
- [ ] **(phase 5, partly)** Per-filter attribution report (which filters reject winners) built on the captures' `event: "screening"` records. *Available:* per-exit net PnL (`pumpfun-audit pnl --group-by reason`), entry rules against a random cut (`pumpfun-audit cuts`, `pumpfun-replay --keep`), per-risk-limit entry rejections in the replay summary
- **Acceptance:** replay of a live capture matches live net PnL within an agreed tolerance; a tuned config beats the canary config out-of-sample before it is promoted

### Sprint 24D: Unattended Operation & Capital Protection (FEAT-50, FEAT-42, BUG-110)
Done: operator pause, BUG-110, daily summary and degradation alerts, profit sweep (off by default), supervised deployment templates ([`DONE.md`](DONE.md#sprint-24d-unattended-operation--capital-protection-feat-50-feat-42-bug-110)).
- [ ] Run the new drills in paper mode: operator pause, profit sweep, supervisor restart, degradation alert ([`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills))
- [ ] Optional, if latency is shown to cost entries: FEAT-39 Yellowstone gRPC transport (isolated in `streams/`). *Not started:* decide on the first clean Stage 0 / canary capture
- **Acceptance:** 7 days unattended at the current capital stage with no manual restarts; pause and sweep exercised in drills ([`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills))

## Phase 4c: Strategy Pivot (income track, ahead of Phase 5)

Launch sniping lost money because it buys tokens no one else buys ([`STRATEGY-PIVOT.md`](STRATEGY-PIVOT.md) §1). Phase 4c replaces it with **confirmed momentum** plus a **pre-graduation lane** fed by a cheap RPC curve poller. Launch sniping stays available as `entry_mode: "launch"` (default), so the golden replay is unchanged. Rationale, cost model and go/no-go rules: [`STRATEGY-PIVOT.md`](STRATEGY-PIVOT.md).

| Sprint | Priority | Goal | Money path? | Exit gate |
|---|---|---|---|---|
| 24E | P0 – first, no code risk | Branch, pivot doc, TODO / FEAT / gate docs, tip experiment plan | No | Docs reviewed (done) |
| 24F | P0 – unlocks everything | Watch list, batch curve poller, promotion and subscription budget (FEAT-51) | Entry gate only | **Done** (paper run PASS on rc.1) |
| 24G | P0 – the income change | Momentum confirmation entry, exit tuning, cost guard, replay support (FEAT-52) | Yes | Replay net > 0 on an unseen capture, then 72 h Stage 0 net > 0 |
| 24H | P1 – second lane | Pre-graduation lane via the poller (FEAT-53), Stage 1 canary at 0.02 SOL with a lower tip | Yes | Lane positive in 72 h paper; Stage 1 criteria |
| 24I | P2 – after 24H | Smart-wallet discovery, copy simulation, reviewed wallet list used as momentum evidence (FEAT-54) | Entry evidence only; no copy lane | Our simulated copy PnL net > 0 on an unseen capture; momentum + wallet evidence beats momentum alone in replay and a 72 h paper run |

Sprint 24F is complete and archived in [`DONE.md`](DONE.md#sprint-24f-watch-list--batch-curve-poller-feat-51).

### Sprint 24E: Branch & Strategy Pivot Documentation
Done: branch, `STRATEGY-PIVOT.md`, FEAT / STRATEGY / RELEASE-GATE / CHANGELOG / AGENTS updates ([`DONE.md`](DONE.md#sprint-24e-branch--strategy-pivot-documentation)).
- [ ] Tip experiment on paper/landing: 0 / 25k / 50k lamports, shared and split by side (`PUMPFUN_JITO_ENTRY_TIP_LAMPORTS` / `PUMPFUN_JITO_EXIT_TIP_LAMPORTS`; e.g. entry 0, exit 25k / 50k). Tips were 83% of the separately listed costs at 0.01 SOL

### Sprint 24G: Momentum Confirmation Entry & Exit Tuning (FEAT-52)
Done: entry and exits, replay support, v0.2.3 tuning, rc.1 NO-GO, BUG-121/122, drift guard, stop-loss sweep, capture-rule tooling, market regime, FEAT-55/56/57/58 inputs, curve polls in captures, rc.3 inputs (FEAT-59/60/61), the read-out tooling, the rc.2 read-out (**NO-GO**), BUG-126, `stop_loss` 0.92, recording of the reject sample and stop crossings, and the rc.3 read-out ([`DONE.md`](DONE.md#sprint-24g-momentum-confirmation-entry--exit-tuning-feat-52)). **Closed 2026-10-23: the momentum lane is NO-GO** ([`STRATEGY-PIVOT.md` §6.11](STRATEGY-PIVOT.md#611-v030-rc3-interim-read-out-455-h-both-pumpfun-lanes-no-go-2026-10-23)); no open items, the acceptance below was not met.
- **Acceptance:** replay net > 0 on an unseen capture, then 72 h Stage 0 net > 0; golden replay unchanged in launch mode

### Sprint 24H: Pre-Graduation Lane via the RPC Poller (FEAT-53)
Done: entry helper on both transports, polled acceleration, PumpSwap exit (BUG-123), quote-mint refusal (BUG-124), near-graduation set, graduation backfill, BUG-125, RUNBOOK §6.3, recording of discovered curves, and the rc.3 discovery read-out ([`DONE.md`](DONE.md#sprint-24h-pre-graduation-lane-via-the-rpc-poller-feat-53)). **The lane is NO-GO on the rc.3 data** (§6.11); the items below stay open only for the end of the 72 h control run.
- [ ] One live PumpSwap sell at the smallest size before any lane relies on it with real capital (the instruction is pinned to mainnet accounts, but no transaction from this code has landed yet)
- [ ] 72 h paper pilot of the pre-graduation lane (rc.3 runs it unchanged as a control); Stage 1 canary
- **Acceptance:** lane positive in a 72 h paper pilot; Stage 1: ≥ 100 trades, net > 0, reconciled

### Sprint 24I: Smart-Wallet Discovery & Reviewed Watch List (FEAT-54)
Starts after 24H. Needs at least two captures recorded with `configs/capture.json` (trade flow for watched mints): one to find wallets, a later one to test them. Wallets are **never** added to live copy trading automatically: high win rate is not net profit, a wide scan finds lucky wallets, and our copy fills later and at a worse price than the wallet ([`STRATEGY-PIVOT.md` §2.4](STRATEGY-PIVOT.md#24-lane-3--reviewed-smart-wallets-feat-54-p2)).

Done: the phase 1 scorer, `pumpfun-replay --wallet-scores` ([`DONE.md`](DONE.md#sprint-24i-smart-wallet-discovery--reviewed-watch-list-feat-54)); copying every captured wallet lost on both captures, so no wallet list is made yet.

| Phase | Scope | Touches money path? |
|---|---|---|
| 1 | Offline wallet scorer on captures; candidate file | No (tooling) |
| 2 | Copy simulation with our delay and costs; train/test by capture | No (replay) |
| 3 | Reviewed tracked list; tracked-wallet buys as momentum evidence | Entry evidence only |
| 4 | Rolling per-wallet kill switch and exposure cap; reporting | Entry gate only |
| 5 | Optional `strategy=copy` lane via `subscribeAccountTrade` | Yes; only after phases 1–4 pass |

- [ ] Phase 1 minimums (`wallet_min_closed_trades`, `wallet_min_distinct_tokens`): wait for a capture that records more than the bot's own subscriptions; today's captures give at most ~15 closed copies per wallet
- [ ] **Rejects:** buys in the first slots after create (snipers / bundles), wallets in the creator's funding cluster (`strategies/filters.py` Sybil checks), round-trip / wash patterns, wallets active on fewer than N days; each reject counted by reason
- [ ] **Copy simulation:** replay each candidate's buys with our delay (`copy_entry_delay_slots`, default 2) and the live exit stack; keep a wallet only if **our** copied PnL is net positive on a later capture not used to find it. Survivors go to `wallets_candidates.json` with their metrics *(the phase-1 scorer copies the wallet's own exit, not the live exit stack, and already checks a second capture)*
- [ ] **Reviewed list:** an operator moves candidates to `tracked_wallets.json` (`WalletRegistry` loads it); nothing writes to it automatically. `RUNBOOK.md` gets the review checklist
- [ ] **Momentum evidence:** a tracked wallet's buy on a watched, subscribed mint lowers the distinct-buyer requirement by `momentum_tracked_wallet_bonus` (default 0 = off); it never skips the age / market-cap band, `_should_buy` or the cost guard. Influenced buys record `entry_metrics.tracked_wallets`; replay models the same rule
- [ ] **Kill switch and cap:** disable a wallet when its rolling net PnL over the last `wallet_rolling_window` (20) influenced positions is below zero; `wallet_max_exposure_sol` caps SOL at risk per wallet; both audited and alerted
- [ ] **Reporting:** `pumpfun-audit pnl --group-by wallet` for influenced positions; dashboard shows tracked / disabled wallet counts
- [ ] Tests in the mirrored layout: `unit/strategies/test_copy_trading.py`, `unit/strategies/test_momentum.py`, `unit/engines/test_replay.py`, `unit/cli/test_audit.py`, `unit/bot/test_run.py`; no network calls
- [ ] Optional phase 5, only after the acceptance below: stand-alone `strategy=copy` lane on `subscribeAccountTrade` with its own subscription budget and the BUG-116 breaker; `enable_copy_trading` stays off in the canary until it passes its own 72 h paper run (`RELEASE-GATE.md` §3.5)
- **Acceptance:** on a capture not used for discovery, our simulated copy PnL of the reviewed wallets is net > 0, and momentum with wallet evidence beats momentum alone in replay and in a 72 h paper run (`pumpfun-audit pnl --group-by strategy`); if not, leave `momentum_tracked_wallet_bonus` at 0 and record the result in `STRATEGY-PIVOT.md` §6

### FEAT-65 Slow Lane: Phase 0 Data (contingency, record-only)
Done: the keyless quote / fee recorder and the bar backfill (`pumpfun-recorder --jupiter-quotes` / `--backfill-bars`, rc.3; [`DONE.md`](DONE.md#feat-65-slow-lane-phase-0-data-contingency-record-only); how to run it: [`RUNBOOK.md` §6.4](RUNBOOK.md#64-slow-lane-data-recorder-feat-65-phase-0-from-rc3)). The lane itself starts only if the rc.3 Pump.fun lanes are NO-GO too ([`PROPOSED-FEATURES.md` FEAT-65](PROPOSED-FEATURES.md#feat-65-slow-lane-daily-bar-trend-on-liquid-solana-tokens-via-jupiter)).
- [ ] Walk-forward test of the §6.12 trend rules on the Binance history (`pumpfun-recorder --backfill-bars --bar-source binance`, 2020–2026), in SOL terms with the measured costs, against a random-entry baseline and on at least two unseen periods; only if it passes, build the FEAT-65 backtester and lane

### rc.5 Data: Launch Sample And Post-Exit Tracking (FEAT-72)
Done: the record-only launch sample and post-exit tracking ([`DONE.md`](DONE.md#rc5-data-launch-sample-and-post-exit-tracking-feat-72), [`FEATURES.md` §42](../FEATURES.md#42-launch-sample-and-post-exit-tracking-feat-72-rc5)).
- [ ] Re-run the A/B on rc.7 (BUG-145 to BUG-155 fixed; the rc.6 run bought only the fifth of launches whose curve the RPC already had, BUG-154) ([`BUGS.md` §26](BUGS.md#26-rc5-paper-run-findings-2026-10-25)): both earlier rc.5 A/B runs are void (fills invented when the curve read failed, coins complete at creation bought, an hour with no working RPC). Give each bot its own RPC key plus a fallback (`PUMPFUN_RPC_URLS`, [`RUNBOOK.md` §5.8](RUNBOOK.md#58-rpc-and-stream-outages-bug-145-to-bug-151)), check `entry_refusals` and `rpc_pool_telemetry.requests_by_method` in the first hour, and leave any window with `healthy_endpoints` 0 out of the verdict
- [ ] 24 h launch-mode paper A/B on rc.5 (runtime `configs/launch_fast_exit.json` and `configs/launch_hold_stop.json`, anti-rug screen off, all out at 1.10×, stop 0.80 from the start vs held 90 s with a 0.40 floor), with `post_exit_observation_seconds: 900` in both and `launch_sample_pct: 0.2` in run A (the draw is deterministic, so one copy is enough): `pumpfun-audit verdict --rules configs/verdict_rules.json` per run, per-trade net A vs B, and from the `post_exit` rows how many stopped or stalled coins came back above their exit within 15 minutes
- [ ] Launch-sample read-out: share of all launches that reach 1.1 / 1.3 / 1.5× and when, by creator buy size, by screen verdict and by UTC hour; what a buy at launch earns after costs with the A / B exits; record it in `STRATEGY-PIVOT.md` §6
- [ ] Trade data for sampled launches (buyer wallets, sizes, timing) only if the curve read-out shows a rule worth testing that needs it (a PumpPortal trade subscription per sampled mint)

## Phase 5: Platform Refactor (required before the Web UI)

**Scheduling around income:** Sprints that change runtime behaviour start only after live capital Stage 1 has passed (see the Phase 4b rules); behaviour-neutral extractions (golden replay unchanged) may ship earlier, as 28a and 28b did.

The bot is in production. Phase 5 pays down the structural debt that blocks the hosted Web UI without touching trading behaviour. Every sprint keeps the standard gates: **coverage ≥ 95% (`fail_under` never lowered)**, `nox -s lint`, `nox -s format`, `nox -s mypy` clean, and replay parity (identical decisions on the recorded datasets in `test-data/`) for any runtime change. Finding IDs (R1–R12, T1–T9) are defined in [`TESTING.md`](TESTING.md) and [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md).

Done: Sprints 25 (packaging), 26–27 (test restructure) and 28a / 28b ([`DONE.md`](DONE.md#phase-5-platform-refactor-required-before-the-web-ui)).

| Finding | Summary | Sprint |
|---|---|---|
| R1 | `bot/run.py` regrew to 5,078 lines (4,631 after Sprint 28a, 3,571 after 28b) | 28c |
| R2 | No typed read-model; `storage/status.py` reads private attributes via `getattr` | 29 |
| R3 | No `PAUSED` / `HALTED` lifecycle states | 29 |
| R4 | No command/control interface or event bus | 29 |
| R5 | Hot config has no validated patch path through the risk pipeline | 29 |
| R11 | No real Yellowstone gRPC transport | FEAT-39 (parallel track) |
| R12 | JSON/JSONL-only persistence; ledger inlined in the snapshot | 30 |

R6–R10 and T1–T9 are closed (Sprints 25–28b).

### Sprint 28: Runtime Decomposition II (R1, R6, R7)
Done: 28a (`bot/factory.py`, `execution/sell_pipeline.py`, `ops/metrics.py`, `streams/websocket.py`, the `sdk/execution.py` split) and 28b (`bot/handlers/`) ([`DONE.md`](DONE.md#sprint-28-runtime-decomposition-ii-r1-r6-r7)).
- [ ] **28c** the rest of the < 800-line target: `__init__`, the buy and sell paths, `get_status_snapshot`, `start`, the supervision loops and `_handle_message`; widen `unit/test_suite_layout.py` from `*/*.py` to `**/*.py` so sub-packages such as `bot/handlers/` need mirrored tests. This also closes the re-opened facade item from Phase 4 item 25 / Sprint 15 ([`DONE.md`](DONE.md#25-core-runtime-decomposition--solid-architecture-refactoring-feat-12))
- **Acceptance:** `bot/run.py` < 800 lines; golden replay tests from Sprint 27 unchanged; coverage ≥ 95%; mypy clean

### Sprint 29: Typed State, Lifecycle Control & Event Bus (R2–R5)
- [ ] `bot/state_model.py`: Pydantic `BotStatusView`, `PositionView`, `TradeView`, `HealthView`; `storage/status.py` and `ui/dashboard.py` consume views instead of `getattr(bot, "_…")`
- [ ] `bot/lifecycle.py`: add `PAUSED` (manage exits, no new buys) and `HALTED` (circuit breaker) states and transitions; the Sprint 24D `SIGUSR1` pause becomes a thin trigger for `BotController.pause()` / `resume()`
- [ ] `bot/control.py`: `BotController` with `pause()`, `resume()`, `stop()`, `sell_all()`, `apply_config_patch(ConfigPatch)`; each command validated, audited, and routed through the unified risk pipeline
- [ ] `ops/bus.py`: in-process typed event bus; terminal dashboard subscribes to it
- [ ] Replace the `TradingBot.config` setter with validated `ConfigPatch` application
- **Acceptance:** zero `getattr(bot, "_…")` in `storage/` and `ui/`; terminal UI behaviour unchanged; coverage ≥ 95%

### Sprint 30: Persistence Layer (FEAT-35, R12)
- [ ] `storage/db/` with SQLAlchemy 2.0 async models and Alembic migrations (tables: `tenants`, `users`, `sessions`, `instances`, `config_versions`, `positions`, `trades`, `audit_events`, `equity_snapshots`, `alerts`)
- [ ] PostgreSQL for hosted mode, SQLite (WAL) for operator/dev mode; selected by URL
- [ ] Move the trade ledger out of the status snapshot; JSONL dual-write during migration
- [ ] DB tests on SQLite in-memory plus an opt-in `postgres` marker
- **Acceptance:** terminal mode runs with and without `[db]`; migrations up/down tested; coverage ≥ 95%

### Sprint 31: Documentation Site & Gap Closure (FEAT-37 build) — see [`DOCUMENTATION-PLAN.md`](DOCUMENTATION-PLAN.md)
- [ ] Add `mkdocs.yml` (Material-compatible) and a Zensical build; `docs/index.md` landing page
- [ ] Close every open gap listed in `DOCUMENTATION-PLAN.md` (FEAT-12 duplicate, FEAT-10 status, rest of the RUNBOOK expansion, missing pages); NEXT-30-DAYS is already retired
- [ ] Convert ASCII diagrams to Mermaid; add front matter, admonitions and tabs
- [ ] mkdocstrings API/SDK reference; strict build in CI
- **Acceptance:** `zensical build` (or `mkdocs build --strict`) passes with zero warnings

### Carried over from the archived roadmap
Open items left in the Phase 0–4 roadmap and the repo-specific work items when they were archived ([`DONE.md`](DONE.md#repo-specific-work-items)). Schedule each into a sprint before starting it.
- [ ] Geyser event pipeline: route parsed Yellowstone updates directly into bot state and the strategy decision loops (needs the FEAT-39 transport; `bot/event_router.py` handles the WebSocket path today)
- [ ] Terminal dashboard: show per-endpoint RPC latencies, Jito bundle status and Geyser stream health (today only the average latency is shown)

### Ongoing
Standing practices with no end date, carried over from the archived work items; not ticked.
- Keep narrowing runtime responsibilities as the bot grows, with explicit module boundaries (Sprint 28c is the current step).
- Expand CLI docs and examples for operators as release tooling matures (Sprint 31 closes the current gaps).
- Add simulation / backtest modes when a strategy question needs one (as `--sweep`, `--shadow-scan` and `--wallet-scores` were).
- Keep the terminal dashboard a lightweight, zero-dependency console monitor (FEAT-19).

## Phase 6: Hosted Web UI (replaces Sprint 16)

**Entry condition:** the Phase 4b funding gate has passed. Until then the terminal UI is the only product and Phase 6 stays planned, not started.

Architecture: [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) and [`docs/WEB-UI.md`](../WEB-UI.md). Features: FEAT-31…FEAT-37 in [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md). The superseded Sprint 16 / FEAT-10 items (Telegram bot, FastAPI in `ui/`) are archived in [`DONE.md`](DONE.md#sprint-16-full-featured-web-control-dashboard-fastapi-portal--mobile-telegram-bot--superseded); the Telegram bot is FEAT-45 (P3).

### Sprint 32: Agent API & Control Plane, Single Tenant (FEAT-31, FEAT-32)
- [ ] `pumpfun_trading/agent/` aiohttp Agent API (`/health`, `/status`, `/commands/*`, `/config`, `/events` WS) backed by `BotController` and `ops/bus.py`
- [ ] FastAPI control plane (separate deployable, `[web]` extra): auth (OIDC/JWT + passkeys), RBAC, REST/WSS, OpenAPI
- [ ] Contract tests between control plane and Agent API
- **Acceptance:** pause/resume/stop/sell-all/config patch work end-to-end against a dry-run bot; trading-loop latency unchanged

### Sprint 33: Vuetify MD3 PWA MVP (FEAT-33)
- [ ] `web/` Vue 3 + TypeScript + Vite + Vuetify 3 (`md3` blueprint) + Pinia + generated OpenAPI client + `vite-plugin-pwa`
- [ ] Views: Overview, Positions, Trades, Controls, Settings
- [ ] Vitest component tests and Playwright desktop + mobile smoke tests, mirrored under `web/`
- **Acceptance:** Lighthouse PWA installable; usable at 360 px width; light/dark follows the system

### Sprint 34: Multi-Tenant Orchestrator & Zero-Knowledge Keys (FEAT-34, FEAT-36, FEAT-46)
- [ ] Docker image (FEAT-46) and orchestrator service (`InstanceBackend`: Docker first) with quotas and private networking
- [ ] X25519 key envelope; worker-only decryption; buffers zeroed after signer setup
- [ ] Tenant isolation tests (no cross-tenant reads; no key material in logs, DB or disk)
- **Acceptance:** two tenants run isolated bots concurrently; security checklist in `RELEASE-GATE.md` signed off

### Sprint 35: Analytics, Audit Search, Embedded Docs & Terminal-UI Deprecation Gate (FEAT-37)
- [ ] Equity/PnL analytics and audit search views
- [ ] Serve the docs site at `/docs` with contextual help links from settings
- [ ] Terminal-UI deprecation gate: Web UI has parity for every operator workflow; terminal UI moves to "maintenance only"
- **Acceptance:** operator runs one full trading week from the Web UI only

## Definition of done for a “serious” bot

The bot is production-worthy and alpha-ready when it can:
- safely manage risk at the portfolio level with automated equity circuit breakers
- stop trading instantly when health, risk, or daily drawdown thresholds fail
- ingest market events with sub-millisecond latency via on-chain Geyser gRPC streams
- execute transactions via private Jito bundles to eliminate toxic MEV sandwiching
- screen out scams, dev dumps, and honeypots using multi-layer heuristic filters
- scale out profits dynamically using multi-tier take-profits and trailing stop-losses
- capture momentum from order flow velocity spikes and Raydium graduation events
- track and mirror proven smart money wallets with proportional risk budgeting
- maintain 99.99% operational uptime via multi-RPC latency pooling and failover
- replay and validate all strategy decisions against historical datasets
- recover smartly after restarts with verified state reconciliation
- maintain a clear, queryable audit ledger and provide remote mobile control via Telegram/Web
- demonstrate consistent risk-adjusted returns (Sharpe ratio > 2.0, Profit Factor > 1.8) across diverse market regimes

Additional rules from Phase 4b onward:
- The terminal UI (`pumpbot`) is the income path that funds the Web UI. It stays the primary interface until the **Sprint 35** deprecation gate, and no refactor or Web UI work may regress it.
- Income-track work (Phases 4b and 4c) outranks Phases 5 and 6; Phase 6 starts only after the Phase 4b funding gate.
- Profit is always reported **net** of network fees, priority fees, Jito tips and rent, and reconciled against the wallet.
- New tests follow the layout and conventions in [`TESTING.md`](TESTING.md) (mirrored `unit/<pkg>/test_<module>.py`, shared `support/` factories, no coverage-named files).

## Notes

This repo has a modular, tested foundation and can trade live, but has not yet shown net profit. Phases 4b and 4c turn the terminal mode into a measured, reconciled income source; that income funds the rest of the roadmap. Phase 5 pays down structural debt (runtime monolith, typed state, persistence, docs site) without risking the terminal mode, and Phase 6 delivers the hosted Material Design 3 Web UI once the funding gate has passed.
