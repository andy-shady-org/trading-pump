# Developer & Internal Engineering Portal

Welcome to the internal engineering and developer portal for `pumpfun-trading`. This directory contains development backlogs, release criteria, operational runbooks, and bug tracking records for contributors, maintainers, and DevOps operators.

For user-facing manuals, trading strategy mathematics, and hosted web instance guides, refer to the [**Primary User Guide (`../USER-GUIDE.md`)**](../USER-GUIDE.md).

---

## 1. Engineering Documentation Directory

| Document | Primary Audience | Description |
| :--- | :--- | :--- |
| [**Sprint Backlog & Roadmap (`TODO.md`)**](TODO.md) | Developers / Leads | Active engineering backlog, phased milestones (Phases 1–4), completed deliverables, and sprint task breakdowns. |
| [**Bug Tracker & Resolution Matrix (`BUGS.md`)**](BUGS.md) | QA / Developers | Identified edge cases, security considerations, unit conversion fixes, and root cause resolution histories. |
| [**Proposed Features & Roadmap (`PROPOSED-FEATURES.md`)**](PROPOSED-FEATURES.md) | Quant Traders / Architects | Candidate feature proposals, alpha generation strategies, and next-generation architectural enhancements under evaluation. |
| [**Operations Runbook (`RUNBOOK.md`)**](RUNBOOK.md) | SRE / Bot Operators | Preflight checklists, startup/shutdown procedures, incident response workflows, and deployment hardening. |
| [**Production Release Gates (`RELEASE-GATE.md`)**](RELEASE-GATE.md) | Release Managers / Leads | Formal quality gates, security review criteria, and sign-off checklists required prior to funded production deployments. |
| [**30-Day Execution Plan (`NEXT-30-DAYS.md`)**](NEXT-30-DAYS.md) | Core Contributors | Tactical 30-day sprint milestones and near-term delivery objectives. |

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

---

## 3. Cross-Reference Index

* **User Manual & Operations**: [docs/USER-GUIDE.md](../USER-GUIDE.md)
* **Complete CLI Reference Manual**: [docs/CLI-COMMANDS.md](../CLI-COMMANDS.md)
* **Financial Strategy & Wealth Blueprint**: [docs/STRATEGY.md](../STRATEGY.md)
* **Capital Protection & Risk Safeguards**: [docs/RISK.md](../RISK.md)
* **Terminal UI & Observability**: [docs/TERMINAL-UI.md](../TERMINAL-UI.md)
* **FastAPI Web Dashboard Blueprint**: [docs/WEB-UI.md](../WEB-UI.md)
* **Complete Feature Catalog**: [docs/FEATURES.md](../FEATURES.md)
* **Historical Replay Backtester**: [docs/REPLAY-ENGINE.md](../REPLAY-ENGINE.md)
* **Forensic Audit & Accounting**: [docs/AUDIT-TOOL.md](../AUDIT-TOOL.md)
