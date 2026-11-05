# Run ee-1-linked (second arm of ee-1)

**A pre-registered replay on ee-1's capture (FEAT-161).**
- It takes the momentum lane's entries only on coins whose operator has already been seen rugging, and skips first-time operators.
- No run of its own: it reads `data/ee-1/` (see [`ee-1.md`](ee-1.md)).
- Nothing is bought.

## Pre-registration (written 2026-11-05 19:56 UTC, before ee-1 starts)

**Question:** do momentum entries on coins linked to an earlier rug clear their costs? And do they do better than entries on coins with no such link?

**Where it came from (in-sample, 2026-11-05):**
- **The finding.** Coins tied to a network that had rugged before crashed less often (about 60% against 80%). On the momentum lane they traded better.
- **Results with exactly this definition** (TP +20%, SL −15%, 30 min):

  | Capture | Linked | Not linked |
  |---|---|---|
  | rc.9 | +6.5% a trade (24) | −0.3% (30) |
  | rc.11 | +3.0% (41) | −5.4% (54) |

- **ee-1's exit on the same coins** gave +2.4% / −0.1%: no help.
- **The threshold was chosen after a broader version failed.** A shared launch wallet joined almost every instant coin into one network. So this is a lead, not a result.
- Project note: `claude/funder-study-2026-11-05.md`.

**The flag (`linked.py`), forward in time:**
- **A coin's entry links:** its creator, read from its bonding-curve account, and the creator's funding chain to hop 4.
  - A wallet's funder is the account that lost the most SOL in the first successful transaction, among its 50 oldest, where the wallet gained at least 0.005 SOL.
- **A coin's cash-out links:** up to 3 destinations of its creator's system transfers of 0.05 SOL or more after the migration, each with its time.
- **Crash:** the coin fell below half its 60–90 s reading within 30 minutes. It counts from the reading where it happened.
- **Shared infrastructure:** a wallet is ignored once 30 or more earlier coins carry it as a link.
- **A coin is LINKED** when one of its entry links, not infrastructure, was already one of these by the coin's migration:
  - an entry link of an earlier crashed coin, or
  - that crashed coin's cash-out destination.
- **The history is every coin.** That includes the coins skipped, the seed, and the ee-1 window as it goes.
  - An operator skipped on a first launch is on the list once that coin has crashed. Their later launches are traded.
  - "Seen on any earlier coin, crash or not" was checked too. It marks almost every coin as linked, so it filters nothing.

**The trade:**
- Entries are the momentum lane's, as in [`ee-1.md`](ee-1.md), kept only when the coin is LINKED.
- Exit: take +20%, stop −15%, or 30 minutes, as in rc.11-tp20's momentum lane.
- Costs as in ee-1.

**Files** (all in `runtimes/pump/analysis-pump12/`):

| File | sha256 | Role |
|---|---|---|
| `ee1_linked.py` | `c8881f796405163b08a15c94523801fb992bd34056d5cedb6a66322ad5562304` | Scorer |
| `linked.py` | `4373e5623784205d6f069306c3c19a5a083982ece442d3d8effa82d2281e0d91` | The flag |
| `pda.py` | `05e1df751d3c40df19b69ca6d066e3b738cdf2f7996f710610a1d209b4c3c8c7` | Curve addresses |
| `ee1-linked-seed.json` | `960109db331a6bd96166b1159bd64f894e2a526116a8fc994b7f0a6208205711` | The history before ee-1 |
| `sim.py`, `load.py` | as in `ee-1.md` | Simulator, compaction |

- **The seed** holds the 2,082 rc.9, rc.11 and rc.11-tp20 graduates with known creators, their crash outcomes, their creators' cash-outs, and the first funders of 5,324 wallets.
- **The scorer:**
  - fetches the window's creators, funders and cash-outs through Helius at the read-out, cached;
  - reads the key from a file given on the command line, never printed or committed;
  - was run end to end on rc.11's last 12 hours as a check (455 graduates, about 6 minutes).

**Window:** ee-1's.

**Verdict (`ee1_linked.py`; ADR-012 words):**
- **GO** when all of these hold:
  - 60 or more linked trades;
  - mean net per trade above 0;
  - above 0 in both halves in time;
  - the one-sided 90% bootstrap lower bound above 0 (seed 20261106, 10,000 draws);
  - mean at 1.5% a side at or above 0;
  - linked mean above the not-linked mean.
- **NO-GO:** 60 or more linked trades and a mean net of 0 or less.
- **EXTEND:** anything else. It follows ee-1's extension: pooled once, then NO-GO if still not GO.
- **Expected:** about 40% of about 230 momentum entries, so about 90 trades.

**Reported, not judged:**
- not-linked trades;
- ee-1's exit on linked and not-linked coins;
- the share of crashes among linked and not-linked graduates.

**A GO leads to:** a Stage 1 paper momentum lane with this filter. That needs the flag live: Helius lookups at the migration, within the 60 s before the signal.

**Command at the end** (after ee-1's `load.py`):

```sh
python3 -I ee1_linked.py ee1.pkl <start epoch> <end epoch - 14400> ee1-linked-seed.json ee1-linked-cache.json <key file>
```

## Read-out (added at the end)

To be added when ee-1 ends.
