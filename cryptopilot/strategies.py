"""Strategies (long-only spot) and the registry that decides which are admitted.

A strategy never sizes or executes; it only proposes entry/stop/target from the
last *closed* candle. Strategies are CANDIDATE by default and can only become
ADMITTED through ``StrategyRegistry.admit`` with independently validated stats."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional

import numpy as np

from . import indicators as ind
from .models import Action, Candles, Proposal, Regime

MIN_BARS = 120


class Strategy:
    name = "base"
    allowed_regimes: FrozenSet[Regime] = frozenset()

    def evaluate(self, c: Candles, regime: Regime) -> Optional[Proposal]:
        if regime not in self.allowed_regimes or len(c) < MIN_BARS:
            return None
        return self._evaluate(c, regime)

    def _evaluate(self, c: Candles, regime: Regime) -> Optional[Proposal]:
        raise NotImplementedError


class TrendFollowing(Strategy):
    name = "trend_following"
    allowed_regimes = frozenset({Regime.UPTREND, Regime.DOWNTREND})

    def _evaluate(self, c, regime):
        px = c.close[-1]
        e20, e50 = ind.ema(c.close, 20)[-1], ind.ema(c.close, 50)[-1]
        r = ind.rsi(c.close)[-1]
        hist = ind.macd(c.close)[2][-1]
        a = ind.atr(c.high, c.low, c.close)[-1]
        if regime is Regime.UPTREND and e20 > e50 and px > e50 and 40 <= r <= 65 and hist > 0:
            return Proposal(Action.BUY, px, px - 2 * a, px + 3 * a, ("pullback in uptrend, MACD hist>0",))
        if regime is Regime.DOWNTREND and px < e50 and hist < 0:
            return Proposal(Action.SELL, px, 0.0, 0.0, ("trend broken: exit existing long",))
        return None


class Breakout(Strategy):
    name = "breakout"
    allowed_regimes = frozenset({Regime.BREAKOUT})

    def _evaluate(self, c, regime):
        px = c.close[-1]
        if px <= c.high[-21:-1].max():
            return None
        a = ind.atr(c.high, c.low, c.close)[-1]
        return Proposal(Action.BUY, px, px - 1.5 * a, px + 3 * a, ("entry-timeframe 20-bar breakout",))


class MeanReversion(Strategy):
    name = "mean_reversion"
    allowed_regimes = frozenset({Regime.SIDEWAYS})

    def _evaluate(self, c, regime):
        px = c.close[-1]
        e20 = ind.ema(c.close, 20)[-1]
        sd = float(np.std(c.close[-20:]))
        r = ind.rsi(c.close)[-1]
        a = ind.atr(c.high, c.low, c.close)[-1]
        if r < 30 and px < e20 - 2 * sd and e20 > px:
            return Proposal(Action.BUY, px, px - 1.5 * a, e20, ("oversold below lower band in range",))
        return None


class VolatilityAdaptive(Strategy):
    name = "volatility_adaptive"
    allowed_regimes = frozenset({Regime.HIGH_VOL, Regime.LOW_VOL})

    def _evaluate(self, c, regime):
        px = c.close[-1]
        a_series = ind.atr(c.high, c.low, c.close)
        a = a_series[-1]
        pct = a_series[-100:] / c.close[-100:]
        k = float(np.clip(2 * (a / px) / np.nanmedian(pct), 1.0, 3.0))
        if px > ind.ema(c.close, 50)[-1] and ind.rsi(c.close)[-1] > 50 and ind.macd(c.close)[2][-1] > 0:
            return Proposal(Action.BUY, px, px - k * a, px + 1.5 * k * a, (f"ATR-scaled stop k={k:.2f}",))
        return None


class Status(str, Enum):
    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    REVOKED = "revoked"


@dataclass(frozen=True)
class StrategyStats:
    """Stats from *independent* validation (out-of-sample), net of costs."""
    n_trades: int
    wins: int
    expectancy_net: float
    validated: bool
    source: str = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.n_trades if self.n_trades else 0.0


class StrategyRegistry:
    def __init__(self, strategies: Optional[List[Strategy]] = None, min_trades: int = 30):
        strategies = strategies or [TrendFollowing(), Breakout(), MeanReversion(), VolatilityAdaptive()]
        self.min_trades = min_trades
        self._s: Dict[str, Strategy] = {s.name: s for s in strategies}
        self._status: Dict[str, Status] = {n: Status.CANDIDATE for n in self._s}
        self._stats: Dict[str, StrategyStats] = {}

    def admit(self, name: str, stats: StrategyStats) -> None:
        if name not in self._s:
            raise KeyError(name)
        if not stats.validated:
            raise ValueError("stats are not from independent validation")
        if stats.n_trades < self.min_trades:
            raise ValueError(f"sample too small: {stats.n_trades} < {self.min_trades}")
        if stats.expectancy_net <= 0:
            raise ValueError("net expectancy is not positive")
        self._stats[name] = stats
        self._status[name] = Status.ADMITTED

    def revoke(self, name: str) -> None:
        self._status[name] = Status.REVOKED

    def status(self, name: str) -> Status:
        return self._status[name]

    def stats(self, name: str) -> Optional[StrategyStats]:
        return self._stats.get(name)

    def select(self, regime: Regime) -> List[Strategy]:
        """Only ADMITTED strategies whose regime filter matches."""
        return [s for n, s in sorted(self._s.items())
                if self._status[n] is Status.ADMITTED and regime in s.allowed_regimes]
