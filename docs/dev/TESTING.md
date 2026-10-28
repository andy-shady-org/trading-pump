# Test Architecture & Migration Plan

This document defines how the `pumpfun_trading` test suite is organised, the conventions every new test must follow, and the file-by-file plan for moving the current flat suite into that structure. The migration was scheduled as **Sprint 26 (Test Foundation)** and **Sprint 27 (Test Consolidation)**, both before the **Sprint 28** `bot/run.py` decomposition, so the restructured suite can act as its safety net. Both sprints are done and archived in [`DONE.md`](DONE.md#phase-5-platform-refactor-required-before-the-web-ui). The decision is recorded as ADR-008 in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md).

---

## 1. Principles

1. **Tests mirror the source.** The tests for `pumpfun_trading/<pkg>/<module>.py` live in `pumpfun_trading/tests/unit/<pkg>/test_<module>.py` (NOTES.md §3).
2. **Test behaviour, not coverage.** No file is organised by a coverage percentage. A failing test must point at a module and a behaviour.
3. **One source of truth for fixtures.** Configs, bots, positions, pool keys, payload bytes and key constants come from `tests/support/`; nothing is copied between files.
4. **Deterministic.** No real sleeps, network, or wall clock. Use `FakeClock`, fakes from `support/fakes.py`, and `await` instead of nested `asyncio.run`. `tests/conftest.py` blocks DNS for non-local hosts for the whole session, removes proxy variables, and points the status file, audit trail, `bot.log` and `events.jsonl` into the test's `tmp_path` (BUG-143); a test that enables alerts must capture them (`bot._send_alert = sent.append`), never post them.
5. **Regressions are linked to bugs.** Every resolved bug in [`BUGS.md`](BUGS.md) has at least one test tagged `@pytest.mark.regression("BUG-xx")`, placed beside the module it guards.
6. **Public seams first.** Tests drive `TradingBot` through public entry points (factory, handlers, controller), not private attributes, so the runtime can be refactored safely.
7. **Gates never move.** Coverage stays **≥ 95%** at every step; `fail_under` is never lowered.

---

## 2. Current-State Findings (T1–T9)

Snapshot at planning time: **65 files** (64 `test_*.py` + `conftest.py`), **~25,050 lines**, **581 tests**, covering **55 source modules**.

| # | Finding | Evidence |
|---|---|---|
| T1 | Flat layout that does not mirror the source | Everything in `pumpfun_trading/tests/`; no sub-packages; no 1:1 module correspondence. **Sprint 26 Phases 4–6:** 42 legacy files moved, merged or split into `unit/<pkg>/` and `integration/` (§6); the 21 files left in the tests root are the Sprint 27 ones (coverage padding, `_full` / `_regressions` pairs, themed regression files) |
| T2 | Six coverage-padding files (~7.1k lines) organised by coverage % | `test_coverage_95_comprehensive.py` (3,395 lines), `test_coverage_boost_v2.py` (1,984), `test_coverage_95_plus.py` (930), `test_coverage_95_final_push.py` (380), `test_coverage_boost_final.py` (298), `test_runtime_coverage_boost.py` (151). **Resolved in Sprint 27:** all six dissolved test by test into the module each test exercises most (§6); per-module coverage unchanged. No test was deleted, because every one still covers lines nothing else does. About 20 grab-bag tests keep coverage-style names (`test_final_coverage_push`, `test_bot_more_branches_push`, …); split them into named behaviour tests when their module is next changed (Sprint 28 extractions first) |
| T3 | Modules split across duplicate base / `_full` / `_regressions` files | `test_api_client.py` + `test_api_client_full.py`; `test_audit_tool.py` + `test_audit_full.py`; `test_execution_sdk.py` + `test_execution_sdk_full.py`; `test_bot_runtime_full.py` + `test_bot_runtime_regressions.py`. **Resolved in Sprint 27:** merged into `unit/api/test_client.py`, `unit/bot/test_audit.py` (new), `unit/sdk/test_execution.py` and `unit/bot/test_run.py`; clashing helpers were suffixed (e.g. `MINT_LAYOUT`) and duplicate helpers replaced by `support/` (`SAMPLE_MINT`, `WSOL_MINT`, `make_pool_keys`, `make_bot`) |
| T4 | Almost no shared fixtures; setup copied everywhere | 15 fixtures, one 58-line root `conftest.py`; `TradingBotConfig(` built inline **136** times; private-key constants redefined in **13** files; `make_bot` / `_make_bot`; three `make_*pool_keys` variants (`make_pool_keys`, `make_sample_pool_keys`, `make_test_pool_keys`). **Sprint 26 Phase 2:** `tests/support/` built (§3, §5) and the 16 private-key constants (four different values) replaced by `SAMPLE_PRIVATE_KEY`; the inline configs and old helpers are replaced file by file as later phases move them. **Phase 7:** in `unit/` and `integration/`, 91 of 94 inline configs now use `make_config` (calls that didn't set `dry_run` pass `dry_run=False`, so behaviour is unchanged) and all four pool-key helpers use `make_pool_keys`; `unit/execution/conftest.py` is the first package conftest. The rest (58 inline configs, `make_bot` / `_make_bot`) is in the Sprint 27 files |
| T5 | Tests coupled to the runtime monolith | **24** files import `pumpfun_trading.bot.run.TradingBot` and reach into private attributes. **Safety net added in Sprint 27:** `integration/test_golden_replay.py` drives a dry-run bot through its stream entry point (`_handle_message`) for four scenarios and compares every ledger row, the final positions, state and wallet balance with `integration/golden/*.json`; Sprint 28 must keep these unchanged. The private-attribute coupling itself goes away as Sprint 28–29 add public seams |
| T6 | Marker noise, no taxonomy | **216** redundant `@pytest.mark.asyncio` although `asyncio_mode = "auto"`; no `unit` / `integration` / `regression` / `slow` markers; no `--strict-markers`; `parametrize` used only twice. **Markers resolved in Sprint 26 Phase 1:** asyncio marks removed, taxonomy registered with `--strict-markers` and applied by directory (§4), `nox -s tests-fast` added. `parametrize` adoption stays with Sprint 27. **Sprint 27:** a scan for tests whose bodies differ only in literals found one pair (`unit/ops/test_redact.py`), now parametrized, plus the `format_uptime` assertion table; new tests use `parametrize` for tables (BUG-75, layout guard). Converting assertion tables inside grab-bag tests continues as they are split (T2) |
| T7 | Non-deterministic / slow tests | `time.sleep` in `test_anti_rug_filters.py`, `test_logging_rotation.py`, `test_ops_retention.py`; `asyncio.run` inside async-mode tests in `test_bugfixes_lifecycle_resilience.py`, `test_cross_venue_arbitrage.py`, `test_market_data_resilience.py`, `test_runtime_coverage_boost.py`; no fake clock. **Resolved in Sprint 26 Phase 3:** all removed; most of the suite's 136 s was real retry backoff on blocked-network lookups, now skipped by the `instant_retry_backoff` fixture in `tests/conftest.py` (full suite ~8 s) |
| T8 | Tests ship in the wheel | `[tool.setuptools.packages.find] include = ["pumpfun_trading*"]` matches `pumpfun_trading.tests`. **Resolved in Sprint 25:** `packages.find` exclude plus `MANIFEST.in` `prune pumpfun_trading/tests` (the exclude alone still packed tests as package data); checked by `nox -s package` |
| T9 | Regressions scattered by theme, not BUG ID | `test_*_regressions.py`, `test_bugfixes_*`; no way to check that every resolved bug has a test. **Resolved in Sprint 27:** 140 tests carry `regression("BUG-xx")` beside the module they guard (IDs taken from each test's docstring, comments or `test_bugNN_` name, plus hand-picked tags and three new tests for BUG-32, BUG-75 and BUG-88); `unit/test_suite_layout.py` fails if a RESOLVED bug in `BUGS.md` has no tagged test (5 known gaps listed, shrink-only) or a tag names an unknown bug (§5 Regressions) |

---

## 3. Target Layout

Tests stay inside the package (as AGENTS.md requires) but are excluded from the wheel (Sprint 25).

```text
pumpfun_trading/tests/
├── conftest.py            # env isolation (existing) + registers support fixtures
├── support/               # shared test code, never collected as tests
│   ├── __init__.py
│   ├── factories.py       # make_config(), make_bot(), make_position(), make_pool_keys()
│   ├── payloads.py        # curve account, trade / complete event, buy / sell instruction bytes
│   ├── fakes.py           # FakeClock, FakeRpc, FakeJito, FakeAlertSink
│   └── constants.py       # SAMPLE_PRIVATE_KEY, SAMPLE_RPC_URL, sample mints, initial curve reserves
├── unit/                  # 1:1 mirror: unit/<pkg>/test_<module>.py
│   ├── test_support.py    # tests of support/ itself (round-trips payloads through the real parsers)
│   ├── test_suite_layout.py  # layout guard + BUG regression-tag check
│   ├── api/  bot/  cli/  config/  engines/  execution/
│   ├── infra/  ops/  sdk/  services/  storage/
│   └── strategies/  streams/  ui/      (each with a package conftest.py)
├── integration/           # cross-component flows (bot + streams + execution), replay end-to-end
│   ├── test_golden_replay.py  # characterisation tests of TradingBot decisions
│   └── golden/            # expected decisions per scenario (JSON, reviewed like code)
└── property/              # Hypothesis (conftest.py: derandomized profile)
    ├── test_curve.py      # sdk/curve.py: bounds, monotonicity, fees, no-free-money round trip
    └── test_geyser_parsers.py  # streams/geyser.py: byte round trips, short / foreign buffers
```

### Mirror rule
| Source | Unit test |
|---|---|
| `pumpfun_trading/sdk/jito.py` | `tests/unit/sdk/test_jito.py` |
| `pumpfun_trading/bot/run.py` | `tests/unit/bot/test_run.py` |
| `pumpfun_trading/strategies/filters.py` | `tests/unit/strategies/test_filters.py` |

The **layout guard** (`tests/unit/test_suite_layout.py`, Sprint 27) asserts that every non-`__init__` source module has a `unit/` counterpart, that the tests root holds no `.py` file except `conftest.py`, that every `unit/<pkg>/` has an `__init__.py`, and that no test file has a coverage-style name. `unit/test_support.py` and the guard itself are the only files allowed directly in `unit/`.

---

## 4. Markers & Configuration

In place since Sprint 26 Phase 1 (`pyproject.toml`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["pumpfun_trading/tests"]
addopts = "-q --strict-markers"
markers = [
    "unit: fast, isolated test of one module (applied by directory)",
    "integration: cross-component flow, e.g. a TradingBot driven end to end (applied by directory)",
    "property: Hypothesis property test (applied by directory)",
    "regression(bug_id): guards a resolved bug from docs/dev/BUGS.md, e.g. regression(\"BUG-96\")",
    "slow: needs real waiting or heavy computation; excluded from `nox -s tests-fast`",
]
```

* `--strict-markers` makes a misspelt or unregistered marker a collection error. Register a new marker here before using it (Sprint 30 adds `postgres: requires a PostgreSQL database (opt-in)`).
* `unit` / `integration` / `property` are applied automatically by location in the root `conftest.py` (`pytest_collection_modifyitems`): `integration/` and `property/` get their own marker and everything else is `unit` (the interim rule for legacy flat `*_integration.py` files was removed once Phase 5 moved them). Never add these three by hand.
* `regression("BUG-xx")` and `slow` are added by hand on the test.
* Do **not** add `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles it (the 216 old marks were removed in Sprint 26 Phase 1).

---

## 5. Conventions

### Naming
* Files: `test_<module>.py`, one per source module. No `_full`, `_v2`, `_final`, `_boost`, or coverage-named files.
* Functions: `test_<unit>_<condition>_<expected>`, e.g. `test_calculate_tip_above_cap_clamps_to_max`.
* Group related tests with plain functions; classes only when sharing a fixture scope.

### Structure
* Arrange / Act / Assert, separated by a blank line.
* One behaviour per test; use `@pytest.mark.parametrize` for tables of cases.
* Assert on public results and emitted events, not private attributes.

### Fixtures: `support/` vs package `conftest.py`
| Use | When |
|---|---|
| `support/factories.py` | Building domain objects used by more than one package (`make_config(**overrides)`, `make_bot(...)`, `make_position(...)`, `make_pool_keys(...)`) |
| `support/fakes.py` | Replacing I/O boundaries (RPC, Jito, REST API, clock, alert sinks) |
| `support/payloads.py` | Building binary Geyser / curve / event payloads (offsets must match `streams/` parsers) |
| `support/constants.py` | Keys, mints and addresses reused across files |
| `unit/<pkg>/conftest.py` | Fixtures only that package's tests need |
| Root `conftest.py` | Environment isolation (status / audit paths, retry delays) only |

Import support code by its full path, e.g. `from pumpfun_trading.tests.support.factories import make_bot`, so every test file shares one copy of the module.

| Helper | What it gives you |
|---|---|
| `make_config(**overrides)` | `TradingBotConfig` with `buy_amount_sol=0.01`, `dry_run=True`; pass `dry_run=False` explicitly for live-path tests |
| `make_bot(tmp_path, *, config=None, bot_kwargs=None, **config_overrides)` | `TradingBot` with `SAMPLE_PRIVATE_KEY`; status and audit files under `tmp_path` |
| `make_position(bot_or_manager, mint, ...)` | Opens a position through `PositionManager.record_buy`, so the dict has the live shape |
| `make_pool_keys(mint, *, pc_mint, unique=True, **overrides)` | Raydium pool keys: fresh valid pubkeys (or `Pubkey.default()` with `unique=False`) and the real authority / Serum ids |
| `FakeClock` | `time()` / `monotonic()` / `sleep()`; `install(monkeypatch, module)` replaces that module's `time`, `install_async_sleep(monkeypatch, module)` makes its `asyncio.sleep` advance the clock without waiting. Both act per module, never globally |
| `FakeRpc().on(method, *answers)` | Stand-in for `RpcConnectionPool`: values become `result`, exceptions are raised, callables get the payload; an unregistered method fails the test; `calls` / `broadcasts` record traffic |
| `FakeJito(status=...)` / `FakeAlertSink()` | Record bundles / alert messages; bundle confirmation answers with `status` |
| `payloads.bonding_curve_bytes(...)` etc. | Account and event bytes in the exact `streams/geyser.py` / `sdk/execution.py` layout (creator at 49..81) |

### Regressions
```python
@pytest.mark.regression("BUG-55")
async def test_geyser_start_without_transport_raises_and_stays_disconnected():
    ...
```
* Put the test in the mirrored file of the module the fix lives in, never in a themed `*_regressions.py` file. One test may name several bugs: `regression("BUG-68", "BUG-69")`.
* When a bug is marked **RESOLVED** in `BUGS.md`, at least one test must carry its tag; `unit/test_suite_layout.py` reads the tags statically (AST) and fails otherwise. `KNOWN_UNTAGGED` in that file lists the 5 older bugs without a behaviour test (BUG-05, 09, 11, 20, 31) with the reason; it may only shrink.
* Tags must name a bug in the `BUGS.md` status table; tests for MITIGATED bugs may be tagged too.

### Characterisation (golden) tests
`integration/test_golden_replay.py` pins what the bot *decides* for fixed message sequences. A failure means a decision changed. If the change is intended, regenerate with `PUMPFUN_UPDATE_GOLDEN=1 pytest pumpfun_trading/tests/integration/test_golden_replay.py` and review the JSON diff in the PR like code. Refactors (Sprint 28) must leave the files unchanged.

### Property tests
Hypothesis tests live in `property/` and use the `deterministic` profile from `property/conftest.py` (derandomized, no example database), so CI and local runs see the same examples. `HYPOTHESIS_PROFILE=explore` searches with fresh seeds and more examples; turn any failure it finds into a fixed `@example` or a unit regression test.

---

## 6. Migration Map

Actions: **move** (rename/relocate, content unchanged), **split** (spread across several mirrored files), **merge** (combine with a sibling into one mirrored file), **dissolve** (each test moves to its module's file; trivia-only tests are deleted and replaced by behaviour tests).

| Current file | Lines | Tests | Target path(s) | Action | Sprint |
|---|---:|---:|---|---|---|
| `conftest.py` | 58 | – | `conftest.py` (kept) + `support/` | keep, extract helpers | 26 |
| `test_anti_rug_bot_integration.py` | 319 | 10 | `integration/test_anti_rug_bot.py` | move; **done** (26 / 5) | 26 |
| `test_anti_rug_filters.py` | 464 | 10 | `unit/strategies/test_filters.py` | move (remove `time.sleep`); **done** (26 / 4a) | 26 |
| `test_api_client.py` | 91 | 4 | `unit/api/test_client.py` | merge with `_full`; **done** (27) | 27 |
| `test_api_client_full.py` | 134 | 3 | `unit/api/test_client.py` | merge; **done** (27) | 27 |
| `test_audit_tool.py` | 167 | 6 | `unit/bot/test_audit.py`, `unit/cli/test_audit.py` | merge with `test_audit_full.py`; **done** (27) | 27 |
| `test_audit_full.py` | 199 | 4 | `unit/bot/test_audit.py` | merge; **done** (27) | 27 |
| `test_bot_runtime_full.py` | 355 | 7 | `unit/bot/test_run.py` | merge with `_regressions`; **done** (27) | 27 |
| `test_bot_runtime_regressions.py` | 206 | 8 | `unit/bot/test_risk.py`, `unit/bot/test_run.py` | split + tag `regression`; **done** (27) | 27 |
| `test_bot_subsystems.py` | 152 | 7 | `unit/bot/test_enrichment.py`, `unit/bot/test_persistence.py`, `unit/bot/test_alerts.py` | split; **done** (26 / 6) | 26 |
| `test_bugfixes_lifecycle_resilience.py` | 284 | 7 | `unit/bot/test_run.py`, `unit/ops/test_logging.py` | split + tag `regression` (remove `asyncio.run`); **done** (27) | 27 |
| `test_capital_displacement.py` | 242 | 4 | `unit/strategies/test_decision.py` (EV evaluator), `unit/bot/test_position_manager.py` (displacement engine), `unit/bot/test_run.py` (bot rotation) | merge; **done** (26 / 6) | 26 |
| `test_cli_suite.py` | 334 | 7 | `unit/cli/test_main.py`, `unit/cli/test_audit.py`, `unit/cli/test_replay.py`, `unit/cli/test_bot.py` | split; **done** (26 / 6) | 26 |
| `test_containment_regressions.py` | 118 | 4 | `unit/cli/test_arbitrage.py`, `unit/strategies/test_arbitrage.py`, `unit/streams/test_geyser.py` | split + tag `regression`; **done** (27) | 27 |
| `test_copy_trading.py` | 373 | 9 | `unit/strategies/test_copy_trading.py` | move; **done** (26 / 4a) | 26 |
| `test_copy_trading_bot_integration.py` | 246 | 5 | `integration/test_copy_trading_bot.py` | move; **done** (26 / 5) | 26 |
| `test_coverage_95_comprehensive.py` | 3,395 | 50 | `unit/bot/test_alerts.py`, `unit/bot/test_audit.py`, `unit/bot/test_position_manager.py`, `unit/bot/test_risk.py`, `unit/bot/test_run.py`, `unit/cli/test_arbitrage.py`, `unit/cli/test_events.py`, `unit/cli/test_main.py`, `unit/engines/test_optimizer.py`, `unit/engines/test_replay.py`, `unit/execution/test_arbitrage.py`, `unit/execution/test_executor.py`, `unit/infra/test_rpc_pool.py`, `unit/ops/test_events.py`, `unit/ops/test_logging.py`, `unit/ops/test_retention.py`, `unit/strategies/test_arbitrage.py`, `unit/strategies/test_cluster.py`, `unit/strategies/test_decision.py`, `unit/strategies/test_graduation.py`, `unit/strategies/test_presets.py`, `unit/ui/test_dashboard.py` | dissolve; **done** (27) | 27 |
| `test_coverage_95_final_push.py` | 380 | 6 | `unit/api/test_client.py`, `unit/bot/test_audit.py`, `unit/bot/test_run.py`, `unit/sdk/test_execution.py` | dissolve; **done** (27) | 27 |
| `test_coverage_95_plus.py` | 930 | 11 | `unit/api/test_client.py`, `unit/bot/test_run.py`, `unit/cli/test_main.py`, `unit/execution/test_liquidator.py`, `unit/sdk/test_execution.py` | dissolve; **done** (27) | 27 |
| `test_coverage_boost_final.py` | 298 | 6 | `unit/api/test_client.py`, `unit/bot/test_run.py`, `unit/cli/test_main.py`, `unit/sdk/test_execution.py` | dissolve; **done** (27) | 27 |
| `test_coverage_boost_v2.py` | 1,984 | 22 | `unit/api/test_client.py`, `unit/bot/test_alerts.py`, `unit/bot/test_event_router.py`, `unit/bot/test_persistence.py`, `unit/bot/test_position_manager.py`, `unit/bot/test_run.py`, `unit/execution/test_executor.py`, `unit/execution/test_liquidator.py`, `unit/infra/test_rpc_pool.py`, `unit/sdk/test_execution.py`, `unit/sdk/test_raydium.py`, `unit/strategies/test_copy_trading.py`, `unit/strategies/test_graduation.py`, `unit/strategies/test_signal.py` | dissolve; **done** (27) | 27 |
| `test_cross_venue_arbitrage.py` | 386 | 8 | `unit/strategies/test_arbitrage.py`, `unit/execution/test_arbitrage.py`, `unit/strategies/test_presets.py`, `unit/cli/test_arbitrage.py`, `unit/engines/test_replay.py` (pool-key helper replaced by `make_pool_keys`) | split (remove `asyncio.run`); **done** (26 / 6) | 26 |
| `test_curve_math.py` | 215 | 7 | `unit/sdk/test_curve.py` (+ `property/test_curve.py`) | move, add properties; **done** (26 / 4a) | 26 / 27 (properties done in 27) |
| `test_diagnostic_events.py` | 174 | 4 | `unit/ops/test_events.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_dynamic_execution_policy.py` | 245 | 5 | `unit/execution/test_policy.py` | move; **done** (26 / 4a) | 26 |
| `test_events_cli.py` | 186 | 4 | `unit/cli/test_events.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_execution_sdk.py` | 148 | 12 | `unit/sdk/test_execution.py` | merge with `_full`; **done** (27) | 27 |
| `test_execution_sdk_full.py` | 344 | 5 | `unit/sdk/test_execution.py` | merge; **done** (27) | 27 |
| `test_funding_cluster_and_sybil.py` | 444 | 12 | `unit/strategies/test_cluster.py` | move; **done** (26 / 4a) | 26 |
| `test_geyser_bot_integration.py` | 600 | 11 | `integration/test_geyser_bot.py` | move; **done** (26 / 5) | 26 |
| `test_geyser_stream.py` | 534 | 14 | `unit/streams/test_geyser.py` (+ `property/test_geyser_parsers.py`) | move, add properties; **done** (26 / 4a) | 26 / 27 (properties done in 27) |
| `test_graduation_bot_integration.py` | 197 | 5 | `integration/test_graduation_bot.py` | move; **done** (26 / 5) | 26 |
| `test_graduation_harvester.py` | 258 | 5 | `unit/strategies/test_graduation.py`, `unit/strategies/test_exits.py` | split; **done** (26 / 6) | 26 |
| `test_jito_execution_integration.py` | 358 | 14 | `integration/test_jito_execution.py` | move; **done** (26 / 5) | 26 |
| `test_jito_sdk.py` | 507 | 17 | `unit/sdk/test_jito.py` | move; **done** (26 / 4a) | 26 |
| `test_logging_rotation.py` | 80 | 4 | `unit/ops/test_logging.py` | move (remove `time.sleep`); **done** (26 / 4a) | 26 |
| `test_market_data_resilience.py` | 56 | 3 | `unit/services/test_market_data.py` | move (remove `asyncio.run`); **done** (26 / 4a) | 26 |
| `test_market_recorder.py` | 786 | 23 | `unit/bot/test_recorder.py`, `unit/cli/test_record.py`, `unit/engines/test_generators.py`, `unit/engines/test_replay.py`, `integration/test_recorder_replay.py` | split; **done** (26 / 6) | 26 |
| `test_momentum_bot_integration.py` | 248 | 5 | `integration/test_momentum_bot.py` | move; **done** (26 / 5) | 26 |
| `test_ops_cli.py` | 50 | 2 | `unit/cli/test_main.py` | merge; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_ops_readiness.py` | 92 | 3 | `unit/config/test_env.py`, `unit/ops/test_monitoring.py` | split; **done** (26 / 6) | 26 |
| `test_ops_retention.py` | 134 | 6 | `unit/ops/test_retention.py` | move (remove `time.sleep`); **done** (26 / 4b, merged into the existing file) | 26 |
| `test_order_executor.py` | 518 | 15 | `unit/execution/test_executor.py`, `unit/execution/test_liquidator.py` (shared fixtures in `unit/execution/conftest.py`), `unit/bot/test_run.py` | split; **done** (26 / 6) | 26 |
| `test_order_flow_momentum.py` | 375 | 12 | `unit/strategies/test_momentum.py` | move; **done** (26 / 4a) | 26 |
| `test_persistence_cache_regressions.py` | 143 | 6 | `unit/config/test_env.py`, `unit/storage/test_status.py`, `unit/strategies/test_filters.py`, `unit/strategies/test_momentum.py`, `unit/strategies/test_risk_validation.py` | split + tag `regression`; **done** (27) | 27 |
| `test_portfolio_circuit_breaker.py` | 702 | 14 | `unit/bot/test_risk.py`; preset test → `unit/strategies/test_presets.py` | merge; **done** (26 / 6) | 26 |
| `test_position_manager.py` | 414 | 12 | `unit/bot/test_position_manager.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_pump_instruction_layout.py` | 208 | 6 | `unit/sdk/test_execution.py` | merge; **done** (27) | 27 |
| `test_raydium_execution.py` | 258 | 5 | `unit/sdk/test_raydium.py` | move; **done** (26 / 4a) | 26 |
| `test_raydium_graduation.py` | 230 | 5 | `unit/strategies/test_graduation.py` (local pool-key helper replaced by `make_pool_keys`) | merge; **done** (26 / 6) | 26 |
| `test_replay_engine.py` | 443 | 9 | `unit/engines/test_replay.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_risk_adaptive_ratchet.py` | 374 | 9 | `unit/bot/test_risk.py` | merge; **done** (26 / 6) | 26 |
| `test_risk_health_execution.py` | 440 | 8 | `unit/bot/test_risk.py`, `unit/bot/test_health.py`, `unit/bot/test_lifecycle.py`, `unit/execution/test_builder.py`, `unit/strategies/test_risk_validation.py` | split; **done** (26 / 6) | 26 |
| `test_rpc_pool.py` | 360 | 11 | `unit/infra/test_rpc_pool.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_rpc_pool_bot_integration.py` | 175 | 3 | `integration/test_rpc_pool_bot.py` | move; **done** (26 / 5) | 26 |
| `test_runtime_coverage_boost.py` | 151 | 5 | `unit/config/test_env.py`, `unit/ops/test_logging.py`, `unit/services/test_market_data.py` | dissolve (remove `asyncio.run`); **done** (27) | 27 |
| `test_sdk_contract_regressions.py` | 321 | 17 | `unit/api/test_client.py`, `unit/infra/test_rpc_pool.py`, `unit/sdk/test_curve.py`, `unit/sdk/test_execution.py`, `unit/sdk/test_jito.py` | split + tag `regression`; **done** (27) | 27 |
| `test_strategy_data_regressions.py` | 122 | 9 | `unit/bot/test_enrichment.py`, `unit/bot/test_position_manager.py`, `unit/execution/test_liquidator.py`, `unit/sdk/test_raydium.py`, `unit/services/test_market_data.py`, `unit/strategies/test_cluster.py`, `unit/strategies/test_filters.py` | split + tag `regression`; **done** (27) | 27 |
| `test_strategy_modularity.py` | 401 | 10 | `unit/strategies/test_signal.py`, `test_risk_validation.py`, `test_decision.py`, `test_base.py`, `test_presets.py`; `unit/config/test_env.py`; `unit/services/test_market_data.py` | split; **done** (26 / 6) | 26 |
| `test_strategy_optimizer.py` | 583 | 14 | `unit/engines/test_optimizer.py` | move; **done** (26 / 4b, merged into the existing file) | 26 |
| `test_strategy_safety.py` | 353 | 10 | `unit/bot/test_strategy.py` | move; **done** (26 / 4a) | 26 |
| `test_tooling_regressions.py` | 216 | 9 | `unit/cli/test_events.py`, `unit/cli/test_record.py`, `unit/cli/test_replay.py`, `unit/engines/test_replay.py`, `unit/ops/test_retention.py` | split + tag `regression`; **done** (27) | 27 |
| `test_trailing_and_tiered_exits.py` | 739 | 22 | `unit/strategies/test_exits.py`, `unit/strategies/test_presets.py`, `unit/bot/test_risk.py`, `unit/bot/test_run.py` | split; **done** (26 / 6) | 26 |
| `test_ui_and_storage.py` | 753 | 11 | `unit/ui/test_dashboard.py`, `unit/storage/test_status.py` | split; **done** (26 / 6) | 26 |

### Modules without a dedicated test file today
None. `unit/strategies/test_base.py` and `test_decision.py` were created in Sprint 26 Phase 6; `unit/bot/test_event_router.py` (from `test_coverage_boost_v2.py`) and `unit/cli/test_optimize.py` (moved out of `unit/engines/test_optimizer.py`) in Sprint 27. The layout guard (§3) now fails on any new source module without a mirrored test file.

---

## 7. Safety Protocol for Moving Tests

For **every** migration batch (one source package per PR):

1. **Before:** record `pytest --collect-only -q | tail -1` (test count) and `pytest --cov --cov-report=json:cov-before.json`.
2. Move / split / merge the files for that package only; replace inline setup with `support/` factories.
3. **After:** re-run both commands. The collected count must be **equal** (moves) or the difference must be explained in the PR (merged duplicates, trivia deletions with replacement behaviour tests).
4. Compare per-module coverage from the two JSON reports; **no module may drop**, and total coverage must stay **≥ 95%**.
5. Never lower `fail_under`; never add `# pragma: no cover` to compensate for a move.
6. Delete the original file in the same PR so no test runs twice.

---

## 8. Running Tests

| Command | Purpose |
|---|---|
| `nox -s tests` | Full suite with coverage gate (CI) |
| `nox -s tests-fast` | `-m "not slow and not integration"` for the inner loop (Sprint 26) |
| `pytest pumpfun_trading/tests/unit/sdk` | One package |
| `pytest pumpfun_trading/tests/unit/sdk/test_jito.py` | One module |
| `pytest -m regression` | All bug regressions |
| `pytest -m integration` | Cross-component flows only |
| `pytest -m property` | Hypothesis property tests (`HYPOTHESIS_PROFILE=explore` for a wider random search) |
| `PUMPFUN_UPDATE_GOLDEN=1 pytest pumpfun_trading/tests/integration/test_golden_replay.py` | Regenerate golden decisions after an intended behaviour change |
