# Release Gate & Live Capital Gate

What must be true **before a release ships** and **before real capital is
put behind a lane**. A reusable checklist, not a status log: run it for every
release or capital stage, then record the outcome in a release record
([§5](#5-release-record)) and the `CHANGELOG.md` entry for that version.

- **What to build** is in [`TODO.md`](TODO.md); **how to operate** in
  [`RUNBOOK.md`](RUNBOOK.md); known defects in [`BUGS.md`](BUGS.md).
- The engine has its own gate in trading-core. A trading-pump release runs
  on a tagged trading-core release that passed it.

pumpfun-trading's gate (pumpbot, with its canary config, drills and the Web
UI funding and security gates) is [archived](../archive/pumpfun-trading/dev/RELEASE-GATE.md);
the funding gate (§3.7 there) and the hosted security gate (§4 there) moved
to trading-core with the Web UI.

| Gate | When it runs | Question it answers |
|---|---|---|
| **Release gate** ([§2](#2-release-gate-every-release)) | Every tagged release, before it runs a counted paper run or a funded wallet | Is this build correct, safe and recoverable? |
| **Live capital gate** ([§3](#3-live-capital-gate)) | Before each capital stage and after any release that touches the money path | Does the lane make money after every cost, and do the books match the chain? |

## 1. Current Status

| Item | Status | Evidence |
|---|---|---|
| Release gate for `v0.4.0rc2` (the rc.9 build, on trading-core `v0.2.0`) | Partly run (2026-10-29): `nox` pass on Linux, 100% coverage on 3.11–3.14. The rc.1 smoke run found BUG-159 and BUG-160 (a devnet endpoint, nothing read). Still to do: CI on the tag, a smoke run with pool readings and a matching replay, the restart drill, the secrets spot-check ([`TODO.md`, Migration gate](TODO.md#migration-gate-before-pumpfun-trading-is-deleted)) | [`CHANGELOG.md`](../../CHANGELOG.md) 0.4.0-rc.2 |
| Live capital stage | **Stage 0 not passed.** Every pumpbot lane was NO-GO (rc.1 to rc.8). FEAT-76 replayed on the rc.8 rows: NO-GO on count and interval, in-sample (STRATEGY-PIVOT §6.14). Next: a 72 h paper run on fresh data | [`STRATEGY-PIVOT.md` §6](STRATEGY-PIVOT.md#6-results-log) |
| Live execution | Not built: `LiveExecutor` refuses every order | [`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane) |
| Mainnet-verified money paths | Pump.fun curve `buy` / `sell` layout (BUG-34, pumpbot). Not verified on a real trade: the PumpSwap buy (not built), the PumpSwap sell (BUG-123), the fee tier a fresh graduate pays | `BUGS.md` |
| Reconciliation | Not ported (pumpbot's `reconcile`); needed before Stage 1 | [`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane) |

## 2. Release Gate (every release)

Run from a clean checkout of the release commit, against the trading-core
tag it will run on.

### 2.1 Code quality
- [ ] `nox -s format` produces no changes
- [ ] `nox -s lint` passes with 0 findings (ruff and flake8)
- [ ] `nox -s mypy` passes with 0 errors

### 2.2 Tests and coverage
- [ ] `nox -s tests` passes with 0 failures, 0 errors and no unexpected skips on **every supported interpreter** (3.11, 3.12, 3.13, 3.14; one CI job each). Locally nox skips interpreters that are not installed, so the CI matrix is the evidence
- [ ] Coverage (statements + branches) is **100%** (`fail_under` in `pyproject.toml` is never lowered)
- [ ] The collected test count is not lower than the previous release, unless the release notes explain the removal
- [ ] Every bug resolved in this release has a regression test tagged `@pytest.mark.regression("BUG-xx")` (`unit/test_suite_layout.py` enforces it)

### 2.3 Trading behaviour
- [ ] `trading-pump replay` of the reference capture (the rc.8 run A graduation rows, or a newer one named in the release record) at the release's example config gives the same positions and net as the previous release, or every difference is explained in the release notes
- [ ] The integration test (`tests/integration/test_module_plugin.py`) runs a paper buy and take profit through the real engine
- [ ] Any change to instruction layouts, account lists, fees or Jito submission is simulated against mainnet (`simulateTransaction`) before release, as was done for BUG-34, and pinned to real account bytes in tests (BUG-123)

### 2.4 Security and secrets
- [ ] No secrets in tracked files: `git grep -nIE "(private_key|secret_key|api_key|webhook|password)\s*[:=]\s*['\"][^'\"]{8,}" -- ':!*.md' ':!trading_pump/tests/*'` returns nothing that is a real credential
- [ ] The status file, audit trail, events, log and capture of the paper run contain no key material and no keyed URL (spot-check them)
- [ ] Dependency changes reviewed; no new runtime dependency without a reason in the release notes
- [ ] `nox -s audit` (pip-audit) reports no known vulnerability
- [ ] `nox -s package` passes: the wheel ships no `trading_pump/tests/` and carries the `Private :: Do Not Upload` classifier (proprietary: never publish)

### 2.5 Persistence and recovery
- [ ] The restart drill ([`RUNBOOK.md` §6](RUNBOOK.md#6-drills)) passes on the release build in paper mode: a held position is restored and priced from its pool

### 2.6 Documentation
- [ ] `CHANGELOG.md` entry written ([§6](#6-versioning-policy))
- [ ] `TODO.md` items ticked only when the code matches the claim
- [ ] `BUGS.md` statuses updated; new variables in `docs/ENVIRONMENT.md` (the test checks the table), new settings in `docs/CONFIGURATION.md`, new commands in `docs/CLI.md`

**Result:** the release gate passes only when every box is ticked.

## 3. Live Capital Gate

The release gate shows the build is correct. It does not show the lane makes
money after fees, tips and rent. The live capital gate does that in stages,
with the smallest amount at risk.

### 3.1 Stages

| Stage | Capital | Duration | Entry condition |
|---|---|---|---|
| **0 – Paper pilot** | None (`"mode": "paper"`) | ≥ 72 h continuous on live data | Release gate passed |
| **1 – Live canary** | A dedicated hot wallet holding only what you can afford to lose entirely | 1–2 weeks and ≥ 100 closed trades | Stage 0 passed; live execution built and one live round trip reconciled ([`TODO.md`](TODO.md#live-gate-for-the-pumpswap-lane)) |
| **2 – Scale-up** | `order_size` / exposure caps raised by at most 2× per step | ≥ 1 week per step | Stage 1 passed; previous step passed |

Any release that changes the money path (execution, SDK, pricing, fees,
sizing, exits) sends the lane back to **Stage 0** for at least 24 h before it
trades live again.

### 3.2 Stage 0 – Paper pilot exit criteria
Procedure: [`RUNBOOK.md` §3](RUNBOOK.md#3-a-paper-run-that-counts).
- [ ] 72 h continuous with 0 unhandled exceptions; memory stable
- [ ] Feed and RPC degradations observed and recovered without a restart (or forced by the drills)
- [ ] At least one take profit, one stop and one max-hold exit fired as configured
- [ ] Alerts delivered for entries, exits and any breaker lock
- [ ] The capture covers the whole run (oldest row at the start, BUG-157) and its replay matches the run
- [ ] `trading-core-audit verdict --rules configs/verdict_rules.json` is **GO**, with the rule file unchanged since the run started (the sha256 in the release record)

### 3.3 Stage 1 – Live canary configuration
A copy of `configs/paper.example.json` with `"mode": "live"` (and `--live`),
its own `status_path` / `audit_log_path`, and only these changes:

```json
{
  "mode": "live",
  "order_size": 0.02,
  "risk": {"max_total_exposure": 0.06, "max_position_size": 0.02, "max_active_positions": 3,
           "max_loss_per_trade": 0.02, "reserve_balance": 0.05},
  "breaker": {"max_daily_drawdown_pct": 0.10, "max_cumulative_drawdown_pct": 0.25}
}
```

The lane's rule and exits stay exactly as in the Stage 0 run that passed.
Jito tip: the value chosen by the tip experiment ([`TODO.md`](TODO.md#live-gate-for-the-pumpswap-lane)).

### 3.4 Stage 1 – Daily reconciliation and exit criteria
Every canary day, record in the release record: the wallet SOL balance at
the start and end of the day (on chain), the day's net PnL from the audit
trail (`trading-core-audit pnl --date-from <day>`), the number of closed
trades, and fees, tips and rent paid; and the reconcile result once ported.

Promotion to Stage 2 requires **all** of:
- [ ] ≥ 100 closed trades
- [ ] Net PnL after fees, tips and rent positive over the whole canary
- [ ] The daily wallet delta matches the audit trail within **max(0.002 SOL, 5%)** every day; a larger gap is explained and fixed before continuing
- [ ] 0 positions lost from tracking (every token balance maps to a tracked or closed position)
- [ ] 0 duplicate sells and 0 sells for tokens not held
- [ ] The circuit breaker never had to be overridden by hand

### 3.5 What stays off until proven

| Feature / setting | Reason | Condition to enable |
|---|---|---|
| Live mode | `LiveExecutor` refuses; the PumpSwap buy is not built | The live-gate items in `TODO.md` |
| `lane.screen_entries` | The rule was registered without screening | A paper run with it on beats one without, on the same days |
| A second lane or rule | Every rule must pass its own Stage 0 | Its own pre-registered verdict |
| Replay output as proof | A replay of the data a rule came from checks the code, not the rule | A paper run on fresh data |

### 3.6 Stop triggers (any stage)
Stop, drop back one stage and open a `BUGS.md` entry if any of these happen:
- a day's realized loss exceeds the daily drawdown, or the breaker locks twice in a week
- the daily wallet reconciliation gap exceeds the tolerance and cannot be explained
- a position is lost from tracking, sold twice, or sold when not held
- an unhandled exception, crash loop or memory growth that needs a restart
- any key material appears in a log, status, event or capture file

## 4. Hosted platform

The hosted Web UI and its security gate are trading-core's (its
`docs/dev/TODO.md`, Web UI). Nothing in this module may hold a key other
than through `PUMPFUN_PRIVATE_KEY`.

## 5. Release Record

One record per release (or capital stage) in the `CHANGELOG.md` entry, or a
linked file under `docs/dev/releases/`. Outcomes, not terminal output.

```markdown
### Release record – vX.Y.Z (YYYY-MM-DD)
- Commit: <sha>; trading-core: <tag>
- Run provenance (the `run_started` audit record of each paper / live run): versions, `git_commit` (`git_dirty` must be `false`), settings file and its sha256, module settings
- Release gate: PASS / FAIL (failed items: …)
- Tests: <collected> collected, <passed> passed; coverage <n>% on 3.11–3.14
- Reference replay: unchanged / differences: …
- Paper verdict: rules sha256 <hash> recorded at <run start>; GO / NO-GO (failed checks: …)
- Mainnet simulation: done for … / not needed
- Capital stage after this release: 0 / 1 / 2 (order_size = …)
- Canary daily log: date | wallet Δ SOL | audit net PnL | gap | trades | fees + tips + rent
- Sign-off: <operator>
```

## 6. Versioning Policy

- Versions follow **Semantic Versioning** (`MAJOR.MINOR.PATCH`). While the version is `0.x`, a MINOR bump may contain breaking changes to settings keys, CLI flags or file formats, and the changelog must say so.
- **PATCH:** bug fixes with no settings or format change.
- **MINOR:** new features, new settings (with safe defaults), or changes to defaults.
- **MAJOR:** reserved for `1.0.0` (the first release that passes Stage 2) and later breaking changes.
- `CHANGELOG.md` follows *Keep a Changelog*; every entry lists the BUG / FEAT IDs it covers and links its release record. Write it before tagging.
- The numbering continues pumpfun-trading's (its last release was `v0.3.0rc8`; this repository's first is `0.4.0`). Tag releases as `vX.Y.Z` on the commit that passed the release gate. Only tagged versions run on a funded wallet.
