# Run ee-1

**Record-only capture, judged offline by a pre-registered replay (FEAT-160).**

- Graduation tracking is on and both PumpSwap lanes are off.
- The run records every graduate's readings as rc.11 did (2 s for the first 300 s, then 10 s, for 4 h).
- When it ends, one fixed rule is replayed on that capture and judged.
- Nothing is bought.

## Pre-registration (written 2026-11-05 19:43 UTC, before the start)

**Question:** do the momentum lane's entries, sold at the first of +4% gross (about +1% after costs) or 60 seconds, clear their costs on graduates none of the design data came from?

**Where the rule came from (in-sample, 2026-11-05):**
- 25 early-exit rules on the momentum lane were tried on the rc.8, rc.9 and rc.11 captures with the pump-12 simulator. This was the only one positive on all three:

  | Capture | Mean per trade | Trades | Won |
  |---|---|---|---|
  | rc.8 | +0.96% | 33 | 82% |
  | rc.9 | +1.90% | 54 | 83% |
  | rc.11 | +0.70% | 95 | 85% |

- Pooled: +1.10% a trade, standard deviation 12.4%.
- Its neighbours are mixed (rc.11 is negative at 30 s and at 120 s).
- An earlier grid of 90 rules (TP +3 to +15%, holds of 10–90 s) found nothing positive on all three.
- The same rule on the instant lane is negative on every capture.
- Project note: `claude/early-exit-2026-11-05.md`.

**The rule (FEAT-160):**
- **Entry:** the momentum lane's, as in rc.11 and the simulator's `LANES["momentum"]`.
  - The first reading's market cap is 205.44–821.76 SOL.
  - The signal is the first reading 60–90 s after the migration, at 1.2× or more the first reading.
  - Entry is at the first reading at least 1.5 s after the signal, refused if it is more than 5% above the signal price.
- **Exit:**
  - sold at the first reading at or above +4% of the entry price;
  - otherwise at the first reading 60 s or more after entry;
  - no stop loss;
  - a coin that stops reporting is sold at its last reading.
- **Costs per position (0.02 SOL):**
  - the pool fee of 1.25% a side;
  - a 50 bps haircut on proceeds;
  - 3.5e-5 SOL per leg for network, priority and the verdict's tip floor.

**Code and files:**
- **Capture:** trading-pump `v0.4.0` (`c369f09`) on trading-core `v0.4.0` (`cfff635`), the release damm-1 runs, installed in `runtimes/pump`. No install change is needed.
- **Config:** `runtimes/pump/configs/ee-1.json`, sha256 `06bb53280c4d0c1330525e3fff967c67cb0c30a0c2c5efdf73a51be6a7876a27`.
  - It is rc.11's `rc11-paper.json` with `lane.enabled` and `instant.enabled` false.
  - The capture is in `data/ee-1/`, up to 200 parts.
  - `strategy_name` is `graduation_capture`.
- **Smoke run first:** `configs/smoke-ee-1.json` (the same, in `data/smoke-ee-1/`), sha256 `931636c1fc5d029a49b0edbdd60617e2f47e7119030957b06f385c8490d370fb`, 30 minutes.
  - It passes when `curve_poll` rows with `"graduation"` are written for migrated mints, at 2 s intervals in their first 300 s.
  - If `strategy_name` or any key is refused, the smallest fix is made in both files, and the new hashes are added as a dated line below before the start.
- **Scorer:** the files in `runtimes/pump/analysis-pump12/`:

  | File | sha256 | Role |
  |---|---|---|
  | `ee1.py` | `849f7b089908a91c3724d873ffc6e0f380aa4e1ebdd283360dbf5004d43fc9da` | The rule, the halves, the bootstrap and the verdict |
  | `sim.py` | `62491ac2992a215eb7047070d3c678d26b2dc695098c6d62e9b8c78daaa25463` | The simulator |
  | `load.py` | `25f3da265e45d44c4b8e09ead4e9ac4ae58b9e998df33a0aad3753745b5f9724` | Compacts the capture |

  On the design captures it reproduces the table above.

**Length and window:**
- **Start:** after damm-1 ends (planned end 2026-11-06 11:20 UTC) and the smoke run passes.
- **Length:** 168 h (`--run-for 168h`).
- **Window:** graduates that migrated from the run's start (from `data/ee-1/RUN.txt`) to 4 h before its end, so every scored coin has its full first 4 hours.
- **Expected:** about 1.4 entries an hour, so about 230 trades.

**Verdict (`ee1.py`; ADR-012 words):**
- **GO** when all of these hold:
  - 150 or more trades;
  - mean net per trade above 0;
  - above 0 in both halves of the trades in time;
  - the one-sided 90% bootstrap lower bound above 0 (seed 20261106, 10,000 draws over trades);
  - mean at a 1.5% pool fee a side at or above 0.
- **NO-GO:** 150 or more trades and a mean net of 0 or less.
- **EXTEND:** anything else (fewer than 150 trades, or a positive mean that misses a check). The run is extended once by 7 days and the two windows are pooled. If it is still not GO, the result is NO-GO.

**Reported, not judged:**
- the result with every entry 2.1% worse, the median live entry error of BUG-164;
- the instant lane under the same exit;
- results by day.

**What a GO leads to:**
- A Stage 1 paper momentum lane with this exit, on its own record (`take_profit_pct` 0.04, `max_hold_seconds` 60, `stop_loss_pct` 0.99).
- It measures real fills against the capture (BUG-164) before anything live.
- A NO-GO closes early exits on PumpSwap graduates (STRATEGY-LEDGER).

**Commands at the end:**

```sh
cd ~/projects/git/trading/runtimes/pump/analysis-pump12
python3 -I load.py ee1.pkl ../data/ee-1/capture.jsonl*
python3 -I ee1.py ee1.pkl <start epoch> <end epoch - 14400>
```

## Read-out (added at the end)

To be added when the run ends.
