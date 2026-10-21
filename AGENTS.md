# AGENTS.md

## Claude 5.5 Opus Self-Correction & Continuous Learning

As **Claude 5.5 Opus**, you are required to treat this repository as a living trading system and this `AGENTS.md` file as your persistent memory. Because quantitative trading environments evolve quickly, you must automatically update your own rules, adapt to edge cases, and self-correct based on runtime or user feedback.

### 1. Triggers for Updates
You must automatically append a new rule to the **"Local Norms"** or **"Learnings Log"** sections at the bottom of this file if:
- **User Correction:** The user explicitly corrects your code, math logic, Solana transaction layout, or architectural layout.
- **Solana/Jito Runtime Failures:** A transaction fails on-chain, a Jito bundle drops, or a zero-copy parser breaks due to an unhandled byte alignment or edge case.
- **Test Failures:** A test fails because of an unwritten assumption or missed edge case.
- **Stale Context:** You discover that a file path, codebase map, or dependency listed in this file is outdated.

### 2. Instructions for Self-Updating
1. **Identify the Root Cause:** Pinpoint exactly what went wrong (e.g., "miscalculated PDA derivation for Token-2022 accumulator").
2. **Draft a Durable Rule:** Write a concise, actionable directive (a "Do" or "Don't") to prevent the error from happening again. Do not just log the error; write the permanent structural fix.
3. **Modify the File:** Use your file-editing tools to surgically append the rule to the end of the appropriate section below. Do not overwrite or erase existing rules.
4. **Keep it Concise:** Keep instructions short and punchy to conserve context tokens for future sessions.

---

## Local Norms
- **Asynchronous Jito Bundle Polling:** Never block the streaming execution loop when waiting for Jito bundle statuses; always use non-blocking `asyncio` polling or websocket event confirmation.
- **Micro-Lamport Compute Budget Management:** Every transaction builder must explicitly append a `SetComputeUnitPrice` and a tight, simulated `SetComputeUnitLimit` instruction to prevent transaction drops or wasted fee capital.
- **Zero-Copy Alignment Checks:** Any structural or byte changes made to binary parsers inside `streams/` must explicitly match the layout offsets of Yellowstone Geyser streaming payloads to prevent memory allocation crashes.
- **Volatile Key Erasure:** Methods handling private keys within the Web UI runtime must clear variables from scope immediately after building transaction signatures to maintain strict memory security.
- **Fail-Fast Risk Validation:** All pre-execution checks (such as Gini coefficient boundaries and daily circuit breakers) must execute within a unified, atomic risk pipeline before hitting the instruction assembly layer.
- **Income Path First:** The terminal UI (`pumpbot`) must earn the money that funds the Web UI. Prioritise Phases 4b/4c (`docs/dev/TODO.md`) over refactors and Web UI work, never regress `pumpbot`, report profit net of fees/priority fees/Jito tips/rent, and don't start Phase 6 before the funding gate (`docs/dev/RELEASE-GATE.md` §3.7).
- **Mirrored Test Layout:** New tests go in `pumpfun_trading/tests/unit/<pkg>/test_<module>.py` (cross-component flows in `integration/`, Hypothesis in `property/`), build configs/bots/payloads from `tests/support/` factories, and never use coverage-named files (`test_coverage_*`, `*_boost*`, `*_full`). See `docs/dev/TESTING.md`.
- **Feature Docs Track Code:** Document a new, unbuilt feature in `docs/dev/PROPOSED-FEATURES.md` (next free FEAT-ID, catalogue row). When its code ships, move it to `docs/FEATURES.md` and leave a pointer behind. For a partly built feature, list what ships in `FEATURES.md`, mark the missing parts **Not built** there, and keep those parts in `PROPOSED-FEATURES.md`. Never list unbuilt work in `FEATURES.md` (FEAT-10 was listed as implemented with no code).
- **TODO Lists Open Work Only:** `docs/dev/TODO.md` holds open items; finished work lives in `docs/dev/DONE.md` under its original heading. When a sprint's last box is ticked, move it to `DONE.md` with a link to its CHANGELOG release; in a partly done sprint, move the ticked items and leave one "Done:" line. Verify a completion against the code before ticking or moving it, put evidence and results in `STRATEGY-PIVOT.md` §6 or `releases/`, not in TODO, and never leave an open box in `DONE.md` (mark it superseded, moved or closed with the reason).

## Learnings Log & Avoided Mistakes
- **[CRITICAL] Slippage Calculation Target:** Avoided calculating slippage based on static REST API prices. Pump.fun bonding curve prices can shift drastically within a single slot. Always compute slippage against the dynamic, local virtual reserves tracked directly from the real-time Geyser stream.
- **[EXECUTION] Jito Tip Placement:** Avoided appending Jito tips as standalone transactions or placing the tip instruction at the beginning of a transaction. The tip must be the *final instruction* inside the transaction payload within the bundle to guarantee inclusion and prevent MEV searchers from unbundling.
- **[RISK] Developer Allocation Fraud:** Avoided checking developer wallet balances via static snapshots. Devs can scatter supply across multiple fresh puppet wallets prior to launch. Shifted to evaluating the collective top-5 holder concentration matrix continuously during the first 30 seconds of token creation.
- **[MATH] Bonding Curve Overflows:** Avoided native integer math for token-to-SOL conversions. High-velocity minting curves can easily overflow standard 64-bit bounds during aggressive volume spikes. Always utilize fixed-point math with explicit scaling factors when tracking $P = \Delta y / \Delta x$.
- **[STREAMS] No Fake Connections:** Never set a stream to CONNECTED without a real transport; fail fast (`GeyserTransportUnavailableError`) and fall back. Yellowstone account filters must use bonding-curve PDAs, not mints.
- **[ARB] Chain-Read Reserves Only:** Never execute or bank arbitrage on estimated/placeholder reserves; only `reserves_verified=True` opportunities may execute.
- **[DOCS] Completion Claims Track Code:** TODO item 25 claimed `bot/run.py` was a "lightweight facade" while it had regrown to ~3,770 lines. Before ticking or citing a completed refactor, verify it against the current code (file size, responsibilities); re-open the item when it regresses.
- **[SCREENING] Stream Payloads Are Not Enrichment:** PumpPortal/Geyser create events carry no socials or holders. Always enrich screened tokens (API record, metadata `uri`, `getTokenLargestAccounts`) with bounded timeouts, since screening runs inside `_trade_lock`; never skip enrichment because stream data was passed (BUG-95). Keep tests off live endpoints.
- **[EXECUTION] Close What You Open:** Every buy of a new mint pays ~0.002 SOL token-account rent (BUG-96). A full exit must close the account in the sell transaction (only when the sell empties it), and every trade record must carry its fees, tip and rent; never report or gate on gross PnL.
- **[TESTS] No Cost RPC In Tests:** Post-fill cost capture calls `getTransaction`. `tests/conftest.py` stubs `PumpFunExecutionClient.get_transaction_costs`; only modules that set `USES_REAL_TRANSACTION_COSTS = True` (and patch `rpc_pool.request`) may call the real one.
- **[EXECUTION] Don't Hard-Code Rent:** Mainnet rent was lowered (Token-2022 ATA 1,513,840 lamports, not 2,039,280). Live costs must come from the transaction meta; modelled values are estimates, so re-check them with `getMinimumBalanceForRentExemption` before relying on them.
- **[TESTS] Mirrored Test Packages:** Every `tests/unit/<pkg>/` directory needs an `__init__.py`; without it, same-named modules (`unit/cli/test_events.py`, `unit/ops/test_events.py`) collide in pytest and mypy.
- **[OPS] Rotate By On-Disk Name:** Background gzip means `X.1` may still be plain. Shift archives by the name actually on disk (never re-derive `.gz`), and join the pending compression before the next rotation (BUG-97).
- **[TESTS] No Network In Tests:** Tests that called mainnet passed locally and failed in CI on HTTP 429. `tests/conftest.py` blocks non-local DNS; stub `get_token_program_for_mint` (or use `offline_trade_rpc`) for ATA/builder paths, and give mocked aiohttp sessions `closed = False` and a mocked `request`.
- **[SECURITY] Redact URLs Before Persisting:** Provider URLs carry API keys (`?api-key=`, `/v2/<key>`). Never write a raw endpoint or stream URL to status files, logs, events or alerts; serialise through `ops/redact.py` (`redact_url` / `redact_text`) and identify endpoints by host label (BUG-102).
- **[REPLAY] Recorded `signal` Is Not An Order:** `--record-replay` captures tag every market trade and new token with `signal`; only snapshots with `reason` (and no `user`) are the bot's own fills. Live-fidelity replay must never treat `signal` strings as exits, and must say plainly that the screener is not replayed.
- **[TESTS] Green On 3.14 Is Not Green On 3.11:** A global `Path.stat` mock passed on 3.14 but broke `Path.glob` on 3.12/3.13. Never patch `pathlib` methods globally; wrap the real call and fake only the target file. Supported interpreters are 3.11–3.14 (`nox -s tests-<ver>`, CI matrix).
- **[PACKAGING] Tests Never Ship:** `packages.find` exclude alone still packed `pumpfun_trading/tests` as package data; keep the `MANIFEST.in` prune and run `nox -s package` after any packaging change. Never add a release/publish workflow (proprietary).
- **[ASYNC] Never Cancel A Dequeued Write:** Cancelling a task awaiting `asyncio.to_thread` also cancels a not-yet-started executor job, so data already taken off a queue is lost on shutdown (BUG-103). Shield in-flight writes and finish them before re-raising `CancelledError`; test shutdown races deterministically (busy one-thread executor), not with wall-clock durations.
- **[TESTS] Slow Tests Mean Unmocked Retries:** Most of the suite's 136 s was real retry backoff on blocked-network API/RPC lookups, not the bot. Profile with `--durations` before tuning; never add real sleeps or rely on backoff in tests (`instant_retry_backoff` in `tests/conftest.py` skips it; `USES_REAL_RETRY_BACKOFF = True` to opt out), and keep a new retry loop's sleep inline in a `request` method or extend that fixture.
- **[TESTS] `make_config` Is Dry-Run:** `make_config()` defaults to `dry_run=True` but `TradingBotConfig()` to `False`. When converting an inline config, pass `dry_run=False` unless the call already set it; scope `ruff --select I --fix` to the files you touched, never the whole tests tree.
- **[TESTS] Resolving A Bug Means Tagging A Test:** Marking a bug RESOLVED in `BUGS.md` fails `unit/test_suite_layout.py` until a test carries `@pytest.mark.regression("BUG-xx")`; never add the ID to `KNOWN_UNTAGGED` instead. A golden-replay diff is a behaviour change: explain it before regenerating.
- **[PAPER] One Price Source, Sane Curves Only:** Stage 0 reported +63.5 SOL that was a pricing artefact (BUG-104): paper entries used the stream's market cap, exits the on-chain curve, and a non-standard curve variant decoded to 25×–3,500×. Price entries and exits from the same source, reject curves whose reserves fail sanity checks, and treat any paper result far above costs as a bug until explained. Judge strategies per position, never per sell (BUG-105).
- **[RPC] Empty Is Not Zero:** `getTokenLargestAccounts` on a load-balanced RPC flaps for new mints (2, 0, 2, 0 accounts within 6 s), which hid holders for 67% of Stage 0 buys (BUG-107). Treat an empty index-backed answer as "not yet indexed": retry inside the lookup budget, count outcomes, and never score it as "no holders".
- **[TESTS] Strip The Operator Shell:** An exported `PUMPFUN_JITO_TIP_LAMPORTS` from `.envrc` changed golden-replay costs locally. `tests/conftest.py` deletes every ambient `PUMPFUN_*` variable per test; set what a test needs with `monkeypatch.setenv`, and read `PUMPFUN_UPDATE_GOLDEN` at import time only.
- **[ENTRY] Trust The Program, Not The Feed:** PumpPortal's create feed carries other launchpads; Stage 0 bought 263 non-Pump.fun mints, USDC included (BUG-108). Buy only when the curve PDA exists and is owned by the Pump.fun program, never let a missing curve fall through to a simulated paper fill, and never re-buy a closed mint (BUG-109). Test new-token flows with `SAMPLE_PUMP_MINT` or set `require_pump_mint_suffix=False`.
- **[ASYNC] Alerts Are I/O Too:** `_send_alert` ran a blocking `urlopen` (10 s timeout) on the trading loop for every alerted event, buys included (BUG-110). Never call a sync network client from loop code; dispatch with `asyncio.to_thread` / a tracked task, and flush (bounded) before `asyncio.run` exits. Test it with a webhook that blocks until released, not with timings.
- **[OPS] Withdrawals Are Not Drawdowns:** A profit sweep lowers wallet equity on purpose. Anything that moves SOL out must call `DailyEquityTracker.record_withdrawal` and write a `sweep` audit record that `reconcile` counts, or the breaker trips and the wallet check shows a gap (FEAT-42).
- **[STREAMS] Check That Subscriptions Deliver:** PumpPortal refuses `subscribeTokenTrade` without a funded API key and replies with a mint-less `message` the bot dropped, so v0.2.0 and v0.2.1 held positions blind (exits on a 5 s curve poll, empty order flow, captures with no trades; BUG-112). Log and alert any server `message`, and treat a held mint with no trade messages as degraded data, not a quiet market.
- **[STREAMS] A Reconnect Is Not A Fix:** BUG-116 cleared the trade-feed refusal on every reconnect, so buys resumed blind while the key's wallet was still empty. Close a feed breaker only on proof of delivery (a confirmed subscription or data), probe while it is open, and name the likely cause (metered API key out of funds) in the alert.
- **[ENTRY] Mayhem Curves Break The Invariant:** mayhem-mode curves drifted to 46 SOL virtual reserve 2 s after launch. Skip `is_mayhem_mode` tokens (`skip_mayhem_mode`) unless their pricing is modelled.
- **[CONFIG] Defaults Are Not Choices:** a preset filled in the public PumpPortal URL, which beat the keyed `PUMPFUN_STREAM_URL` (BUG-117). Never let a filled-in default outrank an env override; check precedence by loading the real runtime config + env through `TradingBot`, not by testing the env value on its own.
- **[SECURITY] Secrets Are Not Part Of A URL:** the dashboard printed `stream_url` with the PumpPortal `?api-key=` in it (BUG-118). Keep provider keys in their own env variable (`PUMPFUN_STREAM_API_KEY`), keep displayed/stored URLs key-free, join the key only at connect time, and pass any URL a UI renders through `redact_url`.

- **[STREAMS] Unsubscribe Where Positions Close:** exits ran from six call sites and only one passed the websocket, so 538 exited mints kept streaming billed trade messages (BUG-120). Put per-position cleanup in the one function every exit goes through (`_sell_token`), never at the call sites. Net PnL means every record: a check that sums only sells drops the buy-side costs (BUG-119).
- **[ENTRY] Demand Before Entry:** buying at the create event lost −0.579 SOL over 1,675 positions (10.3% won) because most launches get no follow-on buyers; exits can't fix that. Never buy a launch without evidence of follow-on demand (`entry_mode: "confirmed"`: watch → RPC curve poll → trade subscription → confirm); `"launch"` stays the default only for back-compat. See `docs/dev/STRATEGY-PIVOT.md`.
- **[CONFIG] Check Limits Against Size:** the first `momentum` preset replay bought nothing: one 0.02 SOL position was 40% of the 0.05 SOL exposure cap, above the inherited 25% `max_token_concentration_pct`. When a preset changes `buy_amount_sol` or exposure, check every inherited risk cap still admits one position, and read `entry_rejections` before tuning signals on a zero-trade replay.
- **[REPLAY] Model The Latency You Pay:** replay filled confirmed entries at the signal price while paper waited 1.5 s and took a 100 bps penalty, so replay beat paper by 0.016 SOL and an 8-buyer variant looked profitable when it wasn't (BUG-121). Every paper execution setting (`paper_entry_*`) must be modelled in replay; run `--compare-audit` before trusting a sweep, and re-run sweeps after any replay fix.
- **[REPLAY] Replay Can't See What It Didn't Record:** the rc.1 audit showed 14 of 118 paper fills > 10% above the signal; replay of the same capture saw 5, because the paper fill reads the curve and the capture only has the trades it subscribed to. Judge rules that act on the fill price (the drift guard) on paper captures, not replay sweeps, and say so when reporting them.
- **[EXECUTION] Graduated Coins Trade On PumpSwap:** the bot waited for a Raydium pool after graduation, but Pump.fun migrates into PumpSwap, and the WebSocket deployment never saw the completion at all (BUG-123). Every held mint needs a completion signal on every transport (curve refresh `complete`, `subscribeMigration`) and an exit on the venue the program actually migrates to; pin new program layouts to real mainnet account bytes in tests.
- **[ANALYSIS] Beat A Random Cut:** every filter on a losing lane "improves" net PnL because it trades less. Compare a filter's kept net with the same share of the total (random cut), on at least two captures, before calling it an edge.
- **[CONFIG] A New Field Needs The Resolver:** `resolve_strategy_config` lists every `TradingBotConfig` field by hand, so a field added only to `base.py` is silently ignored in config files (BUG-125: the profit sweep, FEAT-50 alerts and `enable_pumpswap_exit`). Add every new field to the resolver too; `test_every_config_field_survives_a_config_file` fails otherwise. `make_config` / `replace` bypass the resolver, so they can't catch this.
- **[ANALYSIS] Score The Copy, Not The Wallet:** the operator's "successful" wallet `29yFzeBZ…` turned out to be a serial creator (100 screened launches, no recorded trades), and copying every captured wallet at our 1.5 s delay and costs lost ~0.0013 SOL per copy. Rank wallets only on our simulated copy net on closed copies (`pumpfun-replay --wallet-scores`), check a second capture, and check whether a wallet is a creator before calling it a trader.
- **[TOOLS] No Stash In A Shared Tree:** a subagent's `git stash` / `pop` briefly took another agent's uncommitted work with it. Never stash, checkout or reset in a working tree other agents are editing; run read-only git commands only, and verify with `git status` after any slip.
- **[REPLAY] Scanned Nets Are Relative:** `--shadow-scan` modelled the rc.1 baseline at −0.006 SOL where paper lost −0.099 on the same 118 signals, because scanned fills only see recorded prices. Compare a scanned variant only with the scanned baseline (random cut), never with paper or a replay total.
- **[TOOLS] One Editor Per File:** mixing `sed -i` with the edit tools on the same file left a duplicated tail in `test_presets.py` that broke collection. Edit a file with one tool, then `git diff` it before running the suite.
- **[PAPER] Model The Exit Too:** paper sells took no slippage while replay took 100 bps, so rc.2 paper showed +0.014 SOL where a realistic exit gave about −0.007, and parity was off by 0.028 (BUG-126). Every paper fill, buy or sell, must pay the latency and price impact a live fill pays, through a config key replay reads too (`paper_entry_*`, `paper_exit_slippage_bps`); set them in every config you `--compare-audit` against.
- **[CAPTURE] Observe Without Touching:** rc.3 records curves the bot never trades (screen-reject sample, discovered near-graduation curves). Keep such data off every decision path (no watch list, promotion, shadow book or `GraduationEngine` feed), poll it in its own task, tag its rows (`source` in `RECORD_ONLY_POLL_SOURCES`, `observation_*` events) and skip them in replay and the shadow tools, or a "measurement" changes fills and parity. Never let a record-only API call share the screening client's retry loop or breaker.
- **[DATA] Probe Free APIs Before Picking Defaults:** the keyless Jupiter API allowed 5 requests per ~10 s, and GeckoTerminal sent `Retry-After: 0` while still limiting, the odd 500, and a 401 at its ~6-month history limit (FEAT-65 recorder). Check a free endpoint's real limits by hand before setting pacing defaults, retry 429 / 5xx with bounded growing waits (never trust a zero reset), treat a paging 401 as end of history, and keep such recorders in their own process.

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
│   │   └── handlers/ # Stream handlers (curve, trade, raydium, new_token, watch); TradingBot keeps one-line delegates (Sprint 28b)
│   ├── cli/          # Dedicated CLI entry points (pumpbot, pumpfun-replay, pumpfun-audit, pumpfun-cli)
│   ├── config/       # Environment loading, configuration resolution, and settings validation
│   ├── engines/      # Historical market replay and paper-trading simulation engine
│   ├── execution/    # Transaction instruction builders and execution helpers
│   ├── infra/        # Multi-provider RPC connection pool, latency routing and failover
│   ├── ops/          # Structured logging (ANSI/NO_COLOR compliant) and telemetry monitoring
│   ├── sdk/          # Solana on-chain execution SDK, PDA/ATA derivations, and Jito MEV client
│   ├── services/     # Background service helpers and metadata ingestion
│   ├── storage/      # Durable status snapshot and audit persistence
│   ├── strategies/   # Modular signal generation, anti-rug heuristics, trailing exits, and presets
│   ├── streams/      # Yellowstone Geyser gRPC streaming client & zero-copy binary parsers
│   ├── ui/           # Rich alternate-screen live terminal dashboard
│   └── tests/        # Test suite (>=95% coverage); see docs/dev/TESTING.md
│       ├── conftest.py   # environment isolation only
│       ├── support/      # shared factories, fakes, payload builders, constants
│       ├── unit/         # 1:1 mirror of the source: unit/<pkg>/test_<module>.py
│       ├── integration/  # cross-component flows and replay end-to-end
│       └── property/     # Hypothesis property tests (curve math, parsers)
└── deploy/           # Operator supervisor templates: systemd unit + reconcile timer, launchd agent, wrapper scripts (RUNBOOK §8)
```

> The migration finished in Sprint 27: the tests root holds only `conftest.py`, and `tests/unit/test_suite_layout.py` fails on a source module without a mirrored test, a coverage-named file, or a RESOLVED bug in `docs/dev/BUGS.md` without a `@pytest.mark.regression("BUG-xx")` test. `integration/test_golden_replay.py` pins bot decisions (regenerate with `PUMPFUN_UPDATE_GOLDEN=1` only for an intended change).

---

## Documentation Architecture

The documentation is organized in a clear, audience-separated star topology:

### 1. User & Operator Manuals (`docs/`)
Accessible to end-users, quant traders, and bot operators; planned to be published as a Zensical/Material site served at `/docs` by the Web UI control plane (see `docs/dev/DOCUMENTATION-PLAN.md`):

* [**`docs/USER-GUIDE.md`**](docs/USER-GUIDE.md): Central knowledge hub and primary onboarding portal for both hosted Web UI instances and operator Terminal UI mode.
* [**`docs/ENVIRONMENTAL-VARIABLES.md`**](docs/ENVIRONMENTAL-VARIABLES.md): Exhaustive environment variables manual, fallback aliases, default values, and production configuration recipes.
* [**`docs/CLI-COMMANDS.md`**](docs/CLI-COMMANDS.md): Exhaustive command-line interface manual for all standalone binaries (`pumpbot`, `pumpfun-recorder`, `pumpfun-replay`, `pumpfun-audit`) and unified `pumpfun` subcommands.
* [**`docs/STRATEGY.md`**](docs/STRATEGY.md): Wealth generation blueprint, bonding curve pricing math ($P = \Delta y / \Delta x$), fractional Kelly bankroll management, multi-tier profit scaling, dynamic trailing stops, and anti-rug heuristic scoring.
* [**`docs/RISK.md`**](docs/RISK.md): Multi-tier capital preservation, position concentration caps, daily hard-stop circuit breakers (FEAT-09), startup on-chain reconciliation, and emergency exit queues.
* [**`docs/TERMINAL-UI.md`**](docs/TERMINAL-UI.md): Rich console dashboard manual, sub-millisecond slot latency telemetry, and multi-channel alerting (Discord, Slack, Telegram) for operator self-funding.
* [**`docs/WEB-UI.md`**](docs/WEB-UI.md): Architecture specification for the hosted multi-tenant Web Dashboard (FEAT-10): FastAPI control plane, Vue 3 + Vuetify MD3 PWA, container-per-tenant bots, zero-knowledge key ingestion, draft API, and terminal UI deprecation roadmap.
* [**`docs/FEATURES.md`**](docs/FEATURES.md): Catalog of shipped capabilities only (§1–37); unbuilt parts are marked **Not built** and tracked in `docs/dev/PROPOSED-FEATURES.md`.
* [**`docs/REPLAY-ENGINE.md`**](docs/REPLAY-ENGINE.md): Historical market replay and strategy backtesting simulator (`pumpfun-replay`).
* [**`docs/AUDIT-TOOL.md`**](docs/AUDIT-TOOL.md): Forensic trade accounting and telemetry inspection CLI (`pumpfun-audit`).

### 2. Developer & Engineering Artifacts (`docs/dev/`)
Internal engineering documentation for maintainers, contributors, and SRE:

* [**`docs/dev/README.md`**](docs/dev/README.md): Developer and contributor portal index.
* [**`docs/dev/TODO.md`**](docs/dev/TODO.md): Open work only: Now / Next / Later and the open sprints of Phase 4b (Terminal Income Track, with the Web UI funding gate), Phase 4c (Strategy Pivot), Phase 5 (Platform Refactor) and Phase 6 (Hosted Web UI).
* [**`docs/dev/DONE.md`**](docs/dev/DONE.md): Archive of finished phases, sprints and items (Phases 0–5) moved out of `TODO.md`, under their original headings.
* [**`docs/dev/ARCHITECTURE-DECISIONS.md`**](docs/dev/ARCHITECTURE-DECISIONS.md): Architecture decision records (web stack, control plane, tenant isolation, key handling, database, docs tooling, test layout).
* [**`docs/dev/TESTING.md`**](docs/dev/TESTING.md): Test architecture, conventions, markers, and the file-by-file test migration map.
* [**`docs/dev/DOCUMENTATION-PLAN.md`**](docs/dev/DOCUMENTATION-PLAN.md): Documentation gap analysis, Zensical / Material docs-site plan, and styling conventions.
* [**`docs/dev/BUGS.md`**](docs/dev/BUGS.md): Bug tracker, root cause analyses, and resolution verification matrix.
* [**`docs/dev/PROPOSED-FEATURES.md`**](docs/dev/PROPOSED-FEATURES.md): Unbuilt features only: candidate proposals, alpha ideas and the unscheduled backlog. An entry moves to `docs/FEATURES.md` once its code ships.
* [**`docs/dev/RUNBOOK.md`**](docs/dev/RUNBOOK.md): Operations runbook: runtime layout, paper pilot, incident drills, wallet reconciliation, operator pause, unattended alerts, profit sweep, supervised deployment, incident response and rollback.
* [**`docs/dev/RELEASE-GATE.md`**](docs/dev/RELEASE-GATE.md): Per-release checklist, staged live capital gate (paper → canary → scale-up), hosted security gate, and versioning policy.
* [**`docs/dev/STRATEGY-PIVOT.md`**](docs/dev/STRATEGY-PIVOT.md): v0.3.0 strategy pivot (confirmed momentum + pre-graduation), evidence, cost model, Phase 4c sprints 24E–24H and go/no-go rules.

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
   - On-chain trade execution builds modern Pump.fun `BuyV2` and `SellV2` instructions with dynamic Token-2022 / SPL Token resolution, creator vaults, and fee/volume accumulator PDAs (`sdk/execution.py`).
   - Live orders are bundled through private Jito block engines (`sdk/jito.py`) with dynamic tip floor scaling to prevent sandwich attacks, with fast fallback to direct RPC.

4. **Strategy & Risk Controls**:
   - All token entries are screened against dev-dumping, serial ruggers, and holder inequality (<0.85 Gini coefficient, <15% top 5 holders).
   - Positions scale out via multi-tier take-profits (Tier 1 @ 2.0x, Tier 2 @ 3.5x, Moonbag trailing floor @ 2.5x).
   - Enforce hard stop daily circuit breakers, startup on-chain position reconciliation, and exit retry queues.

---

## Runtime and Command Surface

The package exposes dedicated, high-performance CLI entry points:

* `pumpbot`: Start the live trading bot runtime (with `--preset`, `--headless`, `--dry-run` flags). `SIGUSR1` toggles the operator pause (no new buys, exits continue); exit code 1 means the stream loop ended without a shutdown request.
* `pumpfun-replay`: Run historical market replays, strategy backtests, and trade simulations from recorded JSONL datasets.
* `pumpfun-recorder`: Harvest live market streams, generate synthetic scenarios, or export token trades to replay files.
* `pumpfun-audit`: Query, filter, and inspect structured JSONL audit trails with Rich table rendering.
* `pumpfun-events`: Query, inspect, filter, and tail structured diagnostic runtime event streams.
* `pumpfun-optimize`: Run genetic, random, and grid hyperparameter backtest optimization over historical replay datasets.
* `pumpfun-arb`: Monitor cross-venue spot price disparities and simulate/execute atomic Jito arbitrage bundles.
* `pumpfun-cli` / `pumpfun`: Unified CLI wrapper dispatching to `bot`, `replay`, `record`, `audit`, `events`, `optimize`, `arb`, or `ops` subcommands.

---

## Quality Standards & Testing

All contributions must strictly satisfy project quality gates:

* **Code Formatting & Linting**: 100% compliance with Ruff and Black (`nox -s format`, `nox -s lint`).
* **Static Type Safety**: 0 type violations under strict Mypy checks (`nox -s mypy`).
* **Unit & Integration Test Coverage**: Mandatory minimum of **95% statement and branch coverage** across all modules (`nox -s tests`).
* **Clean Commits & Documentation**: Keep `docs/dev/TODO.md` (open work), `docs/dev/DONE.md` (finished work) and feature docs updated with all architectural changes.
* **Bugs & Regression Prevention**: All runtime failures, edge cases, and user corrections must be logged in the **"Learnings Log"** section of this file with actionable rules to prevent recurrence. All bugs must be logged in `docs/dev/BUGS.md` with root cause analysis and resolution verification.
---

## Build & Installation

```bash
# Editable development install
pip install -e ".[dev]"

# Run quality checks
nox -s lint
nox -s mypy
nox -s tests      # Python 3.11–3.14 (installed interpreters)
nox -s package    # wheel is private and ships no tests
```
