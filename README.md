# Group 12: RSI/ADX Portfolio Strategy

**Authors:** 22125023 - Le Cong Quoc Han, 22125094 - Dao Ba Thanh

## Abstract

This repository implements and tests a VN30F-style intraday futures strategy using RSI, ADX, ATR, and EMA-based signals. The main trading hypothesis is that short-term RSI pressure can identify recovery, momentum, and scalp opportunities, while ADX separates stronger directional regimes from weaker/choppy regimes. ATR is used to size take-profit levels according to current volatility.

The project contains a bar-based backtest, a paper-trading implementation, and an evaluator for full-sample and in-sample/out-of-sample reporting.

## 1. Motivation

VN30 futures can move quickly inside short intraday windows. A  single-position strategy was too restrictive because it blocked additional same-side opportunities and could not represent the broker portfolio correctly. This project therefore uses a net-inventory view:

- Positive inventory means net long
- Negative inventory means net short
- Zero inventory means flat

This matches how the broker reports quantity and average price. The strategy can add to the same side, and it can reverse only when the current broker-side position PnL is positive.

## 2. Data

The current backtest uses 1-minute OHLC bars.

Required columns:

- `datetime`
- `open`
- `high`
- `low`
- `close`

Default data path:

```text
data/vn30f1m_1min_from_tick.csv
```

Although the default file was built from tick data, the current backtest uses the aggregated 1-minute bars. Therefore, entries are simulated from bar data, and TP/SL touches are approximated using each bar's high and low.

This creates an important difference between backtesting and live paper trading:

- Backtest input is bar-based.
- Live market input is tick-fed.
- Live indicators are updated from the current forming 1-minute bar.
- Live order prices can use the latest tick price instead of only the previous completed bar close.

This means the live strategy can react inside a minute, while the current backtest can only approximate what happened inside that minute.

## 3. Indicators

### RSI

RSI is the main signal indicator. The strategy uses period 7 because period 14 reacted too slowly for short VN30F intraday moves.

RSI is used in three ways:

- Recovery after repeated deep oversold/overbought bars
- Momentum when RSI pressure continues after leaving the normal area
- Normal-zone scalp signals around the RSI middle area

### ADX

ADX is a regime filter, not a direction indicator.

- `ADX >= 25`: stronger movement regime, so recovery and momentum signals are allowed
- `ADX < 25`: weaker/choppy regime, so only normal-zone scalp logic is used

### ATR

ATR measures current volatility and is used to size take-profit and stop-loss levels in the signal model. A fixed point target is too rigid because VN30F volatility changes during the day.

### EMA9

EMA9 is used as a local price-bias filter for normal-zone scalp signals. It prevents the scalp logic from relying only on RSI crosses without considering recent price direction.

## 4. Strategy Logic

Each bar or live update produces one candidate action: `BUY`, `SELL`, or no trade.

The strategy is not a pure RSI threshold system. RSI provides the pressure signal, ADX decides which signal family is allowed, ATR sizes the target, and EMA9 filters the normal-zone scalp case. This avoids treating all RSI values the same in both trending and choppy conditions.

In the backtest, these indicators are computed from completed 1-minute bars. In live paper trading, the worker receives tick updates and temporarily recomputes the latest RSI/ADX/ATR/EMA values using the current forming bar. This is why live signals can appear before the minute fully closes.

When `ADX >= threshold`, the priority is:

1. RSI recovery long
2. RSI recovery short
3. RSI momentum long
4. RSI momentum short
5. Normal-zone scalp sell
6. Normal-zone scalp buy

### 4.1 RSI recovery

Recovery logic is used after RSI has stayed deep for several recent bars. Instead of waiting for a slow RSI recross, the strategy uses current price movement against the previous close to react earlier.

- Recovery long: enough recent RSI bars are below `rsi_deep_long`, and current price is lower than the previous close.
- Recovery short: enough recent RSI bars are above `rsi_deep_short`, and current price is higher than the previous close.

The idea is that repeated deep RSI readings show pressure has become stretched. The current price condition is used as the entry trigger because waiting for the next completed RSI bar can be too late in fast VN30F moves.

### 4.2 RSI momentum

Momentum logic handles cases where RSI pressure is not reversing yet but is still strong enough to continue. It is checked after recovery because recovery events are considered more specific.

- Momentum long: previous RSI was in the normal zone, current RSI is not weakening, and enough recent bars have shown deep oversold pressure.
- Momentum short: previous RSI was in the normal zone, current RSI is not strengthening, and enough recent bars have shown deep overbought pressure.

This was added because some profitable moves do not appear as clean recovery patterns. They start as strong RSI pressure and continue before a visible reversal signal appears.

### 4.3 Normal-zone scalp

Normal-zone scalp is used when RSI is around the middle area rather than deeply oversold or overbought. It combines RSI slope, the RSI 50-line, and EMA9.

- `normal_long_signal`: RSI crosses upward through the middle area, RSI slope is positive, and price is above EMA9.
- `normal_short_signal`: RSI crosses downward through the middle area, RSI slope is negative, and price is below EMA9.

When `ADX < threshold`, recovery and momentum are skipped, and only normal-zone scalp logic is allowed.

The normal-zone scalp names are historical. The actual order mapping is:

- `normal_long_signal` places `SELL`
- `normal_short_signal` places `BUY`

This is intentional because the normal-zone scalp logic is treated as a short-term mean-reversion decision, not a trend-following decision.

### 4.4 Why priority matters

The code uses `if / elif / else` priority so only one signal is emitted per update. This is intentional. Recovery and momentum are treated as higher-conviction events than normal-zone scalp. The scalp logic is still available, but it should not override a deeper RSI regime signal when ADX says the market is moving strongly.

### 4.5 Where tick data is used in paper trading

The paper-trading code uses tick updates in `paper_trade/state_worker.py` and `paper_trade/executor.py`.

In `paper_trade/state_worker.py`:

- `on_market()` is called for each market-data update.
- `quote.latest_matched_price` becomes `latest_price`.
- The current forming 1-minute bar is updated tick by tick:
  - `high = max(current high, latest price)`
  - `low = min(current low, latest price)`
  - `close = latest price`
- Before the minute closes, temporary indicator values are recomputed from completed bars plus the current forming bar.
- `build_signal()` is called from this temporary live state.
- The latest signal and latest price are written to `paper_trade/runtime_state.json`.

In `paper_trade/executor.py`:

- The executor reads `paper_trade/runtime_state.json`.
- `latest_price` is saved as `latest_worker_price`.
- If a signal exists, order price is based on `latest_worker_price` when available.
- Broker-side inventory and PnL are synced separately from the server.

So in the paper-trading implementation, tick data is not a separate indicator. It is used to keep the current bar, live signal state, and order price closer to the live market than waiting only for the completed bar close.

## 5. Portfolio Logic

The strategy is portfolio-based instead of ticket-based.

Broker-side position is represented as net quantity and average price, not as separate independent orders. Therefore, the strategy also thinks in terms of net inventory:

- `inventory > 0`: net long
- `inventory < 0`: net short
- `inventory = 0`: flat

### 5.1 Flat inventory

When inventory is zero, a valid signal opens a new position:

- `BUY` signal opens long.
- `SELL` signal opens short.

The order quantity comes from the strategy signal and is capped by the configured maximum inventory / broker-side maximum placeable quantity.

### 5.2 Same-side signal

When the signal points in the same direction as the current inventory, the strategy can add to the position:

- Long inventory + `BUY` signal: add long, up to the inventory cap.
- Short inventory + `SELL` signal: add short, up to the inventory cap.

After adding, the position is treated as one net portfolio position. Average entry price and TP level are blended by quantity. This matches the broker view, where multiple buys or sells become one net position with average price.

### 5.3 Opposite-side signal

When the signal points against the current inventory, the strategy does not automatically flip. It checks current position PnL first:

- Long inventory + `SELL` signal: reverse only if current PnL is positive.
- Short inventory + `BUY` signal: reverse only if current PnL is positive.
- If PnL is zero or negative, the reverse is skipped.

This rule exists because noisy opposite signals can appear before the current position has had enough time to reach TP. Reversing every opposite signal would often close positions at a loss and increase churn.

### 5.4 Close-and-reverse sizing

A reverse order must both close the current inventory and open the new direction. For example, if the strategy is long 4 contracts and receives a valid `SELL` signal for 2 contracts with positive PnL, the reverse order sells 6 contracts:

- 4 contracts close the existing long.
- 2 contracts open a new short.

After the fill, broker inventory becomes short 2 contracts. This is why the executor uses server-side inventory and average price instead of trying to track old individual orders locally.

### 5.5 Why local order history is avoided

Earlier local order tracking could become stale after rejected, canceled, or partially filled orders. The current design relies on broker/server portfolio state for the important trading facts:

- current inventory
- average entry price
- current PnL
- maximum placeable quantity

Local state is still useful for indicators, bars, ATR, RSI, ADX, and runtime signal values, but it should not be the source of truth for position ownership.

## 6. Risk And Exit Model

The backtest supports TP exits and optional SL exits:

- Long TP: `entry_price + ATR * multiplier`
- Short TP: `entry_price - ATR * multiplier`
- Long SL: `entry_price - ATR * multiplier`
- Short SL: `entry_price + ATR * multiplier`

The live paper-trading executor uses broker-side inventory and manages a resting TP limit order. SL is not currently managed as a broker-side resting stop order. This difference is important: Paper-trading losses can be larger than the bar backtest if adverse moves are not actively stopped.

## 7. Configuration

Strategy parameters are stored in:

```text
parameter/backtesting_parameter_v49.json
```

Important fields:

- `rsi_period`
- `rsi_oversold`
- `rsi_overbought`
- `rsi_deep_long`
- `rsi_deep_short`
- `min_bars_deep`
- `atr_period`
- `adx_period`
- `adx_threshold`
- `tp1_atr_mult`
- `sl_atr_mult`
- `contracts`
- `point_value`
- `max_holding_bars`

The same file also contains `split_date`, used by the evaluator to separate in-sample and out-of-sample results.

## 8. How To Run

Create the environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the backtest:

```bash
python3 backtest/backtest.py
```

Run evaluation after generating the backtest CSVs:

```bash
python3 backtest/evaluator.py
```

Default outputs:

- `backtest/trades_main49_bar.csv`
- `backtest/equity_main49_bar.csv`

Run paper trading:

```bash
python3 paper_trade/state_worker.py
```

In a second terminal:

```bash
python3 paper_trade/executor.py
```

The paper-trading workflow needs both processes:

- `paper_trade/state_worker.py` receives market data, builds the forming bar, computes indicators, and writes `paper_trade/runtime_state.json`.
- `paper_trade/executor.py` reads the runtime state, syncs broker inventory/PnL, and places/cancels broker orders.

Paper trading requires broker and market-data environment variables to be configured before running.

## 9. Results And Interpretation

### 9.1 Backtest results

The evaluator was run with:

```bash
python3 backtest/evaluator.py
```

Evaluation windows:

- In-sample: `2024-01-02` -> `2025-12-31`
- Out-sample: `2026-01-01` -> `2026-02-27`

| Metric | Full Sample | In-sample | Out-of-sample |
|--------|------------:|----------:|--------------:|
| Sharpe Ratio | -1.2413 | -1.2044 | -1.6867 |
| Sortino Ratio | -1.5554 | -1.5030 | -2.3083 |
| Max Drawdown | -11.10% | -11.10% | -2.30% |
| HPR | -2.79% | -1.73% | -1.08% |
| Monthly Return | -0.11% | -0.07% | -0.66% |
| Annual Return | -1.34% | -0.89% | -7.65% |
| Total Trades | 20467 | 19216 | 1251 |
| Wins / Losses | 12760 / 7688 | 11968 / 7232 | 792 / 456 |
| Win Rate | 62.34% | 62.28% | 63.31% |
| Average PnL | -545.74 | -360.62 | -3389.31 |
| Profit Factor | 0.9934 | 0.9954 | 0.9746 |
| Average Bars Held | 5.59 | 5.55 | 6.09 |

The backtest has a win rate above 60%, but average PnL is negative and profit factor is below 1. This means the current parameter set wins frequently but loses more on losing trades than it earns on winning trades.

### 9.2 Paper-trading results

Paper-trading performance:

| Metric | Value |
|--------|------:|
| Sharpe Ratio | -3.14 |
| MDD | -1.46% |
| Information Ratio vs VNINDEX | -3.39 |
| Information Ratio vs VN30 | -3.16 |
| Sortino Ratio vs VNINDEX | -3.08 |
| Sortino Ratio vs VN30 | -2.74 |
| Gross Notional Turnover | 140.72x |
| Close Notional Turnover | 70.34x |
| Margin Usage | 35.18x |
| Round Trips | 174 |
| Avg Daily Gross Turnover | 3.43x |
| Avg Daily Close Turnover | 1.72x |
| Avg Daily Margin Usage | 0.86x |
| Avg Daily Round Trips | 4.24 |

Paper-trading results are worse than the backtest metrics. One important reason is that the live paper-trading version skipped active SL handling and used a TP-only exit model. This was intentional because we wanted to test whether holding inventory longer could allow price to recover instead of cutting positions too early. However, this led to tail risk: two large losses on the last trading day dominated the final paper-trading result and pulled down the whole performance summary.

## 10. Limitations

The backtest uses 1-minute OHLC bars, not full tick replay. Therefore, it cannot know the exact order of events inside one candle.

Live execution is also different from the backtest because it depends on broker fills, open orders, inventory, PnL, and rejection/cancel timing. This means live paper-trading results should not be expected to match bar-backtest results exactly.

The current live version does not use an active broker-side SL order. This keeps the strategy simple, but it also creates tail risk when price moves strongly against the position.

## 11. Conclusion

This project tests a portfolio-based RSI/ADX strategy for VN30F-style intraday futures. The result is not yet profitable: The backtest has a win rate above 60% but negative average PnL, and paper trading is weaker because the TP-only live version exposed the account to large tail losses. The main takeaway is that the signal idea can produce frequent winning trades, but risk control and tick-level execution testing must be improved before the strategy is reliable.
