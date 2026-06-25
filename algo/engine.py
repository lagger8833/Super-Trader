"""
algo/engine.py
Algorithmic order placement engine.
Strategies are defined as classes inheriting BaseStrategy.
The AlgoEngine runs them in a background thread with configurable intervals.
"""
import time
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional
from core.api_client import APIClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Base Strategy
# ─────────────────────────────────────────────

class BaseStrategy(ABC):
    """
    Override evaluate() to implement your logic.
    Call self.buy() / self.sell() to place orders.
    """

    def __init__(self, symbol: str, exchange: str, quantity: int,
                 product: str = "CNC"):
        self.symbol = symbol
        self.exchange = exchange
        self.quantity = str(quantity)
        self.product = product
        self.api = APIClient.get()

    @abstractmethod
    def evaluate(self) -> Optional[str]:
        """Return 'BUY', 'SELL', or None."""
        ...

    def buy(self, order_type="MARKET", price="0", trigger="0"):
        return self.api.place_order(
            "regular", self.symbol, self.exchange, "BUY",
            order_type, self.quantity, self.product, "DAY",
            price, trigger,
        )

    def sell(self, order_type="MARKET", price="0", trigger="0"):
        return self.api.place_order(
            "regular", self.symbol, self.exchange, "SELL",
            order_type, self.quantity, self.product, "DAY",
            price, trigger,
        )

    def get_ltp(self) -> Optional[float]:
        result = self.api.get_ltp([f"{self.exchange}:{self.symbol}"])
        if result["success"]:
            data = result["data"]
            # Normalise different response shapes
            instruments = data.get("data", data)
            if isinstance(instruments, dict):
                for v in instruments.values():
                    if isinstance(v, dict):
                        return float(v.get("last_price", 0))
        return None


# ─────────────────────────────────────────────
# Built-in Strategies
# ─────────────────────────────────────────────

class MovingAverageCrossStrategy(BaseStrategy):
    """
    Simple SMA crossover: buy when short MA crosses above long MA,
    sell when it crosses below.
    Requires historical price feed (simulated with LTP here for demo).
    """

    def __init__(self, symbol, exchange, quantity, product="CNC",
                 short_window=5, long_window=20):
        super().__init__(symbol, exchange, quantity, product)
        self.short_window = short_window
        self.long_window = long_window
        self._prices: list[float] = []
        self._position = None  # 'long' / None

    def _sma(self, n: int) -> Optional[float]:
        if len(self._prices) < n:
            return None
        return sum(self._prices[-n:]) / n

    def evaluate(self) -> Optional[str]:
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
            self._position = "long"
            logger.info("[MA Cross] BUY signal for %s (short=%.2f long=%.2f)",
                        self.symbol, short_ma, long_ma)
            return "BUY"
        elif short_ma < long_ma and self._position == "long":
            self._position = None
            logger.info("[MA Cross] SELL signal for %s", self.symbol)
            return "SELL"
        return None


class RSIOverboughtStrategy(BaseStrategy):
    """
    Simplified RSI strategy: sell when RSI > overbought, buy when < oversold.
    """

    def __init__(self, symbol, exchange, quantity, product="CNC",
                 period=14, overbought=70, oversold=30):
        super().__init__(symbol, exchange, quantity, product)
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self._prices: list[float] = []
        self._position = None

    def _rsi(self) -> Optional[float]:
        if len(self._prices) < self.period + 1:
            return None
        deltas = [self._prices[i] - self._prices[i-1]
                  for i in range(1, len(self._prices))]
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = sum(gains[-self.period:]) / self.period if gains else 0
        avg_loss = sum(losses[-self.period:]) / self.period if losses else 0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def evaluate(self) -> Optional[str]:
        ltp = self.get_ltp()
        if ltp is None:
            return None
        self._prices.append(ltp)
        rsi = self._rsi()
        if rsi is None:
            return None

        if rsi < self.oversold and self._position != "long":
            self._position = "long"
            logger.info("[RSI] BUY signal for %s (RSI=%.1f)", self.symbol, rsi)
            return "BUY"
        elif rsi > self.overbought and self._position == "long":
            self._position = None
            logger.info("[RSI] SELL signal for %s (RSI=%.1f)", self.symbol, rsi)
            return "SELL"
        return None


class PriceLevelStrategy(BaseStrategy):
    """
    Simple price-level strategy:
    - Buy when LTP drops to or below buy_price
    - Sell when LTP rises to or above sell_price
    """

    def __init__(self, symbol, exchange, quantity, product="CNC",
                 buy_price=0.0, sell_price=0.0):
        super().__init__(symbol, exchange, quantity, product)
        self.buy_price = buy_price
        self.sell_price = sell_price
        self._position = None

    def evaluate(self) -> Optional[str]:
        ltp = self.get_ltp()
        if ltp is None:
            return None

        if self.buy_price > 0 and ltp <= self.buy_price and self._position != "long":
            self._position = "long"
            logger.info("[PriceLevel] BUY at %.2f for %s", ltp, self.symbol)
            return "BUY"
        elif self.sell_price > 0 and ltp >= self.sell_price and self._position == "long":
            self._position = None
            logger.info("[PriceLevel] SELL at %.2f for %s", ltp, self.symbol)
            return "SELL"
        return None


# ─────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────

class AlgoEngine:
    """
    Runs registered strategies in a background thread.
    """

    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self._strategies: list[BaseStrategy] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_signal = None        # callback(symbol, action, result)
        self.on_error  = None        # callback(strategy, error)

    def add_strategy(self, strategy: BaseStrategy):
        self._strategies.append(strategy)
        logger.info("Strategy added: %s for %s", type(strategy).__name__, strategy.symbol)

    def remove_strategy(self, index: int):
        if 0 <= index < len(self._strategies):
            removed = self._strategies.pop(index)
            logger.info("Strategy removed: %s", type(removed).__name__)

    def clear_strategies(self):
        self._strategies.clear()

    @property
    def strategies(self):
        return list(self._strategies)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("AlgoEngine started (interval=%ds)", self.interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("AlgoEngine stopped")

    def _run_loop(self):
        while self._running:
            for strategy in self._strategies:
                try:
                    signal = strategy.evaluate()
                    if signal == "BUY":
                        result = strategy.buy()
                        if self.on_signal:
                            self.on_signal(strategy.symbol, "BUY", result)
                    elif signal == "SELL":
                        result = strategy.sell()
                        if self.on_signal:
                            self.on_signal(strategy.symbol, "SELL", result)
                except Exception as e:
                    logger.error("Strategy error (%s): %s",
                                 type(strategy).__name__, e)
                    if self.on_error:
                        self.on_error(strategy, str(e))
            time.sleep(self.interval)


# Singleton engine
_engine = AlgoEngine()

def get_engine() -> AlgoEngine:
    return _engine
