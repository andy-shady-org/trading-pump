# Run damm-1

**Record-only, no verdict.** Graduation tracking and both PumpSwap lanes
off; the run records every new Meteora DAMM v2 pool paired with SOL
(FEAT-107, `damm_pools`) from its activation, so that a later read-out can
say whether a lane on these pools beats their costs. Nothing is bought, so
there is nothing to pre-register and no stage to climb.

## Set-up (written 2026-11-03, before the start)

- **Question for the read-out:** on 1–2 s data and each pool's real fee,
  does scout-1's lead hold (trading-scout `docs/dev/runs/scout-1.md`: the
  FEAT-76 rule on DAMM v2 pools, +23% a trade at the median on 30 s
  snapshots)? Read out with: pools followed per hour, the fee by minute
  since activation (the anti-sniper schedule), the paths from activation,
  liquidity at entry, and scout-1's rule replayed with each pool's own fee.
  A lane is proposed only if it shows an edge after costs, and it is built
  in trading-meteora (FEAT-113, ADR-011), which reads this capture as
  written.
- **Code:** trading-pump `v0.4.0` (`c369f09`, the merge commit on `main`) on
  trading-core `v0.4.0` (`cfff635`), installed in `runtimes/pump` with
  `bin/install-release.sh v0.4.0 v0.4.0`.
- **Config:** `runtimes/pump/configs/damm-1.json`: `graduation.enabled`
  false, lanes off, `damm_pools.enabled` true (stream on the public RPC,
  about 6 GB a day; heartbeat reads every 30 s over `PUMPFUN_RPC_URL`),
  capture in `data/damm-1/` with up to 200 parts of 50 MB; sha256
  `2403a4f0ca1c260d3b855e3fdb0f42dea0658cde182feb5fc1d5db073a81dd36`.
- **Smoke run first:** `configs/smoke-damm.json` (the same, in
  `data/smoke-damm/`; sha256
  `002d0885294a1902cc0cc241b5770760b3182521c7a20ed54e2dc653eb17bd73`),
  30 minutes: pools found, `damm_state` rows written, the `DAMM v2` status
  row live, no `damm v2 feed` degraded condition.
- **Length:** 72 h, given to the engine with `--run-for 72h` (trading-core
  TC-11); the planned end is in the `run_started` record (`planned_end`).
- **Started:** to be filled from `data/damm-1/RUN.txt` when it starts.
- **Verdict:** none (record-only).

## Read-out (added at the end)

To be added when the run ends, in trading-meteora if it exists by then
(the capture's rows are FEAT-107's, as trading-pump `v0.4.0` writes them).
