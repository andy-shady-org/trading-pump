# Changelog

All notable changes to `pumpfun-trading` are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the SemVer policy in [`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning-policy). While the version is `0.x`, a MINOR release may change config keys, CLI flags or file formats; such changes are listed under **Changed**.

This is a proprietary project (see [`LICENSE`](LICENSE)). Versions are private git tags only: never published to PyPI or as public GitHub Releases. Only tagged versions run on a funded wallet.

Every entry lists the BUG / FEAT IDs it covers (see [`docs/dev/BUGS.md`](docs/dev/BUGS.md) and [`docs/dev/PROPOSED-FEATURES.md`](docs/dev/PROPOSED-FEATURES.md)) and ends with its release record ([`RELEASE-GATE.md` §5](docs/dev/RELEASE-GATE.md#5-release-record)).

## [Unreleased]

Sprint 24C of the Terminal Income Track (merged as `0ab1ae0`, PR #8): no more API keys on disk, and backtests that run the live sizing, exits and costs. Sprint 25 (branch `sprint-25-packaging-hygiene`): packaging and repository hygiene; no runtime behaviour change.

### Security
- BUG-102: new `ops/redact.py` (`redact_url`, `redact_text`) masks credentials in URLs (`?api-key=`, `token`, `user:pass@`, key-like path segments; Solana addresses are kept). Applied to the RPC pool telemetry and config dicts (`bot_status.json`), `TradingBotConfig.to_dict` (`stream_url`, `api_base_url`, `rpc_endpoints`), every `bot.log` line, dashboard events and alerts, and `events.jsonl`. Raw URLs stay in memory for requests.

### Added
- Live-fidelity replay (BUG-61): `PaperTradingEngine(live_fidelity=True)` uses `buy_amount_sol`, the live risk limits (rejections counted in `entry_rejections`) and the live exit stack (`strategies/exits.py`), with partial tier sells and time-based exits on the replay clock.
- `engines/costs.py` `ReplayCostModel`: replay books the paper-mode costs (125 bps protocol fee each side, base + priority fee, Jito tip, rent paid and refunded); sells carry `gross_pnl_sol`, `costs_sol`, `net_pnl_sol`.
- `engines/parity.py` and `pumpfun-replay --compare-audit AUDIT` (`--parity-tolerance-sol`, `--parity-tolerance-pct`): replay-vs-live parity report, exit code 1 outside the tolerance.
- `pumpfun-replay` flags `--simple-exits`, `--no-costs`, `--tip-lamports`, `--priority-fee-lamports`.

### Added (Stage 0 entry hardening, branch `fix/stage0-entry-hardening`)
- Paper latency penalty: `paper_entry_delay_seconds` waits and re-reads the curve before a paper fill, and `paper_entry_slippage_bps` (0–5,000) gives fewer tokens and a higher entry market cap. Both default to 0; the fill's `metadata` records them.
- Screening data in captures: with `--record-replay`, each screened token adds an `event: "screening"` record (social links, holder count, top-5 share, Gini, creator holding and launch history, verdict, reasons, latency). Replay skips these records; they are input for per-filter attribution.
- `PUMPFUN_BOT_LOG_PATH` sets where `bot.log` is written (it was documented in runtime setups but never read, so the log always landed in the working directory). It beats the config's `log_file`; `none`/`off` disables the file. Tests now write `bot.log` to their temp directory instead of the repo root.
- New config keys: `require_pump_mint_suffix`, `allow_mint_reentry`, `paper_entry_delay_seconds`, `paper_entry_slippage_bps`.

### Added (Sprint 24D: unattended operation, branch `sprint-24d-income-ops`)
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

### Build and packaging (Sprint 25: R8, R9, T8)
- Removed the unused `requests` runtime dependency.
- Classifiers: `Framework :: Django` and `Development Status :: 5 - Production/Stable` replaced by `Framework :: AsyncIO` and `Development Status :: 3 - Alpha` (0.x, live capital gate not passed); financial audience/topic classifiers added. `Private :: Do Not Upload` kept.
- New optional extras for the planned platform work, unused by the terminal bot: `[web]` (FastAPI, Uvicorn), `[db]` (SQLAlchemy async, Alembic, asyncpg, aiosqlite), `[geyser]` (grpcio, protobuf).
- The wheel and sdist no longer ship `pumpfun_trading/tests/` (`packages.find` exclude plus `MANIFEST.in` prune; setuptools otherwise packed the test files as package data).
- New `nox -s package` session builds the sdist and wheel and fails if the wheel contains tests or lacks the private classifier.
- `nox -s tests` runs on Python 3.11, 3.12, 3.13 and 3.14; CI runs one test job per interpreter plus a `lint mypy audit package` job on 3.14. Ruff (`target-version = "py311"`) and mypy (`python_version = "3.11"`) check against the oldest supported Python.
- `.gitignore` covers runtime artifacts (`bot.log*`, `cov.json`, audit/reconcile/replay files, `data/`, `incidents/`, `test-data/`, `.envrc`); stale bytecode of the retired root `audit`/`bot`/`cli`/`replay` modules removed.
- `CONTRIBUTING.md`: release section rewritten for private tags only.

### Tests (Sprint 26: T1, T4, T6, T7, branch `sprint-26-test-foundation`)
- Phase 1: pytest runs with `--strict-markers`; markers `unit`, `integration`, `property`, `regression(bug_id)` and `slow` are registered. `unit` / `integration` / `property` are applied by location in `tests/conftest.py` (951 unit, 53 integration today). The 216 redundant `@pytest.mark.asyncio` marks are gone (`asyncio_mode = "auto"`). New `nox -s tests-fast` (`-m "not slow and not integration"`, no coverage gate, not run by default). Test-only change: 1004 tests, coverage 96.29%, no module below its baseline.
- Phase 2: shared test support package `pumpfun_trading/tests/support/`: `constants.py` (`SAMPLE_PRIVATE_KEY`, sample mints, initial curve reserves), `factories.py` (`make_config`, `make_bot`, `make_position`, `make_pool_keys`), `fakes.py` (`FakeClock`, `FakeRpc`, `FakeJito`, `FakeAlertSink`) and `payloads.py` (curve account, trade / complete event and buy / sell instruction bytes), covered by 33 tests in `tests/unit/test_support.py` that round-trip the payloads through the real parsers. The 16 test files that defined their own private key (four different values) now import `SAMPLE_PRIVATE_KEY`. Test-only change: 1037 tests (1004 + 33), coverage 96.29%, no module below its baseline.
- Phase 3 (T7): the suite runs in ~8 s instead of ~136 s. The time was retry backoff, not the bot: with the network blocked, every unmocked Pump.fun API or RPC lookup retried with real waits (~3.5 s and ~0.7 s per call). New autouse fixture `instant_retry_backoff` (`tests/conftest.py`) skips only the sleeps inside `PumpFunApiClient.request` and `RpcConnectionPool.request`; retries still run and the RPC health-loop interval is untouched (`USES_REAL_RETRY_BACKOFF = True` opts a module out). `time.sleep` removed from `test_anti_rug_filters.py` (`FakeClock`), `test_ops_retention.py` (joins the compression thread, and now checks a `.gz` archive exists) and `test_logging_rotation.py` (rollover made due instead of waiting 1.1 s, and now checks the rotated file); nested `asyncio.run` replaced by `await` in 4 files; the record-CLI polling test runs on `FakeClock`. Test-only change: 1,040 tests, coverage 96.30%, no module below its baseline.
- Phases 4a/4b (T1): 20 legacy flat test files now live in the mirrored layout. 4a renamed 12 unchanged (e.g. `test_jito_sdk.py` → `unit/sdk/test_jito.py`, `test_geyser_stream.py` → `unit/streams/test_geyser.py`; new `unit/strategies/`, `unit/streams/`, `unit/services/` packages). 4b merged 8 into the mirrored file that already existed (e.g. `test_rpc_pool.py` → `unit/infra/test_rpc_pool.py`, `test_ops_cli.py` → `unit/cli/test_main.py`). Test-only change: 1,040 tests, coverage 96.30%, no module below its baseline.
- Phases 5–7 (T1, T4): the 7 `*_integration.py` files moved to the new `tests/integration/` package, and the 15 mixed legacy files were split test by test into the mirrored module files (e.g. `test_risk_health_execution.py` → `unit/bot/test_risk.py`, `test_health.py`, `test_lifecycle.py`, `unit/execution/test_builder.py`, `unit/strategies/test_risk_validation.py`). New mirrored files for `bot/alerts`, `bot/persistence`, `bot/health`, `bot/lifecycle`, `cli/bot`, `cli/replay`, `cli/arbitrage`, `config/env`, `engines/generators`, `execution/liquidator`, `execution/builder`, `execution/arbitrage`, `ops/monitoring`, `storage/status` and seven `strategies/` modules; shared executor fixtures in `unit/execution/conftest.py`. 91 inline `TradingBotConfig(...)` calls in the moved files now use `make_config` (behaviour-identical: `dry_run=False` stated where it wasn't set) and four local pool-key helpers use `make_pool_keys`. The interim `*_integration.py` marker rule was removed from `conftest.py`. Test-only change: 1,040 tests (986 unit, 54 integration), coverage 96.30%, no module below its baseline; 21 legacy flat files remain for Sprint 27.

### Tests (Sprint 27: T2, T3, T5, T6, T9, branch `sprint-27-test-consolidation`)
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

### Release record – Unreleased
- Sprint 24D (branch `sprint-24d-income-ops`): operator pause, unattended alerts, profit sweep (off by default), `deploy/` templates, BUG-110; 1,321 tests, coverage 96.38%, green on 3.12, 3.13, 3.14; ruff, black, mypy clean. Touches the entry gate (pause) and, only when enabled, wallet transfers. Needs the RUNBOOK §7 pause / sweep / supervisor drills on paper before Stage 1
- Stage 0 fixes (branch `fix/stage0-bugs-104-107`): BUG-104…107 fixed; 1,183 tests, coverage 96.30%, green on 3.12, 3.13, 3.14. Money path changed (paper pricing, buy refusal on non-standard curves), so the next Stage 0 is a full 72 h run on a new tag with an empty `data/`.
- Entry hardening (branch `fix/stage0-entry-hardening`): BUG-108, BUG-109, paper latency penalty, screening records; 1,218 tests, coverage 96.29%, green on 3.12, 3.13, 3.14. Money path changed (which tokens are bought, paper fills), so it needs a full 72 h Stage 0
- Commit: – (Sprint 24C merged as `0ab1ae0`; Sprint 25 on branch `sprint-25-packaging-hygiene`, not merged)
- Release gate: PASS (`nox -s lint mypy tests package`; `tests` green on 3.12, 3.13 and 3.14 locally, 3.11 only in CI)
- Tests: 1004 collected, all passed; coverage 96.29% (statement + branch)
- Replay parity: tooling added; not yet run on a live capture
- Capital stage after this release: unchanged (0). BUG-102 touches logging/telemetry only; the trading path is unchanged, so a 24h Stage 0 re-run is enough

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

[Unreleased]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/andy-shady-org/pumpfun-trading/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/andy-shady-org/pumpfun-trading/tree/v0.1.0
