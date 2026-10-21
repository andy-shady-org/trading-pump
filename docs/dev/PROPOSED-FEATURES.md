# Proposed Features & Architectural Enhancements

This document lists candidate features and architectural enhancements for `pumpfun-trading` that have **not yet been implemented**. For completed, supported features see [`docs/FEATURES.md`](../FEATURES.md). Architecture choices referenced below are recorded in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md), and the delivery schedule lives in [`TODO.md`](TODO.md).

**Classification**

| Class | Meaning |
|---|---|
| **Income** | Needed for the terminal UI to earn measurable, reconciled net income. Income features outrank everything else, because that income funds the Web UI. |
| **Required** | Blocks the hosted Web UI (FEAT-10) or hosted multi-tenant operation. |
| **Suggested** | Improves function, safety, or user experience but does not block the Web UI. |

| Priority | Meaning |
|---|---|
| **P1** | Schedule in the next phase. |
| **P2** | Schedule after the P1 items it depends on. |
| **P3** | Backlog; revisit after the Web UI ships. |

**Context.** The bot can trade live through the terminal UI (`pumpbot`), but it has not yet shown net profit. The terminal UI has to generate the income that pays for the Web UI, so the **Income** features below (Phase 4b in [`TODO.md`](TODO.md#phase-4b-terminal-income-track-highest-priority)) come first, and the Web UI starts only after the funding gate ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)). The terminal UI stays the primary interface until the deprecation gate in Sprint 35. Work that keeps the trading path fast, safe and profitable always wins over UI polish.

---

## 1. Catalogue Summary

| ID | Feature | Class | Priority | Sprint |
|---|---|---|---|---|
| FEAT-54 | Smart-wallet discovery, copy simulation & reviewed watch list | Income | P2 | 24I (phase 1 scorer shipped) |
| FEAT-55 | Creator reputation book | Income | P3 | not scheduled (no edge) |
| FEAT-56 | Sniper-volume & wallet-diversity entry filters | Income | P2 | inputs recorded in rc.2; gate not built |
| FEAT-57 | Wash-trade detection as a buy filter | Income | P3 | inputs recorded in rc.2 (no edge yet); gate not built |
| FEAT-59 | Pullback entry after the first dump | Income | P2 | shadow variants in rc.3; entry path not built |
| FEAT-60 | Buy-timing (drizzle / burst) inputs | Income | P3 | inputs recorded in rc.3 (no edge yet); gate not built |
| FEAT-61 | Create-slot bundle proxy | Income | P3 | inputs recorded in rc.3; gate not built |
| FEAT-62 | Moonshot (Solana) as a second venue, capture first | Income | P3 | not scheduled |
| FEAT-63 | Funding-source lookup for the FEAT-26 cluster analyser | Income | P3 | not scheduled |
| FEAT-64 | Post-graduation PumpSwap long-tail recorder, capture first | Income | P3 | not scheduled |
| FEAT-65 | Slow lane: daily-bar trend on liquid Solana tokens via Jupiter | Income | P3 | phase 0 data recorder in rc.3; the lane only if rc.3 is NO-GO |
| FEAT-10 | Web Control Dashboard (umbrella, re-scoped to FEAT-31…37) | Required | P1 | 32–35 |
| FEAT-31 | Bot Agent API & typed event stream | Required | P1 | 32 |
| FEAT-32 | FastAPI control plane (REST/WSS, auth, RBAC, OpenAPI) | Required | P1 | 32 |
| FEAT-33 | Vue 3 + Vuetify MD3 responsive PWA dashboard | Required | P1 | 33 |
| FEAT-34 | Multi-tenant instance orchestrator (container per tenant) | Required | P1 | 34 |
| FEAT-35 | Persistence layer (SQLAlchemy/Alembic, Postgres/SQLite) | Required | P1 | 30 |
| FEAT-36 | Zero-knowledge key ingestion (X25519 envelope, memory-only) | Required | P1 | 34 |
| FEAT-37 | Documentation portal (Zensical) embedded at `/docs` | Required | P2 | 31, 35 |
| FEAT-38 | Hot-config versioning, diff and rollback | Suggested | P2 | after 33 |
| FEAT-39 | Production Yellowstone gRPC transport | Income (conditional) | P1 | 24D, if latency costs entries |
| FEAT-40 | Live cross-venue arbitrage feed (closes BUG-90) | Suggested | P2 | after 39 |
| FEAT-41 | Prometheus / OpenTelemetry exporter + Grafana | Suggested | P2 | after 29 |
| FEAT-43 | PnL / tax CSV export and performance reports | Suggested | P2 | after 30 |
| FEAT-44 | Shadow paper-trading (A/B strategies alongside live) | Suggested | P3 | backlog |
| FEAT-45 | Interactive Telegram bot (deferred from FEAT-10) | Suggested | P3 | backlog |
| FEAT-46 | Docker image + compose for operator mode | Suggested | P2 | 24D (systemd slice), 34 (image) |
| FEAT-47 | Replay analytics on Parquet + DuckDB | Suggested | P3 | backlog |
| FEAT-48 | Strategy plugin registry via entry points | Suggested | P3 | backlog |

**Implemented and moved to [`FEATURES.md`](../FEATURES.md)** (2026-10-20): FEAT-49 net PnL and reconciliation (§30), FEAT-50 operator pause and unattended alerts (§31), FEAT-42 profit sweep (§32), FEAT-51 watch list and curve poller (§33), FEAT-52 confirmed momentum entry and exits (§34), FEAT-53 pre-graduation lane via the poller (§35), FEAT-58 shadow variants and read-out tooling (§36). The recorded inputs already shipped for FEAT-54 (phase 1), FEAT-56, FEAT-57, FEAT-60 and FEAT-61 are listed in `FEATURES.md` §37; their gating rules and later phases stay below. "Implemented" means the code ships, not that the lane is profitable: see [`STRATEGY-PIVOT.md` §6](STRATEGY-PIVOT.md).

**Moved back from [`FEATURES.md`](../FEATURES.md)** (2026-10-20): FEAT-10 (`FEATURES.md` §13 listed the web dashboard, FastAPI portal, in-app docs and Telegram command bot as implemented; none of it is built, see FEAT-10 / FEAT-31…37 / FEAT-45 below). The unbuilt parts of shipped features are now marked **Not built** in `FEATURES.md` and point here: §1 Geyser transport (FEAT-39), §16 Raydium sniping after the move to PumpSwap, §19 the `bot/run.py` facade (Sprint 28c), §27 funding links for the cluster analyser (FEAT-63), §29 live arbitrage reserves (FEAT-40).

---

## 2. Terminal Income Track (Income)

### FEAT-54: Smart-Wallet Discovery, Copy Simulation & Reviewed Watch List
* **Class / Priority:** Income · P2 (Sprint 24I, after 24H; [`STRATEGY-PIVOT.md` §2.4](STRATEGY-PIVOT.md#24-lane-3--reviewed-smart-wallets-feat-54-p2)). Phase 1 scorer shipped ([`FEATURES.md` §37](../FEATURES.md)); steps 3–6 below are not built
* **Goal:** Use wallets with a strong record as evidence for entries, without adding them to live copy trading automatically.
* **Evidence:** a wallet with "100+ buys at 75% wins" is not proof of a copyable edge:
  - win rate is not net profit (the confirmed lane was net positive at a 41–55% win rate in replay; a wallet can win 75% and still lose on a few large losses);
  - scanning thousands of wallets finds lucky ones (selection bias);
  - many high scorers are launch-slot snipers, bundle/dev/insider wallets or wash bots;
  - a copy always fills one or more slots later at a higher curve price, so the wallet's result does not carry over;
  - a wallet known to be copied can sell into its copiers.
* **Current code:** `strategies/copy_trading.py` (`TrackedWallet.win_rate`, `total_trades`, `record_trade_outcome`) tracks win rate only, and copy buys fire only on `subscribeTokenTrade` messages for mints the bot already holds or has promoted.
* **Design:**
  1. **Discover, don't act.** An offline scorer (`pumpfun-audit wallets` or `pumpfun-replay --score-wallets`) ranks wallets from captures on **net SOL after modelled costs**, distinct tokens, average and worst return, hold time and the share of buys in the first slots after create. It rejects launch-slot buyers, wallets linked to the token's creator (funding cluster, `strategies/filters.py` Sybil checks), and round-trip/wash patterns. Minimums are config keys (`wallet_min_closed_trades` 100, `wallet_min_distinct_tokens`, `wallet_min_net_sol`); win rate is reported, never used alone.
  2. **Simulate our copy.** Replay each candidate's buys with our own delay (`copy_entry_delay_slots`, default 2) and `engines/costs.py`; keep a wallet only if **our** copied PnL is net positive on a later capture that was not used to find it.
  3. **Reviewed list.** Survivors are written to a candidate file (`wallets_candidates.json`); a person moves them to the tracked list (`tracked_wallets.json`). Nothing is added to the tracked list automatically.
  4. **Confirmation, not a trigger.** A tracked wallet's buy on a watched mint counts as one more piece of evidence in the momentum check (`momentum_tracked_wallet_bonus`, e.g. one fewer distinct buyer needed); it never bypasses the age / market-cap band, `_should_buy` or the cost guard. Buys it influenced record `entry_metrics.tracked_wallets`.
  5. **Automatic removal.** A wallet is disabled when its rolling net copied PnL over the last `wallet_rolling_window` (20) influenced positions drops below zero, or when its SOL at risk would exceed `wallet_max_exposure_sol`; both are audited and alerted.
  6. **Optional stand-alone lane** (`strategy=copy`), only after the confirmation use is shown positive; needs `subscribeAccountTrade` (another billed PumpPortal feed, BUG-112/120), so it gets its own subscription budget and the BUG-116 breaker.
* **Phase 1 result (2026-10-20, rc.3 tooling):** `pumpfun-replay --wallet-scores` (`engines/wallets.py`) scores wallets by our simulated copy net. On v0.2.3 → rc.1 copying every wallet lost (−4.67 / −2.01 SOL over 4,003 / 1,286 closed copies) and the top v0.2.3 wallets lost on rc.1 as well, so no candidate file is written. The operator's example wallet `29yFzeBZ…` is a serial **creator** (100 launches screened across the two captures, all rejected), not a trader. Captures only hold trades of the bot's subscribed mints, so a real test needs a capture that records wallets' own trades ([`STRATEGY-PIVOT.md` §6.8](STRATEGY-PIVOT.md#68-stop-loss-sweep-wallet-scores-and-the-capture-rule-tool-2026-10-20)).
* **Dependencies:** FEAT-51, FEAT-52 (watch list and momentum check), a capture recorded with `configs/capture.json` that has trade flow for watched mints. **Impact:** more entry evidence at no extra message cost; per-wallet results visible in `pumpfun-audit pnl --group-by strategy`. Copy trading as its own lane stays off ([`RELEASE-GATE.md` §3.5](RELEASE-GATE.md#35-features-that-must-stay-off-until-proven)) until the 24I exit gate passes.

### FEAT-55: Creator Reputation Book
* **Class / Priority:** Income · P3 (tested offline 2026-10-20: **no edge**, not scheduled)
* **Goal:** Skip launches from creators whose earlier tokens lost us money, from our own records and with no network calls (idea from PumpGrok `reputation.py`, AGPL-3.0, so idea only).
* **Evidence:** `DevWalletProfile.rug_history_count` is checked by the screener but never set: `bot/enrichment.py` builds the profile without it, and none of the 24,521 screening records in the two captures has `creator_rugs` above 0. The check is dead code.
* **Design (as tested):** a book keyed by creator (the screening record's `creator`), filled from closed positions in `audit_trail.jsonl`. A creator is blocked after one losing position; the PumpGrok rule ("token fell ≥ 60%") was tested too. Clean creators expire after 30 days.
* **Offline test** (`STRATEGY-PIVOT.md` §6.5):
  - v0.2.3 (1,697 launch-mode positions): walking forward, the book blocks 203 positions worth −0.044 SOL. A random 203 would be worth −0.070, so the blocked ones were *better* than average.
  - rc.1 (118 momentum positions): only 2 creators were bought twice, because the serial-launcher screen already rejects repeat creators. The v0.2.3 book would block 6 rc.1 positions worth +0.002 SOL.
  - The "fell ≥ 60%" rule never fires on our entries (2 of 1,229 tokens): an early curve cannot fall 60% below a ~30 SOL entry because its floor is the ~28 SOL launch market cap.
* **Decision:** don't build it. Either delete `rug_history_count` from the screen or fill it from a source with real rug data; revisit only if a capture shows repeat creators among bought tokens.

### FEAT-56: Sniper-Volume & Wallet-Diversity Entry Filters
* **Class / Priority:** Income · P2 (recorded in rc.2; gate only after an unseen-capture test)
* **Goal:** Skip momentum entries whose "demand" is one wallet or a burst of snipers that will dump (idea from PumpGrok `analyzer.py`).
* **Measures** (all exclude the creator and our wallet):
  - `top_buyer_share`: the largest buyer's share of the buy volume seen before the entry.
  - `wallet_diversity`: `unique_buyers / buys × (1 − top_buyer_share)`. One wallet splitting its buys, or one whale, scores low.
  - Sniper volume: the SOL that entered the curve before the first trade we see. **No capture sees the first slots** (for 90% of mints the first recorded trade came more than 3.3 s after the create), so a true sniper *count* cannot be measured; rc.2 records `first_poll_sol_growth` (create → first curve poll) as the proxy.
* **Offline test** (`STRATEGY-PIVOT.md` §6.5), compared with keeping a random share of the same size:

  | Keep rule | v0.2.3 replay | rc.1 replay | rc.1 paper |
  |---|---|---|---|
  | none (all positions) | +0.058 / 117 | −0.080 / 105 | −0.099 / 118 |
  | `top_buyer_share` < 0.5 | +0.071 / 98 (+0.023 vs random) | −0.027 / 67 (+0.024) | −0.046 / 84 (+0.025) |
  | `wallet_diversity` ≥ 0.3 | +0.073 / 109 (+0.019) | −0.028 / 82 (+0.035) | −0.062 / 96 (+0.018) |
  | inflow before the first seen trade < 5 SOL | +0.086 / 110 (+0.031) | −0.043 / 77 (+0.016) | −0.035 / 87 (+0.038) |
  | all three | +0.099 / 91 (+0.054) | −0.004 / 47 (+0.032) | −0.006 / 58 (+0.043) |

  Net SOL / positions kept; replay is `configs/canary.json` (drift guard on), tip 0. "vs random" is the kept net minus the same share of the total.

  Each rule beats a random cut on all three sets, but none turns rc.1 positive, the samples are small, the thresholds are round numbers that were not tuned, and the inflow measure means different things in the two captures (≈ 3.5 s of snipers in v0.2.3, everything before promotion in rc.1, which overlaps the rc.2 drift guard).
* **Design:** rc.2 records `top_buyer_share`, `wallet_diversity`, `first_poll_sol_growth` and `first_poll_age_seconds` in every momentum buy's `entry_metrics` (`OrderFlowEngine.buy_flow_concentration`, `WatchEntry.first_polled_real_sol`). Nothing gates on them yet. If the rc.2 capture (unseen) confirms the edge, add `momentum_max_top_buyer_share` and `momentum_min_wallet_diversity` (0 = off) to `strategies/signal.py`, model them in replay, and Stage 0 them like any money-path change.
* **Dependencies:** FEAT-52. **Impact:** at best it trims the worst momentum entries; on its own it does not make the lane profitable.

### FEAT-57: Wash-Trade Detection As A Buy Filter
* **Class / Priority:** Income · P3 (recorded in rc.2; tested offline 2026-10-20: **no consistent edge**, not gated)
* **Goal:** Refuse a momentum entry whose "demand" is wallets trading against themselves, which looks like follow-on buying but leaves no buyer to sell to. This is the defensive reading of launch-relay's "organic buyer detection"; we detect wash trading, we never do it.
* **Evidence:** the FEAT-26 `SybilWashTradingDetector` (`strategies/cluster.py`) never runs in practice: `bot/enrichment.py` only calls it when the API coin record carries `funding_links`, which Pump.fun does not send. Our own trade flow for a promoted mint is the data we actually have.
* **Measures** (`OrderFlowEngine.round_trip_flow`, the retained flow before the entry, creator and our wallet excluded):
  - `round_trip_wallets`: wallets that both bought and sold.
  - `round_trip_share`: each wallet's matched volume, `2 × min(bought, sold)`, over all volume; 1.0 means every SOL in came back out of the same wallets.
  - `quick_flips`: a wallet reversing direction within 2 s. PumpPortal trade messages carry no slot, so this receive-time window stands in for "buy and sell in one slot".
  - Not measured: shared funders. That needs a funding lookup per wallet (`getSignaturesForAddress` + `getTransaction`), which is too slow and too many RPC calls for the 1.5 s entry path; revisit with Geyser (FEAT-39) or as an offline enrichment of captures.
* **Offline test** (`data/analysis-2026-10-20/wash.py`, `STRATEGY-PIVOT.md` §6.6), skipping flagged entries and comparing the kept net with a random cut of the same size:

  | Skip rule | v0.2.3 replay (117) | rc.1 replay (105) | rc.1 paper (118) |
  |---|---|---|---|
  | `round_trip_share` > 0.1 | skips 42, edge +0.061 | skips 35, edge −0.001 | skips 39, edge −0.023 |
  | `round_trip_share` > 0.2 | skips 32, edge +0.052 | skips 28, edge −0.000 | skips 33, edge −0.020 |
  | `round_trip_share` > 0.4 | skips 18, edge +0.040 | skips 19, edge +0.009 | skips 18, edge −0.002 |
  | `round_trip_wallets` ≥ 2 | skips 37, edge +0.044 | skips 29, edge −0.006 | skips 34, edge −0.009 |
  | `quick_flips` ≥ 1 | skips 21, edge +0.043 | skips 25, edge −0.018 | skips 26, edge −0.012 |

  It helps on the v0.2.3 replay and is no better (mostly worse) than a random cut on rc.1, including the paper run, which is the set closest to live. v0.2.3 has no paper rows: its launch-mode buys had no flow before the entry.
* **Decision:** keep recording the three inputs in every momentum buy's `entry_metrics`; gate nothing. Re-test on the rc.2 capture; add `momentum_max_round_trip_share` (0 = off) only if it beats a random cut there and on rc.1.
* **Dependencies:** FEAT-52, FEAT-56 (same recorded-inputs pattern). **Impact:** at most a small trim; no evidence yet that it changes the lane's result.

### FEAT-59: Pullback Entry After The First Dump
* **Class / Priority:** Income · P2 (logged as shadow variants in rc.3; not a trading lane)
* **Goal:** Strategy #5 of the "top 10" review: skip the launch candle, let the first wave of snipers sell, and buy the base when buying comes back. It targets our main loss directly (rc.1: 55 stop-loss exits, many filled 8%+ above the signal).
* **Design** (`strategies/shadow.py`): a shadow variant with `"kind": "pullback"` (trade feed of subscribed mints) or `"kind": "pullback_curve"` (watch-poller curve reads, every watched mint, no billed subscription). Fires once per mint when the market cap peaked at ≥ `pullback_min_peak_market_cap_sol` (40), sits `pullback_min/max_drawdown_pct` (30–70%) below that peak, made no new low for `pullback_min_base_seconds` (10), is `pullback_min_rebound_pct` (3%) off the low, saw ≥ `pullback_min_net_inflow_sol` (0.2) over `pullback_window_seconds` (15; curve kind: real SOL change; trade kind: from ≥ `pullback_min_unique_buyers` other wallets), within `pullback_min/max_token_age_seconds` (30–900). The FEAT-56/57/60/61 filters can be added.
* **Evidence so far:** trade-feed kind on v0.2.3 / rc.1 (`--shadow-scan`): 10–11 signals a day, below a random cut of the baseline in 3 of 4 halves. The curve kind needs `watch` polls (rc.2 captures on): 1 signal in the first 1.5 h of rc.2. "Community chat stays active" is not checkable.
* **Next:** read out the four curve variants on the rc.3 capture and pilot; only a clearly positive, better-than-random result earns a real entry path and a 72 h paper pilot.

### FEAT-60: Buy-Timing (Drizzle / Burst) Inputs
* **Class / Priority:** Income · P3 (recorded in rc.3; offline: **no edge**)
* **Goal:** Strategy #9: tell volume bots that keep a coin on the front page ("drizzle": small buys every 20–90 s; "burst": packed buys every few seconds) from independent buyers.
* **Design:** `OrderFlowEngine.buy_timing` over the retained buys (creator and our wallet excluded): `timing_buys`, `buy_gap_median_seconds`, `buy_gap_cv` (needs ≥ 3 buys), `burst_share` (largest share inside 5 s), `buy_size_cv`, `small_buy_share` (< 0.05 SOL). Recorded on momentum buys and shadow signals; shadow filters `min_buy_gap_cv`, `max_burst_share`, `min_buy_size_cv`, `max_small_buy_share` (a missing metric leaves its filter unapplied); `engines/cuts.py` rebuilds them for `--keep`.
* **Evidence:** on v0.2.3 and rc.1 no filter beat a random cut in both halves (e.g. `max_burst_share` 0.5: +0.007 / −0.009 and +0.007 / −0.037). Re-test on rc.3; do not gate.

### FEAT-61: Create-Slot Bundle Proxy
* **Class / Priority:** Income · P3 (recorded in rc.3; untested)
* **Goal:** Strategy #10: skip launches where many wallets took a large share of supply in the create slot (bundled launches).
* **Design:** `HolderDistribution.early_holder_cluster` on the screening holder snapshot (about 1 s after the create): `early_holders` (non-creator, non-curve accounts with ≥ 1% of supply) and `early_holder_pct`. The creator's token account is matched by its initial-buy balance, since `getTokenLargestAccounts` returns token accounts, not owners. Recorded in every screening capture record and on momentum buys; shadow filters `max_early_holders` / `max_early_holder_pct`.
* **Limits:** no funding links (the BubbleMaps view needs a funder lookup per wallet, too slow for the entry path); only the top 20 accounts are returned. No capture before rc.3 has the fields.

### FEAT-62: Moonshot (Solana) As A Second Venue, Capture First
* **Class / Priority:** Income · P3 (proposed 2026-10-20; not scheduled; no code)
* **Goal:** Find out whether the claim that Moonshot's curated, lower-volume launches give "cleaner" momentum signals than Pump.fun is true for us, after our 1.5 s delay and our costs, before writing any execution code.
* **Why this venue and not the others reviewed:** Moonshot is on Solana, so the wallet, RPC pool, Jito path, cost model, audit trail, replay engine, watch → poll → confirm pipeline, exits and shadow variants all carry over (roughly 80% of the bot). The alternatives were rejected on effort or fit:
  - Axiom / Fomo: trading front-ends with no public API for leaderboards or wallet data. Their "smart money" ranking is what `pumpfun-replay --wallet-scores` (FEAT-54) already computes from our captures, and copying captured wallets lost −4.67 SOL (v0.2.3) and −2.01 SOL (rc.1). Use them by hand only, to find candidate wallets for FEAT-54 scoring.
  - Four.meme (BNB) / SunPump (Tron): everything below `strategies/` is Solana-specific (`sdk/`, `infra/rpc_pool`, `streams/`, costs, rent, reconciliation, keys), so this is a second bot behind a chain-abstraction layer (Phase 5-sized), with an unproven "smaller bot cartels" edge.
  - Exchange IDOs (Polkastarter, Binance Launchpad): manual KYC and allocations, days-long holds, no bot API; none of the curve or order-flow logic applies.
  - Moonshot on Base is EVM and falls under the Four.meme verdict.
* **Design, in three gated phases** (each phase starts only if the previous one passes):
  1. **Read-only recorder (no capital, no execution code).** A Moonshot program / curve-account decoder in `sdk/` pinned to real mainnet account bytes in tests (as for PumpSwap, BUG-123), with the same sanity checks as BUG-104/108/124 (owner, reserves, quote mint). A create and curve source written to the existing capture format (`event: "create"`, `curve_poll`, trades), tagged `venue: "moonshot"`. PumpPortal does not carry Moonshot, so the source is either polling the program's accounts over `rpc_pool` (as the watch poller does) or, later, a Geyser feed (FEAT-39). The program ID, account layout, fee schedule and migration target must be read from mainnet and the official IDL, not assumed.
  2. **Offline evaluation.** A 24–48 h capture, then `pumpfun-replay` with the confirmed-momentum config and `--shadow-report --shadow-scan` with the momentum and `pullback_curve` variants, and `--keep` rules. Pass: a rule beats a random cut of the baseline in both halves (`--split-at mid`), net of modelled costs, and it trades often enough to matter (launch volume is much lower than on Pump.fun, so report trades per day next to net).
  3. **Execution (only after phase 2 passes).** Buy and sell builders checked against real mainnet transactions, a `venue` field on positions, trade records and `pumpfun-audit pnl --group-by`, the venue's migration exit, then a 72 h paper pilot and the normal Stage 0 gate (`RELEASE-GATE.md` §3.1) before any capital.
* **Risks:** fewer launches means fewer trades, so a small edge may not cover fixed costs; the "cleaner signal" may just be fewer data points; a second venue doubles the data and cost surface the operator has to watch. The decision rules are the same as on Pump.fun (AGENTS learnings "Beat a random cut", "Model the latency you pay").
* **Dependencies:** none for phase 1; FEAT-58 / FEAT-59 shadow tooling for phase 2. Do not start it while the rc.2 / rc.3 Pump.fun captures and the pre-graduation pilot are still unread. **Impact:** an evidence-based answer on a second Solana venue at the cost of a recorder and one capture; no trading change until phase 3.

### FEAT-63: Funding-Source Lookup For The Cluster Analyser
* **Class / Priority:** Income · P3 (proposed 2026-10-20, split out of `FEATURES.md` §27; not scheduled)
* **Goal:** Make the FEAT-26 funding-cluster and sybil analyser (`strategies/cluster.py`) run on live tokens.
* **Evidence:** `bot/enrichment.py` only builds the funding graph when the Pump.fun API record carries `funding_links` (or a ready `cluster_analysis`); the API never sends either, so the analyser has never run outside tests.
* **Design:** find each top holder's first funder (`getSignaturesForAddress` + `getTransaction`, bounded, through `rpc_pool`) and pass the edges as `funding_links`. Too slow for the 1.5 s momentum entry path, so run it on the slower lanes (pre-graduation, or momentum after promotion) or offline on captures first; record the result and gate only if it beats a random cut on two captures.
* **Dependencies:** FEAT-61 (holder snapshot); FEAT-39 would make it cheaper. **Impact:** the BubbleMaps-style bundle check that FEAT-57 and FEAT-61 cannot do.

### FEAT-64: Post-Graduation PumpSwap Long-Tail Recorder, Capture First
* **Class / Priority:** Income · P3 (proposed 2026-10-21; not scheduled; no code)
* **Goal:** Test the "less-watched venue" idea cheaply: do coins that graduated to PumpSwap at least a day ago (long-tail pools the big searchers ignore) give a momentum or pullback edge after our 1.5 s delay and costs?
* **What exists:** the PumpSwap pool decoder and sell path (`sdk/pumpswap_execution.py`, BUG-123), used only to exit held coins after migration. Buying on PumpSwap is not built.
* **Design, in three gated phases** (each starts only if the previous one passes):
  1. **Read-only recorder (no capital, no buy code).** Collect mints that graduated ≥ 24 h ago (from `subscribeMigration` / curve `complete` events in our captures, or the Pump.fun API), poll their PumpSwap pool reserves in batches over `rpc_pool` (as the watch poller does), and write `pool_poll` records tagged `venue: "pumpswap"` in the existing capture format. Reuse the pool decoder and its sanity checks, pinned to real mainnet account bytes in tests. Trade flow, if needed, from pool polls or a billed trade subscription for a small budget of pools only.
  2. **Offline evaluation.** A 24–48 h capture, then replay / `--shadow-scan` of the momentum and `pullback_curve` rules on pool prices, with PumpSwap fees and the round-trip rent and network fee in the cost model. Pass: a rule beats a random cut of the baseline in both halves (`--split-at mid`), net of costs, and trades often enough to matter (report trades per day next to net).
  3. **Execution (only after phase 2 passes).** A PumpSwap buy builder checked against real mainnet transactions, `strategy: "pumpswap"` on records and in `pnl --group-by strategy`, a 72 h paper pilot and the Stage 0 gate (`RELEASE-GATE.md` §3.1).
* **Risks:** long-tail pools are thin, so 0.02 SOL plus about 0.002 SOL fixed cost per round trip is a large share; "stable fundamentals" are rare among graduated meme coins, and many of these pools are slowly bleeding out or abandoned; order splitting does not help at our size (each split pays the network fee again).
* **Dependencies:** none for phase 1; FEAT-58 / FEAT-59 shadow tooling for phase 2. Do not start before the rc.3 capture is read out. **Impact:** an evidence-based answer on a second, less-contested market on the same chain, reusing the PumpSwap code we already have.

### FEAT-65: Slow Lane, Daily-Bar Trend On Liquid Solana Tokens Via Jupiter
* **Class / Priority:** Income · P3 (proposed 2026-10-21; a deliberate change of direction, considered only if the rc.3 Pump.fun lanes are also NO-GO). Phase 0 data recorder shipped in rc.3 ([`FEATURES.md` §37](../FEATURES.md)); design steps 2–5 below are not built
* **Goal:** A strategy where the edge is analysis and discipline rather than speed: hours-to-days holds on liquid Solana tokens (SOL, JUP and similar), where our 1.5 s latency and per-trade fixed costs barely matter.
* **Why it is separate:** everything in the bot today is built for minutes-old bonding curves (curve math, order flow, watch TTL, 1 s refresh, exits in seconds). This lane needs its own data, backtester and position logic.
* **Phase 0, data (shipped in rc.3, record-only):** `pumpfun-recorder --jupiter-quotes` samples Jupiter round-trip quotes (buy SOL → token, then sell those tokens back) at 0.02 / 0.1 / 0.5 SOL every 5 min for `configs/slow_lane_tokens.json`, with route, pools, price impact, round-trip cost, Jupiter price / liquidity and priority-fee samples for the quoted pools; `--backfill-bars` downloads GeckoTerminal daily / hourly bars. Both keyless (`lite-api.jup.ag`, GeckoTerminal public API), in their own process and files (RUNBOOK §6.4). A quote is valid only when taken, so these series cannot be fetched later; bar history can. Limits found on 2026-10-21: the keyless Jupiter API allowed 5 requests per ~10 s, and GeckoTerminal's public history ends after about 6 months (a multi-year backtest needs another bar source, e.g. a free CoinGecko demo key, or monthly re-runs to extend the series).
* **Design:**
  1. **Data.** OHLCV history and live bars for a fixed, reviewed token list (Jupiter or Birdeye price APIs, keys in their own env variable and never in URLs; `ops/redact.py` for anything persisted). Phase 0 above covers the quote / cost side and 6 months of bars.
  2. **Backtester.** A bar-based engine (not `engines/replay.py`, which replays stream events) with fees, swap price impact and slippage from Jupiter quotes, walk-forward splits and a random-entry baseline.
  3. **Strategy.** A simple trend / regime rule (e.g. moving-average or breakout with a volatility-scaled stop and size), long-only, one position per token, in a new `strategies/` module behind the existing risk pipeline (daily breaker, exposure caps).
  4. **Execution.** A Jupiter swap client in `sdk/` (quote → swap transaction, priority fee, no Jito needed at these holds), position records with `strategy: "slow"`, reconciliation and net PnL as for the other lanes.
  5. **Gate.** Walk-forward backtest net positive on at least two unseen periods and better than the random-entry baseline, then a paper run of several weeks (trade count is low), then the normal Stage 0 / Stage 1 gates.
* **What carries over:** wallet and keys, `infra/rpc_pool`, the cost model, audit trail, `pumpfun-audit pnl` and reconciliation, risk breakers, alerts and the terminal dashboard.
* **Risks:** edges in liquid assets are small and regime-dependent (expect low single-digit returns, not doubling); few trades make evidence slow to collect; overfitting a backtest is easy (same rule as the AGENTS learning "Beat a random cut"). Roughly Phase 5-sized work.
* **Dependencies:** the rc.3 verdict (`STRATEGY-PIVOT.md` §6); a Jupiter swap client; ideally Sprint 28 (`bot/run.py` decomposition) so the lane does not grow `run.py`. **Impact:** a lane that does not depend on winning latency races against searchers.

---

## 3. Web UI Platform (Required)

### FEAT-10: Web Control Dashboard (umbrella)
* **Class / Priority:** Required · P1
* **Goal:** A hosted, multi-tenant, Material Design 3 web dashboard that replaces the terminal UI for day-to-day operation on desktop and mobile.
* **Status:** not built. Until 2026-10-20 `FEATURES.md` §13 listed it as implemented; that entry was moved back here.
* **Re-scope:** FEAT-10 is now an umbrella. Its delivery is split into FEAT-31 (Agent API), FEAT-32 (control plane), FEAT-33 (PWA), FEAT-34 (orchestrator), FEAT-35 (persistence), FEAT-36 (key ingestion), and FEAT-37 (docs portal). The Telegram remote-control bot was moved out into **FEAT-45**. The earlier "in-app Markdown renderer" idea is replaced by the static docs site in FEAT-37.
* **Capabilities kept from the original proposal:** start / pause / resume / stop / `sell_all`; hot strategy and risk changes without restarts; equity curve, PnL, positions, latency telemetry; audit search.
* **Prerequisites:** the funding gate ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)) and the Phase 5 refactor (Sprints 25–31), especially the typed read-model, `PAUSED`/`HALTED` lifecycle states and `BotController` (Sprint 29).
* **Impact:** Remote intervention from any device, no restarts for tuning, and a product that can be offered to hosted users.

### FEAT-31: Bot Agent API & Typed Event Stream
* **Class / Priority:** Required · P1
* **Goal:** Give each bot container a small, internal control and telemetry port so the web tier never touches the trading event loop directly.
* **Design:**
  - New `pumpfun_trading/agent/` package served by `aiohttp.web` (already a runtime dependency, so the trading image stays lean).
  - Endpoints: `GET /health`, `GET /status` (returns `BotStatusView`), `POST /commands/{pause,resume,stop,sell_all}`, `POST /config` (`ConfigPatch`), `POST /keys/envelope` (FEAT-36), `GET /events` (WebSocket of typed events from `ops/bus.py`).
  - Bound to the private container network only; mutual auth via a per-instance token issued by the orchestrator.
  - Commands delegate to `bot/control.py::BotController`; no decision logic in the agent layer.
* **Dependencies:** Sprint 29 (`bot/state_model.py`, `bot/control.py`, `ops/bus.py`).
* **Impact:** Clean process boundary; web load can never stall slot-level trading.

### FEAT-32: FastAPI Control Plane
* **Class / Priority:** Required · P1
* **Goal:** The single public entry point: authentication, tenancy, persistence, and fan-out of bot events to browsers.
* **Design:**
  - Separate deployable (`web/api/` or a `pumpfun_trading_web` package installed with the `[web]` extra), served by Uvicorn.
  - REST + WSS; Pydantic v2 models shared with the bot's typed read-model; OpenAPI used to generate the TypeScript client for FEAT-33.
  - Auth: OIDC / JWT sessions with WebAuthn passkeys as second factor; roles `owner`, `operator`, `viewer`.
  - Every mutating call is written to `audit_events` (FEAT-35) and forwarded to the instance's Agent API.
  - Serves the built PWA and the static docs site (`/docs`, FEAT-37).
* **Dependencies:** FEAT-31, FEAT-35.
* **Alternatives considered:** Litestar (viable, smaller ecosystem). See `ARCHITECTURE-DECISIONS.md` ADR-001.

### FEAT-33: Vue 3 + Vuetify MD3 Responsive PWA
* **Class / Priority:** Required · P1
* **Goal:** A visually attractive Material Design 3 dashboard usable in desktop browsers and installable on mobile.
* **Design:**
  - Vue 3 + TypeScript + Vite; Vuetify 3 with the `md3` blueprint; Pinia stores; OpenAPI-generated client; `vite-plugin-pwa` (offline shell, install prompt).
  - Views: Overview (equity, PnL, health), Positions, Trades, Controls (pause/resume/stop/sell-all with confirmation dialogs), Settings (validated config forms with contextual help links into `/docs`), Audit.
  - Charts: TradingView `lightweight-charts`.
  - Light/dark follows the system; MD3 colour tokens shared with the docs theme.
  - Tests: Vitest component tests and Playwright desktop + mobile smoke tests, mirrored under `web/`.
* **Dependencies:** FEAT-32.

### FEAT-34: Multi-Tenant Instance Orchestrator
* **Class / Priority:** Required · P1
* **Goal:** Run one isolated bot container per tenant with quotas.
* **Design:**
  - Orchestrator service behind an `InstanceBackend` protocol: Docker Engine API first, Kubernetes later.
  - Each container gets CPU/memory limits, a read-only root filesystem, no host env access, and a private network reachable only by the control plane.
  - Lifecycle: `create → provisioned → awaiting_key → running → paused → stopped → destroyed`, persisted in the `instances` table.
  - Per-tenant quotas (instances, max position size, daily loss cap) enforced before config reaches the bot's risk pipeline.
* **Dependencies:** FEAT-31, FEAT-32, FEAT-35, FEAT-46 (image).

### FEAT-35: Persistence Layer
* **Class / Priority:** Required · P1
* **Goal:** Move from JSON/JSONL-only state (`storage/status.py`, which currently inlines `trade_ledger` in the snapshot) to a queryable database for hosted mode.
* **Design:**
  - `pumpfun_trading/storage/db/` using SQLAlchemy 2.0 async + Alembic migrations.
  - PostgreSQL when hosted (TimescaleDB hypertables optional for equity and latency series); SQLite in WAL mode for local operator/dev mode.
  - Tables: `tenants`, `users`, `sessions`, `instances`, `config_versions`, `positions`, `trades`, `audit_events`, `equity_snapshots`, `alerts`.
  - JSONL dual-write continues during migration; JSONL replay datasets stay as files.
  - Installed via the `[db]` extra; the terminal mode keeps working without it.
* **Dependencies:** Sprint 29 typed read-model.

### FEAT-36: Zero-Knowledge Key Ingestion
* **Class / Priority:** Required · P1
* **Goal:** Hosted users load their wallet key without the control plane, database, logs, or disk ever seeing plaintext.
* **Design:**
  - Worker generates an ephemeral X25519 key pair at boot and publishes the public key via the Agent API.
  - Browser encrypts the key (X25519 + HKDF + AES-GCM / libsodium sealed box); control plane relays ciphertext only.
  - Worker decrypts into a `bytearray`, builds the `Keypair`, then zeroes buffers (Volatile Key Erasure norm). Container restart = key re-entry.
  - Redaction filters in `ops/logging.py` assert no base58 key material is ever logged.
* **Dependencies:** FEAT-31, FEAT-34.

### FEAT-37: Documentation Portal
* **Class / Priority:** Required · P2
* **Goal:** Publish all docs as a searchable Material-styled site and embed it in the Web UI.
* **Design:** `mkdocs.yml` authored Material-compatible and built with Zensical (Material for MkDocs as fallback until its EOL). Static output served at `/docs` by the control plane; config fields in FEAT-33 deep-link to anchors. API/SDK reference via mkdocstrings. See [`DOCUMENTATION-PLAN.md`](DOCUMENTATION-PLAN.md).
* **Dependencies:** Sprint 31 (site build), FEAT-32 (hosting).

---

## 4. Trading, Operations & UX Enhancements (Suggested)

### FEAT-38: Hot-Config Versioning, Diff & Rollback
* **Class / Priority:** Suggested · P2
* **Goal:** Make every live config change reviewable and reversible.
* **Design:** Each accepted `ConfigPatch` writes a row to `config_versions` (author, diff, reason). The UI shows a side-by-side diff and offers one-click rollback, which is itself a validated patch through the risk pipeline.
* **Dependencies:** Sprint 29 (`ConfigPatch`), FEAT-35, FEAT-33.

### FEAT-39: Production Yellowstone gRPC Transport
* **Class / Priority:** Income (conditional) · P1 — schedule in Sprint 24D if canary data shows entries lost to latency (fills well above the signal price, or tokens already pumped by the time the buy lands); otherwise after Sprint 28
* **Goal:** Real Geyser streaming instead of the WebSocket fallback.
* **Evidence:** `streams/geyser.py:600` raises `GeyserTransportUnavailableError` unless a `custom_transport` is injected; there is no gRPC dependency.
* **Design:** `streams/yellowstone_transport.py` using `grpcio` + generated Yellowstone protos (installed via the `[geyser]` extra); account filters by bonding-curve PDA (Learnings Log); reconnect with backoff; zero-copy parsing unchanged. Contract tests against recorded payloads.
* **Impact:** Lower slot latency for entries and exits.

### FEAT-40: Live Cross-Venue Arbitrage Feed
* **Class / Priority:** Suggested · P2
* **Goal:** Close mitigated **BUG-90** (`pumpfun-arb --monitor/--live` only evaluate hardcoded sample reserves).
* **Design:** Feed `strategies/arbitrage.py` with chain-read Pump.fun curve reserves and Raydium pool reserves (`sdk/raydium.py`); only `reserves_verified=True` opportunities execute (Learnings Log).
* **Dependencies:** FEAT-39 recommended.

### FEAT-41: Metrics Exporter & Dashboards
* **Class / Priority:** Suggested · P2
* **Goal:** Standard observability for operators and the hosted SRE.
* **Design:** `ops/metrics.py` (extracted in Sprint 28) exposes Prometheus metrics (slot latency, bundle landing rate, fill slippage, open exposure, circuit-breaker state) and optional OpenTelemetry traces; shipped Grafana dashboard JSON.

### FEAT-43: PnL / Tax Export & Performance Reports
* **Class / Priority:** Suggested · P2
* **Goal:** Give operators and users downloadable trade history and periodic performance summaries.
* **Design:** `pumpfun-audit export --format csv` and a Web UI report view (win rate, expectancy, drawdown, fees, per-strategy breakdown) built from the `trades` table.
* **Dependencies:** FEAT-35.

### FEAT-44: Shadow Paper-Trading
* **Class / Priority:** Suggested · P3
* **Goal:** Evaluate a candidate strategy on the live stream without risking capital.
* **Design:** Run a second `strategies/` decision pipeline against the same events, with fills simulated by `engines/replay.py` logic; compare against live in the analytics view.
* **Status:** FEAT-58 shadow variants (`FEATURES.md` §36) cover momentum-rule variants on paper; a full second pipeline compared against live is not built.

### FEAT-45: Interactive Telegram Bot
* **Class / Priority:** Suggested · P3 (deferred from FEAT-10)
* **Goal:** Mobile commands (`/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/sell_all`) on top of existing push alerts (`bot/alerts.py`).
* **Design:** Talks to the control plane API (never directly to a bot); per-user linking with a one-time code; destructive commands need confirmation.
* **Dependencies:** FEAT-32.

### FEAT-46: Docker Image & Compose for Operator Mode
* **Class / Priority:** Suggested · P2
* **Goal:** Reproducible deployment for the operator today and the base image for FEAT-34.
* **Design:** Multi-stage slim image, non-root user, healthcheck on the Agent API; `compose.yaml` with optional Postgres; documented in the deployment guide.
* **Status:** the systemd / launchd slice shipped in Sprint 24D (`deploy/`, `FEATURES.md` §31); no image or compose file yet.

### FEAT-47: Replay Analytics on Parquet + DuckDB
* **Class / Priority:** Suggested · P3
* **Goal:** Fast ad-hoc analysis of large recorded datasets.
* **Design:** `pumpfun-recorder --export parquet`; DuckDB queries from `engines/optimizer.py` for faster backtest sweeps. JSONL stays the source format.

### FEAT-48: Strategy Plugin Registry
* **Class / Priority:** Suggested · P3
* **Goal:** Add strategies without editing core code.
* **Design:** Entry point group `pumpfun_trading.strategies`, discovered alongside `strategies/presets.py`; plugins implement the `strategies/base.py` protocol and are validated at load time.

---

## 5. Prioritisation & Execution Sequence

The order follows funding first, then dependencies; it matches the sprints in [`TODO.md`](TODO.md).

1. **Phase 4b — Terminal Income Track (Sprints 24A–24D, Income).** Paper pilot and canary; **FEAT-49** net PnL and reconciliation; BUG-61 backtest fidelity and tuning on live captures; **FEAT-50** pause and daily digest; **FEAT-42** profit sweep (all three done, now in `FEATURES.md`); **FEAT-39** if latency costs entries. Phase 4c (Sprints 24E–24I): FEAT-51/52/53/58 done; FEAT-54 and the FEAT-56/57/59/60/61 gates wait for capture evidence.
2. **Phase 5 — Platform Refactor (Sprints 25–31, Required).** Sprints 25–27 (packaging, tests) run alongside Phase 4b; Sprints 28–30 (`bot/run.py` decomposition, typed state + `BotController` + event bus, persistence **FEAT-35**) start after canary Stage 1 passes; Sprint 31 docs site (**FEAT-37** build).
3. **Funding gate** ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)). Phase 6 does not start before it passes.
4. **Sprint 32 — FEAT-31 + FEAT-32.** Agent API and single-tenant control plane.
5. **Sprint 33 — FEAT-33.** Vuetify MD3 PWA MVP.
6. **Sprint 34 — FEAT-34 + FEAT-36** (with **FEAT-46** image). Multi-tenant orchestration and zero-knowledge keys.
7. **Sprint 35 — FEAT-37 embed, analytics, terminal-UI deprecation gate.**
8. **P2 follow-ups:** FEAT-38, FEAT-40, FEAT-41, FEAT-43.
9. **P3 backlog:** FEAT-44, FEAT-45, FEAT-47, FEAT-48.
10. **Venue and direction experiments (after the rc.3 read-out):** FEAT-64 (post-graduation PumpSwap recorder) and FEAT-62 (Moonshot), both capture first; FEAT-65 (slow lane) only if the Pump.fun lanes stay NO-GO after rc.3.
