#!/usr/bin/env python3
"""
Evaluate backtest outputs from equity/trades CSV files.

Metrics are aligned with example/evaluator.py and extended with basic trade stats.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EQUITY_PATH = ROOT / "backtest" / "equity_main49_bar.csv"
DEFAULT_TRADES_PATH = ROOT / "backtest" / "trades_main49_bar.csv"
DEFAULT_PARAM_PATH = ROOT / "parameter" / "parameter.json"

RISK_FREE_RATE_ANNUAL = 0.06
TRADING_DAYS_PER_YEAR = 252
TRADING_MINUTES_PER_DAY = 255  # 9:00-11:30 and 13:00-14:45
BAR_PERIODS_PER_YEAR = TRADING_DAYS_PER_YEAR * TRADING_MINUTES_PER_DAY


def compute_sharpe_ratio(
    period_returns: pd.Series,
    periods_per_year: float = BAR_PERIODS_PER_YEAR,
    risk_free_annual: float = RISK_FREE_RATE_ANNUAL,
) -> float:
    if periods_per_year <= 0:
        periods_per_year = BAR_PERIODS_PER_YEAR
    if period_returns.empty:
        return 0.0

    risk_free_per_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = period_returns - risk_free_per_period
    if excess.std() == 0 or np.isnan(excess.std()):
        return 0.0
    return float((excess.mean() / excess.std()) * np.sqrt(periods_per_year))


def compute_sortino_ratio(
    period_returns: pd.Series,
    periods_per_year: float = BAR_PERIODS_PER_YEAR,
    risk_free_annual: float = RISK_FREE_RATE_ANNUAL,
) -> float:
    if periods_per_year <= 0:
        periods_per_year = BAR_PERIODS_PER_YEAR
    if period_returns.empty:
        return 0.0

    risk_free_per_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = period_returns - risk_free_per_period
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0 or np.isnan(downside.std()):
        return 0.0
    return float((excess.mean() / downside.std()) * np.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return float(drawdown.min()) if not drawdown.empty else 0.0


def compute_metrics(
    equity_curve: pd.Series,
    period_returns: pd.Series,
    initial_asset: float,
    periods_per_year: float,
) -> dict:
    if equity_curve.empty:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "hpr_pct": 0.0,
            "monthly_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "periods_per_year": periods_per_year,
        }

    final_asset = float(equity_curve.iloc[-1])
    hpr = (final_asset - initial_asset) / initial_asset if initial_asset != 0 else 0.0

    n_periods = len(equity_curve)
    n_years = n_periods / periods_per_year if n_periods > 0 and periods_per_year > 0 else 1.0

    if n_years > 0 and hpr > -1:
        annual_return = (1 + hpr) ** (1 / n_years) - 1
    else:
        annual_return = hpr
    monthly_return = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0.0

    return {
        "sharpe_ratio": compute_sharpe_ratio(period_returns, periods_per_year=periods_per_year),
        "sortino_ratio": compute_sortino_ratio(period_returns, periods_per_year=periods_per_year),
        "max_drawdown": compute_max_drawdown(equity_curve),
        "hpr_pct": hpr * 100,
        "monthly_return_pct": monthly_return * 100,
        "annual_return_pct": annual_return * 100,
        "periods_per_year": periods_per_year,
    }


def load_equity(path: Path, initial_asset: float) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    equity = pd.read_csv(path)
    if "equity" not in equity.columns:
        raise ValueError(f"Missing 'equity' column in {path}")
    if "time" not in equity.columns:
        raise ValueError(f"Missing 'time' column in {path}")
    equity = equity.copy()
    equity["time"] = pd.to_datetime(equity["time"], errors="coerce")
    equity["equity"] = pd.to_numeric(equity["equity"], errors="coerce")
    equity = equity.dropna(subset=["time", "equity"]).reset_index(drop=True)

    account_curve = equity["equity"] + initial_asset
    period_returns = account_curve.pct_change().fillna(0.0)
    return equity, account_curve, period_returns


def load_trades(path: Path) -> pd.DataFrame:
    trades = pd.read_csv(path)
    if "pnl" not in trades.columns:
        return pd.DataFrame()
    trades = trades.copy()
    for time_col in ["entry_time", "exit_time", "signal_time"]:
        if time_col in trades.columns:
            trades[time_col] = pd.to_datetime(trades[time_col], errors="coerce")
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce")
    trades["qty"] = pd.to_numeric(trades.get("qty"), errors="coerce")
    trades["bars_held"] = pd.to_numeric(trades.get("bars_held"), errors="coerce")
    return trades.dropna(subset=["pnl"])


def summarize_trades(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "avg_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_bars_held": 0.0,
        }

    wins = int((trades["pnl"] > 0).sum())
    losses = int((trades["pnl"] < 0).sum())
    gross_profit = float(trades.loc[trades["pnl"] > 0, "pnl"].sum())
    gross_loss = float(-trades.loc[trades["pnl"] < 0, "pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    return {
        "total_trades": int(len(trades)),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": (wins / len(trades)) * 100 if len(trades) else 0.0,
        "avg_pnl": float(trades["pnl"].mean()),
        "profit_factor": float(profit_factor),
        "avg_bars_held": float(trades["bars_held"].mean()) if "bars_held" in trades.columns else 0.0,
    }


def filter_equity_by_range(equity: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> pd.DataFrame:
    scoped = equity
    time_date = scoped["time"].dt.date
    if start is not None:
        scoped = scoped[time_date >= start.date()]
        time_date = scoped["time"].dt.date
    if end is not None:
        scoped = scoped[time_date <= end.date()]
    return scoped.reset_index(drop=True)


def filter_trades_by_range(trades: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> pd.DataFrame:
    if trades.empty or "exit_time" not in trades.columns:
        return trades
    scoped = trades.copy()
    scoped = scoped.dropna(subset=["exit_time"])
    exit_date = scoped["exit_time"].dt.date
    if start is not None:
        scoped = scoped[exit_date >= start.date()]
        exit_date = scoped["exit_time"].dt.date
    if end is not None:
        scoped = scoped[exit_date <= end.date()]
    return scoped.reset_index(drop=True)


def evaluate_window(
    name: str,
    equity_window: pd.DataFrame,
    trades_window: pd.DataFrame,
    initial_asset: float,
    periods_per_year: float,
) -> tuple[dict, dict]:
    if equity_window.empty:
        empty_metric = {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "hpr_pct": 0.0,
            "monthly_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "periods_per_year": periods_per_year,
        }
        return empty_metric, summarize_trades(trades_window)

    account_curve = equity_window["equity"] + initial_asset
    period_returns = account_curve.pct_change().fillna(0.0)
    window_initial_asset = float(account_curve.iloc[0]) if not account_curve.empty else initial_asset
    metric = compute_metrics(
        equity_curve=account_curve,
        period_returns=period_returns,
        initial_asset=window_initial_asset,
        periods_per_year=periods_per_year,
    )
    return metric, summarize_trades(trades_window)


def print_report_block(title: str, metric: dict, trade_stat: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"Sharpe Ratio:        {metric['sharpe_ratio']:.4f}")
    print(f"Sortino Ratio:       {metric['sortino_ratio']:.4f}")
    print(f"Max Drawdown:        {metric['max_drawdown'] * 100:.2f}%")
    print(f"HPR:                 {metric['hpr_pct']:.2f}%")
    print(f"Monthly Return:      {metric['monthly_return_pct']:.2f}%")
    print(f"Annual Return:       {metric['annual_return_pct']:.2f}%")
    print(f"Periods/Year:        {metric['periods_per_year']:.0f}")
    print("--- Trade Statistics ---")
    print(f"Total Trades:        {trade_stat['total_trades']}")
    print(f"Wins / Losses:       {trade_stat['wins']} / {trade_stat['losses']}")
    print(f"Win Rate:            {trade_stat['win_rate_pct']:.2f}%")
    print(f"Average PnL:         {trade_stat['avg_pnl']:.2f}")
    print(f"Profit Factor:       {trade_stat['profit_factor']:.4f}")
    print(f"Average Bars Held:   {trade_stat['avg_bars_held']:.2f}")


def resolve_split_date(split_date: str | None, param_file: Path) -> pd.Timestamp:
    if split_date:
        return pd.Timestamp(split_date)
    if not param_file.exists():
        raise ValueError(f"Split date not provided and param file not found: {param_file}")

    with param_file.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    raw_split = payload.get("split_date")
    if not raw_split:
        raise ValueError(f"'split_date' not found in {param_file}")
    return pd.Timestamp(raw_split)


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate backtest equity/trades CSV outputs.")
    parser.add_argument("--equity", type=Path, default=DEFAULT_EQUITY_PATH, help="Path to equity CSV.")
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES_PATH, help="Path to trades CSV.")
    parser.add_argument("--initial-asset", type=float, default=400_000_000.0, help="Initial account asset.")
    parser.add_argument(
        "--periods-per-year",
        type=float,
        default=BAR_PERIODS_PER_YEAR,
        help="Return periods per year for annualization (default: VN futures 1-minute bars).",
    )
    parser.add_argument(
        "--in-start",
        type=str,
        default="2024-01-02",
        help="In-sample start date (inclusive).",
    )
    parser.add_argument(
        "--split-date",
        type=str,
        default=None,
        help="Out-of-sample start date. If omitted, read from --param-file split_date.",
    )
    parser.add_argument(
        "--param-file",
        type=Path,
        default=DEFAULT_PARAM_PATH,
        help="JSON parameter file containing split_date.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    equity, account_curve, period_returns = load_equity(args.equity, initial_asset=args.initial_asset)
    trades = load_trades(args.trades)
    split_ts = resolve_split_date(args.split_date, args.param_file)
    in_start_ts = pd.Timestamp(args.in_start)
    in_end_ts = split_ts - pd.Timedelta(days=1)

    metric_all = compute_metrics(
        equity_curve=account_curve,
        period_returns=period_returns,
        initial_asset=args.initial_asset,
        periods_per_year=args.periods_per_year,
    )
    trade_stat_all = summarize_trades(trades)

    in_equity = filter_equity_by_range(equity, in_start_ts, in_end_ts)
    out_equity = filter_equity_by_range(equity, split_ts, None)
    in_trades = filter_trades_by_range(trades, in_start_ts, in_end_ts)
    out_trades = filter_trades_by_range(trades, split_ts, None)
    metric_in, trade_stat_in = evaluate_window(
        "IN_SAMPLE",
        in_equity,
        in_trades,
        initial_asset=args.initial_asset,
        periods_per_year=args.periods_per_year,
    )
    metric_out, trade_stat_out = evaluate_window(
        "OUT_SAMPLE",
        out_equity,
        out_trades,
        initial_asset=args.initial_asset,
        periods_per_year=args.periods_per_year,
    )

    print("============================================================")
    print("Evaluation windows")
    print(f"In-sample:  {in_start_ts.date()} -> {in_end_ts.date()}")
    print(f"Out-sample: {split_ts.date()} -> end")
    print("============================================================")

    print_report_block("FULL SAMPLE", metric_all, trade_stat_all)
    print_report_block("IN SAMPLE", metric_in, trade_stat_in)
    print_report_block("OUT SAMPLE", metric_out, trade_stat_out)


if __name__ == "__main__":
    main()
