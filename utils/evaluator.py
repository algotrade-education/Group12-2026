"""
Evaluation metrics for the trading strategy.

Computes standard performance metrics:
- Sharpe Ratio
- Sortino Ratio
- Maximum Drawdown (MDD)
- Holding Period Return (HPR)
- Monthly and Annual returns
"""

import numpy as np
import pandas as pd


# Risk-free rate: 6% per annum
RISK_FREE_RATE_ANNUAL = 0.06
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_DAILY = RISK_FREE_RATE_ANNUAL / TRADING_DAYS_PER_YEAR


def compute_sharpe_ratio(
    period_returns: pd.Series,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
    risk_free_annual: float = RISK_FREE_RATE_ANNUAL,
) -> float:
    """
    Compute annualized Sharpe Ratio.

    SR = (mean(R - Rf) / std(R - Rf)) * sqrt(periods_per_year)
    """
    if periods_per_year <= 0:
        periods_per_year = TRADING_DAYS_PER_YEAR

    risk_free_per_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = period_returns - risk_free_per_period
    if excess.std() == 0:
        return 0.0
    return float((excess.mean() / excess.std()) * np.sqrt(periods_per_year))


def compute_sortino_ratio(
    period_returns: pd.Series,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
    risk_free_annual: float = RISK_FREE_RATE_ANNUAL,
) -> float:
    """
    Compute annualized Sortino Ratio.

    Uses downside deviation (only negative excess returns).
    """
    if periods_per_year <= 0:
        periods_per_year = TRADING_DAYS_PER_YEAR

    risk_free_per_period = (1 + risk_free_annual) ** (1 / periods_per_year) - 1
    excess = period_returns - risk_free_per_period
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float((excess.mean() / downside.std()) * np.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Compute Maximum Drawdown (MDD).

    MDD = min((equity - peak) / peak)
    Returns a negative value.
    """
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return float(drawdown.min())


def compute_drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Compute the drawdown series from equity curve."""
    peak = equity_curve.cummax()
    return (equity_curve - peak) / peak


def compute_metrics(
    equity_curve: pd.Series,
    period_returns: pd.Series,
    initial_asset: float,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> dict:
    """
    Compute all evaluation metrics.

    Returns
    -------
    dict with keys:
        sharpe_ratio, sortino_ratio, max_drawdown,
        hpr_pct, monthly_return_pct, annual_return_pct
    """
    final_asset = equity_curve.iloc[-1]
    hpr = (final_asset - initial_asset) / initial_asset

    if periods_per_year <= 0:
        periods_per_year = TRADING_DAYS_PER_YEAR

    # Number of years represented by the equity periods.
    n_periods = len(equity_curve)
    n_years = n_periods / periods_per_year if n_periods > 0 else 1
    n_months = n_years * 12

    # Annualized return
    if n_years > 0 and hpr > -1:
        annual_return = (1 + hpr) ** (1 / n_years) - 1
    else:
        annual_return = hpr

    # Monthly return
    monthly_return = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0

    return {
        "sharpe_ratio": compute_sharpe_ratio(period_returns, periods_per_year=periods_per_year),
        "sortino_ratio": compute_sortino_ratio(period_returns, periods_per_year=periods_per_year),
        "max_drawdown": compute_max_drawdown(equity_curve),
        "hpr_pct": hpr * 100,
        "monthly_return_pct": monthly_return * 100,
        "annual_return_pct": annual_return * 100,
        "periods_per_year": periods_per_year,
    }
