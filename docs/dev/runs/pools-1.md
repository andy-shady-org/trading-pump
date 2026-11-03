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
  `new_pools.enabled` on, every file in its own `data/pools-1/`; sha256
  `fda8b3650bf5f3c8a83dd625922ce8e42c183f170559c9da020d6e87ae7c0a04` (the
  run's `RUN.txt`).
- **Feed:** `programSubscribe` on PumpSwap's pool accounts over the RPC
  WebSocket (`PUMPFUN_RPC_WS_URL`), about 36 kB a second, about 3 GB a day
  ([`COSTS.md` §3.3](../COSTS.md#33-on-the-new-stack-trading-pump-040-from-2026-10-28)).
  A pool seen for the first time after the 30-minute warm-up is dated by its
  signatures; a SOL pair created in the last 10 minutes is followed like a
  graduate, with `source: "new_pool"` on its capture rows.
- **Started:** 2026-10-31 07:29:11 UTC. Length: 24–72 h
  ([`TODO.md`](../TODO.md#new-pumpswap-pools-that-are-not-graduations-feat-80)).
- **Verdict:** none (record-only).

## Read-out (added 2026-11-03)

Read from the capture up to 2026-11-03 07:17 UTC, 71.7 hours after the
first observation (07:38 UTC on 31 Oct), while the engine was finishing its
last cycles (`--max-cycles 259200`, which overruns as on rc.11). The last
minutes change none of the numbers below.

- **Recording.** No gap longer than 2 minutes between pool readings in the
  whole capture (33 files, 531 MB). The pool WebSocket connected 18 times
  in all and PumpPortal's feed 23 times (its failures were 502 responses
  and two missed pongs, each retried within seconds). The engine reported
  no pipeline errors, stale data or failures.
- **Followed:** 3,122 new pools (43.5 an hour) and 2,756 graduates (38.4 an
  hour).
- **What the new pools are.** All 3,122 were found by their creation
  transaction and dated exactly. All are SOL pairs, and 3,095 of them put
  SOL on the pool's base side, the reverse of a graduate's pool. None has a
  coin creator (`coin_creator` is the system address), and only 217 are
  Pump.fun mints. 3,086 start with 50 SOL or more in the pool.
- **What happens to them.** 92% have less than a fifth of their starting SOL
  left in the pool within an hour: the liquidity is withdrawn, the price
  path after that is meaningless, and a holder cannot sell. Before that, 79%
  rise 1.2× within 15 minutes.
- **A trade on them** (the offline rule of §6.20: entry at the first reading
  1.5 s later, TP +20% / SL −15% / 30 minutes, a holding that meets a pool
  under a fifth of its entry SOL is a total loss):

  | Group | Pools | Entry | Mean per trade, gains capped at +100% (fee 125 / 30 bps a side) | Median | Total losses |
  |---|---|---|---|---|---|
  | new pools, ≥ 50 SOL | 3,085 | first reading | −12.5% / −10.9% | +16% | 775 |
  | new pools, ≥ 50 SOL | 557 | ≥ 1.2× at 60–90 s | −2.3% / −0.4% | +17% | 74 |
  | graduates, standard band | 672 | first reading | −2.7% / −0.8% | −18% | 1 |
  | graduates, instant band | 751 | first reading | −0.6% / +1.3% | +16% | 8 |

  The pool's own fee was not recorded; 30 bps a side stands for a low fee
  (these pools have no coin creator, so no creator fee).
- **Reading.** The new non-graduate pools are a stream of liquidity pulls:
  three trades in four win a little and one in four loses everything. No
  rule tried is positive at either fee. **No third lane (E3)**; pump-12 does
  not record new pools.
- **RPC credits and WebSocket data:** not measured from the run's files;
  the provider's dashboard has them.
