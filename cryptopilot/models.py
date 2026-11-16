from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

import numpy as np


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Regime(str, Enum):
    UPTREND = "Uptrend"
    DOWNTREND = "Downtrend"
    SIDEWAYS = "Sideways"
    HIGH_VOL = "High Volatility"
    LOW_VOL = "Low Volatility"
    LOW_LIQUIDITY = "Low Liquidity"
    BREAKOUT = "Breakout"
    FALSE_BREAKOUT = "False Breakout"
    PANIC = "Panic"
    UNCERTAIN = "Uncertain"


@dataclass(frozen=True)
class Candles:
    """OHLCV series for one timeframe. ``ts`` = candle open time in ms."""
    tf_ms: int
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __len__(self) -> int:
        return len(self.ts)

    def closed(self, now_ms: int) -> "Candles":
        """Drop candles that are still forming at ``now_ms`` (no look-ahead)."""
        keep = (self.ts + self.tf_ms) <= now_ms
        return Candles(self.tf_ms, *(a[keep] for a in (self.ts, self.open, self.high,
                                                       self.low, self.close, self.volume)))

    def quality(self, now_ms: int, max_stale_bars: int = 2) -> Tuple[bool, Tuple[str, ...]]:
        """Validate a *closed* series. Returns (ok, problems)."""
        p = []
        n = len(self)
        if n == 0:
            return False, ("no candles",)
        for name in ("open", "high", "low", "close", "volume"):
            a = getattr(self, name)
            if not np.all(np.isfinite(a)):
                p.append(f"non-finite {name}")
        if p:
            return False, tuple(p)
        if np.any(np.diff(self.ts) <= 0):
            p.append("timestamps not strictly increasing")
        elif np.any(np.diff(self.ts) != self.tf_ms):
            p.append("gap in candles")
        if np.any(self.close <= 0) or np.any(self.low <= 0):
            p.append("non-positive price")
        if np.any(self.high < np.maximum(self.open, self.close)) or \
                np.any(self.low > np.minimum(self.open, self.close)):
            p.append("inconsistent OHLC")
        if np.any(self.volume < 0):
            p.append("negative volume")
        if now_ms - (self.ts[-1] + self.tf_ms) > max_stale_bars * self.tf_ms:
            p.append("stale data")
        return (not p), tuple(p)


@dataclass(frozen=True)
class Proposal:
    side: Action
    entry: float
    stop: float
    take_profit: float
    reasons: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Signal:
    action: Action
    symbol: str
    regime: Regime
    strategy: str = ""
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    qty: float = 0.0
    risk_amount: float = 0.0      # quote currency, incl. estimated costs
    fees: float = 0.0
    slippage: float = 0.0
    expected_net: float = 0.0     # expected value after all costs (quote)
    reasons: Tuple[str, ...] = ()
    data_quality: str = "unknown"
    note: str = "No calibrated probability: this is not a profit forecast."

    @staticmethod
    def hold(symbol: str, regime: Regime, reasons, quality: str = "unknown") -> "Signal":
        return Signal(Action.HOLD, symbol, regime, reasons=tuple(reasons), data_quality=quality)
