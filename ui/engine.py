"""
algo/engine.py

AlgoEngine — always-on, auto-starts when imported.
BracketGuardStrategy runs in its own high-frequency thread (0.5s interval).
Standard strategies run in the main engine loop.
"""
import time
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Base Strategy
# ─────────────────────────────────────────────────────────────────

class BaseStrategy(ABC):
    def __init__(self, symbol: str, exchange: str, quantity: int,
                 product: str = "CNC"):
        from core.api_client import APIClient
        self.symbol   = symbol
        self.exchange = exchange
        self.quantity = str(quantity)
        self.product  = product
        self.api      = APIClient.get()

    @abstractmethod
    def evaluate(self) -> Optional[str]:
        """Return 'BUY', 'SELL', or None."""
        ...

    def buy(self, order_type="MARKET", price="0", trigger="0"):
        return self.api.place_order(
            "regular", self.symbol, self.exchange, "BUY",
            order_type, self.quantity, self.product, "DAY",
            price, trigger)

    def sell(self, order_type="MARKET", price="0", trigger="0"):
        return self.api.place_order(
            "regular", self.symbol, self.exchange, "SELL",
            order_type, self.quantity, self.product, "DAY",
            price, trigger)

    def get_ltp(self) -> Optional[float]:
        from core.api_client import APIClient
        result = APIClient.get().get_ltp([f"{self.exchange}:{self.symbol}"])
        if result["success"]:
            data = result["data"]
            instruments = data.get("data", data)
            if isinstance(instruments, dict):
                for v in instruments.values():
                    if isinstance(v, dict):
                        return float(v.get("last_price", 0))
        return None


# ─────────────────────────────────────────────────────────────────
# Standard Strategies
# ─────────────────────────────────────────────────────────────────

class MovingAverageCrossStrategy(BaseStrategy):
    def __init__(self, symbol, exchange, quantity, product="CNC",
                 short_window=5, long_window=20):
        super().__init__(symbol, exchange, quantity, product)
        self.short_window = short_window
        self.long_window  = long_window
        self._prices: list = []
        self._position = None

    def _sma(self, n):
        if len(self._prices) < n:
            return None
        return sum(self._prices[-n:]) / n

    def evaluate(self):
        ltp = self.get_ltp()
        if ltp is None:
            return None
        self._prices.append(ltp)
        if len(self._prices) > self.long_window * 3:
            self._prices = self._prices[-(self.long_window * 3):]
        short_ma = self._sma(self.short_window)
        long_ma  = self._sma(self.long_window)
        if short_ma is None or long_ma is None:
            return None
        if short_ma > long_ma and self._position != "long":
            self._position = "long"; return "BUY"
        elif short_ma < long_ma and self._position == "long":
            self._position = None; return "SELL"
        return None


class RSIOverboughtStrategy(BaseStrategy):
    def __init__(self, symbol, exchange, quantity, product="CNC",
                 period=14, overbought=70, oversold=30):
        super().__init__(symbol, exchange, quantity, product)
        self.period = period
        self.overbought = overbought
        self.oversold   = oversold
        self._prices: list = []
        self._position = None

    def _rsi(self):
        if len(self._prices) < self.period + 1:
            return None
        deltas = [self._prices[i] - self._prices[i-1]
                  for i in range(1, len(self._prices))]
        gains  = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains[-self.period:])  / self.period if gains  else 0
        avg_loss = sum(losses[-self.period:]) / self.period if losses else 0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def evaluate(self):
        ltp = self.get_ltp()
        if ltp is None:
            return None
        self._prices.append(ltp)
        rsi = self._rsi()
        if rsi is None:
            return None
        if rsi < self.oversold and self._position != "long":
            self._position = "long"; return "BUY"
        elif rsi > self.overbought and self._position == "long":
            self._position = None; return "SELL"
        return None


class PriceLevelStrategy(BaseStrategy):
    def __init__(self, symbol, exchange, quantity, product="CNC",
                 buy_price=0.0, sell_price=0.0):
        super().__init__(symbol, exchange, quantity, product)
        self.buy_price  = buy_price
        self.sell_price = sell_price
        self._position  = None

    def evaluate(self):
        ltp = self.get_ltp()
        if ltp is None:
            return None
        if self.buy_price > 0 and ltp <= self.buy_price and self._position != "long":
            self._position = "long"; return "BUY"
        elif self.sell_price > 0 and ltp >= self.sell_price and self._position == "long":
            self._position = None; return "SELL"
        return None


# ─────────────────────────────────────────────────────────────────
# Bracket Guard Strategy
# Runs in its OWN dedicated thread at 0.5s — independent of engine loop.
# Always-on: registered once, monitors holdings continuously.
# ─────────────────────────────────────────────────────────────────

class BracketGuardStrategy(BaseStrategy):
    """
    Bracket Guard — auto target + stop-loss for any new holding.

    Lifecycle per position:
      WAITING   → polling holdings every 0.5s until symbol appears
      SETUP     → reads avg price, places LIMIT SELL (target) + SL-M SELL (stoploss)
      WATCHING  → polls both order statuses every 0.5s
      DONE      → one filled, other cancelled; resets to WAITING for next trade

    Parameters:
      target_pct  — profit target above avg price (default 0.9%)
      sl_pct      — stop-loss below avg price (default 0.9%)
    """

    POLL_INTERVAL = 0.5   # seconds

    def __init__(self, symbol: str, exchange: str, quantity: int,
                 product: str = "CNC",
                 target_pct: float = 0.9,
                 sl_pct: float = 0.9):
        super().__init__(symbol, exchange, quantity, product)
        self.target_pct = target_pct
        self.sl_pct     = sl_pct
        self._reset()
        self._thread: Optional[threading.Thread] = None
        self._active  = False
        # callbacks set by engine
        self.on_signal = None   # (symbol, msg, color)
        self.on_error  = None   # (msg)

    def _reset(self):
        self._state       = "WAITING"
        self._buy_price   = 0.0
        self._target_price= 0.0
        self._sl_price    = 0.0
        self._target_oid  = ""
        self._sl_oid      = ""
        self._qty_held    = 0

    # ── Thread management ─────────────────────────────────────────

    def start(self):
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"BracketGuard-{self.symbol}"
        )
        self._thread.start()
        logger.info("[BracketGuard] Started for %s (target=%.1f%% sl=%.1f%%)",
                    self.symbol, self.target_pct, self.sl_pct)

    def stop(self):
        self._active = False

    def evaluate(self):
        # evaluate() is unused — this strategy runs its own thread
        return None

    # ── Main loop (0.5s) ──────────────────────────────────────────

    def _loop(self):
        while self._active:
            try:
                if self._state == "WAITING":
                    self._check_holding()
                elif self._state == "WATCHING":
                    self._check_orders()
            except Exception as e:
                logger.error("[BracketGuard] Loop error: %s", e, exc_info=True)
                if self.on_error:
                    self.on_error(f"BracketGuard error: {e}")
            time.sleep(self.POLL_INTERVAL)

    # ── WAITING: poll holdings every 0.5s ────────────────────────

    def _get_holding(self):
        """Returns (avg_price, quantity) for this symbol, or (0, 0)."""
        from core.api_client import APIClient
        r = APIClient.get().get_holdings()
        if not r["success"]:
            return 0.0, 0
        data  = r.get("data", {})
        items = data if isinstance(data, list) else data.get("data", [])
        for h in (items if isinstance(items, list) else []):
            sym = (h.get("tradingsymbol") or h.get("symbol") or "").upper()
            if sym == self.symbol.upper():
                avg = float(h.get("average_price") or h.get("avg_price") or 0)
                qty = int(h.get("quantity") or h.get("qty") or 0)
                return avg, qty
        return 0.0, 0

    def _check_holding(self):
        avg, qty = self._get_holding()
        if avg <= 0 or qty <= 0:
            return  # not in holdings yet

        self._buy_price    = avg
        self._qty_held     = qty
        self._target_price = round(avg * (1 + self.target_pct / 100), 2)
        self._sl_price     = round(avg * (1 - self.sl_pct    / 100), 2)

        logger.info(
            "[BracketGuard] %s in holdings: avg=₹%.2f qty=%d "
            "→ target=₹%.2f (+%.1f%%) | sl=₹%.2f (-%.1f%%)",
            self.symbol, avg, qty,
            self._target_price, self.target_pct,
            self._sl_price,     self.sl_pct
        )
        self._emit(
            f"🔔 {self.symbol} detected in holdings at ₹{avg:.2f} × {qty} "
            f"→ placing target + SL orders", "#50A0FF"
        )

        qty_str = str(qty)
        self._target_oid = self._place_order("LIMIT",  qty_str,
                                              f"{self._target_price:.2f}", "0")
        self._sl_oid     = self._place_order("SL-M",   qty_str,
                                              "0", f"{self._sl_price:.2f}")

        if self._target_oid and self._sl_oid:
            self._state = "WATCHING"
            self._emit(
                f"✅ Orders placed — "
                f"Target: ₹{self._target_price:.2f} | "
                f"SL: ₹{self._sl_price:.2f}", "#50DD80"
            )
        else:
            self._emit(f"⚠ Order placement failed for {self.symbol} — retrying next cycle",
                       "#FF8800")
            self._reset()

    # ── WATCHING: poll order statuses every 0.5s ─────────────────

    FILLED = {"COMPLETE", "EXECUTED", "FILLED"}
    DEAD   = {"CANCELLED", "REJECTED", "O-CANCELLED", "CANCEL PENDING"}

    def _get_order_status(self, order_id: str) -> str:
        from core.api_client import APIClient
        r = APIClient.get().get_order_book()
        if not r["success"]:
            return ""
        data   = r.get("data", {})
        orders = data if isinstance(data, list) else data.get("data", [])
        for o in (orders if isinstance(orders, list) else []):
            if str(o.get("order_id", "")) == str(order_id):
                return (o.get("status") or "").upper()
        return ""

    def _check_orders(self):
        from core.api_client import APIClient
        client = APIClient.get()

        ts = self._get_order_status(self._target_oid)
        ss = self._get_order_status(self._sl_oid)

        if ts in self.FILLED:
            logger.info("[BracketGuard] TARGET filled for %s — cancelling SL", self.symbol)
            client.cancel_order(self._sl_oid)
            self._emit(
                f"🎯 TARGET hit for {self.symbol} at ₹{self._target_price:.2f} "
                f"(+{self.target_pct:.1f}%) — SL cancelled", "#50DD80"
            )
            self._reset()
            return

        if ss in self.FILLED:
            logger.info("[BracketGuard] STOP-LOSS triggered for %s — cancelling target", self.symbol)
            client.cancel_order(self._target_oid)
            self._emit(
                f"🛑 STOP-LOSS triggered for {self.symbol} at ₹{self._sl_price:.2f} "
                f"(-{self.sl_pct:.1f}%) — target cancelled", "#FF6060"
            )
            self._reset()
            return

        if ts in self.DEAD and ss in self.DEAD:
            logger.warning("[BracketGuard] Both orders dead for %s — resetting", self.symbol)
            self._emit(f"⚠ Both orders cancelled/rejected for {self.symbol} — resetting",
                       "#FF8800")
            self._reset()

    # ── Order placement helper ────────────────────────────────────

    def _place_order(self, order_type: str, qty: str,
                     price: str, trigger: str) -> str:
        from core.api_client import APIClient
        r = APIClient.get().place_order(
            "regular", self.symbol, self.exchange, "SELL",
            order_type, qty, self.product, "DAY",
            price, trigger,
        )
        if r["success"]:
            inner = r.get("data", {})
            if isinstance(inner, list):
                inner = inner[0] if inner else {}
            oid = ((inner.get("data") or {}).get("order_id")
                   or inner.get("order_id") or "")
            logger.info("[BracketGuard] %s SELL placed → oid=%s", order_type, oid)
            return str(oid)
        logger.error("[BracketGuard] %s order FAILED: %s", order_type, r.get("error"))
        return ""

    def _emit(self, msg: str, color: str = "#AAAACC"):
        if self.on_signal:
            try:
                self.on_signal(self.symbol, msg, color)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────
# AlgoEngine
# ─────────────────────────────────────────────────────────────────

class AlgoEngine:
    """
    Always-on engine.
    - BracketGuardStrategy: runs in its own 0.5s thread, auto-starts on add.
    - Other strategies: run in main engine loop (configurable interval).
    """

    def __init__(self, interval_seconds: int = 60):
        self.interval   = interval_seconds
        self._strategies: list = []
        self._running   = False
        self._thread: Optional[threading.Thread] = None
        self.on_signal  = None   # callback(symbol, action, result)
        self.on_error   = None   # callback(strategy, error)

    def add_strategy(self, strategy: BaseStrategy):
        self._strategies.append(strategy)
        logger.info("Strategy added: %s for %s", type(strategy).__name__, strategy.symbol)

        # BracketGuard gets its own thread — wire callbacks and start immediately
        if isinstance(strategy, BracketGuardStrategy):
            strategy.on_signal = lambda sym, msg, color: (
                self.on_signal(sym, msg, color) if self.on_signal else None
            )
            strategy.on_error = lambda msg: (
                self.on_error(strategy, msg) if self.on_error else None
            )
            strategy.start()
            logger.info("[Engine] BracketGuard auto-started for %s", strategy.symbol)

    def remove_strategy(self, index: int):
        if 0 <= index < len(self._strategies):
            s = self._strategies[index]
            if isinstance(s, BracketGuardStrategy):
                s.stop()
            self._strategies.pop(index)
            logger.info("Strategy removed: %s", type(s).__name__)

    def clear_strategies(self):
        for s in self._strategies:
            if isinstance(s, BracketGuardStrategy):
                s.stop()
        self._strategies.clear()

    @property
    def strategies(self):
        return list(self._strategies)

    def start(self):
        """Start the main engine loop for non-Bracket strategies."""
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop, daemon=True, name="AlgoEngine"
        )
        self._thread.start()
        logger.info("AlgoEngine main loop started (interval=%ds)", self.interval)

    def stop(self):
        self._running = False
        for s in self._strategies:
            if isinstance(s, BracketGuardStrategy):
                s.stop()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AlgoEngine stopped")

    def _run_loop(self):
        while self._running:
            for strategy in list(self._strategies):
                if isinstance(strategy, BracketGuardStrategy):
                    continue   # has its own thread
                try:
                    signal = strategy.evaluate()
                    if signal == "BUY":
                        result = strategy.buy()
                        if self.on_signal:
                            self.on_signal(strategy.symbol, "BUY signal → placed", "#50DD80")
                    elif signal == "SELL":
                        result = strategy.sell()
                        if self.on_signal:
                            self.on_signal(strategy.symbol, "SELL signal → placed", "#FF6060")
                except Exception as e:
                    logger.error("Strategy error (%s): %s", type(strategy).__name__, e)
                    if self.on_error:
                        self.on_error(strategy, str(e))
            time.sleep(self.interval)


# Singleton
_engine = AlgoEngine()

def get_engine() -> AlgoEngine:
    return _engine
