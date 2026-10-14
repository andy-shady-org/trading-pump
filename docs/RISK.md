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

## 3. Daily Hard-Stop Circuit Breakers & Adaptive Realized-Ratchet Engine (FEAT-09 & FEAT-29)

To guard against high-volatility market crashes while avoiding false-positive lockouts on winning trading sessions (such as volatile multi-tier take-profit runners), the bot implements dual-zone equity tracking and realized profit ratcheting.

### A. Realized Profit Ratchet & Dynamic Effective Baseline
When positions close with net realized profit, a configurable fraction (`profit_ratchet_ratio`, default `0.50`) permanently ratchets the **Effective Equity Baseline Floor**:
$$\text{Baseline}_{\text{effective}} = \text{Starting Capital} + \alpha \times \max(0, \text{Cumulative Realized PnL})$$

### B. Dual-Zone Risk Evaluation
1. **Principal Protection Zone (`Current Equity < Starting Capital`)**:
   - Strict capital preservation applies.
   - If total portfolio equity drops below $\text{Starting Capital} \times (1 - \text{max\_daily\_drawdown\_pct})$ (e.g. 15%–20% loss from principal), the bot engages **`EMERGENCY_LIQUIDATE`**, liquidating all open positions and locking out trading to protect capital.
2. **Profit Run Zone (`Current Equity >= Starting Capital`)**:
   - The bot operates with "house money".
   - A relaxed trailing buffer (`profit_drawdown_tolerance_pct`, default 35%) is evaluated against intraday peak equity relative to the effective baseline floor.
   - If the profit retracement tolerance is breached, the bot engages **`HALT_NEW_BUYS`**, pausing new token entries while allowing open positions to continue exiting gracefully via trailing stop-losses (`FEAT-03`) and take-profit targets.

### C. Circuit Breaker Trigger Actions

| Action | Regime Trigger | Behavior |
| :--- | :--- | :--- |
| **`HALT_NEW_BUYS`** | Profit Run Zone retracement exceeds `profit_drawdown_tolerance_pct` | Soft-halts new token entries; existing positions remain active and are managed by trailing stops. |
| **`EMERGENCY_LIQUIDATE`** | Principal loss exceeds `max_daily_drawdown_pct` | Dispatches immediate market sell orders across all open positions, engages 24-hour lockout, and emits critical webhook alerts. |

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
| `max_daily_drawdown_pct` | `15.0` | Percent | Daily circuit breaker principal loss trigger (Principal Zone). |
| `drawdown_reference_mode` | `"adaptive_ratchet"` | String | Reference mode (`"adaptive_ratchet"`, `"baseline"`, `"trailing_hwm"`). |
| `profit_ratchet_ratio` | `0.50` | Float | Fraction of realized profits ratcheted into guaranteed baseline floor. |
| `profit_drawdown_tolerance_pct` | `35.0` | Percent | Retracement tolerance from peak equity in Profit Run Zone. |
| `seen_mint_cooldown_seconds` | `300` | Seconds | Cooldown before re-evaluating a previously closed token. |
| `max_slippage_bps` | `250` | Basis Points | Maximum allowable slippage (`250` = 2.5%). |
| `exit_retry_max_attempts` | `5` | Count | Maximum automated retry count for failed sells. |
| `screening_cache_ttl_seconds` | `60` | Seconds | In-memory anti-rug screening cache validity window. |
| `max_cluster_concentration_pct` | `25.0` | Percent | Maximum supply fraction held by multi-wallet insider clusters (FEAT-26). |
| `max_single_cluster_pct` | `20.0` | Percent | Maximum supply fraction held by any single funding cluster (FEAT-26). |
| `max_sybil_wash_ratio` | `20.0` | Percent | Maximum volume churn ratio before triggering sybil wash reject (FEAT-26). |

---

## 7. On-Chain Funding Cluster Graph & Sybil Wash Defense (FEAT-26)

Insider syndicates frequently disperse pre-bought tokens across multiple seemingly independent wallets to bypass basic top-holder checks. `pumpfun-trading` neutralizes this risk through graph-based funding origin analysis:

1. **Common Ancestor Resolution**: Upstream funding links are traced through splitters and intermediary wallets to identify common funding roots.
2. **Cluster Concentration Cap**: Tokens where linked multi-wallet clusters control $\ge 25.0\%$ of supply or where a single dominant cluster holds $\ge 20.0\%$ are immediately rejected.
3. **Sybil Wash Churn Elimination**: Circular buy/sell patterns and alternating ping-pong swaps are detected in streaming trade feeds, preventing capital deployment into manipulated volume surges.
