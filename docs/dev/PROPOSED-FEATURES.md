# Proposed Features

Unbuilt features for trading-pump only: candidate proposals and the venue
backlog. Shipped features are in [`docs/FEATURES.md`](../FEATURES.md); the
schedule is in [`TODO.md`](TODO.md). When a feature's code ships, move it to
`FEATURES.md` and leave a pointer; for a partly built feature, list what
ships there and keep the missing parts here (AGENTS, Feature Docs Track
Code).

This list continues pumpfun-trading's (next free ID: **FEAT-81**). On
2026-10-28 it was split by owner: the venue proposals below stayed; the Web
UI platform and the engine-level proposals (FEAT-10, FEAT-31 to FEAT-38,
FEAT-41, FEAT-43 to FEAT-46, FEAT-48) moved to trading-core's
`docs/dev/PROPOSED-FEATURES.md`. The list as it stood is archived unchanged:
[archive PROPOSED-FEATURES](../archive/pumpfun-trading/dev/PROPOSED-FEATURES.md).
The entries below are copied from it as they were written; they name
pumpbot's files and commands (`strategies/copy_trading.py`, `pumpfun-replay`,
...), which are in the history at tag `v0.3.0rc8`. A proposal that needs
code which was not ported (the trade feed, the curve lanes) must port it
first ([`TODO.md`, Not ported](TODO.md#not-ported)).

**Classification** (as before): **Income** features earn measurable,
reconciled net income and outrank everything else; **Suggested** improve
function or safety. Priorities: **P1** next, **P2** after its dependencies,
**P3** backlog.

---

## 1. Catalogue Summary

| ID | Feature | Class | Priority | Sprint |
|---|---|---|---|---|
| FEAT-76 | PumpSwap post-graduation momentum lane (paper first) | Income | P1 | proposed 2026-10-28 from the rc.8 read-out ([`STRATEGY-PIVOT.md` §6.13](STRATEGY-PIVOT.md#613-rc6-to-rc8-launch-mode-pumpswap-graduations-and-the-cross-chain-market-2026-10-28)) |
| FEAT-54 | Smart-wallet discovery, copy simulation & reviewed watch list | Income | P2 | 24I (phase 1 scorer shipped) |
| FEAT-55 | Creator reputation book | Income | P3 | not scheduled (no edge) |
| FEAT-56 | Sniper-volume & wallet-diversity entry filters | Income | P2 | inputs recorded in rc.2; gate not built |
| FEAT-57 | Wash-trade detection as a buy filter | Income | P3 | inputs recorded in rc.2 (no edge yet); gate not built |
| FEAT-59 | Pullback entry after the first dump | Income | P2 | shadow variants in rc.3; entry path not built |
| FEAT-60 | Buy-timing (drizzle / burst) inputs | Income | P3 | inputs recorded in rc.3 (no edge yet); gate not built |
| FEAT-61 | Create-slot bundle proxy | Income | P3 | inputs recorded in rc.3; gate not built |
| FEAT-62 | Moonshot (Solana) as a second venue, capture first | Income | P3 | not scheduled; refocused on graduates 2026-10-29: read-out from FEAT-74 data first ([`TODO.md`](TODO.md#cross-chain-market-recorder-feat-74)) |
| FEAT-77 | On-chain migration feed as a fallback for PumpPortal | Reliability | P2 | proposed 2026-10-29; the PumpSwap pool subscription is measured (47 messages a second, every swap) and cannot tell a migration from an old graduate without dating each pool; the fallback is not built ([`TODO.md`](TODO.md#on-chain-migration-feed-feat-77-fallback-for-pumpportal)) |
| FEAT-63 | Funding-source lookup for the FEAT-26 cluster analyser | Income | P3 | not scheduled |
| FEAT-64 | Post-graduation PumpSwap long-tail recorder, capture first | Income | P3 | not scheduled |
| FEAT-65 | Slow lane: daily-bar trend on liquid Solana tokens via Jupiter | Income | — | **NO-GO** 2026-10-29: costs pass (0–37 bps, phase 0), but the pre-registered walk-forward on the Binance history lost in every counted half-year and never beat random timing (STRATEGY-PIVOT §6.15); not built |
| FEAT-39 | Production Yellowstone gRPC transport | Income (conditional) | P1 | 24D, if latency costs entries |
| FEAT-40 | Live cross-venue arbitrage feed (closes BUG-90) | Suggested | P2 | after 39 |
| FEAT-47 | Replay analytics on Parquet + DuckDB | Suggested | P3 | backlog |

Built without a proposal (2026-10-30, from the rc.9 / rc.10 replays, [`STRATEGY-PIVOT.md` §6.18](STRATEGY-PIVOT.md#618-rc9-and-rc10-replays-a-second-lane-and-wider-take-profits-2026-10-30)): FEAT-78 (the `pumpswap_instant` lane) and FEAT-79 (per-lane exits), in [`FEATURES.md` §3.1–§3.2](../FEATURES.md#31-the-pumpswap_instant-lane-feat-78-paper). Built record-only on 2026-10-31: FEAT-80, the capture of new PumpSwap pools that are not graduations ([`FEATURES.md` §2.1](../FEATURES.md#21-new-pumpswap-pools-that-are-not-graduations-feat-80-record-only)); a lane on them is not built and waits for its capture.

Moved to trading-core (2026-10-28): FEAT-10, FEAT-31, FEAT-32, FEAT-33, FEAT-34, FEAT-35, FEAT-36, FEAT-37, FEAT-38, FEAT-41, FEAT-43, FEAT-44, FEAT-45, FEAT-46, FEAT-48. Shipped and moved to `FEATURES.md` earlier (pumpfun-trading, 2026-10-20): FEAT-49, FEAT-50, FEAT-42, FEAT-51, FEAT-52, FEAT-53, FEAT-58; of those only the parts listed in [`FEATURES.md` §10](../FEATURES.md#10-what-became-of-pumpfun-tradings-features) are still here.

---

## 2. Venue Income Track (Income)

### FEAT-76: PumpSwap Post-Graduation Momentum Lane
* **Status (2026-10-28):** phase 2 (paper lane, PumpSwap paper executor priced from the pool and the fee config, replay) is **built** in trading-pump 0.4.0 and listed in [`FEATURES.md` §3–§5](../FEATURES.md#3-the-pumpswap_momentum-lane-feat-76-paper); the replay of the rc.8 rows reproduces the read-out (§6.14). Phase 1's 72 h graduation-only capture is replaced by a 72 h paper run, which records the same rows. **Not built:** phase 3 (the live buy, reconcile, the live gate). The proposal below is as it was written on 2026-10-28.
* **Class / Priority:** Income · P1 (proposed 2026-10-28; phase 1 needs no code; supersedes the first two phases of FEAT-64 for fresh graduations)
* **Goal:** trade the one signal that did not lose in rc.5 to rc.8: a coin that has just graduated to PumpSwap and is still at least 1.1–1.2× its first pool price 60–120 s after the migration, bought at the next reading, out at 1.2× (stop 0.85 or none). On 16.6 h of rc.8 data: +1.3% to +5.7% per trade at 2% cost a side in both halves, about 100 signals a day, but n = 42–72 and every 90% interval includes 0 ([`STRATEGY-PIVOT.md` §6.13](STRATEGY-PIVOT.md#613-rc6-to-rc8-launch-mode-pumpswap-graduations-and-the-cross-chain-market-2026-10-28)).
* **What exists:** graduation tracking (FEAT-73: every migrated coin's canonical pool, every 2 s for 5 minutes then 10 s, record-only), the pool decoder, `get_pumpswap_pool_states` and the PumpSwap sell path (BUG-123). Not built: a PumpSwap buy, a paper executor priced from pool reserves, a lane that acts on the graduation rows.
* **Phases, each gated on the previous one:**
  1. **More data, no code.** A 72 h capture with graduation tracking only (no launch buying: `max_active_positions` 0 or a record-only config) on a build with BUG-157 fixed; about 1,000 standard graduations. Pre-register the rule above (one signal time and threshold, one exit set, 2% a side) before reading it; pass if it is positive in both halves and its 90% interval excludes 0, against a random-entry baseline. Add a 1 s fast phase for the first 3 minutes if the RPC budget allows (the result moved with one reading of delay).
  2. **Paper lane.** `strategy: "pumpswap_momentum"`: the signal from the graduation rows, a paper buy priced from the pool reserves with the PumpSwap fee config, `paper_entry_delay_seconds` and slippage like the curve lane, exits on the same 2 s / 10 s reads, its own `entry_refusals` and `pnl --group-by strategy` row. Replay must model it (AGENTS: model the latency you pay). 72 h paper, judged with a pre-registered `verdict_rules.json`.
  3. **Live.** A PumpSwap buy builder checked against real mainnet transactions (like the sell, BUG-123), one live round trip at the smallest size reconciled, then the Stage 0 / Stage 1 gate (`RELEASE-GATE.md` §3).
* **Risks:** the edge is small next to the noise and sensitive to latency; snipers trade the migration block itself, so live fills may be worse than paper's next reading; standard graduations are about 40% of PumpPortal's migration events (the rest are empty or unrelated pools and must be filtered by pool SOL and price); a 2% cost a side is an assumption until live fills measure it.
* **Dependencies:** BUG-157 fix (rc.9). **Impact:** a lane on the same chain, wallet and code base, with on-chain prices instead of third-party quotes.

### FEAT-54: Smart-Wallet Discovery, Copy Simulation & Reviewed Watch List
* **Class / Priority:** Income · P2 (Sprint 24I, after 24H; [`STRATEGY-PIVOT.md` §2.4](STRATEGY-PIVOT.md#24-lane-3--reviewed-smart-wallets-feat-54-p2)). Phase 1 scorer shipped ([`FEATURES.md` §37](../archive/pumpfun-trading/FEATURES.md)); steps 3–6 below are not built
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
* **Dependencies:** FEAT-51, FEAT-52 (watch list and momentum check), a capture recorded with `configs/capture.json` that has trade flow for watched mints. **Impact:** more entry evidence at no extra message cost; per-wallet results visible in `pumpfun-audit pnl --group-by strategy`. Copy trading as its own lane stays off ([`RELEASE-GATE.md` §3.5](../archive/pumpfun-trading/dev/RELEASE-GATE.md#35-features-that-must-stay-off-until-proven)) until the 24I exit gate passes.

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
* **Update (2026-10-29):** the question has moved. Launch buying on Pump.fun is NO-GO (§6.13) and the one positive signal is post-graduation (FEAT-76), so the Moonshot question is whether its *graduates* behave like PumpSwap's after costs, not its launches. Moonshot graduates migrate to open AMMs (Raydium or Meteora; the target and its fees are to be read from mainnet), whose new pools the FEAT-74 market recorder already discovers through GeckoTerminal. Phase 1 therefore starts as a read-out of recorder data (TODO, FEAT-74), with no new decoder. It is very small: 18 Moonshot pools (`moonshot` 10, `moonit` 8) against 2,866 PumpSwap pools in rc.8's 38 h ([`STRATEGY-PIVOT.md` §6.17](STRATEGY-PIVOT.md#617-launchpads-in-the-rc8-cross-chain-data-2026-10-29)), so no pre-registered verdict (≥ 100 positions) is reachable in a reasonable run; FEAT-76's own count is near that minimum on 72 h of Pump.fun graduates. Revisit only if its share grows. A buy path would be a separate trading-core module (Raydium / Meteora pool maths, fees and builders), not a lane here.

### FEAT-77: On-Chain Migration Feed As A Fallback For PumpPortal
* **Class / Priority:** Reliability · P2 (proposed 2026-10-29; no code)
* **Goal:** keep following graduates when PumpPortal fails. Today its `subscribeMigration` is the module's only source of migrations, and it has failed twice: a half-open socket that delivered nothing for 3 h (BUG-150) and refusals a reconnect did not clear (BUG-156).
* **Not the goal: speed.** PumpPortal's migration event reached the module 0.3–1.1 s after the migration's block in the rc.9 data (§6.16's sample), and the FEAT-76 rule acts 60 s after the migration. A Geyser / Yellowstone feed (FEAT-39) is not needed for this.
* **Design:**
  1. **Measure first.** A migration is one transaction: Pump.fun's `migrate` calls PumpSwap's `create_pool`. Candidate subscriptions, each measured for messages and bytes per hour, and the provider's billing for them, before any choice: `logsSubscribe` mentioning the Pump.fun program (filter on the `migrate` log), and `programSubscribe` on the PumpSwap program filtered to pool accounts (`dataSize`, base or quote mint). Check whether swaps rewrite the pool account (it holds addresses and config; the reserves sit in the vault token accounts), since that decides whether `programSubscribe` is a trickle or a firehose.
  2. **Record-only.** The chosen subscription runs next to PumpPortal and writes `migration` rows tagged with their source; a read-out compares both feeds (missed, late, duplicate migrations) over at least 24 h.
  3. **Fallback.** `MigrationFeed` takes migrations from either source, de-duplicated by mint, and reports which source is degraded; trading-core's health and alerts are unchanged.
* **Dependencies:** the RPC provider's WebSocket limits and billing. **Impact:** no blind runs when PumpPortal is down; no change to any decision.

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
* **Class / Priority:** Income · P3 (proposed 2026-10-21; a deliberate change of direction, considered only if the rc.3 Pump.fun lanes are also NO-GO). Phase 0 data recorder shipped in rc.3 ([`FEATURES.md` §37](../archive/pumpfun-trading/FEATURES.md)); design steps 2–5 below are not built
* **Status (2026-10-29): NO-GO, closed.** The gate in Design 5 was tested as a pre-registered walk-forward on the Binance history and failed every condition ([`STRATEGY-PIVOT.md` §6.15](STRATEGY-PIVOT.md#615-feat-65-walk-forward-on-the-binance-history-no-go-2026-10-29)). Steps 2–5 will not be built for this rule; a different rule would need its own pre-registered test first.
* **Goal:** A strategy where the edge is analysis and discipline rather than speed: hours-to-days holds on liquid Solana tokens (SOL, JUP and similar), where our 1.5 s latency and per-trade fixed costs barely matter.
* **Why it is separate:** everything in the bot today is built for minutes-old bonding curves (curve math, order flow, watch TTL, 1 s refresh, exits in seconds). This lane needs its own data, backtester and position logic.
* **Phase 0, data (shipped in rc.3, record-only):** `pumpfun-recorder --jupiter-quotes` samples Jupiter round-trip quotes (buy SOL → token, then sell those tokens back) at 0.02 / 0.1 / 0.5 SOL every 5 min for `configs/slow_lane_tokens.json`, with route, pools, price impact, round-trip cost, Jupiter price / liquidity and priority-fee samples for the quoted pools; `--backfill-bars` downloads GeckoTerminal daily / hourly bars, or Binance public klines with `--bar-source binance`. Both keyless (`lite-api.jup.ag`, GeckoTerminal public API), in their own process and files (RUNBOOK §6.4). A quote is valid only when taken, so these series cannot be fetched later; bar history can. Limits found on 2026-10-21: the keyless Jupiter API allowed 5 requests per ~10 s, and GeckoTerminal's public history ends after about 6 months (a multi-year backtest needs another bar source). CoinGecko's free Demo plan was checked and is no fix: its OHLC history is limited to the past 365 days (full history needs a paid plan). `--bar-source binance` (Binance public spot klines, keyless) gives each `<SYMBOL>USDT` pair since its listing: about 2.5 years for most of the list, 6 for SOL; mSOL and jitoSOL have no pair.
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

## 3. Venue Enhancements (Suggested and conditional)

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

### FEAT-47: Replay Analytics on Parquet + DuckDB
* **Class / Priority:** Suggested · P3
* **Goal:** Fast ad-hoc analysis of large recorded datasets.
* **Design:** `pumpfun-recorder --export parquet`; DuckDB queries from `engines/optimizer.py` for faster backtest sweeps. JSONL stays the source format.

---

## 4. Sequence

1. **FEAT-76** paper run, then its live phase ([`TODO.md`](TODO.md#feat-76-pumpswap-post-graduation-momentum-lane)).
2. The research read-outs that could feed a proposal: graduation paths (FEAT-73 data, FEAT-64), cross-chain (FEAT-74 data), the slow lane walk-forward (FEAT-65).
3. Everything that needs the trade feed or a curve lane (FEAT-54 to FEAT-61) only with new evidence that a curve-side rule beats costs; launch mode is NO-GO.
4. FEAT-39 only if live fills show latency costs entries; FEAT-40 only with a lane that needs it; FEAT-62 as a separate trading-core module, capture first; FEAT-47 when a capture is too big for JSONL tools.
