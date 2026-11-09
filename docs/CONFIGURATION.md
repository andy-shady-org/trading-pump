# Configuration

A run is one trading-core settings file with `"module": "pumpfun"`. The
engine's keys (`order_size`, `risk`, `breaker`, `exits`, paths, ...) are
documented in trading-core's `docs/CONFIGURATION.md`; amounts there are in
the module's quote currency, **SOL**. This page documents `module_settings`,
the object the engine passes to the module.

Rules (the same as the engine's):

* Keys starting with `_` are comments, at every level.
* **Unknown keys are errors** at every level (pumpfun BUG-125: a config
  resolver once dropped new fields without a word). `trading-core check
  --config FILE` builds the module, so a typo fails there, not after a day.
* Amounts are SOL, times are seconds, fees and slippage are basis points
  (`100` = 1%), ratios are fractions or multiples as named.
* No credentials: the file is hashed into the run provenance
  ([ENVIRONMENT.md](ENVIRONMENT.md)).

Examples: [`configs/paper.example.json`](../configs/paper.example.json) (the
FEAT-76 paper run) and [`configs/capture.example.json`](../configs/capture.example.json)
(record-only capture, lane off). Copy one, edit it, check it:

```bash
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
```

```json
"module_settings": {
  "graduation": {"observation_seconds": 14400, "fast_seconds": 300},
  "lane": {"signal_after_seconds": 60, "min_ratio": 1.2},
  "execution": {"slippage_bps": 500},
  "capture": {"path": "data/paper/capture.jsonl"}
}
```

Every section may be left out; it then takes the defaults below.

## `graduation`: following graduates (FEAT-73)

Every coin PumpPortal reports as migrated is followed in its canonical
PumpSwap pool, record-only, whether or not the lane trades it.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` follows no graduate and leaves the PumpPortal feed and the pool poller off (every lane and `new_pools` must then be off). It was added for the `damm_pools` capture (FEAT-107), which left in 0.5.0. |
| `observation_seconds` | `14400` | How long each pool is followed after its migration (4 h). |
| `max_mints` | `500` | Pools followed at once. A full list never evicts: a new graduate is skipped (`list_full` in the stats) so every observation runs its course. |
| `fast_seconds` | `300` | The first part of each observation, read faster. |
| `fast_poll_interval_seconds` | `2` | Read interval during `fast_seconds`. |
| `poll_interval_seconds` | `10` | Read interval after that. |
| `pool_missing_grace_seconds` | `60` | A pool the RPC does not have yet is retried this long after the migration before the observation ends (`missing`); a lagging node answers late (BUG-154's lesson). |
| `book_retention_seconds` | `3600` | The market book the module offers trading-core's lanes (`market_book`, [FEATURES §5.1](FEATURES.md#51-the-strategy-librarys-records-trading-core-feat-133-and-feat-117)): a graduate with no listing or reading for this long is dropped from it, unless a position holds it. A followed graduate is read at least every `poll_interval_seconds`, so this drops the graduates whose observation ended; a pool-read outage longer than this drops the graduates being followed too, and they do not come back until a restart. |

## `lane`: the `pumpswap_momentum` lane (FEAT-76)

One decision per graduate, at the first pool reading at least
`signal_after_seconds` after the migration ([STRATEGY.md](STRATEGY.md)).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns the lane off: the module records and never signals. |
| `signal_after_seconds` | `60` | When the decision is made. |
| `signal_window_seconds` | `30` | A reading later than this past the signal time is too late; no decision is made on it. |
| `min_ratio` | `1.2` | Buy when the signal reading's price is at least this multiple of the first reading after the migration. |
| `first_market_cap_min_sol` | `205.44` | The first reading's market cap must be at least this (0.5× of 410.88 SOL, a just-completed curve) ... |
| `first_market_cap_max_sol` | `821.76` | ... and at most this (2×). About 60% of PumpPortal's migration events are empty or unrelated pools. |
| `min_pool_sol` | `0` | Least SOL in the pool at the signal reading (`0` = off). |
| `screen_entries` | `false` | Run the anti-rug screen (`screening`) on each candidate. Off: the rule was pre-registered without it. |
| `max_ratio` | `0` | Buy only below this multiple (`0` = no upper bound). Must be above `min_ratio`. |
| `first_pool_min_sol` | `0` | The first reading's pool must hold at least this much SOL (`0` = off) ... |
| `first_pool_max_sol` | `0` | ... and at most this (`0` = off). |
| `slippage_bps` | (none) | The lane's own limit over the signal price, 0–9999; left out, `execution.slippage_bps` applies. |
| `exits` | `{}` | The lane's own exits (FEAT-79), trading-core's `ExitRules` keys: `stop_loss_pct`, `take_profit_pct`, `take_profit_fraction`, `trailing_activation_pct`, `trailing_drop_pct`, `max_hold_seconds`. Empty: the engine's `exits` apply. |

Without `exits`, the exits are the engine's `exits` (the paper example: take
profit `0.2`, stop loss `0.15`, `max_hold_seconds` `1800`). With them, the
module decides the lane's exits on its own mark and the engine's exits still
run after it, so **set the engine's `exits` to `{}`** in a config that uses
lane exits: an engine take profit at `0.2` would close a position before a
lane's `0.5`. Sizing is the engine's `order_size` and `risk`.

```json
"lane": {
  "min_ratio": 1.2,
  "exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.15, "max_hold_seconds": 1800}
}
```

## `instant`: the `pumpswap_instant` lane (FEAT-78)

The lane for instant graduations (a first reading at 1,000–2,000 SOL market
cap and 130–200 SOL in the pool), holding at 1.00–1.10× a minute later
([STRATEGY.md](STRATEGY.md#6-the-pumpswap_instant-lane-feat-78)). The same
keys as `lane`, with these defaults:

| Key | Default |
|---|---|
| `enabled` | `false` |
| `signal_after_seconds` / `signal_window_seconds` | `60` / `30` (must equal `lane`'s when both are on) |
| `min_ratio` / `max_ratio` | `1.0` / `1.10` |
| `first_market_cap_min_sol` / `first_market_cap_max_sol` | `1000` / `2000` (may not overlap `lane`'s band when both are on) |
| `first_pool_min_sol` / `first_pool_max_sol` | `130` / `200` |
| `min_pool_sol`, `screen_entries`, `slippage_bps` | `0`, `false`, (none) |
| `exits` | `{"take_profit_pct": 0.5, "stop_loss_pct": 0.15, "max_hold_seconds": 1800}` |

`"instant": {"enabled": true}` turns it on with the replayed rule. A graduate
whose first reading is in the instant band goes to this lane; any other goes
to `lane` (when `lane` is on), so each graduate gets one decision.

## `new_pools`: new PumpSwap pools that are not graduations (FEAT-80)

Record-only and off by default ([FEATURES.md §2.1](FEATURES.md#21-new-pumpswap-pools-that-are-not-graduations-feat-80-record-only)).
The pools found are followed on `graduation`'s schedule and share its
`max_mints` list. The RPC WebSocket is `PUMPFUN_RPC_WS_URL`, or the RPC URL
with `wss://` ([ENVIRONMENT.md](ENVIRONMENT.md)).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Subscribe to PumpSwap's pool accounts and follow the new pools that are not graduations. |
| `warmup_seconds` | `1800` | Pools first seen in this long after the first connection are only remembered (the busy existing pools). |
| `max_age_seconds` | `600` | A pool looked up later is followed only if it was created at most this long ago. |
| `signature_limit` | `100` | Signatures read to date a pool (1–1000); a pool with fewer has its exact creation time. |
| `max_lookups` | `4` | Lookups running at once. |
| `idle_timeout_seconds` | `60` | Reconnect when the stream is silent this long (it carries every PumpSwap swap). |

The stream carries about 36 kB a second (about 3 GB a day): check the RPC
provider's WebSocket pricing before a long run. Lookups are about one
`getSignaturesForAddress` and one `getMultipleAccounts` per pool seen for
the first time after the warm-up.

## `push`: a push feed of the followed pools' vaults (FEAT-174)

Record-only and off by default ([FEATURES.md §2.3](FEATURES.md#23-a-push-feed-beside-the-poller-feat-174-record-only)).
One `accountSubscribe` per vault of each followed pool, on the RPC
WebSocket (`PUMPFUN_RPC_WS_URL`, or the RPC URL with `wss://`), from the
pool's first reading until `seconds` after its migration. Needs
`graduation` on.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Subscribe to each followed pool's two vaults and write every push as a `vault_push` row. |
| `seconds` | `300` | How long after a migration its vaults are pushed (the poller's fast window). |
| `commitment` | `"processed"` | `processed`, `confirmed` or `finalized`. |
| `max_vaults` | `200` | Vaults followed at once (two a pool); a pool beyond it is counted, not followed. |
| `flush_interval_seconds` | `0.5` | How often new subscriptions are sent and ended ones closed. |
| `idle_timeout_seconds` | `1800` | Reconnect when nothing arrives this long (quiet between graduations, as the migration feed is). |

Cost: two subscriptions a graduate for five minutes, a few dozen at once.
Measure the provider's credits for the first day before a longer run.

## `float_capture`: Float's launches, trades and graduates (FEAT-179)

Record-only and off by default ([FEATURES.md §2.4](FEATURES.md#24-the-float-capture-feat-179-record-only)).
`logsSubscribe` on the RPC WebSocket (`PUMPFUN_RPC_WS_URL`) mentioning
Float's program and its LaunchLab platform configs, and each followed
graduate's CPMM pool. It does not need `graduation`: a Float-only run sets
`graduation.enabled` and every lane to `false`.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Record Float. |
| `commitment` | `"confirmed"` | `processed`, `confirmed` or `finalized`, for the log subscriptions. |
| `platform_refresh_seconds` | `3600` | How often Float's platform list (its config account) and each platform's fees are read again; a new platform is followed. |
| `cpmm_logs_seconds` | `7200` | How long a graduate's CPMM pool's trades are followed after its migration. |
| `reading_seconds` | `1800` | How long its vaults are read after the migration. |
| `reading_interval_seconds` | `2` | How often they are read (ee-1's cadence). |
| `max_graduates` | `50` | Graduates followed at once; one beyond it is recorded (`followed: false`), not followed. |
| `trader_lookups_per_second` | `4` | `getTransaction` lookups of a trade's signers and block time a second (0: none; the read-out backfills them). |
| `max_queued_lookups` | `20000` | Trades waiting for that lookup; one more is counted and left to the backfill. |
| `max_lookups` | `4` | Launch and migration lookups running at once. |
| `holders` | `20` | Largest token accounts read at a migration (`getTokenLargestAccounts` returns at most 20, pool vaults included). |
| `seen_signatures` | `200000` | Signatures remembered so a transaction seen on two subscriptions is read once. |
| `flush_interval_seconds` | `0.5` | The periodic work's tick: subscriptions, readings, lookups. |
| `idle_timeout_seconds` | `600` | Reconnect when nothing arrives this long. |

Cost, measured in a workspace smoke on 2026-11-09 (see FEATURES §2.4):
about 20 curve trades and 18 fee-cycle transactions a minute, one
`getTransaction` a trade, one `getMultipleAccounts` a launch, a few calls a
migration and one `getMultipleAccounts` a graduate every 2 s for 30 min.

## `damm_pools`: removed in 0.5.0 (FEAT-107)

The Meteora DAMM v2 capture moved to trading-meteora
([FEATURES.md §2.2](FEATURES.md#22-new-meteora-damm-v2-pools-feat-107-record-only)).
A settings file that still has `damm_pools` is refused (`Unknown
module_settings keys: damm_pools`): remove the section, or run the capture
with trading-meteora. Its keys as of `v0.4.0` are in this page's history at
that tag.

## `execution`: paper fills and modelled costs

| Key | Default | Meaning |
|---|---|---|
| `slippage_bps` | `500` | A buy is refused when its fill price is more than this above the signal price. |
| `fee_bps_floor` | `0` | Least swap fee a side. The fee is the pool's tier from the PumpSwap fee config (on the market cap at the mint's real supply, BUG-162) when it can be read, else the AMM `global_config` total. Not needed for the live tiers (RESULTS §6.16). |
| `priority_fee_lamports` | `5000` | Priority fee booked on every fill (as `priority_fee`). |
| `compute_unit_limit` | `200000` | Compute units requested (live transactions; kept for the live gate). |
| `use_jito` | `false` | Book a Jito tip on every fill. |
| `jito_tip_lamports` | `0` | The tip, when `use_jito` is on. |
| `paper_entry_delay_seconds` | `0` | Wait before a paper buy reads the pool, to model a live buy's latency (BUG-121's lesson). The paper example (and the rc.9 run) use `1.5`, pumpbot's paper latency; `2` is a fair stress test (RESULTS §6.14). |
| `quote_max_age_seconds` | `15` | A held pool's reading older than this is re-read before the engine marks or exits on it; a failed read makes the quote stale. |
| `rpc_timeout_seconds` | `10` | Timeout of one pool or fee-config read. |

Every fill also books the 5,000-lamport base fee (`fee`) and, on the first
buy of a coin, the Token-2022 account rent (`rent`, 1,513,840 lamports),
which a full exit refunds ([dev/COSTS.md](dev/COSTS.md)).

## `capture`: the capture file

Every migration and every pool reading, in pumpfun-trading's capture shape
(`migration`, `observation_start`, `curve_poll` with `source: "graduation"`,
`observation_end`), so the rc.8 read-out scripts and `trading-pump replay`
read the same file. Rotated and pruned by its own policy, never by another
file's (BUG-157).

| Key | Default | Meaning |
|---|---|---|
| `path` | `"data/capture.jsonl"` | The capture; `null` turns it off. |
| `max_bytes` | `52428800` | Rotate at 50 MB. |
| `max_files` | `100` | Rotated parts kept: about two weeks of graduation rows at rc.8's rate (about 320 MB a day before compression). Check the oldest row after the first day (BUG-157's lesson). |
| `max_age_days` | `30` | Parts older than this are pruned. |
| `compress` | `true` | Gzip rotated parts. |
| `flush_interval_seconds` | `5` | How often buffered rows are written. |

## `stream`: the PumpPortal WebSocket (BUG-150)

| Key | Default | Meaning |
|---|---|---|
| `reconnect_delay_seconds` | `1` | First wait after a disconnect; doubles to 30 s and resets once a connection is up. |
| `heartbeat_seconds` | `20` | Ping interval (`0` = no pings). PumpPortal answers pings. |
| `idle_timeout_seconds` | `1800` | Reconnect after this long without a message (`0` = never). A half-open socket once sat silent for 3 h (BUG-150); the migration feed is silent between graduations (up to 18 minutes in rc.9), so a shorter wait reconnects for nothing (BUG-163). The pings (`heartbeat_seconds`) catch a dead socket first. |

## `screening`: the anti-rug screen (FEAT-04, FEAT-26)

Used only when `lane.screen_entries` is on. The keys and defaults are
pumpbot's, so a screen tuned there reads the same. `preset`
(`conservative`, `balanced`, `aggressive`) starts from that preset's
thresholds and the other keys override it:

```json
"screening": {"preset": "conservative", "min_holder_count": 6}
```

| Key | Default | Meaning |
|---|---|---|
| `preset` | none | Start from a pumpbot preset's thresholds. |
| `enable_anti_rug_filters` | `true` | `false` passes every token with risk score 0. |
| `max_dev_24h_launches` | `5` | Creator launches in the last 24 h. |
| `max_creator_initial_holding_pct` | `0.10` | Creator's share of supply. |
| `max_top5_holder_concentration_pct` | `0.15` | Top five holders' share. |
| `max_gini_coefficient` | `0.85` | Holder inequality; a hard reject (BUG-56). |
| `require_social_links` | `false` | Reject without social links (then `min_social_links_count` applies). |
| `min_social_links_count` | `1` | Links needed when they are required. |
| `require_holder_data` | `false` | Reject when no holder data could be read (BUG-107). |
| `min_holder_count` | `0` | Least holder accounts at screening (`0` = off; at most 20 are returned). |
| `max_acceptable_risk_score` | `50` | Reject above this score (0–100). |
| `screening_cache_ttl_seconds` | `60` | How long a verdict is reused. |
| `enable_cluster_analysis` | `true` | Trace the funding of the top holders. |
| `max_cluster_concentration_pct` | `0.25` | Share held by funding-linked wallets. |
| `max_single_cluster_pct` | `0.20` | Share held by the largest such cluster. |
| `max_sybil_wash_ratio` | `0.20` | Wash-trade share among early trades. |
| `cluster_trace_depth` | `2` | Funding hops traced. |

The presets:

| Key | `conservative` | `balanced` | `aggressive` |
|---|---|---|---|
| `max_dev_24h_launches` | 2 | 5 | 8 |
| `max_creator_initial_holding_pct` | 0.05 | 0.10 | 0.15 |
| `max_top5_holder_concentration_pct` | 0.10 | 0.15 | 0.25 |
| `max_gini_coefficient` | 0.80 | 0.85 | 0.90 |
| `require_social_links` | true | false | false |
| `min_social_links_count` | 2 | 0 | 0 |
| `max_acceptable_risk_score` | 30 | 50 | 70 |

## From a pumpbot config

pumpbot's single config file is split: engine keys at the top level,
venue keys in `module_settings`. The common ones:

| pumpbot key | Now |
|---|---|
| `buy_amount_sol` | `order_size` |
| `max_total_exposure_sol`, `max_position_size_sol`, `max_active_positions`, `max_token_concentration_pct`, `max_loss_per_trade_sol`, `reserve_balance_sol` | `risk.max_total_exposure`, `risk.max_position_size`, `risk.max_active_positions`, `risk.max_concentration_pct`, `risk.max_loss_per_trade`, `risk.reserve_balance` |
| `max_daily_drawdown_pct`, `drawdown_reference_mode`, `profit_ratchet_ratio`, `profit_ratchet_min_gain_pct`, `profit_drawdown_tolerance_pct`, `max_cumulative_drawdown_pct`, `emergency_hard_lock_hours` | `breaker.*`, same names |
| `take_profit` / `stop_loss` (multiples) | `exits.take_profit_pct` / `exits.stop_loss_pct` (fractions: a 1.2× take profit is `0.2`, a 0.85 stop is `0.15`) |
| `max_hold_time_seconds` | `exits.max_hold_seconds` |
| `dry_run` | `mode` (`"paper"` or `"live"`, and `--live`) |
| `paper_entry_delay_seconds` | `module_settings.execution.paper_entry_delay_seconds` |
| `PUMPFUN_JITO_TIP_LAMPORTS`, `PUMPFUN_USE_JITO`, `PUMPFUN_COMPUTE_UNIT_LIMIT`, `PUMPFUN_SLIPPAGE_BPS` (variables then) | `module_settings.execution.jito_tip_lamports`, `use_jito`, `compute_unit_limit`, `slippage_bps` |
| `graduation_observation_seconds`, `graduation_observation_max_mints`, `graduation_observation_poll_interval_seconds`, `graduation_observation_fast_seconds`, `graduation_observation_fast_poll_interval_seconds` | `module_settings.graduation.observation_seconds`, `max_mints`, `poll_interval_seconds`, `fast_seconds`, `fast_poll_interval_seconds` |
| `stream_heartbeat_seconds` | `module_settings.stream.heartbeat_seconds` |
| screening keys, `strategy_preset` | `module_settings.screening` (and `preset`) |
| `replay_log_path`, `replay_max_bytes`, `replay_backup_count`, `replay_retention_days`, `replay_compress` | `module_settings.capture.path`, `max_bytes`, `max_files`, `max_age_days`, `compress` |
| launch, momentum, pre-graduation, near-graduation, post-exit, Raydium, arbitrage, copy-trading and tier keys | not ported ([dev/TODO.md](dev/TODO.md#not-ported)) |
