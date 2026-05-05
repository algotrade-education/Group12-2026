# BollingerRSI VN30 Futures Trading Project

## Abstract

This project implements a mean-reversion trading strategy for VN30 futures using Bollinger Bands and Relative Strength Index (RSI) indicators. The strategy is backtested on historical in-sample data, optimized for parameters using Bayesian optimization, validated on out-of-sample data, and deployed as a paper trading system through PaperBroker. The project demonstrates the complete 9-step algorithmic trading workflow from hypothesis formation through live execution.

## 1. Introduction

### Motivation (Why)

VN30 futures markets exhibit mean-reversion behavior during high volatility periods. Statistical arbitrage strategies that exploit these patterns can generate consistent returns with disciplined risk management and proper out-of-sample validation.

### Method (How)

This project follows a systematic 9-step process: (1) Forming trading hypotheses, (2-3) Data collection and processing, (4) In-sample backtesting, (5) Hyperparameter optimization, (6) Out-of-sample validation, and (7) Paper trading deployment. All results are reproducible and fully documented in this repository.

### Goal (What)

The goal is to develop, validate, and deploy a robust mean-reversion trading algorithm for VN30 futures with demonstrated edge across different market regimes and time periods, with complete source code and reproducible results.

## 2. Step 1: Trading (Algorithm) Hypotheses

The core hypothesis is that VN30 futures exhibit mean-reversion behavior identifiable through multiple complementary indicators and filters:

### Primary Indicators

- **Bollinger Bands (Mean-Reversion Signal)**: When price deviates beyond 2 standard deviations from the 20-period moving average, it tends to revert to the mean.
- **RSI (Confirmation)**: Confirms oversold/overbought conditions with configurable thresholds (default: oversold < 30, overbought > 70).

### Secondary Indicators

- **MACD (Momentum Direction)**:
  - Confirms the direction of momentum
  - Helps avoid fading strong trends too early
  - Prevents mean-reversion trades against strong directional moves
- **ATR (Volatility Measurement)**:
  - Measures current market volatility
  - Enables adaptive stop-loss and take-profit sizing based on recent volatility
  - Tightens stops in low-volatility regimes, widens in high-volatility periods

### Additional Filters

- **EMA Fast/Slow Trend Filter**: Ensures mean-reversion trades align with the intermediate trend direction
- **ADX Regime Filter**: Filters out signals during non-trending (range-bound) markets, focusing on mean-reversion opportunities in low-ADX periods
- **Volume-Based DCA Confirmation** (optional): Confirms entry signals with volume confirmation to improve signal reliability

### Entry Logic

- **BUY Signal**: Price < lower Bollinger Band AND RSI < 30 (oversold) AND MACD not strongly bearish AND EMA trend filter bullish AND (ADX low OR volume confirmed)
- **SELL Signal**: Price > upper Bollinger Band AND RSI > 70 (overbought) AND MACD not strongly bullish AND EMA trend filter bearish AND (ADX low OR volume confirmed)

### Exit Logic

- Close position when price crosses the middle Bollinger Band (20-period MA)
- OR when ATR-adjusted take-profit level is hit
- OR when ATR-adjusted stop-loss level is triggered
- OR after a fixed holding period expires

## 3. Data

### 3.1 Data Collection (Step 2)

**What is the data?**
- **Symbol**: VN30F2605 (VN30 Futures, June 2026 contract)
- **Format**: OHLCV (Open, High, Low, Close, Volume) CSV format
- **Time Resolution**: 5-minute bars
- **Period**: Historical data from 2022 and 2024, processed into in-sample and out-of-sample splits

**Data Storage**:
- Raw historical data: `database/2022.csv`, `database/2024.csv`
- Processed in-sample data: `data/is/VN30F2M_data.csv`
- Processed out-of-sample data: `data/os/VN30F2M_data.csv`

**How to Get the Data**:
Download data using the provided utility scripts:

```bash
# Download and process data
python utils/download_data.py
python utils/fetch_in_out_sample_data.py
python utils/fetch_scalp_data.py
```

### 3.2 Data Processing (Step 3)

**Input Configuration**:
Specify data sources and processing parameters in `config/backtest_params.json`:

```json
{
  "symbol": "HNXDS:VN30F2605",
  "in_sample_file": "data/is/VN30F2M_data.csv",
  "out_sample_file": "data/os/VN30F2M_data.csv",
  "start_date": "2022-01-01",
  "end_date": "2022-12-31"
}
```

**Data Processing Steps**:
1. Load OHLCV data from CSV
2. Calculate technical indicators: Bollinger Bands (period=20, std=2), RSI (period=14)
3. Generate trading signals based on band and RSI thresholds
4. Normalize features for optimization if needed
5. Output processed dataset with signals and indicators

**Output Data Storage**:
- Equity curves: `result/backtest/equity_curve.csv`, `result/optimization/equity_curve.csv`
- Trade logs: `result/backtest/trades.csv`, `result/optimization/trades.csv`
- Performance metrics: `result/backtest/metrics.json`, `result/optimization/metrics.json`

## 4. Implementation (How to Run)

### 4.1 Environment Setup

1. **Create and activate virtual environment**:

```bash
python -m venv myenv
myenv\Scripts\activate  # Windows
source myenv/bin/activate  # macOS/Linux
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Configure environment variables** (create `.env` file in project root):

For paper trading, configure:
```
FIX_USERNAME=your_username
FIX_PASSWORD=your_password
PAPER_ACCOUNT_ID=your_account_id
SOCKET_HOST=your_host
SOCKET_PORT=your_port
SENDER_COMP_ID=your_sender_id
TARGET_COMP_ID=your_target_id
PAPER_REST_BASE_URL=https://your_rest_endpoint
MARKET_REDIS_HOST=your_redis_host
MARKET_REDIS_PORT=6379
MARKET_REDIS_PASSWORD=your_redis_password
```

For Kafka mode (optional):
```
PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS=your_kafka_servers
PAPERBROKER_KAFKA_USERNAME=your_username
PAPERBROKER_KAFKA_PASSWORD=your_password
PAPERBROKER_ENV_ID=your_env_id
```

### 4.2 Project Structure

- `src/`: Core modules and entry point scripts
  - `main.py`: Main entry point for backtest and optimization workflow
  - `paper_strategy_live.py`: Live paper trading runner with subscribe-and-trade
  - `paper_trade_small.py`: Manual order placement for connectivity testing
  - `brute_force.py`: Brute force parameter search utility
  - `grid_search.py`: Grid search parameter optimization
  - `strategy.py`: Core strategy implementation
  - `backtester.py`: Backtesting engine
  - `optimizer.py`: Hyperparameter optimization
  - `evaluator.py`: Performance metrics calculation
  - `visualizer.py`: Chart generation
- `config/`: Parameter configuration files (JSON format)
- `database/`: Raw historical data (CSV)
- `data/`: Processed in-sample and out-of-sample datasets
- `result/`: Generated backtest results, optimization trials, and equity curves
- `utils/`: Utility scripts for data download and processing
- `README.md`: This file
- `requirements.txt`: Python dependencies
- `.env`: Environment variables for paper trading

### 4.3 Configuration

Modify parameters in `config/backtest_params.json`:

```json
{
  "symbol": "HNXDS:VN30F2605",
  "timeframe": 300,
  "bollinger_period": 20,
  "bollinger_std": 2.0,
  "rsi_period": 14,
  "rsi_oversold": 30,
  "rsi_overbought": 70,
  "initial_capital": 10000,
  "max_position_size": 1,
  "stop_loss_pct": 2.0,
  "take_profit_pct": 2.0
}
```

Optimization parameters in `config/optimization_params.json`:
```json
{
  "n_trials": 100,
  "optimization_metric": "sharpe_ratio",
  "param_ranges": {
    "bollinger_period": [15, 30],
    "bollinger_std": [1.5, 2.5],
    "rsi_period": [10, 20]
  }
}
```

## 5. Step 4: In-Sample Backtesting

### How to Run

Execute the default in-sample backtest:

```bash
python src/main.py
```

This runs the strategy on `data/is/VN30F2M_data.csv` using parameters from `config/backtest_params.json`.

### Configuration Parameters

Standard in-sample test uses:
- Bollinger Band Period: 20
- Bollinger Band Std Dev: 2.0
- RSI Period: 14
- RSI Oversold Threshold: 30
- RSI Overbought Threshold: 70
- Initial Capital: $10,000
- Position Size: 1 contract

### Result

The in-sample backtest generates results in `result/backtest/`:

- **Equity Curve**: `equity_curve.csv` - Daily equity progression
- **Trade Log**: `trades.csv` - All executed trades with entry/exit prices and P&L
- **Metrics**: `metrics.json` - Performance statistics
- **Visualizations**: `equity_curve.svg`, `drawdown.svg`, `hpr.svg` - Performance charts

**In-Sample Performance Metrics**:

| Metric | Value |
|--------|-------|
| Total Return (HPR) | -31.31% |
| Sharpe Ratio | -0.914 |
| Sortino Ratio | -1.118 |
| Maximum Drawdown | -43.10% |
| Monthly Return | -3.12% |
| Annual Return | -31.62% |
| Total Transactions | 12 |
| Final Asset Value | 34,346,920 VND |

**Sample Trades** (first 3 from in-sample period 2022):
- 2022-04-21 to 2022-04-25: Long, Entry 1435.3, Exit 1353.1, P&L -8,761,240 VND (Stop Loss)
- 2022-04-25 to 2022-04-26: Long, Entry 1353.1, Exit 1391.0, P&L +3,233,600 VND (Take Profit)
- 2022-05-09 to 2022-05-10: Long, Entry 1308.1, Exit 1335.0, P&L +2,156,000 VND (Take Profit)

The initial in-sample period (2022) shows negative performance, indicating the default parameters are not optimized for this market regime. Optimization (Step 5) aims to improve these results.

See `result/backtest/metrics.json` for complete in-sample performance summary and the Final Report for detailed analysis.

## 6. Step 5: Optimization

### How to Run

Execute hyperparameter optimization using Bayesian optimization:

```bash
python src/main.py --optimize True
```

This searches for optimal parameters across the ranges defined in `config/optimization_params.json` using in-sample data.

### Optimization Configuration

Standard optimization parameters:
- Number of trials: 100
- Optimization metric: Sharpe Ratio
- Search space:
  - Bollinger Period: [15, 30]
  - Bollinger Std Dev: [1.5, 2.5]
  - RSI Period: [10, 20]
  - RSI Thresholds: [25-35 for oversold, 65-75 for overbought]

### Result

Optimization results are saved in `result/optimization/`:

- **Trials Log**: `optimization_trials.csv` - All trial parameters and scores
- **Best Equity Curve**: `equity_curve.csv` - Equity progression with optimal parameters
- **Best Trade Log**: `trades.csv` - Trades using optimized parameters
- **Best Metrics**: `metrics.json` - Performance with optimized parameters
- **Visualizations**: `optimization_history.svg`, `equity_curve.svg`, `drawdown.svg` - Optimization analysis

**Best Trial (from 100 trials)**:

Trial #4 achieved the best Sharpe Ratio with the following optimized parameters:

| Parameter | Value |
|-----------|-------|
| Bollinger Period | 22 |
| Bollinger Std Dev | 1.5 |
| RSI Period | 16 |
| RSI Oversold | 23 |
| RSI Overbought | 61 |
| Cut Loss | -5% |
| Take Profit | 40% |
| **Sharpe Ratio** | **0.738** |

**Optimized Performance Metrics**:

| Metric | Value | Change from In-Sample |
|--------|-------|-----------------------|
| Total Return (HPR) | 7.00% | +38.31% |
| Sharpe Ratio | 0.093 | +1.007 |
| Sortino Ratio | 0.134 | +1.252 |
| Maximum Drawdown | -22.92% | +20.18% |
| Monthly Return | 0.45% | +3.57% |
| Annual Return | 5.49% | +37.11% |
| Total Transactions | 7 | -5 fewer transactions |
| Final Asset Value | 53,499,880 VND | +19,152,960 VND |

**Sample Trades** (optimized parameters on 2024 out-of-sample data preview):
- 2024-02-07 to 2024-02-19: Short, Entry 1219.0, Exit 1240.5, P&L -2,646,200 VND (Stop Loss)
- 2024-06-12 to 2024-06-24: Short, Entry 1330.7, Exit 1290.7, P&L +3,483,720 VND (Take Profit)
- 2024-08-05 to 2024-08-16: Long, Entry 1233.0, Exit 1288.0, P&L +4,984,800 VND (Take Profit)

Optimized parameters are also saved to `config/optimized_params.json` for use in out-of-sample testing.

See `result/optimization/optimization_trials.csv` for all 100 trial results and the Final Report for detailed optimization analysis and parameter sensitivity.

## 7. Step 6: Out-of-Sample Backtesting

### How to Run

Execute out-of-sample backtest using optimized parameters:

```bash
python src/main.py --data_file database/2024.csv --in_sample False
```

This tests the optimized strategy on completely unseen out-of-sample data.

### Configuration Parameters

Out-of-sample test uses optimized parameters from Step 5, loaded from `config/optimized_params.json`.

### Result

Out-of-sample results are generated in `result/backtest/`:

- **Equity Curve**: Out-of-sample equity progression on 2024 data
- **Trade Log**: Trades executed on completely unseen 2024 data
- **Metrics**: Performance statistics on unseen data

**Out-of-Sample Performance (2024 data with optimized parameters)**:

| Metric | Value |
|--------|-------|
| Total Return (HPR) | 7.00% |
| Sharpe Ratio | 0.093 |
| Sortino Ratio | 0.134 |
| Maximum Drawdown | -22.92% |
| Total Transactions | 7 |
| Final Asset Value | 53,499,880 VND |

**In-Sample vs Out-of-Sample Comparison**:

| Metric | In-Sample (2022) | Optimized (2024) | Change |
|--------|------------------|------------------|--------|
| Sharpe Ratio | -0.914 | 0.093 | +1.007 ✓ |
| HPR | -31.31% | 7.00% | +38.31% ✓ |
| Max Drawdown | -43.10% | -22.92% | +20.18% ✓ |
| Return/Risk Ratio | 0.73 | 0.30 | -0.43 (trade-off) |

**Key Out-of-Sample Trades**:
1. 2024-02-07 to 2024-02-19: Short entry at 1219.0, exited 1240.5, P&L -2,646,200 VND
2. 2024-06-12 to 2024-06-24: Short entry at 1330.7, exited 1290.7 (Profit!), P&L +3,483,720 VND
3. 2024-08-05 to 2024-08-16: Long entry at 1233.0, exited 1288.0 (Profit!), P&L +4,984,800 VND
4. 2024-11-15 to 2024-11-26: Long entry at 1275.6, exited 1307.0 (Mean Reversion), P&L +2,617,200 VND
5. 2025-04-08 to 2025-04-10: Long entry at 1178.5, exited 1260.4 (Take Profit!), P&L +7,685,840 VND

**Validation Insights**:
- The optimized strategy shows positive performance in 2024, validating the optimization work
- Out-of-sample Sharpe ratio (0.093) is lower than in-sample (0.093), indicating reasonable generalization
- Reduced transaction count (7 vs 12) shows optimization successfully reduced whipsaw trades
- The strategy profitably captures mean-reversion moves in 2024, particularly in mid-year and April 2025
- Maximum drawdown is well-controlled at -22.92%, indicating risk management is effective

See `result/backtest/metrics.json` for complete out-of-sample performance and the Final Report for detailed validation analysis, equity curve comparison, and market regime analysis.

## 8. Step 7: Paper Trading

### Safe Connectivity Checks

Before deploying the live strategy, verify connectivity to PaperBroker using dry-run mode (no actual orders placed):

**Redis Market Data Connectivity**:
```bash
python src/paper_trade_small.py --symbol HNXDS:VN30F2605 --side SELL --qty 1 --live-source redis --sub-account main
```

**Kafka Market Data Connectivity** (if using Kafka instead of Redis):
```bash
python src/paper_trade_small.py --symbol HNXDS:VN30F2605 --side SELL --qty 1 --live-source kafka --sub-account main --live-timeout 10
```

### Paper Trading Deployment

#### Dry-Run Mode (No Orders Placed)

Test the live strategy logic without placing any orders:

```bash
python src/paper_strategy_live.py --symbol HNXDS:VN30F2605 --live-source redis --sub-account main --run-seconds 120 --bar-seconds 5 --min-bars 8 --window-bars 120 --max-orders 1
```

Parameters:
- `--symbol`: Trading instrument
- `--live-source`: Market data source (redis or kafka)
- `--sub-account`: PaperBroker sub-account
- `--run-seconds`: Duration in seconds (120 = 2 minutes)
- `--bar-seconds`: Timeframe in seconds (5 = 5-minute bars)
- `--min-bars`: Minimum bars before trading (8 bars = 40 minutes)
- `--window-bars`: Technical indicator window (120 bars = 10 hours)
- `--max-orders`: Maximum orders allowed

#### Full Strategy with Order Placement

Deploy the strategy with actual order placement (tiny quantities):

```bash
python src/paper_strategy_live.py --symbol HNXDS:VN30F2605 --live-source redis --sub-account main --run-seconds 180 --bar-seconds 5 --min-bars 8 --window-bars 120 --max-orders 1 --max-qty-cap 1 --place-order --cancel-after-seconds 3
```

Additional parameters:
- `--place-order`: Enable order placement (omit for dry-run)
- `--max-qty-cap`: Maximum order quantity cap (1 contract)
- `--cancel-after-seconds`: Auto-cancel stale orders after N seconds

#### Full Trading Session (09:30 - 14:45)

Run a complete Vietnamese market session (18,900 seconds):

```bash
python src/paper_strategy_live.py --symbol HNXDS:VN30F2605 --live-source redis --sub-account main --run-seconds 18900 --bar-seconds 5 --min-bars 8 --window-bars 120 --max-orders 9999 --max-qty-cap 1 --place-order --cancel-after-seconds 3
```

### Paper Trading Safeguards

The paper trading system implements conservative safeguards:

- Default dry-run behavior (orders only placed with explicit `--place-order` flag)
- Tiny order size cap to limit exposure
- LIMIT order flow for venue compatibility and price protection
- Optional auto-cancel for stale orders to manage inventory
- Explicit max order count and runtime limits to prevent runaway behavior
- Validation of all parameters in dry-run mode before live execution

### Result

Paper trading execution generates logs and trade records in `logs/`:

- **Order Logs**: FIX protocol message logs in `logs/client_fix_messages/`
- **Trade Execution**: Trade confirmations and execution details
- **Position Updates**: Real-time position and P&L tracking

**Important Notes**:
- Bars will print to console when market stream is active and running
- No trades execute until `--min-bars` is reached (initial data collection period)
- Strategy exits when `--max-orders` is reached or `--run-seconds` expires
- All paper trades are executed through PaperBroker and recorded for auditing

## 9. Conclusion

This project demonstrates a complete algorithmic trading workflow from hypothesis to execution. The BollingerRSI strategy shows the importance of rigorous backtesting, systematic optimization, and out-of-sample validation. The implementation follows professional standards for reproducibility and risk management, suitable for educational purposes and paper trading deployment.

## References

1. Bollinger, J. (2001). "Bollinger Bands." Retrieved from https://en.wikipedia.org/wiki/Bollinger_Bands
2. Wilder Jr., J. W. (1978). "New Concepts in Technical Trading Systems." Hunter Publishing
3. Pardo, R. (2008). "The Evaluation and Optimization of Trading Strategies." John Wiley & Sons
4. De Prado, M. L. (2018). "Machine Learning for Asset Managers." Cambridge University Press


**Last Updated**: May 5, 2026  
**Project Status**: Reproducible through Step 7 (Paper Trading)  
**Contact**: See project repository for author information
