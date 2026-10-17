# Proposed Features & Architectural Enhancements

This document lists candidate features and architectural enhancements for `pumpfun-trading` that have **not yet been implemented**. For completed, supported features see [`docs/FEATURES.md`](../FEATURES.md). Architecture choices referenced below are recorded in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md), and the delivery schedule lives in [`TODO.md`](TODO.md).

**Classification**

| Class | Meaning |
|---|---|
| **Income** | Needed for the terminal UI to earn measurable, reconciled net income. Income features outrank everything else, because that income funds the Web UI. |
| **Required** | Blocks the hosted Web UI (FEAT-10) or hosted multi-tenant operation. |
| **Suggested** | Improves function, safety, or user experience but does not block the Web UI. |

| Priority | Meaning |
|---|---|
| **P1** | Schedule in the next phase. |
| **P2** | Schedule after the P1 items it depends on. |
| **P3** | Backlog; revisit after the Web UI ships. |

**Context.** The bot can trade live through the terminal UI (`pumpbot`), but it has not yet shown net profit. The terminal UI has to generate the income that pays for the Web UI, so the **Income** features below (Phase 4b in [`TODO.md`](TODO.md#phase-4b-terminal-income-track-highest-priority)) come first, and the Web UI starts only after the funding gate ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)). The terminal UI stays the primary interface until the deprecation gate in Sprint 35. Work that keeps the trading path fast, safe and profitable always wins over UI polish.

---

## 1. Catalogue Summary

| ID | Feature | Class | Priority | Sprint |
|---|---|---|---|---|
| FEAT-49 | Net PnL accounting & wallet reconciliation | Income | P1 | 24B |
| FEAT-50 | Terminal operator pause & daily PnL digest | Income | P1 | 24D (implemented) |
| FEAT-10 | Web Control Dashboard (umbrella, re-scoped to FEAT-31…37) | Required | P1 | 32–35 |
| FEAT-31 | Bot Agent API & typed event stream | Required | P1 | 32 |
| FEAT-32 | FastAPI control plane (REST/WSS, auth, RBAC, OpenAPI) | Required | P1 | 32 |
| FEAT-33 | Vue 3 + Vuetify MD3 responsive PWA dashboard | Required | P1 | 33 |
| FEAT-34 | Multi-tenant instance orchestrator (container per tenant) | Required | P1 | 34 |
| FEAT-35 | Persistence layer (SQLAlchemy/Alembic, Postgres/SQLite) | Required | P1 | 30 |
| FEAT-36 | Zero-knowledge key ingestion (X25519 envelope, memory-only) | Required | P1 | 34 |
| FEAT-37 | Documentation portal (Zensical) embedded at `/docs` | Required | P2 | 31, 35 |
| FEAT-38 | Hot-config versioning, diff and rollback | Suggested | P2 | after 33 |
| FEAT-39 | Production Yellowstone gRPC transport | Income (conditional) | P1 | 24D, if latency costs entries |
| FEAT-40 | Live cross-venue arbitrage feed (closes BUG-90) | Suggested | P2 | after 39 |
| FEAT-41 | Prometheus / OpenTelemetry exporter + Grafana | Suggested | P2 | after 29 |
| FEAT-42 | Automated treasury profit sweep to a cold wallet | Income | P2 | 24D (implemented, off by default) |
| FEAT-43 | PnL / tax CSV export and performance reports | Suggested | P2 | after 30 |
| FEAT-44 | Shadow paper-trading (A/B strategies alongside live) | Suggested | P3 | backlog |
| FEAT-45 | Interactive Telegram bot (deferred from FEAT-10) | Suggested | P3 | backlog |
| FEAT-46 | Docker image + compose for operator mode | Suggested | P2 | 24D (systemd slice), 34 (image) |
| FEAT-47 | Replay analytics on Parquet + DuckDB | Suggested | P3 | backlog |
| FEAT-48 | Strategy plugin registry via entry points | Suggested | P3 | backlog |

---

## 2. Terminal Income Track (Income)

### FEAT-49: Net PnL Accounting & Wallet Reconciliation
* **Class / Priority:** Income · P1 (Sprint 24B) — **implemented** on branch `sprint-24b-net-pnl` together with BUG-96 (token-account rent recovery); see `docs/dev/TODO.md` Sprint 24B for what remains
* **Goal:** Know, every day, whether the bot made money after every cost, and prove it against the wallet.
* **Evidence:** `TradingBot._record_trade` (`bot/run.py`) stores `cost_sol` / `proceeds_sol` only; realized PnL sent to `DailyEquityTracker` (`bot/risk.py`) is `sell_p - entry`, so the daily circuit breaker and the dashboard see **gross** PnL. Network fees, priority fees, Jito tips and ATA rent are not recorded, and there is no transaction signature on the trade record. The snapshot ledger keeps only the last 50 trades. `pumpfun-audit` can filter and summarise records but has no PnL or reconciliation command.
* **Design:**
  - Capture signature, fee, priority fee, tip, rent and the actual SOL delta (`getTransaction` pre/post balances) at confirmation in `sdk/execution.py` / `execution/executor.py`.
  - Add `signature`, `fee_sol`, `tip_sol`, `rent_sol`, `gross_pnl_sol`, `net_pnl_sol` to trade and audit records; the breaker uses net PnL.
  - `pumpfun-audit pnl` (daily, per strategy, per exit reason, cost share) and `pumpfun-audit reconcile --wallet` (exit code ≠ 0 on a gap above the `RELEASE-GATE.md` §3.4 tolerance).
  - Terminal dashboard Risk panel: net vs. gross PnL, fees + tips today, last reconciliation result.
* **Dependencies:** none; lands before live canary trading.
* **Impact:** Makes the live capital gate measurable, stops the breaker under-counting losses, and gives the numbers needed to decide when the Web UI can be funded. Feeds FEAT-43 later.

### FEAT-50: Terminal Operator Pause & Daily PnL Digest
* **Class / Priority:** Income · P1 (Sprint 24D)
* **Goal:** Run the terminal bot unattended for days, intervene without losing open positions, and see the day's result without logging in.
* **Evidence:** the only operator controls today are `SIGINT` / `SIGTERM` (full stop); `bot/lifecycle.py` has no pause state; `bot/alerts.py` pushes per-trade alerts but no daily summary.
* **Design:** `SIGUSR1` toggles "no new buys, keep managing exits", shown on the dashboard and audited. It is an early slice of the Sprint 29 `PAUSED` state and later becomes a trigger for `BotController.pause()`. A daily digest alert (net PnL, trades, fees + tips, breaker state, reconciliation result) and alerts on prolonged stream/RPC degradation. Documented systemd / launchd unit with restart limits.
* **Dependencies:** FEAT-49 for the digest numbers.
* **Impact:** Fewer missed sessions and fewer forced liquidations from full stops; the operator can pause through volatile periods.
* **Status:** implemented in Sprint 24D (`bot/operator.py`, `bot/supervision.py`, `deploy/`; [`RUNBOOK.md` §5.5, §8](RUNBOOK.md#55-operator-pause-and-unattended-alerts-sprint-24d-feat-50)). The pause persists across restarts; the digest is the difference of the persisted session totals since the previous one. Drills and a 7-day unattended run are still to do.

---

## 3. Web UI Platform (Required)

### FEAT-10: Web Control Dashboard (umbrella)
* **Class / Priority:** Required · P1
* **Goal:** A hosted, multi-tenant, Material Design 3 web dashboard that replaces the terminal UI for day-to-day operation on desktop and mobile.
* **Re-scope:** FEAT-10 is now an umbrella. Its delivery is split into FEAT-31 (Agent API), FEAT-32 (control plane), FEAT-33 (PWA), FEAT-34 (orchestrator), FEAT-35 (persistence), FEAT-36 (key ingestion), and FEAT-37 (docs portal). The Telegram remote-control bot was moved out into **FEAT-45**. The earlier "in-app Markdown renderer" idea is replaced by the static docs site in FEAT-37.
* **Capabilities kept from the original proposal:** start / pause / resume / stop / `sell_all`; hot strategy and risk changes without restarts; equity curve, PnL, positions, latency telemetry; audit search.
* **Prerequisites:** the funding gate ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)) and the Phase 5 refactor (Sprints 25–31), especially the typed read-model, `PAUSED`/`HALTED` lifecycle states and `BotController` (Sprint 29).
* **Impact:** Remote intervention from any device, no restarts for tuning, and a product that can be offered to hosted users.

### FEAT-31: Bot Agent API & Typed Event Stream
* **Class / Priority:** Required · P1
* **Goal:** Give each bot container a small, internal control and telemetry port so the web tier never touches the trading event loop directly.
* **Design:**
  - New `pumpfun_trading/agent/` package served by `aiohttp.web` (already a runtime dependency, so the trading image stays lean).
  - Endpoints: `GET /health`, `GET /status` (returns `BotStatusView`), `POST /commands/{pause,resume,stop,sell_all}`, `POST /config` (`ConfigPatch`), `POST /keys/envelope` (FEAT-36), `GET /events` (WebSocket of typed events from `ops/bus.py`).
  - Bound to the private container network only; mutual auth via a per-instance token issued by the orchestrator.
  - Commands delegate to `bot/control.py::BotController`; no decision logic in the agent layer.
* **Dependencies:** Sprint 29 (`bot/state_model.py`, `bot/control.py`, `ops/bus.py`).
* **Impact:** Clean process boundary; web load can never stall slot-level trading.

### FEAT-32: FastAPI Control Plane
* **Class / Priority:** Required · P1
* **Goal:** The single public entry point: authentication, tenancy, persistence, and fan-out of bot events to browsers.
* **Design:**
  - Separate deployable (`web/api/` or a `pumpfun_trading_web` package installed with the `[web]` extra), served by Uvicorn.
  - REST + WSS; Pydantic v2 models shared with the bot's typed read-model; OpenAPI used to generate the TypeScript client for FEAT-33.
  - Auth: OIDC / JWT sessions with WebAuthn passkeys as second factor; roles `owner`, `operator`, `viewer`.
  - Every mutating call is written to `audit_events` (FEAT-35) and forwarded to the instance's Agent API.
  - Serves the built PWA and the static docs site (`/docs`, FEAT-37).
* **Dependencies:** FEAT-31, FEAT-35.
* **Alternatives considered:** Litestar (viable, smaller ecosystem). See `ARCHITECTURE-DECISIONS.md` ADR-001.

### FEAT-33: Vue 3 + Vuetify MD3 Responsive PWA
* **Class / Priority:** Required · P1
* **Goal:** A visually attractive Material Design 3 dashboard usable in desktop browsers and installable on mobile.
* **Design:**
  - Vue 3 + TypeScript + Vite; Vuetify 3 with the `md3` blueprint; Pinia stores; OpenAPI-generated client; `vite-plugin-pwa` (offline shell, install prompt).
  - Views: Overview (equity, PnL, health), Positions, Trades, Controls (pause/resume/stop/sell-all with confirmation dialogs), Settings (validated config forms with contextual help links into `/docs`), Audit.
  - Charts: TradingView `lightweight-charts`.
  - Light/dark follows the system; MD3 colour tokens shared with the docs theme.
  - Tests: Vitest component tests and Playwright desktop + mobile smoke tests, mirrored under `web/`.
* **Dependencies:** FEAT-32.

### FEAT-34: Multi-Tenant Instance Orchestrator
* **Class / Priority:** Required · P1
* **Goal:** Run one isolated bot container per tenant with quotas.
* **Design:**
  - Orchestrator service behind an `InstanceBackend` protocol: Docker Engine API first, Kubernetes later.
  - Each container gets CPU/memory limits, a read-only root filesystem, no host env access, and a private network reachable only by the control plane.
  - Lifecycle: `create → provisioned → awaiting_key → running → paused → stopped → destroyed`, persisted in the `instances` table.
  - Per-tenant quotas (instances, max position size, daily loss cap) enforced before config reaches the bot's risk pipeline.
* **Dependencies:** FEAT-31, FEAT-32, FEAT-35, FEAT-46 (image).

### FEAT-35: Persistence Layer
* **Class / Priority:** Required · P1
* **Goal:** Move from JSON/JSONL-only state (`storage/status.py`, which currently inlines `trade_ledger` in the snapshot) to a queryable database for hosted mode.
* **Design:**
  - `pumpfun_trading/storage/db/` using SQLAlchemy 2.0 async + Alembic migrations.
  - PostgreSQL when hosted (TimescaleDB hypertables optional for equity and latency series); SQLite in WAL mode for local operator/dev mode.
  - Tables: `tenants`, `users`, `sessions`, `instances`, `config_versions`, `positions`, `trades`, `audit_events`, `equity_snapshots`, `alerts`.
  - JSONL dual-write continues during migration; JSONL replay datasets stay as files.
  - Installed via the `[db]` extra; the terminal mode keeps working without it.
* **Dependencies:** Sprint 29 typed read-model.

### FEAT-36: Zero-Knowledge Key Ingestion
* **Class / Priority:** Required · P1
* **Goal:** Hosted users load their wallet key without the control plane, database, logs, or disk ever seeing plaintext.
* **Design:**
  - Worker generates an ephemeral X25519 key pair at boot and publishes the public key via the Agent API.
  - Browser encrypts the key (X25519 + HKDF + AES-GCM / libsodium sealed box); control plane relays ciphertext only.
  - Worker decrypts into a `bytearray`, builds the `Keypair`, then zeroes buffers (Volatile Key Erasure norm). Container restart = key re-entry.
  - Redaction filters in `ops/logging.py` assert no base58 key material is ever logged.
* **Dependencies:** FEAT-31, FEAT-34.

### FEAT-37: Documentation Portal
* **Class / Priority:** Required · P2
* **Goal:** Publish all docs as a searchable Material-styled site and embed it in the Web UI.
* **Design:** `mkdocs.yml` authored Material-compatible and built with Zensical (Material for MkDocs as fallback until its EOL). Static output served at `/docs` by the control plane; config fields in FEAT-33 deep-link to anchors. API/SDK reference via mkdocstrings. See [`DOCUMENTATION-PLAN.md`](DOCUMENTATION-PLAN.md).
* **Dependencies:** Sprint 31 (site build), FEAT-32 (hosting).

---

## 4. Trading, Operations & UX Enhancements (Suggested)

### FEAT-38: Hot-Config Versioning, Diff & Rollback
* **Class / Priority:** Suggested · P2
* **Goal:** Make every live config change reviewable and reversible.
* **Design:** Each accepted `ConfigPatch` writes a row to `config_versions` (author, diff, reason). The UI shows a side-by-side diff and offers one-click rollback, which is itself a validated patch through the risk pipeline.
* **Dependencies:** Sprint 29 (`ConfigPatch`), FEAT-35, FEAT-33.

### FEAT-39: Production Yellowstone gRPC Transport
* **Class / Priority:** Income (conditional) · P1 — schedule in Sprint 24D if canary data shows entries lost to latency (fills well above the signal price, or tokens already pumped by the time the buy lands); otherwise after Sprint 28
* **Goal:** Real Geyser streaming instead of the WebSocket fallback.
* **Evidence:** `streams/geyser.py:600` raises `GeyserTransportUnavailableError` unless a `custom_transport` is injected; there is no gRPC dependency.
* **Design:** `streams/yellowstone_transport.py` using `grpcio` + generated Yellowstone protos (installed via the `[geyser]` extra); account filters by bonding-curve PDA (Learnings Log); reconnect with backoff; zero-copy parsing unchanged. Contract tests against recorded payloads.
* **Impact:** Lower slot latency for entries and exits.

### FEAT-40: Live Cross-Venue Arbitrage Feed
* **Class / Priority:** Suggested · P2
* **Goal:** Close mitigated **BUG-90** (`pumpfun-arb --monitor/--live` only evaluate hardcoded sample reserves).
* **Design:** Feed `strategies/arbitrage.py` with chain-read Pump.fun curve reserves and Raydium pool reserves (`sdk/raydium.py`); only `reserves_verified=True` opportunities execute (Learnings Log).
* **Dependencies:** FEAT-39 recommended.

### FEAT-41: Metrics Exporter & Dashboards
* **Class / Priority:** Suggested · P2
* **Goal:** Standard observability for operators and the hosted SRE.
* **Design:** `ops/metrics.py` (extracted in Sprint 28) exposes Prometheus metrics (slot latency, bundle landing rate, fill slippage, open exposure, circuit-breaker state) and optional OpenTelemetry traces; shipped Grafana dashboard JSON.

### FEAT-42: Automated Treasury Profit Sweep
* **Class / Priority:** Income · P2 (Sprint 24D) — banks the income that funds the Web UI and keeps the hot wallet at its stage limit
* **Goal:** Reduce hot-wallet exposure by sweeping realised profit above a floor to a cold wallet.
* **Design:** Policy in `bot/sweep.py` (floor, minimum, cadence; the floor never drops below `reserve_balance_sol + max_total_exposure_sol + 0.01`); transfer built in `sdk/execution.py` (`transfer_sol`) with compute-budget instructions and no Jito tip; a `sweep` audit record for every sweep; disabled by default.
* **Status:** implemented in Sprint 24D ([`RUNBOOK.md` §5.6](RUNBOOK.md#56-profit-sweep-to-a-cold-wallet-feat-42-off-by-default)). The breaker treats a sweep as a withdrawal, not a drawdown, and `pumpfun-audit reconcile` counts it. Sweeps all SOL above the floor, not only realised profit: deposits above the floor are swept too. Needs its paper drill before use on a funded wallet.

### FEAT-43: PnL / Tax Export & Performance Reports
* **Class / Priority:** Suggested · P2
* **Goal:** Give operators and users downloadable trade history and periodic performance summaries.
* **Design:** `pumpfun-audit export --format csv` and a Web UI report view (win rate, expectancy, drawdown, fees, per-strategy breakdown) built from the `trades` table.
* **Dependencies:** FEAT-35.

### FEAT-44: Shadow Paper-Trading
* **Class / Priority:** Suggested · P3
* **Goal:** Evaluate a candidate strategy on the live stream without risking capital.
* **Design:** Run a second `strategies/` decision pipeline against the same events, with fills simulated by `engines/replay.py` logic; compare against live in the analytics view.

### FEAT-45: Interactive Telegram Bot
* **Class / Priority:** Suggested · P3 (deferred from FEAT-10)
* **Goal:** Mobile commands (`/status`, `/positions`, `/pnl`, `/pause`, `/resume`, `/sell_all`) on top of existing push alerts (`bot/alerts.py`).
* **Design:** Talks to the control plane API (never directly to a bot); per-user linking with a one-time code; destructive commands need confirmation.
* **Dependencies:** FEAT-32.

### FEAT-46: Docker Image & Compose for Operator Mode
* **Class / Priority:** Suggested · P2
* **Goal:** Reproducible deployment for the operator today and the base image for FEAT-34.
* **Design:** Multi-stage slim image, non-root user, healthcheck on the Agent API; `compose.yaml` with optional Postgres; documented in the deployment guide.

### FEAT-47: Replay Analytics on Parquet + DuckDB
* **Class / Priority:** Suggested · P3
* **Goal:** Fast ad-hoc analysis of large recorded datasets.
* **Design:** `pumpfun-recorder --export parquet`; DuckDB queries from `engines/optimizer.py` for faster backtest sweeps. JSONL stays the source format.

### FEAT-48: Strategy Plugin Registry
* **Class / Priority:** Suggested · P3
* **Goal:** Add strategies without editing core code.
* **Design:** Entry point group `pumpfun_trading.strategies`, discovered alongside `strategies/presets.py`; plugins implement the `strategies/base.py` protocol and are validated at load time.

---

## 5. Prioritisation & Execution Sequence

The order follows funding first, then dependencies; it matches the sprints in [`TODO.md`](TODO.md).

1. **Phase 4b — Terminal Income Track (Sprints 24A–24D, Income).** Paper pilot and canary; **FEAT-49** net PnL and reconciliation; BUG-61 backtest fidelity and tuning on live captures; **FEAT-50** pause and daily digest; **FEAT-42** profit sweep; **FEAT-39** if latency costs entries.
2. **Phase 5 — Platform Refactor (Sprints 25–31, Required).** Sprints 25–27 (packaging, tests) run alongside Phase 4b; Sprints 28–30 (`bot/run.py` decomposition, typed state + `BotController` + event bus, persistence **FEAT-35**) start after canary Stage 1 passes; Sprint 31 docs site (**FEAT-37** build).
3. **Funding gate** ([`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-funding-gate-for-the-web-ui)). Phase 6 does not start before it passes.
4. **Sprint 32 — FEAT-31 + FEAT-32.** Agent API and single-tenant control plane.
5. **Sprint 33 — FEAT-33.** Vuetify MD3 PWA MVP.
6. **Sprint 34 — FEAT-34 + FEAT-36** (with **FEAT-46** image). Multi-tenant orchestration and zero-knowledge keys.
7. **Sprint 35 — FEAT-37 embed, analytics, terminal-UI deprecation gate.**
8. **P2 follow-ups:** FEAT-38, FEAT-40, FEAT-41, FEAT-43.
9. **P3 backlog:** FEAT-44, FEAT-45, FEAT-47, FEAT-48.
