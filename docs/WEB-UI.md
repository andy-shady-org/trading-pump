# Web Dashboard & Hosted User Instance Architecture

The Web Dashboard (FEAT-10) is the institutional mission control portal for `pumpfun-trading`. Designed for modern web browsers, it provides end-users with real-time operational control, live portfolio analytics, hot configuration adjustments, and an embedded documentation reader without requiring terminal access or shell permissions.

---

## 1. System Architecture & Hosted Sandbox Topology

In hosted multi-user or single-instance cloud environments, end-users interact exclusively through the authenticated FastAPI web interface:

```
  +-------------------------------------------------------------------+
  |                  User Browser (Web Dashboard)                     |
  |  - Real-Time React / Tailwind Frontend                            |
  |  - Sub-100ms WebSocket Live Telemetry                             |
  |  - Interactive Lightweight Charts (Equity Curves / Latency)       |
  |  - Embedded Markdown Documentation Reader                         |
  +---------------------------------+---------------------------------+
                                    | (HTTPS / WSS / TLS 1.3)
                                    v
  +-------------------------------------------------------------------+
  |                  FastAPI Asynchronous Gateway                     |
  |  - Session Token Authentication (JWT / Bearer)                    |
  |  - REST Control API (Lifecycle, Hot Config, Forensic Logs)        |
  |  - WebSocket State Stream Broadcaster                             |
  +---------------------------------+---------------------------------+
                                    |
                                    v
  +-------------------------------------------------------------------+
  |               Isolated Bot Instance Runtime Sandbox               |
  |  - Volatile In-Memory Keypair Vault (Zero Plaintext Disk Storage) |
  |  - Trading Bot State Machine Engine                               |
  |  - Geyser gRPC Streaming & Jito MEV Bundler                       |
  +-------------------------------------------------------------------+
```

---

## 2. User Credential Security & In-Memory Vault Model

A core architectural guarantee of the Web UI is absolute protection of user wallet private keys against filesystem theft or accidental leakage.

### A. Zero Host Environment Variable Exposure
* **Sandbox Isolation**: Web users operate in an isolated environment without access to host system environment variables, shell processes, or terminal logs.
* **No `.env` Requirement**: End-users do not interact with server configuration files or `.env` disk state.

### B. Ephemeral In-Memory Key Management (Zero Disk Persistence)
* **Secure Key Ingestion**: Users supply their Solana private key through a client-side encrypted upload modal over TLS.
* **Volatile Memory Handling**: The key is decrypted into ephemeral application memory (RAM) exclusively for the duration of the active trading session.
* **Strict Non-Persistence Rule**: **Private keys are never written to disk, SQLite databases, log files, or persistent storage.**
* **Automatic Session Eviction**: Stopping the bot instance or logging out immediately zeroes out the memory buffers holding the private key.

### C. Future Security Roadmap (Envelope Encryption & MPC)
* **Client-Side Envelope Encryption**: Upcoming sprints will introduce client-side AES-GCM encryption where the decryption key remains in the user's browser session.
* **Session Ephemeral Vaults**: Hardware security module (HSM) and multi-party computation (MPC) integrations for institutional hosted clusters.

---

## 3. Web UI Lifecycle Controls & Hot Configuration

The Web Dashboard gives users full control over the trading engine without requiring service restarts:

### A. Lifecycle Operations
* **Start Engine**: Initializes Geyser gRPC subscriptions and activates candidate monitoring.
* **Pause / Resume**: Temporarily suspends new buy order executions while preserving active position monitoring and trailing stop management.
* **Emergency Stop**: Immediately cancels all pending buy requests and suspends candidate ingestion.
* **Panic Liquidate All (`sell_all`)**: One-click emergency action that submits high-priority market exit orders across 100% of open positions.

### B. Hot Configuration Mutation
Users can modify strategy parameters in real time via REST endpoints (`/api/v1/config`):
* Adjust base buy allocation (e.g. from `0.10 SOL` to `0.25 SOL`).
* Update take-profit multipliers and trailing stop retracement percentages.
* Switch between `conservative`, `balanced`, and `aggressive` presets on the fly.
* Tune anti-rug risk thresholds without missing market slots.

---

## 4. Interactive Portfolio Analytics & Telemetry

The Web Dashboard provides rich data visualization components:

* **Real-Time Equity Curve**: Live portfolio valuation chart updating tick-by-tick with realized profits and unrealized mark-to-market positions.
* **Drawdown & Circuit Breaker Gauge**: Visual gauge tracking daily PnL against the 15% hard circuit breaker threshold.
* **Active Position Cards**: Visual cards displaying token avatars, bonding curve progress bars (0% to 100% graduation), unrealized ROI, and trailing stop distances.
* **Order Execution Latency Graphs**: Histogram displaying slot-to-inclusion latency and Jito validator tip execution stats.

---

## 5. Embedded In-App Documentation Hub

The Web Dashboard includes an integrated documentation viewer that natively parses and renders all project Markdown guides (`User Guide`, `Strategy Logic`, `Risk Controls`, `Feature Matrix`, `Audit Runbook`):

* **Context-Aware Help**: Tooltips and config fields link directly to corresponding sections in `docs/STRATEGY.md` and `docs/RISK.md`.
* **Full-Text In-App Search**: Instant search across all documentation directly within the browser interface.
* **Operator Transparency**: Guarantees users understand the mathematical models and risk parameters governing their capital.

---

## 6. Terminal UI Deprecation & Transition Roadmap

The Terminal UI (`pumpbot`) and Web Dashboard fulfill distinct roles across project development phases:

```
  Phase 1 (Current): Terminal UI Self-Funding & Testing
  [Terminal UI (pumpbot)]  ---> Active Operator Trading (Generates Development Capital)
  [Web UI Specification]   ---> Architecture Design & API Staging (FEAT-10)

  Phase 2 (Near Future): Web UI Beta & Dual Run
  [Terminal UI (pumpbot)]  ---> Maintained for Local Diagnostics & Testing
  [FastAPI Web Dashboard]  ---> Live User Instances & Primary Control Center

  Phase 3 (Production Maturity): Web UI Primary Standard
  [FastAPI Web Dashboard]  ---> Official Production Mission Control Portal
  [Terminal UI]            ---> Fully Retired / Deprecated
```
