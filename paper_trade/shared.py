import json
import os
from pathlib import Path

import pandas as pd
import numpy as np
import pytz
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "parameter" / "parameter.json"
WORKER_STATE_PATH = ROOT / "paper_trade" / "runtime_state.json"
EXECUTOR_STATE_PATH = ROOT / "paper_trade" / "executor_state.json"
HCM_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    STRATEGY = json.load(f)["strategy"]

RSI_PERIOD = int(STRATEGY["rsi_period"])
RSI_OVERSOLD = float(STRATEGY["rsi_oversold"])
RSI_OVERBOUGHT = float(STRATEGY["rsi_overbought"])
RSI_DEEP_LONG = float(STRATEGY["rsi_deep_long"])
RSI_DEEP_SHORT = float(STRATEGY["rsi_deep_short"])
MIN_BARS_DEEP = int(STRATEGY["min_bars_deep"])
ATR_PERIOD = int(STRATEGY["atr_period"])
ADX_PERIOD = int(STRATEGY.get("adx_period", 14))
ADX_THRESHOLD = float(STRATEGY["adx_threshold"])
TP1_ATR_MULT = float(STRATEGY["tp1_atr_mult"])
SL_ATR_MULT = float(STRATEGY["sl_atr_mult"])
EMA_FAST_PERIOD = int(STRATEGY.get("ema_fast_period", 9))
SCALP_RSI_PERIOD = int(STRATEGY.get("scalp_rsi_period", 7))
SCALP_ATR_PERIOD = int(STRATEGY.get("scalp_atr_period", 7))
SCALP_ADX_PERIOD = int(STRATEGY.get("scalp_adx_period", 7))
SCALP_ADX_THRESHOLD = float(STRATEGY.get("scalp_adx_threshold", 15.0))
SCALP_RSI_NORMAL_LOW = float(STRATEGY.get("scalp_rsi_normal_low", 30.0))
SCALP_RSI_NORMAL_HIGH = float(STRATEGY.get("scalp_rsi_normal_high", 70.0))
SCALP_TP_ATR_MULT = float(STRATEGY.get("scalp_tp_atr_mult", 2.0))
SCALP_SL_ATR_MULT = float(STRATEGY.get("scalp_sl_atr_mult", 2.0))
SCALP_PROFIT_LOCK_ATR_MULT = float(STRATEGY.get("scalp_profit_lock_atr_mult", 0.2))
SCALP_PROFIT_LOCK_FROM_BAR = int(STRATEGY.get("scalp_profit_lock_from_bar", 3))
SCALP_MAX_HOLD_BARS = int(STRATEGY.get("scalp_max_holding_bars", 6))
SCALP_CONTRACTS = int(STRATEGY.get("scalp_contracts", 2))
CONTRACTS = int(STRATEGY["contracts"])
SYMBOL = os.getenv("PAPER_SYMBOL", "HNXDS:VN30F2605")


def atomic_write_json(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp_path, path)


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return None


def compute_rsi(closes, period):
    if len(closes) < 2:
        return None

    use_period = min(period, len(closes) - 1)
    price_series = pd.Series([float(value) for value in closes], dtype="float64")
    delta = price_series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean()

    if avg_loss.iloc[-1] == 0 and avg_gain.iloc[-1] == 0:
        return 50.0
    if avg_loss.iloc[-1] == 0:
        return 100.0

    rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
    return float(100 - (100 / (1 + rs)))


def compute_atr(highs, lows, closes, period):
    if len(closes) < 2:
        return None

    use_period = min(period, len(closes) - 1)
    high_series = pd.Series([float(value) for value in highs], dtype="float64")
    low_series = pd.Series([float(value) for value in lows], dtype="float64")
    close_series = pd.Series([float(value) for value in closes], dtype="float64")
    prev_close = close_series.shift(1)
    tr = pd.concat(
        [
            high_series - low_series,
            (high_series - prev_close).abs(),
            (low_series - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean()
    return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None


def compute_adx(highs, lows, closes, period):
    if len(closes) < 2:
        return None

    use_period = min(period, len(closes) - 1)
    high_series = pd.Series([float(value) for value in highs], dtype="float64")
    low_series = pd.Series([float(value) for value in lows], dtype="float64")
    close_series = pd.Series([float(value) for value in closes], dtype="float64")

    up_move = high_series.diff()
    down_move = -low_series.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high_series.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high_series.index,
        dtype=float,
    )

    prev_close = close_series.shift(1)
    tr = pd.concat(
        [
            high_series - low_series,
            (high_series - prev_close).abs(),
            (low_series - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean()
    if atr.iloc[-1] == 0 or pd.isna(atr.iloc[-1]):
        return None

    plus_di = 100 * (plus_dm.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], np.nan)
    adx = dx.ewm(alpha=1 / use_period, min_periods=1, adjust=False).mean()
    return float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else None


def compute_ema(closes, period):
    if not closes:
        return None
    price_series = pd.Series([float(value) for value in closes], dtype="float64")
    ema = price_series.ewm(span=max(1, period), min_periods=1, adjust=False).mean()
    return float(ema.iloc[-1]) if pd.notna(ema.iloc[-1]) else None


def count_deep_bars(rsi_history, threshold, direction, lookback=6):
    window = rsi_history[-lookback:]
    count = 0
    for value in window:
        if value is None:
            continue
        if direction == "below" and value <= threshold:
            count += 1
        elif direction == "above" and value >= threshold:
            count += 1
    return count


def get_recovery_signal(rsi_history, current_price=None, reference_price=None, lookback=7):
    if len(rsi_history) < 1:
        return {
            "long_signal": False,
            "short_signal": False,
            "deep_oversold_bars": 0,
            "deep_overbought_bars": 0,
            "prev_rsi": None,
            "curr_rsi": None,
        }

    prev_rsi = rsi_history[-2] if len(rsi_history) >= 2 else None
    curr_rsi = rsi_history[-1]
    if curr_rsi is None:
        return {
            "long_signal": False,
            "short_signal": False,
            "deep_oversold_bars": 0,
            "deep_overbought_bars": 0,
            "prev_rsi": prev_rsi,
            "curr_rsi": curr_rsi,
        }

    deep_oversold_bars = count_deep_bars(rsi_history[:-1], RSI_DEEP_LONG, "below", lookback=lookback)
    deep_overbought_bars = count_deep_bars(rsi_history[:-1], RSI_DEEP_SHORT, "above", lookback=lookback)
    price_up = (
        current_price is not None
        and reference_price is not None
        and float(current_price) > float(reference_price)
    )
    price_down = (
        current_price is not None
        and reference_price is not None
        and float(current_price) < float(reference_price)
    )
    long_signal = deep_oversold_bars >= MIN_BARS_DEEP and price_down
    short_signal = deep_overbought_bars >= MIN_BARS_DEEP and price_up
    return {
        "long_signal": long_signal,
        "short_signal": short_signal,
        "deep_oversold_bars": deep_oversold_bars,
        "deep_overbought_bars": deep_overbought_bars,
        "prev_rsi": prev_rsi,
        "curr_rsi": curr_rsi,
    }


def get_normal_zone_scalp_signal(rsi_history, close_price, ema_value):
    if len(rsi_history) < 8:
        return {
            "normal_long_signal": False,
            "normal_short_signal": False,
            "rsi_slope": None,
        }

    prev_rsi = rsi_history[-2]
    curr_rsi = rsi_history[-1]
    base_rsi = rsi_history[-8]
    if (
        prev_rsi is None
        or curr_rsi is None
        or base_rsi is None
        or close_price is None
        or ema_value is None
    ):
        return {
            "normal_long_signal": False,
            "normal_short_signal": False,
            "rsi_slope": None,
        }

    rsi_slope = curr_rsi - base_rsi
    in_normal_zone = (
        SCALP_RSI_NORMAL_LOW <= prev_rsi <= SCALP_RSI_NORMAL_HIGH
        and SCALP_RSI_NORMAL_LOW <= curr_rsi <= SCALP_RSI_NORMAL_HIGH
    )
    normal_long_signal = (
        in_normal_zone
        and prev_rsi <= 50.0
        and curr_rsi > 50.0
        and rsi_slope > 0
        and float(close_price) > float(ema_value)
    )
    normal_short_signal = (
        in_normal_zone
        and prev_rsi >= 50.0
        and curr_rsi < 50.0
        and rsi_slope < 0
        and float(close_price) < float(ema_value)
    )
    return {
        "normal_long_signal": normal_long_signal,
        "normal_short_signal": normal_short_signal,
        "rsi_slope": float(rsi_slope),
    }
