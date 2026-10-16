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

### Changed
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

### Fixed
- **BUG-103:** `ReplayRecorder.close()` could lose the last batch on shutdown. It cancelled the flush worker while that batch, already taken off the queue, was waiting for its `asyncio.to_thread` write; the cancel also cancelled the write if the thread hadn't started it yet, or closed the sink under a running write. The write is now shielded and finished (and counted) before the cancel is honoured, so `--record-replay` captures and `pumpfun-recorder` keep every record up to shutdown. Found by `unit/cli/test_record.py::test_harvester_websocket_feed_closed_runs_until_duration` failing on Python 3.11 in CI; regression tests in `unit/bot/test_recorder.py`.
- Test `test_retention_sink_and_manager_edge_branches` failed on Python 3.12/3.13: it mocked `Path.stat` globally, which `Path.glob` uses before 3.14. It now fakes only the measured file's size (found by the new interpreter matrix; test-only change).

### Release record – Unreleased
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
