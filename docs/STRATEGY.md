# Financial Strategy & Wealth Generation Blueprint

This document details the quantitative models, mathematical formulations, and financial execution playbooks implemented in `pumpfun-trading`. The platform is engineered to maximize expected value ($E[V]$) per trade, optimize capital compounding efficiency, and protect aggregate portfolio equity against tail-risk drawdowns and toxic market microstructure.

---

## 1. Financial Objective & Mathematical Expectancy

In quantitative microcap trading, long-term capital compounding is governed by the mathematical expectancy equation:

$$E[V] = (P_{\text{win}} \times \overline{W}) - (P_{\text{loss}} \times \overline{L}) - C_{\text{friction}}$$

Where:
* $P_{\text{win}}$: Probability of achieving a winning trade.
* $\overline{W}$: Average gain on winning trades (amplified via multi-tier take-profit scaling and runner moonbags).
* $P_{\text{loss}}$: Probability of a losing trade.
* $\overline{L}$: Average loss on losing trades (strictly bounded via dynamic trailing stop-losses and anti-rug screening).
* $C_{\text{friction}}$: Cumulative execution friction (network gas, priority fees, validator Jito tips, and bonding curve slippage).

**Core Strategic Mandate**: Eliminate adverse selection ($P_{\text{loss}}$ reduction via anti-rug filtering), minimize execution drag ($C_{\text{friction}}$ reduction via private Jito bundles), and engineer asymmetric upside ($\overline{W} / \overline{L} \ge 3.0$ via tiered profit scaling and trailing runner exits).

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
| $< 5.0\text{ SOL}$ | $2.0\% - 3.0\%$ ($0.10 - 0.15\text{ SOL}$) | $2$ | $0.15\text{ SOL}$ |
| $5.0 - 25.0\text{ SOL}$ | $1.5\% - 2.5\%$ ($0.125 - 0.50\text{ SOL}$) | $3$ | $0.50\text{ SOL}$ |
| $> 25.0\text{ SOL}$ | $1.0\% - 2.0\%$ ($0.25 - 1.00\text{ SOL}$) | $3 - 5$ | $1.00\text{ SOL}$ |

### Compounding vs. De-Risking Protocol

To balance exponential capital growth with capital preservation:
1. **Compounding Phase**: As total wallet equity increases, trade sizing scales dynamically up to the configured single-token ceiling.
2. **Profit Sweeping Protocol**: Once bankroll reaches $200\%$ of starting capital (a $2.0x$ portfolio double), $50\%$ of accumulated net profit is automatically routed to cold storage, securing principal gains while leaving the expanded trading bankroll to compound.

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
1. The new virtual SOL reserve becomes: $x' = x + \Delta x$
2. The new virtual token reserve becomes: $y' = \frac{k}{x + \Delta x}$
3. The tokens received by the trader $\Delta y$ is:

$$\Delta y = y - y' = y - \frac{k}{x + \Delta x} = \frac{y \cdot \Delta x}{x + \Delta x}$$

4. The effective execution price per token $P_{\text{exec}}$ and instantaneous spot price $P_{\text{spot}}$ are:

$$P_{\text{exec}} = \frac{\Delta x}{\Delta y} = \frac{x + \Delta x}{y}, \qquad P_{\text{spot}} = \frac{x}{y}$$

5. **Slippage Impact ($\Delta P$)**:

$$\text{Slippage} = \frac{P_{\text{exec}} - P_{\text{spot}}}{P_{\text{spot}}} = \frac{\Delta x}{x}$$

*Example*: For a starting curve ($x = 30\text{ SOL}$), a $0.3\text{ SOL}$ buy experiences an immediate deterministic price impact of $\frac{0.3}{30} = 1.0\%$.

---

## 4. Multi-Tier Take-Profit Scaling (FEAT-03)

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

1. **Tier 1 (2.0x / +100% Gain)**:
   * **Action**: Liquidate **50% of position token quantity**.
   * **Financial Outcome**: $\text{Proceeds} = 0.50 \times 2.0 \times \text{Principal} = 1.0 \times \text{Principal}$.
   * **Impact**: Recovers **100% of initial invested capital**. The position achieves "risk-free" status (free ride), eliminating all downside risk on the trade.
2. **Tier 2 (3.5x / +250% Gain)**:
   * **Action**: Liquidate **25% of initial position token quantity** (50% of remaining balance).
   * **Financial Outcome**: Generates substantial realized net profit ($0.25 \times 3.5 = 0.875\text{ SOL}$ per $1.0\text{ SOL}$ initial principal).
3. **Tier 3 ("Moonbag" Runner Allocation — 25% of initial quantity)**:
   * **Action**: Let remaining tokens ride parabolic runs toward bonding curve graduation ($69k market cap completion).
   * **Protection**: Protected by a hard floor stop at $2.5x$ or an active dynamic trailing stop-loss.

---

## 5. Dynamic Trailing Stop-Loss Engine (FEAT-03)

To capture asymmetric trend continuation while preventing profit round-tripping, positions are monitored by real-time trailing stop algorithms:

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

1. **Continuous Peak Tracking**: For every on-chain swap and bonding curve update, calculate current market cap $M_t$ and update position peak $M_{\text{peak}}$:

$$M_{\text{peak}} \leftarrow \max(M_{\text{peak}}, M_t)$$

2. **Activation Gate**: Trailing evaluation activates once the position reaches the configurable activation threshold (default $+50\%$ or $1.50\text{x}$ entry cost basis):

$$\text{Active}_{\text{trailing}} = \text{True} \quad \text{when } M_{\text{peak}} \ge M_{\text{entry}} \times (1 + \text{Activation Offset})$$

3. **Trailing Exit Condition**: Once active, if current price or market cap retraces by more than `trailing_stop_drop_pct` (default $15.0\%$) from $M_{\text{peak}}$, an immediate market sell is triggered:

$$\text{Exit Triggered} \iff M_t \le M_{\text{peak}} \times (1.0 - \text{Trailing Drop Pct})$$

---

## 6. Pre-Trade Anti-Rug & Scam Heuristic Screening (FEAT-04)

Microcap liquidity pools are susceptible to malicious exploits. Every candidate mint is evaluated against five quantitative heuristic filters prior to transaction signing:

```
   Candidate Token Event
            |
            v
   [ 1. Dev Wallet Profiling ] -----> >5 launches / 24h? -----> [ REJECT ]
            | (Pass)
            v
   [ 2. Creator Initial Supply ] ---> Creator bought >10%? ---> [ REJECT ]
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

1. **Developer Wallet Profiling (`evaluate_dev_wallet`)**:
   * Evaluates creator historical deployment frequency.
   * *Threshold*: Rejects tokens if creator launched $>5$ tokens in the preceding 24 hours or has confirmed rug histories (Risk Penalty: $+40.0$).
2. **Creator Holding Guard (`evaluate_creator_holdings`)**:
   * Inspects creation-block token transfers.
   * *Threshold*: Rejects if creator purchased $>10.0\%$ of supply at inception (Risk Penalty: $+50.0$).
3. **Holder Concentration & Gini Coefficient (`HolderDistribution`)**:
   * Computes supply inequality across non-AMM wallets using the Gini coefficient:

$$G = \frac{\sum_{i=1}^n \sum_{j=1}^n |w_i - w_j|}{2n \sum_{i=1}^n w_i}$$

   * *Thresholds*: Rejects if top 5 non-bonding-curve wallets hold $>15.0\%$ of supply or if $G > 0.85$ (Risk Penalty: $+35.0$).
4. **Metadata & Social Presence Validation (`evaluate_metadata_socials`)**:
   * Validates URI JSON metadata structure and presence of verified Twitter/X, Telegram, or website endpoints.
5. **In-Memory TTL Screening Cache**:
   * Screening evaluations are cached in volatile memory ($60\text{s TTL}$) to maintain sub-millisecond throughput without redundant RPC calls.
6. **On-Chain Funding Cluster Graph & Sybil Wash-Trading Detector (FEAT-26)**:
   * **Funding Cluster Graph (`FundingClusterGraph`)**: Reconstructs directed funding trees ($\text{Funder} \to \text{Recipient}$) up to configured depth (`cluster_trace_depth = 2` to `3`), resolving common root funding origins across the top 10 holders and token creator.
   * **Insider Cluster Concentration Index ($I_{\text{cluster}}$)**:
     $$I_{\text{cluster}} = \sum_{c \in \text{Syndicates}} \text{SupplyFraction}(c)$$
     Rejects candidate tokens if $I_{\text{cluster}} \ge 0.25$ (Risk Penalty: $+50.0$) or if any single cluster controls $\ge 0.20$ of circulating supply (Risk Penalty: $+40.0$).
   * **Sybil Wash-Trading Pattern Detector (`SybilWashTradingDetector`)**: Scans real-time trade sequences for circular buy/sell patterns, alternating ping-pong swaps, and rapid zero-profit wallet churn. Rejects tokens with $\ge 20\%$ coordinated wash volume (Risk Penalty: $+60.0$).

---

## 7. Market Regime Playbooks & Strategy Presets

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
   * **Preset**: `aggressive`
   * **Playbook**: Broaden market cap eligibility, activate larger base buy sizes, and allow trailing moonbags to ride parabolic momentum to graduation.
2. **Consolidation / Choppy Market (Standard Conditions)**:
   * **Preset**: `balanced`
   * **Playbook**: Enforce standard Kelly sizing, lock in principal at $2.0x$, and maintain active $15\%$ trailing stops.
3. **Low-Liquidity / High-Exploit Market (Bear / PvP Environment)**:
   * **Preset**: `conservative`
   * **Playbook**: Strict social link requirements, tighter $10\%$ trailing offsets, and early de-risking at $+35\%$ to $+75\%$ multiples.

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
     [ Risk Engine Guard ] -----> Within Portfolio Risk Limits?
               | (Pass)
               v
      [ EXECUTE BUY ORDER ]
```

### Mathematical & Quantitative Formulation

1. **Sliding Window Ingestion**:
   * Evaluates rolling event deques across configurable durations ($W \in \{15\text{s}, 30\text{s}, 60\text{s}\}$).
   * Automatically evicts trades older than $t - \text{max\_retention}$ ($600\text{s}$) to maintain bounded sub-millisecond memory consumption.

2. **Order Flow Metrics**:
   * **Rolling Buy Volume ($V_{\text{buy}}$)**: Sum of all SOL purchases within window $W$.
   * **Rolling Sell Volume ($V_{\text{sell}}$)**: Sum of all SOL sales within window $W$.
   * **Net SOL Inflow ($\Delta V_{\text{SOL}}$)**:
   
     $$\Delta V_{\text{SOL}} = V_{\text{buy}} - V_{\text{sell}}$$
   
   * **Buy/Sell Volume Ratio ($R_{\text{vol}}$)**:
   
     $$R_{\text{vol}} = \begin{cases} \frac{V_{\text{buy}}}{V_{\text{sell}}} & \text{if } V_{\text{sell}} > 0 \\ 999.0 & \text{if } V_{\text{sell}} = 0 \text{ and } V_{\text{buy}} > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

3. **Statistical Anomaly Detection & Velocity Z-Score**:
   * Slices a longer rolling baseline duration (default $T_{\text{baseline}} = 300\text{s}$) into $N$ equal discrete intervals of size $W$.
   * Computes baseline velocity mean ($\mu$) and standard deviation ($\sigma$):
   
     $$\mu = \frac{1}{N} \sum_{k=0}^{N-1} v_k, \qquad \sigma = \sqrt{\frac{1}{N} \sum_{k=0}^{N-1} (v_k - \mu)^2}$$
   
   * Derives real-time trade velocity Z-score for the active window ($v_0$):
   
     $$Z = \frac{v_0 - \mu}{\sigma}$$
   
   * **Trigger Criterion**: An abnormal surge is flagged when $Z \ge 2.5$ (or preset threshold).

4. **Anti-Wash Trading & Sybil Resistance**:
   * Enforces minimum unique buyer wallet count ($\text{unique\_buyers} \ge N_{\text{min}}$, default 3).
   * Rejects trade bursts originating from a single wallet churning or circular wash-trading.
   * Requires positive net capital deployment ($\Delta V_{\text{SOL}} \ge I_{\text{min}}$, default $0.5\text{ SOL}$).

---

## 9. Raydium Migration Sniping & Graduation Momentum Engine (FEAT-05)

When a token bonding curve achieves full capitalization ($\ge 85\text{ SOL}$ in real reserves, $\sim\$69\text{k}$ market cap, or on-chain `complete == True`), the token graduates and migrates liquidity into a newly initialized Raydium AMM v4 liquidity pool (`675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8`).

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
      [ Anti-Rug Screening Filter ] ------> Creator Dumping & Concentration Check
                   | (Pass)
                   v
        [ Portfolio Risk Engine ] --------> Position Sizing & Drawdown Caps
                   | (Pass)
                   v
     [ Raydium SwapBaseIn Builder ] ------> Dynamic Tip + Priority Fees
                   |
                   v
      [ Jito MEV Private Bundle ] --------> Atomic Sub-Slot Inclusion
```

### Mathematical Formulation & AMM Invariant

Raydium AMM v4 operates under a constant-product AMM model with a standard trading fee ($0.25\%$, fee numerator $= 25$, denominator $= 10000$):

$$\Delta x_{\text{fee}} = \Delta x \times (1 - f) = \Delta x \times \frac{10000 - 25}{10000}$$

$$\Delta y = \frac{\Delta x_{\text{fee}} \times R_{\text{token}}}{R_{\text{SOL}} + \Delta x_{\text{fee}}}$$

Where:
* $R_{\text{SOL}}$: Seeded SOL reserve in Raydium vault ($\sim 80 - 85\text{ SOL}$).
* $R_{\text{token}}$: Seeded token reserve in Raydium coin vault ($\sim 200,000,000\text{ tokens}$).
* $\Delta y$: Expected token output before slippage.

### Execution Protection

1. **Pre-Migration Candidate Staging**: Tokens reaching $\ge 80.0\text{ SOL}$ in real reserves are actively staged in `GraduationEngine` to prime routing tables and pre-validate anti-rug profiles before pool initialization.
2. **Atomic Pool Initialization Extraction**: Solana transactions containing `Initialize2` are decoded into `RaydiumPoolKeys` within $<0.2\text{ms}$.
3. **Zero-Sandwich Bundle Routing**: Swap transactions (`SwapBaseIn`) are routed exclusively through private Jito MEV bundles with dynamic validator tips to prevent public mempool sandwich attacks.
4. **Automatic Stale Candidate Eviction**: Candidates with uninitialized pools automatically expire after an in-memory TTL ($1800\text{s}$) to avoid stale state accumulation.

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

1. **Proportional Position Sizing**:
   Scales bot allocation proportionally relative to the tracked wallet's trade size against their reference bankroll:

   $$\text{Entry SOL} = \min\left(\text{max\_pos\_sol},\, \text{max\_alloc}_{\text{wallet}},\, \text{base\_buy} \times S_{\text{factor}} \times \left(\frac{\text{trade}_{\text{SOL}}}{\text{bankroll}_{\text{ref}}}\right)\right)$$

   *Example*: With `base_buy = 0.02 SOL`, `scale_factor = 1.0`, `bankroll_ref = 10.0 SOL`, and the smart wallet executing a `5.0 SOL` buy (50% bankroll conviction), the bot automatically allocates `0.01 SOL`.

2. **Scaled (Conviction-Weighted) Sizing**:
   Scales trade allocation dynamically according to the tracked wallet's historical win rate:

   $$C_{\text{conviction}} = \max\left(0.50,\, \min\left(2.0,\, \frac{\text{win\_rate}}{0.50}\right)\right)$$
   $$\text{Entry SOL} = \min\left(\text{max\_pos\_sol},\, \text{max\_alloc}_{\text{wallet}},\, \text{base\_buy} \times S_{\text{factor}} \times C_{\text{conviction}}\right)$$

3. **Dynamic Performance & Risk Profiling**:
   Wallets in `WalletRegistry` update dynamic metrics after each closed trade outcome:

   $$\text{win\_rate}_{n+1} = \frac{W_n + \mathbb{I}(R > 0)}{n + 1}$$
   $$\overline{R}_{n+1} = \frac{n \cdot \overline{R}_n + R}{n + 1}$$

   *Drawdown Risk Penalization*: When a tracked wallet incurs a severe loss ($R < -20\%$), its risk score is automatically penalized ($+5.0$), disqualifying reckless traders from triggering mirrored executions.

4. **Safety & De-Risking Controls**:
   * **Pre-Trade Anti-Rug Screening**: All copy-trade buys must satisfy developer launch limits, creator supply caps, and holder Gini distribution metrics before order dispatch.
   * **Mirrored Sell Synchronization**: When a smart money wallet liquidates or trims a position in a token held by the bot, `copy_trading_mirror_sells` immediately triggers position exits to capture gains before liquidity evaporates.

### Strategy Preset Matrix

| Configuration Parameter | Conservative Preset | Balanced Preset | Aggressive Preset |
| :--- | :---: | :---: | :---: |
| `enable_copy_trading` | `True` | `True` | `True` |
| `copy_trading_sizing_mode` | `"proportional"` | `"proportional"` | `"proportional"` |
| `copy_trading_scale_factor` | `0.8x` | `1.0x` | `1.5x` |
| `copy_trading_min_wallet_win_rate` | `70%` ($0.70$) | `60%` ($0.60$) | `50%` ($0.50$) |
| `copy_trading_max_wallet_risk_score` | `30.0` | `40.0` | `50.0` |
| `copy_trading_mirror_sells` | `True` | `True` | `True` |
| `copy_trading_require_anti_rug_screen` | `True` | `True` | `True` |

---

## 11. Multi-RPC Dynamic Load Balancing & Latency-Based Failover Engine (FEAT-08)

High-frequency algorithmic trading on Solana demands sub-millisecond execution and 99.99% network reliability. If a primary RPC provider encounters rate limiting (HTTP 429), timeouts, or node degradation, transaction routing must fail over instantly without dropping trade entries or stop-loss executions.

`pumpfun-trading` implements an asynchronous, native in-process Multi-RPC Connection Pool (`RpcConnectionPool` in `pumpfun_trading/infra/rpc_pool.py`) that continuously monitors rolling endpoint latencies, enforces dynamic circuit breaking, routes read queries to the fastest healthy node, and concurrently broadcasts signed transactions across all operational RPC providers.

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

1. **Rolling Latency Percentile Profiling**:
   Each `RpcEndpoint` maintains a bounded sliding window of response latencies ($N = 100$ samples) using `collections.deque`:

   $$\text{Mean Latency: } \mu = \frac{1}{N} \sum_{i=1}^N L_i$$
   $$p_{50} = \text{Quantile}(L, 0.50), \quad p_{95} = \text{Quantile}(L, 0.95), \quad p_{99} = \text{Quantile}(L, 0.99)$$

2. **Weighted Routing Score Equation**:
   Routing scores determine the optimal candidate for state read queries (`getLatestBlockhash`, `getBalance`, `getTokenAccountsByOwner`), where lower scores indicate higher routing preference:

   $$\text{Score} = \frac{p_{50}}{\max(0.1, W)} + \text{Penalty}_{\text{state}}$$

   Where:
   * $W$: Configured endpoint weight multiplier (default $1.0$).
   * $\text{Penalty}_{\text{HEALTHY}} = 0.0\text{ ms}$.
   * $\text{Penalty}_{\text{DEGRADED}} = 50.0\text{ ms} + (\text{consecutive\_failures} \times 25.0\text{ ms})$.
   * $\text{Penalty}_{\text{HALF\_OPEN}} = 200.0\text{ ms}$.
   * $\text{Penalty}_{\text{OPEN}} = 10,000.0\text{ ms}$.

3. **Dynamic Circuit Breaker State Machine**:
   * **`HEALTHY`**: Normal state. Receives prioritized read routing and transaction broadcasts.
   * **`DEGRADED`**: Encountered $1$ or $2$ consecutive errors. Routed with score penalties.
   * **`OPEN`**: Tripped immediately upon receiving HTTP 429 rate limit or reaching failure threshold ($\ge 3$ consecutive errors). No queries are dispatched to this endpoint during the cooldown window ($60\text{s}$).
   * **`HALF_OPEN`**: Automatically transitioned once `cooldown_until` expires. A single probe query is dispatched: success restores the node to `HEALTHY`; failure resets cooldown and returns the state to `OPEN`.

4. **Multi-RPC Concurrent Transaction Broadcast**:
   When dispatching critical buy/sell orders, transactions are broadcast concurrently across up to `broadcast_concurrency` healthy nodes via asynchronous scatter-gather (`asyncio.as_completed`). The bot returns confirmation immediately upon receiving the first valid transaction signature from any RPC provider.

### Strategy Preset Matrix

| Configuration Parameter | Conservative Preset | Balanced Preset | Aggressive Preset |
| :--- | :---: | :---: | :---: |
| `enable_rpc_pool` | `True` | `True` | `True` |
| `rpc_pool_health_check_interval_seconds` | `30.0s` | `30.0s` | `20.0s` |
| `rpc_pool_circuit_breaker_threshold` | `2` failures | `3` failures | `4` failures |
| `rpc_pool_circuit_breaker_cooldown_seconds` | `90.0s` | `60.0s` | `45.0s` |
| `rpc_pool_broadcast_concurrency` | `2` RPCs | `3` RPCs | `4` RPCs |

---

## 12. Modular SOLID Architecture & Decoupled Bot Runtime (FEAT-12)

To maintain high execution velocity, testability, and reliability as trading capabilities expand, the core bot runtime is structured according to strict SOLID and Single Responsibility (SRP) principles:

```
                            +-----------------------------------------+
                            |       TradingBot Orchestrator Facade     |
                            |       (Lifecycle & Background Loops)    |
                            +-----------------------------------------+
                                   |           |           |
               +-------------------+           |           +-------------------+
               |                               |                               |
               v                               v                               v
    +--------------------+           +--------------------+           +--------------------+
    |   EventRouter      |           |  PositionManager   |           |  TokenEnricher     |
    | (Geyser/WS Stream  |           | (Lot Tracking, TP  |           | (Metadata, Creator |
    | Event Ingestion)   |           | Tiers & Trailing)  |           | Profiling, Gini)   |
    +--------------------+           +--------------------+           +--------------------+
               |                               |                               |
               +-------------------------------+-------------------------------+
                                               |
                                               v
                                    +--------------------+
                                    |   OrderExecutor    |
                                    | (Buy/Sell Dispatch,|
                                    | Jito Tips, Locks)  |
                                    +--------------------+
                                       /              \
                                      /                \
                                     v                  v
                            +----------------+  +-------------------+
                            | OrderLiquidator|  | StatusPersistence |
                            | (Emergency Panic|  | (Snapshots &      |
                            | Batch Exits)   |  | Audit Records)    |
                            +----------------+  +-------------------+
```

### Architectural Subsystems & Responsibilities

1. **`PositionManager` (`pumpfun_trading/bot/position_manager.py`)**:
   Encapsulates position records, entry market capitalization basis, peak price tracking, dynamic trailing stop triggers, multi-tier partial take-profit state scaling, and state snapshot dictionary serialization/restoration.

2. **`OrderExecutor` & `OrderLiquidator` (`pumpfun_trading/execution/`)**:
   Manages single-token buy/sell order dispatching, Jito MEV tip transfers, slippage retries, per-token execution locks (`_trade_locks`), direct RPC fallbacks, and multi-position concurrent emergency liquidation.

3. **`TokenEnricher` (`pumpfun_trading/bot/enrichment.py`)**:
   Coordinates off-chain token metadata lookups, developer wallet profiling (24h deployment counts), top holder concentration Gini coefficient calculations, and thread-safe screening verdict caching (`ScreeningCache`).

4. **`EventRouter` (`pumpfun_trading/bot/event_router.py`)**:
   Decouples transport networking (Yellowstone Geyser gRPC streams and WebSocket connections) from core strategy execution, dispatching incoming updates to registered signal handlers.

5. **`StatusPersistenceManager` & `AlertDispatcher` (`pumpfun_trading/bot/`)**:
   Isolates disk I/O (`bot_status.json`), append-only audit event logging, and multi-channel webhook notifications (Discord, Slack, Telegram) with resilient non-blocking error handling.

---

## 13. Dynamic Volatility-Aware Slippage & Adaptive Priority Fee Engine (FEAT-23)

Static price slippage bounds and fixed priority fees create two severe vulnerabilities in microcap trading:
1. **Under-protection during high-volatility bursts**: Fixed tight slippage causes transaction drops during fast market dumps or explosive parabolic breakouts.
2. **MEV sandwich exploitation during calm regimes**: Wide static slippage exposes normal entries to toxic sandwich front-running and execution leakage.

### Mathematical Formulation

1. **Instantaneous Price Velocity ($\Delta P / \Delta t$)**:
   $$\text{Price Velocity: } v = \frac{P_{t_1} - P_{t_0}}{\max(10^{-4}, t_1 - t_0)}$$

2. **Rolling Volatility ($\sigma_{\text{vol}}$)**:
   $$\sigma_{\text{vol}} = \sqrt{\frac{1}{N} \sum_{i=1}^N (r_i - \overline{r})^2}, \quad \text{where } r_i = \frac{P_i - P_{i-1}}{P_{i-1}}$$

3. **Reserve Depth Consumption & Price Impact**:
   $$\text{Depth Consumption: } \frac{\Delta x}{x_{\text{virtual}}}, \quad \text{Price Impact: } \Delta P_{\text{impact}} = \frac{P_{\text{exec}} - P_{\text{spot}}}{P_{\text{spot}}}$$

4. **Dynamic Slippage Equation ($S_{\text{dynamic}}$)**:
   $$S_{\text{dynamic}} = \operatorname{clamp}\left(\left(S_{\text{base}} + \alpha \cdot \sigma_{\text{vol}} \times 10^4 + \beta \cdot \Delta P_{\text{impact}} \times 10^4\right) \times M_{\text{urgency}},\; S_{\text{min}},\; S_{\text{max}}\right)$$

### Urgency Tiers & Compute Budget Scaling

| Urgency Tier | Trigger Context | Compute Unit Limit | Compute Price Multiplier | Jito Tip (Lamports) | Max Slippage Cap |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `NORMAL_ENTRY` | Standard screening entry | $200,000$ | $1.0\text{x}$ ($50\text{k}$ µLamports) | $100,000$ | $500\text{ BPS}$ |
| `HIGH_CONVICTION` | High Z-score breakout | $250,000$ | $1.5\text{x}$ ($75\text{k}$ µLamports) | $150,000$ | $500\text{ BPS}$ |
| `GRADUATION_SNIPE` | Terminal curve / Raydium pool | $300,000$ | $2.5\text{x}$ ($125\text{k}$ µLamports) | $250,000$ | $800\text{ BPS}$ |
| `EMERGENCY_EXIT` | Stop-loss / panic liquidation | $400,000$ | $4.0\text{x}$ ($200\text{k}$ µLamports) | $400,000$ | $5000\text{ BPS}$ |

---

## 14. Opportunistic Capital Rotation & High-Conviction Displacement (FEAT-24)

When `max_active_positions` or `max_total_exposure_sol` is saturated, standard bots reject new entry signals, trapping capital in stagnant or flat-moving bonding curves while 95th+ percentile breakout candidates are missed.

### Expected Value (EV) Scoring Model

Active positions and incoming breakout candidates are continuously evaluated by `PositionEvEvaluator`:

$$\text{EV} = w_z \cdot Z_{\text{norm}} + w_{\text{inflow}} \cdot \text{Inflow}_{\text{norm}} + w_p \cdot \text{PnL}_{\text{norm}} - w_{\text{stag}} \cdot \text{Stagnation}$$

Where:
* $Z_{\text{norm}} = \operatorname{clamp}(Z_{\text{score}} / 5.0, -0.4, 1.0)$
* $\text{Inflow}_{\text{norm}} = \operatorname{clamp}(\text{NetInflow} / 5.0, -0.2, 1.0)$
* $\text{PnL}_{\text{norm}} = \operatorname{clamp}(P / P_0 - 1.0, -1.0, 3.0)$
* $\text{Stagnation} = \min\left(1.0, \frac{\Delta t_{\text{flat}}}{\text{timeout}_{\text{stagnant}}}\right)$ (when $|P/P_0 - 1.0| < 0.05$)

### Frictional Hurdle Displacement Condition

A candidate breakout displaces the weakest active holding if and only if:
1. The weakest holding has exceeded `min_hold_before_displacement_seconds` ($45\text{s}$).
2. Candidate conviction meets `displacement_min_conviction_percentile` ($\ge 0.95$).
3. The net Expected Value delta exceeds total round-trip transaction friction:

$$\text{EV}_{\text{candidate}} - \text{EV}_{\text{weakest}} > 2 \times \text{Slippage}_{\text{base}} + \text{HurdleMargin}_{\text{displacement}}$$

Upon validation, the engine atomically executes a priority market sell on the weakest asset and immediately dispatches the buy order for the candidate breakout.

---

## 15. Predictive Graduation Acceleration & Liquidity Harvesting (FEAT-25)

Bonding curves approaching Raydium graduation ($\sim 85\text{ SOL}$ reserves / $\$69\text{k}$ market cap) experience an exponential price acceleration phase followed by high post-migration volatility.

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
   * **Moonbag Retained (40% residual)**: Rides into Raydium pool seeding, protected by post-migration trailing stops.
