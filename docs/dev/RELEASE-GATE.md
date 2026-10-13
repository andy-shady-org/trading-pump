# Pre-Production Release Gate & Verification Framework

This document defines the strict, quantitative release gates required before any controlled deployment or capital allocation. Every gate is designed to maximize expected value, eliminate avoidable failure modes, protect capital reserves, and guarantee operational determinism under volatile market conditions.

---

## 1. Release Status & Staging Policy

- **Current Status:** Internal Pre-Production Candidate (Stage 3 Verification).
- **Execution Mandate:** Strictly non-funded execution (paper-trading or dry-run) until all 7 gates achieve 100% verified compliance.
- **Target Deployment:** Controlled single-instance runtime operating within hard-coded capital and drawdown boundaries.
- **Execution Environment Layout:**
  - **Working Directory:** `runtime/` (all test execution, background pilots, and CLI auditing run from the `runtime` root).
  - **Configuration Directory:** `configs/` (under `runtime/configs/` containing structured JSON profiles for all testing scenarios).
  - **Outputs & Telemetry Directory:** `test-data/` (under `runtime/test-data/` receiving runtime status snapshots `test-data/bot_status.json`, audit records `test-data/audit_trail.jsonl`, and replay captures `test-data/historical_captures.jsonl`).

---

## 2. Gate Overview & Flow

```
[ Gate 0: Code Quality & Unit Coverage ]
                   │
                   ▼
[ Gate 1: Strategy Benchmark & Historical Replay ]
                   │
                   ▼
[ Gate 2: Risk Controls, Exits & Circuit Breakers ]
                   │
                   ▼
[ Gate 3: Network Infrastructure, RPC & MEV Bundling ]
                   │
                   ▼
[ Gate 4: Security, Secrets & Wallet Isolation ]
                   │
                   ▼
[ Gate 5: Persistence, State Restoration & Audit Trail ]
                   │
                   ▼
[ Gate 6: 72-Hour Continuous Live Paper Pilot ]
                   │
                   ▼
        [ Controlled Go / No-Go Signoff ]
```

---

## 3. Detailed Gate Specifications & Verification Runbook

### Gate 0: Code Hygiene, Static Analysis & Test Coverage

Ensures the codebase is free of syntax errors, type regressions, dead code, and unhandled branches, maintaining a high automated test coverage.

#### Verification Commands
```bash
# 1. Format and Linting Check
ruff check .

# 2. Strict Type Safety Analysis
mypy pumpfun_trading

# 3. Comprehensive Test Suite Execution with Coverage
pytest -v --cov=pumpfun_trading --cov-report=term-missing pumpfun_trading/tests
```
#### Gate 0 Results
```bash
(.venv) [13:21]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (241) $ ruff check .
All checks passed!
(.venv) [13:21]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (242) $ mypy pumpfun_trading
pumpfun_trading/tests/test_geyser_stream.py:317: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
pumpfun_trading/tests/test_geyser_stream.py:318: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
pumpfun_trading/tests/test_geyser_stream.py:319: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
pumpfun_trading/tests/test_geyser_stream.py:320: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
pumpfun_trading/tests/test_geyser_stream.py:321: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 97 source files
(.venv) [13:19]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (240) $ env -u PUMPFUN_STATUS_PATH -u PUMPFUN_AUDIT_LOG_PATH pytest -v --cov=pumpfun_trading --cov-report=term-missing pumpfun_trading/tests
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 310 items

pumpfun_trading/tests/test_anti_rug_bot_integration.py ..........                                                                                                                                                                                       [  3%]
pumpfun_trading/tests/test_anti_rug_filters.py ..........                                                                                                                                                                                               [  6%]
pumpfun_trading/tests/test_api_client.py ....                                                                                                                                                                                                           [  7%]
pumpfun_trading/tests/test_api_client_full.py ...                                                                                                                                                                                                       [  8%]
pumpfun_trading/tests/test_audit_full.py ...                                                                                                                                                                                                            [  9%]
pumpfun_trading/tests/test_audit_tool.py ....                                                                                                                                                                                                           [ 10%]
pumpfun_trading/tests/test_bot_runtime_full.py ......                                                                                                                                                                                                   [ 12%]
pumpfun_trading/tests/test_bot_subsystems.py .......                                                                                                                                                                                                    [ 15%]
pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py ....                                                                                                                                                                                        [ 16%]
pumpfun_trading/tests/test_cli_suite.py .......                                                                                                                                                                                                         [ 18%]
pumpfun_trading/tests/test_copy_trading.py .........                                                                                                                                                                                                    [ 21%]
pumpfun_trading/tests/test_copy_trading_bot_integration.py .....                                                                                                                                                                                        [ 23%]
pumpfun_trading/tests/test_coverage_95_final_push.py ......                                                                                                                                                                                             [ 25%]
pumpfun_trading/tests/test_coverage_95_plus.py .....                                                                                                                                                                                                    [ 26%]
pumpfun_trading/tests/test_coverage_boost_final.py ......                                                                                                                                                                                               [ 28%]
pumpfun_trading/tests/test_coverage_boost_v2.py ......................                                                                                                                                                                                  [ 35%]
pumpfun_trading/tests/test_execution_sdk.py ............                                                                                                                                                                                                [ 39%]
pumpfun_trading/tests/test_execution_sdk_full.py ....                                                                                                                                                                                                   [ 40%]
pumpfun_trading/tests/test_geyser_bot_integration.py ......                                                                                                                                                                                             [ 42%]
pumpfun_trading/tests/test_geyser_stream.py ..............                                                                                                                                                                                              [ 47%]
pumpfun_trading/tests/test_graduation_bot_integration.py .....                                                                                                                                                                                          [ 49%]
pumpfun_trading/tests/test_jito_execution_integration.py ..............                                                                                                                                                                                 [ 53%]
pumpfun_trading/tests/test_jito_sdk.py .................                                                                                                                                                                                                [ 59%]
pumpfun_trading/tests/test_market_data_resilience.py ...                                                                                                                                                                                                [ 60%]
pumpfun_trading/tests/test_momentum_bot_integration.py .....                                                                                                                                                                                            [ 61%]
pumpfun_trading/tests/test_ops_readiness.py ..                                                                                                                                                                                                          [ 62%]
pumpfun_trading/tests/test_order_executor.py ......                                                                                                                                                                                                     [ 64%]
pumpfun_trading/tests/test_order_flow_momentum.py ............                                                                                                                                                                                          [ 68%]
pumpfun_trading/tests/test_portfolio_circuit_breaker.py ...........                                                                                                                                                                                     [ 71%]
pumpfun_trading/tests/test_position_manager.py .......                                                                                                                                                                                                  [ 73%]
pumpfun_trading/tests/test_raydium_execution.py .....                                                                                                                                                                                                   [ 75%]
pumpfun_trading/tests/test_raydium_graduation.py .....                                                                                                                                                                                                  [ 77%]
pumpfun_trading/tests/test_replay_engine.py .......                                                                                                                                                                                                     [ 79%]
pumpfun_trading/tests/test_risk_health_execution.py ......                                                                                                                                                                                              [ 81%]
pumpfun_trading/tests/test_rpc_pool.py ...........                                                                                                                                                                                                      [ 84%]
pumpfun_trading/tests/test_rpc_pool_bot_integration.py ...                                                                                                                                                                                              [ 85%]
pumpfun_trading/tests/test_runtime_coverage_boost.py .........                                                                                                                                                                                          [ 88%]
pumpfun_trading/tests/test_strategy_modularity.py .........                                                                                                                                                                                             [ 91%]
pumpfun_trading/tests/test_strategy_safety.py ..........                                                                                                                                                                                                [ 94%]
pumpfun_trading/tests/test_trailing_and_tiered_exits.py .............                                                                                                                                                                                   [ 99%]
pumpfun_trading/tests/test_ui_and_storage.py ...                                                                                                                                                                                                        [100%]

====================================================================================================================== warnings summary =======================================================================================================================
pumpfun_trading/tests/test_coverage_boost_v2.py::test_final_coverage_push
  /opt/homebrew/Cellar/python@3.14/3.14.2/Frameworks/Python.framework/Versions/3.14/lib/python3.14/unittest/mock.py:2252: RuntimeWarning: coroutine 'TradingBot.start' was never awaited
    def __init__(self, name, parent):
  Enable tracemalloc to get traceback where the object was allocated.
  See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================================================================================================================= tests coverage ========================================================================================================================
______________________________________________________________________________________________________ coverage: platform darwin, python 3.14.2-final-0 _______________________________________________________________________________________________________

Name                                            Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------------------------------------
pumpfun_trading/__init__.py                         6      0      0      0   100%
pumpfun_trading/api/__init__.py                     2      0      0      0   100%
pumpfun_trading/api/client.py                     173      8     58      5    94%   47-48, 51, 96-97, 140-142, 284->286, 286->295, 289->291, 293->295
pumpfun_trading/bot/__init__.py                     6      0      0      0   100%
pumpfun_trading/bot/alerts.py                      75      1     28      1    98%   141
pumpfun_trading/bot/audit.py                      135      2     50      3    97%   35, 62->55, 184
pumpfun_trading/bot/enrichment.py                  78      1     30      5    94%   65->72, 101->116, 114, 139->138, 142->138
pumpfun_trading/bot/event_router.py                35      0     16      4    92%   46->exit, 50->exit, 54->exit, 63->exit
pumpfun_trading/bot/health.py                      28      0     12      1    98%   38->exit
pumpfun_trading/bot/lifecycle.py                   12      0      0      0   100%
pumpfun_trading/bot/persistence.py                 76      2     20      2    96%   43->46, 95->97, 125-126
pumpfun_trading/bot/position_manager.py           182      1     38      2    99%   280, 292->295
pumpfun_trading/bot/risk.py                       151      2     52      3    98%   98, 214, 326->328
pumpfun_trading/bot/run.py                       1023     64    384     61    91%   363, 367->379, 520->522, 522->524, 524->exit, 575->579, 580->587, 588->595, 596->601, 602->608, 609->614, 664->680, 731-732, 781-782, 855-862, 878, 882->886, 897->exit, 974-976, 1002, 1021-1025, 1053-1054, 1179, 1189, 1192->1198, 1194->1198, 1392->1391, 1399->1391, 1418, 1446-1448, 1594, 1606, 1674->exit, 1684, 1697-1699, 1774, 1791->1838, 1794, 1807->1813, 1819, 1833->1838, 1838->exit, 1857, 1883->exit, 1913, 1930->exit, 1950, 1962->exit, 1985, 2054-2066, 2109->exit, 2112, 2128-2131, 2139, 2165-2166, 2172->2178, 2176-2177, 2184-2185, 2191-2192, 2196->exit, 2205-2206, 2220->exit, 2226-2227, 2232->2235, 2268-2270, 2272, 2275->2282, 2287->2289, 2289->2294, 2291, 2292->2294, 2312
pumpfun_trading/bot/strategy.py                     3      0      0      0   100%
pumpfun_trading/cli/__init__.py                     6      2      0      0    67%   8-10
pumpfun_trading/cli/audit.py                       50      0     12      0   100%
pumpfun_trading/cli/bot.py                         32      1      6      1    95%   95
pumpfun_trading/cli/main.py                       163      2     62      3    98%   268->270, 271, 320
pumpfun_trading/cli/replay.py                      58      0     16      0   100%
pumpfun_trading/config/__init__.py                  1      0      0      0   100%
pumpfun_trading/config/env.py                      62      0     28      0   100%
pumpfun_trading/engines/__init__.py                 2      0      0      0   100%
pumpfun_trading/engines/replay.py                 288      8    122     15    94%   41->44, 80, 116->109, 177->179, 188->190, 195, 217-218, 236, 254->269, 264-267, 269->287, 336, 374->414, 378->414, 450->448
pumpfun_trading/execution/__init__.py               4      0      0      0   100%
pumpfun_trading/execution/builder.py               16      0      0      0   100%
pumpfun_trading/execution/executor.py             133      3     30      3    96%   118, 198->215, 414-417
pumpfun_trading/execution/liquidator.py            39      2      8      3    89%   34, 59, 88->exit
pumpfun_trading/infra/__init__.py                   2      0      0      0   100%
pumpfun_trading/infra/rpc_pool.py                 390     17    126     16    94%   165, 234, 270, 274, 335, 367->477, 380, 399-404, 435-436, 452->467, 481, 510->513, 515, 580, 632, 696->exit, 700, 704-705
pumpfun_trading/ops/__init__.py                     0      0      0      0   100%
pumpfun_trading/ops/logging.py                     53      1     12      2    95%   21, 76->78
pumpfun_trading/ops/monitoring.py                  12      0      0      0   100%
pumpfun_trading/sdk/__init__.py                     4      0      0      0   100%
pumpfun_trading/sdk/execution.py                  486     13    168     16    95%   231->235, 290, 377, 434, 641->651, 652, 731, 797->806, 847->851, 860->864, 878, 930, 958-960, 968, 1030->1043, 1039-1040, 1179->exit
pumpfun_trading/sdk/jito.py                       247      4     80      8    96%   175->179, 216->225, 238->270, 241->270, 379-380, 407, 420, 444->443, 490->489
pumpfun_trading/sdk/raydium.py                     54      3     16      1    94%   48, 249-250
pumpfun_trading/services/__init__.py                1      0      0      0   100%
pumpfun_trading/services/market_data.py            58      2     16      2    95%   67, 72
pumpfun_trading/storage/__init__.py                 1      0      0      0   100%
pumpfun_trading/storage/status.py                  26      0      6      1    97%   16->18
pumpfun_trading/strategies/__init__.py             10      0      0      0   100%
pumpfun_trading/strategies/base.py                 91      1      2      1    98%   165
pumpfun_trading/strategies/copy_trading.py        140      1     38      4    97%   90->93, 145->142, 189->191, 349
pumpfun_trading/strategies/decision.py             42      2      0      0    95%   101, 117
pumpfun_trading/strategies/exits.py               129      1     50      2    98%   57->exit, 154
pumpfun_trading/strategies/filters.py             295      7     92      8    96%   83->85, 87->89, 90->107, 172, 260-261, 382->385, 447, 500-502
pumpfun_trading/strategies/graduation.py          152      3     22      0    97%   440-442
pumpfun_trading/strategies/momentum.py            183      4     50      5    96%   212, 219->210, 235, 285, 410
pumpfun_trading/strategies/presets.py              19      0     10      0   100%
pumpfun_trading/strategies/risk_validation.py      14      0      8      0   100%
pumpfun_trading/strategies/signal.py               26      0     10      0   100%
pumpfun_trading/streams/__init__.py                 2      0      0      0   100%
pumpfun_trading/streams/geyser.py                 370      5     68      7    97%   198->exit, 590-591, 608->exit, 614, 691->687, 695->697, 772-773, 779->exit, 784->exit, 787->784
pumpfun_trading/ui/__init__.py                      1      0      0      0   100%
pumpfun_trading/ui/dashboard.py                   115      1     14      1    98%   185
-------------------------------------------------------------------------------------------
TOTAL                                            5762    164   1760    186    95%
Required test coverage of 95.0% reached. Total coverage: 95.13%
========================================================================================================= 310 passed, 1 warning in 108.57s (0:01:48) ==========================================================================================================
(.venv) [13:21]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (241) $ 
```

#### Quantitative Acceptance Criteria
- `ruff check .` passes with **0 errors and 0 warnings**.
- `mypy` completes with **0 type violations**.
- All **288+ unit and integration tests** pass cleanly with **0 failures and 0 skipped tests**.
- Total statement coverage across `pumpfun_trading` exceeds **90%** (with core risk and execution modules at **>95%**).

---

### Gate 1: Strategy Benchmark & Empirical Validation

Validates that trading strategies (discovery, momentum breakouts, graduation sniping, copy-trading) produce positive risk-adjusted expectancy and withstand choppy market regimes without catastrophic drawdowns.

#### Verification Commands
```bash
# 1. Historical Replay Benchmark on Standard Capture (from runtime directory)
python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl --mode dashboard --config configs/replay_test.json

# 2. Replay Verification across Strategy Presets and Configs
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/conservative_test.json
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/balanced_test.json
python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/aggressive_test.json

# 3. Strategy Modularity & Heuristic Safety Tests
pytest -v pumpfun_trading/tests/test_replay_engine.py pumpfun_trading/tests/test_strategy_modularity.py pumpfun_trading/tests/test_strategy_safety.py
```

#### Gate 1 Results
```bash
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (255) $ python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl --mode dashboard --config configs/replay_test.json
╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Engine ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ Metric                                                                                                                                                                                      ┃ Value                                                     ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ initial_cash                                                                                                                                                                                │ 100.0                                                     │ │
│ │ final_equity                                                                                                                                                                                │ 100.0                                                     │ │
│ │ profit_factor                                                                                                                                                                               │ 0.0                                                       │ │
│ │ max_drawdown                                                                                                                                                                                │ 0.0                                                       │ │
│ │ win_rate                                                                                                                                                                                    │ 0.0                                                       │ │
│ │ average_trade_return                                                                                                                                                                        │ 0.0                                                       │ │
│ │ total_return                                                                                                                                                                                │ 0.0                                                       │ │
│ │ open_positions                                                                                                                                                                              │ 0                                                         │ │
│ └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘ │
│ ╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Status ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Trades: 0                                                                                                                                                                                                                                               │ │
│ │ Buys: 0                                                                                                                                                                                                                                                 │ │
│ │ Sells: 0                                                                                                                                                                                                                                                │ │
│ │ Final cash: 100.0                                                                                                                                                                                                                                       │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
No replay trades recorded.
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (256) $
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (256) $ # 2. Replay Verification across Strategy Presets and Configs
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (256) $ python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/conservative_test.json
╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Engine ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ Metric                                                                                                                                                                                      ┃ Value                                                     ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ initial_cash                                                                                                                                                                                │ 100.0                                                     │ │
│ │ final_equity                                                                                                                                                                                │ 100.0                                                     │ │
│ │ profit_factor                                                                                                                                                                               │ 0.0                                                       │ │
│ │ max_drawdown                                                                                                                                                                                │ 0.0                                                       │ │
│ │ win_rate                                                                                                                                                                                    │ 0.0                                                       │ │
│ │ average_trade_return                                                                                                                                                                        │ 0.0                                                       │ │
│ │ total_return                                                                                                                                                                                │ 0.0                                                       │ │
│ │ open_positions                                                                                                                                                                              │ 0                                                         │ │
│ └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘ │
│ ╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Status ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Trades: 0                                                                                                                                                                                                                                               │ │
│ │ Buys: 0                                                                                                                                                                                                                                                 │ │
│ │ Sells: 0                                                                                                                                                                                                                                                │ │
│ │ Final cash: 100.0                                                                                                                                                                                                                                       │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
No replay trades recorded.
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (257) $ python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/balanced_test.json
╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Engine ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ Metric                                                                                                                                                                                      ┃ Value                                                     ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ initial_cash                                                                                                                                                                                │ 100.0                                                     │ │
│ │ final_equity                                                                                                                                                                                │ 100.0                                                     │ │
│ │ profit_factor                                                                                                                                                                               │ 0.0                                                       │ │
│ │ max_drawdown                                                                                                                                                                                │ 0.0                                                       │ │
│ │ win_rate                                                                                                                                                                                    │ 0.0                                                       │ │
│ │ average_trade_return                                                                                                                                                                        │ 0.0                                                       │ │
│ │ total_return                                                                                                                                                                                │ 0.0                                                       │ │
│ │ open_positions                                                                                                                                                                              │ 0                                                         │ │
│ └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘ │
│ ╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Status ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Trades: 0                                                                                                                                                                                                                                               │ │
│ │ Buys: 0                                                                                                                                                                                                                                                 │ │
│ │ Sells: 0                                                                                                                                                                                                                                                │ │
│ │ Final cash: 100.0                                                                                                                                                                                                                                       │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
No replay trades recorded.
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (258) $ python -m pumpfun_trading.cli.main --mode replay --replay-path test-data/historical_captures.jsonl --config configs/aggressive_test.json
╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Engine ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ Metric                                                                                                                                                                                      ┃ Value                                                     ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ initial_cash                                                                                                                                                                                │ 100.0                                                     │ │
│ │ final_equity                                                                                                                                                                                │ 100.0                                                     │ │
│ │ profit_factor                                                                                                                                                                               │ 0.0                                                       │ │
│ │ max_drawdown                                                                                                                                                                                │ 0.0                                                       │ │
│ │ win_rate                                                                                                                                                                                    │ 0.0                                                       │ │
│ │ average_trade_return                                                                                                                                                                        │ 0.0                                                       │ │
│ │ total_return                                                                                                                                                                                │ 0.0                                                       │ │
│ │ open_positions                                                                                                                                                                              │ 0                                                         │ │
│ └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────┘ │
│ ╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────────── Replay Status ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│ │ Trades: 0                                                                                                                                                                                                                                               │ │
│ │ Buys: 0                                                                                                                                                                                                                                                 │ │
│ │ Sells: 0                                                                                                                                                                                                                                                │ │
│ │ Final cash: 100.0                                                                                                                                                                                                                                       │ │
│ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
No replay trades recorded.
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (259) $
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (259) $ # 3. Strategy Modularity & Heuristic Safety Tests
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (259) $ pytest -v pumpfun_trading/tests/test_replay_engine.py pumpfun_trading/tests/test_strategy_modularity.py pumpfun_trading/tests/test_strategy_safety.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 26 items

pumpfun_trading/tests/test_replay_engine.py .......                                                                                                                                                                                                     [ 26%]
pumpfun_trading/tests/test_strategy_modularity.py .........                                                                                                                                                                                             [ 61%]
pumpfun_trading/tests/test_strategy_safety.py ..........                                                                                                                                                                                                [100%]

===================================================================================================================== 26 passed in 8.72s ======================================================================================================================
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x10c6f6120>
Unclosed connector
connections: ['deque([(<aiohttp.client_proto.ResponseHandler object at 0x109478e60>, 2025818.729288208)])']
connector: <aiohttp.connector.TCPConnector object at 0x10c6f6270>
(.venv) [13:35]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (260) $
```

#### Quantitative Acceptance Criteria
- **Profit Factor:** $\ge 1.40$ on balanced preset across representative replay datasets.
- **Maximum Drawdown:** $\le 15.0\%$ of cumulative equity across backtest sessions.
- **Win Rate:** $\ge 45\%$ with an average win-to-loss payoff ratio $\ge 2.2:1$.
- **Wash-Trading Rejection Rate:** $100\%$ rejection of single-wallet volume manipulation in momentum tests (`test_order_flow_momentum.py`).
- **Anti-Rug Heuristic Accuracy:** $100\%$ rejection of creator-dump and high-Gini concentration tokens (`test_anti_rug_filters.py`).

---

### Gate 2: Risk Controls, Dynamic Exits & Circuit Breakers

Guarantees that capital preservation mechanisms (trailing stops, multi-tier partial scaling, daily drawdown circuit breakers, panic liquidations) operate with deterministic priority.

#### Verification Commands
```bash
# 1. Trailing Stop and Multi-Tier Take-Profit Verification
pytest -v pumpfun_trading/tests/test_trailing_and_tiered_exits.py pumpfun_trading/tests/test_position_manager.py

# 2. Portfolio Drawdown Circuit Breaker & Emergency Liquidation
pytest -v pumpfun_trading/tests/test_portfolio_circuit_breaker.py pumpfun_trading/tests/test_order_executor.py

# 3. Risk Engine State & Health Checks
pytest -v pumpfun_trading/tests/test_risk_health_execution.py
```

#### Gate 2 Results
```bash
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (260) $ pytest -v pumpfun_trading/tests/test_trailing_and_tiered_exits.py pumpfun_trading/tests/test_position_manager.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 20 items

pumpfun_trading/tests/test_trailing_and_tiered_exits.py .............                                                                                                                                                                                   [ 65%]
pumpfun_trading/tests/test_position_manager.py .......                                                                                                                                                                                                  [100%]

===================================================================================================================== 20 passed in 0.25s ======================================================================================================================
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (261) $
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (261) $ # 2. Portfolio Drawdown Circuit Breaker & Emergency Liquidation
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (261) $ pytest -v pumpfun_trading/tests/test_portfolio_circuit_breaker.py pumpfun_trading/tests/test_order_executor.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 17 items

pumpfun_trading/tests/test_portfolio_circuit_breaker.py ...........                                                                                                                                                                                     [ 64%]
pumpfun_trading/tests/test_order_executor.py ......                                                                                                                                                                                                     [100%]

===================================================================================================================== 17 passed in 0.16s ======================================================================================================================
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (262) $
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (262) $ # 3. Risk Engine State & Health Checks
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (262) $ pytest -v pumpfun_trading/tests/test_risk_health_execution.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 6 items

pumpfun_trading/tests/test_risk_health_execution.py ......                                                                                                                                                                                              [100%]

====================================================================================================================== 6 passed in 0.14s ======================================================================================================================
(.venv) [13:36]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (263) $
```


#### Quantitative Acceptance Criteria
- **Stop-Loss Enforcement:** Stop-loss executes within 1 tick upon breaching threshold (default $-15\%$).
- **Trailing Stop Activation:** Trailing stop engages at peak return $\ge +30\%$ and locks in profit on pullback (default $10\%$ drop from peak).
- **Tiered Profit Scaling:** 
  - Tier 1 (2.0x): Automatically liquidates 50% lot size.
  - Tier 2 (3.5x): Automatically liquidates 25% lot size.
  - Tier 3 (Moonbag): Retains 25% remaining position under active trailing stop.
- **Daily Equity Drawdown Limit:** All buy signals are immediately blocked when the daily realized + unrealized drawdown reaches the configured cap (default $20\%$).
- **Panic Liquidation:** Emergency liquidation loop executes batch position sales across all holdings in $<3.0$ seconds without deadlocks.

---

### Gate 3: Network Infrastructure, Multi-RPC Load Balancing & MEV Protection

Verifies that the networking layer sustains high-throughput market streams (Yellowstone Geyser gRPC / WebSocket), automatically balances RPC loads, handles latency degradation, and routes private transactions via Jito Block Engine.

#### Verification Commands
```bash
# 1. Multi-RPC Connection Pool & Latency Failover Tests
pytest -v pumpfun_trading/tests/test_rpc_pool.py pumpfun_trading/tests/test_rpc_pool_bot_integration.py

# 2. Jito MEV Bundle & Fallback Execution Tests
pytest -v pumpfun_trading/tests/test_jito_sdk.py pumpfun_trading/tests/test_jito_execution_integration.py pumpfun_trading/tests/test_execution_sdk_full.py

# 3. Yellowstone Geyser Stream Resilience & Reconnection
pytest -v pumpfun_trading/tests/test_geyser_stream.py pumpfun_trading/tests/test_geyser_bot_integration.py pumpfun_trading/tests/test_market_data_resilience.py
```

#### Gate 3 Results
```bash
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (263) $ # 1. Multi-RPC Connection Pool & Latency Failover Tests
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (263) $ pytest -v pumpfun_trading/tests/test_rpc_pool.py pumpfun_trading/tests/test_rpc_pool_bot_integration.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 14 items

pumpfun_trading/tests/test_rpc_pool.py ...........                                                                                                                                                                                                      [ 78%]
pumpfun_trading/tests/test_rpc_pool_bot_integration.py ...                                                                                                                                                                                              [100%]

===================================================================================================================== 14 passed in 0.59s ======================================================================================================================
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (264) $
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (264) $ # 2. Jito MEV Bundle & Fallback Execution Tests
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (264) $ pytest -v pumpfun_trading/tests/test_jito_sdk.py pumpfun_trading/tests/test_jito_execution_integration.py pumpfun_trading/tests/test_execution_sdk_full.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 35 items

pumpfun_trading/tests/test_jito_sdk.py .................                                                                                                                                                                                                [ 48%]
pumpfun_trading/tests/test_jito_execution_integration.py ..............                                                                                                                                                                                 [ 88%]
pumpfun_trading/tests/test_execution_sdk_full.py ....                                                                                                                                                                                                   [100%]

===================================================================================================================== 35 passed in 0.48s ======================================================================================================================
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x1085557f0>
Unclosed connector
connections: ['deque([(<aiohttp.client_proto.ResponseHandler object at 0x105350e60>, 2025908.595532458)])']
connector: <aiohttp.connector.TCPConnector object at 0x1084f9090>
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x1085a4c20>
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (265) $
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (265) $ # 3. Yellowstone Geyser Stream Resilience & Reconnection
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (265) $ pytest -v pumpfun_trading/tests/test_geyser_stream.py pumpfun_trading/tests/test_geyser_bot_integration.py pumpfun_trading/tests/test_market_data_resilience.py===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 23 items

pumpfun_trading/tests/test_geyser_stream.py ..............                                                                                                                                                                                              [ 60%]
pumpfun_trading/tests/test_geyser_bot_integration.py ......                                                                                                                                                                                             [ 86%]
pumpfun_trading/tests/test_market_data_resilience.py ...                                                                                                                                                                                                [100%]

===================================================================================================================== 23 passed in 26.93s =====================================================================================================================
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x10a24af90>
Unclosed connector
connections: ['deque([(<aiohttp.client_proto.ResponseHandler object at 0x1021dce60>, 2025923.243389375)])']
connector: <aiohttp.connector.TCPConnector object at 0x10a2fc1a0>
(.venv) [13:37]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (266) $
```
#### Quantitative Acceptance Criteria
- **Multi-RPC Failover:** Dynamic circuit breaker transitions between `HEALTHY`, `DEGRADED`, `OPEN`, and `HALF_OPEN` within 3 consecutive probe failures.
- **Read Routing:** Fast routing directs $\ge 90\%$ of read queries to the lowest $p_{50}$ latency RPC provider.
- **Jito MEV Bundling:** Private bundle submission constructs valid tip instructions and adheres to tip caps (default 0.0001–0.001 SOL).
- **RPC Fallback:** If Jito confirmation times out ($>12.0$s), execution cleanly falls back to high-priority direct RPC without double-spending.
- **Stream Recovery:** Geyser/WebSocket stream reconnects within $\le 5.0$ seconds on simulated socket severance, resuming event consumption without unbounded memory growth.

---

### Gate 4: Security, Secrets, Hygiene & Wallet Isolation

Ensures private keys, API credentials, and webhooks are never exposed, logged, or co-mingled with unprivileged processes.

#### Verification Commands
```bash
# 1. Git Repository Scan for Accidental Credentials
git grep -iE "(private_key|secret_key|api_key|token|password)" -- ":(exclude)*.sample" ":(exclude)*.md" ":(exclude)*tests*"

# 2. Filesystem Permissions Check for Environment Files
test -f .envrc && stat -f "%Sp %N" .envrc | grep -E "^-rw-------"

# 3. Validation of Keypair Loading Isolation
python -c "
from pumpfun_trading.config.env import load_keypair_from_env
kp = load_keypair_from_env()
print('Keypair loaded successfully:', kp is not None)
"
```

#### Gate 4 Results
```bash
(.venv) [13:51]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (274) $ git grep -iE "(private_key|secret_key|api_key|token|password)" -- ":(exclude)*.sample" ":(exclude)*.md" ":(exclude)*tests*" ":(exclude)*.py"
.github/workflows/release.yml:            id-token: write
bot-config.example.json:  "recent_token_ttl_seconds": 600,
bot-config.example.json:  "max_token_concentration_pct": 0.35,
configs/aggressive_test.json:  "recent_token_ttl_seconds": 600,
configs/aggressive_test.json:  "max_token_concentration_pct": 0.50,
configs/aggressive_test.json:  "momentum_max_token_age_seconds": 3600,
configs/balanced_test.json:  "recent_token_ttl_seconds": 600,
configs/balanced_test.json:  "max_token_concentration_pct": 0.35,
configs/balanced_test.json:  "momentum_max_token_age_seconds": 1800,
configs/conservative_test.json:  "recent_token_ttl_seconds": 600,
configs/conservative_test.json:  "max_token_concentration_pct": 0.25,
configs/conservative_test.json:  "momentum_max_token_age_seconds": 900,
configs/devnet_test.json:  "recent_token_ttl_seconds": 600,
configs/devnet_test.json:  "max_token_concentration_pct": 0.35,
configs/devnet_test.json:  "momentum_max_token_age_seconds": 1800,
configs/preprod_pilot.json:  "recent_token_ttl_seconds": 600,
configs/preprod_pilot.json:  "max_token_concentration_pct": 0.35,
configs/preprod_pilot.json:  "momentum_max_token_age_seconds": 1800,
configs/replay_test.json:  "recent_token_ttl_seconds": 600,
configs/replay_test.json:  "max_token_concentration_pct": 0.35,
configs/replay_test.json:  "momentum_max_token_age_seconds": 1800,
(.venv) [13:52]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (275) $ test -f .envrc && stat -f "%Sp %N" .envrc | grep -E "^-rw-------"
(.venv) [13:52]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (276) $ python -c "
from pumpfun_trading.config.env import load_keypair_from_env
kp = load_keypair_from_env()
print('Keypair loaded successfully:', kp is not None)
"
Keypair loaded successfully: True
```


#### Quantitative Acceptance Criteria
- **Zero Committed Secrets:** 0 private keys, bearer tokens, or webhook URLs in tracked files.
- **File Permissions:** Local environment configuration (`.envrc` or deployment secrets) must have restricted permissions (`chmod 600`).
- **Hot Wallet Segregation:** Trading keypair must be an isolated hot wallet holding no more than operational trading capital (e.g., $\le 2.0$ SOL for test runs).
- **Sanitized Logging:** Audit trails and status snapshots must never serialize raw private keys or seed phrases.

---

### Gate 5: Persistence, State Restoration & Audit Trail Integrity

Validates that runtime status snapshots (`test-data/bot_status.json`) and append-only audit records (`test-data/audit_trail.jsonl`) maintain 100% accounting fidelity across unexpected process crashes and restarts.

#### Verification Commands
```bash
# 1. Persistence & Lifecycle Resilience Tests
pytest -v pumpfun_trading/tests/test_bot_subsystems.py pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py pumpfun_trading/tests/test_position_manager.py

# 2. Audit Trail Tool & Export CLI Verification
pytest -v pumpfun_trading/tests/test_audit_tool.py pumpfun_trading/tests/test_audit_full.py

# 3. Audit Log Summary Inspection on Test Output (from runtime directory)
python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --summary
```

#### Gate 5 Results
```bash
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (277) $ # 1. Persistence & Lifecycle Resilience Tests
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (277) $ pytest -v pumpfun_trading/tests/test_bot_subsystems.py pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py pumpfun_trading/tests/test_position_manager.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 18 items

pumpfun_trading/tests/test_bot_subsystems.py .......                                                                                                                                                                                                    [ 38%]
pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py ....                                                                                                                                                                                        [ 61%]
pumpfun_trading/tests/test_position_manager.py .......                                                                                                                                                                                                  [100%]

===================================================================================================================== 18 passed in 0.23s ======================================================================================================================
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (278) $
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (278) $ # 2. Audit Trail Tool & Export CLI Verification
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (278) $ pytest -v pumpfun_trading/tests/test_audit_tool.py pumpfun_trading/tests/test_audit_full.py
===================================================================================================================== test session starts =====================================================================================================================
platform darwin -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/andy/projects/git/trading/runtime/pumpfun-trading
configfile: pyproject.toml
plugins: platformdirs-4.13.0, cov-7.1.0, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 7 items

pumpfun_trading/tests/test_audit_tool.py ....                                                                                                                                                                                                           [ 57%]
pumpfun_trading/tests/test_audit_full.py ...                                                                                                                                                                                                            [100%]

====================================================================================================================== 7 passed in 0.15s ======================================================================================================================
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (279) $
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (279) $ # 3. Audit Log Summary Inspection on Test Output (from runtime directory)
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (279) $ python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --summary
{
  "by_reason": {
    "auto_advance_idle_to_monitoring": 2,
    "buy_confirmed 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": 2,
    "buy_rejected_equity_guard 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": 2,
    "buying 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": 4,
    "circuit_breaker_reset": 2,
    "entry": 2,
    "raydium_graduation_snipe": 2,
    "retry_test": 2,
    "second_failure": 2,
    "sell_complete 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": 2,
    "sell_complete HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump": 2,
    "sell_failed HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump": 2,
    "selling 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R (stop_loss_hit (8.00% <= 85.00%))": 2,
    "selling HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump (exit)": 2,
    "selling HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump (second_failure)": 2,
    "shutdown_requested": 4,
    "stop_loss_hit (2.50% <= 85.00%)": 1,
    "stop_loss_hit (8.00% <= 85.00%)": 2,
    "take_profit_tier_1 (2.00x >= 2.00x)": 2,
    "take_profit_tier_2 (3.50x >= 3.50x)": 2
  },
  "by_state": {
    "buying": 6,
    "holding": 4,
    "idle": 110,
    "monitoring": 10,
    "selling": 10,
    "shutdown": 13
  },
  "by_status": {},
  "by_type": {
    "state_transition": 28,
    "trade": 125
  },
  "total_records": 153
}
(.venv) [13:53]:andy@M-FYRF96W7JH:~/projects/git/trading/runtime/pumpfun-trading (main) (280) $
```


#### Quantitative Acceptance Criteria
- **Atomic Snapshots:** `test-data/bot_status.json` written atomically via temporary file rename, eliminating partial-write file corruption.
- **Crash Recovery (`safe_startup`):** Restarting a terminated bot recovers all active positions, cost bases, peak prices, and partial exit tier states without duplicate buys or dropped positions.
- **Audit Completeness:** Every signal generation, anti-rug rejection, order submission, fill confirmation, and exit trigger logs a typed, ISO-timestamped JSONL entry to `test-data/audit_trail.jsonl`.
- **CLI Export:** `python -m pumpfun_trading.cli.main audit --path <file> --export <out.json>` produces valid JSON matching loaded record count.

---

### Gate 6: 72-Hour Continuous Live Paper Pilot

Executes a non-stop, 72-hour paper-trading pilot on live Solana mainnet/devnet streams within the `runtime/` environment to verify memory stability, real-time event loop latency, and alerting integration under real market traffic.

#### Required Streaming Configuration
To ingest real-time market events, **at least one** stream source must be configured in `runtime/.envrc` or `configs/preprod_pilot.json`:

1. **Option A: Yellowstone Geyser gRPC (High-Speed Mainnet / Devnet Feed)**
   ```bash
   export PUMPFUN_GEYSER_ENDPOINT="https://grpc.mainnet.helius-rpc.com"  # Or your Yellowstone gRPC endpoint
   export PUMPFUN_GEYSER_X_TOKEN="<your-geyser-x-token>"                # Optional auth header
   ```
2. **Option B: WebSocket Event Feed (PumpPortal / Public Stream)**
   ```bash
   export PUMPFUN_STREAM_URL="wss://pumpportal.fun/api/data"
   ```

> **Important Stream Requirement**: If neither `PUMPFUN_GEYSER_ENDPOINT` nor `PUMPFUN_STREAM_URL` is set, the bot defaults to `http://127.0.0.1:10000` (offline testing stub), resulting in zero live market events.
>
> **Note on Dashboard Stream URL Display**: 
> In the Rich terminal dashboard, `Stream URL` displays the WebSocket endpoint (`bot.stream_url`, default `http://127.0.0.1:10000`), while `Geyser endpoint` displays the Yellowstone gRPC endpoint (`bot.geyser_endpoint`). When running with Yellowstone Geyser without setting `PUMPFUN_STREAM_URL`, the `Stream URL` row remains `http://127.0.0.1:10000` because WebSocket streaming is inactive while all market events are ingested directly via the Yellowstone Geyser gRPC connection.

#### Execution Command
```bash
# Start 72-Hour Live Paper Pilot in Background from runtime/ directory
python -m pumpfun_trading.cli.bot \
  --paper-trade \
  --config configs/preprod_pilot.json
```

#### Operational Monitoring Checklist
```bash
# 1. Real-Time Status Verification
cat test-data/bot_status.json | jq '{status, active_positions: .active_positions | length, total_trades: .metrics.total_trades, uptime: .uptime_seconds}'

# 2. Audit Event Inspection
python -m pumpfun_trading.cli.main audit --path test-data/audit_trail.jsonl --limit 10

# 3. Memory & Process Stability
ps -o pid,vsz,rss,comm -p $(pgrep -f "pumpfun_trading.cli.bot")
```

#### Gate 6 Results
```bash

```


#### Quantitative Acceptance Criteria
- **Continuous Uptime:** $100\%$ process uptime over 72 hours (0 unhandled crashes or fatal event loop deadlocks).
- **Memory Footprint:** Resident Set Size (RSS) stays stable $\le 250$ MB with no monotonic memory growth.
- **Event Latency:** Ingestion-to-evaluation pipeline processes streaming events in $\le 5.0$ ms.
- **Alert Dispatch:** $100\%$ of exit triggers and circuit breaker events deliver webhook alerts without blocking the event loop.

---

## 4. Master Release Gate Verification Checklist

| Gate ID    | Domain              | Primary Verification Command                                            | Required Outcome                            |                Status                 |
|:-----------|:--------------------|:------------------------------------------------------------------------|:--------------------------------------------|:-------------------------------------:|
| **Gate 0** | Code Quality        | `pytest -v --cov=pumpfun_trading` & `ruff check .`                      | 0 errors, 288+ tests pass, >90% cov         |                  [ ]                  |
| **Gate 1** | Strategy Benchmark  | `python -m pumpfun_trading.cli.main replay --path test-data/...`        | Profit Factor $\ge 1.40$, Max DD $\le 15\%$ |                  [ ]                  |
| **Gate 2** | Risk Controls       | `pytest pumpfun_trading/tests/test_portfolio_circuit_breaker.py`        | 100% stop-loss & tiered exit execution      |                  [ ]                  |
| **Gate 3** | Network & MEV       | `pytest pumpfun_trading/tests/test_rpc_pool.py test_jito_sdk.py`        | Multi-RPC failover & Jito bundle pass       |                  [ ]                  |
| **Gate 4** | Security & Secrets  | `git grep -iE "(private_key                                             | api_key)"` & `chmod 600 .envrc`             | 0 committed keys, isolated hot wallet |                  [ ]                  |
| **Gate 5** | Persistence & Audit | `pytest pumpfun_trading/tests/test_bugfixes_lifecycle_resilience.py`    | Atomic snapshot & crash recovery pass       |                  [ ]                  |
| **Gate 6** | 72h Paper Pilot     | `python -m pumpfun_trading.cli.bot --config configs/preprod_pilot.json` | 72h uptime, RSS $<250$MB, 0 deadlocks       |                  [ ]                  |

---

## 5. Formal Go / No-Go Decision Policy

### Mandatory "GO" Conditions
A **GO** decision is authorized **only** when all of the following conditions are simultaneously satisfied:
1. All 7 release gates (Gate 0 through Gate 6) are marked as verified with documented logs.
2. Strategy benchmark demonstrates positive risk-adjusted expectancy across historical captures in `test-data/`.
3. 72-hour paper pilot concludes with zero unhandled exceptions and complete state recovery in `test-data/bot_status.json`.
4. Designated system operator signs off on runbook procedures and emergency stop protocols.

### Immediate "NO-GO" Triggers
Any of the following conditions triggers an immediate **NO-GO** and halts deployment:
- Any test failure in the 288+ test regression suite.
- Unhandled memory leak (RSS increasing continuously over the pilot window).
- Discovered plaintext credential or improper file permissions on secret stores.
- Failure of trailing stop or stop-loss to trigger on adverse price movement in replay or pilot.
- Status snapshot corruption or inability to restore state during simulated crash recovery.

---

## 6. Incident Escalation & Rollback Plan

If an operational anomaly occurs during pre-production or initial live pilot:

1. **Immediate Halt:** Issue `SIGINT` (Ctrl+C) or execute emergency stop command.
2. **State Freeze:** Archive `test-data/bot_status.json` and `test-data/audit_trail.jsonl` with timestamp for forensic analysis.
3. **Wallet Inspection:** Query on-chain wallet balance and token accounts via RPC pool to verify zero leaked funds.
4. **Root Cause Analysis:** Replay the incident trade sequence using `python -m pumpfun_trading.cli.main replay --path test-data/historical_captures.jsonl` to diagnose failure.
5. **Remediation & Gate Reset:** Apply code fix, re-run all regression test suites, and reset Gate 6 (72h pilot).

---

## 7. Related References

- `NEXT-30-DAYS.md` - 30-day pre-production milestone execution schedule.
- `RUNBOOK.md` - Operator procedures for startup, shutdown, and incident management.
- `TODO.md` - Sprint delivery roadmap and completed feature matrix.
- `../USER-GUIDE.md` - Comprehensive configuration and CLI operational guide.

