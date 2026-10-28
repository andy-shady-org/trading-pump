# Developer & Internal Engineering Portal

Welcome to the internal engineering and developer portal for `pumpfun-trading`. This directory contains development backlogs, release criteria, operational runbooks, and bug tracking records for contributors, maintainers, and DevOps operators.

For user-facing manuals, trading strategy mathematics, and hosted web instance guides, refer to the [**Primary User Guide (`../USER-GUIDE.md`)**](../USER-GUIDE.md).

---

## 1. Engineering Documentation Directory

| Document | Primary Audience | Description |
| :--- | :--- | :--- |
| [**Sprint Backlog & Roadmap (`TODO.md`)**](TODO.md) | Developers / Leads | Open work only: Now / Next / Later, the open sprints of Phases 4b–6 (income track, strategy pivot, Platform Refactor, Hosted Web UI) and the Web UI funding gate. |
| [**Completed Work (`DONE.md`)**](../../../dev/DONE.md) | Developers / Leads | Archive of finished phases, sprints and items moved out of `TODO.md`, under their original headings. |
| [**Architecture Decision Records (`ARCHITECTURE-DECISIONS.md`)**](../../../dev/ARCHITECTURE-DECISIONS.md) | Architects / Developers | Accepted decisions for the Web UI stack (FastAPI, Vue 3 + Vuetify MD3), control plane, container-per-tenant isolation, key handling, database, docs tooling, and test layout. |
| [**Test Architecture & Migration Plan (`TESTING.md`)**](TESTING.md) | Developers / QA | Test-suite layout (mirrored `unit/`, `integration/`, `property/`, `support/`), markers, conventions, and the file-by-file migration map. |
| [**Documentation Plan (`DOCUMENTATION-PLAN.md`)**](DOCUMENTATION-PLAN.md) | Writers / Developers | Documentation gap analysis, Zensical / Material docs-site navigation, `mkdocs.yml` outline, and styling conventions. |
| [**Bug Tracker & Resolution Matrix (`BUGS.md`)**](../../../dev/BUGS.md) | QA / Developers | Identified edge cases, security considerations, unit conversion fixes, and root cause resolution histories. |
| [**Proposed Features & Roadmap (`PROPOSED-FEATURES.md`)**](PROPOSED-FEATURES.md) | Quant Traders / Architects | Candidate feature proposals, alpha generation strategies, and next-generation architectural enhancements under evaluation. |
| [**Operations Runbook (`RUNBOOK.md`)**](RUNBOOK.md) | SRE / Bot Operators | Runtime layout, preflight, startup/shutdown, paper pilot procedure, incident drills, daily wallet reconciliation, incident response and rollback. |
| [**Project Costs (`COSTS.md`)**](../../../dev/COSTS.md) | Maintainers / Operators | Subscriptions, one-off and crypto payments, and the measured running cost per bot (Helius RPC credits, PumpPortal trade data). |
| [**Release Gate & Live Capital Gate (`RELEASE-GATE.md`)**](RELEASE-GATE.md) | Release Managers / Operators | Per-release checklist, staged live capital gate (paper pilot → canary → scale-up), hosted security gate, release record template and versioning policy. |
| [**rc.4 Agent Hand-Off (`RC4-HANDOFF.md`)**](RC4-HANDOFF.md) | Coding agents / Maintainers | What changed for v0.3.0-rc.4 (BUG-127…143, FEAT-66…69), where the code is, the rules for working next to the running rc.3 bot, and what is still open. |
| [**Strategy Pivot (`STRATEGY-PIVOT.md`)**](../../../dev/STRATEGY-PIVOT.md) | Maintainers / Operators | Why launch sniping loses, the confirmed-momentum and pre-graduation strategy, cost model, Phase 4c sprints and go/no-go rules for v0.3.0. |
| [**Stage 0 Pilot Log – v0.2.1 (`releases/v0.2.1-stage0.md`)**](../../../dev/releases/v0.2.1-stage0.md) | Bot Operators / Quant Traders | v0.2.1 paper pilot: pre-start checks, checkpoint 0 and the close-out (closed as FAIL after the breaker tripped; BUG-112…115). |
| [**Stage 0 Pilot Log – v0.2.0 (`releases/v0.2.0-stage0.md`)**](../../../dev/releases/v0.2.0-stage0.md) | Bot Operators / Quant Traders | Checkpoint results of the v0.2.0 paper pilot: operations, screening, PnL, exit-criteria status and decision (could not pass: BUG-104). |

---

## 2. Development Workflow & Quality Gates

All contributions to `pumpfun-trading` must satisfy strict institutional-grade engineering standards before merging:

### A. Environment Setup
```bash
# Clone and configure virtual environment
git clone https://github.com/andy-shady-org/pumpfun-trading.git
cd pumpfun-trading/pumpfun-trading
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install nox
```

### B. Automated Linting & Code Quality
All code must pass strict formatting and linting checks via Ruff and Black:
```bash
nox -s format
nox -s lint
```

### C. Comprehensive Unit & Integration Testing
The test suite enforces a **mandatory minimum of 95% statement and branch coverage** across all modules:
```bash
nox -s tests
```
New tests follow the layout and conventions in [`TESTING.md`](TESTING.md).

---

## 3. Cross-Reference Index

* **User Manual & Operations**: [docs/USER-GUIDE.md](../USER-GUIDE.md)
* **Environment Variables Reference**: [docs/ENVIRONMENTAL-VARIABLES.md](../ENVIRONMENTAL-VARIABLES.md)
* **Complete CLI Reference Manual**: [docs/CLI-COMMANDS.md](../CLI-COMMANDS.md)
* **Financial Strategy & Wealth Blueprint**: [docs/STRATEGY.md](../STRATEGY.md)
* **Capital Protection & Risk Safeguards**: [docs/RISK.md](../RISK.md)
* **Terminal UI & Observability**: [docs/TERMINAL-UI.md](../TERMINAL-UI.md)
* **Web Dashboard Blueprint (FastAPI + Vuetify MD3)**: [docs/WEB-UI.md](../WEB-UI.md)
* **Complete Feature Catalog**: [docs/FEATURES.md](../FEATURES.md)
* **Historical Replay Backtester**: [docs/REPLAY-ENGINE.md](../REPLAY-ENGINE.md)
* **Forensic Audit & Accounting**: [docs/AUDIT-TOOL.md](../AUDIT-TOOL.md)
