# Capital Protection & Risk Management Architecture

In automated microcap trading, capital preservation is the primary prerequisite for long-term compound wealth generation. The `pumpfun-trading` engine implements a multi-tier risk defense architecture designed to contain adverse selection, prevent catastrophic drawdown, ensure on-chain state integrity, and neutralize toxic MEV exploitation.

---

## 1. Multi-Tier Risk Control Hierarchy

The system evaluates risk constraints across three sequential layers:

```
  +--------------------------------------------------------------+
  |              Tier 1: Order-Level Safeguards                  |
  |  - Slippage caps (e.g. 250 bps)                              |
  |  - Exact integer Lamport conversions                         |
  |  - Anti-MEV Jito private bundle routing                      |
  +------------------------------+-------------------------------+
                                 | (Passed)
                                 v
  +--------------------------------------------------------------+
  |            Tier 2: Position-Level Controls                   |
  |  - Dynamic trailing stop-loss (15% drop from peak)           |
  |  - Multi-tier take-profit scaling (2.0x, 3.5x, Moonbag)      |
  |  - Seen-mint cooldown windows (300s)                         |
  |  - Escalating slippage exit retry queues                     |
  +------------------------------+-------------------------------+
                                 | (Passed)
                                 v
  +--------------------------------------------------------------+
  |            Tier 3: Portfolio-Level Safeguards                |
  |  - Max concurrent open positions (default: 3)                |
  |  - Single-token exposure cap (% of total equity)             |
  |  - Minimum SOL reserve floor (0.1 SOL)                       |
  |  - Automated daily drawdown hard circuit breaker (FEAT-09)   |
  |  - Startup on-chain wallet position reconciliation           |
  +--------------------------------------------------------------+
```

---

## 2. Portfolio Exposure & Concentration Limits

To prevent over-exposure to idiosyncratic microcap volatility, portfolio limits are enforced prior to every order creation:

### A. Position Count Ceiling
* **Default**: Maximum of 3 simultaneous active positions.
* **Mechanism**: If the active position registry reaches the limit, new candidate discovery events are suppressed, regardless of signal conviction.

### B. Single-Token Allocation Caps
* **Formula**: $\text{Max Single Allocation} = \text{Total Equity} \times \text{Max Token Concentration Pct}$
* **Default**: No single token position may exceed $25\%$ of total wallet equity.

### C. Minimum SOL Reserve Floor
* **Buffer Floor**: $0.10\text{ SOL}$.
* **Mechanism**: Orders will not be initiated if available wallet SOL minus trade size is less than $0.10\text{ SOL}$. This reserves capital for Solana rent exemption, Compute Budget fees, and urgent liquidation transactions.

---

## 3. Daily Hard-Stop Circuit Breakers (FEAT-09)

To guard against high-volatility market crashes and cascading token exploit waves, the bot monitors cumulative daily portfolio drawdown from intraday peak equity:

$$\text{Daily Drawdown \%} = \frac{\text{Peak Daily Equity} - \text{Current Equity}}{\text{Peak Daily Equity}} \times 100$$

### Circuit Breaker Trigger Actions

If daily drawdown breaches the configured threshold (default: $15.0\%$ of peak daily equity):
1. **Immediate Ingestion Halting**: Ingestion of new token mint events and buy triggers is locked.
2. **Emergency Position Liquidation**: An automated panic liquidation command is dispatched, enqueuing market sell orders across all open positions.
3. **24-Hour Trading Lockout**: The bot transitions to a locked state for 24 hours, requiring explicit operator reset or next UTC day rollover.
4. **Emergency Telemetry Broadcast**: Critical alert payloads are dispatched via configured Webhooks (Discord, Slack, Telegram).

---

## 4. Toxic MEV Elimination & Private Mempool Routing (FEAT-02)

Public Solana mempools are actively monitored by searcher algorithms that execute predatory sandwich attacks on microcap trades. `pumpfun-trading` eliminates this vulnerability by default:

```
  Standard Retail Route (Vulnerable):
  [Bot] ----> [Public RPC Node] ----> [Mempool / Validator] <--- [MEV Searcher Sandwiches Order]

  PumpFun Private Route (Protected):
  [Bot] ----> [Jito Block Engine] ----> [Private Validator Bundle] ----> [Atomic Block Inclusion]
```

### Jito Bundle Architecture

1. **Atomic Packaging**: Buy/Sell instructions are packaged atomically with Compute Budget unit limits, unit prices, and a dedicated Jito validator tip transfer instruction.
2. **Dynamic Tip Floor Scaling**: Validator tips query Jito's live tip stream percentiles (`p25` to `p95`), dynamically adjusting tips based on trade size and conviction:

$$\text{Tip (Lamports)} = \max\left(\text{Base Tip},\; \text{p50 Tip Floor} \times \text{Conviction Multiplier}\right)$$

3. **Fast Fallback Routing**: If Jito Block Engine confirmation exceeds the configured timeout ($15.0\text{s}$), the execution client seamlessly falls back to high-priority direct Solana RPC execution to ensure time-critical exits are never stranded.

---

## 5. Startup On-Chain Reconciliation & Exit Retry Queues (BUG-07 / FEAT-14)

### A. Startup On-Chain Position Reconciliation

Upon initialization or crash recovery, the bot queries the on-chain SPL Token accounts associated with the wallet:
1. **Holding Verification**: Verifies on-chain token balances against local state storage.
2. **Ghost Position Purging**: Removes stale or phantom entries from local storage if on-chain balances are zero.
3. **Valuation Resynchronization**: Fetches live bonding curve states for all surviving holdings, populating baseline entry costs and initializing peak price tracking for trailing stops.

### B. Exit Retry Queue with Escalating Slippage (BUG-08)

When network congestion or sudden volatility causes a sell transaction to fail:
1. **Queue Enlistment**: The position is enqueued into `_exit_retry_queue`.
2. **Escalating Slippage**: Retries execute with exponential slippage widening ($+100\text{ bps}$ per retry up to max $1000\text{ bps}$).
3. **Jito Tip Escalation**: Priority fees and Jito tips scale by $1.5x$ on each attempt.
4. **Emergency Liquidation**: Ensures positions are never left unmanaged during rapid developer sell-offs.

---

## 6. Risk Parameters Reference

| Parameter | Default | Units | Description |
| :--- | :---: | :---: | :--- |
| `max_active_positions` | `3` | Count | Maximum simultaneous open positions. |
| `max_token_concentration_pct` | `25.0` | Percent | Maximum single-token allocation of total equity. |
| `min_wallet_reserve_sol` | `0.10` | SOL | Mandatory wallet buffer for gas fees. |
| `max_daily_drawdown_pct` | `15.0` | Percent | Daily circuit breaker liquidation trigger. |
| `seen_mint_cooldown_seconds` | `300` | Seconds | Cooldown before re-evaluating a previously closed token. |
| `max_slippage_bps` | `250` | Basis Points | Maximum allowable slippage (`250` = 2.5%). |
| `exit_retry_max_attempts` | `5` | Count | Maximum automated retry count for failed sells. |
| `screening_cache_ttl_seconds` | `60` | Seconds | In-memory anti-rug screening cache validity window. |
