# Run ee-1-grid (arms 6 and 7 of ee-1, and the combination grid)

**Pre-registered replays on ee-1's capture, plus an exploratory grid.**
- No run of its own: they read `data/ee-1/` (see [`ee-1.md`](ee-1.md)).
- Nothing is bought.

## Pre-registration (written 2026-11-08 15:10 UTC, while ee-1 runs and before any of its data is read)

**Why (operator, 2026-11-08):**
- Fewer trades are fine if they earn: ten good trades a week beat none.
- Every combination of filters, tiered exits and entry times is to be tested against ee-1.

**Where it comes from (in-sample, RESULTS §6.23 and its 2026-11-08 addendum):**
- The launch-and-dump features, and the entry and exit variants below, were scored on rc.8, rc.9 and rc.11 with the same scripts.
- No filter improved the momentum lane's trades on all three captures under both of ee-1's exits.
- Removing coins with 30% or more of the supply bought in the creation slot came closest. On the tiered exit it gave +10.3% / +3.0% / +3.8% a trade, on 10 / 14 / 45 trades, against +1.9% / +3.5% / +1.1% for all trades.
- On the full grid, the real features did **no better than shuffled ones**:
  - 32,880 filtered cells were positive on all three captures, against a median of 43,180 with the features shuffled among trades (p = 0.965);
  - the best filtered cell scored +5.86%, against a shuffled median of +4.91% (p = 0.249).
- So the in-sample evidence says these filters are noise. They are tested here because a test on fresh data costs nothing, and the design data are small.

### Arms 6a and 6b: the 30% creation-slot filter

**The rules:**
- **Entries:** the momentum lane's, as in [`ee-1.md`](ee-1.md).
- **Filter:** drop a coin when 30% or more of its supply was bought in its bonding curve's creation slot. The share is read from Helius at the read-out (`grid_features.py`).
- **Arm 6a exit:** ee-1's (+4% gross or out at 60 s).
- **Arm 6b exit:** arm 3's tiered exit (half at +8%, the rest at +20% or at +3% once the first half is sold, out at 120 s).
- **Costs:** as ee-1's.

**Verdict per arm** (`arms67.py`, which uses `ee1_arms.judge`): the same GO checks as arms 3 and 4, with the removed trades of the same entry and exit as the comparison.

**Expected:** about 45% of entries are kept, so about 100 trades in 7 days. The verdict therefore needs the pooled 14 days.

### Arm 7: the design pick

This is the single top cell of the grid below on the design captures, chosen before ee-1 is read. Its score is the worst capture's mean less one standard error, with at least 10 kept trades on each capture. Output: `design.txt`.

**The rules:**
- **Entry:** the signal is the first reading 90–120 s after the migration at 1.5× or more the first reading. Entry is 1.5 s later, refused above 5% slippage. The market-cap band is the momentum lane's.
- **Exit:**
  - half at +10%;
  - the rest at +30%, or at a stop raised to +3% once the first half is sold;
  - out at 180 s;
  - no stop before the first sale.
- **Filters:**
  - keep only coins whose highest reading, up to 60 s after the migration and not after the signal, is 1.40× or more the first reading;
  - drop coins whose curve was created 2 s or less before the migration.
- **Design captures:** +8.3% / +16.1% / +10.4% a trade on 14 / 11 / 24 trades.
- **Expected:** about 55 trades a week.

**Verdict:** as arms 6a and 6b.

### Arms with fewer than 150 trades

This applies to arms 6a, 6b and 7, following the operator's point that fewer trades are acceptable:
- after ee-1's pooled 14 days, an arm with fewer than 150 trades that passes every other GO check is not closed;
- it is carried to the next capture or paper lane as a pre-registered rule, unchanged;
- an arm that fails any other check is NO-GO.

`arms67.py` prints which case applies.

### The combination grid (exploratory)

**Cells:** 3,052,220, every combination of the following.

- **20 entry variants:**
  - the signal window starts 30, 45, 60, 90 or 120 s after the migration and lasts 30 s;
  - the signal ratio is 1.1, 1.2, 1.3 or 1.5×;
  - entry is 1.5 s after the signal;
  - every cell is also reported with a 3 s fill.
- **101 exits:**
  - 20 flat exits: take profit at +3, +4, +6, +8 or +10%, or out at 30, 60, 90 or 120 s;
  - 81 tiered exits: half at +6, +8 or +10%; the rest at +15, +20 or +30%; after the first sale, no stop or a stop at 0% or +3%; out at 60, 120 or 180 s.
- **1,511 filters:**
  - no filter;
  - each of 29 conditions as "remove if" or "keep only if";
  - every pair of conditions from different families, in all four direction pairs.
- **The 29 conditions, in eight families:**
  - metadata host: not IPFS; j7tracker;
  - creator sold: before the migration; through a router; within 30 s;
  - creation-slot share: 20%, 30%, 40%, 50%, 60% or 70% or more;
  - first-5 s share: 40%, 50%, 60% or 70% or more;
  - creation-slot buyers: 3, 5 or 7 or more;
  - curve time: 2, 5, 30 or 120 s or less;
  - the creator's launch buy: 5%, 10% or 20% or more;
  - early peak before the signal: 1.25, 1.30, 1.40 or 1.60× or more.
- **Unknown creator features** (history not reached) count as false for "remove if", so the coin is kept. They count as not true for "keep only if", so the coin is dropped.

**A cell is a lead when all of these hold:**
1. at least 10 kept trades on each design capture and 30 on ee-1, and at least 10 a week on each;
2. the mean per trade is above 0 on each design capture and in both halves of ee-1's kept trades in time;
3. ee-1's mean at a 1.5% pool fee is 0 or more;
4. for a filtered cell, ee-1's mean is above the same entry and exit with no filter.

**Multiple tests:**
- For filtered cells, the number of leads is compared with a permutation null (200 draws, seed 20261108). In each draw, the filter results are shuffled among the trades of each capture and entry variant. Returns and trade times are untouched.
- Filtered leads count as more than chance only if their number is above the null's 95th percentile. Otherwise they are reported as consistent with chance.
- Unfiltered cells (2,020 entry and exit pairs) have no null. They are reported with the number tried.

**What a lead leads to:**
- A lead is never a GO.
- At most the best few leads are pre-registered on a fresh capture or paper lane, before that data is read.
- A lead that depends on Helius features also needs a check that the features (about 48 lookups a coin) can be read before a 30–120 s entry.

**Reported:**
- the counts and the null;
- the 50 leads with the best worse half, with their design and 3 s fill results;
- the design pick's numbers (judged by `arms67.py`).

**Not changed:** arms 1 to 5 and their verdicts. With arms 6a, 6b and 7, ee-1 has eight judged arms, so as before a GO leads only to a paper lane, with the fill delay measured first.

## Files

Kept in `runtimes/pump/analysis-pump12/`, beside `sim.py`, `ee1_arms.py` and `pda.py` (unchanged; hashes in [`ee-1.md`](ee-1.md) and [`ee-1-tiered.md`](ee-1-tiered.md)). The design outputs are in `ee1-grid/`.

| File | sha256 | Role |
|---|---|---|
| `grid.py` | `78514cb5ab145e7a8b1f29e7474a60e5db3593a9d9140467849efc48eec26477` | The grid, the leads and the null |
| `grid_entries.py` | `4e8e452a63f80f5a8f2bd393c5e3d36f45e759cf2cbd0e1bd3dfe4cdfb02d460` | Entry variants. Its base variant reproduces `sim.signals` on all three design captures |
| `grid_coins.py` | `a7d2b709f2951e28ebefc0ad24b934cf3b3de7baeb07e70d259c215a263de9dd` | Every coin any variant enters |
| `grid_features.py` | `efe967bb5a035edef7f4bfb56929569a065c0a061bada00fbb7160ad0895b4d4` | Helius features: the lookups of `launch-dump-2026-11-08/fetch.py`, with files as arguments. The key is read from a file and never printed |
| `arms67.py` | `97528dba3d9cd8667375b209681e08916989c9d2c44eb58246f4ef6bc9e1b890` | Arms 6a, 6b and 7. It reproduces the design numbers above |
| `ee1-grid/design.txt` | `10d5476e9e29bebd9b4c22d2b49f1fe650f3bebe866786508885636283d8f9bb` | The design run and arm 7's choice |
| `ee1-grid/features-design.json` | `49bd5ff5c0f81d4191bf615f0e731975459540230ba2b11b14666bda02b4f55d` | Features of the 629 design coins (21,067 calls, none failed) |

Checked on the Mac's Python 3.10: the five scripts compile, `arms67.py` reproduces the design numbers, and `grid.py design` writes a `design.txt` identical to the one above.

## Commands at the end

Run after ee-1's `load.py`. FROM and TO are ee-1's scored window. The feature lookups take about 1.5 h for about 850 coins.

```sh
cd ~/projects/git/trading/runtimes/pump/analysis-pump12
python3 -I grid_coins.py ee1.pkl ee1 <start epoch> <end epoch - 14400> ee1-grid/coins-ee1.json
python3 -I grid_features.py ee1-grid/coins-ee1.json ee1-grid/features-ee1.json <key file>
python3 -I arms67.py ee1.pkl <start epoch> <end epoch - 14400> ee1-grid/features-ee1.json
python3 -I grid.py ee1 ee1-grid/features-design.json,ee1-grid/features-ee1.json \
    launch-dump-2026-11-08/rc8.pkl launch-dump-2026-11-08/rc9.pkl launch-dump-2026-11-08/rc11.pkl \
    ee1.pkl <start epoch> <end epoch - 14400> ee1-grid/ee1-grid
```

## Read-out (added at the end)

To be added when ee-1 ends.
