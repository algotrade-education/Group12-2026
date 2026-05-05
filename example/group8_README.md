# Predictive High-Frequency Market Making: VN30F1M Strategy Evolution & Live Execution Engine

**Authors:** Group 8 (Dương Trung Hiếu - 22125027 | Dương Ngọc Quang Khiêm - 22125037)

## Abstract
This project presents a state-of-the-art Predictive High-Frequency Market Making strategy and Live Execution Engine tailored for the VN30 Index Futures (VN30F1M). Evolving from a theoretical continuous-time Avellaneda-Stoikov (A-S) model, this project implements rigorous microstructure engineering to transition into a live, event-driven paper trading environment. By abandoning symmetric quoting in favor of state-conditional, asymmetric policies and integrating decoupled asynchronous microservices, the engine effectively filters toxic flow. The system achieves a rigorous balance between theoretical modeling and quantitative software engineering, yielding highly deployable out-of-sample edge with tightly controlled tail risk.

## Introduction & Strategy Evolution
Pure market-making models, such as the theoretical Avellaneda-Stoikov baseline, assume smooth diffusion and touch-fills. When applied to discrete, real-world snapshots, this symmetric quoting approach suffers catastrophic failure (up to -97% Maximum Drawdown) due to adverse selection and momentum toxicity.

### Brief Comparison: Teacher's Model vs. Pure Avellaneda-Stoikov
* **Spread control:** Pure A-S uses volatility in the spread ($\sigma^2$), which swings wildly tick-to-tick; the teacher's model fixes a hard step (e.g., 1.8 points), avoiding over-tight or unfillable quotes.
* **Inventory penalty:** Pure A-S skews with $q\gamma\sigma^2(T-t)$, which can explode near session end; the teacher's model uses a stable scalar like $q\times 0.02$, keeping quotes in range.
* **Fill assumptions:** Pure A-S required strict matching; the teacher's backtester uses touch-fills (e.g., `bid >= price`), which is optimistic and boosts backtest PnL.

| Metric | Our Market Making (Complete) | Teacher's Market Making |
| --- | --- | --- |
| Profit | 222,000,000 VND | 40,100,000 VND |
| Sharpe | 3.77 | 0.082 |
| Maximum Drawdown | -2.9% | -10.29% |
| Total Trades | 21,898 | N/A |

To resolve this, our architecture completely overhauled the stochastic model:
1. **Unit Normalization & Strict Matching:** Time is discretized to polling intervals, volatility is mapped to contract points, and touch-at-quote fills are strictly rejected to reflect real-world queue-priority friction.
2. **Asymmetric Quoting:** We shifted to a predictive, state-conditional policy. The algorithm selectively quotes to capture spreads in sideways markets and aggressively fades directional spikes, explicitly optimizing for a risk-adjusted score: `Sharpe × (1 - |MDD|)`.

## Core System Architecture

### 1. Predictive Gating & Circuit Breakers
Instead of symmetric quoting, the engine relies on a rapid-tick feature pipeline consuming RSI, ATR, ADX, and EMAs:
* **RSI-Driven Asymmetry:** Accumulation regimes (RSI < 30) trigger Bid-only quotes; Distribution regimes (RSI > 70) trigger Ask-only quotes.
* **The "Freight Train" Defense:** A combined trend direction (EMA12/EMA26 crossover) and strength (ADX > 25) circuit breaker permanently disables counter-trend fading during strong directional momentum.

### 2. Dynamic Risk Management
* **ATR-Scaled Spread:** Fixed spreads are replaced by a dynamic multiplier (`ATR_14 * multiplier`), preserving adverse-selection buffers during high volatility.
* **Stop-Loss Flush:** If adverse movement exceeds 10 points, a full liquidation is triggered. The engine pays the exchange fee to exit toxic inventory before non-linear escalation.
* **Hard Inventory Caps & EOD Flattening:** State constraints instantly censor quoting sides when max capacity is reached. All positions are force-closed at 14:45 ATC to neutralize overnight gap risk.

### 3. Live Execution Architecture & Microservices
The system was engineered for real-time, event-driven performance:
* **Decoupled Async Flow:** Continuous stream processing via `KafkaMarketDataClient` handles atomic `QuoteSnapshot` events. Execution is routed via a `PaperBrokerClient` over a FIX 4.4 TCP socket.
* **O(1) Memory Deque:** The `on_quote` callback strictly appends to a bounded deque, preventing GIL stalls and unblocking consumer threads.
* **Microstructure Hardening:** Includes *Flatten-Before-Flip* reversal rules and explicit `threading.RLock()` mechanisms to protect in-flight orders from fast-market spam. Mathematical *State Healing* reconstructions prevent null-pointer crashes if FIX messages drop.

### 4. Catastrophic Risk Control
* **Real-Time Fee Deductions:** The engine mathematically deducts 40,000 VND (0.4 index points) instantly per contract on every fill, ensuring equity logic is purely liquidatable NAV.
* **The Global Kill Switch:** Dynamic internal equity monitoring. If the 400M VND threshold is breached, the system halts permanently, cancels all resting orders, and flattens inventory, requiring a human reboot.

## Data Processing
* **Target Contract:** VN30 Index Futures (VN30F1M).
* **Format:** Intraday tick data encompassing `close`, `price`, `best-bid`, `best-ask`, and `spread`.
* **Rollover Management:** Primary and subsequent month contracts are mapped dynamically for clean expiration rollovers. Missing ticks are managed via forward-filling (`ffill()`) to maintain data integrity.

## Implementation (How to Run)

### Environment Setup
Ensure Python, Kafka, and the required data science libraries are installed:
```bash
pip install pandas numpy matplotlib
```
*(Note: Live execution requires the appropriate Kafka Zookeeper environment and a valid FIX 4.4 routing endpoint).*

### Running the Engine
To execute the historical simulation and backtest engine:
```bash
python backtesting.py
```
To launch the live event-driven paper trading microservices:
```bash
python paper_trading.py
```

## Performance & Results

The final optimized model underwent rigorous testing in a **16-month Out-of-Sample evaluation block**, proving exceptional drawdown protection and edge preservation. 

### Final Out-of-Sample Metrics
* **Out-of-Sample Sharpe:** 3.77
* **Maximum Drawdown:** -2.9% (Achieved via rigorous risk geometry)
* **Absolute Profit:** 222,000,000 VND
* **Total Trades:** 21,898 execution round-trips

### Paper Trading Data & Figures
* **Analytics data:** [result/papertrading/analytics_history.csv](result/papertrading/analytics_history.csv)

**Price Path**
![Paper trading price](result/papertrading/price.svg)

**Inventory Over Time**
![Paper trading inventory](result/papertrading/inventory.svg)

**Holdings Period Return (HPR)**
![Paper trading HPR](result/papertrading/hpr.svg)

**Drawdown Curve**
![Paper trading drawdown](result/papertrading/drawdown.svg)

## Conclusion

This project successfully bridges the gap between theoretical quantitative finance and practical software engineering. While the initial Avellaneda-Stoikov baseline failed under real-world microstructure frictions, the evolution into a Hybrid, Asymmetric system protected by strict **Predictive Gating**, **Dynamic ATR Spreads**, and **Catastrophic Kill Switches** created a highly resilient market maker. The resulting execution engine deliberately manages toxic flow and prioritizes algorithmic survivability, yielding a highly stable, positive expectation system.