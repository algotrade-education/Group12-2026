#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

from shared import (
    ADX_PERIOD,
    ATR_PERIOD,
    CONTRACTS,
    EMA_FAST_PERIOD,
    HCM_TZ,
    MAX_HOLDING_BARS,
    POINT_VALUE,
    RSI_PERIOD,
    SCALP_ADX_PERIOD,
    SCALP_ATR_PERIOD,
    SCALP_RSI_PERIOD,
    build_signal,
    get_normal_zone_scalp_signal,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_PATH = ROOT / "data" / "vn30f1m_1min_from_tick.csv"
DEFAULT_TRADES_PATH = ROOT / "backtest" / "trades_main49_bar.csv"
DEFAULT_EQUITY_PATH = ROOT / "backtest" / "equity_main49_bar.csv"

TRADE_COLUMNS = [
    "entry_time",
    "exit_time",
    "side",
    "qty",
    "entry_price",
    "exit_price",
    "exit_reason",
    "gross_points",
    "pnl",
    "bars_held",
    "signal_time",
]

STAGNATION_FLUSH_BARS = 5


@dataclass
class Position:
    side: int
    qty: int
    entry_price: float
    tp: float | None
    sl: float | None
    entry_time: str
    signal_time: str
    holding_bars: int = 0


def is_trading_time(dt_value) -> bool:
    ts = pd.Timestamp(dt_value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(HCM_TZ)
    else:
        ts = ts.tz_convert(HCM_TZ)
    current = ts.time()
    return (
        (time(9, 0) <= current <= time(11, 30))
        or (time(13, 0) <= current <= time(14, 45))
    )


def parse_bound(value: str | None):
    if not value:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(HCM_TZ)
    return ts.tz_convert(HCM_TZ)


def clean_number(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def vector_rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    rsi = rsi.mask((avg_gain > 0) & (avg_loss == 0), 100.0)
    rsi.iloc[0] = np.nan
    return rsi


def true_range(highs: pd.Series, lows: pd.Series, closes: pd.Series) -> pd.Series:
    prev_close = closes.shift(1)
    return pd.concat(
        [
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def vector_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int) -> pd.Series:
    tr = true_range(highs, lows, closes)
    atr = tr.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
    atr.iloc[0] = np.nan
    return atr


def vector_adx(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int) -> pd.Series:
    up_move = highs.diff()
    down_move = -lows.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=highs.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=highs.index,
        dtype=float,
    )
    tr = true_range(highs, lows, closes)
    atr = tr.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=1, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=1, adjust=False).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
    adx.iloc[0] = np.nan
    return adx


def add_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    closes = bars["close"].astype(float)
    highs = bars["high"].astype(float)
    lows = bars["low"].astype(float)
    bars["rsi"] = vector_rsi(closes, RSI_PERIOD)
    bars["atr"] = vector_atr(highs, lows, closes, ATR_PERIOD)
    bars["adx"] = vector_adx(highs, lows, closes, ADX_PERIOD)
    bars["ema_fast"] = closes.ewm(span=max(1, EMA_FAST_PERIOD), min_periods=1, adjust=False).mean()
    bars["scalp_rsi"] = vector_rsi(closes, SCALP_RSI_PERIOD)
    bars["scalp_atr"] = vector_atr(highs, lows, closes, SCALP_ATR_PERIOD)
    bars["scalp_adx"] = vector_adx(highs, lows, closes, SCALP_ADX_PERIOD)
    bars["time_text"] = bars["datetime"].map(lambda value: value.isoformat())
    return bars


def load_bars(path: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    required = ["datetime", "open", "high", "low", "close"]
    bars = pd.read_csv(path)
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    bars = bars.copy()
    bars["datetime"] = pd.to_datetime(bars["datetime"], errors="coerce")
    if bars["datetime"].isna().any():
        bad_count = int(bars["datetime"].isna().sum())
        raise ValueError(f"Found {bad_count} rows with invalid datetime")
    if bars["datetime"].dt.tz is None:
        bars["datetime"] = bars["datetime"].dt.tz_localize(HCM_TZ)
    else:
        bars["datetime"] = bars["datetime"].dt.tz_convert(HCM_TZ)

    for column in ["open", "high", "low", "close"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    if "volume" in bars.columns:
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce").fillna(0)
    bars = bars.dropna(subset=required).sort_values("datetime").drop_duplicates("datetime", keep="last")

    start_ts = parse_bound(start)
    end_ts = parse_bound(end)
    if start_ts is not None:
        bars = bars[bars["datetime"] >= start_ts]
    if end_ts is not None:
        bars = bars[bars["datetime"] <= end_ts]

    bars = bars[bars["datetime"].map(is_trading_time)].reset_index(drop=True)
    return add_indicators(bars)


class BarBacktester:
    def __init__(
        self,
        bars: pd.DataFrame,
        max_contracts: int,
        point_value: int,
        max_holding_bars: int,
        use_sl: bool,
    ):
        self.bars = bars
        self.max_contracts = max(1, int(max_contracts))
        self.point_value = int(point_value)
        self.max_holding_bars = max(0, int(max_holding_bars))
        self.use_sl = bool(use_sl)
        self.position: Position | None = None
        self.pending_signal: dict | None = None
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.realized_pnl = 0.0
        self.closes: list[float] = []
        self.rsi_history: list[float | None] = []
        self.scalp_rsi_history: list[float | None] = []
        self._prev_state_snapshot: dict | None = None
        self._stagnation_bars = 0

    def run(self):
        for bar in self.bars.itertuples(index=False):
            if self.pending_signal is not None:
                self.execute_signal(self.pending_signal)
                self.pending_signal = None

            exited = self.check_price_exit(bar)
            if not exited:
                self.check_holding_exit(bar)
            if self.position is not None:
                self.check_stagnation_flush(bar)

            self.record_equity(bar)
            signal = self.build_bar_signal(bar)
            self.pending_signal = self.to_pending_signal(signal, bar)

        if self.position is not None and not self.bars.empty:
            last_bar = next(self.bars.tail(1).itertuples(index=False))
            self.close_position(float(last_bar.close), last_bar.time_text, "end_of_data")
            if self.equity_curve:
                self.equity_curve[-1].update(self.current_equity_row(last_bar))

    def build_bar_signal(self, bar) -> dict:
        close_price = float(bar.close)
        self.closes.append(close_price)
        rsi_value = clean_number(bar.rsi)
        adx_value = clean_number(bar.adx)
        ema_fast_value = clean_number(bar.ema_fast)
        scalp_rsi_value = clean_number(bar.scalp_rsi)
        scalp_atr_value = clean_number(bar.scalp_atr)
        self.rsi_history.append(rsi_value)
        self.scalp_rsi_history.append(scalp_rsi_value)

        scalp_signal = get_normal_zone_scalp_signal(
            self.scalp_rsi_history,
            close_price,
            ema_fast_value,
        )
        reference_close = self.closes[-2] if len(self.closes) >= 2 else None
        signal, adx_ok = build_signal(
            close_price,
            reference_close,
            self.rsi_history,
            adx_value,
            scalp_signal,
            scalp_atr_value,
        )
        signal["time"] = bar.time_text
        signal["adx_ok"] = adx_ok
        return signal

    def to_pending_signal(self, signal: dict, bar) -> dict | None:
        side = signal.get("side")
        qty = int(signal.get("qty", 0) or 0)
        if side not in {"BUY", "SELL"} or qty <= 0:
            return None
        pending = dict(signal)
        pending["qty"] = qty
        pending["fill_price"] = float(bar.close)
        pending["fill_time"] = bar.time_text
        pending["fill_model"] = "previous_close"
        return pending

    def execute_signal(self, signal: dict) -> None:
        side = 1 if signal["side"] == "BUY" else -1
        qty = min(int(signal["qty"]), self.max_contracts)
        fill_price = float(signal["fill_price"])
        fill_time = signal["fill_time"]
        tp, sl = self.rebase_levels(signal, fill_price)

        if self.position is None:
            self.open_position(side, qty, fill_price, tp, sl, fill_time, signal["time"])
            return

        if self.position.side == side:
            available_qty = self.max_contracts - self.position.qty
            if available_qty <= 0:
                return
            self.add_position(min(qty, available_qty), fill_price, tp, sl)
            return

        unrealized_points = (fill_price - self.position.entry_price) * self.position.side
        if unrealized_points <= 0:
            return

        self.close_position(fill_price, fill_time, "reverse")
        self.open_position(side, qty, fill_price, tp, sl, fill_time, signal["time"])

    def rebase_levels(self, signal: dict, fill_price: float) -> tuple[float | None, float | None]:
        entry_price = signal.get("entry_price")
        tp = signal.get("tp")
        sl = signal.get("sl")
        if entry_price is None:
            return clean_number(tp), clean_number(sl)
        base_entry = float(entry_price)
        rebased_tp = None if tp is None else fill_price + (float(tp) - base_entry)
        rebased_sl = None if sl is None else fill_price + (float(sl) - base_entry)
        return rebased_tp, rebased_sl

    def open_position(
        self,
        side: int,
        qty: int,
        entry_price: float,
        tp: float | None,
        sl: float | None,
        entry_time: str,
        signal_time: str,
    ) -> None:
        if qty <= 0:
            return
        self.position = Position(
            side=side,
            qty=qty,
            entry_price=entry_price,
            tp=tp,
            sl=sl,
            entry_time=entry_time,
            signal_time=signal_time,
        )

    def add_position(self, qty: int, entry_price: float, tp: float | None, sl: float | None) -> None:
        if self.position is None or qty <= 0:
            return
        old_qty = self.position.qty
        new_qty = old_qty + qty
        self.position.entry_price = ((self.position.entry_price * old_qty) + (entry_price * qty)) / new_qty
        if self.position.tp is not None and tp is not None:
            self.position.tp = ((self.position.tp * old_qty) + (tp * qty)) / new_qty
        elif tp is not None:
            self.position.tp = tp
        if self.position.sl is not None and sl is not None:
            self.position.sl = ((self.position.sl * old_qty) + (sl * qty)) / new_qty
        elif sl is not None:
            self.position.sl = sl
        self.position.qty = new_qty

    def check_price_exit(self, bar) -> bool:
        if self.position is None:
            return False

        high = float(bar.high)
        low = float(bar.low)
        exit_price = None
        exit_reason = None

        if self.position.side > 0:
            tp_hit = self.position.tp is not None and high >= self.position.tp
            sl_hit = self.use_sl and self.position.sl is not None and low <= self.position.sl
        else:
            tp_hit = self.position.tp is not None and low <= self.position.tp
            sl_hit = self.use_sl and self.position.sl is not None and high >= self.position.sl

        if sl_hit:
            exit_price = float(self.position.sl)
            exit_reason = "sl"
        elif tp_hit:
            exit_price = float(self.position.tp)
            exit_reason = "tp"

        if exit_price is None:
            return False

        self.close_position(exit_price, bar.time_text, exit_reason)
        return True

    def check_stagnation_flush(self, bar) -> bool:
        if self.position is None:
            self._prev_state_snapshot = None
            self._stagnation_bars = 0
            return False

        snapshot = self.current_equity_row(bar)
        if self._prev_state_snapshot is None:
            self._stagnation_bars = 1
            self._prev_state_snapshot = snapshot
            return False

        same_state = (
            snapshot["inventory"] == self._prev_state_snapshot["inventory"]
            and snapshot["equity"] == self._prev_state_snapshot["equity"]
            and snapshot["realized_pnl"] == self._prev_state_snapshot["realized_pnl"]
            and snapshot["unrealized_pnl"] == self._prev_state_snapshot["unrealized_pnl"]
        )
        self._stagnation_bars = (self._stagnation_bars + 1) if same_state else 1
        self._prev_state_snapshot = snapshot

        if self._stagnation_bars >= STAGNATION_FLUSH_BARS:
            self.close_position(float(bar.close), bar.time_text, "stagnation_flush")
            self._prev_state_snapshot = None
            self._stagnation_bars = 0
            return True
        return False

    def check_holding_exit(self, bar) -> None:
        if self.position is None:
            return
        self.position.holding_bars += 1
        if self.max_holding_bars and self.position.holding_bars >= self.max_holding_bars:
            self.close_position(float(bar.close), bar.time_text, "max_hold")

    def close_position(self, exit_price: float, exit_time: str, exit_reason: str) -> None:
        if self.position is None:
            return
        position = self.position
        gross_points = (exit_price - position.entry_price) * position.side
        pnl = gross_points * position.qty * self.point_value
        self.realized_pnl += pnl
        self.trades.append(
            {
                "entry_time": position.entry_time,
                "exit_time": exit_time,
                "side": "LONG" if position.side > 0 else "SHORT",
                "qty": position.qty,
                "entry_price": position.entry_price,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "gross_points": gross_points,
                "pnl": pnl,
                "bars_held": position.holding_bars,
                "signal_time": position.signal_time,
            }
        )
        self.position = None
        self._prev_state_snapshot = None
        self._stagnation_bars = 0

    def current_equity_row(self, bar) -> dict:
        close_price = float(bar.close)
        unrealized_pnl = 0.0
        inventory = 0
        position_entry = None
        position_tp = None
        position_sl = None
        bars_held = 0
        if self.position is not None:
            inventory = self.position.side * self.position.qty
            position_entry = self.position.entry_price
            position_tp = self.position.tp
            position_sl = self.position.sl
            bars_held = self.position.holding_bars
            unrealized_points = (close_price - self.position.entry_price) * self.position.side
            unrealized_pnl = unrealized_points * self.position.qty * self.point_value
        return {
            "time": bar.time_text,
            "close": close_price,
            "inventory": inventory,
            "position_entry_price": position_entry,
            "position_tp": position_tp,
            "position_sl": position_sl,
            "bars_held": bars_held,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity": self.realized_pnl + unrealized_pnl,
        }

    def record_equity(self, bar) -> None:
        self.equity_curve.append(self.current_equity_row(bar))

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades, columns=TRADE_COLUMNS)

    def equity_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_curve)

    def summary(self) -> dict:
        trades = self.trades_frame()
        equity = self.equity_frame()
        net_pnl = float(trades["pnl"].sum()) if not trades.empty else 0.0
        wins = int((trades["pnl"] > 0).sum()) if not trades.empty else 0
        losses = int((trades["pnl"] < 0).sum()) if not trades.empty else 0
        win_rate = (wins / len(trades) * 100.0) if len(trades) else 0.0
        max_drawdown = 0.0
        if not equity.empty:
            running_max = equity["equity"].cummax()
            drawdown = equity["equity"] - running_max
            max_drawdown = float(drawdown.min())
        return {
            "bars": len(self.bars),
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "net_points": net_pnl / self.point_value if self.point_value else net_pnl,
            "net_pnl": net_pnl,
            "max_drawdown": max_drawdown,
        }


def parse_args():
    parser = argparse.ArgumentParser(description="Run main49 on OHLC bars with previous-close fills.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="CSV with datetime, open, high, low, close.")
    parser.add_argument("--start", help="Optional inclusive start datetime.")
    parser.add_argument("--end", help="Optional inclusive end datetime.")
    parser.add_argument("--trades-output", type=Path, default=DEFAULT_TRADES_PATH)
    parser.add_argument("--equity-output", type=Path, default=DEFAULT_EQUITY_PATH)
    parser.add_argument("--max-contracts", type=int, default=CONTRACTS)
    parser.add_argument("--point-value", type=int, default=POINT_VALUE)
    parser.add_argument("--max-holding-bars", type=int, default=MAX_HOLDING_BARS)
    parser.add_argument("--no-max-hold", action="store_true", help="Disable max holding bar exits.")
    parser.add_argument("--use-sl", action="store_true", help="Use the signal stop-loss level in bar simulation.")
    return parser.parse_args()


def main():
    args = parse_args()
    max_holding_bars = 0 if args.no_max_hold else args.max_holding_bars
    bars = load_bars(args.data, start=args.start, end=args.end)
    if bars.empty:
        raise SystemExit("No bars found after filtering.")

    engine = BarBacktester(
        bars,
        max_contracts=args.max_contracts,
        point_value=args.point_value,
        max_holding_bars=max_holding_bars,
        use_sl=args.use_sl,
    )
    engine.run()

    args.trades_output.parent.mkdir(parents=True, exist_ok=True)
    args.equity_output.parent.mkdir(parents=True, exist_ok=True)
    engine.trades_frame().to_csv(args.trades_output, index=False)
    engine.equity_frame().to_csv(args.equity_output, index=False)

    summary = engine.summary()
    print(f"Bars: {summary['bars']}")
    print(f"Trades: {summary['trades']} wins={summary['wins']} losses={summary['losses']} win_rate={summary['win_rate']:.2f}%")
    print(f"Net: {summary['net_points']:.2f} points, pnl={summary['net_pnl']:.0f}")
    print(f"Max drawdown: {summary['max_drawdown']:.0f}")
    print(f"Trades CSV: {args.trades_output}")
    print(f"Equity CSV: {args.equity_output}")


if __name__ == "__main__":
    main()
