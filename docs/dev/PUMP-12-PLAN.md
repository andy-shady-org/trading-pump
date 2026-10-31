# pump-12 plan

The plan for `pump-12`, the next counted run of trading-pump's lanes, item by
item. Written 2026-10-31, while rc.11 and rc.11-tp20 were still running.
**This is a plan, not the pre-registration.** Every value below marked
*chosen at the deep analysis* is set on 3 November on data that already
exists (rc.9, rc.11, rc.11-tp20, pools-1), discussed with the operator, and
only then frozen in [`runs/pump-12.md`](runs/README.md) before the run
starts. Nothing here changes a running run.

Sources: the rc.11 health checks and the mid-run findings (project doc
`claude/pump-lane-portfolio-2026-10-31.md`), the instant-lane crash study
([`RESULTS.md` §6.19](RESULTS.md#619-rc9-and-rc10-stopped-early-why-the-instant-lane-crashed-2026-10-31)),
the rug study of 258 instant graduates (2026-10-31), and the CloddsBot
review (project doc `claude/cloddsbot-review-2026-10-31.md`).

## 1. What pump-12 has to answer

**Main question:** does each lane, judged alone, make money after every cost
on graduates it was not designed on, once its exits are built for the rugs
that rc.11 met?

**Secondary questions** (record-only, answered at the read-out, used by
pump-13): do supply concentration, the creator's funder or operator tags
(Mayhem mode, reused names) tell a coin that will be dumped from one that
will not?

Where rc.11 stands (30 Oct 18:59 to 31 Oct 18:13 UTC, before its end):

| Run · lane | Closed | Win | Needs (break-even) | Net SOL | Note |
|---|---|---|---|---|---|
| rc.11 · instant (TP +50%) | 92 | 45% | 52% | −0.132 | 22 trades lost over half their cost |
| rc.11-tp20 · instant (TP +20%) | 76 | 64% | 67% | −0.027 | +0.029 before costs, costs 0.042 |
| rc.11 · momentum (TP +50%) | 26 | 31% | 36% | −0.031 | Friday −0.053, Saturday +0.023 |
| rc.11-tp20 · momentum (TP +20%) | 10 | 60% | 44% | +0.013 | too few to judge |

Three things follow, and the plan is built around them:

1. **The instant lane loses on its losers, not on its win rate.** Its rugs
   fill at −37% to −95% against a −15% stop, so a +20% win (+18% after
   fees) needs a 67% win rate. Cutting the average loss is worth more than
   any entry filter that exists today (§6.19 found none).
2. **Costs are now the margin.** About 2.4% a round trip in swap fees at
   0.02 SOL took rc.11-tp20's instant lane from +0.029 to −0.014 SOL. Small
   take-profits and many partial sells pay this again and again.
3. **The pump height moves by day.** Instant coins peaked at a median 2.3×
   their 60 s price on rc.9 and 1.3× on rc.11's first night; Friday lost and
   Saturday nearly broke even. Exits have to work in both regimes, so
   choices are made on the worst capture, not on the pooled average.

## 2. Rules that keep the result honest

- **Design on old data, judge on new.** Every rule and value in pump-12 is
  chosen on rc.9, rc.11 and rc.11-tp20. pump-12 is never tuned while it
  runs, and a lane that fails is not re-tuned on pump-12's data.
- **Chosen for the worst case.** A candidate rule must be positive on each
  design capture on its own (rc.9, rc.11, rc.11-tp20), at 125 bps a side
  and not negative at 200 bps. Among those that pass, the one with the
  best result on its **worst** capture wins (maximin), not the best pooled.
- **One primary rule per lane is counted.** Up to three challengers per
  lane are written into the run record before the start and replayed on
  pump-12's own capture after the end (same coins, same readings). They are
  exploratory: none can be GO, and the best becomes pump-13's primary only
  if it beats the primary on the same coins in both halves.
- **A feature is recorded before it filters.** A measure seen for the first
  time in pump-12 (the holder snapshot) cannot filter pump-12. A measure that
  can be read today for old coins (operator tags, creator funders) can, if
  it separates crashes on every design capture.
- **Same verdict rule as rc.9 and rc.11**, unchanged (item E4).
- **Long enough to reach a verdict.** rc.9 died at 55 of 100 positions;
  rc.11's momentum lane makes about 26 a day. pump-12 runs 7 days.

## 3. Timeline

Times are Helsinki (UTC+2).

| When | What |
|---|---|
| Sun 1 Nov | US daylight saving time ends; from Monday the US session is 16:30–23:00 Helsinki. Health checks as now |
| Mon 2 Nov 14:33 | scout-1 ends (trading-scout) |
| Mon 2 Nov 20:59 | rc.11 ends: verdict per lane (A1) |
| Tue 3 Nov 08:00 | rc.11-tp20 ends; pools-1 ends at about 09:29 |
| Tue 3 Nov 08:30 | **Deep analysis** (items A1–A7), then the design proposal (B, C, D choices) for discussion. Also US midterm election day: election-themed launches on 3–4 Nov are not typical, and pump-12 starts after them |
| Tue 3 – Wed 4 Nov | Agree the design. Build trading-core 0.4.0's FEAT-92 and FEAT-95 (and FEAT-93 / FEAT-94 if adopted), trading-pump v0.4.0's FEAT-96, FEAT-97, FEAT-98 and FEAT-63's creator funder. The replay gate on every design capture (Stage 0) |
| Thu 5 Nov | Release gates, signed tags (operator, on the Mac), install, 30-minute smoke run, run record with hashes committed |
| Thu 5 or Fri 6 Nov | **pump-12 starts**: 168 h, to Thu 12 or Fri 13 Nov. Friday is the realistic start if the build takes the full two days |
| During the run | Health checks twice a day. Nothing changes. If rc.11 gave a lane GO, the live buy builder is built in parallel (F1) |
| End | Verdict per lane, challenger replays, record-only read-outs, then pump-13 or Stage 2 |

## 4. The items

| ID | Item | Kind in pump-12 | Decided | FEAT |
|---|---|---|---|---|
| **A** | **Before the design: the deep analysis, 3 Nov** | | | |
| A1 | rc.11 verdicts and read-outs; rc.11-tp20 read-out | gate | rules as pre-registered | |
| A2 | Replay parity: rc.11's capture replays to rc.11's positions | gate | must pass for challengers | |
| A3 | Costs per lane: fee tier charged, round-trip cost, cost share of gross; replays at 125 / 200 bps and 0 / 2 s delay | gate | A3 sets the cost floor for B and C | |
| A4 | Splits: weekend / weekday, hour of day, graduations per hour; win rate vs break-even; stop fills vs the stop | input to B, C4 | | |
| A5 | Backfill operator tags and creator funders on rc.9, rc.11, rc.11-tp20; crash rate by tag | input to D2, D3 | | FEAT-98, FEAT-63 |
| A6 | Pre-dump study on a sample of crashed instant coins | input to B4, D4 | | |
| A7 | pools-1 read-out | input to E3 | | |
| **B** | **Instant lane: exits against rugs** | | | |
| B1 | Max hold of about 5–6 minutes | primary rule | chosen at the deep analysis | |
| B2 | Take-profit level: lower fixed or adaptive | primary rule | chosen at the deep analysis | FEAT-97 |
| B3 | Tiered profit extraction with a following stop | primary rule or challenger | chosen at the deep analysis | FEAT-92, FEAT-97 |
| B4 | Stall exit | challenger, or primary if it passes everywhere | only if A6 supports it | FEAT-93 |
| B5 | Faster reads: 1 s for the first 5 minutes | config, both lanes | RPC budget | |
| B6 | Per-lane pause | config | chosen at the deep analysis | FEAT-81 (built) |
| B7 | Per-lane budget and order size | config | | FEAT-81 (built) |
| B8 | Fallback: instant lane record-only | config | if nothing passes B's gate | |
| **C** | **Momentum lane** | | | |
| C1 | Take-profit +20% or +50% | primary rule | chosen at the deep analysis | |
| C2 | Tiers for momentum | challenger, or primary if better on every capture | | FEAT-92 |
| C3 | Stop and max hold | primary rule | unchanged unless A4 says | |
| C4 | Trading hours | primary rule or challenger | only if A4's effect holds on rc.9 too | FEAT-94 |
| **D** | **Record-only: questions for pump-13** | | | |
| D1 | Holder snapshot at the signal | record, pre-registered hypothesis | | FEAT-96 |
| D2 | Creator's funder | record, or filter if A5 finds a pattern | A5 | FEAT-63 |
| D3 | Operator tags: Mayhem mode, reused names | record, or filter if A5 finds a pattern | A5 | FEAT-98 |
| D4 | Pre-dump data: holder snapshots at 3 and 6 minutes | record | | FEAT-96, FEAT-100 later |
| **E** | **Run setup** | | | |
| E1 | Code: trading-core 0.4.0, trading-pump v0.4.0, both signed | build | | |
| E2 | Length: 168 h, fixed end | config | | |
| E3 | A third lane on new non-graduate pools | lane, only if A7 passes | A7 | FEAT-80 |
| E4 | Verdict files, one per lane, rc.9's rule | pre-registration | | |
| E5 | Challengers in the run record | pre-registration | | |
| E6 | Smoke run, then the run record before the start | gate | | |
| E7 | Health checks, no changes, stop rules | operations | | |
| E8 | Breaker settings | config | | |
| **F** | **Live path, by verdict** | | | |
| F1 | PumpSwap buy builder, `LiveExecutor`, reconcile | build, only after a GO | A1 or pump-12's verdict | |
| F2 | Jito bundles and the tip experiment | build, with F1 | | FEAT-99 |
| F3 | Stage 2 live canary at 0.02 SOL | stage | pump-12 GO | |
| **G** | **Beside pump-12, other repositories** | | | |
| G1 | Polymarket Up/Down tick recorder and maker study | research | | FEAT-101 |
| G2 | Polymarket full-set scanner, a week of records | research | | FEAT-102 |
| G3 | Polymarket expiry-fade backtest | research | | FEAT-103 |
| G4 | Meteora DBC launchpads' graduates | research | | FEAT-104 (trading-scout) |

## 5. The items in detail

### A. Before the design (deep analysis, Tue 3 Nov)

**A1. rc.11 verdicts and read-outs.** Each lane judged alone by its
pre-registered file (`verdict-rc11-standard.json`, `verdict-rc11-instant.json`)
with `trading-core-audit verdict`; the read-out into
[`runs/rc11.md`](runs/rc11.md) and `RESULTS.md`; rc.11-tp20 read against
rc.11 over the same hours, per lane, in [`runs/rc11-tp20.md`](runs/rc11-tp20.md).
A GO sends that lane to the live gate (F1) whatever pump-12 does.

**A2. Replay parity.** Replay rc.11's capture with `configs/rc11-paper.json`
through `trading-pump replay`: the same positions as the run, fills at the
same readings, net within the fee rounding. Same for rc.11-tp20. This is
the open migration-gate item in [`TODO.md`](TODO.md#migration-gate-before-pumpfun-trading-is-deleted)
and it matters more now: every B and C choice, and every challenger in E5,
is judged by replay. If parity fails, the difference is found and fixed
before any design choice is trusted.

**A3. Costs.**
- Per lane: the swap fee actually charged on these coins (the fee config's
  tier for their market cap), priority fee, rent; round-trip cost in % of
  the order; costs as a share of gross.
- The TODO's sensitivity replays: 125 and 200 bps a side, entry delay 0 and
  2 s.
- From this, the **least tier gain worth taking**: a partial sell has to
  clear the round trip, the verdict's 50 bps exit haircut and its tip floor
  per sell (25,000 lamports, about 0.13% of 0.02 SOL). At about 2.4% a
  round trip that is roughly 3%; the plan takes no tier below +8%.

**A4. Splits.** Per lane and run: weekend against weekday, hour of day (US
session 14:30–21:00 UTC from 2 Nov against Asia / Europe hours),
graduations per hour from the capture as the activity measure; win rate
against break-even win rate; stop fills against the stop level. rc.11 is
mostly a weekend; rc.11-tp20 has Monday's whole US session.

**A5. Backfills on old coins.** For every graduate in rc.9, rc.11 and
rc.11-tp20:
- the Mayhem flag and the name and symbol, read now from the curve and mint
  accounts (FEAT-98's `tag-capture`, or the same reads in a script);
- the creator wallet's funder: its first incoming SOL transfer, the funder's
  age and its other coins in the 24 h before (FEAT-63's creator part).

Then: crash rate (a trade at −40% or worse, as §6.19) and lane result by
tag, on each capture. **A tag that separates crashes on all three captures
can become a pump-12 entry filter** (chosen on old data, judged on new). One
that does not stays record-only (D2, D3).

**A6. Pre-dump study.** A sample of about 30 crashed instant coins from
rc.11: the transactions of the mint in the 5 minutes before the dump. Does
supply move first (top holders sending tokens to new wallets, splitting),
does SOL arrive at the creator, do the launch bots stop buying (the price
going flat before the drop)? This decides B4 (stall exit) and FEAT-100 (rug
alarm). The rug study already showed that per-creator and per-name timing
do not work (fresh wallets every coin; a per-name exit time no better than a
global one out of sample).

**A7. pools-1 read-out** (FEAT-80): paths of new non-graduate pools from
their first reading, an executable 0.02 SOL round trip from the pool's own
fee, against the graduates in the same hours. Decides E3.

### B. Instant lane: exits against rugs

The lane's population is predictable: 91% of instant coins crash, a quarter
by minute 7 after the migration and half by minute 18, and 79% of crashes are
a single reading losing more than 60%. The lane buys at minute 1. Its job is
to be out, with whatever the launch bots gave, before the operator sells.

**B1. Max hold.** About 5–6 minutes in place of 30, chosen on rc.9 and
checked on rc.11 and rc.11-tp20 (the deep-analysis plan's "instant max-hold
replay"). A position that has not reached its target by then is sold at the
next reading. Candidates: 4, 5, 6, 8 minutes.

**B2. Take-profit level.** From §6.19, per trade on rc.9 / rc.11's first
night: TP +50% +18.6% / −20.7%; +30% +16.8% / −6.7%; +20% +9.9% / −3.2%;
+15% +6.0% / +2.4%; adaptive (lower quartile of the last 6 h of instant
peaks, ×0.9) +12.0% / +8.8%. The deep analysis re-runs these on the full
rc.11 and rc.11-tp20 data, with B1's max hold. The adaptive target
(FEAT-97) is built so that it can be chosen; it was positive in both regimes
at a 6 h memory but flipped sign with the memory length on 22 trades, so it
wins only if it holds on the full data.

**B3. Tiered profit extraction** (trading-core FEAT-92, the lane's part in
FEAT-97). Take part of the move early, let the rest run, and never let a
position that reached its first tier become a full loss. Candidates, each
with B1's max hold, tier gains as fixed values or as multiples of B2's
adaptive target (T):
- (a) half at T/2, half at T; stop to break-even after the first tier;
- (b) half at T/2; the rest on a trailing stop 10% below its peak;
- (c) a third each at T/3, 2T/3 and T; stop to break-even after the first;
- (d) no tiers, B2 alone (the control).

Each tier is a separate sell and pays its own transaction and tip floor in
the verdict, so more tiers must earn more than they cost; no tier below
+8% (A3). Expected effect: a higher win rate (a position that sold half at
+10% is rarely a loss) and a smaller average loss, against a smaller average
win. The deep analysis compares them on break-even win rate as well as
net.

**B4. Stall exit** (FEAT-93, conditional). Out when a position at least X%
up has made no new high for N seconds. Tried in the replay only if A6 shows
prices going flat before dumps. Kept only if it passes everywhere.

**B5. Faster reads.** `graduation.fast_poll_interval_seconds` 1 instead of 2
for the first 300 s. Stops and targets fill one reading sooner, and the
lane's exits happen in exactly those minutes. Cost: about 1.25 M more
credits per 30 days for one run ([`COSTS.md` §3.3](COSTS.md#33-on-the-new-stack-trading-pump-040-from-2026-10-28)),
affordable once rc.11, rc.11-tp20 and pools-1 have stopped. It applies to
both lanes. It cannot be replayed on the 2 s captures, so it is a known
difference from the design data and is written as such in the run record.

**B6. Per-lane pause** (FEAT-81, built in trading-core 0.2.3). §6.19: at
TP +30% a 5-close / −0.02 SOL / 120-minute pause turned rc.11's first night
from −0.029 to +0.016 SOL; at TP +50% it only trimmed the loss. Values
chosen at the deep analysis on all captures. It limits a bad regime; it does
not make a losing rule win.

**B7. Budget and size.** `strategies.pumpswap_instant.max_active_positions`
and `max_exposure` from the design replays; `order_size` 0.02 SOL as in
every run so far (the pools hold 130–200 SOL, so the order moves no price;
size does not change the fee share either).

**B8. Fallback.** If no instant candidate passes the replay gate on every
design capture, the instant lane runs record-only in pump-12 (`enabled`
false; its graduates are still followed and recorded for D). That is a
result, not a failure.

### C. Momentum lane

**C1. Take-profit.** +20% or +50%, decided on rc.11 against rc.11-tp20 on the
same coins (so far 9 coins: TP +50% +0.024, TP +20% +0.016 SOL) and on the
rc.9 replay (+5.9% per trade at +50%, +5.1% at +20%, §6.18), by the maximin
rule.

**C2. Tiers.** B3's shapes, tried on the momentum lane; primary only if
better on every capture, otherwise one challenger.

**C3. Stop and max hold.** −15% and 30 minutes stay unless A4 shows the
stop filling far below its level on this lane too (rc.9: −24%).

**C4. Trading hours** (FEAT-94, conditional). The momentum lane needs
follow-on buyers, who may switch off at weekends or outside US hours
(Friday −0.053, Saturday +0.023). A time filter enters only if A4 finds an
effect that also holds on rc.9, and only if the lane still reaches 100
positions in 7 days with it; otherwise it is a challenger.

### D. Record-only: questions for pump-13

**D1. Holder snapshot** (FEAT-96). At the signal of every in-band graduate,
bought or not: the top-1, top-5 and top-10 share of the supply outside the
pool, accounts above dust, the creator's share; plus snapshots at 3 and 6
minutes for instant coins. **Pre-registered hypothesis** (written into the
run record): instant entries in the top third of top-10 share crash (−40%
or worse) more often than those in the bottom third, one-sided Fisher exact
test p < 0.05, the same direction in both halves of the run. The same is
reported for momentum, without a test. A pass makes a holder filter
pump-13's candidate, judged on pump-13's data.

**D2. Creator's funder** (FEAT-63). Recorded for every graduate. A filter in
pump-12 only through A5.

**D3. Operator tags** (FEAT-98). Mayhem flag, `name_seen_24h`,
`symbol_seen_24h`, recorded for every graduate. A filter in pump-12 only
through A5.

**D4. Pre-dump data.** D1's 3- and 6-minute snapshots against the moment of
each crash: does the top holders' supply move before the dump? Feeds
FEAT-100's design if A6 found a lead.

### E. Run setup

**E1. Code.**
- trading-core **0.4.0**: what is on `release/v0.4.0` (local clock times,
  TC-10), plus FEAT-92 and FEAT-95, plus FEAT-93 / FEAT-94 if adopted. A
  money-path change (exits), so its release record includes the reference
  replay (trading-core `RELEASE-GATE.md` §2.3). Signed tag.
- trading-pump **v0.4.0**: FEAT-91 (token names, merged), FEAT-96, FEAT-97,
  FEAT-98, FEAT-63's creator funder; `trading-core>=0.4.0,<0.5`; signed tag,
  installed with `bin/install-release.sh` (which refuses unsigned tags) and
  loaded under `modules.toml`'s `live` policy.
- `configs/pump-12.json`, `configs/verdict-pump-12-standard.json`,
  `configs/verdict-pump-12-instant.json` (and `-pools` if E3), hashed in the
  run record.

**E2. Length.** 168 h with a fixed end, written in the record. Seven UTC
days, five US sessions, one weekend. At rc.11's pace about 180 momentum and
600 instant positions, so both lanes reach the count with room even if a
pause or a time filter removes a share.

**E3. A third lane.** A lane on new non-graduate PumpSwap pools (FEAT-80's
lane, not built) only if A7 finds an edge after costs on pools-1, replay is
taught to read `new_pool` rows, and the lane passes the same replay gate.
Otherwise new pools stay unrecorded in pump-12 (pools-1 has the data; the
feed costs about 3 GB a day, `COSTS.md` §3.3).

**E4. Verdict files.** One per lane, `"strategy"` set, rc.9's rule
unchanged: at least 100 closed positions; adjusted net above 0 after a
50 bps exit haircut and a 25,000-lamport tip floor (applied to every sell,
so tiers pay theirs); both halves positive; at least 50% of UTC days
positive; positive without the best 3; the 90% bootstrap interval of the
mean above 0.

**E5. Challengers.** At most three per lane, each a complete config, listed
with their hashes in the run record and replayed on pump-12's capture after
the end (A2 must have passed). Likely: the B3 shapes that lost narrowly,
the other C1 target, C4's time filter if it is not primary.

**E6. Before the start.** A 30-minute smoke run on the release build (live
data seen, the capture's first row is the start time, the holder and tag
rows written, the RPC load as expected); the run record committed with
every hash; then the start.

**E7. During the run.** Health checks at 08:00 and 20:00 Helsinki as for
rc.11 (positions and net per lane, pauses, feed drops, errors, capture
health), the daily summary, no edits. A fault in the engine or the feed that
corrupts the data stops the run: it is read out as INCONCLUSIVE and the next
run takes a new number (pump-13).

**E8. Breaker.** `drawdown_reference_mode` `"baseline"` as in rc.11, so the
run reaches its count (the 10% daily and 25% cumulative locks stay);
per-lane pauses as B6.

### F. Live path, by verdict

**F1. Live buy builder.** Only for a lane with a GO, from rc.11 (A1) or from
pump-12: the PumpSwap buy builder checked against real mainnet transactions,
`LiveExecutor`, reconcile, one live sell and one live round trip at the
smallest size ([`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane)).
Built beside pump-12; it does not touch the paper run.

**F2. Jito bundles** (FEAT-99). Part of F1: send through Jito's block engine
with a tip or through the RPC, measured in the live gate's tip experiment
(0 / 25k / 50k lamports per side): landing rate, delay, slippage against the
quote. Kept only where the slippage saved is more than the tip.

**F3. Stage 2.** A lane with a pump-12 GO goes to the live canary at
0.02 SOL on a dedicated hot wallet, reconciled daily; acceptance as in the
live gate (at least 100 closed positions, net positive after every cost,
reconciliation within tolerance every day).

### G. Beside pump-12 (other repositories)

Not part of the run; listed so the whole plan is in one place. Each is in
its repository's `docs/dev/PROPOSED-FEATURES.md`.

- **G1. FEAT-101 (trading-polymarket):** a tick recorder for the crypto
  Up/Down markets (spot ticker plus Polymarket book and trades over
  WebSockets) and a maker study: maker P&L by time to expiry, quotes pulled
  on spot moves and on book imbalance, conservative fills. The crypto-updown
  study found taking a loser and making about break-even before rebates.
- **G2. FEAT-102 (trading-polymarket):** the existing `arb` scanner extended
  (buying every No of an event, the book walked for size, how long each gap
  lasts, a loop mode) and run for a week; an executor only if the gaps are
  frequent, large and lasting.
- **G3. FEAT-103 (trading-polymarket):** a one-hour backtest of "expiry
  fade" (buy the cheap side in the last minutes when spot is flat). Low
  prior; stop if negative after fees.
- **G4. FEAT-104 (trading-scout):** graduates of Meteora DBC launchpads,
  whose pools can lock the creator's liquidity: do they rug less than pump
  graduates? Record-only coverage first.

### Not in pump-12, and why

| Idea | Why not |
|---|---|
| Copying wallets | Copying every captured wallet lost (§6.8); a copier buys after the wallet and becomes its exit liquidity |
| Coordinated buys from many wallets ("swarm") | Manufactures demand to sell into: market manipulation, and the mechanism behind the rugs this lane loses to |
| Cross-DEX arbitrage on Solana | Taken by searchers with co-located infrastructure; the feed here is seconds behind |
| Tracking rug creators | Fresh wallet per coin: 253 creators for 258 coins, none reused |
| Exit times per coin name | No better than one global exit time out of sample (rug study) |
| Price filters on instant entries | Crashes look like the rest in the first minute (§6.19) |
| A larger order size | The fee is a share of the order; size changes nothing but risk, and paper cannot show impact |
| Latency arbitrage on Polymarket Up/Down | An artefact of minute data; the book reprices within the minute (crypto-updown study) |

## 6. After pump-12

| Outcome per lane | Next |
|---|---|
| GO | Live gate (F1, F2), then Stage 2 (F3) |
| NO-GO, a challenger better on the same coins in both halves | That challenger is pump-13's primary, judged on pump-13 |
| NO-GO, nothing better | The lane is retired or kept record-only; its data stays for research |
| INCONCLUSIVE (fault) | Fix, then pump-13 with the same pre-registered rules |

The record-only answers (D1–D4) decide pump-13's filters whatever the
verdicts are.

## 7. Build list by repository

| Repository | Release | Items |
|---|---|---|
| trading-core | 0.4.0 (on the held `release/v0.4.0`) | FEAT-92 tiered take-profit; FEAT-95 break-even per strategy; FEAT-93 and FEAT-94 if adopted |
| trading-pump | v0.4.0 | FEAT-96 holder snapshot; FEAT-97 instant-lane exits; FEAT-98 operator tags and `tag-capture`; FEAT-63 creator funder; `trading-core>=0.4.0,<0.5`; configs and verdict files for pump-12 |
| trading-pump | later, after a GO | Live gate with FEAT-99; FEAT-100 only after A6 |
| trading-polymarket | its own releases | FEAT-101, FEAT-102, FEAT-103 |
| trading-scout | its own releases | FEAT-104 |

## 8. Risks

- **The launch bots change.** The instant lane trades other people's bots;
  the pattern can shrink or stop. The weekly check in `TODO.md` (the instant
  family's share of migrations and its 60 s ratio distribution) runs during
  pump-12 too, and the adaptive target is the hedge against a change in pump
  height.
- **Too many choices on the same data.** B and C compare a few dozen
  combinations on three captures. The maximin rule, the 200 bps check and a
  short candidate list limit how far this can overfit; pump-12 is the test
  that counts.
- **Paper is not live.** Paper fills at the next reading with a fee model;
  live adds landing delay, failed sends and possibly sandwiches. F2 and the
  live gate measure these; Stage 2 is where they show.
- **Replay parity.** If A2 fails, challengers cannot be trusted until it is
  fixed.
- **One week is still a small sample** for a lane whose edge is a few
  percent a trade. The bootstrap interval in the verdict says so when it is.

## 9. History

- 2026-10-31: written from the rc.11 review, the crash and rug studies and
  the CloddsBot review; FEAT-92 to FEAT-104 proposed in their repositories.
