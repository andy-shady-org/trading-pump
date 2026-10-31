# Run pools-1

**Record-only, no verdict.** Both lanes off; the run records the new
PumpSwap pools that are not Pump.fun graduations (FEAT-80, `new_pools`),
next to the graduates, so that a later read-out can say whether a lane on
them could beat their costs. Nothing is bought, so there is nothing to
pre-register and no stage to climb.

## Set-up (from the 0.4.0-rc.5 release record)

- **Question for the read-out:** how many new non-graduate pools appear an
  hour, how many are SOL pairs dated exactly, and how their prices move from
  the first reading (1.2× in 15 minutes, 2× in an hour, dead by an hour),
  against the graduates of the same hours.
- **Code:** trading-pump `v0.4.0rc5` (`a16a3a3`, the merge commit on `main`)
  on trading-core `v0.2.2` (`e64526b`).
- **Config:** `runtime-pump/configs/pools-1.json`: both lanes off,
  `new_pools.enabled` on, every file in its own `data/pools-1/`. Its sha256
  is not recorded in this repository.
- **Feed:** `programSubscribe` on PumpSwap's pool accounts over the RPC
  WebSocket (`PUMPFUN_RPC_WS_URL`), about 36 kB a second, about 3 GB a day
  ([`COSTS.md` §3.3](../COSTS.md#33-on-the-new-stack-trading-pump-040-from-2026-10-28)).
  A pool seen for the first time after the 30-minute warm-up is dated by its
  signatures; a SOL pair created in the last 10 minutes is followed like a
  graduate, with `source: "new_pool"` on its capture rows.
- **Started:** 2026-10-31 07:29:11 UTC. Length: 24–72 h
  ([`TODO.md`](../TODO.md#new-pumpswap-pools-that-are-not-graduations-feat-80)).
- **Verdict:** none (record-only).

## Read-out (added at the end)

To be added when the run ends: hours recorded and gaps, pools followed per
hour, the share of SOL pairs and of exact dates, lookup errors, RPC credits
and WebSocket data used. The read-out of the price paths goes to
[`RESULTS.md`](../RESULTS.md) as a new section, and a lane on these pools is
proposed only if it shows an edge after costs.
