# Release gate

What must be true **before a release runs anywhere that counts**, and
**before more money goes behind a lane**. §1 is the only place in this
repository that says where things stand; the rest is a checklist to run
for every release and every capital stage, with the outcome recorded in the
release record (§5) of the version's `CHANGELOG.md` entry and, for a run, in
its record in [`runs/`](runs/README.md).

- **What to build** is in [`TODO.md`](TODO.md); **how to operate** in
  [`RUNBOOK.md`](RUNBOOK.md); **what the runs showed** in
  [`RESULTS.md`](RESULTS.md); known defects in [`BUGS.md`](BUGS.md).
- The engine has its own gate in trading-core (its
  `docs/dev/RELEASE-GATE.md`). A trading-pump release runs on a tagged
  trading-core release that passed it.
- The numbering of stages, the verdict words and the versioning policy are
  trading-core's `docs/dev/DOCUMENTATION.md` (§5, §6); this page adds the
  durations, sizes and checks particular to trading-pump.

pumpfun-trading's gate (pumpbot, with its canary config, drills and the Web
UI funding and security gates) is
[archived](../archive/pumpfun-trading/dev/RELEASE-GATE.md); the funding gate
(§3.7 there) and the hosted security gate (§4 there) moved to trading-core
with the Web UI.

| Gate | When it runs | Question it answers |
|---|---|---|
| **Release gate** ([§2](#2-release-gate-every-release)) | Every tagged release, before it runs a counted run or a funded wallet | Is this build correct, safe and recoverable? |
| **Capital gate** ([§3](#3-capital-gate)) | Before each capital stage, and after any release that touches a lane's money path | Does the lane make money after every cost, and do the books match the chain? |

## 1. Current status

As of 2026-10-31.

| Item | Status | Evidence |
|---|---|---|
| Latest release | `v0.4.0rc5`, the pools-1 build, on trading-core `v0.2.2`. Release gate partly run: `nox` passes on Linux, 859 tests, 100% statement and branch coverage on 3.11–3.14, the FEAT-80 smoke test on the public RPC. Still to do: CI on the tag, the restart drill | [`CHANGELOG.md`](../../CHANGELOG.md) 0.4.0-rc.5 |
| Next release | `v0.4.0`: plain semantic versioning from now on, no more pre-releases (§6) | §6 |
| Runs | **rc.11**, counted: both lanes in paper, `v0.4.0rc4` on trading-core `v0.2.2`, from 2026-10-30 18:58:56 UTC to 2026-11-02 18:58:56 UTC (72 h). **rc.11-tp20**, exploratory and not counted: rc.11's config with TP +20% on both lanes, from 2026-10-31 06:00:15 UTC. **pools-1**, record-only (FEAT-80), `v0.4.0rc5`, from 2026-10-31 07:29:11 UTC. The next counted run is `pump-12` | [`runs/`](runs/README.md) |
| `pumpswap_momentum` (FEAT-76) | **Stage 1** (paper), in rc.11 with its own exits (TP +50%). rc.9, its first counted run, was stopped after 58.4 h: 55 positions, +0.034 SOL, **NO-GO on the count** (55 of 100), and it failed without the best 3 and on the interval | [`RESULTS.md` §6.19](RESULTS.md#619-rc9-and-rc10-stopped-early-why-the-instant-lane-crashed-2026-10-31) |
| `pumpswap_instant` (FEAT-78) | **Stage 1** (paper), in rc.11 under its own verdict. In-sample replay on rc.9's capture passed every check but the count; its first night in rc.11 lost (17 trades at −25% each), and its +50% take-profit is under review for `pump-12` | [`RESULTS.md` §6.18](RESULTS.md#618-rc9-and-rc10-replays-a-second-lane-and-wider-take-profits-2026-10-30), [§6.19](RESULTS.md#619-rc9-and-rc10-stopped-early-why-the-instant-lane-crashed-2026-10-31) |
| New non-graduate pools (FEAT-80) | Record-only; no lane and no rule yet | [`runs/pools-1.md`](runs/pools-1.md) |
| Passed Stage 1 | **No lane** yet | |
| Live execution | Not built: `LiveExecutor` refuses every order | [`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane) |
| Mainnet-verified money paths | Pump.fun curve `buy` / `sell` layout (BUG-34, pumpbot). Not verified on a real trade: the PumpSwap buy (not built), the PumpSwap sell (BUG-123), the fee tier a fresh graduate pays (checked on 94 third-party trades only, RESULTS §6.16) | [`BUGS.md`](BUGS.md) |
| Reconciliation | Not ported (pumpbot's `reconcile`); needed before Stage 2 | [`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane) |

## 2. Release gate (every release)

Run from a clean checkout of the release commit, against the trading-core
tag it will run on.

### 2.1 Code quality
- [ ] `nox -s format` produces no changes
- [ ] `nox -s lint` passes with 0 findings (ruff, black, flake8)
- [ ] `nox -s mypy` passes with 0 errors

### 2.2 Tests and coverage
- [ ] `nox -s tests` passes with 0 failures, 0 errors and no unexpected skips on **every supported interpreter** (3.11, 3.12, 3.13, 3.14; one CI job each). Locally nox skips interpreters that are not installed, so the CI matrix is the evidence
- [ ] Coverage (statements and branches) is **100%** (`fail_under` in `pyproject.toml` is never lowered)
- [ ] The collected test count is not lower than the previous release's, unless the release notes say why
- [ ] Every bug resolved in this release has a regression test tagged `@pytest.mark.regression("BUG-<n>")` (`unit/test_suite_layout.py` enforces it)

### 2.3 Trading behaviour
- [ ] `trading-pump replay` of the reference capture at the release's config gives the same positions and net as the previous release, or every difference is explained in the release notes. The reference is the one the last release record names: today the rc.9 capture, 2026-10-29 08:30 → 2026-10-30 17:54 UTC, at 125 bps (0.4.0-rc.4 record)
- [ ] The integration test (`tests/integration/test_module_plugin.py`) runs a paper buy and take profit through the real engine
- [ ] Any change to instruction layouts, account lists, fees or Jito submission is simulated against mainnet (`simulateTransaction`) before release, as was done for BUG-34, and pinned to real account bytes in tests (BUG-123)
- [ ] A smoke run (about 30 minutes, not counted) on the runtime that will run the release sees live data: pool readings in the capture, and the capture replays ([`RUNBOOK.md` §3](RUNBOOK.md#3-a-paper-run-that-counts))

### 2.4 Security and secrets
- [ ] No secrets in tracked files: `git grep -nIE "(private_key|secret_key|api_key|webhook|password)\s*[:=]\s*['\"][^'\"]{8,}" -- ':!*.md' ':!trading_pump/tests/*'` returns nothing that is a real credential
- [ ] The status file, audit trail, events, log and capture of the smoke run contain no key material and no keyed URL (spot-check them)
- [ ] Dependency changes reviewed; no new runtime dependency without a reason in the release notes
- [ ] `nox -s audit` (pip-audit) reports no known vulnerability
- [ ] `nox -s package` passes: the wheel ships no `trading_pump/tests/` and carries the `Private :: Do Not Upload` classifier (proprietary: never published)

### 2.5 Persistence and recovery
- [ ] The restart drill ([`RUNBOOK.md` §6](RUNBOOK.md#6-drills)) passes on the release build in paper mode: a held position is restored and priced from its pool

### 2.6 Documentation
- [ ] `CHANGELOG.md` entry and release record written (§5, §6)
- [ ] `TODO.md` items ticked only when the code matches the claim
- [ ] `BUGS.md` statuses updated; new variables in `docs/ENVIRONMENT.md` (the test checks the table), new settings in `docs/CONFIGURATION.md`, new commands in `docs/CLI.md`, shipped features in `docs/FEATURES.md`
- [ ] Every counted run this release starts has its record in [`runs/`](runs/README.md), committed before the start

**Result:** the release gate passes only when every box is ticked.

## 3. Capital gate

The release gate shows the build is correct. It does not show a lane makes
money after fees, tips and rent. The capital gate does that, one lane at a
time, in four stages with the least money at risk first. Each stage has its
own pre-registered verdict: **GO**, **NO-GO** or **INCONCLUSIVE**.

### 3.1 Stages

| Stage | Name | Money at risk | Evidence and duration | Leaves the stage when |
|---|---|---|---|---|
| **0** | Evidence | None | A replay through `trading-pump replay` (the real engine and module) or a study on recorded captures, at 125 bps a side with a 200 bps stress and the paper entry delay | The rule is written down, its costs are measured, and it is positive in both halves of a capture it was not found on; the rule is then fixed for Stage 1 |
| **1** | Paper | None (`"mode": "paper"`: paper fills on live pools) | A counted paper run of **≥ 72 h** continuous on live data, pre-registered in `runs/` (§3.2) | Its verdict is **GO** |
| **2** | Live canary | A dedicated hot wallet holding only what you can afford to lose entirely; `order_size` 0.02 SOL (§3.3) | 1–2 weeks and **≥ 100 closed positions**, reconciled against the chain every day (§3.4) | Its verdict is **GO** and the books matched every day |
| **3** | Scale-up | `order_size` and exposure caps raised by at most 2× a step | One counted live run of ≥ 1 week per step | Each step's verdict is **GO**; the lane is then in production |

- **A release that changes a lane's money path** (pricing, fees, fills,
  sizing, exits, execution, the SDK) sends **that lane** back to Stage 1: a
  counted paper run on the new release before it trades live again.
- **A lane that fails a stage goes back one stage.** A new rule, or a
  changed one (another entry band, another take-profit), starts again at
  Stage 0.
- **Lanes climb apart.** Each signal and position carries its lane as its
  `strategy`, and each lane has its own verdict file (`"strategy"` set).
  trading-core 0.2.3's per-strategy limits and pauses (FEAT-81) let one
  engine hold lanes at different stages.

> [!NOTE]
> **Old stage numbers.** Records written before 2026-10-31 (release records
> in `CHANGELOG.md`, `RESULTS.md` up to §6.19, the pumpbot pilot logs in
> `runs/`, the archive) number the stages from paper: their **Stage 0** is
> Stage 1 here (paper), their **Stage 1** is Stage 2 (live canary), their
> **Stage 2** is Stage 3 (scale-up). Stage 0, Evidence, had no number then.

### 3.2 Stage 1: paper exit criteria
Procedure: [`RUNBOOK.md` §3](RUNBOOK.md#3-a-paper-run-that-counts).
- [ ] The run record (`runs/<run>.md`) was committed before the start: the question, both tags and commits, the config's sha256 and one verdict file per lane with its sha256
- [ ] 72 h continuous with 0 unhandled exceptions; memory stable
- [ ] Feed and RPC degradations observed and recovered without a restart (or forced by the drills); any window with no healthy RPC endpoint is named in the read-out
- [ ] At least one take profit, one stop and one max-hold exit fired as configured, per lane
- [ ] Alerts delivered for entries, exits and any breaker lock or strategy pause
- [ ] The capture covers the whole run (oldest row at the start, BUG-157) and its replay matches the run
- [ ] `trading-core-audit verdict --rules configs/verdict-<run>-<lane>.json` is **GO** for the lane, with the rule file unchanged since the start (its sha256 matches the run record)

### 3.3 Stage 2: live canary configuration
A copy of the Stage 1 config with `"mode": "live"` (and `--live`), its own
data folder and file paths, and only these changes:

```json
{
  "mode": "live",
  "order_size": 0.02,
  "risk": {"max_total_exposure": 0.06, "max_position_size": 0.02, "max_active_positions": 3,
           "max_loss_per_trade": 0.02, "reserve_balance": 0.05},
  "breaker": {"max_daily_drawdown_pct": 0.10, "max_cumulative_drawdown_pct": 0.25}
}
```

The lane's rule and exits stay exactly as in the Stage 1 run that passed. A
lane that is not in Stage 2 is off in the live config (`"enabled": false`
in its `module_settings` section). Jito tip: the value chosen by the tip
experiment ([`TODO.md`](TODO.md#live-gate-for-the-pumpswap-lane)).

> [!WARNING]
> A live config spends real SOL from the wallet in `PUMPFUN_PRIVATE_KEY`.
> Use a wallet that holds only the stage's capital, and check every lane's
> `enabled` before the first start.

### 3.4 Stage 2: daily reconciliation and exit criteria
Every canary day, record in the run record: the wallet SOL balance at the
start and end of the day (on chain), the day's net PnL from the audit trail
(`trading-core-audit pnl --date-from <day>`), the number of closed
positions, the fees, tips and rent paid, and the reconcile result once it is
ported.

Promotion to Stage 3 requires **all** of:
- [ ] ≥ 100 closed positions
- [ ] Net PnL after fees, tips and rent positive over the whole canary
- [ ] The daily wallet delta matches the audit trail within **max(0.002 SOL, 5%)** every day; a larger gap is explained and fixed before continuing
- [ ] 0 positions lost from tracking (every token balance maps to a tracked or closed position)
- [ ] 0 duplicate sells and 0 sells of tokens not held
- [ ] The circuit breaker never had to be overridden by hand

### 3.5 What stays off until proven

| Feature / setting | Reason | Condition to enable |
|---|---|---|
| Live mode | `LiveExecutor` refuses; the PumpSwap buy is not built | The live-gate items in `TODO.md` (§4.2), then a lane's Stage 1 **GO** |
| `lane.screen_entries` | The rule was registered without screening | A changed rule: Stage 0, then a Stage 1 run with it on that beats one without, on the same days |
| A lane beyond the two in Stage 1, or a changed rule | Every rule climbs its own stages. The instant lane (FEAT-78) is in Stage 1 under its own verdict in rc.11; a lower or adaptive take-profit for it is a changed rule | Its own Stage 0 evidence, then its own pre-registered Stage 1 run |
| A lane on new non-graduate pools (FEAT-80) | Only recorded so far (pools-1); no rule exists | A read-out that shows an edge after costs (Stage 0), then a pre-registered Stage 1 run |
| Replay output as proof | A replay of the data a rule came from checks the code, not the rule | A paper run on fresh data |

### 3.6 Stop triggers (any stage)
Stop, drop back one stage and open a `BUGS.md` entry if any of these happen:
- a day's realized loss exceeds the daily drawdown, or the breaker locks twice in a week
- the daily wallet reconciliation gap exceeds the tolerance and cannot be explained
- a position is lost from tracking, sold twice, or sold when not held
- an unhandled exception, crash loop or memory growth that needs a restart
- any key material appears in a log, status, event or capture file

## 4. Gates particular to trading-pump

### 4.1 Hosted platform
The hosted Web UI and its security gate are trading-core's (its
`docs/dev/TODO.md`, Web UI). Nothing in this module may hold a key other
than through `PUMPFUN_PRIVATE_KEY`.

### 4.2 Before any lane enters Stage 2
Live execution does not exist yet. Before the first live canary, every item
of [`TODO.md`, Live gate](TODO.md#live-gate-for-the-pumpswap-lane) is done:
the PumpSwap buy builder checked against real mainnet transactions,
`LiveExecutor` with costs from the transaction meta, `reconcile` ported, one
live round trip at the smallest size reconciled, and the tip experiment.

## 5. Release record

One record per release, in its `CHANGELOG.md` entry, or in
`docs/dev/releases/vX.Y.Z.md` linked from it when it is too long
([`releases/`](releases/README.md)). Outcomes, not terminal output. The
template is the standard's (trading-core's `docs/dev/DOCUMENTATION.md`
§8.1):

```markdown
### Release record – vX.Y.Z (YYYY-MM-DD)
- Commit: <the merge commit on main>; trading-core: vA.B.C
- Release gate: PASS, or the items not yet done
- Tests: <n> collected, all passed on 3.11–3.14; coverage 100%
- Checked: what was run against live data or a replay, and what it showed
- Runs: the counted runs this release starts (links to docs/dev/runs/)
- Capital stage: each lane's stage after this release
```

trading-pump adds these lines when they apply:

```markdown
- Reference replay: unchanged / differences: … (§2.3)
- Smoke run: when, how long, what it saw
- Mainnet simulation: done for … / not needed
- Run provenance (the `run_started` audit record of each run): versions, `git_commit` and `module_git` (`git_dirty` must be `false`), settings file and its sha256
- Pre-registration: in the run's record (docs/dev/runs/<run>.md), or here if no record exists
- Canary daily log (Stage 2): date | wallet Δ SOL | audit net PnL | gap | positions | fees + tips + rent
- Sign-off: <operator>
```

Records written before 2026-10-31 (`#### Release record – v0.4.0rcN`) keep
their form; their "Capital stage: 0 (paper)" is Stage 1 in today's numbering
(§3.1). rc.11's pre-registration is in its 0.4.0-rc.4 record and copied to
[`runs/rc11.md`](runs/rc11.md).

## 6. Versioning policy

§6.1–§6.4 are trading-core's `docs/dev/DOCUMENTATION.md` §5.1–§5.4, word
for word; section numbers inside them are the standard's (its §6 is §3
here, its §8.1 is §5 here, its §10 is "History" there). §6.5 adds what is
particular to trading-pump.

### 6.1 The policy

**Semantic versioning, `MAJOR.MINOR.PATCH`.** While the version is `0.x`, a
MINOR bump may change settings keys, CLI options or file formats, and the
changelog says so under **Changed** and **Upgrading**. `1.0.0` is the first
release with a lane that passed Stage 3 (§6). Tag `vX.Y.Z` on the commit that
passed the release gate.

| Bump | When | Examples |
|---|---|---|
| **PATCH** (`0.2.3` → `0.2.4`) | Fixes and internal changes: no new settings key, no new CLI option, no file-format change, no change to the module contract | a bug fix; a refactor that changes nothing; docs |
| **MINOR** (`0.2.3` → `0.3.0`) | Anything a user or a module can see: a new feature, a new settings key or CLI option (with a safe default), a changed default, a new module hook, a file-format change; while `0.x`, also breaking changes, listed under **Changed** and **Upgrading** | per-strategy limits (a new `strategies` key); a new `files()` hook |
| **MAJOR** (`1.0.0`, then `2.0.0`) | `1.0.0` as above; after it, a breaking change to settings, CLI, file formats or the contract | |

### 6.2 What 1.0.0 means in each repository

`1.0.0` means the same thing everywhere: **a lane has made money through
Stage 3.** A module goes to `1.0.0` with the release that its first Stage 3
lane runs on. trading-core and trading-scout have no lanes of their own:
they go to `1.0.0` with the first module that does, on the versions that
lane runs on.

### 6.3 Tags and releases

- **No pre-releases.** No `rc`, `alpha` or `beta` tags or versions. A version
  that needs a fix after it is tagged gets a new PATCH, never a re-tag.
  (trading-pump's `v0.4.0rc1` to `v0.4.0rc5` were the last; its next release
  is `v0.4.0`.)
- **The tag** is annotated, signed and private: `git tag -s vX.Y.Z -m "vX.Y.Z"`
  with the operator's SSH signing key (trading-core's `SECURITY.md`, "Signed
  releases"), on the merge commit on `main` that passed the release gate;
  `git tag -v vX.Y.Z`, then `git push origin vX.Y.Z`. Runtimes install and
  trust only signed tags, so **the tag is never created in the GitHub web
  UI** (a tag GitHub creates is unsigned). Tag rulesets on `v*` restrict
  updates and deletions.
- **The GitHub Release** is optional, made in the UI after the signed tag is
  pushed: "Draft a new release", choose the existing tag, the notes from the
  `CHANGELOG.md` entry. Nothing is published to a package index.
- **The version** lives in two places, changed in the release commit only:
  `pyproject.toml` (`version = "X.Y.Z"`) and the package's `__version__`.
- **The branch** is `release/vX.Y.Z`, holding the version bump, the
  `CHANGELOG.md` entry and its release record; merged by pull request.
- **Compatibility.** A module's release record names the trading-core tag it
  passed its gate on, and its `pyproject.toml` the lowest trading-core it
  needs. A runtime installs one pair of tags (`bin/install-release.sh <core
  tag> <module tag>`).
- **Only tagged versions run** a counted run or a funded wallet.

### 6.4 The changelog

[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), newest first:

```markdown
## [Unreleased]

## [0.3.0] - 2026-11-03

One or two sentences: what this release is for and whether it changes
behaviour. Says MINOR or PATCH and why.

### Added
- **Name (FEAT-81):** what it does for the operator, in one paragraph.
### Changed
### Fixed
- What was wrong, what it caused, what changed (TC-8).
### Removed
### Research
### Upgrading
- What an operator must do, or "Nothing to do".

### Release record – v0.3.0 (2026-11-03)
- ... (§8.1)
```

Sections appear only when they have entries, in this order: Added, Changed,
Deprecated, Removed, Fixed, Security, Research, Docs, Upgrading, then the
release record. Every entry names the FEAT and bug IDs it covers. Entries
written before this standard keep their headings (§10).

### 6.5 In trading-pump

- **The numbering continues pumpfun-trading's.** Its last release was
  `v0.3.0rc8`; this repository's first was `v0.4.0rc1` (2026-10-29).
- **`v0.4.0rc1` to `v0.4.0rc5` were the last pre-releases.** Their
  `CHANGELOG.md` headings (`0.4.0-rc.1` to `0.4.0-rc.5`) and tags stay as
  they are. The next release is **`v0.4.0`**, then `v0.4.1` or `v0.5.0` by
  the table in §6.1.
- **The tag goes on the merge commit** of `release/vX.Y.Z` into `main`:
  ```bash
  git tag -s v0.4.0 -m "v0.4.0"
  git push origin v0.4.0
  ```
- **The version** is in `pyproject.toml` and `trading_pump/__init__.py`
  (`__version__`); `pyproject.toml` also names the lowest trading-core the
  module needs (`trading-core>=…` under `dependencies`).
- **The runtime** is `runtime-pump`: `bin/install-release.sh <core tag>
  <pump tag>` builds one venv per pair of tags, and every counted run uses
  one ([`RUNBOOK.md` §1](RUNBOOK.md#1-runtime-layout)).
- **`1.0.0`** is the release that trading-pump's first Stage 3 lane runs on.
