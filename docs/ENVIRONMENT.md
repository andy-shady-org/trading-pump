# Environment variables

trading-pump reads only the credentials and endpoints below, all with the
`PUMPFUN_` prefix (the module is registered as `pumpfun`). Everything else,
from order size to the capture file, is a setting in the run's JSON file:
engine keys are documented in trading-core's `docs/CONFIGURATION.md`, the
module's `module_settings` in [CONFIGURATION.md](CONFIGURATION.md).

Credentials are kept out of the settings file on purpose: trading-core hashes
that file and writes it into every run's provenance (trading-core
`docs/MODULE-GUIDE.md` §7).

`trading-pump env` shows which of these are set (names and states only,
never values) and warns about every other `PUMPFUN_*` variable that is set
(§2).

## 1. Variables that are read

| Variable | Alias (read when the name is unset or blank) | Used for | Default |
|---|---|---|---|
| `PUMPFUN_PRIVATE_KEY` | `SOLANA_PRIVATE_KEY` | The trading wallet: a base58 32-byte seed or 64-byte secret key. Live mode only; paper runs need none (the module signs nothing and the balance read refuses without it). | unset |
| `PUMPFUN_RPC_URL` | `HELIUS_RPC_URL` | The primary Solana RPC endpoint: every pool, fee-config and account read. | `https://api.mainnet-beta.solana.com` when neither RPC variable is set |
| `PUMPFUN_RPC_URLS` | `SOLANA_RPC_URLS` | More RPC endpoints, comma separated, for failover. Joined after `PUMPFUN_RPC_URL`, duplicates dropped. | unset |
| `PUMPFUN_RPC_WS_URL` | none | The Solana RPC WebSocket the new-pool feed (`new_pools`, FEAT-80) subscribes on. Only read when `new_pools.enabled` is on. It may carry the provider's key, so it is never logged: the dashboard shows its host only. | `PUMPFUN_RPC_URL` (or the first RPC endpoint) with `wss://` for `https://` |
| `PUMPFUN_STREAM_URL` | `PUMPFUN_WS_URL` | The PumpPortal WebSocket the migration feed connects to. Keep it free of keys. | `wss://pumpportal.fun/api/data` |
| `PUMPFUN_STREAM_API_KEY` | none | A PumpPortal API key, added as `api-key` at connect time and only to a `pumpportal.fun` URL. Not needed: the module subscribes to migrations only, which PumpPortal serves without a key. | unset |
| `PUMPFUN_JUPITER_API_KEY` | none | A Jupiter Portal key for `trading-pump record --jupiter-quotes` only: moves the quotes to `api.jup.ag` and sends the key as an `x-api-key` header. | unset (keyless `lite-api.jup.ag`) |

The engine's variables (`TRADING_CORE_ALERT_*`, `TRADING_CORE_*_PATH`,
`TRADING_CORE_GIT_COMMIT`) are trading-core's: see its `docs/ENVIRONMENT.md`.

## 2. Variables that are no longer read

pumpbot read about a hundred `PUMPFUN_*` variables (the archived
[manual](archive/pumpfun-trading/ENVIRONMENTAL-VARIABLES.md)). trading-pump
reads the seven above. When any other `PUMPFUN_*` variable is set, the module
records a warning at start (and `trading-pump env` prints it), naming the
variable and what replaces it, never its value, because some of them held
webhook URLs:

| The old variables | Now |
|---|---|
| `PUMPFUN_ALERT_*`, `PUMPFUN_TELEGRAM_*` | Alerts are the engine's: `TRADING_CORE_ALERT_*` |
| Paths and retention (`PUMPFUN_STATUS_PATH`, `PUMPFUN_AUDIT_LOG_PATH`, `PUMPFUN_EVENT_LOG_PATH`, `PUMPFUN_BOT_LOG_PATH`, `PUMPFUN_LOG_*`, `PUMPFUN_AUDIT_*`), diagnostic events, `PUMPFUN_CONFIG*`, `PUMPFUN_DRY_RUN` | Engine settings (`status_path`, `audit_log_path`, `event_log_path`, `log_file`, `mode`) or `TRADING_CORE_*_PATH`; the engine rotates its own files |
| Risk and exits (`PUMPFUN_MAX_*`, `PUMPFUN_DRAWDOWN_MODE`, `PUMPFUN_PROFIT_*`, `PUMPFUN_STOP_LOSS`, `PUMPFUN_TRAILING_*`) | Engine settings `risk`, `breaker`, `exits` |
| `PUMPFUN_GIT_COMMIT`, `PUMPFUN_HEADLESS` | `TRADING_CORE_GIT_COMMIT`; `trading-core run --headless` |
| The replay capture (`PUMPFUN_RECORD_REPLAY`, `PUMPFUN_REPLAY_*`), costs (`PUMPFUN_JITO_*TIP*`, `PUMPFUN_PRIORITY_FEE_MODE`, `PUMPFUN_USE_JITO`, `PUMPFUN_COMPUTE_UNIT_LIMIT`, slippage), screening (`PUMPFUN_ANTI_RUG_*`, `PUMPFUN_MAX_GINI_*`, cluster analysis), presets and buy size | `module_settings` (`capture`, `execution`, `screening`) or the engine's `order_size` |
| Geyser, arbitrage, capital rotation, pre-graduation, copy trading, momentum, Raydium, tiered take-profit, live Jito tuning, `PUMPFUN_RECONCILE_STATUS_PATH`, stream retry limits | Features that were not ported ([dev/TODO.md, Not ported](dev/TODO.md#not-ported)) |

The full list with each hint is `REPLACED_ENV_VARS` in
`trading_pump/config/env.py`; a test checks that every variable the archived
manual documented has a hint there.

## 3. Notes from running pumpbot that still apply

* **RPC capacity.** Give every run its own RPC key: two runs on one key
  share its rate limit, and an hour with no working endpoint once left two
  bots blind (BUG-149, BUG-151). List a fallback in `PUMPFUN_RPC_URLS`. The
  public mainnet RPC is fine for a short paper test and rate limited for a
  real run. Each followed graduate costs one pool read every 2 s for its
  first 5 minutes, then one every 10 s ([dev/COSTS.md §3.1](dev/COSTS.md#31-helius-rpc-credits)).
* **Mainnet only.** Providers give each key a mainnet and a devnet URL. A
  devnet endpoint answers every mainnet pool read with "no account", so the
  rc.9 smoke run followed 10 graduates and read none (BUG-160). The module
  checks each endpoint's network at start and drops any that is not
  mainnet-beta (or reports `rpc network` degraded when none is).
* **Order of the RPC list.** pumpbot used only `PUMPFUN_RPC_URLS` when it was
  set; trading-pump puts `PUMPFUN_RPC_URL` first and adds the list after it.
* **Keys stay out of URLs.** A provider key in a URL (`?api-key=`, `/v2/<key>`)
  is masked wherever a URL is written (trading-core redaction, BUG-102), but
  keep the PumpPortal key in `PUMPFUN_STREAM_API_KEY`: the stream URL is
  shown on the dashboard. A `PUMPFUN_STREAM_URL` that carries `api-key` still
  works; the key is split out and a warning says to move it (BUG-118).
* **PumpPortal keys and funds.** With a key, PumpPortal's rules for keyed
  connections apply: its linked wallet must hold at least 0.02 SOL, and a
  connection that was refused for lack of funds is not re-accepted after a
  top-up (BUG-112, BUG-156). Without a key none of this applies.
* **Where to keep them.** In a `.envrc` (direnv) or `.env` that is
  `chmod 600` and never committed; `.envrc.sample` lists the names. The test
  suite deletes every `PUMPFUN_*` and `TRADING_CORE_*` variable before each
  test, so an operator shell never changes a result.
