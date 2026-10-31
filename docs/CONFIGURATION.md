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
| `observation_seconds` | `14400` | How long each pool is followed after its migration (4 h). |
| `max_mints` | `500` | Pools followed at once. A full list never evicts: a new graduate is skipped (`list_full` in the stats) so every observation runs its course. |
| `fast_seconds` | `300` | The first part of each observation, read faster. |
| `fast_poll_interval_seconds` | `2` | Read interval during `fast_seconds`. |
| `poll_interval_seconds` | `10` | Read interval after that. |
| `pool_missing_grace_seconds` | `60` | A pool the RPC does not have yet is retried this long after the migration before the observation ends (`missing`); a lagging node answers late (BUG-154's lesson). |

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

## `execution`: paper fills and modelled costs

| Key | Default | Meaning |
|---|---|---|
| `slippage_bps` | `500` | A buy is refused when its fill price is more than this above the signal price. |
| `fee_bps_floor` | `0` | Least swap fee a side. The fee is the pool's tier from the PumpSwap fee config (on the market cap at the mint's real supply, BUG-162) when it can be read, else the AMM `global_config` total. Not needed for the live tiers (STRATEGY-PIVOT §6.16). |
| `priority_fee_lamports` | `5000` | Priority fee booked on every fill (as `priority_fee`). |
| `compute_unit_limit` | `200000` | Compute units requested (live transactions; kept for the live gate). |
| `use_jito` | `false` | Book a Jito tip on every fill. |
| `jito_tip_lamports` | `0` | The tip, when `use_jito` is on. |
| `paper_entry_delay_seconds` | `0` | Wait before a paper buy reads the pool, to model a live buy's latency (BUG-121's lesson). The paper example (and the rc.9 run) use `1.5`, pumpbot's paper latency; `2` is a fair stress test (STRATEGY-PIVOT §6.14). |
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
