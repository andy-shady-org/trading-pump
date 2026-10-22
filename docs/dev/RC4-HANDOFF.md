# rc.4 Hand-Off For Coding Agents

A briefing for an AI coding agent (for example Junie in PyCharm) that picks up this repository after the 2026-10-22 work session. It explains what changed for v0.3.0-rc.4, where the code is, which rules apply and what is still open.

**Read [`AGENTS.md`](../../AGENTS.md) first.** It is the binding rule set (Local Norms and Learnings Log). This file adds the context of the rc.4 changes only. When the two disagree, `AGENTS.md` wins, and this file should be fixed.

---

## 1. Ground rules for this checkout

These come from the operator and are not negotiable:

1. **Never touch the runtime directory** `/Users/andy/projects/git/trading/runtime`. The rc.3 72 h paper test runs there. Read nothing there unless the operator asks, and write nothing ever.
2. **The working repo is live code.** `/Users/andy/projects/git/trading/pumpfun-trading` is installed editable into the venv `/Users/andy/projects/virtual_envs/other_venvs/pumpfun-trading`, and the running rc.3 bot imports from it. While rc.3 runs, **do not check out another branch, reset, stash or rebuild in that working tree**. Work in a separate worktree instead:
   ```bash
   git -C /Users/andy/projects/git/trading/pumpfun-trading worktree add ../pumpfun-trading-rc4 rc4/implementation
   ```
   Open `../pumpfun-trading-rc4` as the PyCharm project for rc.4 work and give it **its own venv**. The shared venv's editable install points at the working repo, so `pumpfun-*` commands there run `main`'s code, not the worktree's. Reinstalling it from the worktree would repoint the package under the running bot. For example:
   ```bash
   cd ../pumpfun-trading-rc4
   python3.14 -m venv ../venv-rc4 && ../venv-rc4/bin/pip install -e ".[dev]"
   ```
   `nox` builds its own venvs, so `nox -s …` is safe in the worktree either way.
3. **Secrets.** `.envrc` holds `PUMPFUN_PRIVATE_KEY` and the provider keys. Never open, print, copy or commit it. Never write a raw provider URL anywhere (use `ops/redact.py`, `AGENTS.md` [SECURITY]).
4. **Git.** Commit and push only when the operator asks. Never push without being asked. One branch per change, merged with `--no-ff` into the integration branch (`rc4/implementation`).
5. **Quality gate.** `nox -s format lint mypy tests package` must pass. Coverage stays ≥ 95% (statement + branch). Python 3.11–3.14 are all supported (`AGENTS.md` [TESTS] "Green On 3.14 Is Not Green On 3.11").

---

## 2. Branch map

```
main  25b4c56  Merge PR #36 (rc4/integration: BUG-127…140, see §3)
 └─ rc4/implementation   (created from main; the rc.4 pre-flight work below)
     ├─ feat/replay-circuit-breaker        FEAT-66
     ├─ fix/bug-141-ratchet-peak-realized  BUG-141
     ├─ feat/audit-verdict                 FEAT-67
     ├─ feat/run-provenance                FEAT-68
     ├─ fix/bug-142-unread-env-vars        BUG-142
     ├─ feat/risk-drills                   FEAT-69
     ├─ fix/bug-143-test-event-log-leak    BUG-143
     ├─ docs/rc4-gate-status               RELEASE-GATE §1, README
     └─ docs/rc4-agent-handoff             this file
```

Branches were built and merged one after another, each starting from the `rc4/implementation` tip of the time, so they merge without conflicts in this order. None of them has been pushed. The version in `pyproject.toml` is still `0.3.0rc3`: the bump to `0.3.0rc4` belongs on the release branch (`RELEASE-GATE.md` §6, CHANGELOG release record).

Gate status of `rc4/implementation`: ruff, black and mypy clean; **2,075 tests pass on 3.14 and 3.11, coverage 97.05%**. That run was on Linux with the venv's pinned package versions. Still to do: `nox -s tests` and `nox -s package` on the Mac, the CI matrix, `pumpfun-drill --report`.

---

## 3. Already on `main`: the 2026-10-22 code-review fixes (BUG-127 to BUG-140)

Full write-ups are in [`BUGS.md` §24](BUGS.md#24-code-review-risk-execution-and-maths-2026-10-22). What an agent needs to know when touching these areas:

| Bug | Area | What the code does now | Where |
|---|---|---|---|
| BUG-127 | Risk | Profit-run zone halts new buys below the ratchet floor `effective_baseline_sol` (soft halt, no liquidation) | `bot/risk.py` `DailyEquityTracker.evaluate_circuit_breaker` |
| BUG-128 | Risk | Emergency locks last `emergency_hard_lock_hours` across the 00:00 UTC rollover. New config key `max_cumulative_drawdown_pct` (default 0.30, 0 = off) measured from the persisted `reference_equity_sol`; a trip sets the operator pause, and `SIGUSR1` resume is the reset | `bot/risk.py`, `bot/run.py` `_check_and_enforce_circuit_breaker`, `resume_buying` |
| BUG-129 | Execution | Live entries are priced from the fill (`entry_price_source`: `live_fill` / `post_fill_curve` / `signal`) | `execution/executor.py`, `bot/run.py` `_buy_token` |
| BUG-130 | Risk | A live run blocks buys and takes no day baseline until its first real balance read (`_live_balance_confirmed`, `_equity_known`) | `bot/run.py`, `bot/risk.py` `evaluate_portfolio_circuit_breaker` |
| BUG-131 | Raydium lane | Entries from the fill or the first observed price, never 69 SOL; lane off in every preset | `bot/run.py` `_raydium_fill_market_cap` |
| BUG-132 | Streams | Confirmed mode: the Geyser path uses the confirmed pipeline, no legacy spike entry | `bot/handlers/trade.py` |
| BUG-133 | Maths | Velocity z-score baseline uses earlier, post-creation slices only | `strategies/momentum.py` |
| BUG-134 | Slippage | Estimator fed from every curve read (LRU 512); impact term is execution slippage Δx/x | `bot/run.py` `_feed_slippage_estimator` |
| BUG-135 | Optimizer | Fitness per position, per-trade Sharpe / Sortino, Calmar drawdown floor 1% | `engines/optimizer.py` `position_returns` |
| BUG-136 | Risk | Breaker values open positions at exit value, displays keep spot | `bot/run.py` `_open_positions_exit_value` |
| BUG-137 | Units | `market_cap_sol_from_reserves` takes lamports / raw units explicitly; unknown entry = `LAUNCH_MARKET_CAP_SOL` (27.96) | `sdk/curve.py` |
| BUG-138 | Fees | Pump.fun `fee_config` tiers decoded (`sdk/fee_config.py`), cached for live quotes, checked at startup against the modelled 125 bps | `sdk/fee_config.py`, `bot/run.py` `_check_pump_fee_schedule` |
| BUG-139 | Slow lane | Sell quotes carry `buy_gap_seconds` / `buy_gap_slots`; `round_trip_cost_summary`, `bars_in_sol` | `services/slow_lane.py` |
| BUG-140 | Exits | A tier sell re-checks the tier under the per-mint lock, so a queued repeat is refused | `bot/run.py` `_tier_already_executed`, `_sell_token_locked` |

`configs/capture.json` and `configs/pregrad_pilot.json` set `max_cumulative_drawdown_pct: 0.0` and `profit_ratchet_ratio: 0.0` so data capture never halts. `configs/canary.json` keeps the defaults (cap 0.30, ratchet 0.50).

---

## 4. The rc.4 pre-flight items

### 4.1 FEAT-66: circuit breaker in replay (`feat/replay-circuit-breaker`)

**Why:** paper runs halt on the breaker (BUG-127/128). Replay didn't model it, so a halted paper day showed up as a false parity gap.

**Code**
- `engines/replay.py`, `PaperTradingEngine(..., circuit_breaker=False)`. It needs `live_fidelity=True` and raises `ValueError` otherwise. When on, `run()` keeps a `DailyEquityTracker`:
  - realized PnL is booked per replayed sell or arbitrage (`record_realized_trade(pnl, costs_sol)`);
  - the tracker is evaluated every `BREAKER_EVAL_SECONDS = 5.0` of **data time** and again before every buy (as the bot's equity guard does), with cash plus open positions at exit value (`_open_exit_value`).
  - Helpers: `_evaluate_breaker`, `_note_breaker_trip`.
  - An `EMERGENCY_LIQUIDATE` lock with `auto_liquidate_on_circuit_breaker` force-sells every filled position (`reason: circuit_breaker_liquidation`, via `_live_exit_pass(forced_reason=...)`).
  - A cumulative-cap trip stays on to the end of the replay, because there is no operator to resume it.
  - Refused buys count as `entry_rejections["circuit_breaker"]`.
- The summary gets a `circuit_breaker` block: `trips`, `liquidations`, `locks[]` (timestamp, action, reason), `refused_buys`, `engaged_at_end`, `cumulative_cap_hit`, `reference_equity_sol`. `render_replay_summary` adds one row.
- `strategies/base.py`: new `simulated_starting_balance_sol(config)` (`paper_starting_balance_sol`, else reserve + 10 × `buy_amount_sol`), shared by the bot (`TradingBot._initial_simulated_balance`) and replay.
- `cli/replay.py`:
  - `--initial-cash` now defaults to `None`. With `--config` / `--preset` it means the paper wallet; with `--simple-exits` or no config it means 100.
  - New `--no-circuit-breaker`.
  - The breaker is on for plain replays and `--compare-audit`.
  - `--sweep`, `--keep`, the shadow tools and `pumpfun-optimize` keep their 100 SOL / own bankroll with the breaker off, so their results are unchanged.
- `engines/parity.py`: `normalise_exit_reason` maps the bot's `circuit_breaker: <reason>` and `emergency_circuit_breaker_liquidation` sells to `circuit_breaker_liquidation`.

**Behaviour change:** a `configs/canary.json` replay now starts from 0.35 SOL with the breaker on, so it can halt like paper did. `--no-circuit-breaker --initial-cash 100` reproduces pre-rc.4 results.

**Tests:** `tests/unit/engines/test_replay.py`. The circuit-breaker section is at the end of the file: daily-limit trip and liquidation, no auto-liquidation, liquidation of the current mint without re-entry, ratchet floor and next-day release, final cumulative cap, pre-buy re-check, summary row. Also `tests/unit/cli/test_replay.py` (paper-wallet cash, flags) and `tests/unit/engines/test_parity.py` (reason mapping).

### 4.2 FEAT-67: pre-registered paper verdict (`feat/audit-verdict`)

**Why:** a go / no-go rule chosen after seeing the data can be tuned to any answer. The rule must be fixed before the run.

**Code**
- `bot/verdict.py`:
  - `VerdictRules` is a frozen dataclass: `min_positions` 100, `min_net_sol` 0, `exit_haircut_bps` 0, `tip_lamports` 0, `split_at` "mid", `min_positive_day_share` 0.5, `drop_top` 3, `bootstrap_samples` 10,000, `confidence` 0.90, `seed` 7, `strategy` None.
  - It validates its values and normalises number types, so 50 and 50.0 hash the same.
  - It loads with `from_file` (unknown keys are refused; keys starting with `_` are comments), takes flag overrides with `with_overrides`, and has a `sha256` fingerprint.
- `adjusted_positions(trades, rules)` returns the closed positions with `net` and `adjusted_net`: net, less `exit_haircut_bps` of each sell's proceeds, less a top-up of every transaction's tip to `tip_lamports`. Open positions are only counted.
- `evaluate_verdict(trades, rules)` runs six checks:
  - `min_positions`
  - `net_positive`
  - `halves_positive`
  - `positive_days` (UTC day of the entry)
  - `without_top_winners`
  - `bootstrap_lower_bound` (seeded percentile bootstrap of the mean per position)

  The report has `verdict` (`GO` / `NO-GO`), `rules`, `rules_sha256`, `halves`, `days`, `without_top_sol` (0–5) and `checks`.
- `cli/audit.py` adds the command `verdict` with `--rules`, `--min-positions`, `--min-net-sol`, `--exit-haircut-bps`, `--tip-lamports`, `--min-positive-day-share`, `--drop-top`, `--bootstrap-samples`, `--confidence` and `--seed`. `--strategy` and `--split-at` are shared with `cuts`. Output goes through `render_verdict` (or `--json`). Exit code is 0 on GO, 1 on NO-GO, 2 on a bad rule.
- `configs/verdict_rules.json` holds the shipped rc.4 rule: 100 positions, 50 bps haircut, 25,000 lamports tip, mid split, 50% of days, drop top 3, 90% CI, seed 7. **Do not edit it once a run has started.** Its hash goes in the release record.

**Tests:** `tests/unit/bot/test_verdict.py` (GO, lucky-winner NO-GO, one-half NO-GO, noise NO-GO, haircut / tip, lanes, empty trail, bootstrap determinism, rule file and hash, bad rules, shipped file) and `tests/unit/cli/test_audit.py` (verdict section at the end).

### 4.3 FEAT-68: run provenance stamp (`feat/run-provenance`)

**Why:** a result is only comparable with a replay or another run when it says which build, config and fee schedule produced it.

**Code**
- `ops/provenance.py`:
  - `collect_run_provenance(config, *, mode, config_path, fee_config, launch_fee_bps, modelled_fee_bps, ...)` collects, without network access:
    - `package_version`;
    - `git_commit` / `git_branch` / `git_dirty` / `git_source` from `git rev-parse` on the checkout the package runs from, with a 2 s timeout (or `PUMPFUN_GIT_COMMIT` when there is no `.git`);
    - Python version, platform, pid, `mode`, preset, entry mode;
    - `config_path`, `config_file_sha256` (file bytes) and `config_sha256` (effective config, URLs and secrets redacted first);
    - `fee_model_bps`, `fee_launch_bps`, `fee_tiers`;
    - `cost_env`: only `PUMPFUN_USE_JITO` and `PUMPFUN_JITO_*TIP_LAMPORTS`.
  - Helpers: `config_sha256`, `file_sha256`, `fee_tiers_summary`, `provenance_capture_row`, `short_build_label`.
- `bot/run.py` adds `TradingBot.config_path` (set by `cli/bot.py` and `cli/main.py` from `--config`), `run_provenance`, `_pump_fee_config` and `_run_mode()`.
- In `start()`:
  1. `_collect_run_provenance()` runs first (in a worker thread, because `git` is a subprocess). A failure is logged and never stops the bot.
  2. The `bot started` alert carries `0.3.0rcN @ <commit8>`.
  3. After `_check_pump_fee_schedule()`, `_record_run_provenance(launch_fee_bps)` adds the fee tiers and writes the stamp to four places: the `run_started` audit record, the `event: "run_provenance"` capture row, a `run_provenance` diagnostic event, and `run_provenance` in `get_status_snapshot()`.
- `engines/replay.py`:
  - `NON_MARKET_EVENTS` now includes `run_provenance`, so the row is never market data.
  - The summary lists a capture's stamps as `capture_runs` (the keys are in `CAPTURE_RUN_KEYS`).
- `engines/parity.py` gains `provenance_notes(audit_records, replay_config_path)`, which `--compare-audit` prints in yellow: no stamp (pre-rc.4 trail), dirty build, or a replay config file whose hash differs from the run's.

**Tests:** `tests/unit/ops/test_provenance.py` (git info faked and on a real temp repo, env override, version fallback, hash stability and URL-key redaction, fee tiers, cost env, collect / capture row / label), the provenance tests at the end of `tests/unit/bot/test_run.py`, and `tests/unit/engines/test_parity.py`.

### 4.4 FEAT-69: scripted risk drills (`feat/risk-drills`)

**Why:** the breaker paths that matter most are hard to force on a running instance.

**Code**
- `ops/drills.py` builds a real paper `TradingBot` per drill in a scratch folder.
  - No stream, and a throwaway keypair.
  - The balance RPC and the sell executor are fakes; `execute_buy` and `execute_sell` raise if they are ever called in the live drill.
  - Alerts are captured in `bot.drill_alerts`.
  - The operator's `PUMPFUN_*` environment is set aside by `isolated_environment`.
  - Logging at WARNING and below is muted while drills run.
- The drills:
  - `cumulative_cap`: two losing days trip the 25% cap; buying pauses; the pause and the cap survive a restart and the lock expiry; `SIGUSR1` resets the cap (BUG-128).
  - `midnight_lock`: a 23:55 UTC emergency lock holds at 00:05 and ends 24 h later (BUG-128).
  - `balance_rpc_down`: live start with the RPC down takes no baseline and refuses buys, then baselines on the real read (BUG-130).
  - `slow_tier_sell`: a tier sell past the 60 s latch is not repeated (BUG-140).
- `run_drills(names=None, *, workdir=None) -> DrillReport`. A drill that raises counts as failed. A drill with no checks counts as failed too.
- **Clock seam:** `TradingBot.clock` (default `time.time`), `now_timestamp()` and `_now_utc()`. `evaluate_portfolio_circuit_breaker(bot)` passes `bot.now_timestamp()` to the tracker when it returns a real number; a `MagicMock` bot falls back to wall time. `update_valuation` / `calculate_drawdown` calls in `bot/run.py` pass `now_utc`. **Use `bot.clock` to move time in tests and drills; never sleep.**
- `cli/drill.py` provides `pumpfun-drill` (new console script in `pyproject.toml`) and `pumpfun ops drill` (`cli/main.py`), with `--only`, `--workdir`, `--report`, `--json` and `--list`. Exit code 1 on any failure. The `pumpfun-drill` console script exists only in a venv installed from rc.4 code (the worktree venv in §1). Without one, use `python -m pumpfun_trading.cli.main ops drill` from the worktree root.

**Tests:** `tests/unit/ops/test_drills.py`, where `test_every_drill_passes_on_the_current_risk_code` is the regression guard for BUG-128/130/140. Also `tests/unit/cli/test_drill.py`, and the clock seam test in `tests/unit/bot/test_risk.py`.

---

## 5. Bugs found during rc.4 (BUG-141 to BUG-143)

Full entries are in [`BUGS.md` §25](BUGS.md#25-rc4-pre-flight-findings-2026-10-22).

- **BUG-141 (Medium):** the ratchet floor used today's *net* realized PnL, so a closed loss after a win lowered it. `DailyEquityTracker` now keeps `peak_realized_daily_pnl_sol`:
  - updated in `record_realized_trade`;
  - reset at the rollover and on the hard-lock auto-unlock;
  - persisted in `to_dict` / `from_dict` (a legacy status file starts from today's PnL).

  `effective_baseline_sol` uses the peak. **Behaviour change** for configs with `profit_ratchet_ratio` > 0 (`canary.json`): a day that wins and then gives the profit back through closed trades now stops buying at the floor.
- **BUG-142 (Medium):** 51 documented environment variables were never read. `PUMPFUN_DRY_RUN` is one of them: **setting it does not stop live trading**. The others include `PUMPFUN_CONFIG_PATH`, the preset and buy-size names, three alert aliases and 41 strategy names from `STRATEGY.md`.
  - They were removed from the manuals, and `ENVIRONMENTAL-VARIABLES.md` §3.15 maps each one to what to use instead.
  - `config/env.py` keeps them in `UNREAD_ENV_VARS`; `unread_env_warnings()` reports names only, never values.
  - `TradingBot._warn_unread_env_vars()` logs a warning at startup for each one that is set, and alerts on `PUMPFUN_DRY_RUN`.
  - They were deliberately **not** wired up, because an operator environment may hold them unnoticed.
  - `tests/unit/config/test_env.py` fails if a name in the §2 matrix of the manual is not read by the code, or if an `UNREAD_ENV_VARS` name starts being read.
- **BUG-143 (Low):** the test suite leaked outside its sandbox in two ways. Test bots wrote `events.jsonl` into the working directory, and a test posted a real Discord webhook from an alert worker thread past the DNS guard (through `HTTPS_PROXY`, or after the per-test guard was undone). `tests/conftest.py` now does three things:
  - sets `PUMPFUN_EVENT_LOG_PATH` to `tmp_path`;
  - removes `HTTP(S)_PROXY` / `ALL_PROXY` (both cases) in every test;
  - installs the DNS guard for the whole session in `pytest_configure`.

  A stray `events.jsonl` / `bot.log` in the main checkout's root comes from test runs before this fix and can be deleted.

---

## 6. Rules these changes added (also in `AGENTS.md`)

- **[RISK] A Ratchet Only Moves Up:** build ratchets from a persisted running peak, and test the giveback with closed trades as well as marked ones.
- **[DOCS] A Documented Variable Must Be Read:** grep the code before documenting a variable, alias or default. Don't silently wire up a long-documented name; warn first.
- **[TESTS] Proxies And Threads Bypass The DNS Guard:** keep every file a bot writes inside `tmp_path`, and capture alerts in tests (`bot._send_alert = sent.append`).
- `pumpfun-drill` entry in the command surface: drive time through `TradingBot.clock`.
- `docs/FEATURES.md` now runs §1–41 (§38 FEAT-66, §39 FEAT-67, §40 FEAT-68, §41 FEAT-69). The next free FEAT-ID is **FEAT-70**; the next free bug ID is **BUG-144**.

Guards that fail when a rule is broken:
- `tests/unit/test_suite_layout.py`: every source module needs `tests/unit/<pkg>/test_<module>.py`; every RESOLVED bug needs a `@pytest.mark.regression("BUG-xx")` test; every regression tag must name a bug that exists in `BUGS.md`.
- `test_every_config_field_survives_a_config_file`: a new `TradingBotConfig` field must also go into `resolve_strategy_config`. rc.4 added **no** new config field.
- `tests/integration/test_golden_replay.py`: bot decisions are pinned. It is unchanged by rc.4, because the engine-level breaker defaults to off.

---

## 7. Docs touched (so you know where the truth lives)

| File | What changed |
|---|---|
| `docs/CLI-COMMANDS.md` | §1 binaries, §4 replay flags (`--initial-cash` default, `--no-circuit-breaker`), §5 audit `verdict` flags, exit codes, Recipe 5c, §8.6 `pumpfun-drill`, §9 matrix |
| `docs/REPLAY-ENGINE.md` | Breaker and starting-cash bullets, parity notes, provenance in captures |
| `docs/AUDIT-TOOL.md` | `run_started` record type, verdict section |
| `docs/ENVIRONMENTAL-VARIABLES.md` | `PUMPFUN_GIT_COMMIT`; unread names removed; §3.15 |
| `docs/USER-GUIDE.md`, `README.md` | Replay with breaker, verdict, Workflow 4b drills, binary list |
| `docs/RISK.md`, `docs/STRATEGY.md` | Ratchet formula uses peak realized PnL; strategy "Environment Variables" lines corrected |
| `docs/dev/RUNBOOK.md` | §3 step 4 provenance check, §6.1 parity note, §6.3 replay gate and Stage 0 judged by the verdict, §7.1 scripted drills / §7.2 manual drills, §9 commands |
| `docs/dev/RELEASE-GATE.md` | §1 status table brought up to date, §2.3 drills item, §3.2 verdict item, §5 release-record fields (provenance, drills, verdict hash) |
| `docs/dev/STRATEGY-PIVOT.md` | §5 go / no-go now = `configs/verdict_rules.json` |
| `docs/dev/TESTING.md` | Isolation done by `conftest.py` |
| `docs/dev/TODO.md` | Sprint 24A drill and Stage 0 items reworded; **still open** (nothing moved to `DONE.md`) |
| `CHANGELOG.md` | `[Unreleased]`: Added (FEAT-66…69), Changed, Fixed (BUG-141…143) |

---

## 8. How to verify (in the rc.4 worktree, with its own venv activated)

```bash
nox -s format lint mypy tests package           # full gate; tests on every installed 3.11–3.14
pumpfun ops drill --report /tmp/rc4-drills.json # scripted drills, exit 1 on failure
pumpfun-audit verdict --path /dev/null --rules configs/verdict_rules.json --json | jq -r .rules_sha256   # rule hash
pumpfun-replay --path <capture> --config configs/canary.json --mode summary   # breaker on, paper wallet
pumpfun-replay --path <capture> --config configs/canary.json --compare-audit <audit_trail> --mode summary
```

None of these touch the runtime directory or the network. Don't point them at files inside `runtime/` unless the operator has copied them out for you.

---

## 9. Open work after rc.4

1. Run the full gate on the Mac (`nox -s tests`, `nox -s package`) and in CI. Fix anything that differs from the Linux run.
2. Release branch `release/v0.3.0rc4`: bump `pyproject.toml` to `0.3.0rc4` and turn `[Unreleased]` into `[0.3.0-rc.4]` with a release record (template in `RELEASE-GATE.md` §5, including the drill report, the provenance fields and the verdict rules hash). Tag only after the gate passes.
3. Before the next paper run: copy `configs/verdict_rules.json` into the runtime `configs/` (the operator does this), record its hash, then check the run's `run_provenance` in `bot_status.json` (`RUNBOOK.md` §3 step 4).
4. Read out the rc.3 72 h runs when they finish (`RUNBOOK.md` §6.3), and judge them with `pumpfun-audit verdict` as evidence only. That rule was not pre-registered for rc.3.
5. Still open from `TODO.md`:
   - manual drills on the paper deployment (§7.2);
   - Stage 0 / Stage 1;
   - mainnet checks of BUG-129 (`entry_price_source: live_fill`), BUG-138 (fee tiers) and BUG-123 (PumpSwap sell) on the first canary trades.
6. Not built, candidates for later FEAT-IDs:
   - refusing to start on a dirty checkout or on a config that differs from the release record (FEAT-68);
   - scripted versions of the process-level drills (FEAT-69).
