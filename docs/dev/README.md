# Developer documentation

For maintainers of trading-pump. User-facing pages are in [`docs/`](../USER-GUIDE.md);
the engine's are in trading-core.

| Document | What |
|---|---|
| [`TODO.md`](TODO.md) | Open work only: the migration gate, FEAT-76, the live gate, research, and what was not ported (with where to find it) |
| [`DONE.md`](DONE.md) | Finished work under its original heading (pumpfun-trading's Phases 0–5, and what is finished here) |
| [`BUGS.md`](BUGS.md) | Every bug since pumpfun-trading BUG-01, root causes and fixes, and where each fix lives after the split |
| [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md) | Unbuilt venue features (FEAT-IDs continue pumpfun-trading's) |
| [`STRATEGY-PIVOT.md`](STRATEGY-PIVOT.md) | The evidence: every result since v0.2.3 (§6 results log) |
| [`RUNBOOK.md`](RUNBOOK.md) | Operating a run, incidents, the research recorders, drills |
| [`RELEASE-GATE.md`](RELEASE-GATE.md) | Release checklist, live capital gate, release record, versioning |
| [`TESTING.md`](TESTING.md) | The gate, CI, layout, isolation, markers, conventions |
| [`COSTS.md`](COSTS.md) | Subscriptions, payments, measured running cost per run |
| [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) | ADRs (ADR-009: the split onto trading-core) |
| [`releases/`](releases/) | Stage 0 logs of v0.2.0 and v0.2.1 |
| [`../archive/pumpfun-trading/`](../archive/pumpfun-trading/INDEX.md) | pumpfun-trading's documents as of v0.3.0rc8, unchanged |

## Workflow

```bash
cd ~/projects/git/trading
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11–3.14
pip install -e trading-core
pip install -e "trading-pump[dev]"
cd trading-pump && nox -s lint mypy tests
```

* One branch per change; a bug fix gets a `BUGS.md` row and section, a
  `regression("BUG-xx")` test and, when the lesson is general, a Learnings
  Log entry in [`AGENTS.md`](../../AGENTS.md).
* Coverage stays at 100% on 3.11–3.14; `fail_under` is never lowered.
* Docs move with the code: settings in `docs/CONFIGURATION.md`, variables in
  `docs/ENVIRONMENT.md` (a test checks it), commands in `docs/CLI.md`,
  shipped features in `docs/FEATURES.md`, unbuilt ones in
  `PROPOSED-FEATURES.md`, results in `STRATEGY-PIVOT.md` §6, open work in
  `TODO.md`, every release in `CHANGELOG.md`.
* An engine change goes to trading-core, with its own tests and bug ID
  (`TC-<n>`); this repository then pins the trading-core version that has it.
