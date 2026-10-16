# Test Architecture & Migration Plan

This document defines how the `pumpfun_trading` test suite is organised, the conventions every new test must follow, and the file-by-file plan for moving the current flat suite into that structure. The migration is scheduled in [`TODO.md`](TODO.md) as **Sprint 26 (Test Foundation)** and **Sprint 27 (Test Consolidation)**, both before the **Sprint 28** `bot/run.py` decomposition, so the restructured suite can act as its safety net. The decision is recorded as ADR-008 in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md).

---

## 1. Principles

1. **Tests mirror the source.** The tests for `pumpfun_trading/<pkg>/<module>.py` live in `pumpfun_trading/tests/unit/<pkg>/test_<module>.py` (NOTES.md §3).
2. **Test behaviour, not coverage.** No file is organised by a coverage percentage. A failing test must point at a module and a behaviour.
3. **One source of truth for fixtures.** Configs, bots, positions, pool keys, payload bytes and key constants come from `tests/support/`; nothing is copied between files.
4. **Deterministic.** No real sleeps, network, or wall clock. Use `FakeClock`, fakes from `support/fakes.py`, and `await` instead of nested `asyncio.run`.
5. **Regressions are linked to bugs.** Every resolved bug in [`BUGS.md`](BUGS.md) has at least one test tagged `@pytest.mark.regression("BUG-xx")`, placed beside the module it guards.
6. **Public seams first.** Tests drive `TradingBot` through public entry points (factory, handlers, controller), not private attributes, so the runtime can be refactored safely.
7. **Gates never move.** Coverage stays **≥ 95%** at every step; `fail_under` is never lowered.

---

## 2. Current-State Findings (T1–T9)

Snapshot at planning time: **65 files** (64 `test_*.py` + `conftest.py`), **~25,050 lines**, **581 tests**, covering **55 source modules**.

| # | Finding | Evidence |
|---|---|---|
| T1 | Flat layout that does not mirror the source | Everything in `pumpfun_trading/tests/`; no sub-packages; no 1:1 module correspondence |
| T2 | Six coverage-padding files (~7.1k lines) organised by coverage % | `test_coverage_95_comprehensive.py` (3,395 lines), `test_coverage_boost_v2.py` (1,984), `test_coverage_95_plus.py` (930), `test_coverage_95_final_push.py` (380), `test_coverage_boost_final.py` (298), `test_runtime_coverage_boost.py` (151) |
| T3 | Modules split across duplicate base / `_full` / `_regressions` files | `test_api_client.py` + `test_api_client_full.py`; `test_audit_tool.py` + `test_audit_full.py`; `test_execution_sdk.py` + `test_execution_sdk_full.py`; `test_bot_runtime_full.py` + `test_bot_runtime_regressions.py` |
| T4 | Almost no shared fixtures; setup copied everywhere | 15 fixtures, one 58-line root `conftest.py`; `TradingBotConfig(` built inline **136** times; private-key constants redefined in **13** files; `make_bot` / `_make_bot`; three `make_*pool_keys` variants (`make_pool_keys`, `make_sample_pool_keys`, `make_test_pool_keys`) |
| T5 | Tests coupled to the runtime monolith | **24** files import `pumpfun_trading.bot.run.TradingBot` and reach into private attributes |
| T6 | Marker noise, no taxonomy | **216** redundant `@pytest.mark.asyncio` although `asyncio_mode = "auto"`; no `unit` / `integration` / `regression` / `slow` markers; no `--strict-markers`; `parametrize` used only twice |
| T7 | Non-deterministic / slow tests | `time.sleep` in `test_anti_rug_filters.py`, `test_logging_rotation.py`, `test_ops_retention.py`; `asyncio.run` inside async-mode tests in `test_bugfixes_lifecycle_resilience.py`, `test_cross_venue_arbitrage.py`, `test_market_data_resilience.py`, `test_runtime_coverage_boost.py`; no fake clock |
| T8 | Tests ship in the wheel | `[tool.setuptools.packages.find] include = ["pumpfun_trading*"]` matches `pumpfun_trading.tests` |
| T9 | Regressions scattered by theme, not BUG ID | `test_*_regressions.py`, `test_bugfixes_*`; no way to check that every resolved bug has a test |

---

## 3. Target Layout

Tests stay inside the package (as AGENTS.md requires) but are excluded from the wheel (Sprint 25).

```text
pumpfun_trading/tests/
├── conftest.py            # env isolation (existing) + registers support fixtures
├── support/               # shared test code, never collected as tests
│   ├── __init__.py
│   ├── factories.py       # make_config(), make_bot(), make_position(), make_pool_keys()
│   ├── payloads.py        # Geyser / curve / trade / complete-event byte builders
│   ├── fakes.py           # FakeRpc, FakeJito, FakeClock, FakeAlertSink, FakeApiClient
│   └── constants.py       # SAMPLE_PRIVATE_KEY, OFFLINE_CREATOR, sample mints
├── unit/                  # 1:1 mirror: unit/<pkg>/test_<module>.py
│   ├── api/  bot/  cli/  config/  engines/  execution/
│   ├── infra/  ops/  sdk/  services/  storage/
│   └── strategies/  streams/  ui/      (each with a package conftest.py)
├── integration/           # cross-component flows (bot + streams + execution), replay end-to-end
└── property/              # Hypothesis: sdk/curve math, streams parsers
```

### Mirror rule
| Source | Unit test |
|---|---|
| `pumpfun_trading/sdk/jito.py` | `tests/unit/sdk/test_jito.py` |
| `pumpfun_trading/bot/run.py` | `tests/unit/bot/test_run.py` |
| `pumpfun_trading/strategies/filters.py` | `tests/unit/strategies/test_filters.py` |

A **layout guard test** (Sprint 27, `tests/unit/test_layout.py`) asserts that every non-`__init__` source module has a `unit/` counterpart and that the tests root contains only `conftest.py` and the four directories above.

---

## 4. Markers & Configuration

Planned for Sprint 26 in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["pumpfun_trading/tests"]
asyncio_mode = "auto"
addopts = "-q --strict-markers"
markers = [
  "unit: fast, isolated test of one module",
  "integration: cross-component flow",
  "regression(bug_id): guards a resolved bug in docs/dev/BUGS.md",
  "slow: takes more than ~1s",
  "property: Hypothesis property-based test",
  "postgres: requires a PostgreSQL database (opt-in, Sprint 30)",
]
```

* `unit` / `integration` / `property` are applied automatically by directory in the package `conftest.py` files.
* Do **not** add `@pytest.mark.asyncio`; `asyncio_mode = "auto"` handles it.

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

### Regressions
```python
@pytest.mark.regression("BUG-55")
async def test_geyser_start_without_transport_raises_and_stays_disconnected():
    ...
```

---

## 6. Migration Map

Actions: **move** (rename/relocate, content unchanged), **split** (spread across several mirrored files), **merge** (combine with a sibling into one mirrored file), **dissolve** (each test moves to its module's file; trivia-only tests are deleted and replaced by behaviour tests).

| Current file | Lines | Tests | Target path(s) | Action | Sprint |
|---|---:|---:|---|---|---|
| `conftest.py` | 58 | – | `conftest.py` (kept) + `support/` | keep, extract helpers | 26 |
| `test_anti_rug_bot_integration.py` | 319 | 10 | `integration/test_anti_rug_bot.py` | move | 26 |
| `test_anti_rug_filters.py` | 464 | 10 | `unit/strategies/test_filters.py` | move (remove `time.sleep`) | 26 |
| `test_api_client.py` | 91 | 4 | `unit/api/test_client.py` | merge with `_full` | 27 |
| `test_api_client_full.py` | 134 | 3 | `unit/api/test_client.py` | merge | 27 |
| `test_audit_tool.py` | 167 | 6 | `unit/bot/test_audit.py` | merge with `test_audit_full.py` | 27 |
| `test_audit_full.py` | 199 | 4 | `unit/bot/test_audit.py` | merge | 27 |
| `test_bot_runtime_full.py` | 355 | 7 | `unit/bot/test_run.py` | merge with `_regressions` | 27 |
| `test_bot_runtime_regressions.py` | 206 | 8 | `unit/bot/test_run.py`, `unit/bot/test_lifecycle.py`, `unit/bot/test_risk.py` | split + tag `regression` | 27 |
| `test_bot_subsystems.py` | 152 | 7 | `unit/bot/test_alerts.py`, `unit/bot/test_enrichment.py`, `unit/bot/test_persistence.py` | split | 26 |
| `test_bugfixes_lifecycle_resilience.py` | 284 | 7 | `unit/bot/test_run.py`, `unit/ops/test_logging.py`, `unit/storage/test_status.py` | split + tag `regression` (remove `asyncio.run`) | 27 |
| `test_capital_displacement.py` | 242 | 4 | `unit/bot/test_position_manager.py` | merge | 26 |
| `test_cli_suite.py` | 334 | 7 | `unit/cli/test_main.py`, `unit/cli/test_audit.py`, `unit/cli/test_bot.py`, `unit/cli/test_replay.py` | split | 26 |
| `test_containment_regressions.py` | 118 | 4 | `unit/cli/test_arbitrage.py`, `unit/execution/test_arbitrage.py`, `unit/strategies/test_arbitrage.py` | split + tag `regression` | 27 |
| `test_copy_trading.py` | 373 | 9 | `unit/strategies/test_copy_trading.py` | move | 26 |
| `test_copy_trading_bot_integration.py` | 246 | 5 | `integration/test_copy_trading_bot.py` | move | 26 |
| `test_coverage_95_comprehensive.py` | 3,395 | 50 | module files across `unit/bot`, `unit/cli`, `unit/engines`, `unit/execution`, `unit/ops`, `unit/sdk`, `unit/strategies`, `unit/streams`, `unit/ui` | dissolve | 27 |
| `test_coverage_95_final_push.py` | 380 | 6 | `unit/api/test_client.py`, `unit/bot/test_audit.py`, `unit/bot/test_run.py`, `unit/sdk/test_execution.py` | dissolve | 27 |
| `test_coverage_95_plus.py` | 930 | 11 | `unit/api/test_client.py`, `unit/bot/test_lifecycle.py`, `unit/bot/test_run.py`, `unit/cli/*`, `unit/sdk/test_execution.py` | dissolve | 27 |
| `test_coverage_boost_final.py` | 298 | 6 | `unit/api/test_client.py`, `unit/bot/test_run.py`, `unit/cli/*`, `unit/sdk/test_execution.py` | dissolve | 27 |
| `test_coverage_boost_v2.py` | 1,984 | 22 | module files across `unit/bot`, `unit/config`, `unit/execution`, `unit/infra`, `unit/sdk`, `unit/strategies`, `unit/streams` | dissolve | 27 |
| `test_cross_venue_arbitrage.py` | 386 | 8 | `unit/strategies/test_arbitrage.py`, `unit/execution/test_arbitrage.py`, `integration/test_arbitrage_replay.py` | split (remove `asyncio.run`) | 26 |
| `test_curve_math.py` | 215 | 7 | `unit/sdk/test_curve.py` (+ `property/test_curve_properties.py`) | move, add properties | 26 / 27 |
| `test_diagnostic_events.py` | 174 | 4 | `unit/ops/test_events.py` | move | 26 |
| `test_dynamic_execution_policy.py` | 245 | 5 | `unit/execution/test_policy.py` | move | 26 |
| `test_events_cli.py` | 186 | 4 | `unit/cli/test_events.py` | move | 26 |
| `test_execution_sdk.py` | 148 | 12 | `unit/sdk/test_execution.py` | merge with `_full` | 27 |
| `test_execution_sdk_full.py` | 344 | 5 | `unit/sdk/test_execution.py` | merge | 27 |
| `test_funding_cluster_and_sybil.py` | 444 | 12 | `unit/strategies/test_cluster.py` | move | 26 |
| `test_geyser_bot_integration.py` | 600 | 11 | `integration/test_geyser_bot.py` | move | 26 |
| `test_geyser_stream.py` | 534 | 14 | `unit/streams/test_geyser.py` (+ `property/test_geyser_parsers.py`) | move, add properties | 26 / 27 |
| `test_graduation_bot_integration.py` | 197 | 5 | `integration/test_graduation_bot.py` | move | 26 |
| `test_graduation_harvester.py` | 258 | 5 | `unit/strategies/test_graduation.py`, `unit/strategies/test_exits.py` | split | 26 |
| `test_jito_execution_integration.py` | 358 | 14 | `integration/test_jito_execution.py` | move | 26 |
| `test_jito_sdk.py` | 507 | 17 | `unit/sdk/test_jito.py` | move | 26 |
| `test_logging_rotation.py` | 80 | 4 | `unit/ops/test_logging.py` | move (remove `time.sleep`) | 26 |
| `test_market_data_resilience.py` | 56 | 3 | `unit/services/test_market_data.py` | move (remove `asyncio.run`) | 26 |
| `test_market_recorder.py` | 786 | 23 | `unit/bot/test_recorder.py`, `unit/engines/test_generators.py`, `unit/cli/test_record.py`, `integration/test_recorder_replay.py` | split | 26 |
| `test_momentum_bot_integration.py` | 248 | 5 | `integration/test_momentum_bot.py` | move | 26 |
| `test_ops_cli.py` | 50 | 2 | `unit/cli/test_main.py` | merge | 26 |
| `test_ops_readiness.py` | 92 | 3 | `unit/ops/test_monitoring.py`, `unit/config/test_env.py` | split | 26 |
| `test_ops_retention.py` | 134 | 6 | `unit/ops/test_retention.py` | move (remove `time.sleep`) | 26 |
| `test_order_executor.py` | 518 | 15 | `unit/execution/test_executor.py`, `unit/execution/test_liquidator.py` | split | 26 |
| `test_order_flow_momentum.py` | 375 | 12 | `unit/strategies/test_momentum.py` | move | 26 |
| `test_persistence_cache_regressions.py` | 143 | 6 | `unit/bot/test_persistence.py`, `unit/storage/test_status.py`, `unit/strategies/test_filters.py` | split + tag `regression` | 27 |
| `test_portfolio_circuit_breaker.py` | 702 | 14 | `unit/bot/test_risk.py` | merge | 26 |
| `test_position_manager.py` | 414 | 12 | `unit/bot/test_position_manager.py` | move | 26 |
| `test_pump_instruction_layout.py` | 208 | 6 | `unit/sdk/test_execution.py` | merge | 27 |
| `test_raydium_execution.py` | 258 | 5 | `unit/sdk/test_raydium.py` | move | 26 |
| `test_raydium_graduation.py` | 230 | 5 | `unit/strategies/test_graduation.py` | merge | 26 |
| `test_replay_engine.py` | 443 | 9 | `unit/engines/test_replay.py` | move | 26 |
| `test_risk_adaptive_ratchet.py` | 374 | 9 | `unit/bot/test_risk.py` | merge | 26 |
| `test_risk_health_execution.py` | 440 | 8 | `unit/bot/test_health.py`, `unit/bot/test_lifecycle.py`, `unit/execution/test_builder.py`, `unit/strategies/test_risk_validation.py` | split | 26 |
| `test_rpc_pool.py` | 360 | 11 | `unit/infra/test_rpc_pool.py` | move | 26 |
| `test_rpc_pool_bot_integration.py` | 175 | 3 | `integration/test_rpc_pool_bot.py` | move | 26 |
| `test_runtime_coverage_boost.py` | 151 | 5 | `unit/config/test_env.py`, `unit/ops/test_logging.py`, `unit/services/test_market_data.py` | dissolve (remove `asyncio.run`) | 27 |
| `test_sdk_contract_regressions.py` | 321 | 17 | `unit/sdk/test_curve.py`, `unit/sdk/test_execution.py`, `unit/sdk/test_jito.py`, `unit/infra/test_rpc_pool.py`, `unit/api/test_client.py` | split + tag `regression` | 27 |
| `test_strategy_data_regressions.py` | 122 | 9 | `unit/strategies/test_filters.py`, `unit/strategies/test_cluster.py`, `unit/bot/test_enrichment.py`, `unit/execution/test_liquidator.py` | split + tag `regression` | 27 |
| `test_strategy_modularity.py` | 401 | 10 | `unit/strategies/test_signal.py`, `unit/strategies/test_exits.py`, `unit/strategies/test_presets.py`, `unit/strategies/test_risk_validation.py` | split | 26 |
| `test_strategy_optimizer.py` | 583 | 14 | `unit/engines/test_optimizer.py` | move | 26 |
| `test_strategy_safety.py` | 353 | 10 | `unit/bot/test_strategy.py` | move | 26 |
| `test_tooling_regressions.py` | 216 | 9 | `unit/cli/test_main.py`, `unit/cli/test_record.py`, `unit/cli/test_replay.py`, `unit/ops/test_retention.py` | split + tag `regression` | 27 |
| `test_trailing_and_tiered_exits.py` | 739 | 22 | `unit/strategies/test_exits.py`, `unit/bot/test_risk.py` | split | 26 |
| `test_ui_and_storage.py` | 753 | 11 | `unit/ui/test_dashboard.py`, `unit/storage/test_status.py` | split | 26 |

### Modules without a dedicated test file today
Created in Sprint 27 (layout guard requires them): `unit/bot/test_event_router.py`, `unit/cli/test_optimize.py`, `unit/strategies/test_base.py`, `unit/strategies/test_decision.py`. Tests for these currently live inside coverage-padding or integration files and move here when those are dissolved.

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
| `pytest -m property` | Hypothesis property tests |
