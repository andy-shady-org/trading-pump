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
