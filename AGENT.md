# AGENT.md

## Project overview

This repository contains a single Python package named `pumpfun_trading`.

It is structured as a flat package layout, not a `src/` layout.

Core intent:
- API client layer for Pump.fun public HTTP endpoints
- SDK/execution layer for on-chain Pump.fun transaction construction and signing
- runtime bot logic contained within the package itself
- no separate top-level bot package at the repo root
- no vendored `pumpfun-apis` package included as a package dependency

## Package structure

- `pumpfun_trading/`
  - `__init__.py`
  - `api/`
  - `sdk/`
  - `bot.py`
  - `tests/`

## Working rules

- Keep the project as a single package distribution.
- Use `pyproject.toml` with a single package namespace discovery rule:
  - `include = ["pumpfun_trading*"]`
- Do not create a separate `src/` directory.
- Do not create a separate top-level `bot/` package.
- Keep the bot runtime inside the package namespace rather than as a sibling repo-level app.
- Keep `pumpfun-apis` as a separate repo/tooling reference, not part of this package.

## Implementation guidance

- Start with the SDK / execution layer before the API layer.
- Build reusable, testable primitives for execution and signing.
- Keep market/API access in the `api` module.
- Keep runtime orchestration in the package-level bot logic.
- Prefer clear separation between public API access and on-chain execution.
- Maintain a durable JSONL audit trail for all lifecycle transitions, events, and trade records.
  - Include structured record types such as `state_transition`, `event`, and `trade`.
  - Ensure the audit trail is accessible for incident review and debugging, not just terminal display.
- Add a search/filter CLI for the audit trail so operators can investigate by mint, name, date/time, state, reason, or outcome.
- Avoid allowing `pumpfun_trading/bot/run.py` to become a monolithic catch-all file.
  - Split runtime concerns into smaller modules for orchestration, risk checks, event handling, execution builders, and dashboard rendering.
  - Keep service boundaries explicit so that API adapters, lifecycle logic, and audit writers are independently testable.
- When preparing a release, prefer a clean `dry-run` and safety-verified baseline before expanding strategy complexity.

## Build/install

```bash
pip install -e .
```

## Notes

This project is intended to be a reusable library plus an executable runtime bot, all under the same Python package name.
