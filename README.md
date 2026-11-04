# trading-pump

<!-- Static badges: the repository is private, so shields.io cannot read live
counts. If it is ever made public, replace a badge's image with
https://img.shields.io/github/{stars,issues,forks,issues-pr,contributors}/andy-shady-org/trading-pump
for live numbers. -->
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Releases: signed and verified](https://img.shields.io/badge/releases-signed%20%26%20verified-2ea44f?logo=git&logoColor=white)](SECURITY.md#signed-releases)
[![Stars](https://img.shields.io/badge/stars-view-blue?logo=github)](https://github.com/andy-shady-org/trading-pump/stargazers)
[![Issues](https://img.shields.io/badge/issues-view-blue?logo=github)](https://github.com/andy-shady-org/trading-pump/issues)
[![Forks](https://img.shields.io/badge/forks-view-blue?logo=github)](https://github.com/andy-shady-org/trading-pump/forks)
[![Pull requests](https://img.shields.io/badge/pull%20requests-view-blue?logo=github)](https://github.com/andy-shady-org/trading-pump/pulls)
[![Contributors](https://img.shields.io/badge/contributors-view-blue?logo=github)](https://github.com/andy-shady-org/trading-pump/graphs/contributors)
[![License: proprietary](https://img.shields.io/badge/license-proprietary-red)](LICENSE)

The Pump.fun / PumpSwap module for trading-core (registered as `pumpfun`).
It follows every coin that graduates from its Pump.fun bonding curve to a
PumpSwap pool, reads the pools on chain, trades two pre-registered lanes in
paper with every fee priced in, and records everything for replay. The
engine (sizing, risk, circuit breaker, exits, accounting, audit, alerts,
dashboard, and the capture writer, stream loop and replay harness) is
trading-core's (`>=0.7.0,<0.8`); the Solana plumbing (RPC pool, transport,
Jito, costs, mint decoding, program-subscribe feeds) is the trading-solana
library's (`>=0.3.0,<0.4`).

| Lane or capture | What it does | Default | Stage |
|---|---|---|---|
| **`pumpswap_momentum`** (FEAT-76) | Buys a standard graduate still at ≥ 1.2× its first PumpSwap price 60 s after the migration; exits +20% / −15% / 30 minutes from the engine, or its own (`lane.exits`, FEAT-79) | on in `configs/paper.example.json` | Stage 1, **NO-GO, closed** |
| **`pumpswap_instant`** (FEAT-78) | Buys an instant graduate (first reading 1,000–2,000 SOL market cap, 130–200 SOL in the pool) still at 1.00–1.10× its first price after 60 s; its own exits +50% / −15% / 30 minutes | off (`"instant": {"enabled": true}`) | Stage 1, **NO-GO, closed** |
| Graduation capture (FEAT-73) | Records every graduate's pool for 4 h | always on | record-only |
| New pools (FEAT-80) | Records new PumpSwap pools that are not graduations (`new_pools`) | off | record-only |
| Meteora DAMM v2 pools (FEAT-107) | Moved to trading-meteora in 0.5.0 (ADR-011); `v0.4.0` was the last release with it | — | — |
| Strategy library records (trading-core FEAT-133, FEAT-117) | `trading-pump lane-rows` writes a capture as the core library's rows for `trading-core-lanes sweep`; `market_book` offers the graduates to the core's lanes | on demand | tooling |

Stages are the capital gate's (0 Evidence, 1 Paper, 2 Live canary, 3
Scale-up). No lane has passed Stage 1, so live orders are refused. **Both
lanes were judged NO-GO on rc.11 and closed on 2026-11-03**: no exit,
filter or adaptive rule passes on every capture, because their losses are
operators' dumps of bundled supply at the peak ([RESULTS §6.20–§6.21](docs/dev/RESULTS.md#621-after-the-deep-analysis-no-pumpswap-lane-can-pass-the-lanes-are-closed-2026-11-03)).
The code stays, so captures can still be replayed. What is running and
what each run showed are in
[docs/dev/RELEASE-GATE.md §1](docs/dev/RELEASE-GATE.md#1-current-status).

## Install and run

```bash
pip install -e ../trading-core && pip install -e ../trading-solana && pip install -e ".[dev]"
export PUMPFUN_RPC_URL="https://<your-rpc>/?api-key=<redacted>"
cp configs/paper.example.json configs/paper.json
```

The three commands that matter:

```bash
trading-core check --config configs/paper.json      # validate the settings and build the module
trading-core run --config configs/paper.json        # paper trading on live graduations
trading-pump replay --config configs/paper.json \
    --capture data/paper/capture.jsonl* --out data/replay-1   # replay a capture through the engine
```

## Documentation

| Page | For |
|---|---|
| [docs/USER-GUIDE.md](docs/USER-GUIDE.md) | Start here: concepts, install, a first run, day to day |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Both lanes: the rule, why, prices and costs, how they are judged |
| [docs/STRATEGY-LEDGER.md](docs/STRATEGY-LEDGER.md) · [docs/LESSONS.md](docs/LESSONS.md) | Shared with every repository: every strategy tried on every venue and why it failed; every lesson learned |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `module_settings` key |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | The six environment variables the module reads |
| [docs/CLI.md](docs/CLI.md) | `trading-pump replay / lane-rows / env` and the trading-core commands |
| [docs/FEATURES.md](docs/FEATURES.md) | What is built, by FEAT ID |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the module meets trading-core's contract |
| [docs/dev/README.md](docs/dev/README.md) | For developers: release gate, runbook, results, runs, TODO, bugs, tests |

This repository continues **pumpfun-trading**: its full history from
2026-10-09, every release tag from `v0.0.1-alpha` to `v0.3.0rc8`, and its
documents in [docs/archive/pumpfun-trading](docs/archive/pumpfun-trading/INDEX.md).
Every pumpfun-trading lane was measured NO-GO in paper (launch buying alone
on about 25,000 trades).

Python 3.11–3.14, 100% branch coverage. Proprietary; private use only (see
`LICENSE`).
