# Financial Strategy & Wealth Generation Blueprint

This document details the quantitative models, mathematical formulations, financial execution playbooks, and concrete configuration recipes implemented across `pumpfun-trading`. The platform is engineered to maximize expected value ($E[V]$) per trade, optimize capital compounding velocity, and protect aggregate portfolio equity against tail-risk drawdowns and toxic market microstructure.

---

## Table of Contents

1. [Financial Objective & Mathematical Expectancy](#1-financial-objective--mathematical-expectancy)
2. [Bankroll Management & Fractional Kelly Sizing](#2-bankroll-management--fractional-kelly-sizing)
3. [Pump.fun Constant-Product Bonding Curve Mechanics](#3-pumpfun-constant-product-bonding-curve-mechanics)
4. [Multi-Tier Take-Profit Scaling & Ladder Engine (FEAT-03)](#4-multi-tier-take-profit-scaling--ladder-engine-feat-03)
5. [Dynamic Trailing Stop-Loss & Stagnation Exit Engine (FEAT-03)](#5-dynamic-trailing-stop-loss--stagnation-exit-engine-feat-03)
6. [Pre-Trade Anti-Rug & Heuristic Screening Engine (FEAT-04)](#6-pre-trade-anti-rug--heuristic-screening-engine-feat-04)
7. [On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)](#7-on-chain-funding-cluster-graph--sybil-wash-trading-detector-feat-26)
8. [Real-Time Order Flow & Trade Velocity Momentum Analytics (FEAT-07)](#8-real-time-order-flow--trade-velocity-momentum-analytics-feat-07)
9. [Raydium Migration Sniping & Post-Graduation Momentum Engine (FEAT-05)](#9-raydium-migration-sniping--post-graduation-momentum-engine-feat-05)
10. [Smart Money Tracking & Copy-Trading Engine (FEAT-06)](#10-smart-money-tracking--copy-trading-engine-feat-06)
11. [Multi-RPC Dynamic Load Balancing & Failover Pool (FEAT-08)](#11-multi-rpc-dynamic-load-balancing--failover-pool-feat-08)
12. [Dynamic Volatility-Aware Slippage & Priority Fee Engine (FEAT-23)](#12-dynamic-volatility-aware-slippage--priority-fee-engine-feat-23)
13. [Opportunistic Capital Rotation & High-Conviction Displacement (FEAT-24)](#13-opportunistic-capital-rotation--high-conviction-displacement-feat-24)
14. [Predictive Graduation Curve Acceleration Harvester (FEAT-25)](#14-predictive-graduation-curve-acceleration-harvester-feat-25)
15. [Adaptive Realized-Ratchet Drawdown & Dual-Tier Risk Engine (FEAT-29)](#15-adaptive-realized-ratchet-drawdown--dual-tier-risk-engine-feat-29)
16. [Automated Hyperparameter Backtest Optimizer (FEAT-27)](#16-automated-hyperparameter-backtest-optimizer-feat-27)
17. [Atomic Jito Back-Running & Cross-Venue Arbitrage Engine (FEAT-28)](#17-atomic-jito-back-running--cross-venue-arbitrage-engine-feat-28)
18. [Structured Diagnostic Telemetry & Event Logging (FEAT-30)](#18-structured-diagnostic-telemetry--event-logging-feat-30)
19. [Automated Log Retention & Multi-Sink Compression (FEAT-22)](#19-automated-log-retention--multi-sink-compression-feat-22)
20. [Market Regime Playbooks & Strategy Presets](#20-market-regime-playbooks--strategy-presets)
21. [Unified Production Master Configuration Profile](#21-unified-production-master-configuration-profile)

---

## 1. Financial Objective & Mathematical Expectancy

In quantitative microcap trading, long-term capital compounding is governed by the mathematical expectancy equation:

$$E[V] = (P_{\text{win}} \times \overline{W}) - (P_{\text{loss}} \times \overline{L}) - C_{\text{friction}}$$

Where:
* $P_{\text{win}}$: Probability of achieving a winning trade.
* $\overline{W}$: Average gain on winning trades (amplified via multi-tier take-profit scaling and runner moonbags).
* $P_{\text{loss}}$: Probability of a losing trade.
* $\overline{L}$: Average loss on losing trades (strictly bounded via dynamic trailing stop-losses, capital rotation, and anti-rug screening).
* $C_{\text{friction}}$: Cumulative execution friction (network gas, priority fees, validator Jito tips, and bonding curve slippage).

**Core Strategic Mandate**: Eliminate adverse selection ($P_{\text{loss}}$ reduction via anti-rug and cluster filtering), minimize execution drag ($C_{\text{friction}}$ reduction via private Jito bundles and dynamic slippage), and engineer asymmetric upside ($\overline{W} / \overline{L} \ge 3.0$ via tiered profit scaling and trailing runner exits).

---

## 2. Bankroll Management & Fractional Kelly Sizing

Sustained wealth generation requires rigorous position sizing to prevent gambler's ruin during adverse market regimes while maximizing the logarithmic growth rate of capital.

### Fractional Kelly Criterion Model

The optimal theoretical position size $f^*$ is determined by the Kelly Criterion:

$$f^* = \frac{p \cdot b - q}{b}$$

Where:
* $p = P_{\text{win}}$ (empirical win probability, typically $0.35$ to $0.45$ in microcap sniping).
* $q = 1 - p = P_{\text{loss}}$.
* $b = \frac{\overline{W}}{\overline{L}}$ (payoff ratio, targeted at $\ge 3.5$).

Because full Kelly allocation induces severe portfolio volatility, `pumpfun-trading` enforces a **Quarter-Kelly ($\frac{1}{4} f^*$) to Tenth-Kelly ($\frac{1}{10} f^*$) allocation ceiling**:

$$\text{Trade Allocation (SOL)} = \min\left(\text{Base Buy SOL},\; \text{Wallet Equity} \times f_{\text{fractional}}\right)$$

### Capital Allocation Guidelines

| Portfolio Bankroll (SOL) | Max Position Size (% Equity) | Recommended Max Open Positions | Single-Token Max Allocation |
| :---: | :---: | :---: | :---: |
| $< 5.0\text{ SOL}$ | $2.0\% - 3.0\%$ ($0.10 - 0.15\text{ SOL}$) | $2 - 4$ | $0.15\text{ SOL}$ |
| $5.0 - 25.0\text{ SOL}$ | $1.5\% - 2.5\%$ ($0.125 - 0.50\text{ SOL}$) | $3 - 5$ | $0.50\text{ SOL}$ |
| $> 25.0\text{ SOL}$ | $1.0\% - 2.0\%$ ($0.25 - 1.00\text{ SOL}$) | $4 - 8$ | $1.00\text{ SOL}$ |

### Configuration Example & Parameter Matrix

```json
{
  "buy_amount_sol": 0.005,
  "max_active_positions": 4,
  "max_total_exposure_sol": 0.03,
  "max_position_size_sol": 0.01,
  "max_token_concentration_pct": 0.35,
  "max_loss_per_trade_sol": 0.002,
  "reserve_balance_sol": 0.05,
  "min_balance_sol": 0.02
}
```

* **`buy_amount_sol`**: Base SOL allocated to standard token purchases.
* **`max_active_positions`**: Hard ceiling on concurrent open token holdings.
* **`max_total_exposure_sol`**: Aggregate portfolio cap across all open positions.
* **`reserve_balance_sol`**: Minimum unallocated wallet balance preserved for gas and emergency fees.
* **Environment Variables**: `PUMPFUN_BASE_BUY_SOL`, `PUMPFUN_MAX_POSITIONS`, `PUMPFUN_MAX_TOTAL_EXPOSURE_SOL`.

---

## 3. Pump.fun Constant-Product Bonding Curve Mechanics

Pump.fun tokens utilize a deterministic constant-product Automated Market Maker (AMM) bonding curve invariant:

$$k = x \cdot y$$

Where:
* $x$: Virtual SOL reserve (initialized at $x_0 = 30.0\text{ SOL}$).
* $y$: Virtual token reserve (initialized at $y_0 = 1,073,000,000\text{ tokens}$).
* $k$: Invariant constant ($k = 30 \times 1,073,000,000 = 32,190,000,000$).

```
       Token Price (SOL)
             ^
             |                             / (Graduation @ ~85 SOL / $69k MC)
             |                           /
             |                         /
             |                      /
             |                  _ -
             |             _ -
             |        _ -
             +-----------------------------------> Real SOL Deposited
           0 SOL                                 ~85 SOL
```

### Exact Price & Execution Impact Equations

When an order deposits $\Delta x$ SOL into the bonding curve:
1. Virtual SOL reserve updates: $x' = x + \Delta x$
2. Virtual token reserve updates: $y' = \frac{k}{x + \Delta x}$
3. Received tokens $\Delta y$:

$$\Delta y = y - y' = y - \frac{k}{x + \Delta x} = \frac{y \cdot \Delta x}{x + \Delta x}$$

4. Effective execution price $P_{\text{exec}}$ and spot price $P_{\text{spot}}$:

$$P_{\text{exec}} = \frac{\Delta x}{\Delta y} = \frac{x + \Delta x}{y}, \qquad P_{\text{spot}} = \frac{x}{y}$$

5. **Slippage Impact ($\Delta P$)**:

$$\text{Slippage} = \frac{P_{\text{exec}} - P_{\text{spot}}}{P_{\text{spot}}} = \frac{\Delta x}{x}$$

### Configuration Example & Parameter Matrix

```json
{
  "min_market_cap_sol": 25.0,
  "max_market_cap_sol": 80.0,
  "min_order_flow_buyers": 3,
  "max_buy_attempts_per_mint": 3
}
```

* **`min_market_cap_sol`**: Minimum bonding curve capitalization in SOL before evaluating entries (filters out instant 0-second dev self-snipes).
* **`max_market_cap_sol`**: Maximum bonding curve capitalization in SOL for standard curve entries.
* **`min_order_flow_buyers`**: Requires at least $N$ distinct wallet buyers before confirming entry signal.
* **Environment Variables**: `PUMPFUN_MIN_MARKET_CAP_SOL`, `PUMPFUN_MAX_MARKET_CAP_SOL`.

---

## 4. Multi-Tier Take-Profit Scaling & Ladder Engine (FEAT-03)

Rigid "all-or-nothing" take-profit targets result in high profit giveback during rapid liquidity contractions. The `pumpfun-trading` engine implements a **Multi-Tier Scale-Out Schedule**:

```
 Price Multiplier
       ^
 3.5x -+-----------------------------[ Tier 2: Sell 25% (Net Profit Boost) ]
       |                            /
 2.5x -+---------------------------/--[ Moonbag Floor Price ]
       |                          /
 2.0x -+---[ Tier 1: Sell 50% (Recover 100% Principal) ]
       |  /
 1.0x -+-/--- (Entry Price)
       +--------------------------------------------------------> Time
```

### Execution Tier Breakdown

1. **Tier 1 (e.g. 1.45x / +45% to 2.0x / +100% Gain)**:
   * **Action**: Liquidate **35% to 50% of position token quantity**.
   * **Financial Outcome**: Recovers initial invested capital or locks in principal, eliminating downside risk.
2. **Tier 2 (e.g. 2.5x to 3.5x Gain)**:
   * **Action**: Liquidate **25% to 35% of initial position quantity**.
   * **Financial Outcome**: Generates substantial realized net cash flow.
3. **Tier 3 ("Moonbag" Runner Allocation — 25% to 35% of initial quantity)**:
   * **Action**: Let remaining tokens ride parabolic runs toward bonding curve graduation ($69k market cap completion).
   * **Protection**: Protected by a hard floor stop or an active dynamic trailing stop-loss.

### Configuration Example & Parameter Matrix

```json
{
  "enable_tiered_take_profit": true,
  "tier_1_take_profit": 1.45,
  "tier_1_sell_fraction": 0.35,
  "tier_2_take_profit": 2.50,
  "tier_2_sell_fraction": 0.35,
  "moonbag_trailing_floor": 2.00
}
```

* **`enable_tiered_take_profit`**: Activates multi-tranche take-profit scaling.
* **`tier_1_take_profit`**: Price multiplier milestone for first profit harvest (e.g. `1.45` = +45%).
* **`tier_1_sell_fraction`**: Fraction of initial position sold at Tier 1 (e.g. `0.35` = 35%).
* **`tier_2_take_profit`**: Price multiplier milestone for second profit harvest (e.g. `2.50` = +150%).
* **`tier_2_sell_fraction`**: Fraction of initial position sold at Tier 2 (e.g. `0.35` = 35%).
* **`moonbag_trailing_floor`**: Minimum price multiplier floor for retaining moonbags.
* **Environment Variables**: `PUMPFUN_TIERED_TP_ENABLED`, `PUMPFUN_TIER1_TP_MULT`, `PUMPFUN_TIER1_TP_FRACTION`, `PUMPFUN_TIER2_TP_MULT`, `PUMPFUN_TIER2_TP_FRACTION`.

---

## 5. Dynamic Trailing Stop-Loss & Stagnation Exit Engine (FEAT-03)

To capture asymmetric trend continuation while preventing profit round-tripping, positions are monitored by real-time trailing stop algorithms and stagnation timeouts:

```
  Price
    ^
    |          /\ (Peak Price $P_{peak}$)
    |         /  \
    |        /    \____ (Trailing Exit Trigger: $P \le P_{peak} \times (1 - \text{Drop\%})$)
    |       /
    |      /  <-- Activation Threshold ($P \ge \text{Cost} \times 1.50$)
    |     /
    |    /
    +---+-----------------------------------------------------> Time
      Entry
```

### Mathematical Trigger Rules

1. **Continuous Peak Tracking**: For every on-chain swap and bonding curve update, update position peak $M_{\text{peak}} \leftarrow \max(M_{\text{peak}}, M_t)$.
2. **Activation Gate**: Trailing evaluation activates once the position reaches the activation threshold:
   $$\text{Active}_{\text{trailing}} = \text{True} \quad \text{when } M_{\text{peak}} \ge M_{\text{entry}} \times (1 + \text{Activation Offset})$$
3. **Trailing Exit Condition**: Once active, if market cap retraces by more than `trailing_stop_drop_pct`:
   $$\text{Exit Triggered} \iff M_t \le M_{\text{peak}} \times (1.0 - \text{Trailing Drop Pct})$$
4. **Stagnation Timeout**: If position price remains within $\pm 0.5\%$ delta for longer than `stagnant_timeout_seconds`, exit to recycle capital.

### Configuration Example & Parameter Matrix

```json
{
  "enable_trailing_stop": true,
  "trailing_stop_activation_pct": 0.35,
  "trailing_stop_drop_pct": 0.12,
  "stop_loss": 0.85,
  "enable_stagnant_exit": true,
  "stagnant_timeout_seconds": 45.0,
  "stagnant_price_delta_threshold_pct": 0.005,
  "enable_max_hold_timeout": true,
  "max_hold_time_seconds": 600.0
}
```

* **`enable_trailing_stop`**: Enables real-time trailing stop evaluation.
* **`trailing_stop_activation_pct`**: Profit threshold (+35%) required before trailing stop engages.
* **`trailing_stop_drop_pct`**: Maximum allowed retracement (12%) from peak price before triggering market exit.
* **`stop_loss`**: Hard stop-loss multiplier from initial entry (0.85 = -15% stop loss).
* **`stagnant_timeout_seconds`**: Maximum duration (45.0s) a flat-moving token is held before recycling.
* **Environment Variables**: `PUMPFUN_TRAILING_STOP_ENABLED`, `PUMPFUN_TRAILING_ACTIVATION_PCT`, `PUMPFUN_TRAILING_DROP_PCT`, `PUMPFUN_STOP_LOSS`, `PUMPFUN_STAGNANT_TIMEOUT`.

---

## 6. Pre-Trade Anti-Rug & Heuristic Screening Engine (FEAT-04)

Microcap liquidity pools are susceptible to malicious exploits. Every candidate mint is evaluated against quantitative heuristic filters prior to transaction signing:

```
   Candidate Token Event
            |
            v
   [ 1. Dev Wallet Profiling ] -----> >5 launches / 24h? -----> [ REJECT ]
            | (Pass)
            v
   [ 2. Creator Initial Supply ] ---> Creator bought >8%? ----> [ REJECT ]
            | (Pass)
            v
   [ 3. Holder Distribution ] ------> Top 5 Wallets >15%? ----> [ REJECT ]
            |                         Gini Coeff > 0.85?
            v (Pass)
   [ 4. Metadata & Socials ] -------> No Twitter/TG/Web? -----> [ REJECT ]
            | (Pass)
            v
   [ 5. Composite Risk Score ] -----> Score > Threshold? -----> [ REJECT ]
            | (Pass)
            v
    [ EXECUTE BUY ORDER ]
```

### Mathematical & Algorithmic Heuristics

1. **Developer Wallet Profiling (`evaluate_dev_wallet`)**: Rejects tokens if creator launched $>5$ tokens in 24 hours (Risk Penalty: $+40.0$).
2. **Creator Holding Guard (`evaluate_creator_holdings`)**: Rejects if creator purchased $>8.0\%$ of supply at inception (Risk Penalty: $+50.0$).
3. **Holder Concentration & Gini Coefficient (`HolderDistribution`)**: Computes supply inequality across non-AMM wallets:
   $$G = \frac{\sum_{i=1}^n \sum_{j=1}^n |w_i - w_j|}{2n \sum_{i=1}^n w_i}$$
   Rejects if top 5 non-bonding-curve wallets hold $>15.0\%$ of supply or if $G > 0.85$.
4. **Metadata & Social Presence Validation**: Validates presence of verified social links.

### Configuration Example & Parameter Matrix

```json
{
  "enable_anti_rug_filters": true,
  "max_dev_24h_launches": 5,
  "max_creator_initial_holding_pct": 0.08,
  "max_top5_holder_concentration_pct": 0.15,
  "max_gini_coefficient": 0.85,
  "require_social_links": false,
  "require_holder_data": false,
  "require_pump_mint_suffix": true,
  "allow_mint_reentry": false,
  "min_social_links_count": 1,
  "max_acceptable_risk_score": 50.0,
  "screening_cache_ttl_seconds": 60
}
```

`require_holder_data: true` rejects a token outright when no holder data could be read (otherwise missing holders adds 30 risk points and the top-5 / Gini checks are skipped). The canary config sets it (BUG-107).

`require_pump_mint_suffix` (default `true`) skips stream tokens whose mint doesn't end in `pump`; tokens that PumpPortal tags with another launchpad `pool` are always skipped, and every buy needs a bonding curve owned by the Pump.fun program (BUG-108). `allow_mint_reentry` (default `false`) controls whether a mint whose position was closed may be bought again (BUG-109).

`skip_mayhem_mode` (default `true`) skips Pump.fun's mayhem-mode launches: the create event's `is_mayhem_mode` flag rejects the token before screening, and a buy is refused when the curve account's mayhem byte is set. In mayhem mode an agent trades the curve after launch and the virtual SOL reserve drifts off the standard 30 SOL invariant (46 SOL two seconds after launch on mainnet), so the bot's curve pricing and exits don't hold.

Paper mode (`--paper-trade` / `dry_run`) can be made to pay for the latency of a real buy: `paper_entry_delay_seconds` waits and re-reads the curve before the fill, and `paper_entry_slippage_bps` worsens the fill (fewer tokens, higher entry market cap). Both default to 0. For Stage 0 use roughly the screening p50 plus landing time, e.g. `1.5` s and `300` bps, so paper profit is a conservative estimate.

Held positions are re-priced from their bonding curve every `position_refresh_seconds` (default `1.0`; `0` falls back to the 5 s health loop), in their own task, so exits don't depend on trade messages arriving (BUG-112). `require_trade_feed` (default `true`) refuses new buys while the trade-feed circuit breaker is open (the stream refuses token-trade subscriptions, usually because the PumpPortal API key's wallet has run out of funds), so the bot never opens a position it can't watch. The breaker closes only on a confirmed subscription or trade data; it probes every `trade_feed_probe_seconds` (BUG-116). The creator used by the serial-launcher and rug-history checks comes from the create event's signer; a missing creator or the system-program placeholder counts as missing dev data (+30 risk points) rather than a clean pass (BUG-113).

* **`enable_anti_rug_filters`**: Master toggle for heuristic pre-trade screening.
* **`max_creator_initial_holding_pct`**: Maximum percentage of curve supply creator can hold at inception (e.g. `0.08` = 8%).
* **`max_gini_coefficient`**: Maximum acceptable Gini concentration coefficient (e.g. `0.85`).
* **`max_acceptable_risk_score`**: Maximum cumulative risk score before token is rejected (default `50.0`).
* **Environment Variables**: `PUMPFUN_ANTI_RUG_ENABLED`, `PUMPFUN_MAX_CREATOR_HOLDING_PCT`, `PUMPFUN_MAX_GINI_COEFFICIENT`, `PUMPFUN_MAX_RISK_SCORE`.

---

## 7. On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)

To protect capital against organized multi-wallet insider syndicates and artificial volume wash trading, `pumpfun-trading` maps directed wallet funding flows and analyzes circular trade patterns.

```
       [ Root Funding Wallet / CEX Hot Wallet ]
                      /          \
                     v            v
             [ Funder A ]      [ Funder B ]
              /        \        /        \
             v          v      v          v
          [Holder 1] [Holder 2] [Holder 3] [Holder 4]
             \_________________________________/
                              |
               Syndicate Controls >= 25% Supply?
                              |
                   [ REJECT AS INSIDER CLUSTER ]
```

### Mathematical Formulation

1. **Funding Cluster Graph (`FundingClusterGraph`)**: Reconstructs directed funding trees ($\text{Funder} \to \text{Recipient}$) up to configured depth (`cluster_trace_depth = 2` to `3`), resolving common root funding origins across the top 10 holders and token creator.
2. **Insider Cluster Concentration Index ($I_{\text{cluster}}$)**:
   $$I_{\text{cluster}} = \sum_{c \in \text{Syndicates}} \text{SupplyFraction}(c)$$
   Rejects candidate tokens if $I_{\text{cluster}} \ge 0.25$ (Risk Penalty: $+50.0$) or if any single cluster controls $\ge 0.20$ of circulating supply (Risk Penalty: $+40.0$).
3. **Sybil Wash-Trading Pattern Detector (`SybilWashTradingDetector`)**: Scans real-time trade sequences for circular buy/sell patterns, alternating ping-pong swaps, and rapid zero-profit wallet churn. Rejects tokens with $\ge 20\%$ coordinated wash volume (Risk Penalty: $+60.0$).

### Configuration Example & Parameter Matrix

```json
{
  "enable_cluster_analysis": true,
  "max_cluster_concentration_pct": 0.25,
  "max_single_cluster_pct": 0.20,
  "max_sybil_wash_ratio": 0.20,
  "cluster_trace_depth": 2
}
```

* **`enable_cluster_analysis`**: Enables on-chain cluster graph and sybil wash detection.
* **`max_cluster_concentration_pct`**: Maximum aggregate supply fraction controlled by multi-wallet clusters (e.g. `0.25` = 25%).
* **`max_single_cluster_pct`**: Maximum supply fraction controlled by any single detected funding cluster (e.g. `0.20` = 20%).
* **`max_sybil_wash_ratio`**: Maximum allowable ratio of circular wash volume to total volume (e.g. `0.20` = 20%).
* **`cluster_trace_depth`**: Number of funding hops traced back on-chain (default `2`).
* **Environment Variables**: `PUMPFUN_CLUSTER_ANALYSIS_ENABLED`, `PUMPFUN_MAX_CLUSTER_CONCENTRATION_PCT`, `PUMPFUN_MAX_SINGLE_CLUSTER_PCT`, `PUMPFUN_MAX_SYBIL_WASH_RATIO`, `PUMPFUN_CLUSTER_TRACE_DEPTH`.

---

## 8. Real-Time Order Flow & Trade Velocity Momentum Analytics (FEAT-07)

To capture explosive momentum breakouts on active Pump.fun bonding curves before price curves steepen, `pumpfun-trading` implements real-time sliding window order flow tracking and statistical trade velocity anomaly detection.

```
 Yellowstone Geyser gRPC Stream
               |
               v (TradeEventUpdate)
     [ OrderFlowEngine ]
               |
  +------------+------------+
  | Rolling Sliding Windows | (15s, 30s, 60s)
  | - Buy/Sell Volume Ratio |
  | - Net SOL Inflow        |
  | - Unique Buyer Count    |
  | - Trade Velocity (tx/s) |
  +------------+------------+
               |
               v
     [ Velocity Z-Score ] ------> $Z = \frac{v - \mu}{\sigma} \ge 2.5$?
               | (Pass)
               v
     [ Anti-Wash Guard ] -------> Unique Buyers $\ge 3$ & Net Inflow $\ge 0.5$ SOL?
               | (Pass)
               v
     [ Anti-Rug Screening ] ----> Passed Heuristics?
               | (Pass)
               v
      [ EXECUTE BUY ORDER ]
```

### Mathematical Formulation

1. **Sliding Window Metrics**: Evaluates rolling event deques across configurable durations ($W = 30\text{s}$). Computes Net SOL Inflow ($\Delta V_{\text{SOL}} = V_{\text{buy}} - V_{\text{sell}}$) and Buy/Sell Volume Ratio ($R_{\text{vol}} = V_{\text{buy}} / V_{\text{sell}}$).
2. **Trade Velocity Z-Score**: Evaluates active trade velocity ($v_0$) against rolling baseline mean ($\mu$) and standard deviation ($\sigma$):
   $$Z = \frac{v_0 - \mu}{\sigma}$$
   Flags momentum breakouts when $Z \ge 2.5$.
3. **Sybil Resistance**: Enforces minimum unique buyer wallet count ($\ge 3$) and net capital deployment ($\ge 0.5\text{ SOL}$).

### Configuration Example & Parameter Matrix

```json
{
  "enable_momentum_signals": true,
  "momentum_window_seconds": 30,
  "momentum_min_buy_ratio": 3.0,
  "momentum_min_z_score": 2.5,
  "momentum_min_unique_buyers": 3,
  "momentum_min_net_inflow_sol": 0.5,
  "momentum_baseline_window_seconds": 300,
  "momentum_max_token_age_seconds": 1800
}
```

* **`enable_momentum_signals`**: Enables real-time order flow and velocity Z-score evaluation.
* **`momentum_min_buy_ratio`**: Minimum buy-to-sell volume ratio required in the active window (e.g. `3.0` = 3:1 buy pressure).
* **`momentum_min_z_score`**: Statistical Z-score threshold for trade velocity anomaly detection (e.g. `2.5`).
* **`momentum_min_unique_buyers`**: Minimum unique buyer addresses in the active window (default `3`).
* **`momentum_min_net_inflow_sol`**: Minimum net SOL volume deposited during the window (default `0.5 SOL`).
* **Environment Variables**: `PUMPFUN_MOMENTUM_ENABLED`, `PUMPFUN_MOMENTUM_MIN_BUY_RATIO`, `PUMPFUN_MOMENTUM_MIN_Z_SCORE`, `PUMPFUN_MOMENTUM_MIN_UNIQUE_BUYERS`, `PUMPFUN_MOMENTUM_MIN_NET_INFLOW_SOL`.

---

## 9. Raydium Migration Sniping & Post-Graduation Momentum Engine (FEAT-05)

When a token bonding curve achieves full capitalization ($\ge 85\text{ SOL}$ in real reserves, $\sim\$69\text{k}$ market cap, or on-chain `complete == True`), liquidity migrates into a newly initialized Raydium AMM v4 liquidity pool.

```
 Bonding Curve Near Completion (>= 80 SOL)
                   |
                   v
      [ Graduation Candidate Tracking ]
                   |
                   v
     On-Chain Complete Event Received ----> Exit Bonding Curve Positions
                   |
                   v
     Raydium AMM v4 Initialize2 Parsed
                   |
                   v
     [ Raydium SwapBaseIn Builder ] ------> Dynamic Tip + Priority Fees
                   |
                   v
      [ Jito MEV Private Bundle ] --------> Atomic Sub-Slot Inclusion
```

### Execution Protection

1. **Pre-Migration Staging**: Tokens reaching $\ge 80.0\text{ SOL}$ reserves are staged in `GraduationEngine` to prime routing tables.
2. **Atomic Pool Initialization Extraction**: Solana transactions containing `Initialize2` are decoded into `RaydiumPoolKeys` within $<0.2\text{ms}$.
3. **Zero-Sandwich Bundle Routing**: Swap transactions (`SwapBaseIn`) are routed exclusively through private Jito MEV bundles with dynamic validator tips.

### Configuration Example & Parameter Matrix

```json
{
  "enable_raydium_migration_sniping": true,
  "raydium_pre_migration_sol_threshold": 80.0,
  "raydium_buy_amount_sol": 0.02,
  "raydium_slippage_bps": 500,
  "raydium_priority_fee_lamports": 100000,
  "raydium_max_entry_latency_seconds": 30.0
}
```

* **`enable_raydium_migration_sniping`**: Enables automated Raydium AMM v4 pool sniping upon graduation.
* **`raydium_pre_migration_sol_threshold`**: Real SOL curve reserve threshold to begin staging graduation keys (default `80.0 SOL`).
* **`raydium_buy_amount_sol`**: Trade allocation dedicated to Raydium post-migration buy.
* **`raydium_slippage_bps`**: Allowed slippage basis points for the Raydium swap (e.g. `500` = 5.0%).
* **Environment Variables**: `PUMPFUN_RAYDIUM_SNIPE_ENABLED`, `PUMPFUN_RAYDIUM_BUY_SOL`, `PUMPFUN_RAYDIUM_SLIPPAGE_BPS`.

---

## 10. Smart Money Tracking & Copy-Trading Engine (FEAT-06)

To capture high-conviction alpha generated by proven insider wallets, KOLs, and top-tier algorithmic traders on Pump.fun bonding curves, `pumpfun-trading` integrates a real-time smart money tracking and copy-trading engine.

```
 Yellowstone Geyser / WebSocket Stream
                   |
                   v (TradeEventUpdate: user, mint, sol_amount, is_buy)
        [ CopyTradeEngine ]
                   |
                   v (O(1) Hash Map Lookup)
        [ WalletRegistry ] ---------------> Untracked? Ignore (<0.05ms)
                   | (Tracked & Enabled)
                   v
        [ Qualification Filters ] --------> Win Rate >= Min & Risk Score <= Max?
                   | (Pass)
                   +-----------------------------------+
                   |                                   |
                   v (If is_buy == True)               v (If is_buy == False & Mirror Sells)
         [ Proportional Sizing ]              [ Active Position Check ]
                   |                                   |
                   v                                   v
        [ Anti-Rug Screening ]                [ Immediate Exit Execution ]
                   | (Pass)
                   v
        [ Portfolio Risk Validation ]
                   | (Pass)
                   v
        [ EXECUTE COPY BUY ]
```

### Mathematical & Quantitative Sizing Models

1. **Proportional Position Sizing (`copy_trading_sizing_mode: "proportional"`)**:
   Scales bot allocation proportionally relative to the tracked wallet's trade size against their reference bankroll:

   $$\text{Entry SOL} = \min\left(\text{max\_pos\_sol},\, \text{max\_alloc}_{\text{wallet}},\, \text{base\_buy} \times S_{\text{factor}} \times \left(\frac{\text{trade}_{\text{SOL}}}{\text{bankroll}_{\text{ref}}}\right)\right)$$

   *Example*: With `base_buy = 0.005 SOL`, `scale_factor = 1.0`, `bankroll_ref = 10.0 SOL`, and the smart wallet executing a `5.0 SOL` buy (50% bankroll conviction), the bot automatically allocates `0.0025 SOL`.

2. **Scaled (Conviction-Weighted) Sizing (`copy_trading_sizing_mode: "scaled"`)**:
   Scales trade allocation dynamically according to the tracked wallet's historical win rate:

   $$C_{\text{conviction}} = \max\left(0.50,\, \min\left(2.0,\, \frac{\text{win\_rate}}{0.50}\right)\right)$$
   $$\text{Entry SOL} = \min\left(\text{max\_pos\_sol},\, \text{max\_alloc}_{\text{wallet}},\, \text{base\_buy} \times S_{\text{factor}} \times C_{\text{conviction}}\right)$$

3. **Dynamic Performance & Risk Profiling**:
   Wallets in `WalletRegistry` update dynamic metrics after each closed trade outcome:

   $$\text{win\_rate}_{n+1} = \frac{W_n + \mathbb{I}(R > 0)}{n + 1}, \qquad \overline{R}_{n+1} = \frac{n \cdot \overline{R}_n + R}{n + 1}$$

   *Drawdown Risk Penalization*: When a tracked wallet incurs a severe loss ($R < -20\%$), its risk score is automatically penalized ($+5.0$), disqualifying reckless traders from triggering mirrored executions.

4. **Safety & De-Risking Controls**:
   * **Pre-Trade Anti-Rug Screening (`copy_trading_require_anti_rug_screen: true`)**: All copy-trade buys must satisfy developer launch limits, creator supply caps, and holder Gini distribution metrics before order dispatch.
   * **Mirrored Sell Synchronization (`copy_trading_mirror_sells: true`)**: When a smart money wallet liquidates or trims a position in a token held by the bot, `copy_trading_mirror_sells` immediately triggers position exits to capture gains before liquidity evaporates.

### Configuration Example & Parameter Matrix

```json
{
  "enable_copy_trading": true,
  "copy_trading_sizing_mode": "proportional",
  "copy_trading_scale_factor": 1.0,
  "copy_trading_min_wallet_win_rate": 0.60,
  "copy_trading_max_wallet_risk_score": 40.0,
  "copy_trading_mirror_sells": true,
  "copy_trading_require_anti_rug_screen": true,
  "copy_trading_wallets": [
    {
      "address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
      "label": "AlphaWhale_1",
      "win_rate": 0.72,
      "reference_bankroll_sol": 25.0,
      "max_allocation_sol": 0.01
    },
    {
      "address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
      "label": "TopSniper_2",
      "win_rate": 0.65,
      "reference_bankroll_sol": 10.0,
      "max_allocation_sol": 0.008
    }
  ]
}
```

* **`enable_copy_trading`**: Master switch enabling copy trading signal evaluation.
* **`copy_trading_wallets`**: List of tracked wallet objects containing address, win rate, reference bankroll, and maximum per-trade allocation.
* **`copy_trading_sizing_mode`**: Dynamic sizing algorithm (`"proportional"`, `"scaled"`, or `"fixed"`).
* **`copy_trading_scale_factor`**: Global multiplier applied to copy trade allocations (default `1.0`).
* **`copy_trading_min_wallet_win_rate`**: Minimum required historical win rate (e.g. `0.60` = 60%).
* **`copy_trading_max_wallet_risk_score`**: Maximum allowable wallet risk score (default `40.0`).
* **`copy_trading_mirror_sells`**: Automatically liquidates holdings when the tracked wallet sells (default `true`).
* **`copy_trading_require_anti_rug_screen`**: Enforces strict anti-rug screening before mirroring copy buys (default `true`).
* **Environment Variables**: `PUMPFUN_COPY_TRADING_ENABLED`, `PUMPFUN_COPY_TRADING_SIZING_MODE`, `PUMPFUN_COPY_TRADING_SCALE_FACTOR`, `PUMPFUN_COPY_TRADING_WALLETS`.

---

## 11. Multi-RPC Dynamic Load Balancing & Failover Pool (FEAT-08)

High-frequency algorithmic trading on Solana demands sub-millisecond execution and 99.99% network reliability. `pumpfun-trading` implements an asynchronous Multi-RPC Connection Pool (`RpcConnectionPool`) that continuously monitors endpoint latencies, enforces dynamic circuit breaking, routes read queries to the fastest healthy node, and concurrently broadcasts signed transactions across operational RPC providers.

```
                  +----------------------------------------------+
                  |         Bot Execution & Runtime Layer        |
                  +----------------------------------------------+
                                   |           |
            (Account Reads / Blockhashes)      (Send Signed Transaction)
                                   |           |
                                   v           v
                    +--------------------+   +---------------------------+
                    | Lowest-Latency Read|   | Concurrent Multi-RPC      |
                    | Query Router       |   | Scatter-Gather Broadcaster|
                    +--------------------+   +---------------------------+
                               |                           |
                 +-------------+-------------+             | (Simultaneous)
                 |             |             |             |
                 v             v             v             v
            +---------+   +---------+   +---------+   +---------+
            | Primary |   | Secondary|  | Fallback|   | Backup  |
            | RPC 1   |   | RPC 2   |   | RPC 3   |   | RPC 4   |
            +---------+   +---------+   +---------+   +---------+
                 |             |             |             |
                 +-------------+-------------+-------------+
                                       |
                                       v
                    +------------------------------------+
                    | Dynamic Circuit Breaker & Health   |
                    | State Machine (p50/p95 Tracking)   |
                    +------------------------------------+
```

### Mathematical & Quantitative Latency Scoring

1. **Rolling Latency Profiling**: Bounded sliding window ($N = 100$ samples) calculating $\mu$, $p_{50}$, $p_{95}$, and $p_{99}$.
2. **Weighted Routing Score**:
   $$\text{Score} = \frac{p_{50}}{\max(0.1, W)} + \text{Penalty}_{\text{state}}$$
   Where $\text{Penalty}_{\text{DEGRADED}} = 50.0\text{ ms} + (\text{failures} \times 25.0\text{ ms})$, $\text{Penalty}_{\text{OPEN}} = 10,000.0\text{ ms}$.
3. **Multi-RPC Scatter-Gather Broadcast**: Signed transactions are broadcast concurrently across up to `broadcast_concurrency` healthy nodes (`asyncio.as_completed`).

### Configuration Example & Parameter Matrix

```json
{
  "enable_rpc_pool": true,
  "rpc_endpoints": [
    "https://mainnet.helius-rpc.com/?api-key=YOUR_KEY_1",
    "https://solana-mainnet.g.alchemy.com/v2/YOUR_KEY_2",
    "https://api.mainnet-beta.solana.com"
  ],
  "rpc_pool_health_check_interval_seconds": 30.0,
  "rpc_pool_circuit_breaker_threshold": 3,
  "rpc_pool_circuit_breaker_cooldown_seconds": 60.0,
  "rpc_pool_broadcast_concurrency": 3
}
```

* **`enable_rpc_pool`**: Enables active multi-RPC connection pooling and failover.
* **`rpc_endpoints`**: Ordered list of Solana JSON-RPC endpoints.
* **`rpc_pool_circuit_breaker_threshold`**: Consecutive errors before tripping endpoint circuit breaker into OPEN state (default `3`).
* **`rpc_pool_broadcast_concurrency`**: Number of healthy RPC nodes receiving concurrent transaction broadcasts (default `3`).
* **Environment Variables**: `PUMPFUN_RPC_POOL_ENABLED`, `PUMPFUN_RPC_ENDPOINTS`, `PUMPFUN_RPC_POOL_CONCURRENCY`.

---

## 12. Dynamic Volatility-Aware Slippage & Priority Fee Engine (FEAT-23)

Static price slippage bounds and fixed priority fees create two severe vulnerabilities: under-protection during high-volatility dumps and MEV sandwich exploitation during calm market regimes.

```
 Bonding Curve State Update (Price & Reserves)
                     │
                     ▼
 [ Instantaneous Velocity ] ──► v = (P_t1 - P_t0) / dt
 [ Rolling Volatility ]     ──► sigma = StdDev(returns)
 [ Reserve Depth Impact ]   ──► PriceImpact = dx / x_virtual
                     │
                     ▼
 [ Adaptive Execution Policy ]
  ├─ Dynamic Slippage: S = clamp(S_base + alpha*sigma + beta*Impact, S_min, S_max)
  └─ Urgency Tiering: Compute Units & Jito Tips scaled by trade context
```

### Mathematical Formulation

1. **Instantaneous Price Velocity**: $v = \frac{P_{t_1} - P_{t_0}}{\max(10^{-4}, t_1 - t_0)}$
2. **Rolling Volatility**: $\sigma_{\text{vol}} = \sqrt{\frac{1}{N} \sum_{i=1}^N (r_i - \overline{r})^2}$
3. **Price Impact**: $\Delta P_{\text{impact}} = \frac{\Delta x}{x_{\text{virtual}}}$
4. **Dynamic Slippage**:
   $$S_{\text{dynamic}} = \operatorname{clamp}\left(\left(S_{\text{base}} + \alpha \cdot \sigma_{\text{vol}} \times 10^4 + \beta \cdot \Delta P_{\text{impact}} \times 10^4\right) \times M_{\text{urgency}},\; S_{\text{min}},\; S_{\text{max}}\right)$$

### Urgency Tiers & Compute Budget Scaling

| Urgency Tier | Trigger Context | Compute Units | Compute Price Multiplier | Jito Tip (Lamports) | Max Slippage Cap |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `NORMAL_ENTRY` | Standard screening entry | $200,000$ | $1.0\text{x}$ ($50\text{k}$ µLamports) | $100,000$ | $500\text{ BPS}$ |
| `HIGH_CONVICTION` | High Z-score breakout | $250,000$ | $1.5\text{x}$ ($75\text{k}$ µLamports) | $150,000$ | $500\text{ BPS}$ |
| `GRADUATION_SNIPE` | Terminal curve / Raydium pool | $300,000$ | $2.5\text{x}$ ($125\text{k}$ µLamports) | $250,000$ | $800\text{ BPS}$ |
| `EMERGENCY_EXIT` | Stop-loss / panic liquidation | $400,000$ | $4.0\text{x}$ ($200\text{k}$ µLamports) | $400,000$ | $5000\text{ BPS}$ |

### Configuration Example & Parameter Matrix

```json
{
  "enable_dynamic_slippage": true,
  "min_slippage_bps": 100,
  "max_slippage_bps": 500,
  "max_exit_slippage_bps": 5000,
  "priority_fee_mode": "adaptive",
  "volatility_slippage_multiplier": 1.0,
  "price_impact_slippage_multiplier": 1.0
}
```

* **`enable_dynamic_slippage`**: Enables volatility-aware slippage scaling.
* **`min_slippage_bps`**: Minimum slippage floor in basis points (e.g. `100` = 1.0%).
* **`max_slippage_bps`**: Maximum slippage ceiling for entries (e.g. `500` = 5.0%).
* **`max_exit_slippage_bps`**: Maximum allowed slippage for emergency stop-loss exits (e.g. `5000` = 50.0%).
* **`priority_fee_mode`**: Priority fee scaling policy (`"adaptive"` or `"fixed"`).
* **Environment Variables**: `PUMPFUN_DYNAMIC_SLIPPAGE_ENABLED`, `PUMPFUN_MIN_SLIPPAGE_BPS`, `PUMPFUN_MAX_SLIPPAGE_BPS`, `PUMPFUN_MAX_EXIT_SLIPPAGE_BPS`, `PUMPFUN_PRIORITY_FEE_MODE`.

---

## 13. Opportunistic Capital Rotation & High-Conviction Displacement (FEAT-24)

When `max_active_positions` or `max_total_exposure_sol` is saturated, standard bots reject new entry signals, trapping capital in stagnant bonding curves while 95th+ percentile breakout candidates are missed.

```
 Breakout Candidate Detected (EV_candidate >= 0.95)
                     │
                     ▼
  [ Position Capacity Saturated? ] (len(positions) >= max_active_positions)
                     │ (Yes)
                     ▼
  [ Identify Weakest Open Asset ] ──► EV_weakest = min(EV_positions)
                     │
                     ▼
  [ Frictional Hurdle Check ]
    EV_candidate - EV_weakest > 2*Slippage + HurdleMargin (3.0%)?
                     │ (Pass)
                     ▼
  [ Atomic Rotation Workflow ]
   1. Priority Market Sell on Weakest Holding (Free up SOL)
   2. Immediate Market Buy on Breakout Candidate
```

### Expected Value (EV) Scoring Model

Active positions and incoming breakout candidates are continuously evaluated by `PositionEvEvaluator`:

$$\text{EV} = w_z \cdot Z_{\text{norm}} + w_{\text{inflow}} \cdot \text{Inflow}_{\text{norm}} + w_p \cdot \text{PnL}_{\text{norm}} - w_{\text{stag}} \cdot \text{Stagnation}$$

### Frictional Hurdle Displacement Condition

A candidate breakout displaces the weakest active holding if and only if:
1. The weakest holding has exceeded `min_hold_before_displacement_seconds` ($45\text{s}$).
2. Candidate conviction meets `displacement_min_conviction_percentile` ($\ge 0.95$).
3. The net Expected Value delta exceeds total round-trip transaction friction:
   $$\text{EV}_{\text{candidate}} - \text{EV}_{\text{weakest}} > 2 \times \text{Slippage}_{\text{base}} + \text{HurdleMargin}_{\text{displacement}}$$

### Configuration Example & Parameter Matrix

```json
{
  "enable_capital_rotation": true,
  "displacement_min_conviction_percentile": 0.95,
  "displacement_hurdle_rate_pct": 0.03,
  "min_hold_before_displacement_seconds": 45.0,
  "displacement_evaluation_interval_seconds": 2.0
}
```

* **`enable_capital_rotation`**: Enables autonomous capital displacement when capacity is full.
* **`displacement_min_conviction_percentile`**: Minimum conviction percentile of candidate required to trigger displacement (e.g. `0.95` = 95th percentile).
* **`displacement_hurdle_rate_pct`**: Minimum net EV edge over round-trip transaction costs (e.g. `0.03` = 3.0%).
* **`min_hold_before_displacement_seconds`**: Minimum holding duration before an open asset can be displaced (default `45.0s`).
* **Environment Variables**: `PUMPFUN_CAPITAL_ROTATION_ENABLED`, `PUMPFUN_DISPLACEMENT_MIN_CONVICTION`, `PUMPFUN_DISPLACEMENT_HURDLE_PCT`, `PUMPFUN_MIN_HOLD_BEFORE_DISPLACEMENT`.

---

## 14. Predictive Graduation Curve Acceleration Harvester (FEAT-25)

Bonding curves approaching Raydium graduation ($\sim 85\text{ SOL}$ reserves / $\$69\text{k}$ market cap) experience an exponential price acceleration phase followed by high post-migration volatility.

```
 Curve Progress Approaching 70% - 85%
                   │
                   ▼
 [ Reserve Acceleration Calculation ] ──► a_curve = d^2(SOL) / dt^2
                   │
                   ▼
 [ Trajectory Classification ]
   ├─ "organic": Positive acceleration & unique buyers ──► Pre-Graduation Entry Trigger
   ├─ "syndicate_sweep": Whale sweep spike              ──► Early Scaled Take-Profit
   └─ "exhaustion": Decelerating order flow             ──► Suppress Entry / Exit
                   │
                   ▼
 [ Pre-Graduation Multi-Stage Take-Profit Ladder ]
   ├─ Tranche 1: Sell 30% @ 92% Curve Progress
   ├─ Tranche 2: Sell 30% @ 97% Curve Progress
   └─ Moonbag: Retain 40% riding into Raydium Migration
```

### Acceleration Dynamics & Trajectory Modeling

1. **Curve Reserve Inflow Acceleration ($a_{\text{curve}}$)**:
   $$a_{\text{curve}} = \frac{d^2(\text{SOL})}{dt^2} = \frac{v_2 - v_1}{\Delta t_{\text{mid}}}$$
2. **Deterministic Trajectory Classification**:
   * **`organic`**: Sustained positive acceleration ($a_{\text{curve}} \ge 0$) and $\ge 2$ unique buyers $\implies$ High-conviction pre-graduation entry trigger.
   * **`syndicate_sweep`**: Instantaneous velocity spike ($v > 3.0\text{ SOL/s}$) with single buyer $\implies$ Scaled early take-profit exit.
   * **`exhaustion`**: Decelerating velocity ($v < 0$ or $a_{\text{curve}} < -0.05$) $\implies$ Entry suppressed; positions exit immediately.
3. **Staged Multi-Tranche Take-Profit Schedule**:
   * **Tranche 1 (30% scale-out)**: Executed when curve completion reaches **92%**.
   * **Tranche 2 (30% scale-out)**: Executed when curve completion reaches **97%**.
   * **Moonbag Retained (40% residual)**: Rides into Raydium pool seeding.

### Configuration Example & Parameter Matrix

```json
{
  "enable_pre_graduation_harvesting": true,
  "pre_graduation_entry_progress_pct": 0.70,
  "pre_graduation_max_entry_progress_pct": 0.85,
  "pre_graduation_min_acceleration": 0.0,
  "pre_graduation_tranches": [
    {"progress_pct": 0.92, "sell_fraction": 0.30},
    {"progress_pct": 0.97, "sell_fraction": 0.30}
  ]
}
```

* **`enable_pre_graduation_harvesting`**: Enables predictive pre-graduation entry and staged exits.
* **`pre_graduation_entry_progress_pct`**: Minimum curve completion fraction to enter (e.g. `0.70` = 70%).
* **`pre_graduation_max_entry_progress_pct`**: Maximum curve completion fraction for initial entry (e.g. `0.85` = 85%).
* **`pre_graduation_tranches`**: List of progress milestones and corresponding sell fractions.
* **Environment Variables**: `PUMPFUN_PRE_GRADUATION_ENABLED`, `PUMPFUN_PRE_GRAD_ENTRY_PROGRESS`, `PUMPFUN_PRE_GRAD_MAX_ENTRY_PROGRESS`.

---

## 15. Adaptive Realized-Ratchet Drawdown & Dual-Tier Risk Engine (FEAT-29)

To eliminate false-positive circuit breaker lockouts after large profitable runs while preserving aggregate capital, the bot separates portfolio equity into two distinct regimes:

```
+-----------------------------------------------------------------------------------+
|                              PORTFOLIO EQUITY STATES                              |
+-----------------------------------------------------------------------------------+
|  [HIGH-WATER MARK] (Peak Equity with Unrealized Wicks)                             |
|       |                                                                           |
|       |  --> Managed by: Individual Position Trailing Stops (FEAT-03)             |
|       v                                                                           |
|  [REALIZED RATCHET BASELINE] = Starting Capital + (alpha * Realized Profits)       |
|       |                                                                           |
|       |  --> Buffer Zone: Relaxed Trailing Drawdown on "House Money" (35% - 40%)  |
|       v                                                                           |
|  [CAPITAL PRESERVATION FLOOR] = Starting Capital * (1 - Max Principal Drawdown)   |
|       |                                                                           |
|       |  --> Hard Stop: HALT_ENTRIES / Emergency Action                           |
+-------v---------------------------------------------------------------------------+
```

### Mathematical Formulation & Dual-Zone Logic

1. **Guaranteed Ratchet Baseline**:
   $$\text{Baseline}_{\text{effective}} = \text{Starting Capital} + \alpha \times \max(0, \text{Realized PnL})$$
   Where $\alpha = \text{profit\_ratchet\_ratio}$ (default `0.50`).
2. **Principal Protection Zone (`Current Equity < Starting Capital`)**:
   * Evaluates maximum allowed loss against initial starting capital.
   * If total equity drops below $\text{Starting Capital} \times (1 - \text{max\_daily\_drawdown\_pct})$, trigger emergency circuit breaker.
3. **Profit Run Zone (`Current Equity >= Starting Capital`)**:
   * Applies relaxed trailing drawdown tolerance (`profit_drawdown_tolerance_pct`, default `35% - 40%`) against peak equity.
   * Prevents premature session lockouts when volatile moonbags retrace after multi-tier take-profits.
4. **Tiered Two-Stage Action**:
   * **Stage 1 (`halt_new_buys`)**: Soft halt suppressing new buys while open positions exit orderly via trailing stops.
   * **Stage 2 (`emergency_liquidate`)**: Global emergency market sell across all open holdings.

### Configuration Example & Parameter Matrix

```json
{
  "drawdown_reference_mode": "adaptive_ratchet",
  "max_daily_drawdown_pct": 0.25,
  "profit_drawdown_tolerance_pct": 0.40,
  "profit_ratchet_ratio": 0.50,
  "auto_liquidate_on_circuit_breaker": false
}
```

* **`drawdown_reference_mode`**: Circuit breaker policy mode (`"adaptive_ratchet"`, `"baseline"`, or `"trailing_hwm"`).
* **`max_daily_drawdown_pct`**: Maximum drawdown from starting capital before engaging Stage 2 protection (e.g. `0.25` = 25%).
* **`profit_drawdown_tolerance_pct`**: Allowed trailing retracement on profits in the Profit Run Zone (e.g. `0.40` = 40%).
* **`profit_ratchet_ratio`**: Fraction of realized gains permanently banked into guaranteed baseline floor (e.g. `0.50` = 50%).
* **`auto_liquidate_on_circuit_breaker`**: Determines whether to execute global emergency market sells upon circuit breaker engagement.
* **Environment Variables**: `PUMPFUN_DRAWDOWN_MODE`, `PUMPFUN_MAX_DAILY_DRAWDOWN`, `PUMPFUN_PROFIT_DRAWDOWN_TOLERANCE_PCT`, `PUMPFUN_PROFIT_RATCHET_RATIO`.

---

## 16. Automated Hyperparameter Backtest Optimizer (FEAT-27)

To counteract parameter decay as market volatility regimes shift, `pumpfun-trading` integrates an automated multi-objective hyperparameter optimization engine (`pumpfun_trading/engines/optimizer.py`).

```
 Recorded Historical Market Dataset (.jsonl / .jsonl.gz)
                     │
                     ▼
       [ Parameter Search Space ] (Sizing, TP Tiers, Trailing, Z-Scores, Stagnation)
                     │
                     ▼
       [ Optimization Engine ]
         ├─ Genetic Algorithm (Elitism, Tournament, Crossover, Mutation)
         ├─ Random Search
         └─ Grid Search
                     │
                     ▼
       [ Walk-Forward Cross-Validation ] (70% In-Sample / 30% Out-of-Sample)
                     │
                     ▼
       [ Multi-Objective Fitness Evaluation ]
         Composite = Sharpe + Sortino + ProfitFactor + Calmar - MaxDrawdown - OverfitPenalty
                     │
                     ▼
     [ Export Calibrated bot-config.json ] ──► pumpbot --config <file>
```

### CLI Execution & Optimization Recipes

```bash
# Run Genetic Optimization across historical replay data
pumpfun-optimize \
  --replay runtime/market_replay_24h.jsonl \
  --algo genetic \
  --generations 10 \
  --population 20 \
  --metric composite \
  --export-config runtime/configs/optimized_pilot.json

# Run Random Search Exploration
pumpfun optimize \
  --replay runtime/market_replay_24h.jsonl \
  --algo random \
  --iterations 50 \
  --export-config runtime/configs/random_pilot.json
```

---

## 17. Atomic Jito Back-Running & Cross-Venue Arbitrage Engine (FEAT-28)

To capture risk-free, delta-neutral yield across graduating Pump.fun bonding curves and external DEX liquidity pools (Raydium AMM v4), `pumpfun-trading` embeds an atomic cross-venue arbitrage engine.

```
       Disparity Monitor (Compare Pump.fun Spot vs. Raydium AMM Spot)
                                  │
                                  ▼
      Closed-Form Optimal Input (x*) Derived (Maximizing Net Profit)
                                  │
                                  ▼
      Hurdle Check: Net Profit >= 0.003 SOL & Spread >= 1.5%?
                                  │ (Pass)
                                  ▼
      Atomic Bundle Assembly (Single VersionedTransaction)
        ├─ Leg 1: Buy on Underpriced Venue
        ├─ Leg 2: Sell on Overpriced Venue
        └─ Leg 3: Dynamic Profit-Share Jito Validator Tip Transfer
                                  │
                                  ▼
      Submitted via Private Jito Block Engine (0 Capital Loss Atomicity)
```

### Closed-Form Optimal Arbitrage Sizing Math

Given fee factors $\gamma_1 = 1 - f_{\text{pump}} = 0.99$ and $\gamma_2 = 1 - f_{\text{raydium}} = 0.9975$, setting marginal return equal to marginal cost yields the exact closed-form optimal swap input $x^*$:

$$x^* = \frac{\sqrt{A \cdot C} - C}{B}$$

Where for `pump_to_raydium`:
* $A = R_{\text{sol}} \cdot \gamma_1 \cdot \gamma_2 \cdot y_{\text{virtual}}$
* $B = \gamma_1 \cdot (R_{\text{token}} + \gamma_2 \cdot y_{\text{virtual}})$
* $C = R_{\text{token}} \cdot x_{\text{virtual}}$

### Configuration Example & Parameter Matrix

```json
{
  "enable_cross_venue_arbitrage": true,
  "enable_mempool_backrunning": true,
  "min_arbitrage_profit_sol": 0.003,
  "min_arbitrage_spread_pct": 0.015,
  "max_arbitrage_input_sol": 0.50,
  "min_arbitrage_input_sol": 0.01,
  "arbitrage_jito_tip_profit_share_pct": 0.50
}
```

* **`enable_cross_venue_arbitrage`**: Master toggle enabling real-time cross-venue arbitrage capture in the bot.
* **`enable_mempool_backrunning`**: Evaluates immediate back-running rebalancing following large whale transactions.
* **`min_arbitrage_profit_sol`**: Minimum net profit hurdle in SOL after fees and Jito tips (default `0.003 SOL`).
* **`min_arbitrage_spread_pct`**: Minimum gross percentage spread hurdle (e.g. `0.015` = 1.5%).
* **`max_arbitrage_input_sol`**: Maximum SOL input allocated per arbitrage leg (default `0.50 SOL`).
* **`arbitrage_jito_tip_profit_share_pct`**: Fraction of gross profit shared with Jito block builders (default `0.50` = 50%).
* **Environment Variables**: `PUMPFUN_ARB_ENABLED`, `PUMPFUN_ARB_MIN_PROFIT_SOL`, `PUMPFUN_ARB_MIN_SPREAD_PCT`, `PUMPFUN_ARB_MAX_INPUT_SOL`, `PUMPFUN_ARB_JITO_TIP_SHARE_PCT`.

---

## 18. Structured Diagnostic Telemetry & Event Logging (FEAT-30)

To provide deep observability into real-time screening verdicts, pricing calculations, and execution latencies without blocking the high-frequency trading loop, `pumpfun-trading` implements an async batch event logger (`DiagnosticEventLogger`).

```
 Bot Subsystems (Stream / Screening / Strategy / Execution / Risk)
                                 │
                                 ▼
              [ DiagnosticEventLogger (Async Queue) ]
                                 │
                                 ▼ (Background Worker Thread)
                     [ events.jsonl Sink ]
                                 │
                                 ▼
         [ CLI Telemetry Inspection & Live Tailing Tool ]
                 pumpfun-events --tail --subsystem risk
```

### Configuration Example & Parameter Matrix

```json
{
  "enable_diagnostic_events": true,
  "event_log_path": "events.jsonl",
  "event_log_subsystems": [
    "stream",
    "screening",
    "strategy",
    "execution",
    "risk",
    "lifecycle"
  ]
}
```

* **`enable_diagnostic_events`**: Enables structured JSONL diagnostic event persistence.
* **`event_log_path`**: File path for diagnostic telemetry sink (default `events.jsonl`).
* **`event_log_subsystems`**: Active subsystem filters for event logging.
* **Environment Variables**: `PUMPFUN_DIAGNOSTIC_EVENTS_ENABLED`, `PUMPFUN_EVENT_LOG_PATH`, `PUMPFUN_EVENT_LOG_SUBSYSTEMS`.

---

## 19. Automated Log Retention & Multi-Sink Compression (FEAT-22)

Continuous 24/7 trading produces unbounded log growth across standard application logs (`bot.log`), forensic audit trails (`audit.jsonl`), and market replay recordings (`market_replay.jsonl`). The automated retention manager provides non-blocking rollover, background gzip compression, and age/quota-based pruning.

```
 Active Sinks (bot.log / audit.jsonl / replay.jsonl)
                         │
                         ▼ (Exceeds max_bytes?)
          [ RotatedFileSink Atomic Rollover ]
                         │
                         ▼ (asyncio.to_thread)
          [ Background Gzip Compression (.gz) ]
                         │
                         ▼ (Periodic Maintenance Cycle)
     [ LogRetentionManager Age & Quota Pruning ]
```

### Configuration Example & Parameter Matrix

```json
{
  "log_file": "bot.log",
  "log_max_bytes": 10485760,
  "log_backup_count": 5,
  "log_rotation_type": "size",
  "log_compress": true,
  "audit_max_bytes": 10485760,
  "audit_backup_count": 10,
  "audit_retention_days": 30,
  "audit_compress": true,
  "replay_max_bytes": 52428800,
  "replay_backup_count": 10,
  "replay_retention_days": 30,
  "replay_compress": true,
  "retention_check_interval_seconds": 3600.0
}
```

* **`log_max_bytes`**: Maximum file size in bytes before rotating `bot.log` (default `10 MB`).
* **`log_backup_count`**: Maximum retained rotated log files (default `5`).
* **`audit_retention_days`**: Maximum age in days for archived audit records before pruning (default `30`).
* **`audit_compress`**: Automatically compress rotated audit archives into `.jsonl.gz` format (default `true`).
* **Environment Variables**: `PUMPFUN_LOG_MAX_BYTES`, `PUMPFUN_LOG_BACKUP_COUNT`, `PUMPFUN_AUDIT_RETENTION_DAYS`, `PUMPFUN_AUDIT_COMPRESS`.

---

## 20. Market Regime Playbooks & Strategy Presets

The system provides three optimized preset configurations tailored to prevailing market conditions:

| Parameter | `conservative` | `balanced` (Default) | `aggressive` |
| :--- | :---: | :---: | :---: |
| **Base Buy Size** | `0.05 SOL` | `0.10 SOL` | `0.25 SOL` |
| **Max Slippage** | `150 bps` (1.5%) | `250 bps` (2.5%) | `400 bps` (4.0%) |
| **Take-Profit Multiplier (Base)** | `1.5x` (+50%) | `2.0x` (+100%) | `3.0x` (+200%) |
| **Stop-Loss Drop** | `-15%` | `-20%` | `-30%` |
| **Trailing Activation** | `+35%` | `+50%` | `+75%` |
| **Trailing Stop Retracement** | `10.0%` | `15.0%` | `20.0%` |
| **Tier 1 Scale-Out** | 60% @ 1.75x | 50% @ 2.0x | 40% @ 2.5x |
| **Tier 2 Scale-Out** | 25% @ 2.50x | 25% @ 3.5x | 30% @ 4.5x |
| **Moonbag Trailing Floor** | `1.75x` | `2.50x` | `3.00x` |
| **Require Social Links** | `True` (Min 2) | `False` (Optional) | `False` |
| **Max Acceptable Risk Score** | `35.0` | `50.0` | `70.0` |
| **Enable Momentum Signals** | `True` | `True` | `True` |
| **Momentum Min Z-Score** | `3.0` | `2.5` | `2.0` |
| **Momentum Min Buy Ratio** | `4.0` | `3.0` | `2.0` |
| **Momentum Min Unique Buyers** | `5` | `3` | `2` |
| **Momentum Min Net Inflow** | `1.0 SOL` | `0.50 SOL` | `0.25 SOL` |
| **Momentum Max Token Age** | `900s` (15m) | `1800s` (30m) | `3600s` (60m) |
| **Enable Raydium Sniping** | `True` | `True` | `True` |
| **Pre-Migration SOL Threshold**| `82.0 SOL` | `80.0 SOL` | `75.0 SOL` |
| **Raydium Buy Amount** | `0.01 SOL` | `0.02 SOL` | `0.05 SOL` |
| **Raydium Slippage Bps** | `300 bps` (3%) | `500 bps` (5%) | `800 bps` (8%) |
| **Raydium Priority Fee** | `50,000 lamports` | `100,000 lamports` | `200,000 lamports` |
| **Raydium Max Entry Latency** | `15.0s` | `30.0s` | `60.0s` |
| **Enable Cluster Analysis** | `True` | `True` | `True` |
| **Max Cluster Concentration** | `15.0%` | `25.0%` | `35.0%` |
| **Max Single Cluster Fraction** | `10.0%` | `20.0%` | `30.0%` |
| **Max Sybil Wash Ratio** | `10.0%` | `20.0%` | `30.0%` |
| **Cluster Trace Depth** | `3` | `2` | `2` |

### Market Regime Application

1. **High-Velocity Meme Wave (Bull Euphoria)**:
   * **Preset**: `aggressive` (`pumpbot --preset aggressive`)
   * **Playbook**: Broaden market cap eligibility, activate larger base buy sizes, and allow trailing moonbags to ride parabolic momentum to graduation.
2. **Consolidation / Choppy Market (Standard Conditions)**:
   * **Preset**: `balanced` (`pumpbot --preset balanced`)
   * **Playbook**: Enforce standard Kelly sizing, lock in principal at $2.0x$, and maintain active $15\%$ trailing stops.
3. **Low-Liquidity / High-Exploit Market (Bear / PvP Environment)**:
   * **Preset**: `conservative` (`pumpbot --preset conservative`)
   * **Playbook**: Strict social link requirements, tighter $10\%$ trailing offsets, and early de-risking at $+35\%$ to $+75\%$ multiples.

---

## 21. Unified Production Master Configuration Profile

Below is the complete, production-ready master JSON configuration profile integrating all alpha engines, risk limits, copy-trading models, multi-RPC failover, dynamic execution policies, and telemetry sinks:

```json
{
  "strategy_preset": "balanced",
  "buy_amount_sol": 0.005,
  "max_active_positions": 4,
  "max_total_exposure_sol": 0.03,
  "max_position_size_sol": 0.01,
  "max_token_concentration_pct": 0.35,
  "max_loss_per_trade_sol": 0.002,
  "reserve_balance_sol": 0.05,
  "min_balance_sol": 0.02,
  "min_market_cap_sol": 25.0,
  "max_market_cap_sol": 80.0,
  "min_order_flow_buyers": 3,
  "max_buy_attempts_per_mint": 3,
  "enable_tiered_take_profit": true,
  "tier_1_take_profit": 1.45,
  "tier_1_sell_fraction": 0.35,
  "tier_2_take_profit": 2.50,
  "tier_2_sell_fraction": 0.35,
  "moonbag_trailing_floor": 2.00,
  "enable_trailing_stop": true,
  "trailing_stop_activation_pct": 0.35,
  "trailing_stop_drop_pct": 0.12,
  "stop_loss": 0.85,
  "enable_stagnant_exit": true,
  "stagnant_timeout_seconds": 45.0,
  "stagnant_price_delta_threshold_pct": 0.005,
  "enable_max_hold_timeout": true,
  "max_hold_time_seconds": 600.0,
  "enable_anti_rug_filters": true,
  "max_dev_24h_launches": 5,
  "max_creator_initial_holding_pct": 0.08,
  "max_top5_holder_concentration_pct": 0.15,
  "max_gini_coefficient": 0.85,
  "require_social_links": false,
  "min_social_links_count": 1,
  "max_acceptable_risk_score": 50.0,
  "screening_cache_ttl_seconds": 60,
  "enable_cluster_analysis": true,
  "max_cluster_concentration_pct": 0.25,
  "max_single_cluster_pct": 0.20,
  "max_sybil_wash_ratio": 0.20,
  "cluster_trace_depth": 2,
  "enable_momentum_signals": true,
  "momentum_window_seconds": 30,
  "momentum_min_buy_ratio": 3.0,
  "momentum_min_z_score": 2.5,
  "momentum_min_unique_buyers": 3,
  "momentum_min_net_inflow_sol": 0.5,
  "momentum_baseline_window_seconds": 300,
  "momentum_max_token_age_seconds": 1800,
  "enable_raydium_migration_sniping": true,
  "raydium_pre_migration_sol_threshold": 80.0,
  "raydium_buy_amount_sol": 0.02,
  "raydium_slippage_bps": 500,
  "raydium_priority_fee_lamports": 100000,
  "raydium_max_entry_latency_seconds": 30.0,
  "enable_copy_trading": true,
  "copy_trading_sizing_mode": "proportional",
  "copy_trading_scale_factor": 1.0,
  "copy_trading_min_wallet_win_rate": 0.60,
  "copy_trading_max_wallet_risk_score": 40.0,
  "copy_trading_mirror_sells": true,
  "copy_trading_require_anti_rug_screen": true,
  "copy_trading_wallets": [
    {
      "address": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
      "label": "AlphaWhale_1",
      "win_rate": 0.72,
      "reference_bankroll_sol": 25.0,
      "max_allocation_sol": 0.01
    }
  ],
  "enable_rpc_pool": true,
  "rpc_endpoints": [],
  "rpc_pool_health_check_interval_seconds": 30.0,
  "rpc_pool_circuit_breaker_threshold": 3,
  "rpc_pool_circuit_breaker_cooldown_seconds": 60.0,
  "rpc_pool_broadcast_concurrency": 3,
  "enable_dynamic_slippage": true,
  "min_slippage_bps": 100,
  "max_slippage_bps": 500,
  "max_exit_slippage_bps": 5000,
  "priority_fee_mode": "adaptive",
  "volatility_slippage_multiplier": 1.0,
  "price_impact_slippage_multiplier": 1.0,
  "enable_capital_rotation": true,
  "displacement_min_conviction_percentile": 0.95,
  "displacement_hurdle_rate_pct": 0.03,
  "min_hold_before_displacement_seconds": 45.0,
  "displacement_evaluation_interval_seconds": 2.0,
  "enable_pre_graduation_harvesting": true,
  "pre_graduation_entry_progress_pct": 0.70,
  "pre_graduation_max_entry_progress_pct": 0.85,
  "pre_graduation_min_acceleration": 0.0,
  "pre_graduation_tranches": [
    {"progress_pct": 0.92, "sell_fraction": 0.30},
    {"progress_pct": 0.97, "sell_fraction": 0.30}
  ],
  "drawdown_reference_mode": "adaptive_ratchet",
  "max_daily_drawdown_pct": 0.25,
  "profit_drawdown_tolerance_pct": 0.40,
  "profit_ratchet_ratio": 0.50,
  "auto_liquidate_on_circuit_breaker": false,
  "enable_cross_venue_arbitrage": true,
  "enable_mempool_backrunning": true,
  "min_arbitrage_profit_sol": 0.003,
  "min_arbitrage_spread_pct": 0.015,
  "max_arbitrage_input_sol": 0.50,
  "min_arbitrage_input_sol": 0.01,
  "arbitrage_jito_tip_profit_share_pct": 0.50,
  "enable_diagnostic_events": true,
  "event_log_path": "events.jsonl",
  "event_log_subsystems": [
    "stream",
    "screening",
    "strategy",
    "execution",
    "risk",
    "lifecycle"
  ],
  "log_file": "bot.log",
  "log_max_bytes": 10485760,
  "log_backup_count": 5,
  "log_rotation_type": "size",
  "log_compress": true,
  "audit_max_bytes": 10485760,
  "audit_backup_count": 10,
  "audit_retention_days": 30,
  "audit_compress": true,
  "replay_max_bytes": 52428800,
  "replay_backup_count": 10,
  "replay_retention_days": 30,
  "replay_compress": true,
  "retention_check_interval_seconds": 3600.0
}
```

### Loading and Running the Configuration

To run the live bot or paper-trading simulation with this configuration:

```bash
# Live trading bot execution
pumpbot --config /path/to/master_config.json

# Live dry-run soak testing
pumpbot --config /path/to/master_config.json --dry-run --headless

# Unified CLI wrapper
pumpfun bot --config /path/to/master_config.json
```
