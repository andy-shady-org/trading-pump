# Changelog

All notable changes to `pumpfun-trading` are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the SemVer policy in [`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy). While the version is `0.x`, a MINOR release may change config keys, CLI flags or file formats; such changes are listed under **Changed**.

This is a proprietary project (see [`LICENSE`](LICENSE)). Versions are private git tags only: never published to PyPI or as public GitHub Releases. Only tagged versions run on a funded wallet.

Every entry lists the BUG / FEAT IDs it covers (see [`docs/dev/BUGS.md`](docs/dev/BUGS.md) and [`docs/dev/PROPOSED-FEATURES.md`](docs/dev/PROPOSED-FEATURES.md)) and ends with its release record ([`RELEASE-GATE.md` §5](docs/dev/RELEASE-GATE.md#5-release-record)).

## [Unreleased]

Work towards `v0.3.0-rc.2`. The v0.3.0-rc.1 capture is a **NO-GO** for the momentum lane: paper −0.100 SOL over 65 positions (21.5% profitable), replay with the frozen `configs/canary.json` −0.084 SOL over 62 ([`STRATEGY-PIVOT.md` §6.3](docs/dev/STRATEGY-PIVOT.md#63-v030-rc1-capture-no-go-2026-10-19)). Stage 0 does not start on this lane. The runtime side (watch list, poller, subscription budget) passed its paper exit gate.

The full 24.2 h rc.1 capture confirms it: paper −0.099 SOL over 118 positions (29.7% profitable); the last 11.5 h, which no sweep had seen, broke even (+0.001 SOL over 53). The 8-buyer setting, a buy/sell-ratio cap and a 60 s age cap all failed on those hours. The one change that helped in both halves, skipping buys whose price ran away between signal and fill, is added below; it cuts the loss but is not a profit on its own, and replay cannot judge it, so the next 24 h capture is the last test of this lane ([`STRATEGY-PIVOT.md` §6.4](docs/dev/STRATEGY-PIVOT.md#64-v030-rc1-capture-full-24-h-still-no-go-drift-guard-added-2026-10-20)).

### Added
- Momentum entry drift guard, `momentum_max_entry_drift_pct` (default `0` = off; `0.08` in the `momentum` preset, `configs/canary.json` and `configs/capture.json`). For `strategy=momentum` buys the bot passes the signal's market cap to `OrderExecutor.execute_buy`: paper re-reads the curve after `paper_entry_delay_seconds` and skips the buy (`entry_drift` error, no costs) when the curve is more than the limit above the signal; live refuses before sending when the curve is already past it and otherwise caps the slippage at the headroom left. A refused mint is dropped from the watch list and unsubscribed (`watch_list.stats.drift_refused`). Filled buys record `entry_metrics.fill_drift_pct`. Replay applies the same rule to delayed confirmed fills and refunds the cash (`entry_rejections.entry_drift`). On the rc.1 audit trail the guard at 8% would have skipped 17 buys and moved the 24 h result from −0.099 to −0.046 SOL (first half −0.100 → −0.075, second half +0.001 → +0.029).
- PumpSwap exit for graduated coins (BUG-123): `sdk/pumpswap.py` (canonical pool PDA, pool / `global_config` layouts, sell quote, `sell` instruction) and `sdk/pumpswap_execution.py` (`get_pumpswap_market_state`, `quote_pumpswap_sell`, `build_pumpswap_sell_tx`, `pumpswap_sell`); `OrderExecutor.execute_pumpswap_sell`. A held position whose curve completes is priced from its PumpSwap pool and sold there; the sell waits while the pool is missing. New config key `enable_pumpswap_exit` (default `true`).
- The PumpPortal stream also subscribes to `subscribeMigration` (free, not metered). A migration exits a held mint, drops a watched one and is recorded in the capture as an `event: migration` record (no price, so replay skips it).
- Market-regime telemetry (`strategies/regime.py`): every buy audit record, every screening capture record and the status file carry `market_regime` (UTC hour and weekday, launches per minute and graduations per hour over 15 min, `warm` after one full window). Nothing gates on it.
- Momentum buys record `entry_metrics.top_buyer_share`, `wallet_diversity`, `first_poll_sol_growth` and `first_poll_age_seconds` (FEAT-56, recorded only; `OrderFlowEngine.buy_flow_concentration`).
- FEAT-55 (creator reputation book) and FEAT-56 (sniper-volume / wallet-diversity filters) in `docs/dev/PROPOSED-FEATURES.md`, with the offline tests on the v0.2.3 and rc.1 captures in `STRATEGY-PIVOT.md` §6.5: FEAT-55 has no edge; FEAT-56 beats a random cut on both captures but does not make rc.1 positive, so it is recorded and not gated.
- FEAT-57 wash-trade inputs (recorded only): momentum buys record `entry_metrics.round_trip_wallets`, `round_trip_share` (each wallet's matched in-and-out volume over all volume) and `quick_flips` (a wallet reversing within 2 s), from `OrderFlowEngine.round_trip_flow`. Offline on the captures they beat a random cut on the v0.2.3 replay but not on rc.1 paper, so nothing gates on them ([`STRATEGY-PIVOT.md` §6.6](docs/dev/STRATEGY-PIVOT.md#66-wash-trade-inputs-graduation-backfill-and-split-tips-2026-10-20)).
- Graduation backfill: a third completion source for held mints. Every `graduation_backfill_seconds` (new key, default `30`, `0` = off) the bot asks the Pump.fun API about each held mint that is not already migrating; `complete: true` or a `pump_swap_pool` sends it to the PumpSwap exit (`watch_list.stats.graduation_backfill`). Catches a migration the curve refresh and `subscribeMigration` both missed, e.g. across a reconnect or restart.
- Split entry / exit Jito tips for the tip experiment: `PUMPFUN_JITO_ENTRY_TIP_LAMPORTS` and `PUMPFUN_JITO_EXIT_TIP_LAMPORTS` (unset = the shared tip as before). A side set to `0` goes over plain RPC with no tip; a positive value is paid as a fixed tip on that side. Paper costs and `ReplayCostModel.from_env` model the same per-side tips.
- Polled curves in the capture: every curve the bot reads is written to the `--record-replay` capture as an `event: "curve_poll"` row (`market_cap_sol`, `price`, and `real_sol_reserves` / `virtual_sol_reserves` where read), tagged `source`: `watch` (the watch-list poller), `position` (the held-position refresh paper exits price from), `entry_fill` (the curve a paper buy filled or was refused at; the executor now returns `fill_curve_market_cap_sol`) and `shadow_fill`. New key `capture_curve_polls` (default `true`). About 1 KB/s at rc.1 watch-list sizes.
- Replay uses the recorded curves (`engines/replay.py`): a delayed paper fill is priced from the mint's first curve read within 1 s after it is due (the read the paper fill itself takes) and the drift guard judges that price; watched mints are promoted on `watch` polls as live; recorded real reserves feed watch growth and `GraduationEngine`, so exits get curve progress for the pre-graduation tranches. Captures without `curve_poll` rows replay exactly as before.
- Near-graduation set (FEAT-53): with `near_graduation_max_mints` > 0 (default `0` = off) a watched mint past `watch_ttl_seconds` stays on the watch list while its curve is at least `near_graduation_min_progress_pct` along (default 0.5) and grew within `near_graduation_stall_seconds` (300), up to `near_graduation_ttl_seconds` (3600). Its trade subscription is released (it is never promoted again), it is polled every `near_graduation_poll_interval_seconds` (6) until it is within 10 points of the pre-graduation entry band, and it has its own cap so it never takes a regular watch slot. `watch_list.near_graduation` in the status file. Replay models the same set and runs the pre-graduation lane on `watch` polls of watched mints (4 readings, `strategy: pre_graduation`, cost guard), so a capture can now test that lane.
- Shadow variants (FEAT-58): `shadow_variants` lists momentum rules that are logged on paper but never traded (`{"name", momentum_* overrides, "max_entry_drift_pct", "max_top_buyer_share", "min_wallet_diversity", "max_round_trip_share", "max_quick_flips"}`; validated at load). On every trade of a promoted watched mint, or of one seen that way before, each variant fires at most once per mint; the bot then reads the curve after `paper_entry_delay_seconds` and records an `event: "shadow_entry"` row (signal and fill market cap, drift, `refused`, entry metrics) plus a `shadow_fill` curve read. Replay skips `shadow_entry` rows. Bounded at 50 pending reads (`watch_list.stats.shadow_signals` / `shadow_skipped`); only active in confirmed mode with a capture.
- `configs/capture.json` records curves, keeps 50 near-graduation curves and logs nine shadow variants (baseline, 6 / 8 buyers, 5% / 10% drift guard, the two FEAT-56 and two FEAT-57 rules). New `configs/pregrad_pilot.json` for the 72 h pre-graduation paper pilot: lane on, near-graduation set on, no momentum subscriptions.

### Fixed
- BUG-121: `pumpfun-replay` filled confirmed and signal entries at the signal price and ignored `paper_entry_delay_seconds` and `paper_entry_slippage_bps`, so replay ran 0.016–0.023 SOL better than the paper bot on the rc.1 capture. Entries now fill at the last recorded price at signal + delay, cut by the penalty, with no exits before the fill; `entry_metrics` gain `fill_market_cap_sol` and `fill_drift_pct`. Earlier confirmed-lane replay results were optimistic: the v0.2.3 capture drops from +0.139 to +0.062 SOL. Replays without those settings, and entries mirrored from recorded fills, are unchanged.
- BUG-123: a position held through graduation could not exit. The bot waited for a Raydium pool that Pump.fun no longer creates, and on the WebSocket deployment never noticed the completion at all. Completion is now seen from the position refresh, Geyser and the migration feed, and the exit goes through PumpSwap.
- BUG-124: the bonding-curve decoder ignored `quote_mint`, so a USDC-quoted curve would have been priced as lamports. Non-SOL quote mints are now refused as non-standard curves.
- BUG-125: `resolve_strategy_config` built the config field by field and left out `enable_pumpswap_exit`, `replay_log_path`, the FEAT-50 alert keys (`daily_summary_alert`, `daily_summary_hour_utc`, `degradation_alert_minutes`) and every FEAT-42 `profit_sweep_*` key, so those values in a config file were ignored without a warning. They are now read; a test fails when any field is dropped. No shipped config sets them, so current runs do not change.

### Changed
- Sprint 28a, runtime decomposition (no behaviour change; ships with the rc.2 entry rework so Stage 0 runs once; `docs/dev/TODO.md` Sprint 28):
  - `bot/factory.py`: config resolution (stream URL precedence, BUG-117/118 key split, validation) and component builders moved out of `TradingBot.__init__`.
  - `streams/websocket.py`: the PumpPortal connect / read / back-off loop and the subscription messages; `TradingBot` implements the `WebSocketStreamHost` hooks.
  - `ops/metrics.py`: runtime counters and latency telemetry.
  - `execution/sell_pipeline.py`: sell sizing, proceeds and replay-record helpers used by `_sell_token_locked`.
  - `sdk/execution.py` split into `execution_types.py`, `execution_base.py`, `transport.py`, `pumpfun_execution.py` and `raydium_execution.py`; every name still imports from `sdk.execution`.
  - `bot/run.py` 5,078 → 4,631 lines, `sdk/execution.py` 1,953 → 165. Golden replay unchanged.

### Known issues
- BUG-122 (open): stream reconnects are not counted in `connection_loss`; the rc.1 capture connected 7 times with the counter at 0. Telemetry only.
- The PumpSwap sell (BUG-123) is pinned to mainnet account data and a real PumpSwap sell, but no transaction built by this code has landed yet. Paper exercises the pricing only. Send one live sell at the smallest size before relying on it with real capital.

## [0.3.0-rc.1] - 2026-10-18

Release candidate for the strategy pivot (Phase 4c, Sprints 24E–24H; PR #22) plus the fixes from the v0.2.3 capture (BUG-118…120). With `entry_mode: "confirmed"` the bot no longer buys at the create event: it watches screened launches, polls their curves over RPC and buys only after follow-on demand is confirmed, with a pre-graduation lane fed by the same poller. The default `entry_mode` stays `"launch"`, so existing configs behave as before.

This is a MINOR release under the [§6 versioning policy](docs/dev/RELEASE-GATE.md#6-versioning-policy) (new config keys). It is a **pre-release for paper testing only**: the capture run, the replay go/no-go and the 72 h Stage 0 run on this tag. `v0.3.0` is tagged only after Sprint 24G passes Stage 0 ([`STRATEGY-PIVOT.md` §5](docs/dev/STRATEGY-PIVOT.md#5-go--no-go)); until then this build must not run on a funded wallet.

### Security
- BUG-118: the dashboard's Coin Polling and Bot Status panels showed the PumpPortal API key inside the stream URL. The key now has its own variable, `PUMPFUN_STREAM_API_KEY`; `stream_url` stays key-free and the key is only added when connecting to `pumpportal.fun`. A key still in `PUMPFUN_STREAM_URL` is split out and used, with a warning. The dashboard also redacts the stream and Geyser URLs.

### Added
- Strategy pivot plan (Phase 4c, Sprints 24E–24H; FEAT-51, FEAT-52, FEAT-53): [`docs/dev/STRATEGY-PIVOT.md`](docs/dev/STRATEGY-PIVOT.md) records why launch sniping loses (−0.579 SOL over 1,675 positions in the v0.2.3 capture) and replaces it with confirmed-momentum entries plus a pre-graduation lane fed by an RPC curve poller. The target release is v0.3.0 (MINOR: new config keys); the default `entry_mode` stays `"launch"`. The v0.3.0 canary runs at 0.02 SOL with a lower Jito tip (`RELEASE-GATE.md` §3.3).
- FEAT-51 watch list and batch curve poller (Sprint 24F): with `entry_mode: "confirmed"` a screened launch goes onto a bounded watch list (`watch_ttl_seconds`, `watch_max_mints`) instead of being bought. A separate task reads all watched curves with one `getMultipleAccounts` call per 100 mints every `watch_poll_interval_seconds` (`PumpFunExecutionClient.get_bonding_curve_states`; BUG-104/108 checks, mayhem and completed curves dropped) and feeds `GraduationEngine`. Only mints whose real SOL grew by `watch_promote_min_sol_growth` get a trade subscription, at most `watch_max_trade_subscriptions` at once, and none while the trade-feed breaker is open; expired or dropped mints are unsubscribed. `bot_status.json` has a `watch_list` block and the dashboard a `Watch list` row.
- FEAT-52 confirmed momentum entry (Sprint 24G): a promoted watched mint is bought only when its token age is within [`momentum_min_token_age_seconds`, `momentum_max_token_age_seconds`], its market cap within [`min_market_cap_sol`, `momentum_max_market_cap_sol`], `OrderFlowEngine` confirms buyers / inflow / buy ratio / z-score with the creator and the bot's own wallet left out, and `_should_buy` passes. In confirmed mode a cost guard refuses buys whose modelled fixed round-trip costs (network fees, tip, unrefunded rent; `ReplayCostModel.round_trip_fixed_costs_sol`) exceed `max_entry_cost_share_pct` (default 10%). Buys record `strategy: "momentum"` and `entry_metrics`; their sells inherit the lane, so `pumpfun-audit pnl --group-by strategy` splits it out. Exits for confirmed entries: `stagnant_buy_flow` (no buy of at least `stagnant_min_buy_sol` from another wallet within `stagnant_timeout_seconds`) and a `breakeven_ratchet` (floor at entry + `breakeven_buffer_pct` once the peak gain reached `breakeven_ratchet_activation_pct`). New `momentum` preset (`--preset momentum`): conservative screen, `entry_mode: confirmed`, 0.02 SOL, pre-graduation, Raydium, copy trading, arbitrage and rotation off. Launch mode is unchanged (golden replay identical).
- Config key `min_holder_count` (default `0`, off): screening rejects a token with fewer holder accounts than this (`Too few holders`, flag `too_few_holders`). It counts the accounts `getTokenLargestAccounts` returned, bonding curve included, the same number as `holder_count` in replay captures. In the 24 h capture, buying only tokens with more than 5 (`min_holder_count: 6`) was the only filter that was net positive in replay in both halves of the day (+0.026 SOL over ~229 positions); it still needs confirming on a second capture.
- Confirmed-entry replay and tuning (Sprint 24G): with `entry_mode: "confirmed"`, `pumpfun-replay` models watch → promote → confirm instead of mirroring recorded fills (`entries_from: confirmed`, `watch_stats` in the summary); `pumpfun-optimize` also searches the watch, band and momentum-exit keys for a confirmed base config. New `configs/canary.json` (live, 0.02 SOL, 2 positions) and `configs/capture.json` (paper) use the thresholds picked on the first half of the v0.2.3 capture: +0.086 SOL over 62 positions there, +0.023 SOL over 70 on the held-out second half, +0.132 SOL over 132 on the full day at a 25k-lamport tip. The capture only has trade flow for mints the launch-mode bot bought, so this is not yet a go (`STRATEGY-PIVOT.md` §6). The `momentum` preset sets `max_token_concentration_pct` 0.5 (one 0.02 SOL position is 40% of the 0.05 SOL cap).
- FEAT-53 pre-graduation lane via the RPC poller (Sprint 24H): the pre-graduation entry is one helper (`_maybe_buy_pre_graduation`) called from the Geyser curve handler and from the watch-list poller, so it works on the WebSocket deployment. Polled entries need 4 curve readings in the 30 s acceleration window (`evaluate_pre_graduation_harvesting_entry(min_samples=…)`); buys record `strategy: "pre_graduation"` with curve progress and acceleration. In confirmed mode held positions keep their curve progress fresh from the position refresh loop, and the last `pre_graduation_tranches` step sells the whole remainder, so nothing is held into migration (launch mode keeps its runner). The lane stays off in `configs/canary.json` until a 72 h paper pilot (`RUNBOOK.md` §6.3).
- FEAT-54 planned (Sprint 24I, after 24H; docs only): smart-wallet discovery from captures, ranked on net SOL after costs rather than win rate, a copy simulation with our own delay and costs, a reviewed tracked-wallet list (never filled automatically), tracked-wallet buys used as momentum evidence (`momentum_tracked_wallet_bonus`, off by default), and a rolling per-wallet kill switch. See [`docs/dev/STRATEGY-PIVOT.md` §2.4](docs/dev/STRATEGY-PIVOT.md#24-lane-3--reviewed-smart-wallets-feat-54-p2) and `docs/dev/TODO.md` Sprint 24I; `RELEASE-GATE.md` §3.5 keeps copy trading off until its exit gate passes.

### Changed
- New environment variable `PUMPFUN_STREAM_API_KEY`. Move the key out of `PUMPFUN_STREAM_URL` (`?api-key=` still works, with a warning).
- New config keys (FEAT-51/52/53): `entry_mode`, `watch_ttl_seconds`, `watch_max_mints`, `watch_poll_interval_seconds`, `watch_promote_min_sol_growth`, `watch_max_trade_subscriptions`, `momentum_min_token_age_seconds`, `momentum_max_market_cap_sol`, `stagnant_min_buy_sol`, `breakeven_ratchet_activation_pct`, `breakeven_buffer_pct`, `max_entry_cost_share_pct`, plus `min_holder_count`. All default to the old behaviour. New `momentum` preset.
- Buy audit records carry `strategy` (`launch`, `momentum`, `pre_graduation`) and `entry_metrics`; `bot_status.json` and the dashboard show the watch list size and subscribed mints.

### Fixed
- BUG-119: `pumpfun-replay --compare-audit` left the costs booked on live buys out of the live total, so a losing run looked profitable (+2.06 SOL against a real −0.579 SOL). Both sides now net every buy and sell record.
- BUG-120: trade subscriptions were only cancelled on exits from the trade-message path, so most exited mints kept streaming (54% of the capture's trade messages, billed by PumpPortal). `_sell_token` now unsubscribes whenever it closes a position.

### Known limitations
- The confirmed-lane thresholds were picked on the v0.2.3 capture, which only has trade flow for mints the launch-mode bot bought. The replay result (+0.023 SOL over 70 positions on the held-out half) is weak evidence and must be confirmed on a new capture before Stage 0 counts ([`STRATEGY-PIVOT.md` §6.2](docs/dev/STRATEGY-PIVOT.md#62-why-this-is-not-yet-a-go)).
- The pre-graduation lane only sees curves still on the watch list (`watch_ttl_seconds`) or already held, and stays off in `configs/canary.json` until a 72 h paper pilot.
- FEAT-54 (Sprint 24I, smart wallets) is planned only; no code ships for it.

### Release record – v0.3.0-rc.1 (2026-10-18)
- Commit: the release commit on `release/v0.3.0rc1` (this record and `pyproject.toml` → `0.3.0rc1`); the code is that of `83ce16a` (merge of PR #22, `strategy-pivot-momentum` → `main`). The `v0.3.0-rc.1` tag goes on the merge of this branch into `main`.
- Merged since v0.2.3: `004face` (PR #21, BUG-118…120 and capture findings), `83ce16a` (PR #22, Sprints 24E–24H, FEAT-51/52/53, FEAT-54 plan)
- Release gate: PASS (`nox -s lint mypy tests-3.14 package`; 3.11–3.13 in CI)
- Tests: 1,483 collected, all passed; coverage 96.34% (statement + branch); golden replay unchanged in launch mode
- Replay (v0.2.3 capture, `configs/canary.json`, net of costs): first half (tuning) +0.086 SOL / 62 positions, held-out second half +0.023 SOL / 70, full day at a 25k-lamport tip +0.132 SOL / 132; the tip moves the full-day result by at most 0.03 SOL
- Replay parity: not yet run on a confirmed-mode capture
- Money path changed (entries in confirmed mode, cost guard, momentum exits, pre-graduation via the poller), so no earlier Stage 0 result carries over
- Runtime settings: new `configs/capture.json` (paper, confirmed) and `configs/canary.json` (0.02 SOL, 2 positions, confirmed, pre-graduation off); copy them into the runtime folder
- Next: pin `runtime/pumpfun-trading` to `v0.3.0-rc.1`, record a 24–72 h capture with `capture.json` (also the 24F exit gate), replay it with the frozen `canary.json` thresholds (no re-tuning; go/no-go), then a 72 h Stage 0 with the tip test (0 / 25k / 50k lamports) ([RUNBOOK §6.3](docs/dev/RUNBOOK.md)). Fixes found on paper ship as `rc.2`, `rc.3`, …; a money-path fix restarts Stage 0
- RUNBOOK §7 drills: not yet run
- Capital stage after this release: 0 (paper only)
- Stage 0 paper pilot: not started on this build
- Sign-off: –

## [0.2.3] - 2026-10-17

Tagged on 2026-10-17 (`6002806`, merge of PR #20, `release/v0.2.3` → `main`) without its own CHANGELOG section; recorded here afterwards. This is the build the 24 h capture ran on.

### Fixed
- BUG-117: a `strategy_preset` config filled in the public PumpPortal URL, which beat `PUMPFUN_STREAM_URL`, so the API key was never sent and the trade-feed breaker blamed the key's funds. An env URL now beats that placeholder; a PumpPortal URL without `api-key` logs a warning, and the breaker alert and `trade_feed_breaker.stream_has_api_key` in `bot_status.json` name the missing key.

## [0.2.2] - 2026-10-17

Fixes from the v0.2.1 Stage 0 close-out (PR #17) and a dashboard layout change, plus the trade-feed circuit breaker and mayhem-mode filter (PR #18). These change which tokens are bought and when exits see prices, so this build starts with a 24 h capture run and then a fresh 72 h Stage 0.

Under the [§6 versioning policy](docs/dev/RELEASE-GATE.md#6-versioning-policy) the new config keys would make this a MINOR release (0.3.0); it is kept as 0.2.2 by operator decision, as with 0.2.1.

### Added
- Trade-feed circuit breaker (`bot/trade_feed.py`, BUG-116): opens on PumpPortal's `subscribeTokenTrade` refusal, blocks new buys, survives reconnects and closes only on a confirmed subscription or trade data. The alert names the likely cause: the PumpPortal API key's wallet has run out of funds (it needs ≥ 0.02 SOL). While open a probe subscription is sent every `trade_feed_probe_seconds` (default `300`, minimum `30`), so a top-up is picked up without a restart; recovery is alerted. Status: `trade_feed_breaker`.
- `skip_mayhem_mode` (default `true`): create events with `is_mayhem_mode` are rejected before screening (`mayhem_rejections` in the status file), and a buy is refused when the curve's mayhem flag is set (`mayhem_mode` error), in paper mode too. On mainnet, mayhem curves drifted off the 30 SOL virtual-reserve invariant within 2 s (46.0 SOL seen), so curve pricing doesn't hold for them.
- `paper_starting_balance_sol` (default `0`, meaning reserve + 10 buys): simulated wallet for long paper data runs, so the drawdown breaker isn't reached within hours.
- `position_refresh_seconds` (default `1.0`): held positions are re-priced from their bonding curve in their own task, instead of on the 5 s health loop (BUG-112).
- `require_trade_feed` (default `true`): no new buys while the stream refuses token-trade subscriptions (BUG-112).
- Status snapshot: `trade_feed_available` and `circuit_breaker_locked_at`; dashboard Health Check row `Trade feed` (`ok` / `REFUSED (key funds?)`).

### Changed
- Dashboard: `Max total exposure`, `Max position size`, `Max loss / trade` and `Daily drawdown` moved from the Risk panel to the Strategy panel (they are configured limits; Risk now shows live risk state). Metrics moved from a full-width bottom panel into the Run Time panel, beside Coin Polling at half width each, so open positions no longer push it off the screen.
- `pumpfun-audit pnl --group-by reason`: buy legs are booked under the position's first exit reason, and the `entry` row only holds buys of positions still open (BUG-115).
- `circuit_breaker_lockout_until` now holds the unlock time (next 00:00 UTC, or the hard-lock end if sooner); the lock time moved to `circuit_breaker_locked_at` (BUG-114).

### Fixed
- BUG-111: a sell that starts during a buy's paper entry delay no longer logs an invalid `BUYING → SELLING` transition or settles the state while the buy is still running.
- BUG-112: PumpPortal's refusal of `subscribeTokenTrade` (no funded API key) was silently dropped. Server `message` replies are now logged and counted; a refusal is alerted once, marks the trade feed degraded and blocks buys until a reconnect. **Operator action:** add a funded PumpPortal API key to `PUMPFUN_STREAM_URL`.
- BUG-113: the creator came from the API record even when it was the system program; the create event's signer is now preferred, and an unresolved creator adds the missing-dev-data penalty.
- BUG-114: `circuit_breaker_trips` counted every 5 s check while locked (394 for one trip); it now counts once per lock.
- BUG-116: a trade-subscription refusal was cleared by any reconnect, so buys resumed blind while the key was still unfunded; failed subscription sends are now logged and counted instead of swallowed.

### Known limitations
- The first position after a start can open before any `subscribeTokenTrade` has been confirmed; the breaker only trips on the first refusal.
- The entry confirmation (buy only after other wallets buy, TODO Sprint 24A) is not built yet; its thresholds wait for the 24 h capture run.

### Release record – v0.2.2 (2026-10-17)
- Commit: `7829724` (merge of PR #18, `feat/mayhem-filter-trade-feed-breaker` → `main`). The release commit on `release/v0.2.2` only adds this record; `pyproject.toml` (`0.2.2`) and the code are those of `38af508`.
- Merged since v0.2.1: `4cc58f5` (PR #16, v0.2.1 Stage 0 log), `e2dc05b` (PR #17, BUG-111…115 and dashboard layout), `7829724` (PR #18, BUG-116 and mayhem-mode filter)
- Release gate: PASS (`nox -s lint mypy package`, tests on 3.12, 3.13 and 3.14; 3.11 only in CI)
- Tests: 1,372 collected, all passed; coverage 96.33% (statement + branch)
- Replay parity: not yet run on a capture with trade data
- Mainnet checks (read-only): the funded PumpPortal API key got "Successfully subscribed to keys" for 3 of 3 `subscribeTokenTrade` requests and trade messages arrived; 2 of 4 mayhem-mode curves had left the 30 SOL virtual-reserve invariant within 2 s (46.0 SOL seen), all normal curves had not
- Money path changed (creator resolution, buys blocked while the trade feed is refused, mayhem-mode refusals, 1 s position re-pricing), so earlier Stage 0 results don't carry over
- Runtime settings: `capture.json` validated (canary settings plus `paper_trade: true`, `paper_starting_balance_sol` 2.0, `max_daily_drawdown_pct` 0.5, 5 positions / 0.05 SOL exposure, `stagnant_timeout_seconds` 120, `skip_mayhem_mode`, `trade_feed_probe_seconds` 300); `canary.json` `paper_entry_slippage_bps` lowered to 100
- Next: pin `runtime/pumpfun-trading` to `v0.2.2`, run the 24 h capture ([RUNBOOK §6.2](docs/dev/RUNBOOK.md#62-24-h-capture-run)), build and tune the entry confirmation, freeze `canary.json`, then a 72 h Stage 0
- RUNBOOK §7 drills (incl. the new trade-feed breaker drill): not yet run
- Capital stage after this release: 0
- Stage 0 paper pilot: not started on this build
- Sign-off: –

## [0.2.1] - 2026-10-17

Everything merged to `main` since v0.2.0 (PRs #8–#14): Sprint 24C (no more API keys on disk; backtests that run the live sizing, exits and costs), Sprint 25 (packaging and repository hygiene), Sprints 26–27 (test restructure), the Stage 0 fixes BUG-104…109 and entry hardening, and Sprint 24D (unattended operation). This is the build the restarted Stage 0 paper pilot runs on.

### Security
- BUG-102: new `ops/redact.py` (`redact_url`, `redact_text`) masks credentials in URLs (`?api-key=`, `token`, `user:pass@`, key-like path segments; Solana addresses are kept). Applied to the RPC pool telemetry and config dicts (`bot_status.json`), `TradingBotConfig.to_dict` (`stream_url`, `api_base_url`, `rpc_endpoints`), every `bot.log` line, dashboard events and alerts, and `events.jsonl`. Raw URLs stay in memory for requests.

### Added
- Live-fidelity replay (BUG-61): `PaperTradingEngine(live_fidelity=True)` uses `buy_amount_sol`, the live risk limits (rejections counted in `entry_rejections`) and the live exit stack (`strategies/exits.py`), with partial tier sells and time-based exits on the replay clock.
- `engines/costs.py` `ReplayCostModel`: replay books the paper-mode costs (125 bps protocol fee each side, base + priority fee, Jito tip, rent paid and refunded); sells carry `gross_pnl_sol`, `costs_sol`, `net_pnl_sol`.
- `engines/parity.py` and `pumpfun-replay --compare-audit AUDIT` (`--parity-tolerance-sol`, `--parity-tolerance-pct`): replay-vs-live parity report, exit code 1 outside the tolerance.
- `pumpfun-replay` flags `--simple-exits`, `--no-costs`, `--tip-lamports`, `--priority-fee-lamports`.

### Added (Stage 0 entry hardening, PR #13)
- Paper latency penalty: `paper_entry_delay_seconds` waits and re-reads the curve before a paper fill, and `paper_entry_slippage_bps` (0–5,000) gives fewer tokens and a higher entry market cap. Both default to 0; the fill's `metadata` records them.
- Screening data in captures: with `--record-replay`, each screened token adds an `event: "screening"` record (social links, holder count, top-5 share, Gini, creator holding and launch history, verdict, reasons, latency). Replay skips these records; they are input for per-filter attribution.
- `PUMPFUN_BOT_LOG_PATH` sets where `bot.log` is written (it was documented in runtime setups but never read, so the log always landed in the working directory). It beats the config's `log_file`; `none`/`off` disables the file. Tests now write `bot.log` to their temp directory instead of the repo root.
- New config keys: `require_pump_mint_suffix`, `allow_mint_reentry`, `paper_entry_delay_seconds`, `paper_entry_slippage_bps`.

### Added (Sprint 24D: unattended operation, PR #14)
- Operator pause (FEAT-50): `SIGUSR1` toggles "no new buys, keep managing exits" (`bot/operator.py`; `TradingBot.pause_buying` / `resume_buying`). Capital rotation is blocked too. The state is saved in `bot_status.json` (`operator_pause`, `buying_paused`) and survives restarts; each change is an `operator_pause` audit record and an alert; the dashboard shows a `Buying` row. `bot_status.json` now carries the process `pid`.
- Unattended alerts (`bot/supervision.py`): a daily summary at `daily_summary_hour_utc` (default 00:00 UTC; net / gross PnL, fees, tips, rent, trades, win rate, expectancy, breaker, drawdown, reconciliation, buying state; also a `daily_summary` audit record), one alert when the stream or RPC pool stays degraded longer than `degradation_alert_minutes` (default 5) plus one on recovery, one alert per new reconciliation `GAP`, and `bot started` / `bot stopped` alerts.
- Profit sweep (FEAT-42, off by default): `profit_sweep_enabled`, `profit_sweep_destination`, `profit_sweep_hot_floor_sol`, `profit_sweep_min_sol`, `profit_sweep_interval_seconds` (`bot/sweep.py`, `PumpFunExecutionClient.transfer_sol`). Moves SOL above a floor (never below `reserve_balance_sol + max_total_exposure_sol + 0.01`) to a cold wallet under the trade lock; `sweep` audit records; the breaker baseline drops by the amount (`DailyEquityTracker.record_withdrawal`); paper / dry-run simulate it; the bot refuses to start on an invalid sweep config. `pumpfun-audit reconcile` counts live sweeps in the whole-wallet check (`swept_sol`).
- Supervised deployment templates in `deploy/`: `pumpbot-run.sh`, systemd `pumpbot.service` and `pumpfun-reconcile.{service,timer}` (+ `pumpfun-reconcile.sh`), launchd `com.pumpfun.pumpbot.plist` (`RUNBOOK.md` §8).
- New config keys: `daily_summary_alert`, `daily_summary_hour_utc`, `degradation_alert_minutes`, `profit_sweep_*`.

### Changed
- `pumpbot` exits with code 1 when its stream loop ends without a shutdown request (0 after SIGINT/SIGTERM as before), so a supervisor restarts it.
- `bot started` is now alerted (it was a dashboard event only), so supervisor restarts are visible.
- Dashboard: `Health timeout` is shown only in the Health Check panel; the duplicate row in the Risk panel is gone.
- `pumpfun-replay --config/--preset` now runs live-fidelity replay with costs; results are not comparable with earlier replays (use `--simple-exits --no-costs` for the old model). On `--record-replay` captures, entries are the bot's own recorded fills; recorded `signal` strings are no longer treated as exit orders.
- `pumpfun-optimize`: trials run live-fidelity replay with costs (fitness is net), start with `reserve_balance_sol + 2 × max_total_exposure_sol` of cash instead of 100 SOL, and the search space includes the tier, moonbag, trailing-stop and timeout parameters again.
- A config exported by `pumpfun-optimize` masks credentials in its URLs.

### Build and packaging (Sprint 25: R8, R9, T8, PR #9)
- Removed the unused `requests` runtime dependency.
- Classifiers: `Framework :: Django` and `Development Status :: 5 - Production/Stable` replaced by `Framework :: AsyncIO` and `Development Status :: 3 - Alpha` (0.x, live capital gate not passed); financial audience/topic classifiers added. `Private :: Do Not Upload` kept.
- New optional extras for the planned platform work, unused by the terminal bot: `[web]` (FastAPI, Uvicorn), `[db]` (SQLAlchemy async, Alembic, asyncpg, aiosqlite), `[geyser]` (grpcio, protobuf).
- The wheel and sdist no longer ship `pumpfun_trading/tests/` (`packages.find` exclude plus `MANIFEST.in` prune; setuptools otherwise packed the test files as package data).
- New `nox -s package` session builds the sdist and wheel and fails if the wheel contains tests or lacks the private classifier.
- `nox -s tests` runs on Python 3.11, 3.12, 3.13 and 3.14; CI runs one test job per interpreter plus a `lint mypy audit package` job on 3.14. Ruff (`target-version = "py311"`) and mypy (`python_version = "3.11"`) check against the oldest supported Python.
- `.gitignore` covers runtime artifacts (`bot.log*`, `cov.json`, audit/reconcile/replay files, `data/`, `incidents/`, `test-data/`, `.envrc`); stale bytecode of the retired root `audit`/`bot`/`cli`/`replay` modules removed.
- `CONTRIBUTING.md`: release section rewritten for private tags only.

### Tests (Sprint 26: T1, T4, T6, T7, PR #10)
- Phase 1: pytest runs with `--strict-markers`; markers `unit`, `integration`, `property`, `regression(bug_id)` and `slow` are registered. `unit` / `integration` / `property` are applied by location in `tests/conftest.py` (951 unit, 53 integration today). The 216 redundant `@pytest.mark.asyncio` marks are gone (`asyncio_mode = "auto"`). New `nox -s tests-fast` (`-m "not slow and not integration"`, no coverage gate, not run by default). Test-only change: 1004 tests, coverage 96.29%, no module below its baseline.
- Phase 2: shared test support package `pumpfun_trading/tests/support/`: `constants.py` (`SAMPLE_PRIVATE_KEY`, sample mints, initial curve reserves), `factories.py` (`make_config`, `make_bot`, `make_position`, `make_pool_keys`), `fakes.py` (`FakeClock`, `FakeRpc`, `FakeJito`, `FakeAlertSink`) and `payloads.py` (curve account, trade / complete event and buy / sell instruction bytes), covered by 33 tests in `tests/unit/test_support.py` that round-trip the payloads through the real parsers. The 16 test files that defined their own private key (four different values) now import `SAMPLE_PRIVATE_KEY`. Test-only change: 1037 tests (1004 + 33), coverage 96.29%, no module below its baseline.
- Phase 3 (T7): the suite runs in ~8 s instead of ~136 s. The time was retry backoff, not the bot: with the network blocked, every unmocked Pump.fun API or RPC lookup retried with real waits (~3.5 s and ~0.7 s per call). New autouse fixture `instant_retry_backoff` (`tests/conftest.py`) skips only the sleeps inside `PumpFunApiClient.request` and `RpcConnectionPool.request`; retries still run and the RPC health-loop interval is untouched (`USES_REAL_RETRY_BACKOFF = True` opts a module out). `time.sleep` removed from `test_anti_rug_filters.py` (`FakeClock`), `test_ops_retention.py` (joins the compression thread, and now checks a `.gz` archive exists) and `test_logging_rotation.py` (rollover made due instead of waiting 1.1 s, and now checks the rotated file); nested `asyncio.run` replaced by `await` in 4 files; the record-CLI polling test runs on `FakeClock`. Test-only change: 1,040 tests, coverage 96.30%, no module below its baseline.
- Phases 4a/4b (T1): 20 legacy flat test files now live in the mirrored layout. 4a renamed 12 unchanged (e.g. `test_jito_sdk.py` → `unit/sdk/test_jito.py`, `test_geyser_stream.py` → `unit/streams/test_geyser.py`; new `unit/strategies/`, `unit/streams/`, `unit/services/` packages). 4b merged 8 into the mirrored file that already existed (e.g. `test_rpc_pool.py` → `unit/infra/test_rpc_pool.py`, `test_ops_cli.py` → `unit/cli/test_main.py`). Test-only change: 1,040 tests, coverage 96.30%, no module below its baseline.
- Phases 5–7 (T1, T4): the 7 `*_integration.py` files moved to the new `tests/integration/` package, and the 15 mixed legacy files were split test by test into the mirrored module files (e.g. `test_risk_health_execution.py` → `unit/bot/test_risk.py`, `test_health.py`, `test_lifecycle.py`, `unit/execution/test_builder.py`, `unit/strategies/test_risk_validation.py`). New mirrored files for `bot/alerts`, `bot/persistence`, `bot/health`, `bot/lifecycle`, `cli/bot`, `cli/replay`, `cli/arbitrage`, `config/env`, `engines/generators`, `execution/liquidator`, `execution/builder`, `execution/arbitrage`, `ops/monitoring`, `storage/status` and seven `strategies/` modules; shared executor fixtures in `unit/execution/conftest.py`. 91 inline `TradingBotConfig(...)` calls in the moved files now use `make_config` (behaviour-identical: `dry_run=False` stated where it wasn't set) and four local pool-key helpers use `make_pool_keys`. The interim `*_integration.py` marker rule was removed from `conftest.py`. Test-only change: 1,040 tests (986 unit, 54 integration), coverage 96.30%, no module below its baseline; 21 legacy flat files remain for Sprint 27.

### Tests (Sprint 27: T2, T3, T5, T6, T9, PR #11)
- The last 21 legacy flat files are gone: the six coverage-padding files were dissolved and the `_full` / `_regressions` pairs and themed regression files merged or split test by test into their mirrored module files (new `unit/bot/test_audit.py`, `unit/bot/test_event_router.py`, `unit/cli/test_optimize.py`). The tests root now holds only `conftest.py`. Per-module coverage unchanged; no test deleted. Duplicate local helpers replaced by `support/` (`SAMPLE_MINT`, `WSOL_MINT`, `make_pool_keys`, `make_bot`) and 57 more inline `TradingBotConfig(...)` calls by `make_config`.
- Regression tags (T9): 140 tests carry `@pytest.mark.regression("BUG-xx")`; new tests for BUG-32 (custom config fields survive `TradingBot.__init__`), BUG-75 (market cap from UI-unit and raw reserves, parametrized) and BUG-88 (dashboard shows `entry_reason`). `unit/test_suite_layout.py` fails if a RESOLVED bug in `BUGS.md` has no tagged test (5 older bugs listed as known gaps, shrink-only) or a tag names an unknown bug.
- Layout guard: the same file checks that every source module has `unit/<pkg>/test_<module>.py`, that the tests root holds only `conftest.py`, that every `unit/<pkg>/` has an `__init__.py`, and that no file has a coverage-style name.
- Property tests (`tests/property/`, `hypothesis` added to `[dev]`): `sdk/curve.py` bounds, monotonicity, fees and slippage, and buy-then-sell never returning more SOL, across the full u64 range; `streams/geyser.py` byte round trips for every curve / trade / complete-event field and rejection of short or foreign buffers. Derandomized profile, so runs are reproducible.
- Characterisation tests (T5): `integration/test_golden_replay.py` drives a dry-run bot through `_handle_message` for four scenarios (tiered take-profit and trailing stop, stop-loss, position cap, below minimum market cap) and compares every ledger row, the final positions, state and wallet balance with `integration/golden/*.json`; the safety net for the Sprint 28 `bot/run.py` split.
- `parametrize`: the one pair of literal-only duplicate tests (`unit/ops/test_redact.py`) and the `format_uptime` table converted.
- Test-only change: 1,139 tests (1,040 + 99 new), coverage 96.30%, no module changed; green on 3.12, 3.13, 3.14.

### Fixed
- **BUG-110:** alerts blocked the trading event loop. `_send_alert` called the synchronous webhook (`urlopen`, 10 s timeout) on every alerted event, buys included, freezing stream ingestion and exits for the round trip once an alert provider was set. Inside the running loop alerts are now sent through `send_alert_async` (worker thread) as tracked tasks, and shutdown waits up to 5 s for them.
- **BUG-104 (High, money path):** paper entries were priced from the stream's create event while exits read the on-chain curve, and a non-standard curve variant (virtual SOL 764–105,860 SOL with no real SOL) decoded to 25×–3,500× market caps, producing +64 SOL of phantom profit in the v0.2.0 Stage 0 pilot. New `sdk/curve.py::curve_reserve_anomaly` checks that an active curve's `virtual_sol − real_sol` is the 30 SOL initial reserve (±1%); `get_bonding_curve_state` and `build_buy_tx` raise the new `NonStandardCurveError` on a failing curve. `OrderExecutor.execute_buy` refuses such a buy (live and paper, error `non_standard_curve: …`); price refreshes ignore the curve and keep the stored price; sells still go through. Paper buys now take their entry market cap from the same curve the exits read (`ExecutionResult.metadata["entry_market_cap_sol"]`).
- **BUG-105:** `pumpfun-audit pnl` and `pnl_totals` scored each sell on its own, so the rent refunded on a full exit turned flat exits into wins (97% reported vs 19–29% per position). `win_rate` and `expectancy_sol` are now per closed position (buy plus all its sells, keyed by `position_id`); new fields `positions_closed`, `winning_positions`, `closed_net_pnl_sol`, `open_position_net` and `sell_win_rate` (the old per-sell figure). `--group-by reason` counts each position once, under its first exit reason; the table gains a `Positions` column.
- **BUG-106:** with a position open, every further buy logged `Ignored invalid state transition from HOLDING to BUYING` (276 in 14 h). `HOLDING → BUYING` is now valid, and a buy or sell that ends while positions are still open settles in `HOLDING`, not `MONITORING` (`bot/lifecycle.py::settled_state`).
- **BUG-107:** holder data was missing for 67% of passes. `getTokenLargestAccounts` on a load-balanced RPC flaps for new mints (the same mint returned 2, 0, 2, 0 accounts within 6 s), so an empty answer is now retried up to 4 times within the 2.5 s lookup budget. Lookup outcomes are counted in `bot_status.json` → `holder_lookup_stats` (`ok`, `ok_after_retry`, `empty`, `error`, `timeout`). New config key `require_holder_data` (default `false`) makes missing holder data a hard reject.
- **BUG-108 (High, money path):** the bot bought tokens that are not Pump.fun launches (263 of 1,159 Stage 0 entries, USDC among them). PumpPortal tokens whose `pool` isn't `pump`, or whose mint doesn't end in `pump` (`require_pump_mint_suffix`, default `true`), are rejected before screening and counted in `bot_status.json` → `non_pump_rejections`. `get_bonding_curve_state` and the buy builder raise `NotPumpFunCurveError` when the curve account is missing or not owned by the Pump.fun program, and `execute_buy` refuses such buys in live and paper mode (a missing curve no longer gives a simulated paper fill).
- **BUG-109:** an exited mint could be bought again once the seen-mints cache expired (two mints bought twice, ~6 h apart). Bought mints are kept in `traded_mints` (persisted, capped at 10,000) and a closed one is never bought again; `allow_mint_reentry: true` turns this off.
- Tests ignored the operator shell: an exported `PUMPFUN_JITO_TIP_LAMPORTS` (direnv `.envrc`) changed golden-replay costs. `tests/conftest.py` now removes every ambient `PUMPFUN_*` variable before each test.
- **BUG-103:** `ReplayRecorder.close()` could lose the last batch on shutdown. It cancelled the flush worker while that batch, already taken off the queue, was waiting for its `asyncio.to_thread` write; the cancel also cancelled the write if the thread hadn't started it yet, or closed the sink under a running write. The write is now shielded and finished (and counted) before the cancel is honoured, so `--record-replay` captures and `pumpfun-recorder` keep every record up to shutdown. Found by `unit/cli/test_record.py::test_harvester_websocket_feed_closed_runs_until_duration` failing on Python 3.11 in CI; regression tests in `unit/bot/test_recorder.py`.
- Test `test_retention_sink_and_manager_edge_branches` failed on Python 3.12/3.13: it mocked `Path.stat` globally, which `Path.glob` uses before 3.14. It now fakes only the measured file's size (found by the new interpreter matrix; test-only change).

### Release record – v0.2.1 (2026-10-17)
- Commit: `987fd92` (merge of PR #15, `release/v0.2.1` → `main`), tagged `v0.2.1`. Its release commit `552ded6` only bumps `pyproject.toml` to `0.2.1` and adds this record; the code is that of `f7b34f7` (merge of PR #14, `sprint-24d-income-ops`).
- Merged since v0.2.0: `0ab1ae0` (PR #8, Sprint 24C), `d3f4c77` (PR #9, Sprint 25), `5fdd5bc` (PR #10, Sprint 26), `67969b6` (PR #11, Sprint 27), `1498f37` (PR #12, BUG-104…107), `44b9e27` (PR #13, entry hardening, BUG-108/109), `f7b34f7` (PR #14, Sprint 24D, BUG-110)
- Release gate: PASS (`nox -s lint mypy package tests-3.12 tests-3.13 tests-3.14`; 3.11 only in CI)
- Tests: 1,321 collected, all passed; coverage 96.38% (statement + branch)
- Replay parity: tooling added (Sprint 24C); not yet run on a live capture
- Mainnet simulation: holder-lookup flapping (BUG-107) and the non-standard curves (BUG-104) checked read-only on mainnet; pre-start checks on 2026-10-17 (RPC, stream, holder lookups, config load) in the [Stage 0 log](docs/dev/releases/v0.2.1-stage0.md#pre-start-checks--2026-10-17-before-1141)
- Money path changed (paper pricing, buy refusal on non-standard / non-Pump.fun curves, no re-entry, operator pause), so Stage 0 restarts as a full 72 h run on this tag with an empty `data/`. Applied: `canary.json` has `"paper_entry_delay_seconds": 1.5`, `"paper_entry_slippage_bps": 300`, `"require_holder_data": true`; `.envrc` has `PUMPFUN_BOT_LOG_PATH=data/bot.log`, Slack alerts and a 50,000-lamport Jito tip (was 300,000)
- RUNBOOK §7 pause / sweep / supervisor / degradation drills: not yet run (to run on paper from a second runtime directory); keep the profit sweep off on a funded wallet until its drill passes
- Alerts: Slack test alert and "bot started (conservative preset, paper, pid 73499)" received
- Capital stage after this release: 0
- Stage 0 paper pilot: **in progress**, started 2026-10-17 11:41:22 (+03:00), 72 h ends 2026-10-20 11:41; log in [`docs/dev/releases/v0.2.1-stage0.md`](docs/dev/releases/v0.2.1-stage0.md). Checkpoint 0 (T + 7 min): 0 exceptions, 0 stream drops, RSS ~80 MB; 24 non-Pump.fun mints rejected, 1 non-standard curve refused, holder data for every screened token (10 of 28 after a retry); 4 positions closed (1 stop-loss, 3 stagnant), net −0.00303 SOL, win rate 25% per position (too few trades to judge). New BUG-111 (Low, lifecycle state during an in-flight buy), open until after the run.
- Stage 0 result: **FAIL, closed early** at 2026-10-17 13:14 (T + 1 h 33 min). The daily circuit breaker tripped at T + 60 min (10.16% > 10%) and emergency-liquidated 2 positions; final: 34 positions, net −0.022975 SOL (gross −0.018895, fees 0.00068, tips 0.0034), 2 of 34 profitable; 0 exceptions, 0 stream drops, RSS 79 MB. Causes: no trade data for held positions (BUG-112, PumpPortal needs a funded API key for `subscribeTokenTrade`) and launch-time entries with no follow-on buyers (17 of 34 never moved; all 34 back at launch market cap). New BUG-112…115 ([`BUGS.md` §15](docs/dev/BUGS.md#15-stage-0-close-out-on-v021-2026-10-17)). Stage 1 stays blocked
- Sign-off: –

## [0.2.0] - 2026-10-16

Sprint 24B of the Terminal Income Track: the bot now measures profit **after** costs, recovers token-account rent on every full exit, and checks its books against the wallet. This is the build the official Stage 0 paper pilot and the Stage 1 live canary must run on.

### Added
- **Per-trade costs (FEAT-49).** New `sdk/costs.py` reads the network fee, priority fee, Jito tip, token-account rent and the exact SOL swapped from the confirmed transaction (`getTransaction`, capped at 8 s). Paper and dry-run trades use the same cost model, so paper and live PnL are comparable.
- **Net PnL on trade records (FEAT-49).** New `bot/pnl.py`. Every trade record now carries `signature`, the fee / priority fee / tip / rent fields, `costs_sol`, `gross_pnl_sol`, `net_pnl_sol` and `cash_flow_sol`. Records written by older versions fall back to their gross fields.
- **`pumpfun-audit pnl`** reports realized profit after costs, with `--group-by` day, exit/entry reason, strategy or mint, and `--json` output.
- **`pumpfun-audit reconcile --wallet <pubkey>`** (new `bot/reconcile.py`) checks every live trade against the chain: closed positions that still hold tokens, open positions that hold none, and (with `--start-balance`) the whole-wallet SOL change within `--tolerance-sol`. Exits with code 1 on a gap. `--no-token-check`, `--rpc-url`, `--status-file` and `--no-status-file` are also available.
- **Reconciliation status.** `reconcile` stores its result in `reconcile_status.json` next to the audit trail (override with `PUMPFUN_RECONCILE_STATUS_PATH`). The dashboard Risk panel shows a **Reconciliation** row (OK / GAP / STALE after 36 h / not run) and `bot_status.json` gains a `reconciliation` field.
- **Dashboard Risk panel** shows today's profit after costs, before costs, today's costs, and profit after costs since start.
- **Config key `close_token_account_on_full_exit`** (default `true`; BUG-96).
- **Daily tracker fields** `realized_daily_costs_sol` and `realized_daily_gross_pnl_sol` in the persisted risk state.

### Changed
- **The daily circuit breaker now runs on profit after costs** (FEAT-49). Costs reset at the start of each UTC day. Expect the breaker to trip earlier than on 0.1.x, which under-counted losses.
- **Paper mode deducts Pump.fun's fee on both the buy and the sell**, plus modelled fees, tips and rent. Paper PnL is lower than on 0.1.x and is not comparable with older paper runs.
- **Buys book the SOL actually paid and sells the exact SOL received**, read from the transaction, instead of the quoted amounts.
- **The modelled token-account rent is 1,513,840 lamports** (≈0.0015 SOL, current mainnet Token-2022 ATA rent), not 2,039,280. Live trades always use the figure in the transaction meta.
- **Stream URL precedence** (BUG-100): an explicit `stream_url=` argument now wins, then the config URL, then `PUMPFUN_STREAM_URL` / `PUMPFUN_WS_URL`, then the default. `pumpbot` never passes the argument, so its behaviour is unchanged.
- `DailyEquityTracker.record_realized_trade` takes an optional `costs_sol`; `pnl_sol` must now be net of costs.

### Fixed
- **BUG-96:** a full exit never closed the token account, so every new mint left its rent (≈15% of a 0.01 SOL position) locked in the wallet. The sell that empties the account now closes it in the same transaction. Partial sells never close; if a closing sell fails, the retry sells without closing.
- **BUG-97:** log rotation could store plain text under a `.gz` name and race the background gzip. Archives are now shifted by their on-disk name and each rotation waits (up to 60 s) for the previous compression; a failed gzip is logged and the plain archive kept.
- **BUG-98:** `DiagnosticEventLogger.emit` raised on an unknown category or severity string. It now falls back to `LIFECYCLE` / `INFO` and never raises.
- **BUG-99:** landed arbitrage was booked before fees and tip. It is now booked net, from the bundle transaction (modelled in dry-run or if the lookup fails), and fed to the daily breaker.
- **BUG-101:** the Pump.fun buy/sell builders quoted against made-up initial-curve reserves when a curve reported none. They now raise `CurveStateUnavailableError`; a failed sell goes to the exit retry queue.

### Testing
- `tests/conftest.py` stubs `PumpFunExecutionClient.get_transaction_costs`, so tests never call mainnet; only modules setting `USES_REAL_TRANSACTION_COSTS = True` may use the real one.
- New behaviour tests in the mirrored `tests/unit/<pkg>/` layout (with `__init__.py` per package): 922 tests, coverage 96.2% (gate 95%).
- `tests/conftest.py` blocks DNS lookups of any non-local host, so a test that reaches the network fails at once instead of depending on the public RPC. Four legacy tests had been calling mainnet / the Pump.fun API (token-program lookup, an API client mock that opened a real session) and failed in CI on HTTP 429; they are now fully mocked.

### Known limitations
- Positions removed as dust and exits on Raydium after graduation still leave the token account open (BUG-96 scope).
- The bot's own trades have not yet been reconciled on mainnet; the cost parser was checked read-only against third-party mainnet sells. Closing this is the first task of the Stage 1 canary.
- Arbitrage, pre-graduation harvesting, Raydium sniping and pyramiding stay off for the canary ([`RELEASE-GATE.md` §3.5](docs/dev/RELEASE-GATE.md)).

### Release record – v0.2.0 (2026-10-16)
- Commit: `754822d` (merge of PR #6, `sprint-24b-net-pnl` → `main`; feature commit `99314ab`), plus the `release/v0.2.0` commits that add this record and make the tests network-free. The `v0.2.0` tag goes on the last of those once CI is green.
- Release gate: PASS (`nox -s lint mypy tests`), with the network blocked in tests; CI on `754822d` failed 3 tests that called mainnet and got HTTP 429
- Tests: 922 collected, 922 passed; coverage 96.22% (statement + branch)
- Replay parity: not checked (replay alignment is Sprint 24C)
- Mainnet simulation: cost parser checked read-only on 3 third-party Pump.fun sells
- Capital stage after this release: 0 (official Stage 0 paper pilot to start on this tag)
- Stage 0 paper pilot: started 2026-10-16 18:48 (+03:00); log in [`docs/dev/releases/v0.2.0-stage0.md`](docs/dev/releases/v0.2.0-stage0.md). Checkpoint 1 (T + 14 h): operationally clean (0 exceptions, 0 stream drops, 115 MB RSS), but **Stage 0 cannot pass on this build**: the reported +63.5 SOL net is a pricing artefact (BUG-104), corrected net is about −0.75 SOL over 1,024 trades, the 97% win rate is per sell (BUG-105), holder checks did not run for 67% of buys (BUG-107), and no alert provider is configured
- Canary daily log: –
- Sign-off: –

## [0.1.1] - 2026-10-16

Stream-fed tokens are now enriched before screening, so the bot can pass tokens on the PumpPortal stream at all.

### Added
- `PumpFunExecutionClient.get_token_largest_accounts` (a failed lookup doesn't lower the execution health score).
- `PumpFunAPIClient.fetch_token_metadata`, reading a token's metadata `uri` through Pump.fun's gateway (`pump.mypinata.cloud`), since `ipfs.io` / `dweb.link` return HTTP 429.

### Changed
- The Pump.fun API client retries only on 408/425/429 and 5xx; a 404 no longer retries or counts towards the API circuit breaker. Screening takes about 1 s per token instead of timing out.
- `screen_rejected` events and the dashboard list every rejection reason, not just the first.

### Fixed
- **BUG-95:** `TokenEnricher.enrich_and_screen` skipped enrichment whenever the stream sent a payload, so every token had 0 social links and no holder data and was rejected. Every token is now enriched (API record, metadata `uri`, `getTokenLargestAccounts`) with a 2.5 s cap per lookup; the bonding-curve account is excluded from the top-5 and Gini checks; the creator holding comes from `initialBuy`.
- The mypy error in `tests/test_order_executor.py:506`.

### Release record – v0.1.1 (2026-10-16)
- Commit: `b8a666a`
- Release gate: FAIL (coverage 93.33% < 95%); lint and mypy pass
- Replay parity: not checked
- Mainnet simulation: screening run against 2 live tokens; holder lookup not checked (public RPC returns HTTP 429)
- Capital stage after this release: 0 (soak paper run only; does not count as the official Stage 0)
- Sign-off: –

## [0.1.0] - 2026-10-16

First tagged build (`v0.0.1-alpha` points at the same commit). Baseline for the paper pilot.

### Added
- Proprietary licence and `Private :: Do Not Upload` classifier; the PyPI publish workflow was removed.
- Planning docs: Phase 4b Terminal Income Track, Phases 5–6, architecture decisions, test strategy, documentation plan, rewritten `RELEASE-GATE.md` (live capital gate, funding gate §3.7) and expanded `RUNBOOK.md`.

### Fixed
- **BUG-34:** Pump.fun buy/sell instruction layout verified on mainnet; mayhem-mode fee routing; Jito base64 encoding.
- **BUG-35 … BUG-94** (found by code audit, fixed in seven batches): strategy layer (BUG-38/42/43/56/57/58/65/76/79/80/81); SDK, Jito and RPC-pool contracts (BUG-35/36/51/53/54/66–69/93); executor fill and proceeds accounting (BUG-48/49/50/52/73); runtime exits, concurrency and health (BUG-39/40/41/44/46); persistence, daily rollover, risk caps and lifecycle (BUG-45/47/70/71/74/75/91/92); atomic status writes, bounded caches and env aliases (BUG-72/77/78/87/94); replay, optimizer, CLI, ops and dashboard (BUG-60/62/63/64/82–86/88/89); containment for Geyser, arbitrage and the optimizer (BUG-37/55/59/61/90, mitigated rather than fixed).

### Release record – v0.1.0 (2026-10-16)
- Commit: `4bc324c`
- Release gate: FAIL (mypy: 1 error in `tests/test_order_executor.py`; coverage 93.2% < 95%); waived for Stage 0 paper only
- Tests: 581 collected
- Capital stage after this release: 0
- Sign-off: –

[Unreleased]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0-rc.1...HEAD
[0.3.0-rc.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.3...v0.3.0-rc.1
[0.2.3]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/andy-shady-org/pumpfun-trading/tree/v0.1.0
