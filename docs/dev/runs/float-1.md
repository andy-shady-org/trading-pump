# Run float-1

**Record-only capture of Float (FEAT-179), 14 days: rules designed on the
first 7 days, frozen, and judged on the last 7.**

- Float (floatlaunch.xyz) launches coins on Raydium LaunchLab curves; a
  filled curve migrates to a Raydium CPMM pool.
- The run records every launch, curve trade (with its trader), graduation
  (with the largest holders) and each graduate's CPMM pool, trade by trade
  for 2 h and read every 2 s for 30 min ([`FEATURES.md` §2.4](../../FEATURES.md#24-the-float-capture-feat-179-record-only)).
- pump.fun graduation tracking and every lane are off. Nothing is bought.

## Pre-registration (written 2026-11-09 13:35 UTC, before the start)

**Question:** while Float is young and its trading still natural, is there
an entry-and-exit rule on its curves or its graduates that clears its costs
on days it was not designed on?

**Why now:**
- The 9 Nov re-look (`claude/float-launch-2026-11-08.md`) found the
  structure natural:
  - creation-slot buyers had a median of 1–2 against pump.fun's 5;
  - after graduation, one-transaction dumps hit 10 of 49 graduates against
    61% on pump.fun.
- No rule paid on that look:
  - curve momentum lost 10–20% a trade, weighted to the population;
  - ee-1's rule had 6 graduate entries.
- The operator expects snipers and ruggers to arrive in time, so the
  platform is recorded while it lasts.

**Code:**
- trading-core `v0.7.0` (`cceeed4e2c300eba612dedbd4d2699b6b863815e`);
- trading-pump `v0.6.0` (`9de5bc6479aee543af9e0f18bfa4281c75db53ad`);
- trading-solana `v0.4.0` (`c62a71e6231236681d19adb0eeaad65846eee2cc`);
- runtime venv `pump-v0.6.0` in `runtimes/pump`, beside `ee-1`'s
  `pump-v0.5.0`.

**Config:** `configs/float-1.json`, sha256
`eda4c4ca699da43fde234263cb3552d863652cac01487afe011b692881026341`.
- It is the release's `configs/float-1.example.json` with its comment and
  the capture's retention set to 200 parts and 60 days (the default 100
  parts and 30 days would hold it too).
- Its settings: `graduation.enabled` and `lane.enabled` false;
  `float_capture` on with its defaults:
  - `confirmed` commitment;
  - the platform list read again every hour;
  - CPMM trades for 7,200 s and readings every 2 s for 1,800 s;
  - at most 50 graduates at once;
  - trader lookups at 4 a second, with 20,000 queued at most.
- Rows go to `data/float-1/capture.jsonl`.

**Start and end:**
- **Start:** when the operator starts it on 2026-11-09. `data/float-1/RUN.txt`
  and the capture's first row give the time.
- **Planned end:** the start plus 336 h (`--run-for 336h`).

**The halves (fixed now):**
- T0 is the `timestamp` of the capture's first row.
- **Design:** rows with `timestamp` < T0 + 604,800 s (days 1–7).
- **Test:** the rest, to the end. Rows are placed by their receive
  `timestamp`, never by block time.

**How rules are made and judged (there are no verdict files at the start):**

1. **Design (days 1–7):** rules for curves (entries on curve state and flow
   from `float_trade`, `float_trader` and `float_launch` rows) and for
   graduates (`float_migration`, `float_cpmm_trade`, `float_pool_reading`).
   They are explored on the design half only. Any number may be tried; each
   one tried is listed with its design result.
2. **Freeze, before any test-half row is read:** each rule to be judged goes
   in `runs/float-1-rules.md` and is committed. A rule not listed there is
   not judged, and nothing in the list changes after the commit. Each rule
   is written with:
   - entry, exit, size;
   - costs and fill delay;
   - its scorer script and the script's sha256;
   - its ADR-012 rule file and that file's sha256.
3. **Costs, unless the freeze states higher:**
   - a curve trade pays its platform's fee a side, as each `TradeEvent`
     carries it (1.0%, 2.0% or 2.5% by platform);
   - a graduate's CPMM trade pays its pool's trade and creator fees, as each
     `SwapEvent` carries them;
   - plus 10,000 lamports of network fees a side, at 0.02 SOL a position.
4. **Fill delay:** 1.5 s, the same as the pump lanes. If FEAT-175's probes
   have measured a delay before the freeze, the freeze uses the measured
   median instead and says so.
5. **Verdict:** `trading-core-audit verdict` with each rule's ADR-012 file,
   on the test half only, giving GO, EXTEND or NO-GO.
   - With fewer than 150 test trades, a rule is reported as underpowered,
     not NO-GO; a fresh capture (`float-2`) may carry it.
   - With several rules, each is judged against its own file, and the
     read-out names how many were frozen.

**What GO leads to:** a Stage 1 paper lane on Float. That needs a LaunchLab
and CPMM paper executor, which is not built. Nothing trades live from this
run.

**Checks while it runs (none of them is a verdict):**
- **Daily:**
  - the capture's newest row is recent;
  - the `Float` status row shows the feed connected;
  - trader rows keep up with trade rows;
  - no keyed URL appears in the run's files.
- **The first graduation:** checked by hand against `getTransaction` (the
  curve, the CPMM pool, the holders, the 2 s readings). It is the one path
  not yet seen live.
- **Gaps:** any gap in the capture longer than 10 minutes is named in the
  read-out.

**Stop rule:** none on results, as the run is record-only. It is stopped
early only for a broken capture, which the read-out names.

## Read-out (added at the end)

Not yet.
