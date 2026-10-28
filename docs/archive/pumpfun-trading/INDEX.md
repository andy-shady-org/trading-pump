# pumpfun-trading documentation archive (v0.3.0rc8)

These are pumpfun-trading's documents as they stood at its last release,
v0.3.0rc8 (2026-10-28), moved here unchanged when this repository became the
trading-core module `trading-pump`. They describe the `pumpbot` runtime and
the commands, variables and lanes it had. The code they describe is in this
repository's history at tag `v0.3.0rc8`.

They are kept so nothing learnt is lost: the evidence behind every decision,
the user guides, the incident drills, the bug history. They are **not** a
guide to the current code. For that:

| Archived document | Current document |
|---|---|
| [README](README.md) | [README](../../../README.md) |
| [AGENTS](AGENTS.md) | [AGENTS](../../../AGENTS.md) (every learning kept) |
| [CONTRIBUTING](CONTRIBUTING.md) | [CONTRIBUTING](../../../CONTRIBUTING.md) |
| [USER-GUIDE](USER-GUIDE.md) | [USER-GUIDE](../../USER-GUIDE.md) |
| [ENVIRONMENTAL-VARIABLES](ENVIRONMENTAL-VARIABLES.md) | [ENVIRONMENT](../../ENVIRONMENT.md); engine variables in trading-core `docs/ENVIRONMENT.md` |
| [CLI-COMMANDS](CLI-COMMANDS.md) | [CLI](../../CLI.md); engine commands in trading-core `docs/CLI.md` |
| [STRATEGY](STRATEGY.md) | [STRATEGY](../../STRATEGY.md) |
| [FEATURES](FEATURES.md) | [FEATURES](../../FEATURES.md) (what became of every section) |
| [REPLAY-ENGINE](REPLAY-ENGINE.md) | [CLI: `trading-pump replay`](../../CLI.md#trading-pump-replay) |
| [RISK](RISK.md) | trading-core `docs/RISK.md` |
| [AUDIT-TOOL](AUDIT-TOOL.md) | trading-core `docs/AUDIT-TOOL.md` |
| [TERMINAL-UI](TERMINAL-UI.md) | trading-core `docs/TERMINAL-UI.md` |
| [WEB-UI](WEB-UI.md) | trading-core `docs/dev/WEB-UI.md` (Phase 6 moved with the engine) |
| [dev/README](dev/README.md) | [dev/README](../../dev/README.md) |
| [dev/TODO](dev/TODO.md) | [dev/TODO](../../dev/TODO.md) and trading-core `docs/dev/TODO.md` (split by owner) |
| [dev/PROPOSED-FEATURES](dev/PROPOSED-FEATURES.md) | [dev/PROPOSED-FEATURES](../../dev/PROPOSED-FEATURES.md) and trading-core `docs/dev/PROPOSED-FEATURES.md` |
| [dev/RUNBOOK](dev/RUNBOOK.md) | [dev/RUNBOOK](../../dev/RUNBOOK.md) |
| [dev/RELEASE-GATE](dev/RELEASE-GATE.md) | [dev/RELEASE-GATE](../../dev/RELEASE-GATE.md) |
| [dev/TESTING](dev/TESTING.md) | [dev/TESTING](../../dev/TESTING.md) |
| [dev/DOCUMENTATION-PLAN](dev/DOCUMENTATION-PLAN.md) | trading-core `docs/dev/TODO.md` (documentation site) |
| [dev/RC4-HANDOFF](dev/RC4-HANDOFF.md) | history only |

Documents that are still current stayed where they were and keep their
history: [CHANGELOG](../../../CHANGELOG.md), [BUGS](../../dev/BUGS.md),
[DONE](../../dev/DONE.md), [STRATEGY-PIVOT](../../dev/STRATEGY-PIVOT.md),
[COSTS](../../dev/COSTS.md),
[ARCHITECTURE-DECISIONS](../../dev/ARCHITECTURE-DECISIONS.md) and the
[release records](../../dev/releases/).

Changes made when archiving: relative links were rewritten so they still
resolve from the new location, and one link to the retired `deploy/` folder
became plain text. Nothing else was edited; use
`git log --follow docs/archive/pumpfun-trading/<file>` for each file's
history.
