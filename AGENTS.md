# AGENTS.md

## Claude 5.5 Opus Self-Correction & Continuous Learning

As **Claude 5.5 Opus**, you are required to treat this repository as the Pump.fun / PumpSwap module of a live trading system built on **trading-core**, and this `AGENTS.md` file as your persistent memory. Because quantitative trading environments evolve quickly, you must automatically update your own rules, adapt to edge cases, and self-correct based on runtime or user feedback.

### 1. Triggers for Updates
You must automatically append a new rule to the **"Local Norms"** or **"Learnings Log"** sections of this file if:
- **User Correction:** The user explicitly corrects your code, math logic, Solana transaction layout, or architectural layout.
- **Solana/Jito Runtime Failures:** A transaction fails on-chain, a Jito bundle drops, or a zero-copy parser breaks due to an unhandled byte alignment or edge case.
- **Module Contract Friction:** The module cannot express something through trading-core's `TradingModule` contract, works around it, or a core change breaks the module. Record it here and in trading-core's `docs/dev/TODO.md`; never patch around the core.
- **Test Failures:** A test fails because of an unwritten assumption or missed edge case.
- **Stale Context:** You discover that a file path, codebase map, or dependency listed in this file is outdated.

### 2. Instructions for Self-Updating
1. **Identify the Root Cause:** Pinpoint exactly what went wrong (e.g., "miscalculated PDA derivation for Token-2022 accumulator").
2. **Draft a Durable Rule:** Write a concise, actionable directive (a "Do" or "Don't") to prevent the error from happening again. Do not just log the error; write the permanent structural fix.
3. **Modify the File:** Use your file-editing tools to surgically append the rule to the end of the appropriate section below. Do not overwrite or erase existing rules.
4. **Keep it Concise:** Keep instructions short and punchy to conserve context tokens for future sessions.

---

## Local Norms
pumpfun-trading's norms are kept (originals in `docs/archive/pumpfun-trading/AGENTS.md`), reworded where the code they named moved or was retired, and new ones added for the module.
- **The Module Owns The Venue, The Core Owns The Run:** Solana, Pump.fun and PumpSwap knowledge lives here; sizing, risk, the breaker, exits, accounting, persistence, alerts and the dashboard are trading-core's. Never re-implement an engine concern in this package; if the contract cannot express something, change trading-core (with its own test and `TC-<n>` bug) and pin the version here.
- **Fail Closed, Never Guess:** a failed pool read makes the quote stale and the fill refused (`ExecutionRefused`); a missing balance raises (BUG-158); a drained pool is a result, not a gap. No fallback number (a default price, a placeholder market cap, a simulated balance) may reach a decision or a fill.
- **Credentials In The Environment, Everything Else In Settings:** only the six `MODULE_ENV_VARS` (`docs/ENVIRONMENT.md`) are read from the environment; every other choice is a validated `module_settings` key (`PumpSettings`, unknown keys are errors). Never read a new `PUMPFUN_*` variable without adding it to `MODULE_ENV_VARS` and the manual (the test checks both).
- **Asynchronous Jito Bundle Polling:** Never block the event loop when waiting for Jito bundle statuses; always use non-blocking `asyncio` polling or websocket event confirmation.
- **Micro-Lamport Compute Budget Management:** Every transaction builder must explicitly append a `SetComputeUnitPrice` and a tight, simulated `SetComputeUnitLimit` instruction to prevent transaction drops or wasted fee capital.
- **Zero-Copy Alignment Checks:** Any structural or byte change to a decoder (`sdk/`, `streams/`) must match the program's real account layout; pin it to real mainnet account bytes in `tests/support/payloads.py`.
- **Volatile Key Erasure:** Code that handles the private key must keep it in `Credentials` (hidden `repr`) and drop references as soon as the signer is built; never log, persist or put it in settings.
- **Fail-Fast Risk Validation:** All pre-execution checks run before the instruction assembly layer: the venue checks (standard pool, screening with its Gini and concentration caps) as pipeline filters here, the portfolio checks in trading-core's single risk gate (`risk/limits.py`) and breaker. Never add a risk check inside an executor or builder.
- **Income Path First:** A lane must show net income after every cost before anything is built on it. Prioritise the FEAT-76 paper run and its gates (`docs/dev/TODO.md`) over new features, report profit net of fees, priority fees, Jito tips and rent, and judge every run with a pre-registered verdict.
- **Mirrored Test Layout:** New tests go in `trading_pump/tests/unit/<pkg>/test_<module>.py` (top-level modules: `tests/unit/test_<module>.py`; cross-component flows in `integration/`, Hypothesis in `property/`), build objects and payloads from `tests/support/`, and never use coverage-named files (`test_coverage_*`, `*_boost*`, `*_full`). See `docs/dev/TESTING.md`.
- **100% Or It Does Not Merge:** statement and branch coverage stay at 100% on Python 3.11–3.14 (`nox -s tests`); Ruff, Black, flake8 and mypy pass. Prefer deleting an unreachable branch over a pragma.
- **Feature Docs Track Code:** Document a new, unbuilt feature in `docs/dev/PROPOSED-FEATURES.md` (next free FEAT-ID, catalogue row). When its code ships, move it to `docs/FEATURES.md` and leave a pointer behind. For a partly built feature, list what ships in `FEATURES.md`, mark the missing parts **Not built** there, and keep those parts in `PROPOSED-FEATURES.md`. Never list unbuilt work in `FEATURES.md` (FEAT-10 was listed as implemented with no code).
- **TODO Lists Open Work Only:** `docs/dev/TODO.md` holds open items; finished work lives in `docs/dev/DONE.md` under its original heading. When a section's last box is ticked, move it to `DONE.md` with a link to its CHANGELOG release; in a partly done section, move the ticked items and leave one "Done:" line. Verify a completion against the code before ticking or moving it, put evidence and results in `STRATEGY-PIVOT.md` §6 or `releases/`, not in TODO, and never leave an open box in `DONE.md` (mark it superseded, moved or closed with the reason).
- **History Is Kept, Not Rewritten:** `docs/archive/pumpfun-trading/` is frozen (only link fixes); `BUGS.md`, `CHANGELOG.md`, `DONE.md` and `STRATEGY-PIVOT.md` are appended to, never edited back. A port of retired code brings the fixes and tagged tests of every bug `BUGS.md` lists for it.

## Learnings Log & Avoided Mistakes

Every learning from pumpfun-trading is kept below, in its original words, with where it applies now: **here** (code in this repository), **trading-core** (the code moved there; the rule is in trading-core's `AGENTS.md` too), **retired code** (code not ported; apply the rule if it is ported back), or **everywhere** (a working practice). File paths in these entries name pumpfun-trading's layout at the time. New learnings follow at the end.

- **[CRITICAL] Slippage Calculation Target:** Avoided calculating slippage based on static REST API prices. Pump.fun bonding curve prices can shift drastically within a single slot. Always compute slippage against the dynamic, local virtual reserves tracked directly from the real-time Geyser stream. *[Applies: here.]*
- **[EXECUTION] Jito Tip Placement:** Avoided appending Jito tips as standalone transactions or placing the tip instruction at the beginning of a transaction. The tip must be the *final instruction* inside the transaction payload within the bundle to guarantee inclusion and prevent MEV searchers from unbundling. *[Applies: here.]*
- **[RISK] Developer Allocation Fraud:** Avoided checking developer wallet balances via static snapshots. Devs can scatter supply across multiple fresh puppet wallets prior to launch. Shifted to evaluating the collective top-5 holder concentration matrix continuously during the first 30 seconds of token creation. *[Applies: here.]*
- **[MATH] Bonding Curve Overflows:** Avoided native integer math for token-to-SOL conversions. High-velocity minting curves can easily overflow standard 64-bit bounds during aggressive volume spikes. Always utilize fixed-point math with explicit scaling factors when tracking $P = \Delta y / \Delta x$. *[Applies: here.]*
- **[STREAMS] No Fake Connections:** Never set a stream to CONNECTED without a real transport; fail fast (`GeyserTransportUnavailableError`) and fall back. Yellowstone account filters must use bonding-curve PDAs, not mints. *[Applies: retired code: Geyser; the rule holds for any stream.]*
- **[ARB] Chain-Read Reserves Only:** Never execute or bank arbitrage on estimated/placeholder reserves; only `reserves_verified=True` opportunities may execute. *[Applies: retired code.]*
- **[DOCS] Completion Claims Track Code:** TODO item 25 claimed `bot/run.py` was a "lightweight facade" while it had regrown to ~3,770 lines. Before ticking or citing a completed refactor, verify it against the current code (file size, responsibilities); re-open the item when it regresses. *[Applies: everywhere.]*
- **[SCREENING] Stream Payloads Are Not Enrichment:** PumpPortal/Geyser create events carry no socials or holders. Always enrich screened tokens (API record, metadata `uri`, `getTokenLargestAccounts`) with bounded timeouts, since screening runs inside `_trade_lock`; never skip enrichment because stream data was passed (BUG-95). Keep tests off live endpoints. *[Applies: here.]*
- **[EXECUTION] Close What You Open:** Every buy of a new mint pays ~0.002 SOL token-account rent (BUG-96). A full exit must close the account in the sell transaction (only when the sell empties it), and every trade record must carry its fees, tip and rent; never report or gate on gross PnL. *[Applies: here.]*
- **[TESTS] No Cost RPC In Tests:** Post-fill cost capture calls `getTransaction`. `tests/conftest.py` stubs `PumpFunExecutionClient.get_transaction_costs`; only modules that set `USES_REAL_TRANSACTION_COSTS = True` (and patch `rpc_pool.request`) may call the real one. *[Applies: here.]*
- **[EXECUTION] Don't Hard-Code Rent:** Mainnet rent was lowered (Token-2022 ATA 1,513,840 lamports, not 2,039,280). Live costs must come from the transaction meta; modelled values are estimates, so re-check them with `getMinimumBalanceForRentExemption` before relying on them. *[Applies: here.]*
- **[TESTS] Mirrored Test Packages:** Every `tests/unit/<pkg>/` directory needs an `__init__.py`; without it, same-named modules (`unit/cli/test_events.py`, `unit/ops/test_events.py`) collide in pytest and mypy. *[Applies: here.]*
- **[OPS] Rotate By On-Disk Name:** Background gzip means `X.1` may still be plain. Shift archives by the name actually on disk (never re-derive `.gz`), and join the pending compression before the next rotation (BUG-97). *[Applies: trading-core.]*
- **[TESTS] No Network In Tests:** Tests that called mainnet passed locally and failed in CI on HTTP 429. `tests/conftest.py` blocks non-local DNS; stub `get_token_program_for_mint` (or use `offline_trade_rpc`) for ATA/builder paths, and give mocked aiohttp sessions `closed = False` and a mocked `request`. *[Applies: here.]*
- **[SECURITY] Redact URLs Before Persisting:** Provider URLs carry API keys (`?api-key=`, `/v2/<key>`). Never write a raw endpoint or stream URL to status files, logs, events or alerts; serialise through `ops/redact.py` (`redact_url` / `redact_text`) and identify endpoints by host label (BUG-102). *[Applies: here and trading-core.]*
- **[REPLAY] Recorded `signal` Is Not An Order:** `--record-replay` captures tag every market trade and new token with `signal`; only snapshots with `reason` (and no `user`) are the bot's own fills. Live-fidelity replay must never treat `signal` strings as exits, and must say plainly that the screener is not replayed. *[Applies: retired code.]*
- **[TESTS] Green On 3.14 Is Not Green On 3.11:** A global `Path.stat` mock passed on 3.14 but broke `Path.glob` on 3.12/3.13. Never patch `pathlib` methods globally; wrap the real call and fake only the target file. Supported interpreters are 3.11–3.14 (`nox -s tests-<ver>`, CI matrix). *[Applies: everywhere.]*
- **[PACKAGING] Tests Never Ship:** `packages.find` exclude alone still packed `pumpfun_trading/tests` as package data; keep the `MANIFEST.in` prune and run `nox -s package` after any packaging change. Never add a release/publish workflow (proprietary). *[Applies: here.]*
- **[ASYNC] Never Cancel A Dequeued Write:** Cancelling a task awaiting `asyncio.to_thread` also cancels a not-yet-started executor job, so data already taken off a queue is lost on shutdown (BUG-103). Shield in-flight writes and finish them before re-raising `CancelledError`; test shutdown races deterministically (busy one-thread executor), not with wall-clock durations. *[Applies: here.]*
- **[TESTS] Slow Tests Mean Unmocked Retries:** Most of the suite's 136 s was real retry backoff on blocked-network API/RPC lookups, not the bot. Profile with `--durations` before tuning; never add real sleeps or rely on backoff in tests (`instant_retry_backoff` in `tests/conftest.py` skips it; `USES_REAL_RETRY_BACKOFF = True` to opt out), and keep a new retry loop's sleep inline in a `request` method or extend that fixture. *[Applies: here.]*
- **[TESTS] `make_config` Is Dry-Run:** `make_config()` defaults to `dry_run=True` but `TradingBotConfig()` to `False`. When converting an inline config, pass `dry_run=False` unless the call already set it; scope `ruff --select I --fix` to the files you touched, never the whole tests tree. *[Applies: retired code.]*
- **[TESTS] Resolving A Bug Means Tagging A Test:** Marking a bug RESOLVED in `BUGS.md` fails `unit/test_suite_layout.py` until a test carries `@pytest.mark.regression("BUG-xx")`; never add the ID to `KNOWN_UNTAGGED` instead. A golden-replay diff is a behaviour change: explain it before regenerating. *[Applies: here.]*
- **[PAPER] One Price Source, Sane Curves Only:** Stage 0 reported +63.5 SOL that was a pricing artefact (BUG-104): paper entries used the stream's market cap, exits the on-chain curve, and a non-standard curve variant decoded to 25×–3,500×. Price entries and exits from the same source, reject curves whose reserves fail sanity checks, and treat any paper result far above costs as a bug until explained. Judge strategies per position, never per sell (BUG-105). *[Applies: here.]*
- **[RPC] Empty Is Not Zero:** `getTokenLargestAccounts` on a load-balanced RPC flaps for new mints (2, 0, 2, 0 accounts within 6 s), which hid holders for 67% of Stage 0 buys (BUG-107). Treat an empty index-backed answer as "not yet indexed": retry inside the lookup budget, count outcomes, and never score it as "no holders". *[Applies: here.]*
- **[TESTS] Strip The Operator Shell:** An exported `PUMPFUN_JITO_TIP_LAMPORTS` from `.envrc` changed golden-replay costs locally. `tests/conftest.py` deletes every ambient `PUMPFUN_*` variable per test; set what a test needs with `monkeypatch.setenv`, and read `PUMPFUN_UPDATE_GOLDEN` at import time only. *[Applies: here.]*
- **[ENTRY] Trust The Program, Not The Feed:** PumpPortal's create feed carries other launchpads; Stage 0 bought 263 non-Pump.fun mints, USDC included (BUG-108). Buy only when the curve PDA exists and is owned by the Pump.fun program, never let a missing curve fall through to a simulated paper fill, and never re-buy a closed mint (BUG-109). Test new-token flows with `SAMPLE_PUMP_MINT` or set `require_pump_mint_suffix=False`. *[Applies: retired code: launch mode; the same lesson is why the lane keeps only standard pools.]*
- **[ASYNC] Alerts Are I/O Too:** `_send_alert` ran a blocking `urlopen` (10 s timeout) on the trading loop for every alerted event, buys included (BUG-110). Never call a sync network client from loop code; dispatch with `asyncio.to_thread` / a tracked task, and flush (bounded) before `asyncio.run` exits. Test it with a webhook that blocks until released, not with timings. *[Applies: trading-core.]*
- **[OPS] Withdrawals Are Not Drawdowns:** A profit sweep lowers wallet equity on purpose. Anything that moves SOL out must call `DailyEquityTracker.record_withdrawal` and write a `sweep` audit record that `reconcile` counts, or the breaker trips and the wallet check shows a gap (FEAT-42). *[Applies: retired code.]*
- **[STREAMS] Check That Subscriptions Deliver:** PumpPortal refuses `subscribeTokenTrade` without a funded API key and replies with a mint-less `message` the bot dropped, so v0.2.0 and v0.2.1 held positions blind (exits on a 5 s curve poll, empty order flow, captures with no trades; BUG-112). Log and alert any server `message`, and treat a held mint with no trade messages as degraded data, not a quiet market. *[Applies: retired code: the trade feed; the rule holds for any subscription.]*
- **[STREAMS] A Reconnect Is Not A Fix:** BUG-116 cleared the trade-feed refusal on every reconnect, so buys resumed blind while the key's wallet was still empty. Close a feed breaker only on proof of delivery (a confirmed subscription or data), probe while it is open, and name the likely cause (metered API key out of funds) in the alert. *[Applies: retired code: the trade feed.]*
- **[ENTRY] Mayhem Curves Break The Invariant:** mayhem-mode curves drifted to 46 SOL virtual reserve 2 s after launch. Skip `is_mayhem_mode` tokens (`skip_mayhem_mode`) unless their pricing is modelled. *[Applies: retired code.]*
- **[CONFIG] Defaults Are Not Choices:** a preset filled in the public PumpPortal URL, which beat the keyed `PUMPFUN_STREAM_URL` (BUG-117). Never let a filled-in default outrank an env override; check precedence by loading the real runtime config + env through `TradingBot`, not by testing the env value on its own. *[Applies: everywhere.]*
- **[SECURITY] Secrets Are Not Part Of A URL:** the dashboard printed `stream_url` with the PumpPortal `?api-key=` in it (BUG-118). Keep provider keys in their own env variable (`PUMPFUN_STREAM_API_KEY`), keep displayed/stored URLs key-free, join the key only at connect time, and pass any URL a UI renders through `redact_url`. *[Applies: here.]*
- **[STREAMS] Unsubscribe Where Positions Close:** exits ran from six call sites and only one passed the websocket, so 538 exited mints kept streaming billed trade messages (BUG-120). Put per-position cleanup in the one function every exit goes through (`_sell_token`), never at the call sites. Net PnL means every record: a check that sums only sells drops the buy-side costs (BUG-119). *[Applies: retired code.]*
- **[ENTRY] Demand Before Entry:** buying at the create event lost −0.579 SOL over 1,675 positions (10.3% won) because most launches get no follow-on buyers; exits can't fix that. Never buy a launch without evidence of follow-on demand (`entry_mode: "confirmed"`: watch → RPC curve poll → trade subscription → confirm); `"launch"` stays the default only for back-compat. See `docs/dev/STRATEGY-PIVOT.md`. *[Applies: retired code: launch mode; the strategy lesson stands.]*
- **[CONFIG] Check Limits Against Size:** the first `momentum` preset replay bought nothing: one 0.02 SOL position was 40% of the 0.05 SOL exposure cap, above the inherited 25% `max_token_concentration_pct`. When a preset changes `buy_amount_sol` or exposure, check every inherited risk cap still admits one position, and read `entry_rejections` before tuning signals on a zero-trade replay. *[Applies: everywhere.]*
- **[REPLAY] Model The Latency You Pay:** replay filled confirmed entries at the signal price while paper waited 1.5 s and took a 100 bps penalty, so replay beat paper by 0.016 SOL and an 8-buyer variant looked profitable when it wasn't (BUG-121). Every paper execution setting (`paper_entry_*`) must be modelled in replay; run `--compare-audit` before trusting a sweep, and re-run sweeps after any replay fix. *[Applies: here.]*
- **[REPLAY] Replay Can't See What It Didn't Record:** the rc.1 audit showed 14 of 118 paper fills > 10% above the signal; replay of the same capture saw 5, because the paper fill reads the curve and the capture only has the trades it subscribed to. Judge rules that act on the fill price (the drift guard) on paper captures, not replay sweeps, and say so when reporting them. *[Applies: here.]*
- **[EXECUTION] Graduated Coins Trade On PumpSwap:** the bot waited for a Raydium pool after graduation, but Pump.fun migrates into PumpSwap, and the WebSocket deployment never saw the completion at all (BUG-123). Every held mint needs a completion signal on every transport (curve refresh `complete`, `subscribeMigration`) and an exit on the venue the program actually migrates to; pin new program layouts to real mainnet account bytes in tests. *[Applies: here.]*
- **[ANALYSIS] Beat A Random Cut:** every filter on a losing lane "improves" net PnL because it trades less. Compare a filter's kept net with the same share of the total (random cut), on at least two captures, before calling it an edge. *[Applies: everywhere.]*
- **[CONFIG] A New Field Needs The Resolver:** `resolve_strategy_config` lists every `TradingBotConfig` field by hand, so a field added only to `base.py` is silently ignored in config files (BUG-125: the profit sweep, FEAT-50 alerts and `enable_pumpswap_exit`). Add every new field to the resolver too; `test_every_config_field_survives_a_config_file` fails otherwise. `make_config` / `replace` bypass the resolver, so they can't catch this. *[Applies: here.]*
- **[ANALYSIS] Score The Copy, Not The Wallet:** the operator's "successful" wallet `29yFzeBZ…` turned out to be a serial creator (100 screened launches, no recorded trades), and copying every captured wallet at our 1.5 s delay and costs lost ~0.0013 SOL per copy. Rank wallets only on our simulated copy net on closed copies (`pumpfun-replay --wallet-scores`), check a second capture, and check whether a wallet is a creator before calling it a trader. *[Applies: retired code.]*
- **[TOOLS] No Stash In A Shared Tree:** a subagent's `git stash` / `pop` briefly took another agent's uncommitted work with it. Never stash, checkout or reset in a working tree other agents are editing; run read-only git commands only, and verify with `git status` after any slip. *[Applies: everywhere.]*
- **[REPLAY] Scanned Nets Are Relative:** `--shadow-scan` modelled the rc.1 baseline at −0.006 SOL where paper lost −0.099 on the same 118 signals, because scanned fills only see recorded prices. Compare a scanned variant only with the scanned baseline (random cut), never with paper or a replay total. *[Applies: retired code.]*
- **[TOOLS] One Editor Per File:** mixing `sed -i` with the edit tools on the same file left a duplicated tail in `test_presets.py` that broke collection. Edit a file with one tool, then `git diff` it before running the suite. *[Applies: everywhere.]*
- **[PAPER] Model The Exit Too:** paper sells took no slippage while replay took 100 bps, so rc.2 paper showed +0.014 SOL where a realistic exit gave about −0.007, and parity was off by 0.028 (BUG-126). Every paper fill, buy or sell, must pay the latency and price impact a live fill pays, through a config key replay reads too (`paper_entry_*`, `paper_exit_slippage_bps`); set them in every config you `--compare-audit` against. *[Applies: here.]*
- **[CAPTURE] Observe Without Touching:** rc.3 records curves the bot never trades (screen-reject sample, discovered near-graduation curves). Keep such data off every decision path (no watch list, promotion, shadow book or `GraduationEngine` feed), poll it in its own task, tag its rows (`source` in `RECORD_ONLY_POLL_SOURCES`, `observation_*` events) and skip them in replay and the shadow tools, or a "measurement" changes fills and parity. Never let a record-only API call share the screening client's retry loop or breaker. *[Applies: here.]*
- **[OPS] One Policy Per File:** a folder-wide prune with the audit policy deleted replay parts the replay policy was meant to keep, and the first 20 h of a 37 h run were gone before anyone looked (BUG-157). Prune each file by its own name and policy, never by extension; after a long run, check that the oldest capture row is near the start time before analysing it. *[Applies: here.]*
- **[STREAMS] Retry On A Fresh Connection:** a PumpPortal top-up at 15:49 was not accepted by the probe on the connection that had refused it, and both rc.7 bots stayed blocked (BUG-156). When a provider refuses on a connection, retry on a new one; never let a reconnect reset a degraded status before the feed proves it works, and check the funding source's on-chain history before guessing at a cause. *[Applies: retired code: the trade feed; the rule holds for any keyed connection.]*
- **[DATA] One Pool, Several Names:** GeckoTerminal and DexScreener disagree on ids: four.meme curves are `<token>:4meme` on DexScreener, and some BSC pools (PancakeSwap Infinity, Uniswap v4) are not indexed there at all, so 40% of a live run's BSC pools came back missing (FEAT-74). When joining two data providers, match on the token as a fallback, mark what was substituted, and check the miss rate on live data per chain before trusting a recorder. *[Applies: here.]*
- **[ANALYSIS] Charts Show Survivors:** the operator saw many coins on charts that graduated, crashed and then ran, and asked why the bot missed them (2026-10-26). Of 39 fast graduates in the rc.6 data that fell below half the graduation price within 15 minutes, none recovered: charts and trending lists show the coins that survived. Before building for a pattern seen on charts, measure how often it happens across every coin it could have happened to (FEAT-73). *[Applies: everywhere.]*
- **[CAPTURE] Record The Population, Not The Selection:** rc.3 followed only the 14% of launches its screen passed or sampled, and dropped every coin at its sell, so ideas the operator raised (buy at launch, hold through the first dip, take +10%) could not be tested on it (user correction, 2026-10-24). Sample the whole population from its first event and keep following each exit for a while, record-only and off every decision path (FEAT-72). *[Applies: here.]*
- **[DATA] Probe Free APIs Before Picking Defaults:** the keyless Jupiter API allowed 5 requests per ~10 s, and GeckoTerminal sent `Retry-After: 0` while still limiting, the odd 500, and a 401 at its ~6-month history limit (FEAT-65 recorder). Check a free endpoint's real limits by hand before setting pacing defaults, retry 429 / 5xx with bounded growing waits (never trust a zero reset), treat a paging 401 as end of history, and keep such recorders in their own process. *[Applies: here.]*
- **[DATA] Check A Plan's Limits Before Recommending It:** a free CoinGecko demo key was named as the fix for GeckoTerminal's 6-month bar limit, but the Demo plan's OHLC history is limited to 365 days too (FEAT-65; user correction). Before a doc or reply names a data source, read the provider's plan limits (history depth, rate, region) and quote them; prefer a source you can test, and say when it was not. *[Applies: everywhere.]*
- **[RISK] A Limit Nobody Checks Is Not A Limit:** the ratchet floor was computed and only displayed (BUG-127), and daily locks lifted at UTC midnight with no cumulative cap (BUG-128). Every documented risk limit needs a test that trips it, locks must outlast rollovers, and daily limits need a cap across days that only the operator resets. *[Applies: trading-core.]*
- **[LIVE] Real Numbers Only:** live positions were measured from the signal market cap (BUG-129) and the day's baseline could come from the simulated start balance (BUG-130). Price live entries from the fill, value equity at exit value (BUG-136), and never let a placeholder (`or 30.0`, 69 SOL, a simulated balance) reach a decision. *[Applies: here and trading-core.]*
- **[EXITS] Re-check Under The Lock:** a tier decision queued on the per-mint sell lock sold the same tier twice once the first slow sell finished (BUG-140). Anything that waits for a lock must re-validate its precondition after acquiring it. *[Applies: trading-core.]*
- **[REVIEW] Fix Branches Touch Shared Lines:** fourteen one-bug branches conflicted in `bot/run.py`, `tests/unit/bot/test_run.py` and the BUGS.md status table. Insert new tests at different anchors, update only the bug's own BUGS.md section on its branch, flip status rows on the integration branch, and run the merged suite before calling a set of fixes done. *[Applies: everywhere.]*
- **[RISK] A Ratchet Only Moves Up:** the BUG-127 floor was built from net realized PnL, so a closed loss after a win lowered it and the floor never held (BUG-141). Build a ratchet from a running peak, persist the peak, and test it with the giveback realized by closed trades, not only marked on open ones. *[Applies: trading-core.]*
- **[RISK] Size Risk Triggers To The Account:** the ratchet floor armed on any gain, so +0.5% realized and a 0.04% dip halted a whole day (BUG-144). Give every risk trigger a minimum it must clear relative to the account, and replay it on a real capture before shipping. *[Applies: trading-core.]*
- **[DOCS] A Documented Variable Must Be Read:** the env manual listed `PUMPFUN_DRY_RUN` and 50 other names no code reads (BUG-142). Never document a variable, alias or default without grepping the code for it; `unit/config/test_env.py` checks the §2 matrix. Don't wire up a long-documented name silently either: warn when it is set, then decide. *[Applies: here and trading-core.]*
- **[TESTS] Proxies And Threads Bypass The DNS Guard:** a test posted a real Discord alert: `urllib` sent it to the local `HTTPS_PROXY`, and the alert worker thread ran after the per-test guard was undone (BUG-143). Keep every file a bot writes inside `tmp_path`, capture alerts in tests, and never rely on DNS blocking alone for a client that honours proxy variables. *[Applies: here.]*
- **[TESTS] Paths Wrap On The Mac:** a parity test passed on Linux and failed on macOS, where `tmp_path` (`/private/var/folders/...`) made Rich wrap the line it asserted on. Never assert a phrase in Rich output that also prints a path; normalise whitespace (`" ".join(text.split())`) first. *[Applies: everywhere.]*
- **[PAPER] No Read, No Fill:** a paper buy whose curve read failed filled at the fresh-launch curve, and paper sells went on with no RPC (BUG-152), and 29% of the rc.5 buys (all of its profit) were such fills (BUG-145); coins complete at creation were bought too (BUG-146). A paper fill must fail whenever the live one would (no read, complete curve, zero quote); never add a fallback price to any fill or exit, and count refusals (`entry_refusals`). *[Applies: here.]*
- **[RPC] An Open Breaker Sends Nothing:** the pool routed every request to its open endpoint, so the 429s never stopped and two bots on one key ran blind for an hour (BUG-151). Fail fast while open, grow the cooldown, probe one at a time, stop buying with no endpoint (BUG-149), batch per-position reads, keep record-only reads off a rate-limited RPC, and give each bot its own key. *[Applies: here.]*
- **[STREAMS] Silence Must Reconnect:** a half-open PumpPortal socket waited in `async for` for 3 h; the health check only paused trading (BUG-150). Every long-lived socket needs pings and an idle timeout that reconnects, not just an alert. *[Applies: here.]*
- **[LOGGING] A Blocked Exit Is A Warning:** four positions could not sell for an hour and `bot.log` only said "Exit triggered" every second (BUG-148). Log why an exit or buy did not happen at WARNING with its cause, back off the retry, and rate-limit repeated decision lines. *[Applies: trading-core.]*
- **[RPC] New Accounts Arrive Late:** a launch's curve was read ~90 ms after the create event and 80% of rc.6 buys were refused as "not Pump.fun"; the coins skipped did better than the ones bought (BUG-154). A missing account right after a create is "not yet", not "never": wait a bounded time before deciding, measure the wait, and check that what a refusal filters out is not the better half. *[Applies: here.]*
- **[TESTS] Paper Bots Need Curves:** 34 tests broke once paper buys needed a curve read: they had passed only on the fallback fill. A test that paper-buys installs `FakeCurves` (`tests/support/fakes.py`); a refresh test mocks `get_bonding_curve_states`, which the refresh uses, not the single read. *[Applies: retired code.]*
- **[MIGRATION] Port The Venue, Rebuild The Runtime:** a 1:1 port of pumpbot onto trading-core would have carried thousands of lines of NO-GO lanes and an event-driven runtime that does not fit the engine's cycle (2026-10-28). Port the venue layer with its tests and bug tags, rebuild a lane as a pipeline, and account for every bug whose code is left behind (`BUGS.md`, Where each fix lives). *[Applies: here.]*
- **[MIGRATION] A Smaller Suite Needs An Account:** the suite went from 2,208 to 779 tests when pumpbot was retired. A drop in test count is only acceptable when every removed regression is listed (tagged here, tagged in trading-core, or retired with its code) and the release notes say why. *[Applies: everywhere.]*
- **[REPLAY] Tick Faster Than The Cycle:** the first replay of the rc.8 rows advanced the clock by `cycle_seconds` only and saw too few readings; the poller and the engine must both get their turn. Advance the replay clock by `min(poll_tick, cycle_seconds)` and run the engine cycle when it is due. *[Applies: here.]*
- **[TESTS] Health Waits For The First Data:** trading-core's health monitor blocks entries only after market data has been seen once, so a test that expects "no RPC, no entries" must assert the module's degraded RPC condition, not a stale-data blocker that never armed (BUG-149 test). *[Applies: here.]*
- **[TOOLS] Type-Check Against The Editable Core:** with trading-core installed editable, mypy does not find its package; run it with `MYPYPATH=../trading-core` (nox installs it normally and needs nothing). *[Applies: here.]*
- **[TOOLS] The Mac Folder Cannot Delete:** in the connected Mac checkout, `rm` and `gzip` (which deletes its input) fail without delete permission, and git leaves lock files. Write new files, use `gzip -c`, deliver commits as bundles fetched into a branch, and never run state-changing git there. *[Applies: everywhere.]*
- **[TESTS] 100% On 3.14 Is Not 100% On 3.11:** the first nox run on 3.11 missed three arcs that 3.14 covers: an exception raised inside a coroutine under `asyncio.run` reached the CLI's `except` on 3.14 but not on 3.11, and 3.11's tracer misses the exit arc of a suppressing `with` and of a branch that ends an `async with` block. Test interrupts by replacing `asyncio.run`, prefer `asyncio.gather(..., return_exceptions=True)` over `contextlib.suppress` around an await, and run `nox -s tests` on every version before calling coverage done. *[Applies: here.]*

## Project Overview

`trading-pump` (package `trading_pump`) is the Pump.fun / PumpSwap module for trading-core, registered as `pumpfun`. It continues pumpfun-trading: same git history and tags (to `v0.3.0rc8`), same bug and feature numbering. It follows every coin that graduates to PumpSwap, reads the pools on chain, runs the FEAT-76 `pumpswap_momentum` lane in paper with every fee priced in, records a capture, and replays captures through the real engine. Live execution is refused until the lane passes paper.

---

## Package Structure

```text
trading-pump/
├── trading_pump/
│   ├── module.py         # PumpModule: trading-core's TradingModule for Pump.fun graduates
│   ├── market.py         # PoolReading, SwapFee, PumpSwap pool maths, RpcPoolSource
│   ├── graduates.py      # GraduateTracker (FEAT-73): who is followed, readings, capture rows
│   ├── feed.py           # MigrationFeed (PumpPortal subscribeMigration), PoolPoller
│   ├── execution.py      # PaperExecutor (pool-priced fills, every cost), LiveExecutor (refuses)
│   ├── replay.py         # capture playback through the engine (trading-pump replay)
│   ├── recorder.py       # the capture file (core RotatedFileSink)
│   ├── identifiers.py    # Solana public keys are public (core redaction)
│   ├── api/              # Public Pump.fun REST API client
│   ├── cli/              # trading-pump (record, replay, env) and trading-pump-recorder
│   ├── config/           # env.py (credentials only), settings.py (PumpSettings)
│   ├── infra/            # Multi-provider RPC connection pool, latency routing, breaker, failover
│   ├── sdk/              # Curve and PumpSwap maths, fee config, transaction builders, costs, Jito
│   ├── services/         # Record-only research recorders (market, slow lane)
│   ├── strategies/       # pumpswap_momentum (the lane), anti-rug screening, observations
│   ├── streams/          # PumpPortal WebSocket host (reconnect, pings, key handling)
│   └── tests/            # 100% coverage; see docs/dev/TESTING.md
│       ├── conftest.py   # environment isolation only
│       ├── support/      # shared factories, fakes, payloads, constants
│       ├── unit/         # 1:1 mirror of the source: unit/<pkg>/test_<module>.py
│       ├── integration/  # the module on the real engine, end to end
│       └── property/     # Hypothesis property tests (curve maths)
├── configs/              # paper / capture examples, verdict rules, slow-lane token list
└── docs/                 # user and developer docs; archive/pumpfun-trading/ is pumpbot's, frozen
```

`tests/unit/test_suite_layout.py` fails on a source module without a mirrored test, a coverage-named file, a RESOLVED bug in `docs/dev/BUGS.md` without a `@pytest.mark.regression("BUG-xx")` test (unless "Where each fix lives" lists it), or a tag that names no bug.

---

## Documentation Architecture

### 1. User & Operator Manuals (`docs/`)
* [**`docs/USER-GUIDE.md`**](docs/USER-GUIDE.md): Start here: concepts, install, run, judge, replay, from pumpbot.
* [**`docs/STRATEGY.md`**](docs/STRATEGY.md): The FEAT-76 lane, its evidence, prices and costs, and how it is judged.
* [**`docs/CONFIGURATION.md`**](docs/CONFIGURATION.md): Every `module_settings` key, and the pumpbot key map.
* [**`docs/ENVIRONMENT.md`**](docs/ENVIRONMENT.md): The six variables read, and what replaced the rest (checked by a test).
* [**`docs/CLI.md`**](docs/CLI.md): `trading-pump record / replay / env` and the trading-core commands used with them.
* [**`docs/FEATURES.md`**](docs/FEATURES.md): Shipped features, and what became of each pumpfun-trading feature.
* [**`docs/ARCHITECTURE.md`**](docs/ARCHITECTURE.md): How the module meets trading-core's contract; data flow; layout.
* [**`docs/archive/pumpfun-trading/`**](docs/archive/pumpfun-trading/INDEX.md): pumpfun-trading's documents as of v0.3.0rc8, unchanged.

### 2. Developer & Engineering Artifacts (`docs/dev/`)
* [**`docs/dev/README.md`**](docs/dev/README.md): Index and workflow.
* [**`docs/dev/TODO.md`**](docs/dev/TODO.md): Open work only: migration gate, FEAT-76, live gate, research, Not ported.
* [**`docs/dev/DONE.md`**](docs/dev/DONE.md): Finished work under its original headings.
* [**`docs/dev/BUGS.md`**](docs/dev/BUGS.md): Every bug, root cause and fix; where each fix lives after the split.
* [**`docs/dev/PROPOSED-FEATURES.md`**](docs/dev/PROPOSED-FEATURES.md): Unbuilt venue features.
* [**`docs/dev/STRATEGY-PIVOT.md`**](docs/dev/STRATEGY-PIVOT.md): The evidence: every result since v0.2.3.
* [**`docs/dev/RUNBOOK.md`**](docs/dev/RUNBOOK.md): Operating a run, incidents, recorders, drills.
* [**`docs/dev/RELEASE-GATE.md`**](docs/dev/RELEASE-GATE.md): Release checklist, live capital gate, versioning.
* [**`docs/dev/TESTING.md`**](docs/dev/TESTING.md): The gate, CI, layout, isolation, conventions.
* [**`docs/dev/COSTS.md`**](docs/dev/COSTS.md): Project costs and the measured running cost per run. Add every new payment there.
* [**`docs/dev/ARCHITECTURE-DECISIONS.md`**](docs/dev/ARCHITECTURE-DECISIONS.md): ADRs (ADR-008 test layout, ADR-009 the split).

---

## Working Rules & Architecture Principles

1. **Modular Boundaries**:
   - One Python package (`trading_pump`), no `src/` layout.
   - Streaming and decoding stay in `streams/`; on-chain maths, transactions and Jito in `sdk/`; strategy decisions and screening in `strategies/`; CLI handlers in `cli/` delegate to library functions.
   - The module renders nothing and owns no risk: it answers trading-core through `PumpModule`.

2. **Security & Key Management**:
   - The wallet key and keyed URLs come from the environment only; the settings file is hashed into provenance.
   - Every persisted URL is redacted; Solana public keys are registered as public so they are not masked.

3. **Execution & Anti-MEV**:
   - Prices come from the module's own pool reads, never a third-party quote.
   - Pump.fun `BuyV2` / `SellV2` and the PumpSwap sell are built with Token-2022 detection, creator vaults and fee / volume accumulators (`sdk/`); Jito bundles with on-chain error checks. Live sending waits for the live gate.

4. **Strategy & Risk Controls**:
   - One lane, pre-registered (FEAT-76); exits and limits are the engine's.
   - Screening (Gini, top-5 concentration, creator history, clusters) is available and off by default.

---

## Runtime and Command Surface

* `trading-core run --config F` (`"module": "pumpfun"`): run the module (`--headless`, `--live`); `SIGUSR1` toggles the operator pause.
* `trading-core check --config F`: validate settings and build the module.
* `trading-core-audit pnl / cuts / verdict`, `trading-core-events`: read a run.
* `trading-pump replay --config F --capture C... --out DIR`: replay captures through the engine.
* `trading-pump record --market | --jupiter-quotes | --backfill-bars` (also `trading-pump-recorder`): research recorders.
* `trading-pump env`: which variables are set (names only).

---

## Quality Standards & Testing

* **Formatting & Linting**: Black, Ruff and flake8 clean (`nox -s format`, `nox -s lint`).
* **Static Types**: mypy clean (`nox -s mypy`), checked as Python 3.11.
* **Coverage**: 100% statement and branch coverage on Python 3.11–3.14 (`nox -s tests`).
* **Docs With Code**: TODO (open), DONE (finished), FEATURES / PROPOSED-FEATURES, CONFIGURATION, ENVIRONMENT and CLI updated in the same change.
* **Bugs & Regressions**: every bug in `docs/dev/BUGS.md` (next free BUG-ID is in the file) with root cause and a tagged test; general lessons in the Learnings Log above.

---

## Build & Installation

```bash
pip install -e ../trading-core
pip install -e ".[dev]"

nox -s lint
nox -s mypy
nox -s tests      # Python 3.11–3.14 (installed interpreters)
nox -s package    # wheel is private and ships no tests
```
