# Changelog

All notable changes to `pumpfun-trading` are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the SemVer policy in [`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy). While the version is `0.x`, a MINOR release may change config keys, CLI flags or file formats; such changes are listed under **Changed**.

This is a proprietary project (see [`LICENSE`](LICENSE)). Versions are private git tags only: never published to PyPI or as public GitHub Releases. Only tagged versions run on a funded wallet.

Every entry lists the BUG / FEAT IDs it covers (see [`docs/dev/BUGS.md`](docs/dev/BUGS.md) and [`docs/dev/PROPOSED-FEATURES.md`](docs/dev/PROPOSED-FEATURES.md)) and ends with its release record ([`RELEASE-GATE.md` §5](docs/dev/RELEASE-GATE.md#5-release-record)).

## [Unreleased]

### Fixed
- A PumpPortal top-up is picked up without a restart: while the trade-feed breaker is open, a connection that has already refused is closed and the fresh connection subscribes again, instead of re-asking the refused one (BUG-156). The dashboard keeps "degraded: token-trade subscription refused" across reconnects until the feed is back, shows the retry countdown on the Trade feed row, and on recovery shows Trade feed ok, Last status "monitoring active tokens" and the CLOSED notice. `bot_status.json` → `trade_feed_breaker.reconnects`.

### Added
- Launch entry filter (FEAT-75): `launch_skip_creator_buy_below_sol` (default `0` = off) skips a launch whose creator bought more than 0 and less than that many SOL (`entry_refusals.tiny_creator_buy`); with `momentum_max_entry_drift_pct: 0.15` (fills more than 15% above the create market cap) it cut the paper loss per trade by about one point on the rc.6 and rc.7 data.
- Graduation tracking (FEAT-73, record-only): `graduation_observation_seconds` (default `0` = off), `graduation_observation_max_mints` (300) and `graduation_observation_poll_interval_seconds` (5) follow every coin that migrates to PumpSwap, held or not, as `curve_poll` rows with `source: "graduation"` (`market_cap_sol` on the curve basis, `pool_sol`, `pool_tokens`) and `observation_start` / `observation_end` rows. Never trades; replay skips the rows. `configs/capture.json` turns it on for 4 h at 10 s. Status: `watch_list.graduation`, counter `graduation_observed`.
- Graduation tracking polls the first `graduation_observation_fast_seconds` (300) after a migration every `graduation_observation_fast_poll_interval_seconds` (2) (FEAT-73).
- The launch sample follows a launch still alive at its TTL until it graduates or fades: `launch_sample_extend_seconds` (default `0` = off), `launch_sample_extend_min_real_sol` (1.0), `launch_sample_extend_poll_interval_seconds` (15); its `observation_end` row carries `extended: true` and a new cause `faded`; counter `extended` in `watch_list.launch_sample.stats` (FEAT-73). `configs/capture.json` turns it on for up to 4 h.
- Cross-chain market recorder (FEAT-74, record-only): `pumpfun-recorder --market` records new pools and trending / top-volume lists on Solana, Base and BSC (GeckoTerminal) and follows each picked pool for up to 7 days (DexScreener), into `market/market.jsonl` (`market_pool`, `market_list`, `market_snapshot`, `market_end`, `market_stats`). Options `--market-chains`, `--market-sample`, `--market-state`, `--market-max-followed`, `--market-no-lists`. Keyless; no RPC credits.
- `get_pumpswap_pool_states`: batched PumpSwap pool reads (33 pools per `getMultipleAccounts` call, vault addresses cached), with the reason each refused pool was left out.

## [0.3.0-rc.7] - 2026-10-26

Seventh release candidate of v0.3.0 (this release branch, off `main` at the v0.3.0-rc.6 merge): a **fix release** from the first 18 h of the rc.6 launch-mode A/B (BUG-154, BUG-155, [`BUGS.md` §27](docs/dev/BUGS.md#27-rc6-paper-run-findings-2026-10-26); branch `fix/curve-wait-and-health-label`). Entry market caps were correct (median 28.35 SOL against a fresh curve's 27.96 SOL), but 80% of the launch buys were refused because the new coin's curve was read before the RPC had it, and the coins refused did better than the ones bought. The rc.6 A/B covers only that biased fifth of launches; re-run it on rc.7.

This is a **pre-release for paper testing only**, like rc.1 to rc.6. It must not run on a funded wallet.

### Fixed
- A buy waits for a new launch's curve account: when the read finds no account, it is repeated every 0.25 s for up to `entry_curve_wait_seconds` before the buy is refused as `curve_missing` (was: refused at once as `not_pump_fun`); a curve owned by another program is still refused at once. In paper the wait counts toward `paper_entry_delay_seconds` (BUG-154).
- The status no longer stays "health timeout" after the stream recovers; a resume is recorded as "trading resumed: stream active" (BUG-155).

### Added
- Config key `entry_curve_wait_seconds` (default `3.0`, `0` = read once, 0–10) (BUG-154).
- `bot_status.json` → `entry_curve_wait` (fills found on the first read / after a wait, wait p50 / p90 / max, budget) and `entry_refusals.curve_missing`; fills record `curve_wait_seconds` (BUG-154).
- `CurveAccountMissingError` (a `NotPumpFunCurveError`) from `get_bonding_curve_state` when the curve account has no value.

### Known issues
- rc.5 had almost no such refusals and rc.6 had 63–96% every hour; the change came with rc.6's RPC setup and is not explained. `entry_curve_wait` measures how long Helius takes now; if fills often wait close to the budget, raise it.
- Everything listed under rc.6's known issues still applies.

### Release record – v0.3.0-rc.7 (2026-10-26)
- Commit: the release commit on `release/v0.3.0rc7` (`pyproject.toml` → `0.3.0rc7`, this entry), on a merge of `fix/curve-wait-and-health-label` into `main` at `dd3dd2c` (the v0.3.0-rc.6 merge)
- Release gate: PASS on Linux (`nox -s format lint mypy tests package audit`: tests on 3.11, 3.12, 3.13 and 3.14); the CI matrix and the kill-and-restart drill in paper mode on the Mac are still to run
- Tests: 2,164 collected (9 more than rc.6, for BUG-154 and BUG-155), all passed on 3.11–3.14; coverage 97.08–97.12% (statement + branch); the wheel `pumpfun_trading-0.3.0rc7-py3-none-any.whl` ships 119 files, no tests, private classifier
- Risk drills: `pumpfun-drill --report` 4 of 4 passed
- Security: secrets grep clean; `nox -s audit` no known vulnerabilities
- Paper verdict (FEAT-67): `configs/verdict_rules.json` unchanged
- Capital stage after this release: 0 (paper only)
- Sign-off: –

## [0.3.0-rc.6] - 2026-10-25

Sixth release candidate of v0.3.0 (this release branch, off `main` after the rc.5 merge and the operator's cost notes): a **fix release** for the rc.5 launch-mode paper run (BUG-145 to BUG-153, [`BUGS.md` §26](docs/dev/BUGS.md#26-rc5-paper-run-findings-2026-10-25); branches `fix/runtime-rpc-outage`, `fix/paper-sell-and-retry-reason`, `docs/costs`). Both rc.5 A/B runs are void: 29% of their paper buys were filled at an invented price when the curve read failed, which made all of the reported profit, and the last hour ran with no working RPC. rc.6 makes paper buys and sells fail where live ones would, stops the RPC pool from hammering a rate-limited endpoint, and reconnects a silent stream.

This is a **pre-release for paper testing only**, like rc.1 to rc.5. It must not run on a funded wallet.

### Fixed
- Paper buys no longer fill without a curve read: a failed read at the signal or after `paper_entry_delay_seconds`, a zero-token quote or a complete curve refuses the buy (`curve_unreadable`, `curve_complete`), as it would refuse a live one; the fresh-launch fallback is gone (BUG-145).
- Launches whose create event already shows a full curve (410.88 SOL market cap: the creator bought it all in the create transaction) are skipped in both entry modes (`complete_at_create`), and live-fidelity replay skips them too (BUG-146).
- A held coin that migrated is valued and exited from its PumpSwap pool only, never from PumpPortal trade messages; while the pool can't be read the position is flagged `price_stale` and shown as `… SOL (stale)` in the terminal UI (BUG-147).
- A failed PumpSwap pool read backs off (2 s doubling to 60 s, no RPC call while waiting) and is logged as a warning with its cause; "graduated while held" is logged; a repeated exit decision logs at INFO once a minute (BUG-148).
- No buys while every RPC endpoint's breaker is open (BUG-149).
- The PumpPortal socket is pinged (`stream_heartbeat_seconds`) and reconnected after twice `health_check_timeout_seconds` (120 s) without a message, instead of waiting on a half-open connection for hours; "Cannot write to closing transport" reconnects quietly (BUG-150).
- The RPC pool sends nothing to an open endpoint: requests fail at once (`RpcPoolUnavailableError`) until the cooldown ends, which now starts at 1 s and doubles per opening up to `rpc_pool_circuit_breaker_cooldown_seconds`, with one half-open probe at a time; failed transaction simulations no longer open the breaker; a 429 error keeps the provider's reason with keys masked (BUG-151).
- Paper sells whose curve read fails are refused and go to the exit retry queue, as a live sell would (BUG-152).
- A retried sell repeats the exit that failed (reason, tier, fraction) instead of recording the error text as its reason and selling everything (BUG-153).
- Held positions are refreshed with one `getMultipleAccounts` per pass instead of one call per position, and record-only observation polls wait while the RPC is rate limited (BUG-151).

### Added
- Config key `stream_heartbeat_seconds` (default `20`, `0` = no pings) (BUG-150).
- `bot_status.json`: `entry_refusals` (refused entries by cause: `curve_unreadable`, `curve_complete`, `complete_at_create`, `rpc_unavailable`, …); `rpc_pool_telemetry.rejected_requests` and `requests_by_method`, and per endpoint `open_streak` and `last_rate_limited_time`; positions `price_stale` / `price_stale_since`; watch stats `position_refresh_errors` and `observation_polls_deferred`; exit retry entries `exit_reason`, `sell_fraction`, `sell_amount_tokens` and `target_tier` (BUG-145 to BUG-153).
- A startup warning when the RPC pool has a single endpoint (BUG-151); [`RUNBOOK.md` §5.8](docs/dev/RUNBOOK.md#58-rpc-and-stream-outages-bug-145-to-bug-151) on RPC capacity and outages.
- Test support: `FakeCurves` and `standard_curve` (`tests/support/fakes.py`) give a paper bot curve reads.

### Known issues
- Replay cannot see an RPC outage: on a capture where paper buys were refused (`entry_refusals.curve_unreadable` / `rpc_unavailable`), replay can still buy those signals, so `--compare-audit` shows them as replay-only fills.

### Changed
- New [`docs/dev/COSTS.md`](docs/dev/COSTS.md): subscriptions, payments and the measured running cost per bot (Helius credits, PumpPortal trade data).
- `PUMPFUN_RPC_URLS` documentation: when set, the pool uses only those endpoints (list the primary first).
- Golden replay: the scenarios give the bot a curve that follows the stream's market cap; the open position in `position_cap_and_unheld_trades` now holds the curve's 329,113,500,516 tokens instead of the fresh-launch fallback's 353,134,762,944. Every ledger row is unchanged.

### Release record – v0.3.0-rc.6 (2026-10-25)
- Commit: the release commit on `release/v0.3.0rc6` (`pyproject.toml` → `0.3.0rc6`, this entry), on merges of `docs/costs` and `fix/paper-sell-and-retry-reason` (which contains `fix/runtime-rpc-outage`) into `main` at `50658ec`
- Release gate: PASS on Linux (`nox -s format lint mypy tests package audit`: tests on 3.11, 3.12, 3.13 and 3.14); the CI matrix and the kill-and-restart drill in paper mode on the Mac are still to run
- Tests: 2,155 collected (43 more than rc.5, for BUG-145 to BUG-153), all passed on 3.11–3.14; coverage 97.09–97.14% (statement + branch); the wheel `pumpfun_trading-0.3.0rc6-py3-none-any.whl` ships 119 files, no tests, private classifier
- Risk drills: `pumpfun-drill --report` 4 of 4 passed
- Security: secrets grep clean; `nox -s audit` no known vulnerabilities
- Replay parity: golden replay changed only in the open position's token amount (above); live-fidelity replay now skips launches complete at creation (BUG-146)
- Stream: PumpPortal answers WebSocket pings (pong in 115 ms, 2026-10-25), so the 20 s heartbeat is safe
- Paper verdict (FEAT-67): `configs/verdict_rules.json` unchanged
- Before the next run: the HTTPS Helius URL in `PUMPFUN_RPC_URL`, one RPC key per bot plus a fallback in `PUMPFUN_RPC_URLS` ([`RUNBOOK.md` §5.8](docs/dev/RUNBOOK.md#58-rpc-and-stream-outages-bug-145-to-bug-151)), `EXPECTED_VERSION=0.3.0rc6` in `run-paper.sh`, and a 1 h check of `entry_refusals` and `rpc_pool_telemetry.requests_by_method`
- Capital stage after this release: 0 (paper only)
- Sign-off: –

## [0.3.0-rc.5] - 2026-10-24

Fifth release candidate of v0.3.0 (this release branch, off `main` at the v0.3.0-rc.4 merge): a **data release**. rc.3 recorded a price path for only 6,571 of its 47,523 launches (13.8%), the coins its screen passed or the 20% of rejects it sampled, and stopped watching every coin at the moment it was sold. So the ideas raised after the rc.3 read-out (buy at launch with the screen off, hold through a first-minute dip, take +10% before the fall) could not be tested on the capture. rc.5 records a sample of all launches from creation and follows every closed position after its sell (FEAT-72). Nothing changes what the bot buys or sells; the new rows are record-only and replay skips them.

This is a **pre-release for paper testing only**, like rc.1 to rc.4. It must not run on a funded wallet.

### Added
- Launch sample (FEAT-72): `launch_sample_pct` (0 = off), `launch_sample_max_mints` (300), `launch_sample_ttl_seconds` (900), `launch_sample_poll_interval_seconds` (5). A salted, deterministic share of every standard Pump.fun launch is polled from its create event as `curve_poll` rows with `source: "launch_sample"`, before screening and every entry gate, in both entry modes; `observation_start` carries `created_at`, `market_cap_sol`, `entry_mode` and the create event's `creator`, `creator_buy_sol`, `creator_buy_tokens`, `symbol` and `name`.
- Post-exit tracking (FEAT-72): `post_exit_observation_seconds` (0 = off), `post_exit_max_mints` (100), `post_exit_poll_interval_seconds` (2). Every fully closed position keeps being polled as `source: "post_exit"` rows tagged with `exit_reason`, `entry_market_cap_sol` and `exit_market_cap_sol`; `observation_start` adds `strategy` and `held_seconds`.
- Both hooks run inside the buy and sell paths, so they catch, count (`observation_hook_errors`) and log their own failures and never raise into trading.
- `watch_list.launch_sample` / `watch_list.post_exit` in `bot_status.json`, counters `launch_sampled` and `post_exit_observed`; `jq` recipes in [`RUNBOOK.md` §6.3](docs/dev/RUNBOOK.md); [`FEATURES.md` §42](docs/FEATURES.md#42-launch-sample-and-post-exit-tracking-feat-72-rc5).

### Changed
- `configs/capture.json` samples 20% of launches and follows each closed position for 15 minutes; `configs/pregrad_pilot.json` follows its closed positions (the launch sample runs once per capture + pilot pair).
- The record-only observation task also runs in `launch` entry mode when a rc.5 list is on (the rc.3 reject sample and discovery scan stay confirmed-mode only), and polls at the shortest interval of the lists that are on (at least 1 s).
- A mint in several observation lists is read once per poll and written once per list; before, only the first list got a row (no rc.3 data was lost: discovery already skipped reject-sampled mints).

### Known issues
- The trades of sampled and exited coins (buyer wallets, sizes, timing) are still not recorded, only their curve state (FEAT-72 **Not built**).
- Capture volume: at rc.3's ~1,050 launches an hour, a 20% sample adds about 38,000 rows an hour (~0.9 M a day); post-exit adds up to 450 rows per closed position at the 2 s interval, about 0.5 GB a day for a busy launch-mode run. The default replay retention (`PUMPFUN_REPLAY_BACKUP_COUNT` 10 × `PUMPFUN_REPLAY_MAX_BYTES` 50 MB) holds only about a day of that before rotation deletes the oldest part; set `PUMPFUN_REPLAY_BACKUP_COUNT` to 40 or more (the runtime `.envrc` uses 40) and archive each run as it ends. RPC load: about one extra `getMultipleAccounts` call every 2 s (100 accounts per call).
- The momentum and pre-graduation lanes are NO-GO (rc.3, [`STRATEGY-PIVOT.md` §6.11](docs/dev/STRATEGY-PIVOT.md#611-v030-rc3-interim-read-out-455-h-both-pumpfun-lanes-no-go-2026-10-23)); rc.5 is not a Stage 0 build. Everything listed under rc.4's known issues still applies.

### Release record – v0.3.0-rc.5 (2026-10-24)
- Commit: the release commit on `release/v0.3.0rc5` (FEAT-72, configs, docs, `pyproject.toml` → `0.3.0rc5`), branched from `fe87c61` (merge of PR #44, `release/v0.3.0rc4` → `main`)
- Release gate: PASS on Linux (`nox -s format lint mypy tests package`: tests on 3.11, 3.12, 3.13 and 3.14); the wheel `pumpfun_trading-0.3.0rc5-py3-none-any.whl` ships 119 files, no tests, private classifier
- Tests: 2,112 collected (20 new for FEAT-72), all passed on 3.11–3.14; coverage 97.02–97.09% (statement + branch)
- Replay parity: new rows are record-only (`RECORD_ONLY_POLL_SOURCES`), so replay of a capture is unchanged; golden replay unchanged
- Paper verdict (FEAT-67): `configs/verdict_rules.json` unchanged from rc.4 (rules sha256 `0a9217ce71b1e16fe87f83eed5708f12b2410414c7e54177daa802c95aea14c0`)
- First run on this build: the 24 h launch-mode A/B in the runtime folder (configs outside the repo, see [`TODO.md`](docs/dev/TODO.md#rc5-data-launch-sample-and-post-exit-tracking-feat-72)); run `run-paper.sh` with `EXPECTED_VERSION=0.3.0rc5`
- Capital stage after this release: 0 (paper only)
- Stage 0 paper pilot: not started on this build
- Sign-off: –

## [0.3.0-rc.4] - 2026-10-23

Fourth release candidate of v0.3.0 (PRs #36–#43 and this release branch): a **tooling and risk release**. It ships the fixes from the 2026-10-22 code review (BUG-127 to BUG-140, [`BUGS.md` §24](docs/dev/BUGS.md#24-code-review-risk-execution-and-maths-2026-10-22); one branch per bug, merged on `rc4/integration`) and the rc.4 pre-flight work (`rc4/implementation`, one branch per item): the circuit breaker in replay (FEAT-66), the pre-registered paper verdict (FEAT-67), the run provenance stamp (FEAT-68), the scripted risk drills (FEAT-69) and the bugs they found (BUG-141 to BUG-143, [`BUGS.md` §25](docs/dev/BUGS.md#25-rc4-pre-flight-findings-2026-10-22)). After the rc.3 interim read-out it also fixes the over-eager ratchet floor (BUG-144) and adds Binance bars to the FEAT-65 recorder. Nothing here changes a confirmed-momentum buy decision on paper; the risk engine, live pricing and tooling change.

This is a **pre-release for paper testing only**, like rc.1 to rc.3. It must not run on a funded wallet.

The v0.3.0-rc.3 interim read-out (45.5 h) is a **NO-GO** for both Pump.fun lanes: momentum −0.179 SOL over 127 closed positions (14% profitable, both halves and every UTC day negative, bootstrap 90% interval of the mean per position [−0.0021, −0.0010] SOL), pre-graduation 0 trades, and what-ifs on discovered near-graduation curves and screen-rejected movers lose 6–14% per trade. Pump.fun strategy work stops here; no Stage 0 runs on these lanes. The FEAT-65 slow lane passes on costs (a 0.1 SOL round trip costs about 0.1–0.5%) but shows no edge on six months of bars ([`STRATEGY-PIVOT.md` §6.11–6.12](docs/dev/STRATEGY-PIVOT.md#611-v030-rc3-interim-read-out-455-h-both-pumpfun-lanes-no-go-2026-10-23)).

### Added
- `pumpfun-replay` models the bot's circuit breaker in live-fidelity replays and parity checks: daily limit, profit ratchet floor, cumulative cap, hard lock and emergency liquidation on the data clock; summary block `circuit_breaker`, `entry_rejections.circuit_breaker`; `--no-circuit-breaker` turns it off (FEAT-66).
- `pumpfun-audit verdict`: a pre-registered go / no-go rule (`configs/verdict_rules.json`) on a paper audit trail, per lane: net after an exit haircut and a tip top-up, both halves and most UTC days positive, positive without the best positions, bootstrap lower bound above zero; prints the rule hash, exit code 1 on NO-GO (FEAT-67).
- Run provenance stamp at startup: version, git commit / branch / modified flag, mode, config path with file and effective-config SHA-256, Pump.fun fee tiers and Jito tip switches, in `bot_status.json` (`run_provenance`), a `run_started` audit record, an `event: "run_provenance"` capture row and the `bot started` alert; new optional `PUMPFUN_GIT_COMMIT` for copies without `.git`. Replay lists a capture's stamps (`capture_runs`) and `--compare-audit` warns when the replay config file differs from the run's (FEAT-68).
- `pumpfun-recorder --backfill-bars --bar-source binance`: multi-year daily / hourly bars from Binance's public spot klines (keyless, `data-api.binance.vision`), each `<SYMBOL>USDT` pair from its listing, closed bars only, rows `venue: "binance"` with `pair` and `quote_asset` to `slow_lane/binance_bars.jsonl`. Optional `"binance"` pair per token in the token list (`null` skips: mSOL, jitoSOL); `--bar-base-url` overrides the host, `--bar-since YYYY-MM-DD` sets the first bar; a missing pair is counted and skipped, and a blocked host (403 / 418 / 451) stops the run with a hint. `--bar-max-pages` now defaults per source (6 GeckoTerminal, 100 Binance) and both sources report `Page limit reached`. A backfill writes one file and no longer rotates at 50 MB (a full Binance download is about 100 MB). `bars_in_sol` divides only bars of the same `venue`. Smoke-tested live on 2026-10-23: 314,865 bars for the 9 listed tokens in under 3 min, no errors (FEAT-65).
- `pumpfun-drill` / `pumpfun ops drill`: four scripted risk drills on a paper bot with a simulated clock, no network and a throwaway key (cumulative cap with restart and `SIGUSR1` reset, emergency lock across midnight, live start with the balance RPC down, slow tier sell); `--report` JSON, exit code 1 on failure. `TradingBot.clock` drives the breaker checks (FEAT-69).

### Changed
- New config key `profit_ratchet_min_gain_pct` (default `0.02`, `0` = old behaviour): the profit ratchet floor arms only once the day's peak realized gain reaches that share of the starting equity (BUG-144).
- Terminal UI: `Last event` is shown only in the Health Check panel; the duplicate row in Bot Status is gone (panel heights unchanged).
- `pumpfun-replay --config` / `--preset` starts from the paper bot's wallet (`paper_starting_balance_sol`, else reserve + 10 buys) instead of 100 SOL when `--initial-cash` is not given, and runs the circuit breaker. Replays of `configs/canary.json` can now halt as paper would; `--no-circuit-breaker --initial-cash 100` reproduces earlier results. Sweeps, `--keep`, shadow tools and the optimizer are unchanged (FEAT-66).
- New config key `max_cumulative_drawdown_pct` (default `0.30`, `0` = off; `0` in `configs/capture.json` and `configs/pregrad_pilot.json`): a loss cap across days and locks from a persisted reference equity. Breaching it liquidates and sets the operator pause; resuming with `SIGUSR1` resets it (BUG-128).
- Emergency locks with `emergency_hard_lock_hours` > 0 now last their full duration across the 00:00 UTC rollover; soft halts and zero-hour locks still end at midnight (BUG-128).
- The profit-run zone also halts new buys below the realized-profit ratchet floor (BUG-127). The floor follows the day's peak realized PnL, so a win given back through closed trades halts buys too (BUG-141).
- `enable_raydium_migration_sniping` defaults to `false` in every preset (BUG-131).
- Velocity z-score baseline excludes the current and pre-creation slices; presets with a z threshold need 90 s of trade history (BUG-133).
- Dynamic slippage: impact term is the execution slippage (about half the old term) and the volatility term is fed from every curve read (BUG-134).
- Optimizer fitness is per position, with per-trade Sharpe / Sortino and a 1% Calmar drawdown floor; scores are not comparable with earlier runs (BUG-135).

### Fixed
- Profit ratchet floor computed but never enforced (BUG-127).
- Daily lock lifted at UTC midnight and no cumulative loss cap (BUG-128).
- Live positions measured from the signal market cap instead of the fill (BUG-129).
- Live day baseline could come from the simulated start balance (BUG-130).
- Raydium positions recorded a fixed 69 SOL entry; unknown entries became 30 SOL (BUG-131, BUG-137).
- Geyser trade handler bought on the legacy momentum spike in confirmed mode (BUG-132).
- Breaker valued open positions at spot, ignoring the sell fee and exit haircut (BUG-136).
- Market cap from on-chain reserves now has explicit units; the launch market cap is 27.96 SOL, not 30 (BUG-137).
- Pump.fun market-cap fee tiers (`fee_config`) are read from chain for live quotes and checked at startup against the modelled 125 bps (BUG-138).
- FEAT-65 sell quotes record their gap after the buy quote; cost-distribution and SOL-terms bar helpers (BUG-139).
- A take-profit tier queued behind a slow sell of the same tier was sold twice (BUG-140).
- The profit ratchet floor fell with closed losses after a win (BUG-141).
- The profit ratchet floor halted buying for the rest of the day after a trivial win and a tiny dip: +0.011 SOL realized on a 2 SOL wallet, then 0.0007 SOL under the floor (BUG-144).
- 51 documented environment variables were never read, `PUMPFUN_DRY_RUN` among them; they are gone from the manuals and `pumpbot` warns at startup when one is set (BUG-142).
- The test suite wrote `events.jsonl` into the working directory and one test posted a real webhook past the DNS guard; event logs now go to the test's temp dir, proxy variables are removed and the DNS guard covers the whole session (BUG-143).
- Test `test_compare_audit_prints_provenance_and_replay_skips_the_stamp` failed on macOS: the long `tmp_path` (`/private/var/folders/...`) made Rich wrap the provenance note across lines. The test now compares whitespace-normalised output (test-only change; found by the first Mac gate run).

### Known issues
- The momentum and pre-graduation lanes are NO-GO (see above). rc.4 is not a Stage 0 build for them.
- `configs/canary.json` behaves differently from rc.3: the ratchet floor is enforced (BUG-127) from the day's peak realized PnL (BUG-141) once the gain reaches `profit_ratchet_min_gain_pct` (BUG-144), and the cumulative cap is on. Replays of it start from the paper wallet with the breaker on (FEAT-66), so they are not comparable with pre-rc.4 replays unless run with `--no-circuit-breaker --initial-cash 100`.
- `PUMPFUN_DRY_RUN` and the other 50 names in `UNREAD_ENV_VARS` are still not read: they only trigger a startup warning (BUG-142). Use `paper_trade` / `--dry-run`.
- Not built: refusing to start on a dirty checkout or on a config that differs from the release record (FEAT-68), and scripted versions of the process-level drills (FEAT-69); the manual drills (RUNBOOK §7.2) are still to run on the paper deployment.
- Mainnet checks still open for the first canary trades: BUG-129 (`entry_price_source: live_fill`), BUG-138 (fee tiers) and the BUG-123 PumpSwap sell, which has still not landed a transaction built by this code.
- The `pumpfun-drill` console script exists only in a venv installed from rc.4; until the shared venv is reinstalled after the rc.3 runs, use `python -m pumpfun_trading.cli.main ops drill`.

### Release record – v0.3.0-rc.4 (2026-10-23)
- Commit: the release commit on `release/v0.3.0rc4` (this record, `pyproject.toml` → `0.3.0rc4`, the macOS test fix); the rest is the code of `2c78974` (merge of PR #43, `docs/rc3-interim-readout` → `main`). The `v0.3.0rc4` tag goes on the merge of this branch into `main`, after CI passes.
- Merged since v0.3.0-rc.3: PR #36 (`rc4/integration`, BUG-127…140), #37 (`rc4/implementation`, FEAT-66…69, BUG-141…143), #38 (rc.4 agent hand-off), #39 (TUI duplicate `Last event`), #40 (BUG-144), #41 (`rc4/implementation` re-merge of the hand-off branch, no code), #42 (FEAT-65 Binance bars), #43 (rc.3 interim read-out)
- Release gate: PASS on macOS (`nox -s format lint mypy tests package`: tests on 3.12, 3.13 and 3.14; 3.11 not installed on the Mac, so 3.11 in CI and in the earlier Linux run)
- Tests: 2,092 collected, all passed on 3.12, 3.13 and 3.14; coverage 97.06% (statement + branch); golden replay unchanged
- Replay parity: on the rc.3 capture the first parity run with the breaker on showed a false 93-position gap, because the rc.3 paper bot did not enforce the ratchet floor (BUG-127) and the floor armed on a trivial gain (BUG-144); re-run `--compare-audit` on the first rc.4 paper capture
- Scripted drills (FEAT-69): `pumpfun ops drill --report` PASS, 4 of 4 (`cumulative_cap`, `midnight_lock`, `balance_rpc_down`, `slow_tier_sell`) on 2026-10-23
- Paper verdict (FEAT-67): `configs/verdict_rules.json` rules sha256 `0a9217ce71b1e16fe87f83eed5708f12b2410414c7e54177daa802c95aea14c0` (file sha256 `c61725222a875f76257c585209bde4007173b52c29e8254e21d171b387d26a1c`); to be recorded at the start of the next paper run. The rc.3 runs were judged with it as evidence only (not pre-registered): NO-GO
- Run provenance (FEAT-68): to be checked in `bot_status.json` → `run_provenance` of the first rc.4 run (`git_dirty: false`, `config_file_sha256`, `fee_launch_bps`; RUNBOOK §3 step 4)
- Money path changed (ratchet floor and cumulative cap enforced, emergency locks across midnight, live entries from the fill, breaker at exit value, fee tiers from chain), so no earlier Stage 0 result carries over
- Runtime settings: `configs/capture.json` and `configs/pregrad_pilot.json` turn off the cumulative cap and the ratchet (`max_cumulative_drawdown_pct: 0.0`, `profit_ratchet_ratio: 0.0`); `configs/canary.json` keeps the defaults; copy `configs/verdict_rules.json` into the runtime `configs/` before the next paper run and do not edit it once the run starts
- Next: let the rc.3 72 h runs finish (2026-10-24) and archive them; reinstall the shared venv and pin `runtime/pumpfun-trading` to `v0.3.0rc4` only after that; FEAT-65 walk-forward test on the Binance bars with a random-entry baseline before any slow-lane code ([`STRATEGY-PIVOT.md` §6.12](docs/dev/STRATEGY-PIVOT.md#612-feat-65-slow-lane-phase-0-read-out-costs-pass-no-edge-shown-2026-10-23))
- RUNBOOK §7 drills: scripted drills PASS; manual drills (§7.2) not yet run
- Capital stage after this release: 0 (paper only)
- Stage 0 paper pilot: not started on this build
- Sign-off: –

## [0.3.0-rc.3] - 2026-10-21

Third release candidate of v0.3.0 (PRs #31–#34 and this release branch). It records the rc.2 verdict, fixes the paper / replay exit-price gap the rc.2 read-out found (BUG-126), adopts the one exit change that held on three captures (`stop_loss` 0.92 for the momentum lane), trims the shadow set to the rules worth a second look, and ships the read-out tooling, BUG-122, Sprint 28b and the rc.3 capture inputs (FEAT-59/60/61, a sample of screen-rejected launches, discovered near-graduation curves and stop-crossing measurement; all record only). It also ships the FEAT-65 phase 0 data recorder (Jupiter quotes, priority fees and OHLCV bars for liquid Solana tokens), a separate `pumpfun-recorder` process that runs next to the rc.3 runs, so the slow-lane data exists if rc.3 is NO-GO too.

This is a **pre-release for paper testing only**, like rc.1 and rc.2. It must not run on a funded wallet.

The v0.3.0-rc.2 capture is a **NO-GO** for the momentum lane: paper +0.014 SOL over 105 positions (32.4% profitable), about −0.007 SOL once paper sells pay the exit slippage replay charges; replay with the rc.3 `configs/canary.json` +0.000 SOL at tip 0. The best 5 positions made +0.096 SOL and the other 100 lost −0.082. The pre-graduation pilot took 2 positions (−0.008 SOL): the screen and the 10 min watch TTL starve it. Entry thresholds are not tuned further; the rc.3 capture runs 48 h ([`STRATEGY-PIVOT.md` §6.10](docs/dev/STRATEGY-PIVOT.md#610-v030-rc2-capture-and-pilot-momentum-no-go-stop-092-adopted-2026-10-21)).

### Added
- `pumpfun-replay --shadow-report` (FEAT-58, `engines/shadow_report.py`): reads a paper capture's `shadow_entry` rows and reports per variant the signals, refusals by reason, fill drift (median, p90, share above 5 / 8 / 10%) and a modelled net PnL. Each fill that was not refused is mirrored into live-fidelity replay at its recorded fill price with the paper penalty, and the config's exits and cost model run on the capture's data for that mint; positions open at the end are marked to market. Every variant is compared with a random cut of the baseline variant (`--shadow-baseline`, default `baseline`), per half with `--split-at mid|TIMESTAMP`; `--json` prints the report. Needs `--config` (the capture's config).
- `pumpfun-audit cuts` (`bot/selection.py`): tests entry rules on the closed positions of an audit trail against a random cut, per half with `--split-at`. Rules are `--keep METRIC<OP>VALUE` on the buy's `entry_metrics` or `market_regime` (e.g. `top_buyer_share<0.3`, `hour_utc>=12`), repeatable and also tested together; `--strategy` picks a lane. Replaces the hand-run scripts in `data/analysis-2026-10-20/`.
- `pumpfun-audit pnl --group-by hour`: books each whole position under the UTC hour of its buy (`market_regime.hour_utc`, else the buy's timestamp), to test the time-of-day effect seen in rc.1.
- Stop-loss redesign keys (all default `0` = the plain stop): `stop_loss_arm_seconds` (no stop until the position is that old), `stop_loss_demand_hold_seconds` (the stop waits while a buy of at least `stagnant_min_buy_sol` from another wallet came within that window) and `stop_loss_hard_floor` (exits at or below this ratio while the stop waits; must be below `stop_loss`). Exit reason `stop_loss_floor`. No shipped config sets them.
- `pumpfun-replay --sweep KEY=V1,V2,...` (`engines/sweep.py`): replays the config with each value (repeat for a grid) and reports net per half A / B against the base config; a grid point only counts when it beats the base in both halves. On the v0.2.3 and rc.1 captures a later or demand-held stop lost in every half; a tighter stop (0.90–0.95) won by noise-sized amounts ([`STRATEGY-PIVOT.md` §6.8](docs/dev/STRATEGY-PIVOT.md#68-stop-loss-sweep-wallet-scores-and-the-capture-rule-tool-2026-10-20)).
- Entry features rebuilt from a capture (`engines/cuts.py`; the `data/analysis-2026-10-20/` scripts as one tested tool): FEAT-56 `top_buyer_share` / `wallet_diversity` / `unique_buyers` / `pre_entry_buys`, FEAT-57 `round_trip_wallets` / `round_trip_share` / `quick_flips`, `early_sol` / `first_trade_gap_seconds` and the walk-forward FEAT-55 `creator_prior_loss`, from the trades recorded before each entry with the creator left out. Used by `pumpfun-replay --keep RULE` (replayed positions against a random cut, per half) and `pumpfun-audit cuts --capture CAPTURE` (paper positions of trails that predate the recorded metrics; recorded metrics win).
- FEAT-54 phase 1, wallet scores (`pumpfun-replay --wallet-scores`, `engines/wallets.py`): every wallet in a capture is ranked by what copying it would have netted us (the config's size, `paper_entry_delay_seconds` or `--copy-delay`, paper penalty, Pump.fun fee and modelled costs), on closed copies only; `--validate-path` checks the top wallets on a second capture against a random cut and random wallet sets; `--wallet` always shows a wallet and says when it is a creator. On v0.2.3 → rc.1 no wallet set made money.
- Pullback shadow variants (FEAT-59): `shadow_variants` entries take `"kind": "pullback"` (evaluated on the trade feed of subscribed mints) or `"kind": "pullback_curve"` (evaluated on the watch poller's curve reads, so every watched mint, no billed subscription) with `pullback_*` thresholds (defaults in `strategies/shadow.py::PULLBACK_DEFAULTS`: peak ≥ 40 SOL market cap, 30–70% below it, no new low for 10 s, ≥ 3% off the low, ≥ 0.2 SOL net inflow over 15 s, age 30–900 s). They write `shadow_entry` rows with `kind` and the peak / low / drawdown / base, and never trade. On v0.2.3 / rc.1 the trade-feed kind fired 10–11 times a day and did worse than a random cut of the baseline in 3 of 4 halves; the curve kind needs `watch` polls (rc.2 on) ([`STRATEGY-PIVOT.md` §6.9](docs/dev/STRATEGY-PIVOT.md#69-pullback-entry-buy-timing-and-the-bundle-proxy-for-rc3-2026-10-20)).
- Buy-timing inputs (FEAT-60, recorded only), `OrderFlowEngine.buy_timing`: `timing_buys`, `buy_gap_median_seconds`, `buy_gap_cv`, `burst_share`, `buy_size_cv`, `small_buy_share`, on every momentum buy's `entry_metrics` and every shadow signal; shadow filters `min_buy_gap_cv`, `max_burst_share`, `min_buy_size_cv`, `max_small_buy_share`. Offline on v0.2.3 / rc.1 no filter beat a random cut in both halves.
- Bundle proxy (FEAT-61, recorded only), `HolderDistribution.early_holder_cluster` / `strategies.filters.bundle_metrics`: `early_holders` (non-creator, non-curve accounts with ≥ 1% of supply at screening) and `early_holder_pct`, in every screening capture record and momentum `entry_metrics`; shadow filters `max_early_holders`, `max_early_holder_pct`. No earlier capture has the data.
- `pumpfun-replay --shadow-report --shadow-scan` (`engines/shadow_scan.py`): rebuilds the `shadow_entry` rows from a capture's recorded trades and watch polls with the config's `shadow_variants`, so a new variant can be read out on an older capture. Fills are the first recorded price after `paper_entry_delay_seconds` (within 5 s), so nets are optimistic next to paper (scanned rc.1 baseline −0.006 SOL, paper −0.099): compare variants with the scanned baseline only. On the rc.2 capture it reproduces the recorded rows exactly.
- `configs/capture.json` logs 19 shadow variants (adds three FEAT-60, two FEAT-61, the trade-feed pullback and four curve pullbacks); `configs/pregrad_pilot.json` logs the four curve pullbacks (trimmed after the rc.2 read-out, see **Changed**).
- Record-only curve observations for the rc.3 capture (`strategies/observation.py`, `bot/handlers/observe.py`). Nothing here changes a buy or an exit: the observed mints are never watched, promoted, shadow-evaluated or bought, and they poll in their own task so the watch poller is never delayed. Replay, `--shadow-report` and `--shadow-scan` skip their rows, so a capture with them replays like one without.
  - Screen-rejected sample: `screen_reject_sample_pct` (default `0` = off; `0.2` in `configs/capture.json`) polls a deterministic share (SHA-256 of the mint) of the launches the screen rejects, up to `screen_reject_sample_max_mints` (100; 150 in `capture.json`) for `screen_reject_sample_ttl_seconds` (1800; 3600 in `capture.json`). Rows: `event: "observation_start"` with `reject_reasons` and `risk_score`, `curve_poll` with `source: "reject_sample"` and `reject_reasons`, and `observation_end` with `cause` (`ttl`, `complete`, `mayhem`, `missing`, ...) and first / last / peak real SOL. Shows whether the top-5 holder and creator-holding caps keep out coins that later get demand.
  - Pre-graduation discovery: `graduation_discovery_scan_seconds` (default `0` = off, else at least 10; `30` in `configs/pregrad_pilot.json`) asks the Pump.fun API for the 50 most recently traded coins still on their curve (`PumpFunApiClient.scan_active_coins`: one attempt, outside the retry loop and circuit breaker, so a failed scan never disables screening). Pump.fun / SOL-quote curves with at least `graduation_discovery_min_real_sol` (40) real SOL that the bot does not already poll are polled as `curve_poll` rows with `source: "discovery"`, regardless of screening or the watch TTL, until they complete, fall below the floor, or reach `graduation_discovery_ttl_seconds` (7200); at most `graduation_discovery_max_mints` (100). The pre-graduation lane does not buy from them, so the rc.3 pilot stays a control.
  - Both lists poll every `observation_poll_interval_seconds` (default 5, at least 1; 10 in the configs) through one batched `get_bonding_curve_states` call; counters in `watch_list.stats` (`reject_sampled`, `discovery_scans`, `discovery_scan_errors`, `observation_poll_errors`) and per-list `watch_list.reject_sample` / `watch_list.discovery` in the status file.
- Stop-overshoot measurement, `record_stop_crossings` (default `false`; `true` in `configs/canary.json`, `capture.json` and `pregrad_pilot.json`): per held position the first trade-feed price and the first curve-refresh price at or below `stop_loss` are kept, and every full exit writes `exit_metrics` (`stop_level`, `trigger_ratio` = the price the exit fired at, `fill_ratio` = proceeds over cost, and `trade_feed_` / `refresh_` `cross_ratio`, `cross_at`, `lead_seconds`) on the audit sell record and the capture's sell row. Exits are unchanged; this measures how much a trade-feed stop trigger could save before one is built.
- FEAT-62 proposed (docs only, `docs/dev/PROPOSED-FEATURES.md`): Moonshot (Solana) as a second venue, evaluated capture first (read-only recorder → offline random-cut test → execution only if it passes). Axiom / Fomo, Four.meme / SunPump and exchange IDOs were reviewed and not taken up; the reasons are in the entry.
- FEAT-64 and FEAT-65 proposed (docs only, `docs/dev/PROPOSED-FEATURES.md`): a read-only recorder for post-graduation PumpSwap long-tail pools, evaluated capture first like FEAT-62, and a "slow lane" (daily-bar trend on liquid Solana tokens through Jupiter, with its own bar backtester), to be considered only if the Pump.fun lanes are still NO-GO after rc.3.
- FEAT-65 phase 0, slow-lane data (`services/slow_lane.py`, record-only: no wallet, no transactions, never inside `pumpbot`). Two new `pumpfun-recorder` modes, both keyless:
  - `--jupiter-quotes`: every `--quote-interval` (300 s) quotes each token of the list (`--tokens`, default the built-in list = `configs/slow_lane_tokens.json`: SOL, USDC, JUP, JTO, BONK, WIF, PYTH, RAY, ORCA, mSOL, jitoSOL) on Jupiter's free `lite-api.jup.ag` at `--quote-sizes` (0.02, 0.1, 0.5 SOL): a buy SOL → token, then a sell of exactly those tokens back, so each pair is a full round trip at that size. Rows `event: "quote"` (`venue: "jupiter"`: in / out amounts, `price_impact_pct`, `route`, `pools`, `hops`, `context_slot`, request `latency_ms`, `price_sol` on buys, `round_trip_ratio` / `round_trip_cost_bps` on sells), `quote_error`, and one `price` row per token (Price API v3: USD price, liquidity, 24 h change, decimals). With `PUMPFUN_RPC_URL` / `PUMPFUN_RPC_URLS` set it also writes `fee_sample` rows (`getRecentPrioritizationFees`, network-wide and for the 12 most recently quoted pools: p50 / p90 / max, `nonzero_share`, `nonzero_p50` / `nonzero_p90`; `--no-fee-samples` turns them off). Requests are paced (`--request-gap`, default 2 s; the keyless API allowed 5 per ~10 s when checked) and a 429 / 5xx is retried up to 3 times with bounded waits; one cycle of the default list is 61 requests, about 2 min. Default output `slow_lane/jupiter_quotes.jsonl` (rotated like captures).
  - `--backfill-bars`: one-off daily / hourly OHLCV download (`--bar-timeframes day,hour`, `--bar-max-pages` 6 × 1,000 bars) from GeckoTerminal's public API for each token's top pool, in USD of the token itself; rows `event: "bar"` (`venue: "geckoterminal"`) to `slow_lane/bars.jsonl`, de-duplicated per run, paced at 6 s per request. Paging stops cleanly at the public history limit (`history_limited`).
  - The rows never go into a Pump.fun capture, and the replay tools never read them. An optional `PUMPFUN_JUPITER_API_KEY` moves quotes to `api.jup.ag` and is sent as an `x-api-key` header only; any URL in an error row or log goes through `ops/redact.py`.

### Fixed
- BUG-126: paper sells took no slippage while live-fidelity replay took 100 bps, so on the rc.2 capture replay ran 0.028 SOL below paper (tip 0, allowed ±0.002) on the same 105 positions. New config key `paper_exit_slippage_bps` (default `0`, clamped to 0–5,000): paper sell proceeds lose that many bps, and live-fidelity replay uses it instead of the engine's `slippage_bps` when set. `100` in the `momentum` preset, `configs/canary.json`, `configs/capture.json` and `configs/pregrad_pilot.json`. With it matched the same-exit positions agree to −0.002 SOL; configs without the key, older captures and the golden replay are unchanged.
- BUG-122: stream reconnects are counted in `connection_loss` (and logged as a stream connection-loss event): `on_stream_exception` and `on_stream_ended` count one loss per disconnect unless a shutdown was requested. Telemetry only.

### Changed
- `momentum` preset, `configs/canary.json` and `configs/capture.json`: `stop_loss` 0.85 → **0.92**. It beat 0.85 in both halves of the v0.2.3, rc.1 and rc.2 captures (rc.2: +0.004 / +0.011 SOL). `configs/pregrad_pilot.json` keeps 0.85, since 0.92 was never tested on that lane. An earlier tier-1 take-profit (1.2–1.3×) was tested too and lost in at least one half of every capture; the take-profit settings are unchanged.
- `configs/capture.json` logs 8 shadow variants instead of 19: `baseline`, `buyers6`, `drift5`, `drift10`, `feat56_diversity` (all beat a random cut in both halves of rc.2), the two FEAT-61 bundle filters (first data in rc.3) and the trade-feed pullback. Dropped: `buyers8`, `feat56_top_buyer`, the FEAT-57 and FEAT-60 filters and the four curve pullbacks. `configs/pregrad_pilot.json` logs none (every curve pullback lost on the rc.2 pilot).
- Docs: rc.2 verdict and results in `STRATEGY-PIVOT.md` §6.10; RUNBOOK §6.3 read-out joins the rotated capture parts first, runs the capture 48 h and archives the previous run first; TODO / DONE for Sprints 24G / 24H (screen sample, pre-graduation discovery, stop overshoot); `AGENTS.md` learning on paper exit fidelity.
- `pumpfun-replay` mirroring recorded fills: a fill row that carries `strategy`, `creator`, `entry_metrics` or `entry_penalty_bps` (only the shadow read-out writes them) gets that lane, the paper penalty, and, for `momentum`, the buy-flow stagnation clock fed by later buys of other wallets. Fills the bot recorded carry none of these keys and mirror exactly as before.
- `pumpfun-audit cuts` positions carry `exit_ts`; `render_selection_report` takes an optional console.
- Docs: implemented features moved from `docs/dev/PROPOSED-FEATURES.md` to `docs/FEATURES.md` §30–36 (FEAT-42, FEAT-49, FEAT-50, FEAT-51, FEAT-52, FEAT-53, FEAT-58); the recorded-only inputs of FEAT-54 (phase 1), FEAT-56, FEAT-57, FEAT-60 and FEAT-61 are listed in §37, while their gates stay proposed.
- Docs: unbuilt features moved out of `docs/FEATURES.md`. FEAT-10 (web dashboard, FastAPI portal, Telegram command bot; no code) left §13 and stays in `PROPOSED-FEATURES.md`; the unbuilt parts of §1 (Geyser transport, FEAT-39), §16 (Raydium sniping after the move to PumpSwap), §19 (`bot/run.py` facade, Sprint 28c), §27 (funding links, new FEAT-63) and §29 (live arbitrage reserves, FEAT-40) are marked **Not built**. `AGENTS.md` Local Norms: new unbuilt features go in `PROPOSED-FEATURES.md` and move to `FEATURES.md` when they ship.
- Docs: `docs/dev/TODO.md` split into open work (1,074 → 231 lines: Now / Next / Later, open sprints of Phases 4b–6, items carried over from the old roadmap) and a new `docs/dev/DONE.md` archive of finished phases, sprints and items under their original headings. Items that were open when archived are marked superseded, moved or closed with the reason (e.g. `nox.ini` is gone, the FEAT-21 recorder tests exist, the pre-pivot Stage 0 steps were overtaken by Phase 4c). `RELEASE-GATE.md` §3.7 now links to Phase 6 instead of Phase 4b. `AGENTS.md` Local Norms: `TODO.md` lists open work only and finished sprints move to `DONE.md`.
- `engines/cuts.py` also rebuilds the FEAT-60 timing inputs from the pre-entry trades and copies the FEAT-61 fields from the screening record, for `--keep` and `pumpfun-audit cuts --capture`. `OrderFlowEngine.get_metrics` takes `exclude_users`. A shadow flow filter whose metric is missing (too few buys for gap statistics, no holder data) is not applied; the rc.2 filters always have their metric, so they behave as before.
- Sprint 28b, stream handlers out of `bot/run.py` (no behaviour change): new `bot/handlers/` package with `curve.py` (Geyser curve state / complete, pre-graduation entry, held-position curve refresh), `trade.py` (trade updates, momentum entry, shadow variants), `raydium.py` (Raydium pool, arbitrage, PumpSwap exit, migrations, graduation backfill), `new_token.py` (create events, watch path) and `watch.py` (watch-list poller, promotion, curve-poll recording). Each `TradingBot` method stays as a one-line delegate, so call sites and patches are unchanged. `bot/run.py` 5,052 → 3,571 lines; golden replay unchanged.

### Known issues
- The momentum lane is NO-GO (see above); Stage 0 does not start on it. rc.3 is a capture build.
- Replay still differs from paper by −0.007 SOL on rc.2 after BUG-126, almost all from one position whose exit path came from curve reads the capture did not record.
- Stops fill below their level: on rc.2 the median stop sold at 80.3% of entry against an 85% stop, because prices move between the 1 s position refreshes. rc.3 measures it (`record_stop_crossings`); the trigger itself is unchanged.
- The pre-graduation lane sees almost no candidates (5 near-graduation curves in 24 h): it only polls screened mints within the watch TTL. rc.3 records discovered curves past 40 SOL alongside, but the lane still buys only from its own watch list.
- The discovery scan relies on the Pump.fun frontend API's `/coins` query (`sort=last_trade_timestamp`, `complete=false`); it was checked by hand on 2026-10-21 (7 of 50 coins past 40 SOL) and is not a documented API, so `discovery_scan_errors` in the status file is the signal that it changed.
- The PumpSwap sell (BUG-123) has still not landed a transaction built by this code.
- FEAT-65 data limits: GeckoTerminal's public API serves only about 6 months of history (183 daily bars; hourly paging answered 401 after about 208 days), so a multi-year backtest needs another source later; run `--backfill-bars` again monthly to extend the series (rows from different runs overlap, so de-duplicate on `mint`, `timeframe`, `timestamp`). Quotes exclude the network fee, priority fee and any token-account rent; `fee_sample` rows give the priority-fee side. The keyless Jupiter rate limit is not documented and may change: `quote_error` rows with `status: 429` are the signal.

### Release record – v0.3.0-rc.3 (2026-10-21)
- Commit: the release commit on `release/v0.3.0rc3` (this record, `pyproject.toml` → `0.3.0rc3`, BUG-126, the config changes); the rest is the code of `d5a5853` (merge of PR #34, `feat/rc3-pullback-timing-bundle` → `main`). The `v0.3.0rc3` tag goes on the merge of this branch into `main`.
- Merged since v0.3.0-rc.2: PRs #31–#34 (read-out tooling, stop-loss sweep, FEAT-54 scorer, BUG-122, Sprint 28b, FEAT-59/60/61, shadow scan, docs split)
- Release gate: PASS (`nox -s format lint mypy tests-3.14 package`; 3.11–3.13 in CI)
- Tests: all passed; coverage 96.95% (statement + branch); golden replay unchanged in launch mode
- Replay (rc.2 capture, rc.3 `configs/canary.json`, net of costs): +0.000 SOL over 107 positions at tip 0, −0.023 SOL at the modelled tip; stop 0.85 −0.015 SOL at tip 0
- Replay parity: rc.2 capture −0.028 SOL against paper; −0.007 with the BUG-126 exit haircut matched (allowed ±0.002); re-run on the rc.3 capture, whose paper sells pay the haircut
- Money path changed (paper exit haircut, stop 0.92), so no earlier Stage 0 result carries over
- Runtime settings: `configs/capture.json` (paper, confirmed, stop 0.92, exit haircut 100 bps, 8 shadow variants, 20% reject sample, stop crossings), `configs/pregrad_pilot.json` (stop 0.85, exit haircut, no shadow variants, discovery every 30 s, stop crossings), `configs/canary.json` (stop 0.92, exit haircut, stop crossings; pre-graduation off), and `configs/slow_lane_tokens.json` for the FEAT-65 recorder. Copy them into the runtime folder. The rc.2 runs are archived in `runtime/archive/paper-v0.3.0rc2/`
- FEAT-65 recorder: smoke-tested against the live keyless endpoints on 2026-10-21 (quotes, prices, pool fee samples and bars written; no rate-limit failures at the default gaps). Start `pumpfun-recorder --jupiter-quotes` with the rc.3 runs and leave it running until the rc.3 verdict; run `pumpfun-recorder --backfill-bars` once ([RUNBOOK §6.4](docs/dev/RUNBOOK.md))
- Next: pin `runtime/pumpfun-trading` to `v0.3.0rc3`; run the momentum capture for **48 h** with `capture.json` and the pre-graduation pilot alongside as a control ([RUNBOOK §6.3](docs/dev/RUNBOOK.md)); read out parity, shadow variants, `pnl --group-by hour`, the reject sample, the discovered curves and the stop crossings
- RUNBOOK §7 drills: not yet run
- Capital stage after this release: 0 (paper only)
- Stage 0 paper pilot: not started on this build
- Sign-off: –

## [0.3.0-rc.2] - 2026-10-20

Second release candidate of v0.3.0 (PRs #24–#29). It ships the one entry change that helped on unseen rc.1 hours (the momentum drift guard), the PumpSwap exit for graduated coins, and a capture that can test more than one rule per run: polled curves, shadow variants, the near-graduation set for the pre-graduation pilot, and recorded market-regime, FEAT-56 and FEAT-57 inputs. No new buy filter is gated on; FEAT-55/56/57 are recorded only.

This is a **pre-release for paper testing only**, like rc.1: the 24 h momentum capture and the 72 h pre-graduation paper pilot run on this tag. It must not run on a funded wallet.

The v0.3.0-rc.1 capture is a **NO-GO** for the momentum lane: paper −0.100 SOL over 65 positions (21.5% profitable), replay with the frozen `configs/canary.json` −0.084 SOL over 62 ([`STRATEGY-PIVOT.md` §6.3](docs/dev/STRATEGY-PIVOT.md#63-v030-rc1-capture-no-go-2026-10-19)). Stage 0 does not start on this lane. The runtime side (watch list, poller, subscription budget) passed its paper exit gate.

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
- Replay ran +0.022 SOL better than paper on the rc.1 capture (tolerance ±0.010). The recorded curve reads should close most of that gap, but this is not yet shown; re-run `--compare-audit` on the rc.2 capture before trusting any sweep on it.
- FEAT-55/56/57 and the shadow variants are recorded only; none of them gates a buy.

### Release record – v0.3.0-rc.2 (2026-10-20)
- Commit: the release commit on `release/v0.3.0rc2` (this record and `pyproject.toml` → `0.3.0rc2`); the code is that of `bb8a33a` (merge of PR #29, `feat/curve-poll-capture-near-grad-shadow` → `main`). The `v0.3.0rc2` tag goes on the merge of this branch into `main`.
- Merged since v0.3.0-rc.1: `7c389e9` (PR #24, BUG-121 replay entry fidelity), `1544f4d` (PR #25, Sprint 28a runtime decomposition), `cdd5d46` (PR #26, momentum drift guard, rc.1 24 h results), `cc4f0c1` (PR #27, BUG-123/124 PumpSwap exit and quote mint, market regime, FEAT-55/56), `2e62858` (PR #28, FEAT-57, graduation backfill, split tips, BUG-125), `bb8a33a` (PR #29, curve polls in the capture, near-graduation set, FEAT-58 shadow variants)
- Release gate: PASS (`nox -s lint mypy tests-3.14 package`; 3.11–3.13 in CI)
- Tests: 1,729 collected, all passed; coverage 96.70% (statement + branch); golden replay unchanged in launch mode
- Replay (rc.1 capture, frozen `configs/canary.json`, tip 0, net of costs): −0.080 SOL over 105 buys, 7 refused by the drift guard. The rc.1 capture has no `curve_poll` rows, so this is the rc.1 replay model; the guard's real test is the rc.2 paper capture
- Replay parity: rc.1 capture +0.022 SOL vs paper (outside ±0.010); to re-run on the rc.2 capture
- Money path changed (drift guard, PumpSwap exit, graduation backfill, per-side tips, quote-mint refusal), so no earlier Stage 0 result carries over
- Runtime settings: `configs/capture.json` (paper, confirmed, drift guard 0.08, curve polls, 50 near-graduation curves, nine shadow variants, pre-graduation off), new `configs/pregrad_pilot.json` (paper, pre-graduation lane and near-graduation set on, no momentum subscriptions) and `configs/canary.json` (drift guard 0.08, pre-graduation off); copy them into the runtime folder. Archive the rc.1 capture first (`runtime/archive/capture-v0.3.0rc1/`)
- Next: pin `runtime/pumpfun-trading` to `v0.3.0rc2`; run the 24 h momentum capture with `capture.json` and, in a second runtime folder, the 72 h pre-graduation paper pilot with `pregrad_pilot.json` ([RUNBOOK §6.3](docs/dev/RUNBOOK.md)); then `--compare-audit`, the shadow-variant read-out and the per-lane PnL. If the momentum lane is not clearly net positive with the drift guard on, stop tuning it ([`STRATEGY-PIVOT.md` §6.4](docs/dev/STRATEGY-PIVOT.md#64-v030-rc1-capture-full-24-h-still-no-go-drift-guard-added-2026-10-20))
- RUNBOOK §7 drills: not yet run
- Capital stage after this release: 0 (paper only)
- Stage 0 paper pilot: not started on this build
- Sign-off: –

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

[Unreleased]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0rc5...HEAD
[0.3.0-rc.5]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0rc4...v0.3.0rc5
[0.3.0-rc.4]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0rc3...v0.3.0rc4
[0.3.0-rc.3]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0rc2...v0.3.0rc3
[0.3.0-rc.2]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.3.0rc1...v0.3.0rc2
[0.3.0-rc.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.3...v0.3.0rc1
[0.2.3]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/andy-shady-org/pumpfun-trading/tree/v0.1.0
