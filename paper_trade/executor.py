#!/usr/bin/env python3
import asyncio
import os
import time
from datetime import datetime

from paperbroker.client import PaperBrokerClient

from shared import (
    EXECUTOR_STATE_PATH,
    HCM_TZ,
    SYMBOL,
    WORKER_STATE_PATH,
    atomic_write_json,
    load_json,
)


class Executor:
    ENTRY_ORDER_STALE_BAR_LIMIT = 20
    BROKER_SYNC_INTERVAL_SECONDS = 10
    TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}

    def __init__(self, client, symbol):
        self.client = client
        self.symbol = symbol
        self.inventory = 0
        self.position_entry_price = None
        self.position_atr = None
        self.position_tp = None
        self.position_sl = None
        self.position_pnl = None
        self.resting_tp_order_id = None
        self.resting_tp_side = None
        self.resting_tp_qty = None
        self.resting_tp_price = None
        self.resting_tp_cancel_requested = False
        self.active_order_id = None
        self.active_order_side = None
        self.active_order_qty = None
        self.active_order_filled_qty = 0
        self.active_order_purpose = None
        self.active_order_tp = None
        self.active_order_sl = None
        self.active_order_cancel_requested = False
        self.active_order_bar_count = 0
        self.last_processed_bar_time = None
        self.last_processed_signal_time = None
        self.latest_worker_price = None
        self.latest_worker_atr = None
        self.latest_worker_scalp_atr = None
        self.last_broker_sync_ts = 0.0

    def load_state(self):
        state = load_json(EXECUTOR_STATE_PATH)
        if not state:
            print("[EXEC] No saved state found")
            return
        self.inventory = int(state.get("inventory", 0))
        self.position_entry_price = state.get("position_entry_price")
        self.position_atr = state.get("position_atr")
        self.position_tp = state.get("position_tp")
        self.position_sl = state.get("position_sl")
        self.position_pnl = state.get("position_pnl")
        self.resting_tp_order_id = state.get("resting_tp_order_id")
        self.resting_tp_side = state.get("resting_tp_side")
        self.resting_tp_qty = state.get("resting_tp_qty")
        self.resting_tp_price = state.get("resting_tp_price")
        self.resting_tp_cancel_requested = bool(state.get("resting_tp_cancel_requested", False))
        self.active_order_id = state.get("active_order_id")
        self.active_order_side = state.get("active_order_side")
        self.active_order_qty = state.get("active_order_qty")
        self.active_order_filled_qty = int(state.get("active_order_filled_qty", 0))
        self.active_order_purpose = state.get("active_order_purpose")
        self.active_order_tp = state.get("active_order_tp")
        self.active_order_sl = state.get("active_order_sl")
        self.active_order_cancel_requested = bool(state.get("active_order_cancel_requested", False))
        self.active_order_bar_count = int(state.get("active_order_bar_count", 0))
        self.last_processed_bar_time = state.get("last_processed_bar_time")
        self.last_processed_signal_time = state.get("last_processed_signal_time")
        print("[EXEC] State loaded")

    def save_state(self):
        atomic_write_json(
            EXECUTOR_STATE_PATH,
            {
                "inventory": self.inventory,
                "position_entry_price": self.position_entry_price,
                "position_atr": self.position_atr,
                "position_tp": self.position_tp,
                "position_sl": self.position_sl,
                "position_pnl": self.position_pnl,
                "resting_tp_order_id": self.resting_tp_order_id,
                "resting_tp_side": self.resting_tp_side,
                "resting_tp_qty": self.resting_tp_qty,
                "resting_tp_price": self.resting_tp_price,
                "resting_tp_cancel_requested": self.resting_tp_cancel_requested,
                "active_order_id": self.active_order_id,
                "active_order_side": self.active_order_side,
                "active_order_qty": self.active_order_qty,
                "active_order_filled_qty": self.active_order_filled_qty,
                "active_order_purpose": self.active_order_purpose,
                "active_order_tp": self.active_order_tp,
                "active_order_sl": self.active_order_sl,
                "active_order_cancel_requested": self.active_order_cancel_requested,
                "active_order_bar_count": self.active_order_bar_count,
                "last_processed_bar_time": self.last_processed_bar_time,
                "last_processed_signal_time": self.last_processed_signal_time,
                "updated_at": datetime.now(HCM_TZ).isoformat(),
            },
        )

    def sync_broker_inventory_periodic(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self.last_broker_sync_ts) < self.BROKER_SYNC_INTERVAL_SECONDS:
            return False
        changed = self.sync_broker_inventory()
        self.last_broker_sync_ts = now
        self.save_state()
        return changed

    def clear_active_order(self):
        self.active_order_id = None
        self.active_order_side = None
        self.active_order_qty = None
        self.active_order_filled_qty = 0
        self.active_order_purpose = None
        self.active_order_tp = None
        self.active_order_sl = None
        self.active_order_cancel_requested = False
        self.active_order_bar_count = 0

    def clear_resting_tp_order(self):
        self.resting_tp_order_id = None
        self.resting_tp_side = None
        self.resting_tp_qty = None
        self.resting_tp_price = None
        self.resting_tp_cancel_requested = False

    def has_active_exit_order(self):
        return bool(self.active_order_purpose and self.active_order_purpose.startswith("exit_"))

    def sync_broker_inventory(self):
        previous_inventory = self.inventory
        previous_entry_price = self.position_entry_price
        previous_atr = self.position_atr
        previous_tp = self.position_tp
        previous_sl = self.position_sl
        previous_pnl = self.position_pnl
        portfolio = self.client.get_portfolio_by_sub()
        inventory = 0
        if isinstance(portfolio, dict) and portfolio.get("success"):
            for pos in portfolio.get("items", []):
                if pos.get("instrument") == self.symbol:
                    inventory = int(pos.get("quantity", 0))
                    avg_price = pos.get("avgPrice")
                    self.position_pnl = pos.get("pnl")
                    if inventory != 0 and avg_price is not None:
                        self.position_entry_price = float(avg_price)
                        if self.position_atr is None:
                            self.position_atr = self.latest_worker_atr or self.latest_worker_scalp_atr
                    break
        self.inventory = inventory
        if self.inventory == 0:
            self.position_entry_price = None
            self.position_atr = None
            self.position_tp = None
            self.position_sl = None
            self.position_pnl = None
            self.clear_resting_tp_order()
        else:
            self.position_sl = None
        print(
            f"[EXEC] broker inventory={self.inventory} "
            f"entry={self.position_entry_price} atr={self.position_atr} tp={self.position_tp} sl={self.position_sl} pnl={self.position_pnl}"
        )
        return (
            self.inventory != previous_inventory
            or self.position_entry_price != previous_entry_price
            or self.position_atr != previous_atr
            or self.position_tp != previous_tp
            or self.position_sl != previous_sl
            or self.position_pnl != previous_pnl
        )

    def place_order(self, side, qty, price, reason, purpose=None, tp=None, sl=None, ord_type="LIMIT", tif="GTC", stop_price=None):
        order_px = None if price is None else float(price)
        self.active_order_id = self.client.place_order(
            self.symbol,
            side,
            qty,
            order_px,
            ord_type=ord_type,
            tif=tif,
            stop_price=stop_price,
        )
        self.active_order_side = side
        self.active_order_qty = int(qty)
        self.active_order_filled_qty = 0
        self.active_order_purpose = purpose
        self.active_order_tp = tp
        self.active_order_sl = sl
        self.active_order_cancel_requested = False
        self.active_order_bar_count = 0
        print(
            f"[EXEC ORDER] {reason} -> side={side} qty={qty} "
            f"ord_type={ord_type} price={order_px} stop={stop_price}"
        )
        self.save_state()

    def get_side_inventory_cap(self, side: str, price: float) -> int:
        try:
            result = self.client.get_max_placeable(self.symbol, float(price), side)
        except Exception as exc:
            print(f"[EXEC] max placeable fetch failed for {side}: {exc}")
            return 0
        if not isinstance(result, dict) or not result.get("success"):
            print(f"[EXEC] max placeable unavailable for {side}: {result}")
            return 0
        max_qty = int(result.get("maxQty", 0) or 0)
        cap = (max_qty * 2) // 3
        print(f"[EXEC] side cap {side}: maxQty={max_qty} -> cap={cap}")
        return cap

    def rebase_signal_levels(self, signal_entry_price, signal_tp, signal_sl, order_price):
        if signal_entry_price is None:
            return signal_tp, signal_sl
        try:
            base_entry = float(signal_entry_price)
            base_tp = float(signal_tp) if signal_tp is not None else None
            base_sl = float(signal_sl) if signal_sl is not None else None
            order_px = float(order_price)
        except (TypeError, ValueError):
            return signal_tp, signal_sl

        rebased_tp = None if base_tp is None else order_px + (base_tp - base_entry)
        rebased_sl = None if base_sl is None else order_px + (base_sl - base_entry)
        return rebased_tp, rebased_sl

    def place_resting_tp_order(self):
        if self.inventory == 0 or self.position_tp is None:
            return
        side = "SELL" if self.inventory > 0 else "BUY"
        qty = abs(self.inventory)
        price = float(self.position_tp)
        self.resting_tp_order_id = self.client.place_order(
            self.symbol,
            side,
            qty,
            price,
            ord_type="LIMIT",
            tif="GTC",
        )
        self.resting_tp_side = side
        self.resting_tp_qty = qty
        self.resting_tp_price = price
        self.resting_tp_cancel_requested = False
        print(f"[EXEC TP ORDER] side={side} qty={qty} price={price}")
        self.save_state()

    def cancel_resting_tp_order(self):
        if not self.resting_tp_order_id or self.resting_tp_cancel_requested:
            return
        try:
            print(f"[EXEC TP CANCEL] {self.resting_tp_order_id}")
            self.client.cancel_order(self.resting_tp_order_id)
            self.resting_tp_cancel_requested = True
            self.save_state()
        except Exception as exc:
            print(f"[EXEC TP CANCEL] failed {self.resting_tp_order_id}: {exc}")

    def ensure_resting_tp_order(self):
        if self.inventory == 0 or self.position_tp is None:
            if self.resting_tp_order_id:
                self.cancel_resting_tp_order()
            return

        desired_side = "SELL" if self.inventory > 0 else "BUY"
        desired_qty = abs(self.inventory)
        desired_price = float(self.position_tp)
        if (
            self.resting_tp_order_id
            and not self.resting_tp_cancel_requested
            and self.resting_tp_side == desired_side
            and self.resting_tp_qty == desired_qty
            and self.resting_tp_price is not None
            and abs(float(self.resting_tp_price) - desired_price) < 1e-9
        ):
            return

        if self.resting_tp_order_id and not self.resting_tp_cancel_requested:
            self.cancel_resting_tp_order()
            return
        if not self.resting_tp_order_id:
            self.place_resting_tp_order()

    def get_server_order(self, cl_ord_id):
        if not cl_ord_id:
            return None
        order_date = datetime.now(HCM_TZ).strftime("%Y-%m-%d")
        try:
            result = self.client.get_orders(order_date, order_date)
        except Exception as exc:
            print(f"[EXEC] server order lookup failed for {cl_ord_id}: {exc}")
            return None
        if not isinstance(result, dict) or not result.get("success"):
            print(f"[EXEC] server order lookup unavailable for {cl_ord_id}: {result}")
            return None
        for item in result.get("items", []):
            if item.get("clOrdId") == cl_ord_id and item.get("symbol") == self.symbol:
                return item
        return None

    def clear_stale_active_order_from_server(self):
        if not self.active_order_id:
            return
        server_order = self.get_server_order(self.active_order_id)
        if server_order is None:
            print(f"[EXEC] stale active order {self.active_order_id} not found on server; clearing local tracking")
            self.clear_active_order()
            self.sync_broker_inventory()
            self.save_state()
            return

        ord_status = str(server_order.get("ordStatus") or "").upper()
        leaves_qty = server_order.get("leavesQty")
        is_cancelled = bool(server_order.get("isCancelled"))
        is_executing = bool(server_order.get("isExecuting"))
        print(
            f"[EXEC] server order {self.active_order_id}: status={ord_status} "
            f"leavesQty={leaves_qty} isCancelled={is_cancelled} isExecuting={is_executing}"
        )

        if ord_status in self.TERMINAL_ORDER_STATUSES or is_cancelled:
            self.clear_active_order()
            self.sync_broker_inventory()
            self.save_state()
            return

        print(f"[EXEC] stale active order {self.active_order_id} still open on server; clearing local tracking only")
        self.clear_active_order()
        self.sync_broker_inventory()
        self.save_state()

    def on_filled(self, cl_ord_id, last_px, last_qty, **kw):
        qty = int(last_qty)
        if cl_ord_id == self.active_order_id:
            print(f"[EXEC FILL] id={cl_ord_id} side={self.active_order_side} qty={last_qty} px={last_px}")
            previous_inventory = self.inventory
            previous_tp = self.position_tp
            if self.active_order_side == "BUY":
                self.inventory += qty
            elif self.active_order_side == "SELL":
                self.inventory -= qty
            self.active_order_filled_qty += qty

            if self.position_entry_price is None and self.inventory != 0:
                self.position_entry_price = float(last_px)
            if self.inventory != 0:
                if self.position_atr is None:
                    self.position_atr = self.latest_worker_atr or self.latest_worker_scalp_atr
                fills_new_or_added_long = (
                    self.active_order_side == "BUY"
                    and self.inventory > 0
                    and self.active_order_tp is not None
                )
                fills_new_or_added_short = (
                    self.active_order_side == "SELL"
                    and self.inventory < 0
                    and self.active_order_tp is not None
                )
                if fills_new_or_added_long or fills_new_or_added_short:
                    same_side_add = (
                        previous_inventory != 0
                        and previous_inventory * self.inventory > 0
                        and abs(self.inventory) > abs(previous_inventory)
                        and previous_tp is not None
                    )
                    if same_side_add:
                        previous_qty = abs(previous_inventory)
                        new_qty = qty
                        self.position_tp = (
                            (float(previous_tp) * previous_qty) + (float(self.active_order_tp) * new_qty)
                        ) / (previous_qty + new_qty)
                    else:
                        self.position_tp = self.active_order_tp
                    self.position_sl = None
            else:
                self.position_entry_price = None
                self.position_atr = None
                self.position_tp = None
                self.position_sl = None
                self.clear_resting_tp_order()

            if self.inventory != 0 and self.position_entry_price is not None:
                print(
                    f"[EXEC POSITION] inventory={self.inventory} entry={self.position_entry_price:.1f} "
                    f"atr={self.position_atr if self.position_atr is not None else 'None'} "
                    f"tp={self.position_tp} sl={self.position_sl}"
                )

            status = kw.get("status")
            order_done = status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
            if self.active_order_qty is not None and self.active_order_filled_qty >= self.active_order_qty:
                order_done = True
            if order_done:
                self.clear_active_order()
            self.ensure_resting_tp_order()
            self.save_state()
            return

        if cl_ord_id == self.resting_tp_order_id:
            print(f"[EXEC TP FILL] id={cl_ord_id} qty={last_qty} px={last_px}")
            self.clear_resting_tp_order()
            self.sync_broker_inventory()
            self.ensure_resting_tp_order()
            self.save_state()
            return

        print(f"[EXEC FILL] non-active id={cl_ord_id} qty={last_qty} px={last_px}; syncing broker state")
        self.sync_broker_inventory()
        self.ensure_resting_tp_order()
        self.save_state()

    def on_canceled(self, orig_cl_ord_id, status=None, **kw):
        print(f"[EXEC CANCELED] id={orig_cl_ord_id} status={status}")
        if orig_cl_ord_id == self.active_order_id:
            self.clear_active_order()
            self.sync_broker_inventory()
            self.save_state()
            return
        if orig_cl_ord_id == self.resting_tp_order_id:
            self.clear_resting_tp_order()
            self.sync_broker_inventory()
            self.ensure_resting_tp_order()
            self.save_state()
            return
        self.sync_broker_inventory()
        self.ensure_resting_tp_order()
        self.save_state()
        return

    def on_rejected(self, cl_ord_id, reason=None, status=None, **kw):
        print(f"[EXEC REJECT] id={cl_ord_id} status={status} reason={reason}")
        if cl_ord_id == self.active_order_id:
            self.clear_active_order()
            self.save_state()
            return
        if cl_ord_id == self.resting_tp_order_id:
            self.clear_resting_tp_order()
            self.save_state()
            return
        self.sync_broker_inventory()
        self.ensure_resting_tp_order()
        self.save_state()

    def handle_tick_exit(self, latest_price):
        return

    def handle_bar_signal(self, state):
        last_closed_bar = state.get("last_closed_bar")
        signal = state.get("signal") or {}
        signal_time = signal.get("time")
        if not signal_time and not last_closed_bar:
            return

        event_time = signal_time or last_closed_bar.get("time")
        if not event_time or event_time == self.last_processed_signal_time:
            return

        if last_closed_bar:
            self.last_processed_bar_time = last_closed_bar.get("time")
        self.last_processed_signal_time = event_time
        self.sync_broker_inventory()
        self.save_state()

        if self.active_order_id:
            self.active_order_bar_count += 1
            self.save_state()
            if (
                not self.active_order_cancel_requested
                and not self.has_active_exit_order()
                and self.active_order_bar_count >= self.ENTRY_ORDER_STALE_BAR_LIMIT
            ):
                self.clear_stale_active_order_from_server()
                print(f"[EXEC] stale active order reconciled from server after {self.active_order_bar_count} bars")
            elif self.active_order_cancel_requested:
                print(f"[EXEC] active order still waiting for cancel resolution ({self.active_order_bar_count} bars)")
            elif self.has_active_exit_order():
                print(f"[EXEC] active exit order still pending ({self.active_order_bar_count} bars)")
            else:
                print(
                    f"[EXEC] active order still pending; continuing signal handling "
                    f"({self.active_order_bar_count}/{self.ENTRY_ORDER_STALE_BAR_LIMIT} bars)"
                )

        signal_price = float(last_closed_bar["close"]) if last_closed_bar else float(signal.get("entry_price") or self.latest_worker_price or 0.0)
        signal_side = signal.get("side")
        signal_qty = int(signal.get("qty", 0) or 0)
        signal_entry_price = signal.get("entry_price")
        signal_tp = signal.get("tp")
        signal_sl = signal.get("sl")
        order_price = float(self.latest_worker_price) if self.latest_worker_price is not None else (
            float(signal_entry_price) if signal_entry_price is not None else signal_price
        )
        adjusted_tp, adjusted_sl = self.rebase_signal_levels(
            signal_entry_price,
            signal_tp,
            signal_sl,
            order_price,
        )

        if self.inventory > 0 and signal_side == "SELL":
            if self.position_pnl is None or float(self.position_pnl) <= 0:
                print(f"[EXEC] reverse to SHORT skipped: pnl={self.position_pnl} not positive")
                return
            short_cap = self.get_side_inventory_cap("SELL", order_price)
            reverse_qty = abs(self.inventory) + signal_qty
            target_short = reverse_qty - abs(self.inventory)
            if short_cap <= 0 or target_short <= 0:
                print("[EXEC] reverse skipped: short cap unavailable")
                return
            reverse_qty = abs(self.inventory) + min(signal_qty, short_cap)
            self.place_order(
                "SELL",
                reverse_qty,
                order_price,
                (
                    f"Close and reverse to SHORT (signal_close={signal_price:.1f} "
                    f"order={order_price:.1f} cap={short_cap})"
                ),
                purpose="exit_opposite_recovery",
                tp=adjusted_tp,
                sl=adjusted_sl,
            )
            return
        if self.inventory < 0 and signal_side == "BUY":
            if self.position_pnl is None or float(self.position_pnl) <= 0:
                print(f"[EXEC] reverse to LONG skipped: pnl={self.position_pnl} not positive")
                return
            long_cap = self.get_side_inventory_cap("BUY", order_price)
            reverse_qty = abs(self.inventory) + signal_qty
            target_long = reverse_qty - abs(self.inventory)
            if long_cap <= 0 or target_long <= 0:
                print("[EXEC] reverse skipped: long cap unavailable")
                return
            reverse_qty = abs(self.inventory) + min(signal_qty, long_cap)
            self.place_order(
                "BUY",
                reverse_qty,
                order_price,
                (
                    f"Close and reverse to LONG (signal_close={signal_price:.1f} "
                    f"order={order_price:.1f} cap={long_cap})"
                ),
                purpose="exit_opposite_recovery",
                tp=adjusted_tp,
                sl=adjusted_sl,
            )
            return
        if self.inventory > 0 and signal_side == "BUY":
            long_cap = self.get_side_inventory_cap("BUY", order_price)
            if self.inventory >= long_cap:
                print(f"[EXEC] add LONG skipped: inventory={self.inventory} cap={long_cap}")
                return
            signal_qty = min(signal_qty, long_cap - self.inventory)
        elif self.inventory < 0 and signal_side == "SELL":
            short_cap = self.get_side_inventory_cap("SELL", order_price)
            if abs(self.inventory) >= short_cap:
                print(f"[EXEC] add SHORT skipped: inventory={self.inventory} cap={short_cap}")
                return
            signal_qty = min(signal_qty, short_cap - abs(self.inventory))
        elif self.inventory == 0 and signal_side == "BUY":
            long_cap = self.get_side_inventory_cap("BUY", order_price)
            if long_cap <= 0:
                print("[EXEC] LONG entry skipped: long cap unavailable")
                return
            signal_qty = min(signal_qty, long_cap)
        elif self.inventory == 0 and signal_side == "SELL":
            short_cap = self.get_side_inventory_cap("SELL", order_price)
            if short_cap <= 0:
                print("[EXEC] SHORT entry skipped: short cap unavailable")
                return
            signal_qty = min(signal_qty, short_cap)

        if signal_side == "BUY" and signal_qty > 0:
            self.place_order(
                "BUY",
                signal_qty,
                order_price,
                (
                    f"LONG entry (order={order_price:.1f} qty={signal_qty} "
                    f"tp={adjusted_tp} sl={adjusted_sl})"
                ),
                purpose="entry",
                tp=adjusted_tp,
                sl=adjusted_sl,
            )
        elif signal_side == "SELL" and signal_qty > 0:
            self.place_order(
                "SELL",
                signal_qty,
                order_price,
                (
                    f"SHORT entry (order={order_price:.1f} qty={signal_qty} "
                    f"tp={adjusted_tp} sl={adjusted_sl})"
                ),
                purpose="entry",
                tp=adjusted_tp,
                sl=adjusted_sl,
            )
        else:
            print("[EXEC] no new signal")


async def main():
    client = PaperBrokerClient(
        default_sub_account=os.getenv("PAPER_ACCOUNT_ID_D1", "main"),
        username=os.getenv("PAPER_USERNAME"),
        password=os.getenv("PAPER_PASSWORD"),
        rest_base_url=os.getenv("PAPER_REST_BASE_URL"),
        socket_connect_host=os.getenv("SOCKET_HOST"),
        socket_connect_port=int(os.getenv("SOCKET_PORT", "5001")),
        sender_comp_id=os.getenv("SENDER_COMP_ID"),
        target_comp_id=os.getenv("TARGET_COMP_ID", "SERVER"),
        order_store_path=None,
    )

    executor = Executor(client, SYMBOL)
    executor.load_state()
    client.on("fix:order:filled", executor.on_filled)
    client.on("fix:order:canceled", executor.on_canceled)
    client.on("fix:order:rejected", executor.on_rejected)

    client.connect()
    if not client.wait_until_logged_on(10):
        print("[EXEC] Login failed")
        return

    print("[EXEC] Connected")
    executor.sync_broker_inventory_periodic(force=True)

    while True:
        executor.sync_broker_inventory_periodic()
        worker_state = load_json(WORKER_STATE_PATH)
        if worker_state:
            latest_price = worker_state.get("latest_price")
            if latest_price is not None:
                executor.latest_worker_price = float(latest_price)
            last_closed_bar = worker_state.get("last_closed_bar") or {}
            latest_atr = last_closed_bar.get("atr")
            executor.latest_worker_atr = float(latest_atr) if latest_atr is not None else None
            latest_scalp_atr = last_closed_bar.get("scalp_atr")
            executor.latest_worker_scalp_atr = float(latest_scalp_atr) if latest_scalp_atr is not None else None
            if executor.inventory != 0 and executor.position_atr is None and (
                executor.latest_worker_atr is not None or executor.latest_worker_scalp_atr is not None
            ):
                executor.position_atr = executor.latest_worker_atr or executor.latest_worker_scalp_atr
                executor.save_state()
            if latest_price is not None:
                executor.handle_tick_exit(executor.latest_worker_price)
            executor.handle_bar_signal(worker_state)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
