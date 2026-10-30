# Strategy

trading-pump has two lanes over the same graduates, both in paper only.
`pumpswap_momentum` (FEAT-76): buy a coin that has just graduated from its
Pump.fun bonding curve to PumpSwap and is still holding its price a minute
later. `pumpswap_instant` (FEAT-78, from 0.4.0-rc.4, §6): buy an *instant*
graduation, a coin whose curve was bought out in one go, while it is
holding, not running. This page says what
the rule is, why it is this rule, how its prices and costs are computed, and
how it is judged. The evidence is in
[dev/STRATEGY-PIVOT.md §6](dev/STRATEGY-PIVOT.md#6-results-log); pumpbot's
strategy manual (launch sniping, momentum, pre-graduation, tiers, Kelly
sizing) is [archived](archive/pumpfun-trading/STRATEGY.md).

## 1. Why this lane, and only this one

From rc.1 to rc.8 pumpfun-trading paper-traded about 25,000 Pump.fun
positions across every lane it had: launch buying, confirmed momentum,
pre-graduation, copy trading in simulation. **Every setting lost after
costs** (§6.3–§6.13). Launch buying lost 4–5% per trade whatever the exits;
a round trip on the curve costs about 4.4% in paper. The one signal that did
not lose was on PumpSwap, after graduation (§6.13):

* Of 569 migrations recorded in rc.8, the median pool was at 0.96× its first
  price after 1 minute, 0.72× after 5 and 0.09× after 15; half were below
  0.1× by 15 minutes. Coins that crash do not come back (0 of 39 in the rc.6
  candles).
* Buying at the migration loses. Buying the **survivors**, the coins still at
  least 1.1–1.2× their first pool price 60–120 s after the migration, out at
  +20% with a −15% stop, made +1.3% to +5.7% per trade at 2% cost a side in
  both halves of the data, against −7.3% for a random entry.
* n was 42–72 and every 90% interval included 0: a lead, not a result.

So the rule was pre-registered from that read-out, built as the only lane of
the new module, and is judged on fresh data before any capital.

## 2. The rule

For every graduate followed (FEAT-73,
[CONFIGURATION.md](CONFIGURATION.md#graduation-following-graduates-feat-73)):

1. **First reading.** The first pool reading after the migration event (a
   median 1.2 s after it in rc.8) is the reference price.
2. **Standard pool.** Its market cap must be 0.5–2× of 410.88 SOL, the
   market cap of a curve that has just completed (85 SOL real plus the 30 SOL
   virtual reserve against about 279 M tokens). About 60% of PumpPortal's
   migration events are pools already empty, large established pools or odd
   ones; this keeps the standard graduations (a pool of about 84 SOL).
3. **Signal reading.** The first reading at least `signal_after_seconds` (60)
   after the migration, and no later than `signal_window_seconds` (30) past
   that; otherwise no decision is made.
4. **Buy** when the signal price is at least `min_ratio` (1.2) times the
   first price, the pool is not drained and holds at least `min_pool_sol`.
   The order is limited to the signal price plus `slippage_bps` (5%).
5. **One decision per graduate.** A coin that fails is never looked at again.
6. **Exits** are the engine's `ExitRules`: take profit at +20%, stop at −15%,
   out after 30 minutes at most; or the lane's own (`lane.exits`, FEAT-79,
   §6). The engine marks the position with the
   module's exit value (what selling into the pool would return after the
   fee) on every cycle.
7. **Size** is the engine's `order_size` (0.02 SOL in the example), within
   its risk limits and circuit breaker.

The anti-rug screen can be put in front of the analyst
(`lane.screen_entries`); it is off because the rule was registered without
it.

## 3. Prices and costs

All prices come from the module's own on-chain pool reads, never a third
party's quote:

* **Price** = SOL reserve / token reserve (the SOL side includes the pool's
  virtual quote reserve, as the program prices with it); market cap = price ×
  1 B tokens.
* **Buy**: the swap fee is taken from the SOL in,
  `swapped = in × 10000 / (10000 + fee_bps)`, and the rest swaps along the
  constant product: `tokens = base × swapped / (quote + swapped)`.
* **Sell**: `pumpswap_sell_quote` (the program's own maths): the tokens swap
  for SOL along the constant product and the fee comes off what comes out.
* **Swap fee**: the pool's tier in the PumpSwap fee config by market cap on
  the mint's real supply (as the program prices it; burns take it below 1B
  tokens, BUG-162), else the AMM `global_config` total, never below
  `fee_bps_floor`. Checked against 94 real trades of fresh graduates
  ([dev/STRATEGY-PIVOT.md §6.16](dev/STRATEGY-PIVOT.md#616-pumpswap-fee-check-the-cost-model-holds-on-the-mints-real-supply-2026-10-29)):
  125 bps a side below 420 SOL, 120 bps from there, and the pool maths
  reproduces their fills. Replays use a fixed fee (`--fee-bps`, 125 by
  default); 200 is a stress, not a plausible fee.
* **Network costs** on every fill: 5,000 lamports base fee, the priority fee
  (5,000 lamports in the example), a Jito tip when on, and 1,513,840 lamports
  of Token-2022 account rent on the first buy of a coin, refunded at the full
  exit. At 0.02 SOL a trade the rent is 7.6% of the stake for the life of the
  position: it is booked, not ignored ([dev/COSTS.md](dev/COSTS.md)).
* **Latency**: `paper_entry_delay_seconds` (1.5 s in the paper example) delays the read a paper buy fills
  at. pumpbot learnt that a paper fill without the latency a live fill pays
  makes a losing rule look good (BUG-121, BUG-126).

## 4. How it is judged

`configs/verdict_rules.json` is the pre-registered go / no-go rule, fixed
before a run starts and never edited after: at least 100 closed positions;
adjusted net above 0 after a 50 bps exit haircut and a tip floor of 25,000
lamports per transaction; both halves of the run positive; at least half
the UTC days positive; positive without the best 3 positions; and the lower
bound of a 90% bootstrap interval of the mean per position above 0. Judge a
run with:

```bash
trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict_rules.json
trading-core-audit pnl --path data/paper/audit.jsonl --group-by reason
```

Record the rule's sha256 (printed by the verdict) and the run's provenance
in the release record ([dev/RELEASE-GATE.md](dev/RELEASE-GATE.md)).

Rules pumpbot learnt that apply to any lane here:

* Beat a random cut: a filter on a losing lane "improves" net PnL because it
  trades less (AGENTS, `[ANALYSIS]`).
* Judge per position, never per sell (BUG-105).
* Treat a paper result far above costs as a bug until it is explained
  (BUG-104).
* Before building for a pattern seen on charts, measure how often it happens
  across every coin it could have happened to (charts show survivors).

## 5. Where it stands

| Step | State |
|---|---|
| Rule found on rc.8 (16.6 h) | done, §6.13 |
| Lane, paper executor, replay on the new stack | done; the replay reproduces the read-out (+1.1% per trade at 125 bps, −0.4% at 200 bps, NO-GO on count and interval), §6.14 |
| 72 h paper run on fresh data, pre-registered verdict | rc.9 and rc.10 running ([dev/TODO.md](dev/TODO.md#feat-76-pumpswap-post-graduation-momentum-lane)) |
| Instant lane (FEAT-78) and lane exits (FEAT-79), replayed through the engine on rc.9's 33 h | done: the instant lane passes every verdict check but the count (80 of 100), §6.18 |
| rc.11: both lanes, 72 h paper, a verdict per lane | next |
| PumpSwap buy builder checked against mainnet, one live round trip reconciled | only if the paper run passes |
| Stage 0 / Stage 1 live gate | after that ([dev/RELEASE-GATE.md](dev/RELEASE-GATE.md)) |

Known risks (from the FEAT-76 proposal): the edge is small next to the
noise and sensitive to latency; snipers trade the migration block, so live
fills may be worse than paper's next reading. The fee tier was checked on
real third-party trades (§6.16); our own first live fill still has to confirm it.

## 6. The `pumpswap_instant` lane (FEAT-78)

**Why.** rc.10 bought 7 of 310 graduates. About 60% of migrations never
reach the standard lane: their first pool is not the 410.88 SOL market cap of
a just-completed curve. One group among them is regular: coins whose first
reading shows a market cap of **1,000–2,000 SOL with 130–200 SOL in the
pool**, about 125 of 1,079 migrations in 33 h. Their launch bots buy the
whole curve in a block or two and keep buying for the first minutes after the
migration; chasing them at 1.1× or more loses, but the ones still **at
1.00–1.10× their first price after 60 s** climb on (rc.9 / rc.10 replays,
[dev/STRATEGY-PIVOT.md §6.18](dev/STRATEGY-PIVOT.md#618-rc9-and-rc10-replays-a-second-lane-and-wider-take-profits-2026-10-30)).

**The rule** (`instant`, [CONFIGURATION.md](CONFIGURATION.md#instant-the-pumpswap_instant-lane-feat-78)):

1. The graduate's first reading is in the instant band (market cap
   1,000–2,000 SOL, pool 130–200 SOL); it goes to this lane, never to the
   standard one.
2. At the same signal reading as the standard lane (60 s, 30 s window), buy
   when the price is at least 1.00× and below 1.10× the first price.
3. Exits are the lane's own: take profit **+50%**, stop −15%, out after 30
   minutes. The wide take-profit is the point: the winners run, and +20%
   would sell them early.

**Risks.** The pattern is other people's launch bots and can change in a day;
it is watched weekly while the lane runs. Stops fill well below −15%: a
coin being dumped falls far in the 2 s between pool reads, −57% on average
in the replay, so the lane lives on its win rate. The size is the
engine's `order_size` (0.02 SOL), which bounds a rug. The buy path is
paper only, like the standard lane's.

**Wider take-profits on the standard lane.** `lane.exits` (FEAT-79) lets
the standard lane run its own exits too. A lane's exits are decided by the
module on the pool mark; the engine's `exits` must then be `{}`, or the
engine's +20% fires first ([CONFIGURATION.md](CONFIGURATION.md#lane-the-pumpswap_momentum-lane-feat-76)).

