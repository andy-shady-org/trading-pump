# Run ee-1-tiered (arms 3, 4 and 5 of ee-1)

**Two pre-registered replays on ee-1's capture (FEAT-162).**
- No run of its own: they read `data/ee-1/` (see [`ee-1.md`](ee-1.md)).
- Nothing is bought.

## Pre-registration (written 2026-11-06 07:40 UTC, before ee-1 starts)

**Question:**
- **Arm 3:** does a tiered exit on the momentum lane's entries clear its costs on fresh graduates? It takes part of the costs early and lets the rest run for 2 minutes.
- **Arm 4:** does the same exit, kept only for coins whose first minute after migration was strong, do better?

**Where they came from (in-sample, 2026-11-06, project note `claude/early-exit-2026-11-05.md`):**
- **The exit grid.** 420 tiered exits on rc.8, rc.9 and rc.11; 32 positive on all three.
  - Choosing on two captures and judging on the third gave +0.8%, +2.5% and +0.6% on the held-out capture.
  - The best neighbourhood was: sell part at +8%, the rest at +15–20%, out by 2 minutes. The share sold first hardly matters.
- **The first-sale level is a sharp peak.** At +7% or +9% the worst capture drops to about 0%.
- **The remainder's stop.** Raising it from the entry price to +3% after the first sale gave +1.9% / +3.5% / +1.1% a trade.
- **The losses.** Coins that never reach +8% (20% of entries) lose about 30% each.
- **The rug matrix: 13 features**, crash rates on 2,086 graduates and momentum trades on three captures.
  - Social links, Twitter, description length, the creator's launches and transactions in the prior 24 h, hour of day and graduations in the prior hour did not separate trades consistently.
  - A name or symbol reused in the prior 24 h, and a seen operator, pointed the right way on two captures with small samples.
  - **The highest reading in the first 60 s against the first reading** separated trades on all three captures and on a plateau of thresholds:
    - kept at 1.25–1.6×, both exits are positive on every capture;
    - at 1.30× the tiered exit makes +3.6% / +3.6% / +3.4% a trade (26, 44, 80);
    - the removed coins make −4.5% / +3.2% / −11.2%.
- **Speed.** With a 3 s fill instead of 1.5 s, both arms lose on most captures (arm 4: −1.9% / −2.5% / +0.2%).

**The rules:**
- **Entries:** the momentum lane's, as in [`ee-1.md`](ee-1.md).
- **Arm 3 exit:**
  - sell half at the first reading at or above +8% of the entry price;
  - sell the rest at the first reading at or above +20%;
  - once the first half is sold, sell the rest at the first reading at or below +3%;
  - otherwise sell everything left at the first reading 120 s or more after entry;
  - no stop before the first sale.
  - Each sale pays its own network and tip floor.
- **Arm 4:** arm 3's trades, kept only when the highest reading in the first 60 s after the migration is at least 1.30× the first reading. Those readings come before the signal.
- **Costs:** as ee-1's.

**Files:**

| File | sha256 |
|---|---|
| `runtimes/pump/analysis-pump12/ee1_arms.py` | `21e4a795505d9bdbf29cf3a48041042b61cf105648e3e3927f4fd079107a364b` |
| `sim.py`, `load.py` | as in `ee-1.md` |

On the design captures the scorer reproduces the numbers above.

**Window:** ee-1's.

**Verdict per arm (`ee1_arms.py`; ADR-012 words):**
- **GO** when all of these hold:
  - 150 or more trades;
  - mean net per trade above 0;
  - above 0 in both halves of the trades in time;
  - the one-sided 90% bootstrap lower bound above 0 (seed 20261106, 10,000 draws);
  - mean at 1.5% a side at or above 0;
  - for arm 4, the kept mean above the removed coins' mean.
- **NO-GO:** 150 or more trades and a mean of 0 or less.
- **EXTEND:** anything else. It follows ee-1's extension: pooled once, then NO-GO if still not GO.
- **Expected:** arm 3 about 230 trades, arm 4 about 190.

**Reported, not judged:** the result with the entry filled 3 s after the signal.
- The design data say both arms depend on filling within about 1.5 s.
- So a GO here leads to a paper lane whose first job is to measure our real fill delay. It still comes before anything live.

**Command at the end** (after ee-1's `load.py`):

```sh
python3 -I ee1_arms.py ee1.pkl <start epoch> <end epoch - 14400>
```

## Arm 5 (pre-registered 2026-11-06 07:50 UTC, before ee-1 starts; FEAT-163)

**Question:** does arm 4 do better without coins whose bonding curve was created and sold out in the same moment?
- These are the "instant curve" graduates another trader described: bought whole in the creation transaction, then distributed and dumped.
- Some of them reach the momentum band.

**Where it came from (in-sample, 2026-11-06):**
- A coin's creation time is the block time of its mint's oldest transaction.
- The gap from creation to the capture's recorded migration bunches between 0.37 and 1.60 s, then jumps to 2.10 s. So the cut is set at that gap, **2.0 s**, not at the best result.
- With the tiered exit, the same-second coins made:

  | Capture | Same-second coins |
  |---|---|
  | rc.8 | +13.2% a trade (1 coin) |
  | rc.9 | −1.3% (9) |
  | rc.11 | −11.8% (17) |

- Arm 4 without curves under 2.0 s makes +2.8% / +4.1% / +4.1% a trade (24, 25, 62). The removed coins make −0.7% / +3.1% / −4.7%.
- With a 3 s fill it makes −3.2% / −1.4% / +0.5%.
- rc.8 holds only 2 such entries, so the evidence is mainly two captures.

**The rule:**
- Arm 4's trades;
- dropping a coin whose capture-recorded migration time is less than 2.0 s after its creation time;
- creation time looked up through Helius at the read-out, cached; the key from a file, never printed.

**Files:**

| File | sha256 |
|---|---|
| `runtimes/pump/analysis-pump12/ee1_arm5.py` | `bf25a856a6761758a26b9a140e664776f02a9378c34b24b119214c87386a18d9` |

It imports `ee1_arms.py` (hash above) and `sim.py`.

**Verdict:** as arms 3 and 4, with the removed coins as the comparison.
- **Expected:** about 140 trades in 7 days, so probably EXTEND to the pooled 14 days.

**Multiple arms:** ee-1 now has five pre-registered arms. A GO on any one of them could be luck, so a GO leads only to a paper lane (fill delay first), never to live money directly.

```sh
python3 -I ee1_arm5.py ee1.pkl <start epoch> <end epoch - 14400> ee1-arm5-cache.json <key file>
```

## Read-out (added at the end)

To be added when ee-1 ends.
