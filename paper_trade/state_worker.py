#!/usr/bin/env python3
import asyncio
import os
from datetime import datetime, time

from paperbroker.market_data import KafkaMarketDataClient

from shared import (
    ADX_THRESHOLD,
    ADX_PERIOD,
    ATR_PERIOD,
    CONTRACTS,
    EMA_FAST_PERIOD,
    HCM_TZ,
    MIN_BARS_DEEP,
    RSI_PERIOD,
    RSI_DEEP_LONG,
    RSI_DEEP_SHORT,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    SCALP_CONTRACTS,
    SCALP_ADX_PERIOD,
    SCALP_ATR_PERIOD,
    SCALP_RSI_PERIOD,
    SCALP_SL_ATR_MULT,
    SCALP_TP_ATR_MULT,
    SL_ATR_MULT,
    SYMBOL,
    TP1_ATR_MULT,
    WORKER_STATE_PATH,
    count_deep_bars,
    compute_adx,
    atomic_write_json,
    compute_atr,
    compute_ema,
    compute_rsi,
    get_normal_zone_scalp_signal,
    get_recovery_signal,
    load_json,
)


def is_trading_time(dt_value: datetime) -> bool:
    current = dt_value.astimezone(HCM_TZ).time()
    return (
        (time(9, 0) <= current <= time(11, 30))
        or (time(13, 0) <= current <= time(14, 45))
    )


class StateWorker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.latest_price = None
        self.current_bar = None
        self.last_bar_time = None
        self.closes = []
        self.highs = []
        self.lows = []
        self.rsi_history = []
        self.atr_history = []
        self.adx_history = []
        self.ema_fast_history = []
        self.scalp_rsi_history = []
        self.scalp_atr_history = []
        self.scalp_adx_history = []
        self.last_closed_bar = None
        self.signal = {
            "side": None,
            "qty": 0,
            "entry_price": None,
            "tp": None,
            "sl": None,
            "time": None,
        }

    def load_state(self):
        state = load_json(WORKER_STATE_PATH)
        if not state:
            print("[WORKER] No saved state found")
            return

        self.latest_price = state.get("latest_price")
        self.current_bar = state.get("current_bar")
        self.closes = list(state.get("closes", []))
        self.highs = list(state.get("highs", []))
        self.lows = list(state.get("lows", []))
        self.rsi_history = list(state.get("rsi_history", []))
        self.atr_history = list(state.get("atr_history", []))
        self.adx_history = list(state.get("adx_history", []))
        self.ema_fast_history = list(state.get("ema_fast_history", []))
        self.scalp_rsi_history = list(state.get("scalp_rsi_history", []))
        self.scalp_atr_history = list(state.get("scalp_atr_history", []))
        self.scalp_adx_history = list(state.get("scalp_adx_history", []))
        self.last_closed_bar = state.get("last_closed_bar")
        self.signal = state.get("signal", self.signal)

        last_bar_time = state.get("last_bar_time")
        if last_bar_time:
            self.last_bar_time = datetime.fromisoformat(last_bar_time)
        print("[WORKER] State loaded")

    def save_state(self):
        payload = {
            "symbol": self.symbol,
            "latest_price": self.latest_price,
            "current_bar": self.current_bar,
            "last_bar_time": self.last_bar_time.isoformat() if self.last_bar_time else None,
            "last_closed_bar": self.last_closed_bar,
            "closes": self.closes,
            "highs": self.highs,
            "lows": self.lows,
            "rsi_history": self.rsi_history,
            "atr_history": self.atr_history,
            "adx_history": self.adx_history,
            "ema_fast_history": self.ema_fast_history,
            "scalp_rsi_history": self.scalp_rsi_history,
            "scalp_atr_history": self.scalp_atr_history,
            "scalp_adx_history": self.scalp_adx_history,
            "signal": self.signal,
            "updated_at": datetime.now(HCM_TZ).isoformat(),
        }
        atomic_write_json(WORKER_STATE_PATH, payload)

    def build_signal(self, close_price, reference_close, rsi_history, adx_value, scalp_signal, scalp_atr_value):
        prev_rsi = rsi_history[-2] if len(rsi_history) >= 2 else None
        curr_rsi = rsi_history[-1] if rsi_history else None
        deep_oversold_recent = count_deep_bars(rsi_history, RSI_DEEP_LONG, "below", lookback=7)
        deep_overbought_recent = count_deep_bars(rsi_history, RSI_DEEP_SHORT, "above", lookback=7)
        prev_in_normal_zone = (
            prev_rsi is not None
            and RSI_OVERSOLD < float(prev_rsi) < RSI_OVERBOUGHT
        )
        momentum_long_signal = (
            prev_in_normal_zone
            and curr_rsi is not None
            and prev_rsi is not None
            and float(curr_rsi) >= float(prev_rsi)
            and deep_oversold_recent >= MIN_BARS_DEEP
        )
        momentum_short_signal = (
            prev_in_normal_zone
            and curr_rsi is not None
            and prev_rsi is not None
            and float(curr_rsi) <= float(prev_rsi)
            and deep_overbought_recent >= MIN_BARS_DEEP
        )

        signal = {
            "side": None,
            "qty": 0,
            "entry_price": float(close_price),
            "tp": None,
            "sl": None,
            "time": None,
        }
        adx_ok = adx_value is not None and float(adx_value) >= ADX_THRESHOLD
        if adx_ok:
            recovery_signal = get_recovery_signal(
                rsi_history,
                current_price=close_price,
                reference_price=reference_close,
                lookback=7,
            )
            if recovery_signal["long_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "BUY",
                        "qty": 2,
                        "tp": float(close_price) + (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) - (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif recovery_signal["short_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "SELL",
                        "qty": 2,
                        "tp": float(close_price) - (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) + (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif momentum_long_signal and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "BUY",
                        "qty": 2,
                        "tp": float(close_price) + (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) - (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif momentum_short_signal and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "SELL",
                        "qty": 2,
                        "tp": float(close_price) - (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) + (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif scalp_signal["normal_long_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "SELL",
                        "qty": 2,
                        "tp": float(close_price) - (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) + (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif scalp_signal["normal_short_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "BUY",
                        "qty": 2,
                        "tp": float(close_price) + (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) - (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
        else:
            if scalp_signal["normal_long_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "SELL",
                        "qty": 2,
                        "tp": float(close_price) - (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) + (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
            elif scalp_signal["normal_short_signal"] and scalp_atr_value is not None:
                signal.update(
                    {
                        "side": "BUY",
                        "qty": 2,
                        "tp": float(close_price) + (scalp_atr_value * SCALP_TP_ATR_MULT),
                        "sl": float(close_price) - (scalp_atr_value * SCALP_SL_ATR_MULT),
                    }
                )
        return signal, adx_ok

    def update_live_signal(self, signal, signal_time):
        previous = {
            "side": self.signal.get("side"),
            "qty": self.signal.get("qty"),
            "entry_price": self.signal.get("entry_price"),
            "tp": self.signal.get("tp"),
            "sl": self.signal.get("sl"),
        }
        current = {
            "side": signal.get("side"),
            "qty": signal.get("qty"),
            "entry_price": signal.get("entry_price"),
            "tp": signal.get("tp"),
            "sl": signal.get("sl"),
        }
        signal["time"] = signal_time.isoformat() if current != previous else self.signal.get("time")
        self.signal = signal

    def finalize_bar(self):
        if self.current_bar is None or self.last_bar_time is None:
            return
        if not is_trading_time(self.last_bar_time):
            print("[WORKER] Skip outside trading hours")
            return

        bar = self.current_bar
        self.closes.append(float(bar["close"]))
        self.highs.append(float(bar["high"]))
        self.lows.append(float(bar["low"]))

        rsi_value = compute_rsi(self.closes, RSI_PERIOD)
        atr_value = compute_atr(self.highs, self.lows, self.closes, ATR_PERIOD)
        adx_value = compute_adx(self.highs, self.lows, self.closes, ADX_PERIOD)
        scalp_rsi_value = compute_rsi(self.closes, SCALP_RSI_PERIOD)
        scalp_atr_value = compute_atr(self.highs, self.lows, self.closes, SCALP_ATR_PERIOD)
        scalp_adx_value = compute_adx(self.highs, self.lows, self.closes, SCALP_ADX_PERIOD)
        ema_fast_value = compute_ema(self.closes, EMA_FAST_PERIOD)
        self.rsi_history.append(rsi_value)
        self.atr_history.append(atr_value)
        self.adx_history.append(adx_value)
        self.ema_fast_history.append(ema_fast_value)
        self.scalp_rsi_history.append(scalp_rsi_value)
        self.scalp_atr_history.append(scalp_atr_value)
        self.scalp_adx_history.append(scalp_adx_value)
        scalp_signal = get_normal_zone_scalp_signal(
            self.scalp_rsi_history,
            float(bar["close"]),
            ema_fast_value,
        )
        previous_close = self.closes[-2] if len(self.closes) >= 2 else None
        signal, adx_ok = self.build_signal(
            float(bar["close"]),
            previous_close,
            self.rsi_history,
            adx_value,
            scalp_signal,
            scalp_atr_value,
        )
        self.update_live_signal(signal, self.last_bar_time)
        self.last_closed_bar = {
            "time": self.last_bar_time.isoformat(),
            **bar,
            "rsi": rsi_value,
            "atr": atr_value,
            "adx": adx_value,
            "ema_fast": ema_fast_value,
            "scalp_rsi": scalp_rsi_value,
            "scalp_atr": scalp_atr_value,
            "scalp_adx": scalp_adx_value,
        }

        rsi_text = "NA" if rsi_value is None else f"{rsi_value:.2f}"
        atr_text = "NA" if atr_value is None else f"{atr_value:.2f}"
        adx_text = "NA" if adx_value is None else f"{adx_value:.2f}"
        ema_text = "NA" if ema_fast_value is None else f"{ema_fast_value:.2f}"
        scalp_rsi_text = "NA" if scalp_rsi_value is None else f"{scalp_rsi_value:.2f}"
        scalp_atr_text = "NA" if scalp_atr_value is None else f"{scalp_atr_value:.2f}"
        scalp_adx_text = "NA" if scalp_adx_value is None else f"{scalp_adx_value:.2f}"
        print(
            f"[WORKER BAR] {self.last_bar_time.strftime('%Y-%m-%d %H:%M')} "
            f"O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']}"
        )
        print(
            "[WORKER SIGNAL] "
            f"adx_ok={adx_ok} side={self.signal['side']} qty={self.signal['qty']} "
            f"entry={self.signal['entry_price']} tp={self.signal['tp']} sl={self.signal['sl']}"
        )
        print(
            f"[WORKER INDICATOR] rsi={rsi_text} atr={atr_text} adx={adx_text} "
            f"scalp_rsi={scalp_rsi_text} scalp_atr={scalp_atr_text} scalp_adx={scalp_adx_text} "
            f"ema9={ema_text}"
        )

    def on_market(self, instrument, quote):
        price = quote.latest_matched_price
        if price is None:
            return

        price = float(price)
        self.latest_price = price
        now = datetime.now(HCM_TZ).replace(second=0, microsecond=0)

        if self.last_bar_time and now != self.last_bar_time:
            self.finalize_bar()
            self.current_bar = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            }
        else:
            if self.current_bar is None:
                self.current_bar = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                }
            else:
                self.current_bar["high"] = max(self.current_bar["high"], price)
                self.current_bar["low"] = min(self.current_bar["low"], price)
                self.current_bar["close"] = price

        if self.current_bar is not None and is_trading_time(now):
            temp_closes = self.closes + [float(self.current_bar["close"])]
            temp_highs = self.highs + [float(self.current_bar["high"])]
            temp_lows = self.lows + [float(self.current_bar["low"])]
            live_rsi_value = compute_rsi(temp_closes, RSI_PERIOD)
            live_adx_value = compute_adx(temp_highs, temp_lows, temp_closes, ADX_PERIOD)
            live_scalp_rsi_value = compute_rsi(temp_closes, SCALP_RSI_PERIOD)
            live_scalp_atr_value = compute_atr(temp_highs, temp_lows, temp_closes, SCALP_ATR_PERIOD)
            live_ema_fast_value = compute_ema(temp_closes, EMA_FAST_PERIOD)
            live_rsi_history = self.rsi_history + [live_rsi_value]
            live_scalp_rsi_history = self.scalp_rsi_history + [live_scalp_rsi_value]
            live_scalp_signal = get_normal_zone_scalp_signal(
                live_scalp_rsi_history,
                float(self.current_bar["close"]),
                live_ema_fast_value,
            )
            live_reference_close = self.closes[-1] if self.closes else None
            live_signal, _ = self.build_signal(
                float(self.current_bar["close"]),
                live_reference_close,
                live_rsi_history,
                live_adx_value,
                live_scalp_signal,
                live_scalp_atr_value,
            )
            self.update_live_signal(live_signal, now)

        self.last_bar_time = now
        self.save_state()


async def main():
    worker = StateWorker(SYMBOL)
    worker.load_state()

    md = KafkaMarketDataClient(
        bootstrap_servers=os.getenv("PAPERBROKER_KAFKA_BOOTSTRAP_SERVERS"),
        username=os.getenv("PAPERBROKER_KAFKA_USERNAME"),
        password=os.getenv("PAPERBROKER_KAFKA_PASSWORD"),
        env_id=os.getenv("PAPERBROKER_ENV_ID"),
        merge_updates=True,
    )
    await md.subscribe(SYMBOL, worker.on_market)
    await md.start()

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
