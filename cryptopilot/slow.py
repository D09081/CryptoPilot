"""Slow (H4) long-only trend strategies + single-timeframe backtester.

Pre-registered candidates (fixed BEFORE looking at results, small grid, see CANDIDATES):
  donchian   : enter on close above prior N-bar high, exit on close below prior N/2-bar low
  ema_trend  : enter while EMA(fast) > EMA(slow) and close > EMA(slow), exit when fast < slow
  momentum   : enter while L-bar return > 0 and close > EMA(200), exit when L-bar return < 0
All use a fixed 3*ATR(14) protective stop. Decisions use the closed bar; fills at the NEXT bar's open;
indicators are causal, so precomputing them on the full series cannot leak the future."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from . import indicators as ind
from .backtest import Trade
from .models import Candles
from .profitability import MarketCosts, unit_costs
from .sizing import ExchangeRules, size_position


@dataclass(frozen=True)
class SlowStrategy:
    kind: str
    p1: int
    p2: int = 0
    stop_atr: float = 3.0

    @property
    def name(self) -> str:
        return f"{self.kind}_{self.p1}" + (f"_{self.p2}" if self.p2 else "")

    def prepare(self, c: Candles) -> dict:
        h, l, cl = pd.Series(c.high), pd.Series(c.low), c.close
        d = {"atr": ind.atr(c.high, c.low, c.close, 14), "close": cl}
        if self.kind == "donchian":
            m = max(2, self.p1 // 2)
            d["up"] = h.rolling(self.p1).max().shift(1).to_numpy()
            d["dn"] = l.rolling(m).min().shift(1).to_numpy()
        elif self.kind == "ema_trend":
            d["f"], d["s"] = ind.ema(cl, self.p1), ind.ema(cl, self.p2)
        elif self.kind == "momentum":
            ret = np.full(len(cl), np.nan)
            ret[self.p1:] = cl[self.p1:] / cl[:-self.p1] - 1
            d["ret"], d["e200"] = ret, ind.ema(cl, 200)
        else:
            raise ValueError(self.kind)
        return d

    def entry(self, d, i) -> bool:
        if np.isnan(d["atr"][i]):
            return False
        if self.kind == "donchian":
            return bool(d["close"][i] > d["up"][i])          # NaN -> False
        if self.kind == "ema_trend":
            return bool(d["f"][i] > d["s"][i] and d["close"][i] > d["s"][i])
        return bool(d["ret"][i] > 0 and d["close"][i] > d["e200"][i])

    def exit(self, d, i) -> bool:
        if self.kind == "donchian":
            return bool(d["close"][i] < d["dn"][i])
        if self.kind == "ema_trend":
            return bool(d["f"][i] < d["s"][i])
        return bool(d["ret"][i] < 0)


CANDIDATES: List[SlowStrategy] = [
    SlowStrategy("donchian", 60), SlowStrategy("donchian", 120),
    SlowStrategy("ema_trend", 50, 200), SlowStrategy("ema_trend", 100, 400),
    SlowStrategy("momentum", 180), SlowStrategy("momentum", 360),
]


# Pre-registered "active" family (faster lookbacks => more trades). Declared before any result was seen.
ACTIVE_CANDIDATES: List[SlowStrategy] = [
    SlowStrategy("donchian", 20), SlowStrategy("donchian", 40),
    SlowStrategy("ema_trend", 20, 50), SlowStrategy("ema_trend", 30, 100),
    SlowStrategy("momentum", 42), SlowStrategy("momentum", 90),
]


# Pre-registered FAST family for H1 candles (declared before any H1 result was seen). Cumulative tried: 18.
FAST_CANDIDATES: List[SlowStrategy] = [
    SlowStrategy("donchian", 24), SlowStrategy("donchian", 48),
    SlowStrategy("ema_trend", 12, 48), SlowStrategy("ema_trend", 24, 96),
    SlowStrategy("momentum", 24), SlowStrategy("momentum", 72),
]


def run_slow_backtest(symbol: str, c: Candles, strat: SlowStrategy, rules: ExchangeRules,
                      market: MarketCosts, equity: float, risk_pct: float = 0.5,
                      warmup: int = 410) -> List[Trade]:
    d = strat.prepare(c)
    n = len(c)
    half, slip, sslip = market.spread_bps / 1e4 / 2, market.slippage_bps / 1e4, market.stop_slippage_bps / 1e4
    trades: List[Trade] = []
    pos = None          # dict(entry_idx, entry, stop, qty)
    pending_exit = False

    def close_pos(j, px, reason):
        nonlocal pos
        fee = pos["qty"] * pos["entry"] * rules.taker_fee + pos["qty"] * px * rules.taker_fee
        trades.append(Trade(symbol, strat.name, "slow", int(c.ts[pos["i"]]), int(c.ts[j]), pos["entry"], px,
                            pos["qty"], pos["qty"] * (px - pos["entry"]) - fee, fee, reason))
        pos = None

    for j in range(n):
        if pos is not None:
            if pending_exit:                                   # signal on bar j-1 close -> fill at open j
                close_pos(j, c.open[j] * (1 - half - slip), "signal")
                pending_exit = False
            elif j > pos["i"] - 1 and c.low[j] <= pos["stop"]:
                close_pos(j, min(pos["stop"], c.open[j]) * (1 - half - sslip), "stop")
            elif strat.exit(d, j) and j < n - 1:
                pending_exit = True
        if pos is not None or j < warmup or j >= n - 1:
            continue
        if c.ts[j + 1] != c.ts[j] + c.tf_ms or not strat.entry(d, j):
            continue
        entry = c.open[j + 1] * (1 + slip + half)
        stop = entry - strat.stop_atr * d["atr"][j]
        if not 0 < stop < entry:
            continue
        _, cl_cost, _, _ = unit_costs(entry, stop, entry * 1.5, rules, market)
        size = size_position(equity, entry, stop, rules, risk_pct, equity, cl_cost)
        if size.ok:
            pos = {"i": j + 1, "entry": entry, "stop": stop, "qty": size.qty}
            pending_exit = False
    if pos is not None:
        close_pos(n - 1, c.close[-1] * (1 - half - slip), "end")
    return trades
