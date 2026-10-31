# Developer documentation

For whoever changes trading-pump's code. The operator's pages are in
[`docs/`](../USER-GUIDE.md); the engine's are in trading-core.

These pages follow one standard for trading-core and every module on it:
**trading-core's `docs/dev/DOCUMENTATION.md`** (layout, style, words,
versioning, capital stages, run names, records, IDs, history). When this
repository and the standard disagree, the standard wins and this repository
is fixed. Below is only what is particular to trading-pump.

## 1. The pages

| Page | What it holds |
|---|---|
| [`RELEASE-GATE.md`](RELEASE-GATE.md) | §1 what is true today (releases, runs, each lane's stage), §2 the release gate, §3 the capital gate and its four stages, §4 gates particular to this module, §5 the release-record template, §6 versioning |
| [`RUNBOOK.md`](RUNBOOK.md) | Operating a run: the `runtime-pump` folder, preflight, a smoke run, a counted run, incidents, the research recorders, drills |
| [`RESULTS.md`](RESULTS.md) | The results log: every run, replay and study since v0.2.3, with its verdict (continues `STRATEGY-PIVOT.md` §6) |
| [`runs/`](runs/README.md) | One record per run: pre-registration before the start, read-out at the end (rc.11, rc.11-tp20, pools-1, and pumpbot's two pilot logs) |
| [`TODO.md`](TODO.md) | Open work only: Now / Next / Later, then by subject, and what was not ported |
| [`DONE.md`](DONE.md) | Finished work under the heading it had in `TODO.md` (pumpfun-trading's Phases 0–5 and what is finished here) |
| [`BUGS.md`](BUGS.md) | Every bug since pumpfun-trading BUG-01: cause, fix and test, and where each fix lives after the split |
| [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md) | Venue features not built yet, by FEAT ID |
| [`TESTING.md`](TESTING.md) | The `nox` gate, CI, the test layout, isolation, markers, conventions |
| [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) | Decisions and why, as ADR-NNN (ADR-008 the test layout, ADR-009 the split onto trading-core) |
| [`COSTS.md`](COSTS.md) | What the project pays (subscriptions, RPC, data) and what a run costs; every new payment goes here |
| [`releases/`](releases/README.md) | Release records too long for `CHANGELOG.md` (none so far) |
| [`STRATEGY-PIVOT.md`](STRATEGY-PIVOT.md) | History: pumpfun-trading's v0.3.0 strategy plan (§1–§5); its results log moved to `RESULTS.md` |
| [`../archive/pumpfun-trading/`](../archive/pumpfun-trading/INDEX.md) | pumpfun-trading's documents as of v0.3.0rc8, frozen (only links are fixed) |

## 2. Workflow

```bash
cd ~/projects/git/trading
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11–3.14
pip install -e trading-core
pip install -e "trading-pump[dev]"
cd trading-pump && nox -s lint mypy tests
```

- **One branch per change.** A bug fix gets a `BUGS.md` row and section
  (next free BUG number is in the file), a `regression("BUG-<n>")` test
  and, when the lesson is general, a Learnings Log entry in
  [`AGENTS.md`](../../AGENTS.md).
- **Coverage stays at 100%** on 3.11–3.14; `fail_under` is never lowered.
- **Docs move with the code**, in the same commit: settings in
  `docs/CONFIGURATION.md`, variables in `docs/ENVIRONMENT.md` (a test checks
  it), commands in `docs/CLI.md`, shipped features in `docs/FEATURES.md`,
  unbuilt ones in `PROPOSED-FEATURES.md`, open work in `TODO.md`, every
  release in `CHANGELOG.md`.
- **Results and runs:** a counted run's record is written in `runs/` before
  it starts; every result, counted or not, gets a row and a section in
  `RESULTS.md`; what is running now is said only in `RELEASE-GATE.md` §1
  and `TODO.md`.
- **A new feature** takes the next free `FEAT-<n>` from trading-core's
  `docs/dev/PROPOSED-FEATURES.md` (one series across every repository) and
  bumps it there in the same pull request.
- **An engine change** goes to trading-core, with its own tests and bug ID
  (`TC-<n>`); this repository then requires the trading-core version that
  has it.
- **A release** is `vX.Y.Z`, never a pre-release
  ([`RELEASE-GATE.md` §6](RELEASE-GATE.md#6-versioning-policy)).
