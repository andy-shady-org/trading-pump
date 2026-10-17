# Release Gate & Live Capital Gate

This document defines what must be true **before a release ships** and **before more real capital is put behind the bot**. It is a reusable checklist, not a status log: run it for every release or capital stage, then record the outcome in a release record (see [§5](#5-release-record)) and the `CHANGELOG.md` entry for that version.

- **What to build** lives in [`TODO.md`](TODO.md). This file only says when something is safe to ship or fund.
- **How to operate** (startup, paper pilot, drills, incidents, rollback) lives in [`RUNBOOK.md`](RUNBOOK.md).
- Known defects and their status live in [`BUGS.md`](BUGS.md).

There are two independent gates:

| Gate | When it runs | Question it answers |
|---|---|---|
| **Release gate** ([§2](#2-release-gate-every-release)) | Every tagged release, before it is deployed to a funded instance | Is this build correct, safe and recoverable? |
| **Live capital gate** ([§3](#3-live-capital-gate)) | Before each capital stage (paper → canary → scale-up) and after any release that touches the money path | Does the bot actually make money, and do the books match the chain? |

A release can pass the release gate and still be held at its current capital stage. Capital is only increased when the live capital gate for the next stage passes.

---

## 1. Current Status

Update this table whenever a gate run finishes. Link the release record rather than pasting logs here.

| Item | Status | Evidence |
|---|---|---|
| Release gate for the current `main` | Not yet run against a tagged version | – |
| Live capital stage | **Stage 0 – Paper pilot: in progress on v0.2.0, cannot pass on this build** | [Stage 0 log](releases/v0.2.0-stage0.md): 14 h clean operationally; paper PnL invalid (BUG-104), corrected net negative; alerts not configured. BUG-104…107 fixed on branch `fix/stage0-bugs-104-107`; next Stage 0 needs a new tag, `require_holder_data` in `canary.json`, an alert provider and an empty `data/` |
| Net PnL measurement | Implemented on branch `sprint-24b-net-pnl` (fees, tips, rent per trade; `pumpfun-audit pnl` / `reconcile`, last result on the dashboard); release gate green (922 tests, coverage 96.3%); test-pass bugs BUG-97…101 fixed; cost parser checked read-only on real mainnet sells; the bot's own canary trades not yet reconciled | Sprint 24B (FEAT-49, BUG-96) |
| Funding gate for the Web UI ([§3.7](#37-funding-gate-for-the-web-ui)) | Not passed | – |
| Mainnet-verified money paths | Pump.fun `buy`/`sell` layout only (BUG-34) | `BUGS.md` |
| Open (mitigated) defects that limit live scope | BUG-37, BUG-55, BUG-59, BUG-90, BUG-92 (BUG-61 resolved in Sprint 24C) | See [§3.5](#35-features-that-must-stay-off-until-proven) |

---

## 2. Release Gate (every release)

Run from a clean checkout of the release commit. Commands use the nox sessions so they keep working while the test suite is restructured in Sprints 26–27 (see [`TESTING.md`](TESTING.md)); do not hard-code individual test file paths here.

### 2.1 Code quality
- [ ] `nox -s format` produces no changes
- [ ] `nox -s lint` passes with 0 findings
- [ ] `nox -s mypy` passes with 0 errors

### 2.2 Tests and coverage
- [ ] `nox -s tests` passes with 0 failures, 0 errors and no unexpected skips on **every supported interpreter** (3.11, 3.12, 3.13, 3.14; one CI job each). Locally nox skips interpreters that aren't installed, so the CI matrix is the evidence
- [ ] Total coverage (statements + branches, `branch = true`) ≥ **95%** (`fail_under` in `pyproject.toml` is never lowered)
- [ ] Collected test count is not lower than the previous release, unless the release notes explain the removal
- [ ] Every bug resolved in this release has a regression test (after Sprint 27: tagged `@pytest.mark.regression("BUG-xx")`, check with `pytest -m regression`)

### 2.3 Trading behaviour
- [ ] Replay parity: for runtime, strategy or execution changes, replaying the recorded datasets in `test-data/` gives the same decisions as the previous release, or every difference is explained in the release notes
- [ ] Risk controls exercised by the suite: stop-loss, trailing stop, tiered take-profit (2.0x / 3.5x / moonbag), daily drawdown breaker, emergency liquidation, exit retry queue
- [ ] Any change to instruction layouts, account lists, fees or Jito submission is simulated against mainnet (`simulateTransaction`) before release, as was done for BUG-34

### 2.4 Security and secrets
- [ ] No secrets in tracked files: `git grep -nIE "(private_key|secret_key|api_key|webhook|password)\s*[:=]\s*['\"][^'\"]{8,}" -- ':!*.md' ':!pumpfun_trading/tests/*'` returns nothing that is a real credential
- [ ] Logs, audit trail, events and status snapshot contain no key material (spot-check the files produced by the paper pilot)
- [ ] Dependency changes reviewed; no new runtime dependency outside an optional extra without a reason in the release notes
- [ ] `nox -s audit` (pip-audit) reports no known vulnerability in the dev environment
- [ ] `nox -s package` passes: the wheel ships no `pumpfun_trading/tests/` and carries the `Private :: Do Not Upload` classifier (proprietary: never publish to PyPI)

### 2.5 Persistence and recovery
- [ ] Status snapshot is written atomically and restores positions, cost basis, pool keys and the exit retry queue (BUG-39, BUG-45, BUG-72)
- [ ] Kill-and-restart drill from [`RUNBOOK.md` §7](RUNBOOK.md#7-incident-drills) passes on the release build in paper mode

### 2.6 Documentation
- [ ] `CHANGELOG.md` entry written (see [§6](#6-versioning-policy))
- [ ] `TODO.md` items ticked only when the code matches the claim (AGENTS.md Learnings Log)
- [ ] `BUGS.md` statuses updated; new environment variables or CLI flags documented

**Result:** the release gate passes only when every box is ticked. Record the outcome in a release record.

---

## 3. Live Capital Gate

The release gate shows the build is correct. It does not show the strategy makes money after fees and Jito tips. The live capital gate does that in stages, with the smallest possible amount at risk.

### 3.1 Stages

| Stage | Capital | Duration | Entry condition |
|---|---|---|---|
| **0 – Paper pilot** | None (`--paper-trade`) | ≥ 72h continuous on the live stream | Release gate passed |
| **1 – Live canary** | Dedicated hot wallet holding only what you can afford to lose entirely | 1–2 weeks and ≥ 100 closed trades | Stage 0 passed |
| **2 – Scale-up** | Increase `buy_amount_sol` / exposure caps by at most 2× per step | ≥ 1 week per step | Stage 1 passed; previous step passed |

Any release that changes the money path (execution, SDK, sizing, exits, risk) sends the bot back to **Stage 0** for at least 24h before it trades live again.

### 3.2 Stage 0 – Paper pilot exit criteria
Procedure: [`RUNBOOK.md` §6](RUNBOOK.md#6-paper-pilot-procedure).
- [ ] 72h continuous uptime with 0 unhandled exceptions and 0 event-loop stalls
- [ ] RSS memory stable (no monotonic growth; target ≤ 250 MB)
- [ ] Stream reconnects observed and recovered without a restart
- [ ] At least one stop-loss, one take-profit tier and one stagnant/max-hold exit fired as configured
- [ ] Circuit breaker and exit retry queue observed working (forced if needed, see the drills)
- [ ] Alerts delivered for entries, exits and breaker trips
- [ ] Simulated PnL is positive after modelled fees and tips (informational only; paper fills are optimistic)

### 3.3 Stage 1 – Live canary configuration
Start from the conservative preset and override only these fields in a dedicated config file:

```json
{
  "strategy_preset": "conservative",
  "dry_run": false,
  "paper_trade": false,
  "buy_amount_sol": 0.01,
  "max_position_size_sol": 0.01,
  "max_active_positions": 2,
  "max_total_exposure_sol": 0.03,
  "max_loss_per_trade_sol": 0.01,
  "max_daily_drawdown_pct": 0.10,
  "enable_cross_venue_arbitrage": false,
  "enable_mempool_backrunning": false,
  "enable_pre_graduation_harvesting": false,
  "enable_raydium_migration_sniping": false,
  "enable_copy_trading": false
}
```

Run with `pumpbot --config <canary.json> --headless` from a dedicated runtime directory (never the repository root) so status, audit and event files belong only to the canary.

### 3.4 Stage 1 – Daily reconciliation and exit criteria
Every day of the canary, follow [`RUNBOOK.md` §5.3](RUNBOOK.md#53-daily-wallet-reconciliation) and record the numbers in the release record:
- wallet SOL balance at the start and end of the day (on-chain)
- realized PnL for the day from the audit trail
- number of closed trades, fees and Jito tips paid

> Sprint 24B (FEAT-49) records fees, tips, rent and signatures on every trade: use `pumpfun-audit pnl` for the day's net PnL and `pumpfun-audit reconcile --wallet <pubkey> --start-balance <SOL>` for the wallet check (exit code 1 = gap above tolerance). Builds without Sprint 24B record **gross** PnL only; on those, sum fees and tips by hand from the transaction signatures, and do not start Stage 1 without one of the two.

Promotion to Stage 2 requires **all** of:
- [ ] ≥ 100 closed trades
- [ ] Net PnL after fees and tips is positive over the whole canary
- [ ] Daily wallet delta matches audit realized PnL within **max(0.002 SOL, 5%)** on every day; any larger gap is explained and fixed before continuing
- [ ] 0 positions lost from tracking (every on-chain token balance maps to a tracked or closed position)
- [ ] 0 duplicate sells and 0 sells for tokens not held
- [ ] Circuit breaker never had to be overridden by hand

### 3.5 Features that must stay off until proven
These stay disabled in Stages 1–2 until the listed condition is met and a release record shows it:

| Feature / config | Reason | Condition to enable |
|---|---|---|
| `enable_cross_venue_arbitrage`, `enable_mempool_backrunning` | BUG-37 and BUG-59 only mitigated; BUG-90 monitor is demo data | FEAT-40 delivered and both arbitrage directions simulated on mainnet |
| `enable_pre_graduation_harvesting` | BUG-38/42/43 fixes not yet observed live | Observed working in a ≥ 72h paper pilot |
| `enable_raydium_migration_sniping`, graduation exits via Raydium | BUG-36/44/50/51 fixes not mainnet-verified | Raydium buy and sell simulated on mainnet, then one live round trip at canary size |
| Geyser endpoint (`PUMPFUN_GEYSER_ENDPOINT`) | BUG-55 mitigated; no real gRPC transport, falls back to WebSocket | FEAT-39 delivered |
| `max_positions_per_mint` > 1 | BUG-92 clamps it to 1 | Per-mint pyramiding implemented |
| Replay/optimizer output as proof of profitability | BUG-61 is resolved (live sizing, exits and modelled costs), but the screener is not replayed and parity with live has not been shown yet | `pumpfun-replay --compare-audit` passes on a Stage 0 and a Stage 1 capture (`RUNBOOK.md` §6.1) |

### 3.6 Stop triggers (any stage)
Stop the bot, drop back one stage and open a `BUGS.md` entry if any of these happen:
- realized loss in one day exceeds the configured daily drawdown, or the breaker trips twice in a week
- the daily wallet reconciliation gap exceeds the tolerance and cannot be explained
- a position is lost from tracking, sold twice, or sold when not held
- an unhandled exception, crash loop or memory growth that needs a restart
- any key material appears in a log, snapshot or event file

### 3.7 Funding gate for the Web UI
The terminal UI funds the Web UI. Phase 6 in [`TODO.md`](TODO.md#phase-4b-terminal-income-track-highest-priority) starts only when **all** of these are true and recorded in a release record:
- [ ] Stage 1 passed and the bot runs at Stage 2 or above
- [ ] Cumulative net profit (after fees, tips and rent, reconciled against the wallet) covers the agreed Phase 6 budget plus at least one month of running costs
- [ ] Net profit positive for at least 4 consecutive weeks at the current stage
- [ ] No open stop trigger ([§3.6](#36-stop-triggers-any-stage)) in the last 2 weeks

If net profit turns negative for 2 consecutive weeks after the gate has passed, pause Phase 6 spending and return to Phase 4b tuning.

---

## 4. Hosted Web UI Security Gate (from Sprint 34)

Required before any hosted tenant uses real funds (see [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) ADR-003/ADR-004 and [`docs/WEB-UI.md`](../WEB-UI.md)):
- [ ] Wallet keys reach the worker only as an X25519 envelope; plaintext never touches the control plane, database, logs or disk
- [ ] Key buffers are zeroed after signer setup (Volatile Key Erasure norm)
- [ ] Tenant isolation tests pass: no cross-tenant reads via API, database or container network
- [ ] Agent API reachable only from the control plane network with a per-instance token
- [ ] Auth: OIDC/JWT sessions, passkey second factor, role checks on every mutating endpoint; every command written to `audit_events`
- [ ] Per-tenant quotas enforced before config reaches the bot's risk pipeline
- [ ] External security review of the key-ingestion path

---

## 5. Release Record

Keep one record per release (or capital stage) in the `CHANGELOG.md` entry, or in a linked file under `docs/dev/releases/`. Record outcomes, not raw terminal output.

```markdown
### Release record – vX.Y.Z (YYYY-MM-DD)
- Commit: <sha>
- Release gate: PASS / FAIL (failed items: …)
- Tests: <collected> collected, <passed> passed; coverage <n>% (branch <n>%)
- Replay parity: unchanged / differences: …
- Mainnet simulation: done for … / not needed
- Capital stage after this release: 0 / 1 / 2 (buy_amount_sol = …)
- Canary daily log: date | wallet Δ SOL | audit realized PnL | gap | trades | fees+tips
- Sign-off: <operator>
```

---

## 6. Versioning Policy

- Versions follow **Semantic Versioning** (`MAJOR.MINOR.PATCH`). While the version is `0.x`, a MINOR bump may contain breaking changes to config keys, CLI flags or file formats, and the changelog must say so.
- **PATCH:** bug fixes with no config or format change.
- **MINOR:** new features, new config keys (with safe defaults), or changes to defaults.
- **MAJOR:** reserved for `1.0.0` (first release that passes Stage 2) and later breaking changes.
- `CHANGELOG.md` follows *Keep a Changelog*; every entry lists the BUG/FEAT IDs it covers and links its release record. It lives at the repo root ([`CHANGELOG.md`](../../CHANGELOG.md)); write the entry before tagging.
- Tag releases as `vX.Y.Z` on the commit that passed the release gate. Only tagged versions run on a funded wallet.

---

## 7. Related References

- [`RUNBOOK.md`](RUNBOOK.md) – operator procedures, paper pilot, drills, incident response and rollback.
- [`TODO.md`](TODO.md) – sprint backlog and acceptance criteria.
- [`BUGS.md`](BUGS.md) – defect tracker and resolution matrix.
- [`TESTING.md`](TESTING.md) – test layout and markers used by the release gate.
- [`../RISK.md`](../RISK.md) – risk controls exercised by the gates.
