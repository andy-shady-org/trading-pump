# Costs

What trading-pump (pumpfun-trading until 2026-10-28) has cost so far: its own subscriptions and payments, and what each run costs to keep going. Record every new payment for this module here as it happens, in the currency it was paid in.

Development costs (the Claude subscription and invoices, the JetBrains licence and AI credits) pay for every repository and are recorded in trading-core's `docs/dev/COSTS.md`; they moved there, unedited, on 2026-10-31. That page also has the project's totals, with this module's line. Amounts are not converted: the project pays in USD, EUR, GBP and SOL, and an exchange rate picked later would make the totals look more exact than they are.

Last updated: 2026-10-31.

---

## 1. Subscriptions

| Service | Plan | Price | What it covers |
| :--- | :--- | :--- | :--- |
| Helius (Solana RPC) | Developer | $49.00 / month | 10 M credits a month, 50 RPC requests a second, 5 `sendTransaction` a second; extra credits $5 per million ([pricing](https://www.helius.dev/pricing), checked 2026-10-25). The Free plan (1 M credits, 10 requests a second) ran out during the rc.5 paper run (§4.1). |

The JetBrains and Claude subscriptions moved to trading-core's `docs/dev/COSTS.md` §1 (development) on 2026-10-31.

---

## 2. One-off payments

### 2.1 JetBrains AI credits

Moved to trading-core's `docs/dev/COSTS.md` §2.1 (development) on 2026-10-31.

### 2.2 Crypto payments

| Date | Payee | Amount | Note |
| :--- | :--- | ---: | :--- |
| – | [PumpPortal](https://pumpportal.fun/) API key, wallet `C2CU8UW9mvbTY4D3uBvbPfTnpRfP2SFFc4idVWkCoBcA` | 0.03 SOL | Funds the key's trade-data metering (§3.2). Operator's rate at payment: 0.01 SOL = $1.00. |
| 2026-10-26 15:49 UTC | PumpPortal key wallet (top-up) | 0.02 SOL | After the rc.7 runs lost their trade feed (§3.2). |
| 2026-10-26 16:05 UTC | PumpPortal key wallet (top-up) | 0.01 SOL | |
| 2026-10-26 16:07 UTC | PumpPortal key wallet (top-up) | 0.05 SOL | Balance afterwards 0.099985 SOL. |
| 2026-10-26 16:49 UTC | PumpPortal key wallet (top-up) | 0.10 SOL | For the 72 h rc.8 runs (both runs on this key). Balance afterwards 0.199985 SOL. |

### 2.3 On-chain trading

None. Every run so far has been paper (pumpbot's `dry_run` / `paper_trade`, then trading-core's `"mode": "paper"`): no transaction fees, priority fees, Jito tips or token-account rent have been paid. Live costs per trade are modelled in [`docs/STRATEGY.md` §3](../STRATEGY.md#3-prices-and-costs) and booked in the audit trail once a funded wallet runs, from Stage 2 of the capital gate ([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate)).

### 2.4 Claude invoices

Moved to trading-core's `docs/dev/COSTS.md` §2.2 (development) on 2026-10-31.

--- | ---: | :--- |
| 2026-10-22 | €22.59 | Monthly subscription (§1); not counted again in §5 |
| 2026-10-29 | $56.48 | |
| 2026-10-29 | $25.10 | |
| 2026-10-29 | $25.10 | |
| 2026-10-30 | $25.10 | |
| 2026-10-30 | €96.21 | |
| **One-off total** | **$131.78 and €96.21** | |

---

## 3. Running costs per run

What decides the bill while a run is going. pumpbot's runs (rc.5 to rc.8, the "capture" and "pilot" runs below) were measured from `bot_status.json` → `rpc_pool_telemetry.requests_by_method` (BUG-151) and the replay capture. On trading-core the run's `status.json` does not carry the RPC pool's per-method counts (the dashboard's RPC row shows healthy endpoints only), so measure a run on the provider's usage page, and update the estimates below.

### 3.1 Helius RPC credits

A standard RPC call costs 1 credit (`getAccountInfo`, `getMultipleAccounts`, `getTransaction`, …; `getProgramAccounts` is 10); a transaction sent through `mainnet.helius-rpc.com` costs 1; WebSocket subscriptions cost 2 credits per 0.1 MB streamed ([credits](https://docs.helius.xyz/docs/billing/credits.md), checked 2026-10-25). Requests refused with HTTP 429 are assumed not to be billed; Helius does not say.

| Measured run | Successful RPC requests | Per run per day | Per run per 30 days |
| :--- | ---: | ---: | ---: |
| rc.5 launch-mode A/B, 2026-10-24 18:16 → 2026-10-25 07:01 UTC (12.75 h with a working RPC), capture run | 53,421 | ≈ 100,000 | ≈ 3.0 M |
| same A/B, pilot run | 58,606 | ≈ 110,000 | ≈ 3.3 M |

(`rpc_pool_telemetry`: total requests less rate-limited ones; every request after 07:01 UTC failed.) That run read each held curve with its own call every second; since `fix/runtime-rpc-outage` all held curves are one call per second, so expect less. Two runs on the measured load use about 6.3 M credits a month: inside the Developer plan's 10 M, six times the Free plan's 1 M. Each run should have its own key ([`RUNBOOK.md` §5.8](../archive/pumpfun-trading/dev/RUNBOOK.md#58-rpc-and-stream-outages-bug-145-to-bug-151)); check on the Helius dashboard whether a second key draws on the same credits.

The cross-chain market recorder (FEAT-74, in trading-scout since 2026-10-30) uses no Helius credits: GeckoTerminal and DexScreener are free and keyless (about 7 and at most 240 requests a minute). Its cost is disk: about 1 GB of rows a day before compression, about a tenth of that gzipped.

Measured in rc.8 (37.2 h, Developer plan, no rate limits): the capture run (launch buying plus graduation tracking and followed launches) made 305,836 requests (258,548 `getMultipleAccounts`), about 5.9 M per 30 days; the pilot (launch buying only) 205,986, about 4.0 M. Together about 9.9 M per 30 days: at the plan's 10 M, so a third run or a faster graduation poll needs the next plan or a second Helius key on its own plan.

Graduation tracking (FEAT-73, record-only) adds to one run: at rc.6's rate (about 930 migrations a day, about 155 pools followed at once for 4 h, 33 pools per call) about one `getMultipleAccounts` call a second at a 5 s interval, ≈ 86,000 credits a day or ≈ 2.6 M per 30 days; at the 10 s interval in `configs/capture.json` about half that, ≈ 1.3 M. Its fast phase (every 2 s for the first 5 minutes after each migration; about 3 coins in it at any time, so about one call every 2 s) adds ≈ 1.25 M, and following sampled launches past 15 minutes (about 8% of the sample, 15 s interval, batched with the other curve reads) adds little. With the two runs above that is about 8.8 M of the Developer plan's 10 M: turn it on in one run only, watch the Helius dashboard in the first day, and raise `graduation_observation_fast_poll_interval_seconds` to 3 (≈ 0.85 M) or the slow interval if it runs high.

### 3.2 PumpPortal trade data

PumpPortal meters token-trade messages against the API key's wallet: 0.01 SOL per 10,000 messages; the create and migration feeds are free ([`RUNBOOK.md` §5.7](../archive/pumpfun-trading/dev/RUNBOOK.md#57-trade-feed-circuit-breaker-pumpportal-api-key-funds-bug-116)).

| Measured run | Trade messages received | Cost | Per run per 30 days |
| :--- | ---: | ---: | ---: |
| rc.5 launch-mode A/B (13.85 h), capture run | 14,786 | 0.0148 SOL | ≈ 0.77 SOL |
| same A/B, pilot run | 16,995 | 0.0170 SOL | ≈ 0.88 SOL |
| rc.7 launch-mode A/B (5.75 h until the feed stopped, 2026-10-26), capture run | 7,592 | 0.0076 SOL | ≈ 0.95 SOL |
| same A/B, pilot run | 6,069 | 0.0061 SOL | ≈ 0.76 SOL |
| rc.8 launch-mode A/B (37.2 h, 2026-10-26 → 28; one shared key), both runs | 90,652 (52,495 + 38,157) | 0.050 SOL charged (wallet 0.199985 → 0.149910) | ≈ 0.97 SOL for both |

(Trade rows with a `user` in the replay capture.) Launch mode subscribes to every held coin, so this grows with `max_active_positions` and how busy the held coins are.

**The 0.02 SOL floor.** PumpPortal serves trade data only while the key's wallet holds at least 0.02 SOL, so only the balance above 0.02 SOL is usable. On 2026-10-26 a 0.010015 SOL charge at 15:10:59 UTC left 0.019985 SOL; PumpPortal closed the connection at 15:35:05 and refused every trade subscription after it, and both rc.7 runs (one shared key) stopped buying. A 0.02 SOL top-up at 15:49:16 was not picked up by pumpbot's retry on the same connection at 15:50:21, and the runs were stopped at 15:51 ([`RUNBOOK.md` §5.7](../archive/pumpfun-trading/dev/RUNBOOK.md#57-trade-feed-circuit-breaker-pumpportal-api-key-funds-bug-116)). Plan funding as 0.02 SOL plus the run's use: at rc.7's rate two runs use about 0.0024 SOL an hour, so a 72 h run needs about 0.17 SOL above the floor. After the 16:49 UTC top-up the wallet holds 0.199985 SOL, about 0.18 SOL above the floor: about 75 h of both runs at rc.7's rate, so check the balance on day 3 of the rc.8 runs (FEAT-75's filters buy less, which helps). The wallet's on-chain history shows the charges (one 0.01 SOL debit per 10,000 messages). At the operator's rate of 0.01 SOL = $1.00, two runs like these cost about $165 a month in trade data, more than the Helius plan.

### 3.3 On the new stack (trading-pump 0.4.0, from 2026-10-28)

What a run of the module costs, from the measurements above and FEAT-80's;
measure it on each run (the provider's usage page) and replace these
estimates:

* **PumpPortal: nothing.** The module subscribes to migrations only, which PumpPortal serves without a key and without metering. No trade-data charges, no 0.02 SOL floor.
* **RPC requests: graduation tracking.** No launch buying and no held curves to refresh: every followed graduate's pool is read every 2 s for its first 5 minutes, then every 10 s for 4 h, 33 pools per `getMultipleAccounts` call. At rc.6 / rc.8 rates (about 900 migrations a day) that is the FEAT-73 estimate above: about 1.3 M credits per 30 days at 10 s plus about 1.25 M for the fast phase, ≈ 2.6 M per run, plus a fee-config read every 5 minutes. Both lanes share these reads: a second lane costs no extra RPC. Two runs fit the Developer plan's 10 M with room to spare; four do not.
* **RPC WebSocket: the new-pool feed (FEAT-80, only with `new_pools` on, as in pools-1).** A `programSubscribe` on PumpSwap's pool accounts carries every swap's pool write: measured at 47 messages and about 36 kB a second for 832 pools (15 minutes on the public RPC, 2026-10-31), about **3 GB a day**. At the Helius rate in §3.1 (2 credits per 0.1 MB streamed) that would be about 62,000 credits a day, about 1.9 M per 30 days; an estimate from the published rate, not a bill. Each new pool found also costs one `getSignaturesForAddress` lookup (at most `new_pools.max_lookups` at once), and the pools followed are read on the graduates' schedule.
* **RPC requests: token names (FEAT-91).** One `getMultipleAccounts` call for the graduates read since the last one (up to 100 mints, at most three tries each): at about 900 graduates a day, a few hundred to 900 credits a day, under 0.03 M per 30 days.
* **Disk:** about 1–2 M capture rows a day (rc.8: 861,000 rows in 16.6 h).

---

## 4. Notes

### 4.1 Free-tier RPC exhaustion (2026-10-25)

Both runs of the rc.5 A/B shared one Free-plan Helius key, so 10 requests a second for the two together; about 20% of requests were already rate limited in the run before. From 07:01 UTC every request failed, and the runs kept trading on invented prices, which BUG-145 to BUG-151 fix ([`BUGS.md` §26](BUGS.md#26-rc5-paper-run-findings-2026-10-25)). The Developer plan is listed in §1.

### 4.2 Helius WebSocket URL

Helius gives each key an HTTPS endpoint and a WebSocket one (`wss://mainnet.helius-rpc.com/?api-key=<redacted>`) on the same host. The WebSocket endpoint only takes subscriptions (`accountSubscribe`, `programSubscribe`, `logsSubscribe`, …), billed by data streamed. Since 0.4.0-rc.5 the module uses it for one thing: the FEAT-80 new-pool feed (`programSubscribe`, `PUMPFUN_RPC_WS_URL`, by default the RPC URL with `wss://`), about 3 GB a day (§3.3). Every other call is a request and answer over HTTPS, so moving the RPC URL to the WebSocket one does not lower the bill. Subscribing to followed pools instead of polling them could, for pools that rarely trade, but a PumpSwap pool account is written on every swap, so for busy graduates it would cost more, not less.

---

## 5. Totals to date

This module's payments only; the project's totals, development included, are
in trading-core's `docs/dev/COSTS.md` §4.

| Currency | Recurring | One-off |
| :--- | :--- | :--- |
| USD | $49.00 / month (Helius) | – |
| SOL | ≈ 0.8 SOL / month per pumpbot run (PumpPortal trade data, measured; nothing on the new stack, §3.3) | 0.21 SOL (PumpPortal key funding: 0.03 SOL, then 0.18 SOL on 2026-10-26) |
