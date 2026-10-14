# AGENTS.md

## Project Overview

This repository contains the `pumpfun-trading` Python package, organized as a modular, high-performance automated trading runtime and quantitative toolkit designed for microcap Solana liquidity on Pump.fun bonding curves.

The project is intentionally structured around clean responsibility boundaries across streaming ingestion, MEV protection, execution SDK, algorithmic strategies, bot runtime lifecycle, terminal & web UI presentation, and forensic auditing.

---

## Package Structure

```text
pumpfun-trading/
├── pumpfun_trading/
│   ├── api/          # Public Pump.fun REST and coin discovery API client
│   ├── bot/          # Runtime orchestration, lifecycle state machine, risk controls, and audit trails
│   ├── cli/          # Dedicated CLI entry points (pumpbot, pumpfun-replay, pumpfun-audit, pumpfun-cli)
│   ├── config/       # Environment loading, configuration resolution, and settings validation
│   ├── engines/      # Historical market replay and paper-trading simulation engine
│   ├── execution/    # Transaction instruction builders and execution helpers
│   ├── ops/          # Structured logging (ANSI/NO_COLOR compliant) and telemetry monitoring
│   ├── sdk/          # Solana on-chain execution SDK, PDA/ATA derivations, and Jito MEV client
│   ├── services/     # Background service helpers and metadata ingestion
│   ├── storage/      # Durable status snapshot and audit persistence
│   ├── strategies/   # Modular signal generation, anti-rug heuristics, trailing exits, and presets
│   ├── streams/      # Yellowstone Geyser gRPC streaming client & zero-copy binary parsers
│   ├── ui/           # Rich alternate-screen live terminal dashboard
│   └── tests/        # Comprehensive unit and integration test suite (>=95% coverage)
```

---

## Documentation Architecture

The documentation is organized in a clear, audience-separated star topology:

### 1. User & Operator Manuals (`docs/`)
Accessible to end-users, quant traders, and bot operators; embedded into the FastAPI Web UI:

* [**`docs/USER-GUIDE.md`**](docs/USER-GUIDE.md): Central knowledge hub and primary onboarding portal for both hosted Web UI instances and operator Terminal UI mode.
* [**`docs/CLI-COMMANDS.md`**](docs/CLI-COMMANDS.md): Exhaustive command-line interface manual for all standalone binaries (`pumpbot`, `pumpfun-recorder`, `pumpfun-replay`, `pumpfun-audit`) and unified `pumpfun` subcommands.
* [**`docs/STRATEGY.md`**](docs/STRATEGY.md): Wealth generation blueprint, bonding curve pricing math ($P = \Delta y / \Delta x$), fractional Kelly bankroll management, multi-tier profit scaling, dynamic trailing stops, and anti-rug heuristic scoring.
* [**`docs/RISK.md`**](docs/RISK.md): Multi-tier capital preservation, position concentration caps, daily hard-stop circuit breakers (FEAT-09), startup on-chain reconciliation, and emergency exit queues.
* [**`docs/TERMINAL-UI.md`**](docs/TERMINAL-UI.md): Rich console dashboard manual, sub-millisecond slot latency telemetry, and multi-channel alerting (Discord, Slack, Telegram) for operator self-funding.
* [**`docs/WEB-UI.md`**](docs/WEB-UI.md): Architecture specification for the full-featured FastAPI web dashboard (FEAT-10), volatile in-memory keypair security (zero disk persistence), hot config mutations, and terminal UI deprecation roadmap.
* [**`docs/FEATURES.md`**](docs/FEATURES.md): Standardized catalog of completed architectural capabilities (FEAT-01 through FEAT-30).
* [**`docs/REPLAY-ENGINE.md`**](docs/REPLAY-ENGINE.md): Historical market replay and strategy backtesting simulator (`pumpfun-replay`).
* [**`docs/AUDIT-TOOL.md`**](docs/AUDIT-TOOL.md): Forensic trade accounting and telemetry inspection CLI (`pumpfun-audit`).

### 2. Developer & Engineering Artifacts (`docs/dev/`)
Internal engineering documentation for maintainers, contributors, and SRE:

* [**`docs/dev/README.md`**](docs/dev/README.md): Developer and contributor portal index.
* [**`docs/dev/TODO.md`**](docs/dev/TODO.md): Sprint backlog, milestone tracking (Phases 1–4), and architectural tasks.
* [**`docs/dev/BUGS.md`**](docs/dev/BUGS.md): Bug tracker, root cause analyses, and resolution verification matrix.
* [**`docs/dev/PROPOSED-FEATURES.md`**](docs/dev/PROPOSED-FEATURES.md): Candidate architectural proposals, alpha enhancement ideas, and unscheduled feature backlog.
* [**`docs/dev/RUNBOOK.md`**](docs/dev/RUNBOOK.md): Operations runbook, preflight checks, and deployment hardening.
* [**`docs/dev/RELEASE-GATE.md`**](docs/dev/RELEASE-GATE.md): Quality release gates, security checklists, and sign-off criteria.
* [**`docs/dev/NEXT-30-DAYS.md`**](docs/dev/NEXT-30-DAYS.md): Tactical 30-day milestone execution plan.

---

## Working Rules & Architecture Principles

1. **Modular Boundaries**:
   - Keep the project as a single Python package distribution (`pumpfun_trading`) without a `src/` layout.
   - Respect strict separation of concerns across modules. Do not reintroduce monolithic catch-all files.
   - Streaming and binary decoding stay in `streams/`.
   - On-chain execution and Jito bundling stay in `sdk/`.
   - Strategy decisions, filters, and exit rules stay in `strategies/`.
   - Runtime lifecycle, concurrency mutexes, and risk limits stay in `bot/`.
   - CLI handlers in `cli/` must delegate to library functions.
   - UI code in `ui/` renders state and must never own decision-making logic.

2. **Security & Key Management**:
   - **Operator Mode (Terminal UI)**: Uses environment variables (`.env`) for immediate testing and capital generation.
   - **Hosted End-User Instances (Web UI)**: Web users have no access to host environment variables. Wallet private keys are uploaded via secure web modal and held exclusively in volatile in-memory session state—never written to plaintext disk.

3. **Execution & Anti-MEV**:
   - Real-time bonding curve tracking uses Yellowstone Geyser gRPC streams (`streams/geyser.py`) with zero-copy binary parsers.
   - Live orders are bundled through private Jito block engines (`sdk/jito.py`) with dynamic tip floor scaling to prevent sandwich attacks, with fast fallback to direct RPC.

4. **Strategy & Risk Controls**:
   - All token entries are screened against dev-dumping, serial ruggers, and holder inequality (<0.85 Gini coefficient, <15% top 5 holders).
   - Positions scale out via multi-tier take-profits (Tier 1 @ 2.0x, Tier 2 @ 3.5x, Moonbag trailing floor @ 2.5x).
   - Enforce hard stop daily circuit breakers, startup on-chain position reconciliation, and exit retry queues.

---

## Runtime and Command Surface

The package exposes dedicated, high-performance CLI entry points:

* `pumpbot`: Start the live trading bot runtime (with `--preset`, `--headless`, `--dry-run` flags).
* `pumpfun-replay`: Run historical market replays, strategy backtests, and trade simulations from recorded JSONL datasets.
* `pumpfun-recorder`: Harvest live market streams, generate synthetic scenarios, or export token trades to replay files.
* `pumpfun-audit`: Query, filter, and inspect structured JSONL audit trails with Rich table rendering.
* `pumpfun-cli` / `pumpfun`: Unified CLI wrapper dispatching to `bot`, `replay`, `record`, `audit`, or `status` subcommands.

---

## Quality Standards & Testing

All contributions must strictly satisfy project quality gates:

* **Code Formatting & Linting**: 100% compliance with Ruff and Black (`nox -s format`, `nox -s lint`).
* **Static Type Safety**: 0 type violations under strict Mypy checks (`nox -s mypy`).
* **Unit & Integration Test Coverage**: Mandatory minimum of **95% statement and branch coverage** across all modules (`nox -s tests`).
* **Clean Commits & Documentation**: Keep `docs/dev/TODO.md` and feature docs updated with all architectural changes.

---

## Build & Installation

```bash
# Editable development install
pip install -e ".[dev]"

# Run quality checks
nox -s lint
nox -s tests
```
