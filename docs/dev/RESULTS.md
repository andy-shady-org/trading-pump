# Results log

Every run, replay and study of trading-pump, and of pumpfun-trading before
it, with its data, its numbers and its verdict. Oldest first: a new result
is a new row in the table and a new numbered section, and nothing already
written is edited back (a correction is a new dated line).

- **Where this came from.** This page continues
  [`STRATEGY-PIVOT.md`](STRATEGY-PIVOT.md) §6. On 2026-10-31 that section
  moved here whole and unedited, with its `6.N` numbering, so every link to
  a §6.N section keeps working and the next result is §6.20.
- **Old names stay old.** Entries written before 2026-10-31 use the names of
  their time:
  - "Stage 0" means the paper stage, now **Stage 1**; "Stage 1" the live
    canary, now **Stage 2**; "Stage 2" scale-up, now **Stage 3**
    ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate)).
  - "PASS", "FAIL", "adopted" and "not evidence" are older verdict words;
    new entries use **GO**, **NO-GO** or **INCONCLUSIVE**.
  - Runs are named by the release candidate of the time (rc.1 to rc.11).
    The "rc.12" that §6.19 plans is the next counted run, now named
    `pump-12`.
- **Related pages.** A counted run's pre-registration and read-out are in
  [`runs/`](runs/README.md); what is running now is in
  [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status); the lanes the
  results led to are in [`../STRATEGY.md`](../STRATEGY.md).

**Adding a result:**

1. Add a row to the table: date, data, lane, config, positions, net SOL,
   win rate, verdict.
2. Add a section `### 6.N <what it was> (<date>)` with the question, the
   data (files, hours in UTC, release tags), the results and the reading.
3. For a counted run, link its record in [`runs/`](runs/README.md) and
   complete the record's read-out there too.

## 6. Results log

| Date | Data | Lane | Config | Positions | Net SOL | Win rate | Verdict |
|---|---|---|---|---|---|---|---|
| 2026-10-18 | v0.2.3 24 h capture | launch | v0.2.3 canary | 1,675 | −0.579 | 10.3% | baseline (FAIL) |
| 2026-10-18 | same, 1st half (tuning) | momentum | `momentum` preset defaults | 21 | +0.008 | 66.7% | — |
| 2026-10-18 | same, 2nd half (held out) | momentum | `momentum` preset defaults | 19 | −0.022 | 36.8% | defaults not positive out of sample |
| 2026-10-18 | same, 1st half (tuning) | momentum | `configs/canary.json` | 62 | +0.086 | 54.8% | best of 162-point grid |
| 2026-10-18 | same, 2nd half (held out) | momentum | `configs/canary.json` | 70 | +0.023 | 41.4% | positive out of sample |
| 2026-10-18 | full 24 h | momentum | `configs/canary.json`, tip 25k | 132 | +0.132 | 49.2% | replay PASS (provisional) |
| 2026-10-19 | v0.3.0-rc.1 capture, 12.7 h (paper) | momentum | `configs/capture.json` | 65 | −0.100 | 21.5% | **paper FAIL** |
| 2026-10-19 | same, replay (rc.1 engine) | momentum | `configs/canary.json`, tip 0 | 62 | −0.084 | — | **replay NO-GO**; parity GAP +0.016 (allowed ±0.010) |
| 2026-10-19 | same, 13.1 h, replay (BUG-121 fix) | momentum | `configs/canary.json`, tip 0 | 63 | −0.090 | — | NO-GO; parity gap +0.023 → +0.014 (still GAP) |
| 2026-10-19 | v0.2.3 24 h, replay (BUG-121 fix) | momentum | `configs/canary.json`, tip 0 | 132 | +0.062 | — | was +0.139: half of the old edge was replay optimism |
| 2026-10-20 | v0.3.0-rc.1 capture, full 24.2 h (paper) | momentum | `configs/capture.json` | 118 | −0.099 | 29.7% | **paper FAIL** |
| 2026-10-20 | same, last 11.5 h only (unseen by the sweeps) | momentum | `configs/capture.json` | 53 | +0.001 | 39.6% | break-even |
| 2026-10-20 | same, 24.2 h, replay | momentum | `configs/canary.json`, tip 0 | 112 | −0.077 | — | NO-GO; parity gap +0.022 (allowed ±0.010) |
| 2026-10-20 | same, audit trail, drift guard applied after the fact | momentum | + `momentum_max_entry_drift_pct` 0.08 | 101 | −0.046 | — | helps in both halves (A −0.075, B +0.029), still negative |
| 2026-10-20 | rc.1 replay, FEAT-56 filters (top buyer < 50%, diversity ≥ 0.3, early inflow < 5 SOL) | momentum | `configs/canary.json`, tip 0 | 47 | −0.004 | — | beats a random cut on 3 sets; recorded in rc.2, not gated (§6.5) |
| 2026-10-20 | v0.2.3 / rc.1 replay + rc.1 paper, FEAT-57 wash inputs (skip `round_trip_share` > 0.2) | momentum | `configs/canary.json`, tip 0 | 85 / 77 / 85 | +0.094 / −0.059 / −0.091 | — | beats a random cut on v0.2.3 only; recorded in rc.2, not gated (§6.6) |
| 2026-10-20 | v0.2.3 / rc.1 replay, stop-loss sweep: `stop_loss` 0.92 (base 0.85) | momentum | `configs/canary.json`, tip 0 | 117 / 105 | +0.075 / −0.049 | — | better than the base in all four halves, by noise-sized amounts; not adopted (§6.8) |
| 2026-10-20 | same, stop armed after 5–30 s or held while buys continue | momentum | `configs/canary.json`, tip 0 | 117 / 105 | worse in every half (arming after 5 s: flat on rc.1 B, +0.0003) | — | rejected (§6.8) |
| 2026-10-20 | v0.2.3 / rc.1 replay, FEAT-56 + FEAT-57 + creator book together (rebuilt from the capture) | momentum | `configs/canary.json`, tip 0 | 64 / 39 | +0.097 / +0.004 | — | beats a random cut in all four halves; rc.1 only breaks even (§6.8) |
| 2026-10-20 | FEAT-54 copy simulation, top v0.2.3 wallets copied on rc.1 | copy (sim) | 0.02 SOL, 1.5 s, 100 bps, tip 0 | 92 copies | −0.125 | — | **no edge**: every wallet set loses at our delay and costs (§6.8) |
| 2026-10-20 | v0.2.3 / rc.1, pullback rule on the trade feed (FEAT-59), `--shadow-scan` | pullback (shadow) | `configs/capture.json`, tip 0 | 7 / 7 | −0.006 / −0.007 | — | too few signals (10–11 a day); below a random cut of the baseline in 3 of 4 halves (§6.9) |
| 2026-10-20 | v0.2.3 / rc.1, FEAT-60 buy-timing filters (gap CV ≥ 0.5, burst ≤ 50%, size CV ≥ 0.5), `--shadow-scan` | momentum (shadow) | `configs/capture.json`, tip 0 | 74–104 / 49–97 | — | — | **no edge**: none beats a random cut in both halves on either capture (§6.9) |
| 2026-10-21 | v0.3.0-rc.2 capture, 24.1 h (paper, no exit slippage) | momentum | rc.2 `configs/capture.json` | 105 | +0.014 | 32.4% | break-even; with the BUG-126 exit haircut about −0.007 (§6.10) |
| 2026-10-21 | same, replay | momentum | rc.2 `configs/canary.json` (stop 0.85), tip 0 | 107 | −0.015 | — | parity gap −0.028 → −0.007 after BUG-126 (allowed ±0.002) |
| 2026-10-21 | same, replay | momentum | rc.3 `configs/canary.json` (stop 0.92, exit 100 bps), tip 0 / modelled tip | 107 | +0.000 / −0.023 | — | **NO-GO**: stop 0.92 beats 0.85 in both halves (+0.004 / +0.011) but the lane only breaks even |
| 2026-10-21 | v0.2.3 / rc.1 / rc.2 replay, tier 1 at 1.2–1.3× (take +20–30% early) | momentum | rc.3 `configs/canary.json`, tip 0 | 117 / 105 / 106 | worse in at least one half on every capture | — | rejected (§6.10) |
| 2026-10-21 | v0.3.0-rc.2 pre-graduation pilot, 24.1 h (paper) | pre_graduation | rc.2 `configs/pregrad_pilot.json` | 2 | −0.008 | 0% | too few entries: the screen and the 10 min TTL starve the lane (§6.10) |
| 2026-10-23 | v0.3.0-rc.3 capture, first 45.5 h (paper) | momentum | rc.3 `configs/capture.json` (stop 0.92, exit 100 bps) | 127 | **−0.179** | 14.2% | **NO-GO**: verdict FAIL on every profit check; both halves and all 3 UTC days negative (§6.11) |
| 2026-10-23 | same, replay with `--no-circuit-breaker` | momentum | rc.3 `configs/capture.json` | 123 | −0.197 | — | parity holds: 119 of 127 matched, gap −0.018 (allowed ±0.018) |
| 2026-10-23 | same, stop-loss sweep 0.80 / 0.85 / 0.92 | momentum | rc.3 `configs/capture.json` | 123 | −0.205 / −0.203 / −0.197 | — | the stop is not the problem; no level is better in both halves |
| 2026-10-23 | same, FEAT-56/57 filters (top buyer < 50%, diversity ≥ 0.3, early inflow < 5 SOL, round trips ≤ 20%) on paper positions | momentum | rc.3 `configs/capture.json` | 39 | −0.066 | — | **fails out of sample**: below a random cut in half B (−0.023) |
| 2026-10-23 | same, shadow variants | momentum (shadow) | rc.3 `configs/capture.json` | 18–150 | −0.010 to −0.281 | 9–33% | several beat a random cut, none is near break-even |
| 2026-10-23 | v0.3.0-rc.3 pre-graduation pilot, first 45.5 h (paper) | pre_graduation | rc.3 `configs/pregrad_pilot.json` | 0 | 0 | — | **cannot fire**: 4 of ~2,100 watched curves ever reached 75% (§6.11) |
| 2026-10-23 | same, what-if: buy discovered curves in the 75–88% band (record-only rows, 10 s polls) | pre_graduation (sim) | pilot entry band, tranches, stop 0.85, 4.6% costs | 562 | ≈ −1.62 at 0.02 SOL | 37% | **no edge**: about −14% per trade, both halves negative (§6.11) |
| 2026-10-23 | FEAT-65 phase 0 quotes, 46.9 h (Jupiter, 10 tokens, 0.02 / 0.1 / 0.5 SOL) | slow lane (costs) | `configs/slow_lane_tokens.json` | 16,918 round trips | — | — | **costs pass**: median round trip 0–37 bps (Pump.fun lanes ≈ 460 bps); priority fees 0 in ~99% of slots (§6.12) |
| 2026-10-23 | FEAT-65 bars, daily, 132 days after warm-up, trend rules in SOL terms (SMA 10 / 20 / 50, measured costs) | slow lane (backtest) | 7 liquid tokens, equal weight | 71–163 switches | −4.7% / +3.8% / +7.5% | — | **no edge shown**: buy and hold +8.9%; without RAY every rule loses (−6% to −14%); half A negative for all three (§6.12) |
| 2026-10-23 | same, hourly bars (SMA 5 / 10 / 20 days), BONK and JUP left out (bad prints, gaps) | slow lane (backtest) | 5 tokens | 555–1,243 switches | −20.2% / −13.0% / +7.4% | — | whipsaw; buy and hold +46.3% (§6.12) |
| 2026-10-28 | rc.8 run A graduation rows, 16.6 h, `trading-pump replay` (in-sample) | pumpswap_momentum | `configs/paper.example.json`, swap fee 125 bps a side | 42 | +0.009 | 50.0% | **not evidence**: +1.1% per trade, verdict NO-GO (42 of 100 positions, interval includes 0) (§6.14) |
| 2026-10-28 | same, swap fee 200 bps a side | pumpswap_momentum | same | 42 | −0.003 | 50.0% | the edge is about the cost: −0.4% per trade (§6.14) |
| 2026-10-28 | same, 125 bps, `paper_entry_delay_seconds` 2 | pumpswap_momentum | same + 2 s entry delay | 33 | +0.023 | 54.5% | better, not worse, with a later fill: +3.5% per trade; NO-GO on count and interval (§6.14) |
| 2026-10-29 | FEAT-65 walk-forward, Binance daily bars 2021-08 → 2026-10-22, trend rule (SMA 10 / 20 / 50 chosen on the 730 days before each half-year), SOL terms, measured costs | slow lane (backtest) | pre-registered (`PREREGISTRATION.md` sha256 `a76d5535…`), 6–7 tokens in the counted periods | 60–180 switches a period | −0.6% / −17.3% / −17.1% / −8.6% (2024 H2 → 2026 Jan–Apr) | — | **NO-GO**: below 0 and below the random-entry p90 in all four counted periods; −37.8% compounded (§6.15) |
| 2026-10-29 | PumpSwap fee check: 94 real trades in the first 10 minutes of 11 standard rc.9 graduates, `BuyEvent` / `SellEvent` decoded (public RPC, read-only) | pumpswap_momentum (costs) | the live fee config | 94 trades | — | — | **the cost model holds**: 92 of 94 paid the module's tier, the module's pool maths reproduces real fills to 0.001 bps; the tier must use the mint's real supply (BUG-162) (§6.16) |
| 2026-10-30 | rc.9 capture, 33.4 h (2026-10-29 08:30 → 10-30 17:54 UTC, 1,097 migrations), `trading-pump replay` at 125 bps, 1.5 s entry delay, breaker `baseline` | pumpswap_momentum | rc.10 rule (ratio 1.2, 5% slippage, TP +20% / SL −15% / 30 min) | 60 | +0.061 | 60% | reference: +5.1% per trade, halves +0.9% / +9.4% (§6.18) |
| 2026-10-30 | same | pumpswap_momentum | rc.10 entry, lane exits TP **+50%** / SL −15% / 30 min (FEAT-79) | 60 | +0.071 | 38% | **adopted for rc.11**: +5.9% per trade, halves +1.5% / +10.2% (§6.18) |
| 2026-10-30 | same | pumpswap_momentum | ratio 1.1, 10% slippage, TP +50% | 111 | +0.014 | 32% | rejected: +0.6% per trade, second half −9.5% (§6.18) |
| 2026-10-30 | same | pumpswap_instant | instant band, ratio 1.00–1.10, 10% slippage, TP +50% / SL −15% / 30 min (FEAT-78) | 80 | +0.283 | 71% | **adopted for rc.11**: +17.7% per trade, halves +11.4% / +20.0%; verdict passes all but the count (80 of 100) (§6.18) |
| 2026-10-30 | rc.9 paper run, stopped by the operator after 58.4 h (2026-10-29 08:27 → 10-30 18:53 UTC), `v0.4.0rc2` on trading-core `v0.2.0` | pumpswap_momentum | `configs/rc9-paper.json` (ratio 1.2, TP +20% / SL −15% / 30 min, 0.02 SOL) | 55 | +0.034 | 58.2% | **NO-GO on the count** (55 of 100); net, halves and days pass; fails without the best 3 and on the interval (§6.19) |
| 2026-10-30 | rc.10 paper run, stopped by the operator after 9.9 h (2026-10-30 09:01 → 18:53 UTC), `v0.4.0rc3` on trading-core `v0.2.1` | pumpswap_momentum | `configs/rc10-paper.json` (rc.9's rule) | 8 | +0.004 | 50.0% | too short to judge; superseded by rc.11 (§6.19) |
| 2026-10-31 | instant-lane entries: rc.9 capture (A, 82) and rc.11 live (B, 30 Oct 18:58 → 31 Oct 08:30 UTC, 22), rc.11's rule replayed on each path | pumpswap_instant | TP +50% / SL −15% / 30 min, 2% cost a side | 82 / 22 | — | 72% / 41% | **crashes are not predictable before entry**; the pump height fell from ~2.3× to ~1.3×; +50% is the lane's weak point (§6.19) |
| 2026-11-03 | rc.11 paper run, 2026-10-30 18:58 → 11-02 19:49 UTC, `v0.4.0rc4` on trading-core `v0.2.2`; buying locked 27 of 72 h (daily 10%, then cumulative 25%) | pumpswap_momentum | `configs/rc11-paper.json` (ratio 1.2, TP +50% / SL −15% / 30 min) | 52 | −0.018 | 34.6% | **NO-GO**: adjusted −0.026, halves −0.010 / −0.016, 2 of 4 days ([`runs/rc11.md`](runs/rc11.md), §6.20) |
| 2026-11-03 | same | pumpswap_instant | instant band, ratio 1.00–1.10, TP +50% / SL −15% / 30 min | 245 | −0.477 | 40.0% | **NO-GO**: adjusted −0.512, both halves and all 4 days negative; stops filled at −44% median (§6.20) |
| 2026-11-03 | rc.11-tp20 paper run (exploratory), 2026-10-31 06:00 → 11-03 06:54 UTC; buying locked from 11-02 17:19 | pumpswap_momentum | rc.11 with TP +20% | 71 | +0.009 | 53.5% | not counted; rc.11's rule would say NO-GO (adjusted −0.002, count 71) ([`runs/rc11-tp20.md`](runs/rc11-tp20.md)) |
| 2026-11-03 | same | pumpswap_instant | rc.11 with TP +20% | 405 | −0.335 | 60.7% | not counted; on the 189 coins both runs bought, −0.144 against rc.11's −0.274 (§6.20) |
| 2026-11-03 | rc.11 capture replayed (`trading-pump replay`, 125 bps) | both | `configs/rc11-paper.json` | 305 | −0.502 | 38.7% | parity: instant matches (245 of 245 coins, 244 same exit); momentum entry prices off by 2.1% at the median (§6.20) |
| 2026-11-03 | rc.8, rc.9, rc.11, rc.11-tp20 captures, offline exit simulator (61 exit rules × 2 lanes, 105 entry variants) | both | pump-12 design gate: positive on every capture at 125 bps, not negative at 200 bps | — | — | — | **nothing passes** on either lane; every rule loses on the rc.11 capture (§6.20) |
| 2026-11-03 | continuous capture rc.9 → rc.11-tp20, walk-forward | both | adaptive gate and selector over 6 exit rules (trade only when the best rule's last 10 closed shadow trades are positive) | 393 / 130 | −0.019 / +0.075 | — | **NO-GO by the design gate**: both lanes lose in rc.11's second half (−8.5% / −1.3% a trade); losses cut, not removed (§6.21) |
| 2026-11-03 | 902 instant graduates of rc.9, rc.11, rc.11-tp20, holders at the migration from the curve's transactions (supply map) | pumpswap_instant | identical-balance wallets, more than 7 holders, top-5 share, creator share, signers, curve time | — | — | — | **crash signal, no lane filter**: identical balances crash more (81% / 72% / 70% against 42% / 60% / 66%), but filtering them leaves the lane negative on rc.11 and rc.11-tp20 (§6.21) |
| 2026-11-03 | same, section B of the pump-12 plan on each supply-map group | pumpswap_instant | 8 coin groups × 30 exit rules (TP +10–50%, holds 2–30 min, adaptive, tiers) | — | — | — | **nothing passes** (222 combinations; best worst capture −1.2% a trade). The PumpSwap lanes are closed; pump-12 is not run (§6.21) |

### 6.1 How the thresholds were picked (Sprint 24G)
- Data: `runtime/capture/replay_capture.jsonl` (v0.2.3, 24.4 h, 25,610 create events, 10,718 screening records, 22,487 market trades on 1,229 mints). Replay: `pumpfun-replay --config configs/canary.json` (live exit stack, `ReplayCostModel`, 0.02 SOL, 2 positions, 0.05 SOL exposure), `entries_from: confirmed`.
- Split by time: the first 12.2 h picked the values, the second 12.2 h was never used to pick them. Grid: `watch_promote_min_sol_growth` {0.5, 1.5, 3}, `momentum_min_unique_buyers` {3, 5, 8}, `momentum_min_net_inflow_sol` {0.5, 1, 2}, `min_market_cap_sol` {30, 35, 45}, `momentum_min_token_age_seconds` {20, 60}, with `momentum_min_z_score` 0 and `momentum_min_buy_ratio` 1.5. 100 of 162 points were positive on the first half; the top 8 were then run on the second half, and 5 stayed positive.
- Chosen: promotion at +3 SOL real reserve growth, ≥ 3 distinct non-creator buyers and ≥ 0.5 SOL net inflow in 30 s, age ≥ 20 s, market cap 35–75 SOL. The z-score is off: a 300 s baseline does not exist for tokens this young.
- Tip experiment in replay (full 24 h, same config): 0 lamports +0.139 SOL, 25k +0.132, 50k +0.124, 100k +0.109. The tip is not what decides the result on this lane; the canary starts at 25k lamports (`PUMPFUN_JITO_TIP_LAMPORTS=25000`) and the landing rate decides the final value.
- The `momentum` preset needs `max_token_concentration_pct` 0.5: one 0.02 SOL position is 40% of the 0.05 SOL exposure cap, so the conservative 25% refused every buy.

### 6.2 Why this is not yet a go
- **Biased data.** The capture only has trade flow for the 1,229 mints the v0.2.3 bot bought at launch; the confirmed lane can only buy among them. Tokens the old bot never bought, which a live confirmed bot would see, are missing. A capture recorded with `configs/capture.json` (confirmed mode, so it records the watched and promoted mints) is the real test.
- **Same day.** The held-out half is the same day and market as the tuning half. The go/no-go rule (§5) asks for a second capture.
- **Small numbers.** +0.023 SOL over 70 positions in the held-out half is within a few lucky trades.
- **Replay simplifications.** Promotion uses the curve derived from recorded prices and is up to one poll interval optimistic. Until BUG-121 the 1.5 s paper entry delay and the 100 bps paper penalty were not modelled at all (see §6.3).

**Next:** run `configs/capture.json` for 24 h, replay it with `configs/canary.json` unchanged, and only if it is net positive start the 72 h Stage 0 with `configs/canary.json` in paper mode.

### 6.3 v0.3.0-rc.1 capture: NO-GO (2026-10-19)
- **Data:** `runtime/capture/` on tag `v0.3.0-rc.1`, `configs/capture.json` (paper, confirmed, 0.02 SOL, 5 positions), 2026-10-18 20:36 → 2026-10-19 09:20 (12.7 h). The run kept recording afterwards.
- **Paper result:** −0.100 SOL net over 65 momentum positions, 21.5% profitable, expectancy −0.0015 SOL. Costs were 0.0014 SOL with no tips and every rent refunded, so the loss is trade selection, not friction.

| First exit | Positions | Net SOL | Average return |
|---|---|---|---|
| Stop loss | 33 | −0.143 | −21.6% (worst −52%) |
| Buy flow dried up | 22 | −0.016 | −3.5% |
| Take profit, tier 1 | 5 | +0.044 | +43.8% |
| Trailing stop | 5 | +0.015 | +15.2% |

- **Fill drift:** the median stop-loss came 15 s after the buy and sold at −17% to −26% against a −15% stop. 9 stops came within 1 s of the buy; in 3 of them the paper fill (curve read 1.5 s after the signal) was 1.3–1.7× the signal price.
- **Winners vs losers at entry (medians):** distinct buyers 6.5 vs 3, token age 52 s vs 109 s, buy/sell ratio 5.5 vs 10.4 (a very one-sided ratio is usually one wallet or a bundle).
- **Runtime (24F exit gate): PASS.** 869 watched, 148 promoted, 65 bought, 83 expired; subscriptions never above 20 and all closed; 4,661 billed trade messages, no refusals or breaker trips; RPC ≈ 0.8 req/s, p95 139 ms, no errors.
- **Replay go/no-go (frozen `canary.json`, no re-tuning): NO-GO**, −0.084 SOL over 62 positions (profit factor 0.48). The tip changes the result by ≈ 0.003 SOL.
- **Replay was optimistic (BUG-121).** `engines/replay.py` filled confirmed entries at the signal price and ignored `paper_entry_delay_seconds` and `paper_entry_slippage_bps`. With the fix (rc.2) the fill is priced at the last curve price at signal + delay, cut by the penalty, and no exit runs before the fill. On the 13.1 h data the parity gap fell from +0.023 to +0.014 SOL (allowed ±0.010; it was +0.016 on the first 12.7 h). The rest comes from curve reads that see trades the capture's trade stream does not (a few fills 1.3–1.5× above any recorded price) and from 7 unmatched positions.
- **Exploratory sweep, re-run on the fixed replay** (net SOL / positions, tip 0; picked after seeing this capture, so not evidence):

| `momentum_min_unique_buyers` | v0.2.3 24 h | rc.1 capture 13.1 h | 1st half | 2nd half |
|---|---|---|---|---|
| 3 (canary) | +0.062 / 132 | −0.090 / 63 | −0.043 | −0.050 |
| 6 | +0.079 / 108 | −0.019 / 39 | −0.010 | −0.012 |
| 8 | +0.089 / 96 | −0.003 / 32 | +0.005 | −0.010 |
| 10 | +0.068 / 85 | −0.004 / 25 | +0.007 | −0.013 |

  With the rc.1 engine, 8 buyers looked positive in every period (+0.021 SOL on the new capture). With entry latency modelled, **no buyer threshold is net positive on the new capture**. Stop-loss 0.75/0.65, a 20 s stagnation timeout, a shorter age window and a higher inflow threshold did not help either (rc.1 engine).
- **Verdict:** no Stage 0 with the current lane. Changing `momentum_min_unique_buyers` alone is not enough. Next candidates, each to be judged on hours the sweep has not seen: a cap on the buy/sell ratio, skipping the buy when the curve moved more than X% between signal and fill, and a shorter signal-to-fill latency. If none is positive on unseen data, the momentum lane has no edge at this latency and the pre-graduation paper pilot or a faster data source comes next (§4).

### 6.4 v0.3.0-rc.1 capture, full 24 h: still NO-GO; drift guard added (2026-10-20)
- **Data:** the same run as §6.3, now 2026-10-18 20:36 → 2026-10-19 20:50 (24.2 h; archive it as `runtime/archive/capture-v0.3.0rc1/` before the next run). Half **A** is the first 12.7 h (the hours the §6.3 sweep was picked on); half **B** is the last 11.5 h, which no sweep had seen.
- **Paper result:** −0.099 SOL net over 118 momentum positions, 29.7% profitable; the paper wallet went from 2.000 to 1.901 SOL, matching the audit trail. Costs were 0.0025 SOL, tips 0, every rent refunded.

| Period | Positions | Net SOL | Profitable |
|---|---|---|---|
| A: first 12.7 h | 65 | −0.100 | 22% |
| B: last 11.5 h (unseen) | 53 | +0.001 | 40% |

- **Stop losses make the whole loss:** 55 positions, −0.229 SOL. Every other exit together made +0.130 SOL. The median stop sold at −19% against a −15% stop, and 15 of them sold within 1 s of the buy.
- **Earlier ideas, checked on B (fixed replay, frozen `canary.json`, net SOL / buys):**

| `momentum_min_unique_buyers` | A | B (unseen) |
|---|---|---|
| 3 (canary) | −0.093 / 62 | +0.016 / 50 |
| 6 | −0.019 / 38 | −0.014 / 43 |
| 8 | −0.003 / 31 | −0.024 / 40 |
| 10 | −0.004 / 25 | −0.030 / 31 |

  The 8-buyer setting from §6.3 **failed out of sample**. Among the bot's own buys the ones that already had ≥ 8 buyers were positive in both halves, but a rule that *waits* for 8 buyers enters later and higher, and that removes the gain. A buy/sell-ratio cap (A −0.026, B −0.028 on the bot's own buys) and a 60 s maximum token age were worse in both halves; both are dropped.
- **The one idea that helped in both halves: skip the buy when the price ran away between signal and fill** (audit trail, the curve at the fill against the signal's market cap, net SOL / positions kept):

| Skip when the curve moved more than | A | B | 24 h |
|---|---|---|---|
| no guard | −0.100 / 65 | +0.001 / 53 | −0.099 / 118 |
| 10% | −0.077 / 61 | +0.028 / 43 | −0.049 / 104 |
| **8% (chosen)** | **−0.075 / 59** | **+0.029 / 42** | **−0.046 / 101** |
| 5% | −0.066 / 54 | +0.028 / 39 | −0.038 / 93 |

  The move here is taken from the paper fill price less the ~2.25% Pump.fun fee and paper penalty, so it is approximate. 8% keeps about as much of the gain as 5% while skipping fewer buys. The guard reduces the loss; it does not create a profit on its own.
- **Drift guard (rc.2): `momentum_max_entry_drift_pct`** (default 0 = off; 0.08 in the `momentum` preset, `configs/canary.json` and `configs/capture.json`). Momentum-lane buys only:
  - **Paper:** after `paper_entry_delay_seconds` the executor re-reads the curve and skips the buy when its market cap is more than the limit above the signal's (`entry_drift` error, no costs). The fill's drift is recorded as `entry_metrics.fill_drift_pct`.
  - **Live:** the buy is refused before sending if the curve is already past the limit, and otherwise its slippage is capped at the headroom left, so the fill cannot land above signal × (1 + limit).
  - **Replay:** a delayed confirmed entry whose fill price is past the limit is dropped, its cash and modelled costs refunded (`entry_rejections.entry_drift`, `watch_stats.drift_refused`).
  - A refused mint is dropped from the watch list and unsubscribed in both the bot and replay: the move has already happened.
- **Replay cannot judge the guard.** In replay the median fill drift is 0 and only 5 of 112 fills moved > 10%, against 14 of 118 in paper: most of the runaway fills came from curve reads that see trades the capture's trade stream misses (the remaining parity gap, +0.022 SOL on 24 h). Replayed with the guard at 0.08 the result barely changes (A −0.096, B +0.017 against −0.093 / +0.016 without it; 24 h −0.080). **The next paper capture is the only test of the guard.**
- **Operations: healthy.** 1,568 watched, 251 promoted, 118 bought, 13 dropped as non-standard curves; ≤ 20 subscriptions; 7,689 trade messages with no refusals or breaker trips; 0 ERROR lines; RPC p95 117 ms. The stream connected 7 times but `connection_loss` stayed 0 (telemetry gap, BUG-122).
- **Possible time-of-day effect.** A ran overnight in Europe, B in EU/US daytime, and B did better under every setting. One day cannot separate the hour from the settings; every buy carries its timestamp, so net PnL per hour can be compared on the next capture.
- **Verdict:** no Stage 0, no change to `momentum_min_unique_buyers`. rc.2 ships the drift guard (plus BUG-121 and Sprint 28a). **The next 24 h capture with `configs/capture.json` is the last test of the momentum lane:** if it is not clearly net positive with the guard on, stop tuning it. In parallel and at no risk to capital: the 72 h pre-graduation paper pilot (FEAT-53, second runtime folder, `enable_pre_graduation_harvesting: true`) and the FEAT-54 offline wallet scorer on the two captures.

### 6.5 Ideas from other projects, tested offline (2026-10-20)
Ideas taken from a review of `pumpfun-bonkfun-bot`, `pumpfun-sniper-bot` and `PumpGrok` (FEAT-55/56 in [`PROPOSED-FEATURES.md`](../archive/pumpfun-trading/dev/PROPOSED-FEATURES.md#feat-55-creator-reputation-book)). Data: the v0.2.3 capture (`runtime/archive/stage0-v0.2.3/`) and the rc.1 capture (`runtime/capture/`). Replay is `configs/canary.json` as in rc.2 (drift guard on), tip 0: v0.2.3 +0.058 SOL / 117, rc.1 −0.080 / 105. Every filter is compared with keeping a random share of the same size, since any cut of a losing lane loses less.

- **Creator reputation book (FEAT-55): no edge.**
  - Walking forward through v0.2.3 and blocking a creator after one losing position blocks 203 of 1,697 positions worth −0.044 SOL; a random 203 would be −0.070.
  - In rc.1 only 2 creators were bought twice (the serial-launcher screen already rejects repeat creators), and the v0.2.3 book would block 6 rc.1 positions worth +0.002 SOL.
  - PumpGrok's "token fell ≥ 60%" rule fires on 2 of 1,229 tokens: an early curve cannot fall that far below a ~30 SOL entry.
  - `creator_rugs` is 0 on all 24,521 screening records: `rug_history_count` is never filled, so that screen check does nothing.
- **Sniper count: not measurable on these captures.** For 90% of mints the first recorded trade comes more than 3.3 s after the create, so the first-slot buyers are never seen. The proxy used is the SOL that entered the curve before the first recorded trade.
- **Wallet diversity and sniper volume (FEAT-56): small, consistent edge; not enough on its own.** Net SOL / positions kept:

| Keep rule | v0.2.3 replay | rc.1 replay | rc.1 paper |
|---|---|---|---|
| none | +0.058 / 117 | −0.080 / 105 | −0.099 / 118 |
| largest buyer < 50% of buy volume | +0.071 / 98 | −0.027 / 67 | −0.046 / 84 |
| wallet diversity ≥ 0.3 | +0.073 / 109 | −0.028 / 82 | −0.062 / 96 |
| inflow before the first seen trade < 5 SOL | +0.086 / 110 | −0.043 / 77 | −0.035 / 87 |
| all three | +0.099 / 91 | −0.004 / 47 | −0.006 / 58 |

  Each rule beats a random cut of the same size on all three sets (+0.016 to +0.054 SOL), but the combination only brings rc.1 to about break-even, on 47–58 positions. The thresholds are round numbers chosen before looking, not tuned. The inflow measure overlaps the rc.2 drift guard on rc.1 (it is everything before promotion there), so the two gains will not simply add up.
- **Verdict:** no gate in rc.2. rc.2 records the inputs on every momentum buy (`entry_metrics.top_buyer_share`, `wallet_diversity`, `first_poll_sol_growth`, `first_poll_age_seconds`) and the market regime on every buy and screened launch (`market_regime`: UTC hour and weekday, launches per minute and graduations per hour over 15 min, `warm` once a full window has passed). The rc.2 capture is unseen data for all of them: add a filter only if it beats a random cut there too, then Stage 0 it.

### 6.6 Wash-trade inputs, graduation backfill and split tips (2026-10-20)
Ideas taken from the `launch-relay` review, applied to trading only (we detect wash trading, we never do it).

- **Wash-trade inputs (FEAT-57): no consistent edge.** `OrderFlowEngine.round_trip_flow` scores the flow before each entry (creator and our wallet excluded): `round_trip_wallets`, `round_trip_share` (matched in-and-out volume over all volume) and `quick_flips` (a wallet reversing within 2 s; trade messages carry no slot). Skipping flagged entries, edge against a random cut of the same size (`data/analysis-2026-10-20/wash.py`):

| Skip rule | v0.2.3 replay (117) | rc.1 replay (105) | rc.1 paper (118) |
|---|---|---|---|
| `round_trip_share` > 0.1 | +0.061 | −0.001 | −0.023 |
| `round_trip_share` > 0.2 | +0.052 | −0.000 | −0.020 |
| `round_trip_share` > 0.4 | +0.040 | +0.009 | −0.002 |
| `round_trip_wallets` ≥ 2 | +0.044 | −0.006 | −0.009 |
| `quick_flips` ≥ 1 | +0.043 | −0.018 | −0.012 |

  It helps on v0.2.3 and is no better than chance on rc.1, including the paper run. Shared funders are not measured (a per-wallet funding lookup is too slow for the entry path). The FEAT-26 sybil detector never ran: it needs `funding_links`, which the Pump.fun API does not send.
- **Verdict:** rc.2 records the three inputs on every momentum buy; nothing gates on them. Re-test on the rc.2 capture.
- **Graduation backfill.** A third completion source for held mints: every `graduation_backfill_seconds` (default 30 s) the bot asks the Pump.fun API about each held mint; `complete` or a `pump_swap_pool` sends it to the PumpSwap exit (BUG-123). It covers migrations missed across a reconnect or restart. The API is only a hint: the exit still prices and sells from the on-chain pool.
- **Split tips.** `PUMPFUN_JITO_ENTRY_TIP_LAMPORTS` / `PUMPFUN_JITO_EXIT_TIP_LAMPORTS` set a fixed tip per side (`0` = plain RPC, no tip). Paper and replay model the same per-side costs, so the RUNBOOK tip experiment can test "no tip on entries, paid exits".

### 6.7 What the rc.2 capture records (2026-10-20)
Three gaps kept the rc.1 capture from answering the open questions; rc.2 closes them without changing what the bot buys.
- **Curve history in the capture.** rc.1 polled every watched curve every 2 s but wrote none of it, and paper fills and exits read curves the capture never saw. That is most of the replay-vs-paper gap (+0.022 SOL against ±0.010) and why replay could not judge the drift guard (5 of 112 fills > 10% in replay, 14 of 118 on paper). rc.2 writes every curve read as a `curve_poll` row (`watch`, `position`, `entry_fill`, `shadow_fill`), and replay prices a delayed fill from the read within 1 s after it is due. The rc.1 capture has no such rows and still replays as before (−0.080 SOL / 105 buys with `canary.json`, tip 0). Re-run `--compare-audit` on the rc.2 capture before trusting any sweep on it.
- **Near-graduation set (FEAT-53).** The pre-graduation lane only saw coins younger than the 10 min watch TTL. With `near_graduation_max_mints` > 0 a coin past the TTL that is ≥ 50% up its curve and still growing stays polled (slowly, without a trade subscription) for up to 1 h. Replay runs the lane on the recorded polls, so the pilot capture can be replayed. `configs/pregrad_pilot.json` is the 72 h paper pilot (lane on, no momentum buys).
- **Shadow variants (FEAT-58).** `capture.json` logs nine momentum rules on real paper fill prices without trading them: baseline, 6 and 8 buyers, 5% and 10% drift guard, FEAT-56 top buyer < 50% and diversity ≥ 0.3, FEAT-57 round-trip share ≤ 0.4 and no quick flips. Judge each one per position against a random cut of the same size, on the rc.2 capture only (it is unseen for all of them).
- **Verdict:** no new buy rule ships in rc.2. The rc.2 capture is the last test of the momentum lane; if neither the bot's rule nor a shadow variant is clearly net positive on it, stop tuning this lane.

### 6.8 Stop-loss sweep, wallet scores and the capture rule tool (2026-10-20)
Offline work on the v0.2.3 and rc.1 captures (both in `runtime/archive/`) while the rc.2 runs go. Replay with the frozen `configs/canary.json`, tip 0, each capture split at its midpoint (A / B). The rc.1 audit trail in `archive/stage0-v0.3.0rc1/` is still 0 bytes, so rc.1 is replay only.

**Stop-loss redesign** (`pumpfun-replay --sweep`, new keys `stop_loss_arm_seconds`, `stop_loss_demand_hold_seconds`, `stop_loss_hard_floor`; all 0 = the plain stop, so nothing changes until a config sets them):

| Change (Δ net SOL against the base, A / B) | v0.2.3 | rc.1 |
|---|---|---|
| `stop_loss` 0.80 | −0.010 / −0.007 | −0.015 / −0.007 |
| `stop_loss` 0.90 | +0.012 / +0.001 | +0.006 / +0.011 |
| `stop_loss` 0.92 | +0.012 / +0.006 | +0.015 / +0.015 |
| `stop_loss` 0.95 | +0.020 / +0.003 | +0.007 / +0.012 |
| stop armed after 10 s | −0.003 / −0.014 | −0.004 / −0.010 |
| stop held 10 s after a qualifying buy | −0.008 / −0.027 | −0.018 / −0.017 |

- Waiting longer never helped: arming the stop late (5–30 s) or holding it while buys come in (5–30 s) lost in every half, with or without a 0.6 / 0.7 hard floor; the only exception is arming after 5 s on rc.1 B, flat at +0.0003 SOL. The longer the wait, the bigger the loss. The stop-loss positions are mostly coins that keep falling.
- A **tighter** stop (0.90–0.95) beat the base in all four halves. The gains are 0.001–0.020 SOL per half, inside the ~0.02 SOL replay noise, and rc.1 stays negative (−0.049 at 0.92). Tighter stops also depend most on fill prices, which replay gets wrong (§6.4), so this is a candidate for the rc.2 capture (re-run the sweep there after `--compare-audit`), not a change to `canary.json`.

**Entry rules rebuilt from the capture** (`pumpfun-replay --keep`, `engines/cuts.py`; replaces the `data/analysis-2026-10-20/` scripts): FEAT-56 top buyer < 50% and diversity ≥ 0.3 beat a random cut in all four halves; FEAT-57 round-trip share ≤ 0.2 on v0.2.3 only; the creator book (block a creator after one of its coins closed at a loss) has no edge. All four together keep 64 / 39 positions, +0.097 / +0.004 SOL: the same picture as §6.5, a better-than-random cut that still only breaks even on rc.1.

**FEAT-54 wallet scores** (`pumpfun-replay --wallet-scores`, `engines/wallets.py`): every wallet in a capture is scored by what copying it would have netted **us** (0.02 SOL, 1.5 s delay, 100 bps penalty, fees, closed copies only).
- Copying every wallet loses: −4.67 SOL over 4,003 copies (v0.2.3), −2.01 over 1,286 (rc.1), about −0.0013 SOL per copy, mostly fees and the delay.
- The best v0.2.3 wallets (≥ 3 / 5 / 8 copies, top 20) lost on rc.1 (−0.08 / −0.12 / −0.10 SOL). With ≥ 5 copies they did better than the same share of all rc.1 copies, but worse than 97% of random sets of as many wallets. The reverse direction (rc.1 → v0.2.3) is no better. No wallet goes on a list.
- Wallet `29yFzeBZ…kbw8` never traded a recorded coin: it is a **creator**, with 47 (v0.2.3) and 53 (rc.1) launches screened, every one rejected as a serial launcher (20 launches in 24 h, 9.8% initial holding). Its income is launching coins, which is not a strategy this bot should copy.
- Limit: captures only hold trades of mints the bot subscribed to, so each wallet has at most ~15 closed copies. A copy lane needs a capture that records wallets' own trades (`subscribeAccountTrade`) before it can be judged.

**Verdict:** nothing changes in `canary.json`. On the rc.2 capture, re-run the stop-loss sweep (0.90 / 0.92 / 0.95), the `--keep` rules and the wallet scores; adopt only what holds there.

### 6.9 Pullback entry, buy timing and the bundle proxy for rc.3 (2026-10-20)
Items 2 and 3 of the "top 10 strategies" review: the **pullback entry** (wait for the first dump after a pump, buy when a base holds and buying comes back), **drizzle / burst detection** and an **anti-bundler proxy**. All three are logged only; none gates a buy, and the shipped buy, exit and sizing rules do not change.

- **Pullback rule (FEAT-59)**, as a shadow variant kind. `"kind": "pullback"` runs on the trade feed of subscribed mints; `"kind": "pullback_curve"` runs on the watch poller's curve reads, so it covers every watched mint without a billed subscription. Defaults (`PULLBACK_DEFAULTS`, each overridable as `pullback_*`): peak ≥ 40 SOL market cap, now 30–70% below it, no new low for 10 s, ≥ 3% off the low, ≥ 0.2 SOL net inflow over 15 s (trade kind: from ≥ 2 other wallets; curve kind: the curve's real SOL change), token age 30–900 s.
- **Buy timing (FEAT-60)**, `OrderFlowEngine.buy_timing`: `buy_gap_cv` (gap regularity; a drizzle bot is well below 1, independent buyers near 1), `buy_gap_median_seconds`, `burst_share` (largest share of buys inside 5 s), `buy_size_cv` (identical sizes = a bot), `small_buy_share` (< 0.05 SOL). Recorded on every momentum buy and shadow signal; usable as shadow filters (`min_buy_gap_cv`, `max_burst_share`, `min_buy_size_cv`, `max_small_buy_share`) and as `--keep` rules (`engines/cuts.py` rebuilds them from any capture).
- **Bundle proxy (FEAT-61)**, `HolderDistribution.early_holder_cluster`: non-creator accounts already holding ≥ 1% of supply when the token is screened (about a second after the create, so mostly the create slot) and their combined share. `getTokenLargestAccounts` returns token accounts, not owners, so the creator's account is matched by its initial-buy balance. Recorded in every screening capture record (`early_holders`, `early_holder_pct`) and on momentum buys; shadow filters `max_early_holders`, `max_early_holder_pct`. Linked funding (the BubbleMaps view) is still not measured: it needs a funder lookup per wallet.
- **Offline test** (`pumpfun-replay --shadow-report --shadow-scan`, new `engines/shadow_scan.py`: the same shadow book run over a capture's recorded trades and watch polls, filled at the first recorded price after the 1.5 s delay). On the rc.2 capture so far the scan reproduces the 13 recorded shadow rows exactly. Edge against a random cut of the baseline, A / B:

| Variant | v0.2.3 (baseline 169 signals) | rc.1 (baseline 118 signals) |
|---|---|---|
| pullback (trade feed) | 10 signals; −0.004 / −0.005 | 11 signals; −0.006 / −0.002 |
| `min_buy_gap_cv` 0.5 | −0.004 / +0.019 | +0.003 / −0.013 |
| `max_burst_share` 0.5 | +0.007 / −0.009 | +0.007 / −0.037 |
| `min_buy_size_cv` 0.5 | −0.002 / +0.008 | +0.013 / −0.019 |
| pullback on curve reads, bundle filters | no data (no watch polls / holder snapshot before rc.2 / rc.3) | no data |

- **Read the numbers as relative only.** Scanned fills come from recorded data: the scanned baseline on rc.1 models −0.006 SOL where paper lost −0.099 on the same 118 signals, because the paper fill read curves that saw trades the capture missed (§6.4). A filter's edge over a random cut of that baseline is the usable figure, and even that leans optimistic.
- **Why the trade-feed pullback fires so rarely:** it only sees subscribed mints (≥ 3 SOL growth, 10 min watch TTL), and most dumps come after the subscription ends. The curve kind sees every watched mint (35–65 an hour); in the first 1.5 h of the rc.2 capture 10 of 52 polled mints peaked above 32 SOL and 2 fell 30%, so expect a few dozen pullback signals per 24 h.
- **rc.3 capture:** planned with 19 shadow variants (the nine rc.2 ones, three FEAT-60, two FEAT-61, the trade pullback and four curve pullbacks) and the four curve pullbacks in `configs/pregrad_pilot.json`. After the rc.2 read-out (§6.10) `capture.json` keeps eight of them and the pilot none.
- **Verdict:** none of the three ships as a gate. Judge them on the rc.3 capture with `--shadow-report --split-at mid` (unseen data for all), per position and against a random cut; a pullback lane needs a clearly positive result there before it gets its own entry path and a paper pilot.

### 6.10 v0.3.0-rc.2 capture and pilot: momentum NO-GO, stop 0.92 adopted (2026-10-21)
- **Data:** two paper runs on tag `v0.3.0rc2`, 2026-10-20 07:00 → 2026-10-21 07:06 UTC (24.1 h), archived in `runtime/archive/paper-v0.3.0rc2/capture/` and `.../pilot/`. Read-outs with the `main` tools at tip 0, as in the runs. Half A / B split at the midpoint.
- **Momentum capture (paper):** +0.014 SOL over 105 positions, 32.4% profitable, +0.00013 SOL per position. The best 5 positions made +0.096 and the other 100 lost −0.082, so one or two trades decide the day. Exits: 35 stop losses −0.157 (median hold 12 s), 25 trailing stops +0.166, 43 buy-flow stagnation +0.002, 2 break-even ratchets +0.004. Operations were clean: no trade-feed refusals or breaker trips, one poll error, RPC p95 135 ms.
- **Paper was ~1% per exit too kind (BUG-126).** Paper sells took no slippage; replay took 100 bps. That was 0.021 of the −0.028 SOL parity gap. With the haircut matched, same-exit positions agree to −0.002 SOL; the rest is one position where replay saw the stop and paper the trailing stop. With the haircut the paper result is about **−0.007 SOL**. rc.3 applies `paper_exit_slippage_bps: 100` in paper and replay.
- **Stops overshoot.** The stop is 85% of entry, but the median trigger was 82.3% and the median proceeds 80.3% (worst tenth 66.9%): the curve moves too far between 1 s refreshes.
- **What held up on a second capture:**

| Test | rc.2 | Earlier captures | Decision |
|---|---|---|---|
| `stop_loss` 0.92 (base 0.85), full capture | +0.004 / +0.011 | +0.012 / +0.006 (v0.2.3), +0.015 / +0.015 (rc.1) | **adopted**: 6 of 6 halves on three captures |
| shadow `buyers6` | beats a random cut in both halves | 8 buyers failed out of sample on rc.1 and in rc.2 B | keep logging |
| shadow `drift5` / `drift10`, `feat56_diversity` | beat a random cut in both halves | FEAT-56 beat a random cut on v0.2.3 and rc.1 | keep logging |
| FEAT-57 wash and FEAT-60 timing filters | no edge | no edge | dropped from `capture.json` |
| trade-feed pullback | 10 positions, +0.006 | 10–11 a day, worse than random in 3 of 4 halves | keep logging (cheap) |
| curve pullbacks (capture and pilot) | all lose (pilot baseline −0.080, 11% won) | no data | dropped |
| FEAT-61 bundle filters | no data | no data | keep logging (rc.3 records the inputs) |

  None of the shadow variants is net positive in both halves on its own; scanned and shadow nets compare variants with each other only.
- **Take profit earlier? No.** In the `momentum` preset `take_profit` (3.0×) never fires: the tiers and the trailing stop exit first (tier 1 sells 50% at 1.5×, the trailing stop arms at +25% and sells 12% below the peak, so a spike to 1.25× already exits near 1.10×). Moving tier 1 to 1.2–1.3× was worse in at least one half on every capture (v0.2.3 A −0.012 to −0.015, rc.1 B −0.008 to −0.012, rc.2 A −0.004 to −0.010). Selling more or less at tier 1 (30% / 100%) and other trailing settings each won on one capture and lost on another. The lane's profit is a few positions that run well past +50%; an early full take-profit caps exactly those and leaves the stop losses as they are.
- **The screen rejects the coins that later get demand.** 1,993 of 13,583 screened launches passed (14.7%). Of 119 screened coins that graduated two minutes or more after their create, 3 passed (2.5%): 104 failed the top-5 holder cap (their median top-5 share is 27%, against 5.5% for all launches) and 50 the creator-holding cap. 259 more graduated within 10 s of the create (bundled launches, not tradeable).
- **Pre-graduation pilot:** 2 positions, −0.008 SOL, both stop losses at about 80% progress on coins the momentum lane had already bought and sold at a profit. It saw only 5 near-graduation curves in 24 h, because it polls screened mints only and only within the 600 s watch TTL, while 105 coins graduated more than 10 min after launch.
- **Time of day:** 00–14 UTC made money and 15–17 UTC lost −0.061 SOL, but per hour the result swings with one or two trades. Not a rule yet; `pumpfun-audit pnl --group-by hour` on rc.3 adds a second day.
- **Verdict: the momentum lane as it stands is NO-GO for Stage 0, and its entry thresholds are not tuned further.** rc.3 ships BUG-126, `stop_loss` 0.92 for the momentum lane (preset, `canary.json`, `capture.json`; the pilot keeps 0.85 because 0.92 was never tested on that lane) and a smaller shadow set. The rc.3 capture runs 48 h. Next work, in order: watch a random sample of screen-rejected mints as shadow-only (does the top-5 / creator cap help at all?), feed the pre-graduation lane from curves with large real reserves regardless of screening or the TTL, and a faster reaction to stops on held mints (trade-feed prices instead of the 1 s refresh).
- **Added to rc.3 before the run (record only, 2026-10-21):** the first halves of those three items ship as measurements, so the rc.3 runs still trade exactly as configured above. `capture.json` polls a 20% sample of screen-rejected launches (`screen_reject_sample_pct`, rows `source: "reject_sample"` with the screen's reasons); `pregrad_pilot.json` polls curves past 40 SOL real reserves found by a Pump.fun API scan every 30 s (`graduation_discovery_scan_seconds`, rows `source: "discovery"`), which the lane does not buy; all three configs record where each price source first crossed the stop and what the exit sold at (`record_stop_crossings`, `exit_metrics`). Replay and the shadow tools skip the observation rows. The rules that would act on them (relaxing a cap, buying discovered curves, a trade-feed stop trigger) wait for the rc.3 read-out and a second capture (RUNBOOK §6.3).

### 6.11 v0.3.0-rc.3 interim read-out (45.5 h): both Pump.fun lanes NO-GO (2026-10-23)
- **Data:** two paper runs on tag `v0.3.0rc3`, started 2026-10-21 10:55 UTC, read at 45.5 h (2026-10-23 08:25 UTC) while still running: 15 + 1 capture parts joined into 2.19 M rows (no gaps), 6 + 1 pilot parts into 1.25 M rows. Tools from `main` after rc.4; verdict with the shipped `configs/verdict_rules.json` as evidence only (it was not pre-registered for rc.3). The 72 h runs end on 2026-10-24.
- **Operations clean in both runs:** no errors or tracebacks, about 22 stream reconnects each (all recovered), trade feed 404 confirmed subscriptions and 0 refusals, breaker never tripped. Of 48,460 create events, 22,015 (45%) were other launchpads and 3,819 (8%) mayhem launches, all skipped as designed. 70% of holder lookups needed a retry; 71 failed.
- **Momentum (capture):** −0.179 SOL over 127 closed positions (wallet 2.000 → 1.821; audit, status file and cash flows agree), −0.0014 SOL per position (−7% of the stake), 14% profitable. Halves A −0.093 / B −0.105, every UTC day negative, −0.240 without the best 3. The bootstrap 90% interval of the mean per position is [−0.0021, −0.0010] SOL: the loss is not noise.
  - **Selection, not costs.** With fees and the paper haircuts taken out (≈ 4.6% a round trip), the average position's price still fell 2.6% (median −7.4%); 24% of positions rose at all. Exits: 71 stop losses −0.225 (proceeds 84% of cost on average), 39 stagnation exits −0.040, 8 trailing stops +0.018, 6 tier-1 take profits +0.069.
  - **Stops gap through.** Stop at 92%: median trigger 90.2%, median fill 87.1%. The trade feed crossed only 0.07 s before the curve refresh and at the same price (90.2%), so a trade-feed stop trigger would not help. A wider stop does not help either (sweep row above).
  - **Nothing that held earlier holds here.** The FEAT-56/57 combination that beat a random cut in four halves of v0.2.3 / rc.1 is below a random cut in rc.3 half B. Shadow variants: `buyers6`, `drift10`, `feat56_diversity`, the FEAT-61 bundle filters and `pullback` beat a random cut in both halves, but every one loses (best `pullback`, −0.010 over 18). Only 3 of 24 UTC hours were positive, each on a handful of trades.
- **Pre-graduation (pilot): 0 trades.** The lane only buys watched mints, and only 4 of about 2,100 ever passed 75% of the curve; the discovery scan found 661 that did (and 422 of the 1,807 recorded migrations) but by design only records them. A what-if on those discovered curves (entry in the 75–88% band at the next poll, 30% / 30% tranches at 92% / 97%, stop 0.85, 4.6% costs) loses about 14% per trade (−1.62 SOL at 0.02 SOL over 562 entries, both halves); without the stop, or with a 88–95% band, it is still about −13%. The polls are 10 s apart and exits at completion are valued at the last curve price, so this is optimistic if anything.
- **The screen keeps the quiet coins, and the movers are worse to trade.** In the same first 10 minutes, the 20% sample of screen-rejected launches reached 20 SOL real reserves 9.4% of the time against 1.0% for watched launches, most often the coins rejected for top-holder or creator concentration. The same crude momentum rule (enter at +3 SOL growth, stop 0.92 / take profit 1.5× / 35 s stall, 4.6% costs) loses about 10% per trade on the rejected sample against 6% on the watched coins. Relaxing the caps would buy into insider pumps, not demand.
- **Ratchet floor too eager (BUG-144).** Replaying this capture with the rc.4 breaker and the run's settings (momentum preset `profit_ratchet_ratio` 0.60) halted buying twice for the rest of the UTC day: after +0.011 SOL realized on a 2 SOL wallet, a 0.0007 SOL dip under the floor. The rc.3 paper bot did not enforce the floor (BUG-127 is fixed in rc.4), which is why the first parity run, with the breaker on, showed a false 93-position gap.
- **Verdict: the momentum and pre-graduation lanes are NO-GO, and Pump.fun strategy work stops here.** Three captures (v0.2.3, rc.1, rc.2) broke even at best, and rc.3 loses clearly with an honest cost model. Three entry sets (confirmed momentum, discovered near-graduation curves, screen-rejected movers) all lose 6–14% per trade at this latency, before any tuning. No Stage 0 on these lanes. rc.4 ships as a tooling and risk release (FEAT-66…69, BUG-141…144). The next candidate is the FEAT-65 slow lane, judged on its recorded costs.

### 6.12 FEAT-65 slow lane, phase 0 read-out: costs pass, no edge shown (2026-10-23)
- **Data:** the separate keyless recorder, copied from the second host into `runtime/slow_lane/`. `jupiter_quotes.jsonl` covers 2026-10-21 09:48 → 2026-10-23 08:45 UTC (46.9 h) with 33,836 quotes (16,918 round trips at 0.02 / 0.1 / 0.5 SOL), 6,193 prices, 4,927 priority-fee samples and 2 quote errors (JUP, HTTP 400). `bars-202610.jsonl` holds GeckoTerminal daily bars (183 per token, 2026-04-22 → 10-21) and hourly bars (about 5,000 per token from late March) for SOL, USDC, JUP, JTO, BONK, WIF, PYTH, RAY, ORCA, mSOL and jitoSOL.
- **Costs (the phase 0 question):** median round trip in bps at 0.02 / 0.1 / 0.5 SOL:
  - JUP −0.5 / 0.8 / 1.2;
  - RAY 6.8 / 7.6 / 8.4;
  - WIF 8.2 / 8.8 / 11.8;
  - PYTH 8.3 / 10.9 / 14.8;
  - BONK 8.8 / 10.3 / 11.8;
  - ORCA 12.0 / 15.3 / 21.9;
  - JTO 25.9 / 33.5 / 37.0;
  - mSOL / jitoSOL about 0.2; USDC about 0.

  p90s are at most 52 bps (JTO). The p90 buy-side price impact is under 0.5%. Routes change between consecutive quotes 10–96% of the time without moving the cost much. Priority fees are 0 in the median slot (median non-zero share 0.7%; p90 of the p90s 36,485 µlamports/CU, about 0.00001 SOL for a 300k-CU swap). With the 5,000-lamport network fee, a round trip at 0.1 SOL costs about 0.1–0.5%: roughly 10–40× cheaper than a Pump.fun round trip (about 4.6%). **The cost side of FEAT-65 passes.**
- **Data quality:** BONK's hourly pool has 408 gaps and bad prints (×4.3 then ×0.23 within hours), and JUP's hourly series has 298 gaps; both are left out of the hourly test. Bars carry no `currency` field: they are USD. Six months of daily bars is about a third of what a trend rule needs to be judged (a longer source: see the verdict below).
- **Backtest (offline, pre-specified, not tuned):** prices in SOL terms (token USD / SOL USD). Hold a token while its close is above its N-bar mean, else hold SOL; signal on a bar's close, trade at the next bar's open. Each side pays half the measured median round trip at 0.1 SOL plus 10 bps, with a stress run at the p90 plus 20 bps. The seven risky tokens are equal-weighted, with halves A / B by time. Results, with stress-cost numbers 1–3 points lower throughout:
  - **Daily, 132 days:** buy and hold +8.9% in SOL terms, carried by RAY (+111%); JTO −44%, BONK −56%. SMA10 −4.7%, SMA20 +3.8%, SMA50 +7.5%, every one negative in half A. Without RAY the rules lose −6% to −14%. They do cut the worst losers (BONK −56% → −8%), the usual trend-following trait, but nothing here beats holding.
  - **Hourly, 188 days (5 tokens):** SMA 5 / 10 / 20 days give −20.2% / −13.0% / +7.4% against buy and hold +46.3%: 555–1,243 switches of whipsaw.
  - **SOL against USDC in USD terms:** every switch rule trails holding SOL (+60.2% daily, +25.2% hourly).
  - **Staking** (jitoSOL against SOL) earned +0.9% over the 132 days with no trading.
- **Verdict: FEAT-65 is cheap enough to trade but unproven, and phase 0 gives no reason to build the lane yet.** The proposal's gate (walk-forward net positive on two unseen periods and better than a random-entry baseline) cannot be tested on six months of bars. The simple rules tried here underperform holding and depend on one token. Before any lane code: get a longer bar history, then run the walk-forward test with a random-entry baseline. *(Corrected 2026-10-23: this first said a free CoinGecko demo key would give about 2–3 years. It does not: the Demo plan's OHLC history is limited to the past 365 days, and full history needs a paid plan.)* The source is Binance's public spot klines: free, keyless, and back to each pair's listing. `pumpfun-recorder --backfill-bars --bar-source binance` downloaded 314,865 daily and hourly bars on 2026-10-23 in under 3 min: SOL from 2020-08, RAY from 2021-08, JTO and BONK from 2023-12, JUP and PYTH from 2024-02, WIF from 2024-03, ORCA from 2024-12. mSOL and jitoSOL have no pair. These are exchange prices in USDT, not the Solana pools a swap fills in, so they serve the signal and the Jupiter quotes above stay the cost model. Expect low single-digit returns at best: at 2 SOL of capital a good year is cents per day, so this is a learning lane, not an income lane.

### 6.13 rc.6 to rc.8 launch mode, PumpSwap graduations and the cross-chain market (2026-10-28)
- **Data:** the rc.8 A/B on tag `v0.3.0rc8`, 2026-10-26 17:31 UTC to a power cut at 2026-10-28 06:43 UTC (37.2 h); run A `configs/launch_fast_exit.json` (stop 0.80, launch sample, graduation tracking, launches followed to graduation), run B was started with `configs/launch_stop90.json` (stop 0.90) instead of the planned `configs/launch_entry_filters.json`, so the FEAT-75 filters were applied offline to run A's fills. Audit trails and event logs are complete; the replay captures lost their first 20 h (A) and 14 h (B) to BUG-157, so the per-poll paths, graduation pools and launch sample cover the last 16.6 h of run A only. The market recorder (`pumpfun-recorder --market`, FEAT-74) ran 38.2 h without a rate limit. Operations otherwise clean: no RPC rate limits, the trade feed never refused (90,652 trade messages, 0.050 SOL charged), curve waits p90 0.37–0.43 s. Scripts: `runtime/archive/paper-v0.3.0rc6/analysis/` (rc.6 / rc.7) and `runtime/analysis-rc8/` (rc.8; offline, paper cost model, fills at the next reading).
- **Launch buying on Pump.fun stays negative, whatever the exits.** rc.8: run A −9.25 SOL over 9,848 trades of 0.02 SOL (−4.69% per trade, halves −5.11 / −4.28, 25% won), run B −9.30 over 9,874 (−4.71%); the 0.90 stop made no difference for the third run in a row (paired over 9,813 coins: −0.02 points). rc.7 (5.75 h, 1,274 per bot) −3.9%, rc.6 (18 h, a biased fifth of launches, BUG-154) −5.5%. Exit grids on the recorded paths never beat about −3.5% (rc.7) per trade; higher take-profits and selling half to trail the rest are worse. With zero costs the rc.6 buys would still have lost 0.7% per trade.
- **The fill-drift guard is the one entry rule that held on every dataset.** Refusing fills more than 15% above the create market cap (`momentum_max_entry_drift_pct: 0.15`): rc.8 run A −4.69% → −3.27% per trade (both halves), with the tiny-creator-buy skip as well −2.87% (54% of trades kept, −3.06 SOL instead of −9.25); rc.7 −3.9% → −2.9%; rc.6 −5.5% → −4.6%. The tiny-creator-buy skip on its own made little difference (worse on rc.6 and rc.8, −4.82% here; slightly better on rc.7). Still a loss: no launch-mode setting found pays the 4.4% paper round trip.
- **PumpSwap after graduation (run A, 16.6 h, 569 migrations with pool rows; the status counters show 1,484 over the whole run).** 236 were standard graduations (pool ~84 SOL, first price 0.5–2× the curve's 410.88 SOL market cap, first reading a median 1.2 s after the migration event); the rest were pools already empty (178, under 1 SOL from the first reading), established large pools (125) or odd ones. Of all 569, the median pool was at 0.96× its first price after 1 minute, 0.72× after 5 and 0.09× after 15; 52% were below 0.1× by 15 minutes. Half touched 1.5× at some point, but the median peak came 1.6 minutes after the migration. No sampled coin that crashed below 0.5× in its first 15 minutes came back (rc.6 candles: 0 of 39; rc.8: the same pattern).
  - **Buying at the migration loses:** best exit −0.02% per trade at 1% cost a side, −2.0% at 2% (n = 236); a random entry in the first 10 minutes −7.3% (2%).
  - **Buying the survivors is the first rule in this project that did not lose.** Signal: 60–120 s after the migration the price is still at least 1.1–1.2× the first reading; fill at the next reading; take profit at 1.2×, stop 0.85 (or none), 2% cost a side: +1.3% to +5.7% per trade in both halves (n = 42–72, about a third of graduations, ~100 a day), against −7.3% for a random entry. Not yet a result: every 90% bootstrap interval includes 0 (e.g. 120 s / 1.2×: +4.5%, [−1.2%, +11.0%], n = 54), one extra reading of fill delay moves it by up to 5 points, and earlier (30 s) or later (≥ 3 min) signals lose.
  - **Before graduation:** only 31 sampled launches completed their curve in the surviving 16.6 h (most within 3 minutes of creation), too few to test whether anything before graduation predicts the pool.
- **Cross-chain (FEAT-74, 38.2 h):** 60,597 new pools seen on Solana, Base and BSC, 28,790 followed, 1.27 M snapshots, 19,619 ended dead. Coverage gaps: DexScreener returned almost nothing for Raydium LaunchLab (98% missing), stonkfun (98%) and memefun (99%), and missed a third of Uniswap v4 pools on Base / BSC. Momentum-list entries (trending 5 m / 1 h, top 24 h volume) lose on Base (−3% to −4% per trade at 2% a side) and are noise elsewhere. The new-pool groups that look best (Base Uniswap v2, BSC PancakeSwap v2, Base v4 after +50%: 90–96% of trades "win" at a 1.2× take-profit with no stop) carry the signature of honeypots and sell taxes, and Meteora DAMM v2 launches charge dynamic launch fees DexScreener prices do not include; with liquidity floors, a 10× cap and drained pools at 0 the rest are inconsistent across halves. **None of the cross-chain numbers is trusted until a sell quote shows the price was executable.** At $2 a trade, EVM gas alone would cost 0.5–5% a side.
- **Verdict:** launch-mode Pump.fun buying is NO-GO (rc.5 to rc.8, about 25,000 paper trades, every setting negative). The only positive signal is PumpSwap momentum shortly after graduation, on the bot's own on-chain pool reads, with known fees and no honeypot risk; it needs more data before it is a lane. Next ([`PROPOSED-FEATURES.md` FEAT-76](../archive/pumpfun-trading/dev/PROPOSED-FEATURES.md#feat-76-pumpswap-post-graduation-momentum-lane)): a 72 h graduation-only capture with BUG-157 fixed, a pre-registered rule from this read-out, then a PumpSwap paper executor. The cross-chain recorder needs sell-quote checks and better LaunchLab coverage before its data can pick a venue.

### 6.14 FEAT-76 on the new stack: the rc.8 graduations replayed through trading-core (2026-10-28)
- **What was run:** the `pumpswap_momentum` lane as built in trading-pump 0.4.0 (the module for trading-core; pumpbot is retired), replayed with `trading-pump replay` on the rc.8 run A graduation rows that survived BUG-157 (2026-10-27 14:10 to 2026-10-28 06:43 UTC, 16.6 h, 861,000 rows, 617 migrations). The real engine and the real module ran on a replay clock with a capture-backed pool source that never looks ahead; every fill paid the swap fee a side (fixed, `--fee-bps`), the 5,000-lamport base fee, the 5,000-lamport priority fee and the Token-2022 rent (refunded at the full exit). Config `configs/paper.example.json`: signal at the first reading ≥ 60 s after the migration, price ≥ 1.2× the first reading, first market cap 0.5–2× of 410.88 SOL; take profit +20%, stop −15%, 30 minutes max hold; 0.02 SOL a trade. Judged with `configs/verdict_rules.json` (sha256 `620ae5f7116ddbc0…`).
- **Results:**

  | Run | Positions | Net SOL | Per trade | Win rate | Take profits / stops | Verdict (adjusted net, 90% interval of the mean) |
  |---|---|---|---|---|---|---|
  | 125 bps a side | 42 | +0.009226 | +1.1% | 50.0% | 21 (+0.0986) / 21 (−0.0894) | NO-GO: +0.0028 adjusted, [−0.00113, +0.00127]; both halves positive; −0.018 without the best 3 |
  | 200 bps a side | 42 | −0.003431 | −0.4% | 50.0% | 21 / 21 | NO-GO |
  | 125 bps, 2 s entry delay | 33 | +0.023414 | +3.5% | 54.5% | 18 / 15 | NO-GO: +0.0183 adjusted, [−0.00070, +0.00178]; both halves and both UTC days positive; −0.0016 without the best 3 |

- **Reading:** the engine reproduces the offline read-out of §6.13 (n = 42–72, +1.3% to +5.7% per trade at 2% a side there; +1.1% at 1.25% here), so the module, the replay and the accounting agree with the scripts. It is the same data the rule was found on, so this is a check of the code, **not evidence for the rule**. Costs are 70% of the gross; at 2% a side the lane loses. A 2 s entry delay helped rather than hurt, the opposite of the "one extra reading moves it by up to 5 points" warning in §6.13, which says the result is noise-sized, not that latency is free.
- **Next:** unchanged from FEAT-76: a fresh 72 h paper run on the new stack with the rule and the verdict file fixed before it starts ([`TODO.md`](TODO.md#feat-76-pumpswap-post-graduation-momentum-lane)), and the PumpSwap fee tier checked against a real swap before trusting either cost assumption.

### 6.15 FEAT-65 walk-forward on the Binance history: NO-GO (2026-10-29)
- **Question:** the gate FEAT-65 set itself ([`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md#feat-65-slow-lane-daily-bar-trend-on-liquid-solana-tokens-via-jupiter), Design 5): is the §6.12 trend rule net positive on at least two unseen periods and better than a random-entry baseline, now that a long bar history exists?
- **Pre-registered** before any result (`PREREGISTRATION.md`, sha256 `a76d553552572a75961b8bad729efa47273d9f53ea1aa94791c2221a76956269`). It was revised once before anything was computed: the first draft's calendar years hold RAY alone until 2024, so its "not one token" condition could never have been met. The test, in short:
  - Binance daily bars (downloaded 2026-10-23), the seven risky tokens of §6.12, prices in SOL terms. A token joins a period once it has 60 bars.
  - The §6.12 rule unchanged: hold the token while yesterday's close is above its N-day mean, else SOL; trade at the next open; each switch pays half the measured Jupiter round trip at 0.1 SOL plus 10 bps (stress: half the p90 plus 20 bps).
  - Half-year test periods 2022 → 2026-04-21; N ∈ {10, 20, 50} chosen on the 730 days before each period, then run on the period. The six months §6.12 looked at count as seen.
  - Random-entry baseline: the rule's own in-token and in-SOL stretches shuffled (same exposure and trade count, other timing), 2,000 draws.
  - Pass: in at least two unseen periods with three or more tokens, above 0 and above the baseline's 90th percentile; positive compounded over those periods (stress not negative); and not resting on the best token.
- **Results** (base costs; stress 1–3 points lower):

  | Period | Tokens | N chosen | Walk-forward | Random p90 | Without the best token | Buy and hold |
  |---|---|---|---|---|---|---|
  | 2024 H2 | 6 | 10 | −0.6% | +18.7% | −9.9% | +8.2% |
  | 2025 H1 | 6 | 10 | −17.3% | −6.2% | −20.9% | −40.9% |
  | 2025 H2 | 7 | 50 | −17.1% | +1.5% | −24.9% | −48.6% |
  | 2026 Jan–Apr | 7 | 50 | −8.6% | +18.6% | −12.5% | +19.0% |
  | *2026 Apr–Oct (seen)* | 7 | 50 | *+26.9%* | *+50.6%* | *+12.2%* | *+33.2%* |

  Compounded over the four counted periods: −37.8% (stress −43.3%), against −60.9% for holding the tokens. RAY alone (2022 H1 → 2024 H1, reported, not counted): four of five half-years negative, −82.1% compounded; its one positive half (+13.1% in 2023 H2) was far below the random p90 (+71.5%).
- **Reading:** **NO-GO on every condition**: no counted period is above 0, none beats random timing, and the compounded return is negative. Every training window had all three rules negative too, so the walk-forward only ever chose the least bad loser. The trend rule does what §6.12 saw, cutting the worst drawdowns (−37.8% against −60.9% for holding), but in SOL terms holding SOL beat both. The one good stretch is the six months §6.12 had already seen. Costs are not the problem (60–180 switches a half-year at 4–27 bps a side).
- **Next:** FEAT-65 stops here. No backtester, no lane and no Jupiter swap client are built for it. Another rule on the same data would be a new pre-registered test, not a variation of this one tuned until it passes (AGENTS: "Beat a random cut"). The scripts, the cost table and the result are in `runtime/analysis-feat65-walkforward/`.

### 6.16 PumpSwap fee check: the cost model holds, on the mint's real supply (2026-10-29)
- **Question** (FEAT-76, [`TODO.md`](TODO.md#feat-76-pumpswap-post-graduation-momentum-lane)): does the fee the module charges a fresh graduate, the PumpSwap fee-config tier for its market cap, match what real swaps in a graduate's first minutes pay? Every FEAT-76 result so far assumed a rate (§6.14 moved from +1.1% to −0.4% a trade between 125 and 200 bps a side).
- **Data:** the 11 standard graduates of the rc.9 capture's first hours (first market cap 205–822 SOL); for each, 12 transactions spread over its first 10 minutes on PumpSwap (132 in all), read from the public mainnet RPC. Each PumpSwap trade emits a `BuyEvent` / `SellEvent` (`pump-fun/pump-public-docs`, `idl/pump_amm.json`) with the reserves it priced at, the LP, protocol and creator fee in bps and in lamports, and the mint's supply: 94 such events (58 buys, 36 sells). The fee config was read the same day:

  | Market cap from (SOL) | LP | Protocol | Creator | Total (bps) |
  |---|---|---|---|---|
  | 0 | 2 | 93 | 30 | 125 |
  | 420 | 20 | 5 | 95 | 120 |
  | 1,470 | 20 | 5 | 90 | 115 |
  | then down by 5 bps a step | 20 | 5 | … | to 30 from 98,240 |

- **Results:**
  - **The tier:** 92 of 94 trades paid exactly the tier the module picks. One was the migration's own buy (no fee). The other, at 432.3 SOL on the module's basis, paid the below-420 tier: the program prices the tier on the mint's real supply, which was 3.8% below the 1B tokens the module assumed (burns). On the real supply all 93 fee-paying trades match their tier. Fixed as **BUG-162**.
  - **The price:** given a trade's reserves (vault plus the pool's virtual quote reserve, about 17.6 SOL on every fresh graduate) and what the user paid, the module's own `buy_tokens_out` / `sell_lamports_out` reproduce the tokens or SOL received to within 0.001 bps for every `buy`, `buy_v2` and sell, and within 0.34 bps for `buy_exact_quote_in` (from the transactions' balance changes; the event's input field means something else for that instruction). The only miss is a 7-lamport dust sell.
  - **Nothing else is charged:** half of the protocol fee goes to a buyback (`buyback_fee_basis_points` 5,000), inside the 5 or 93 bps, not on top; cashback and holder rewards were 0 on these coins (none was a cashback coin).
- **Reading:** a fresh graduate pays **125 bps a side below 420 SOL and 120 bps from there** (on the real supply), as the module charges once BUG-162 is fixed: the §6.14 replay at 125 bps was the realistic one, and 200 bps a stress, not a plausible fee. No `fee_bps_floor` is needed. The lane's other costs (base and priority fee, rent) are unchanged. Scripts and data: `runtime/analysis-feat76-fee-check/`.

### 6.17 Launchpads in the rc.8 cross-chain data (2026-10-29)
- **Question:** before choosing another chain or launchpad (Moonshot; Base's Clanker and Virtuals; BSC's four.meme; Tron's SunPump), how much does each launch, as seen by the FEAT-74 recorder we already ran?
- **Data:** the rc.8 market recorder (`runtime/market/`, 38.2 h to 2026-10-28 06:43 UTC), every `market_pool` row from GeckoTerminal's new-pool lists, by chain and GeckoTerminal `dex` id: 60,617 new pools.
- **Counts** (top of the list): Solana `pump-fun` 38,560 (curves), `meteora-damm-v2` 4,098, `pumpswap` 2,866 (Pump.fun graduations and other PumpSwap pools), `meteora-dbc` 2,708, `stonkfun` 981, `raydium-launchlab` 750, `memefun` 518, `bags-fm` 104, `letsbonk-fun` 26, `moonshot` 10, `moonit` 8; BSC `pancakeswap_v2` 2,864, `four-meme` 2,392, `uniswap-v4-bsc` 1,322; Base `uniswap-v4-base` 1,965, `uniswap-v2-base` 475, `uniswap-v3-base` 150, `o1-launchpad` 87, `bankr` 41. No pool was listed under a Virtuals id. Tron is not recorded.
- **Reading:** four.meme is the only Pump.fun-style launchpad elsewhere with real volume here (about 1,500 curves a day, against Pump.fun's ~24,000). Base launches mostly arrive as Uniswap v4 pools, where Clanker deploys, without a launchpad label. Moonshot (18 pools in 38 h) is too small to judge any rule on. These are counts, not edges: §6.13's warning stands, and no cross-chain return is trusted until a sell-quote check shows the price was executable ([`TODO.md`, FEAT-74](TODO.md#cross-chain-market-recorder-feat-74)).

### 6.18 rc.9 and rc.10 replays: a second lane and wider take-profits (2026-10-30)
- **Question:** rc.10 bought 7 of 310 graduates in its first day. Where do the other graduates go, is any group of them tradeable, and does a wider take-profit beat +20%?
- **Funnel (rc.9 and rc.10 captures, offline):** about 60% of PumpPortal's migration events are not standard graduations (first market cap outside 205–822 SOL), and rc.10's 5% slippage cap refused about half of the standard lane's signals (12 of 72 in the replay below). Among the non-standard pools one group is regular: the **instant graduations**, a first reading at 1,000–2,000 SOL market cap with 130–200 SOL in the pool (about 125 of 1,079 migrations in 33.1 h): curves bought out in a block or two whose launch bots keep buying for the first minutes. Offline, entering these at 1.00–1.10× their first price at 60 s, out at +50% / −15% / 30 min, made +14.6% per trade (n = 79, both halves positive); at ≥ 1.10× they lost (−10.9%). The result held at a 5 s entry delay and at 4% cost a side (+3.9% to +4.3% at a +35% take-profit). About 240 offline variants were compared, so the engine replay below decides.
- **Engine replay** (`trading-pump replay`, the real engine and module of 0.4.0-rc.4, fee 125 bps a side, 1.5 s paper entry delay, 0.02 SOL, on the rc.9 capture: 2026-10-29 08:30 → 10-30 17:54 UTC, 1,097 migrations; breaker `drawdown_reference_mode` `"baseline"`):

  | Lane | Entry | Exits | Positions | Net SOL | Per trade | Halves | Win |
  |---|---|---|---|---|---|---|---|
  | standard | ratio ≥ 1.2, 5% slippage (rc.10) | TP +20% (rc.10) | 60 | +0.061 | +5.1% | +0.9% / +9.4% | 60% |
  | standard | ratio ≥ 1.2, 5% slippage | **TP +50%** | 60 | +0.071 | **+5.9%** | +1.5% / +10.2% | 38% |
  | standard | ratio ≥ 1.2, 10% slippage | TP +50% | 67 | +0.072 | +5.4% | −2.6% / +13.1% | 37% |
  | standard | ratio ≥ 1.3, 5% slippage | TP +50% | 43 | +0.044 | +5.1% | −1.2% / +11.1% | 35% |
  | standard | ratio ≥ 1.1, 10% slippage | TP +50% | 111 | +0.014 | +0.6% | +5.7% / −9.5% | 32% |
  | **instant** | ratio 1.00–1.10, 10% slippage | **TP +50%** | 80 | **+0.283** | **+17.7%** | +11.4% / +20.0% | 71% |

  Every exit is SL −15% and 30 min max hold. Stops fill well below −15% (−24% on the standard lane, −57% on the instant lane, between 2 s pool reads), and take-profits near +50%: the instant lane wins on its 71% win rate.
- **Verdict rule on the replay** (rc.9's rule with `"strategy"` set): the instant lane passes every check but the count (80 of 100 in 33 h): adjusted net +0.270 SOL, both halves and both days positive, +0.227 without its best 3, 90% interval of the mean above 0. The standard lane at ratio 1.1 fails (net, halves, interval).
- **The frozen rc.11 config, both lanes together** (instant as above; standard on rc.10's entry with TP +50%), on the same capture: 143 positions, net +0.366 SOL. The instant lane makes 80 positions, +0.314 SOL; the standard lane makes 63 positions, +0.053 SOL, both halves positive. There were no breaker trips and no risk refusals. The rc.10 config made 60 positions, +0.061 SOL ([`CHANGELOG.md`](../../CHANGELOG.md) 0.4.0-rc.4 release record).
- **The breaker:** with rc.10's `adaptive_ratchet`, the first two-lane replay halted new buys at 2026-10-30 10:49 UTC for the rest of the capture, after the day gave back half of a +0.044 SOL realized peak: 126 positions instead of 191. A paper run that has to reach a count runs with `"baseline"` (the 10% daily and 25% cumulative drawdown locks stay).
- **Reading:** a second lane worth a counted run. The instant lane is in-sample and its pattern is other people's bots, so it gets rc.11's pre-registered verdict on fresh data, a rule of its own, and a weekly check of its share and ratio distribution. On the standard lane, the wider take-profit helps a little and loosening the entry does not: rc.11 keeps rc.10's entry with TP +50%, an A/B against rc.10 on the same graduates. Replay configs, the per-lane script and the audit trails: `runtime-pump/analysis-rc11/`.
- **Note (2026-10-31):** `runtime-pump/analysis-rc11/` was deleted on 2026-10-30 at the operator's request. The numbers above are the record. Every replay can be run again from `runtime-pump/data/rc9/capture.jsonl*` with `configs/rc11-paper.json` (its file paths removed) and the variants the table names.

### 6.19 rc.9 and rc.10 stopped early; why the instant lane crashed (2026-10-31)

**rc.9 and rc.10, final.** The operator stopped both on 2026-10-30 at about 18:53 UTC to start rc.11 on the same graduates. Neither reached 72 h; both are judged by `configs/verdict_rules.json` (rc.9's pre-registered rule) as they stood:

| Run | Ran for | Positions | Net SOL | Win | Verdict |
|---|---|---|---|---|---|
| rc.9 (`v0.4.0rc2`) | 58.4 h | 55 (32 take profit +0.149, 23 stop −0.116) | +0.034 | 58.2% | NO-GO: 55 of 100 positions. Passes: adjusted net +0.025, both halves, every UTC day. Fails: without the best 3 (−0.002), 90% interval of the mean (lower bound −0.0008) |
| rc.10 (`v0.4.0rc3`) | 9.9 h | 8 | +0.004 | 50% | Not judged: 8 positions |

**Reading.** rc.9's rule (ratio 1.2, TP +20%) made money but about a position an hour, too slowly to ever reach a verdict in 72 h; that is why rc.11 adds the instant lane. rc.10 only confirmed that rc.9's code change (BUG-162) did not move the result.

**The instant lane's first night.** In rc.11's first 11 hours, the instant lane made 17 trades at −25% each, 35% won, against +19.6% and 72% in the replay (§6.18). Six trades lost 64–96% in a single 2-second step from a gain, which no stop can catch. Question: can those coins be told apart before the buy?

- **Data.** Every instant-band graduate whose 60 s price was 1.00–1.10× its first, with rc.11's rule replayed on its recorded path (entry 1.5 s after the signal, TP +50% / SL −15% / 30 min, 2% cost a side). **A**: the rc.9 capture, 29 Oct 08:30 → 30 Oct 17:54 UTC, 82 entries, 13 crashes (a trade at −40% or worse). **B**: rc.11 live, 30 Oct 18:58 → 31 Oct 08:30 UTC (no overlap), 22 entries, 9 crashes.
- **Before the buy, crashes look like the rest.** These were compared, crash against not, in both sets: first market cap and pool, the delay to the first reading, readings before the signal, the signal ratio, its high and low, the drawdown, the volatility, the share of up-ticks, the pool's SOL change, the last 10 s, and the hour. Every median matches within noise. The share of up-ticks is a little higher before a crash (0.83 against 0.75 in A, 0.79 against 0.69 in B), too weak to filter on. These coins are pushed up by their launch bots, smoothly and alike; nothing in the first minute says when the operator will sell.
- **Nearly every instant coin is dumped; the pump height changes.** Of A's 128 instant graduates, 114 fell below 0.6× their 60 s price within the 4 h followed. What changed between A and B is how high they went first: A's coins peaked at a median 2.3× their 60 s price before the fall, B's at 1.3×. In A, entries reached +50% at a median 9.7 min after the migration (56 of 82); in B at 22 min, and only 8 of 22 did.
- **Take-profits, fixed and adaptive** (per trade, A / B):

  | Rule | A | B |
  |---|---|---|
  | TP +50% (rc.11) | +18.6% | −20.7% |
  | TP +30% | +16.8% | −6.7% |
  | TP +20% | +9.9% | −3.2% |
  | TP +15% | +6.0% | +2.4% |
  | Adaptive: lower quartile of the peaks of the instant graduates of the last 6 h, ×0.9 (known before the entry only) | +12.0% | +8.8% |
  | Same, last 2 / 3 / 4 / 8 h | +12.4 / +13.8 / +13.3 / +12.1% | −6.2 / −3.4 / +2.6 / −4.7% |
  | Same with a median, or a 12–24 h memory | +16 to +22% | −8 to −20% |

- **The per-lane pause (trading-core 0.2.3, FEAT-81)** limits losses at the edges and does not change the sign: B at TP +50% goes from −0.091 to −0.078 SOL with a 10-close / −0.03 SOL / 120 min pause; at TP +30%, a 5-close / −0.02 SOL pause turns B from −0.029 to +0.016 SOL (18 trades).
- **Reading.**
  1. No pre-entry filter is supported: crashes cannot be predicted from the first minute.
  2. The lane is a race against a dump that comes to almost every coin; its edge is the pump height, which moved by a factor of two within a day.
  3. TP +50% is the lane's weak point: best in the high-pump period, worst in the low one. Lower fixed targets earn less and hold up better.
  4. The adaptive target is a candidate, not a result: positive in both periods at a 6 h memory, but its sign in B flips with the memory length, which is what noise on 22 trades looks like.
  5. Nothing changes in rc.11 (pre-registered). rc.11-tp20 measures +20% live on the same coins; rc.12 decides between a lower fixed target and the adaptive one on the full rc.11 data, with the per-lane pause on.

### 6.20 rc.11 and rc.11-tp20 read-outs; no exit passes pump-12's design gate (2026-11-03)

The deep analysis of [`PUMP-12-PLAN.md`](PUMP-12-PLAN.md) §5 A, items A1 to
A7, and the design gate of its §2 for the B (instant) and C (momentum)
choices.

**A1. Verdicts.** rc.11: **both lanes NO-GO** by their pre-registered
files. Momentum 52 positions, net −0.018 SOL (adjusted −0.026); instant 245
positions, net −0.477 SOL (adjusted −0.512), every UTC day negative. Buying
was locked for 27 of the 72 hours: the daily 10% lock on 1 Nov 13:23 UTC
(24 h), then the cumulative 25% lock on 2 Nov 15:40 UTC. rc.11-tp20
(exploratory): momentum 71 positions +0.009, instant 405 positions −0.335;
its daily lock on 2 Nov 17:19 UTC stopped buying for its last 13.6 h. Full
tables in [`runs/rc11.md`](runs/rc11.md) and
[`runs/rc11-tp20.md`](runs/rc11-tp20.md).

**A2. Replay parity.** rc.11's capture (2026-10-30 19:02 → 11-02 19:49 UTC,
2,651 migrations, 18 files) replayed with `configs/rc11-paper.json`
through `trading-pump replay`, trading-pump `v0.4.0rc4` on trading-core
`v0.2.2`, `--fee-bps 125`:

| | Run | Replay |
|---|---|---|
| Positions | 297 | 305 |
| Net SOL | −0.4958 | −0.5015 |
| Locks | 1 Nov 13:23:21, 2 Nov 15:40:47 | the same |
| Instant lane | 245 | 247: the same 245 coins plus 2; 244 with the same exit reason; entry price within 0.01% at the median; net on the 245 −0.457 against −0.477 (0.023 of it from 3 positions) |
| Momentum lane | 52 | 58: 49 shared, 9 only in the replay, 3 only in the run; 46 of 49 with the same exit reason; **entry price off by 2.1% at the median** (up to 22%); net on the 49 −0.034 against −0.020 |

- **Cause.** The paper executor fills against a fresh pool read taken at
  the moment of the order (`execution.py`, `PaperExecutor._read`), and the
  capture does not record that read. The replay fills at the last reading
  the capture holds. On the instant lane the order lands on a recorded
  reading (the fill equals a capture row in the 5 cases checked); on the
  momentum lane it lands between two readings 2 s apart, at minute 1, when
  a standard-band coin moves about 2% a reading. The extra and missing
  momentum positions follow from the changed fills (budget and stop
  timing).
- **Result:** parity holds for the instant lane and the run as a whole
  (net within 1.2%); it does not hold to the reading for the momentum
  lane. For pump-12 this matters only for E5's challenger replays; the fix
  is to write the executor's fill read into the capture as a row of its own
  (a new row name, so old captures still read) and let the replay fill
  from it: [BUG-164](BUGS.md#bug-164-a-replayed-buy-fills-at-the-signals-reading-not-at-the-live-buys-fresh-read-resolved),
  for v0.4.0.

**A3. Costs.** The cost per position is 2.4–2.5% of the order on both
lanes and both runs, and 96% of it is the swap fee (125 bps a side, the
fee tier of these coins' market caps); base and priority fees are 0.00001
SOL each per position, and the paper runs charge no tip. The verdict adds a
50 bps exit haircut and a 25,000-lamport tip floor per leg, about 0.75% of
a 0.02 SOL round trip. A take-profit or tier below about +3.2% cannot pay
for itself; the plan's floor of +8% stands. The fee sensitivity (125 against
200 bps a side) is in every row of the design tables below; a 200 bps
column moves every rule down by 1.4–1.6 points per trade.

**A4. Splits.**

| Run · lane | Win | Break-even win | Stops: median / 10th pct | Lost > half the cost |
|---|---|---|---|---|
| rc.11 · momentum (TP +50%) | 35% | 37% | −17% / −92% | 12% |
| rc.11 · instant (TP +50%) | 40% | 51% | −44% / −80% | 24% |
| rc.11-tp20 · momentum (TP +20%) | 54% | 52% | −17% / −34% | 4% |
| rc.11-tp20 · instant (TP +20%) | 61% | 68% | −25% / −63% | 11% |

- **The instant lane loses on its stops.** A −15% stop fills at −25% to
  −44% at the median, because the dump is one reading. Lowering the target
  raises the win rate and the break-even together.
- **Week part and hour (momentum).** In both live runs weekends were
  positive and weekdays negative (rc.11 +0.056 / −0.074; rc.11-tp20
  +0.051 / −0.041). The simulator on the other captures does not confirm
  it: rc.9 (Thursday–Friday only) made money on weekdays, inside the US
  session (+4.4% per trade at TP +20%) and outside it (+1.1%); rc.8
  (Tuesday–Wednesday) was flat. The hour of day changes sign between
  captures (00–12 UTC: rc.9 −2.3%, rc.11 −4.9%, rc.8 +7.7%). No time filter
  meets C4's condition; it stays out.

**A5, A6, A7.** After the design gate, below.

**The design gate.** Every candidate was run through an offline exit
simulator on the recorded readings of four captures: rc.8 (graduation rows,
27 Oct 14:10 → 28 Oct 06:41 UTC), rc.9 (29 Oct 08:30 → 30 Oct 18:52), rc.11
(30 Oct 19:02 → 2 Nov 19:46) and rc.11-tp20 after rc.11's end (2 Nov 19:50
→ 3 Nov 06:53, 453 graduates; the rest of its capture is rc.11's hours).
Signal: the first reading 60–90 s after the migration; entry at the first
reading at least 1.5 s later, refused above the lane's slippage limit;
exits checked at every later reading and filled at its price; the pool fee
a side, the 50 bps haircut and 3.5 × 10⁻⁵ SOL a leg. The simulator ignores
the breaker, so it trades all of rc.11's hours.

- **Calibration** against rc.11's own trades: instant 242 of 245 trades
  with the same sign, total −0.489 against −0.477 SOL; momentum 47 of 50
  with the same sign, slightly optimistic. (On rc.9's momentum lane at TP
  +50% the simulator gives −0.2% per trade where §6.18's engine replay gave
  +5.9%; the difference is not explained, and the rc.11 calibration is the
  stronger check.)
- **Gate** (§2 of the plan): positive on each capture at 125 bps, not
  negative at 200 bps; among those, the best worst capture.

Per trade at 125 bps (200 bps in brackets); n is rc.8 / rc.9 / rc.11 /
rc.11-tp20:

| Lane · rule | rc.8 | rc.9 | rc.11 | rc.11-tp20 |
|---|---|---|---|---|
| instant · TP +50%, 30 min (rc.11) | −26.0% | +18.3% | −9.3% | +0.5% |
| instant · TP +20%, 30 min (rc.11-tp20) | −18.3% | +9.9% | −4.6% | −1.7% |
| instant · TP +15%, 5 min | −11.8% | +5.8% (+4.2%) | −3.3% (−4.7%) | −0.7% (−2.2%) |
| instant · adaptive target (§6.19), 6 min | −12.0% | +6.0% (+4.4%) | −3.0% (−4.5%) | −1.4% (−2.9%) |
| instant · thirds at T/3, 2T/3, T (adaptive T), break-even stop, 6 min | −4.8% | +3.4% (+1.9%) | −3.0% (−4.5%) | −1.6% (−3.1%) |
| n (instant) | 11 | 85 | 450 | 87 |
| momentum · TP +50%, 30 min (rc.11) | −3.9% | −0.2% | −5.1% | +5.9% |
| momentum · TP +20%, 30 min | +0.3% (−1.3%) | +2.7% (+1.1%) | −2.0% (−3.5%) | +3.7% (+2.1%) |
| momentum · adaptive target, 30 min (best worst case) | −0.1% (−1.6%) | −0.4% (−1.9%) | −0.6% (−2.1%) | +2.6% (+1.0%) |
| momentum · TP +15%, 5 min | −1.2% | +1.5% (−0.0%) | −1.7% (−3.2%) | +3.6% (+2.0%) |
| n (momentum) | 33 | 54 | 100 | 17 |

- **61 exit rules per lane** were compared: TP +15/20/30/50% with a max
  hold of 4, 5, 6, 8 or 30 minutes; the adaptive target with the same
  holds; and B3's tier shapes (a), (b), (c) at T = +30%, +50% or adaptive,
  with a 6 or 30 minute hold. **None passes on either lane.** On the
  instant lane every rule loses 2.7% to 4.5% a trade on rc.11; on the
  momentum lane every rule loses on rc.11, the best by 0.6%.
- **105 entry variants** (the momentum ratio from 1.1 to 1.5, with and
  without a 2.0 cap, at 60, 120 and 180 s; the instant ratio band from 0.9
  to 1.3 at 30, 60 and 120 s; each with TP +20%, TP +50% and the adaptive
  target) did not pass either. The best momentum entry, ratio ≥ 1.3 at 60 s
  with the adaptive target, is +1.1% / +2.8% / −0.4% / +3.3% on the four
  captures; the best instant entry is negative on rc.8 and rc.11.
- **What changed.** The instant lane's edge was the pump height of rc.9's
  two days (§6.19); since rc.11 started the same coins peak lower and the
  lane loses whatever the exit. The momentum lane sits at about zero after
  costs on every capture but one. The 2.4% round trip decides both: the
  momentum lane's best rules make +1% to +4% a trade before it.

**What would have to change.** The instant lane's losses are its stop
fills. As a bound, the same rules with every stop filled no worse than −20%
would be positive on rc.9, rc.11 and rc.11-tp20 (TP +50%: +27.1%, +4.9%,
+12.8%; rc.8's 11 instant entries stay negative), and the momentum lane's
TP +20% would pass narrowly (+1.6%, +4.3%, +0.1%, +3.7%). No reading speed
gives that floor: of the instant lane's stops on rc.11, 160 of 171 came
while the pool was read every 2 s (median 3.0 minutes after the
migration), and they still filled at −33% at the median, from a reading
that was +7% at the median. The dump is one step of about 2 s at most;
reading every second would halve the step, not remove it. B5 (faster
reads) cannot rescue the lane on its own.

**A5. Tags and creator funders, backfilled** (graduates split by mint so
the sets do not overlap: rc.9 535, rc.11 1,332, rc.11-tp20 after rc.11 219;
crash: below half the 60 s price within 30 minutes; files and scripts in
`runtime-pump/xfer/a5a6/`, public RPC only):

| Capture | Instant band: crash | of which in one reading | Standard band: crash | of which in one reading |
|---|---|---|---|---|
| rc.9 | 66% | 85% | 77% | 60% |
| rc.11 | 64% | 82% | 75% | 54% |
| rc.11-tp20 | 67% | 78% | 75% | 56% |

- **Mayhem mode:** the program address in the CloddsBot review holds no
  curve for any graduate. Byte 81 of the 166-byte curve account is 1 on 5
  coins, each with a 2-billion-token supply, which matches Mayhem mode;
  all 5 are standard band. No instant coin is one. No use as a filter.
- **A name or symbol seen in the last 24 h:** on the standard band, fewer
  crashes in all three captures (60% / 81%, 64% / 77%, 65% / 77%; p 0.001,
  0.006, 0.36); on the instant band the direction flips. Among momentum
  entries only 8, 14 and 4 coins carry the tag, and the lane result at
  TP +20% reverses on rc.11-tp20. Too few for a filter.
- **Creator funders** (all 889 instant-band creators traced): creator
  wallets are a median 2.6 minutes old at the migration with about 530
  transactions; 773 distinct funders for 816 coins; the few shared ones
  look like exchanges, with ordinary crash rates. A shared funder, a funder
  of an earlier crash and a fresh creator all fail on at least one capture.
  A busy creator (1,000 transactions or more) crashes a little less on all
  three (56% / 66%, 54% / 65%, 62% / 68%), every p above 0.1, with mixed
  lane results.
- **Result:** no tag separates crashes on all three captures with a lane
  result to match. **No entry filter for pump-12**; D2 and D3 stay
  record-only.

**A6. Before the dump** (18 usable of 22 crashed instant-lane coins from
rc.11 and rc.11-tp20, transactions read around the crash reading):
- The pools trade about 10 transactions a second before the dump. The dump
  is a burst of identical sells from many wallets, a median of about 20 in
  one slot.
- In the sampled transactions: no tokens moved outside the pool before the
  burst, no SOL reached the creator, and the burst's sellers do not appear
  as earlier buyers.
- In the last 10 seconds, sells outnumbered buys in 8 of 18 coins, mostly
  where the dump had already begun over several slots; activity halved in
  the last 2 seconds in 5 of 18.
- From the captures, on every instant-lane crash (rc.9 53, rc.11 293,
  rc.11-tp20 55): the reading before the crash had already fallen 5% or more
  in only 4–8%; the price was already 15% below its peak in 23–47% (a
  trailing stop, tried in the design table as shape (b), did not pass).
- **Result:** nothing a 1–2 s reader can act on. FEAT-100 (rug alarm) and
  FEAT-93 (stall exit, B4) are not supported. The identical-sized sells
  from about 20 wallets say the supply was split among sibling wallets
  before the dump; the holder snapshot (D1, FEAT-96) is the way to see that
  at the signal, and stays record-only in pump-12 under the plan's rule.

**A7. pools-1** ([`runs/pools-1.md`](runs/pools-1.md)): 3,122 new
non-graduate pools in 71.7 h, all SOL pairs with no coin creator, 3,095 of
them with SOL on the base side; 92% lose four fifths of their pool SOL
within an hour (liquidity withdrawn). Bought at the first reading with TP
+20% / SL −15% / 30 minutes, a quarter are total losses and the mean is
−12.5% a trade at 125 bps (−10.9% at 30 bps); a 60–90 s momentum entry
gives −2.3% (−0.4%). **No third lane (E3)**; pump-12 does not record new
pools.

**Reading (A1–A7 together).**
1. Neither lane goes to the live gate (pre-registered). No live buy
   builder for pump-12.
2. No exit rule (61 per lane) and no entry variant (105) passes the gate
   the plan set before the analysis; no tag or funder gives a filter; the
   new pools give no third lane. Under the plan the instant lane runs
   record-only (B8). The momentum lane has no qualifying rule either, and
   the plan has no fallback written for it: pump-12's shape goes to the
   operator (plan §9, 2026-11-03).
3. The instant lane's edge was rc.9's pump height, and its losses are
   single-step dumps that no exit at 1–2 s reads avoids. The momentum lane
   is about break-even after a 2.4% round trip on every capture. What is
   left to learn on pump.fun graduates is whether the supply split before
   a dump shows at the signal (D1), which pump-12 can record.
4. The replay matches the run for the instant lane and not to the reading
   for the momentum lane (BUG-164).

### 6.21 After the deep analysis: no PumpSwap lane can pass; the lanes are closed (2026-11-03)

**Scripts** (for this section and §6.20): `runtimes/pump/analysis-pump12/`
(the exit simulator, the walk-forward gate, the read-out and parity tools,
with a README); the supply map in `runtimes/supply-map/`.

**Question.** After §6.20, is there anything left that could make a
PumpSwap lane a GO: an adaptive rule, the coin's supply structure, or any
item of section B of [`PUMP-12-PLAN.md`](PUMP-12-PLAN.md)? Only ideas that
had not already failed on the data were tried. The design gate is §6.20's:
positive on every capture at 125 bps, not negative at 200 bps.

**When the dumps come** (the offline simulator's captures; a crash step is
a single reading 30% or more below the one before):

| Capture | Instant: crash step within 40 min | Price before the crash, vs its peak / vs the first price (median) | Standard: crash step within 40 min | Price before the crash, vs its peak |
|---|---|---|---|---|
| rc.8 | 56% (n = 16) | 0.59 / 0.88× | 82% | 0.69 |
| rc.9 | 77% | 1.00 / 1.69× | 84% | 0.69 |
| rc.11 | 78% | 1.00 / 1.37× | 76% | 0.68 |
| rc.11-tp20 (after rc.11) | 86% | 1.00 / 1.53× | 78% | 0.70 |

Instant coins are dumped at their running peak, in one step: no trailing
stop or stall exit sees it coming. On rc.11, of the instant coins not yet
crashed, 2–4% crash in each of the first three minutes after the migration
and 11–17% in each later interval (minutes 3–5, 5–7, 7–10, 10–15, 15–20);
part of the rise after minute 5 is the slower 10 s reads.

**Short holds** (75 rules: TP +6–20%, SL −10/−15/−30%, held 60–180 s). On
the instant lane all lose on rc.11 (best −1.9% a trade). On the momentum
lane one rule passes the gate at 125 bps, TP +20% / SL −30% / 3 minutes
(+1.0% / +4.8% / +1.8% / +5.8% on rc.8, rc.9, rc.11, rc.11-tp20, −0.5% on
rc.8 at 200 bps), but it is a lone peak: with the stop at −25% or −40%, or
the hold at 150 or 210 s, the worst capture is −0.2% to −1.8%. Not a rule.

**An adaptive gate and selector.** Every lane signal is traded in shadow
under six exit rules (TP +15% / 5 min, TP +20% / 30 min, TP +50% / 30 min,
the adaptive target / 6 and 30 min, TP +20% / SL −30% / 3 min). At each
signal the lane takes the rule with the best mean over its last 10 closed
shadow trades, and trades only if that mean is above 0. Walk-forward on the
continuous capture from rc.9 to rc.11-tp20 (per trade, then the total):

| Lane | Fixed rule (TP +20% / 30 min) | Adaptive | rc.9 | rc.11, first half | rc.11, second half | rc.11-tp20 |
|---|---|---|---|---|---|---|
| instant | 622 trades, −0.275 SOL | 393 trades, −0.019 SOL | +15.9% | +0.8% | −8.5% | −3.9% |
| momentum | 170 trades, −0.004 SOL | 130 trades, +0.075 SOL | +0.9% | +7.8% | −1.3% | +3.8% |

With a memory of 20 or 40 trades the totals move between −0.14 and +0.03
SOL; on rc.8 the momentum selector loses (−3.6% a trade, 21 trades). The
gate stands aside in bad hours and keeps the good ones; it does not make a
bad period pay, and both lanes fail the gate in rc.11's second half. A
simpler gate (trade only when the lane's own last N or last H hours of
shadow trades are positive) gives the same picture.

**The supply map.** Who held each coin's supply at the migration, rebuilt
from the transactions of its bonding curve, for all 902 instant graduates
of rc.9 (126), rc.11 (662) and rc.11-tp20 after rc.11 (114). Read with
Helius on 2026-11-03 (5,491 calls, none failed); script and data in
`runtimes/supply-map/` (`supply_map.py`, `data/features.csv`).
- **Every instant coin is a bundle.** The whole curve (79.3% of the supply)
  is bought in the creation slot by 3–5 signers within about a second (the
  median: 5 curve transactions, 0.8 s); about 7 holders at the migration,
  the largest with about 14%; the creator keeps under 0.4%. A first check
  on the number of curve transactions alone flipped between captures
  (fewer transactions: 41% crashes on rc.9, 70% on rc.11).
- **It predicts crashes** (below half the 60 s price within 30 minutes):

  | Feature at the migration | rc.9 | rc.11 | rc.11-tp20 |
  |---|---|---|---|
  | Wallets with identical balances (with / without) | 81% / 42% (p < 0.001) | 72% / 60% (p = 0.006) | 70% / 66% (p = 0.84) |
  | More than 7 holders (with / without) | 49% / 75% (p = 0.006) | 47% / 66% (p = 0.001) | 60% / 68% (p = 0.73) |
  | Top-5 share ≥ 66% (with / without) | 75% / 49% | 66% / 49% | 68% / 60% |

  Same direction on every capture, significant on two (two-sided Fisher
  exact test).
- **It does not predict the lane's result** (instant lane, TP +20% /
  30 min, per trade, with / without the feature):

  | Feature | rc.9 | rc.11 | rc.11-tp20 |
  |---|---|---|---|
  | Identical balances | +13.2% / +1.9% | −7.6% / −3.3% | +0.8% / −4.2% |
  | More than 7 holders | −4.5% / +13.6% | −13.9% / −4.7% | 2 trades |

  The bundled coins pump higher before they are dumped, so they earned the
  lane more on rc.9; without them the lane still loses on rc.11 and
  rc.11-tp20, at TP +20% and +50%. Top-1 share, creator share, signers,
  curve time and transactions in the creation slot do no better.

**Section B on the supply-map groups.** Eight groups of instant coins (all;
identical balances or not; more or at most 7 holders; creator share above
or below 0.2%; no identical balances and at most 7 holders) against 30 exit
rules (TP +10/15/20/30/50% with holds of 2, 3, 4, 6 and 30 minutes, the
adaptive target with 3, 6 and 30 minutes, and B3's tier shapes a, b, c at
T = +30%, +50% and adaptive), 222 combinations with at least 10 trades on
each capture: **none passes**. The best worst capture is −1.2% a trade
(creator share ≥ 0.2%, thirds at the adaptive target), and every
combination loses on rc.11.

**Item by item** (the plan's section B):

| Item | Result |
|---|---|
| B1 max hold | 2–8 minutes tried; the lane's stops come at about minute 3, so a shorter hold leaves into the same dumps |
| B2 take-profit, fixed or adaptive | Every level from +10% to +50% and the adaptive target lose on rc.11; a lower target raises the win rate and the break-even win rate together |
| B3 tiers | Shapes a, b, c lose on rc.11; each partial sell pays the 2.4% round trip again |
| B4 stall exit | Not supported (A6): the price does not flatten before a dump |
| B5 faster reads | 160 of rc.11's 171 instant stops came on 2 s reads and still filled at −33%; the dump is one slot |
| B6 per-lane pause | Limits a bad period; the adaptive gate, which does the same, still fails the gate |
| B7 budget and size | Changes neither the cost share nor the result a trade |
| B8 instant lane record-only | What is left; a record-only week would repeat what rc.11, rc.11-tp20, pools-1 and the supply map already hold |

**Reading.**
1. The PumpSwap graduate lanes cannot pass the design gate with anything
   seen before the buy or any exit at 1–2 s reads. Their losses are
   operators' dumps of bundled supply, timed at the peak; the result
   depends on how high the operators pump first, which changes from day to
   day.
2. **pump-12 is not run.** Both lanes stay at Stage 1 with rc.11's NO-GO and
   are closed: no counted run, no live path (F), no build of FEAT-92 to
   FEAT-98 for them. The code stays, so every capture can still be
   replayed.
3. The supply map is the one coin-level signal found (it predicts crashes,
   not trade results). It is worth recording if a PumpSwap lane is ever
   reopened, with a new design judged on new data.
4. Next: Meteora DAMM v2, where scout-1 saw the same rule positive
   (trading-scout's `docs/dev/runs/scout-1.md`); `damm-1` (FEAT-107, record-only) on
   this release, then trading-meteora (FEAT-113), which takes FEAT-107 from
   here (ADR-011).


### 6.22 trading-core's venue sweep calibrated on these captures; the rc.9 momentum gap explained (2026-11-03)

**Question.** Before trading-core's strategy library (its ADR-011) judges a
new venue, does its sweep (`trading-core-lanes sweep`, fed by `trading-pump
lane-rows`) reproduce this repository's exit simulator (§6.20) on rc.8,
rc.9, rc.11 and tp20x? And what is the rc.9 momentum gap of §6.20
(−0.2% simulated against +5.9% in §6.18's replay)?

**Method.** Both lanes at rc.11's settings (momentum: ratio ≥ 1.2, first
price 205.44–821.76e-9; instant: 1.0–1.1, first price 1000–2000e-9, first
pool 130–200 SOL), TP +50% / SL −15% / 30 min, 125 bps a side, 50 bps
haircut, 3.5e-5 SOL a leg, 1.5 s entry delay, readings to 40 minutes. The
full rc.11 and tp20 captures are the copies in `runtime-pump/data/` (the
`runtimes/pump/data/` copies stop at 2 Nov 17:01 UTC). Scripts on the Mac
VM in `~/calib/`.

**Result.** The trade simulation (fill reading, exit order, costs, price)
matched this simulator exactly. Two differences were in the library, both
fixed on trading-core's `feature/strategy-library` the same day:

1. `listing_momentum` retried across its 30 s window; this simulator and
   the live lanes decide once, on the first reading at or after 60 s. The
   retries were all the extra trades (momentum +22, +49, +68, +16 on rc.8,
   rc.9, rc.11, tp20x; instant +3, +3, +57, +4), mostly losers.
2. A sale waited for the next reading after its trigger (a median 10.4 s
   on the instant lane after minute 5); a paper sale reads the pool when it
   sells. Every sign flip came from this.

With both fixes the sweep's shared trades agree in sign on every capture
and the means agree within 0.01%. Against rc.11's audit trail it agrees
as this simulator does (242 of 245 instant trades, 47 of 50 momentum, the
same sign).

**The rc.9 momentum gap.** §6.18's +5.9% (0.4.0-rc.4 replay, 60 positions)
was reproduced (59 positions, +5.2%). Of it, 7 coins only the replay
bought averaged +34.7% (about 4 of the 5.4 points): their next reading was
5.8–19% higher, so this simulator's 5% slippage limit refused them, and
the replay bought them at the signal reading's stale price. The rest is
the same stale fill on 29 of the 52 shared trades. This is BUG-164: the
replay was optimistic; the simulator's −0.2% is the figure to keep.
