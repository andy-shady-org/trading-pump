# AGENT.md

## Project overview

This repository contains the `pumpfun_trading` Python package, organized as a modular runtime and tooling package rather than a flat monolith.

The package is intentionally structured around responsibility boundaries across runtime, execution, strategies, CLI, and supporting services.

Core intent:
- Public Pump.fun API access stays in the `api/` layer
- Trading execution and transaction-building helpers stay in `execution/` and related modules
- Runtime orchestration, lifecycle, risk checks, and audit flows live under `bot/`
- CLI commands for bot, replay, and audit workflow live under `cli/`
- Replay and simulation code lives under `engines/`
- Strategy logic lives under `strategies/` and should remain modular rather than embedded in the runtime
- Terminal rendering and dashboard concerns live under `ui/`
- Supporting config, storage, and service domains are separated into their own packages

## Package structure

- `pumpfun_trading/`
  - `__init__.py`
  - `api/`
  - `bot/`
  - `cli/`
  - `config/`
  - `engines/`
  - `execution/`
  - `services/`
  - `storage/`
  - `strategies/`
  - `ui/`
  - `tests/`

## Working rules

- Keep the project as a single Python package distribution, without a `src/` layout.
- Use package-level modular boundaries rather than root-level catch-all modules.
- Do not reintroduce stale top-level modules such as `audit.py`, `replay.py`, or monolithic CLI files after cleanup.
- Keep canonical logic in the package location that matches its responsibility:
  - runtime/lifecycle/risk/audit in `bot/`
  - strategy decision logic in `strategies/`
  - replay engine logic in `engines/`
  - CLI entrypoints in `cli/`
- Keep `pumpfun-apis` as a separate reference/tooling repo and not as part of this package distribution.
- Prefer refactoring into smaller modules over growing a single runtime file.

## Runtime and command surface

The project exposes a small set of focused command entrypoints rather than a single overloaded CLI:

- `pumpbot` - start the live bot runtime
- `pumpfun-audit` - inspect, filter, summarize, and export the JSONL audit trail
- `pumpfun-replay` - run historical replay / paper-trading flows from saved datasets

All CLI code should stay under `pumpfun_trading/cli/` and should delegate to package logic instead of embedding business rules directly in command handlers.

## UI and terminal presentation

The terminal UI is intentionally separate from runtime execution logic.

- Dashboard and display logic live under `pumpfun_trading/ui/`
- Rich panels and tables are used for live operational status, health, and metrics
- Runtime state, risk logic, and execution behavior remain in the bot/runtime and strategy packages
- UI code should render state; it should not own the decision-making path or execution flow

## Implementation guidance

- Start with the execution and runtime boundaries before expanding strategy complexity.
- Keep market/API access focused on read-only requests and metadata fetches in `api/` and `services/`.
- Keep on-chain execution and transaction safety in `execution/`.
- Keep bot orchestration, health checks, lifecycle transitions, and risk controls inside `bot/`.
- Keep strategy logic modular and testable in `strategies/` with clear separation of:
  - signal generation
  - filter evaluation
  - risk validation
  - execution planning
  - exit evaluation
- Maintain a durable JSONL audit trail for lifecycle transitions, events, and trade records.
  - Include structured record types such as `state_transition`, `event`, and `trade`.
  - Keep audit/search tooling easy to operate from the CLI.
- Keep dashboard rendering separate from runtime logic; display code should not carry decision-making responsibilities.
- Prefer a clean `dry-run` and safety-verified baseline before expanding strategy complexity or live deployment risk.
- When code is moved or refactored, ensure test imports and public module paths follow the canonical package structure instead of legacy compatibility shims.

## Build/install

```bash
pip install -e .
```

## Notes

This project is intended to be a reusable library plus an executable runtime bot, all under the same Python package name, but structured by responsibility and operational role rather than as a monolithic flat package.
