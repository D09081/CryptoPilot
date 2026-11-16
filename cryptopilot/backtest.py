"""Backtesting engine (long-only spot, one position at a time).

Anti look-ahead rules enforced here:
  * decisions use only candles closed at decision time (``window``);
  * the signal comes from bar j's close, the entry fills at bar j+1's OPEN;
  * stop and take-profit are checked from the entry bar onward; if both are hit
    inside one bar the STOP is assumed to fill first (pessimistic);
  * stop exits are worse than the stop price (spread + extra slippage; gaps fill at the open).

Indicators are computed on a trailing window of at most 300 bars per timeframe, exactly as
a live system would; the order book is not available historically, so the spread is an
assumed constant (``MarketCosts``)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from . import indicators as ind
from .models import Action, Candles, Regime
from .profitability import MarketCosts, unit_costs
from .regime import detect_regime
from .sizing import ExchangeRules, size_position
from .strategies import Strategy

WINDOW = 300
BLOCKED = (Regime.UNCERTAIN, Regime.LOW_LIQUIDITY, Regime.PANIC, Regime.FALSE_BREAKOUT)


@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy: str
    regime: str
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    qty: float
    pnl: float          # net of fees, spread and slippage (quote currency)
    fees: float
    exit_reason: str    # stop | take_profit | time | end


def window(c: Candles, now_ms: int, n: int = WINDOW) -> Candles:
    """Last ``n`` candles that are fully closed at ``now_ms``."""
    k = int(np.searchsorted(c.ts + c.tf_ms, now_ms, side="right"))
    lo = max(0, k - n)
    return Candles(c.tf_ms, *(a[lo:k] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume)))


def load_candles_csv(path: str, tf_ms: int) -> Candles:
    """Load candles from CSV. Accepts (a) a header row with ts/open/high/low/close/volume
    columns, or (b) raw OKX rows [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm] (newest first).
    Unconfirmed (still forming) rows are dropped; rows are sorted and de-duplicated."""
    rows = []
    with open(path, newline="") as f:
        data = list(csv.reader(f))
    if not data:
        raise ValueError("empty CSV")
    header = None
    try:
        float(data[0][0])
    except ValueError:
        header = [h.strip().lower() for h in data[0]]
        data = data[1:]
    if header:
        def col(*names):
            for nme in names:
                if nme in header:
                    return header.index(nme)
            raise ValueError(f"missing column {names}")
        i = [col("ts", "timestamp", "open_time"), col("open"), col("high"), col("low"),
             col("close"), col("volume", "vol")]
        conf = header.index("confirm") if "confirm" in header else None
    else:
        i = [0, 1, 2, 3, 4, 5]
        conf = 8 if len(data[0]) > 8 else None
    for r in data:
        if conf is not None and r[conf].strip() not in ("1", "true", "True"):
            continue
        rows.append([float(r[k]) for k in i])
    if not rows:
        raise ValueError("no confirmed candles")
    a = np.array(rows)
    a = a[np.argsort(a[:, 0], kind="stable")]
    _, uniq = np.unique(a[:, 0], return_index=True)
    a = a[np.sort(uniq)]
    return Candles(tf_ms, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])


@dataclass
class _Pos:
    entry_idx: int
    entry: float
    stop: float
    tp: float
    qty: float
    regime: str


def run_backtest(symbol: str, tfs: Dict[str, Candles], strategy: Strategy, rules: ExchangeRules,
                 market: MarketCosts, equity: float, risk_pct: float = 0.5,
                 max_hold_bars: int = 96, warmup: int = 120) -> List[Trade]:
    h4, h1, m15 = tfs["H4"], tfs["H1"], tfs["M15"]
    tf = m15.tf_ms
    n = len(m15)
    half = market.spread_bps / 1e4 / 2
    slip = market.slippage_bps / 1e4
    stop_slip = market.stop_slippage_bps / 1e4
    trades: List[Trade] = []
    pos: Optional[_Pos] = None
    cache_k, regime = -1, Regime.UNCERTAIN

    def close_pos(j, px, reason, maker, ts):
        nonlocal pos
        fee_in = pos.qty * pos.entry * rules.taker_fee
        fee_out = pos.qty * px * (rules.maker_fee if maker else rules.taker_fee)
        pnl = pos.qty * (px - pos.entry) - fee_in - fee_out
        trades.append(Trade(symbol, strategy.name, pos.regime, int(m15.ts[pos.entry_idx]), int(ts),
                            pos.entry, px, pos.qty, pnl, fee_in + fee_out, reason))
        pos = None

    for j in range(n):
        if pos is not None:
            if m15.low[j] <= pos.stop:
                px = min(pos.stop, m15.open[j]) * (1 - half - stop_slip)
                close_pos(j, px, "stop", False, m15.ts[j])
            elif m15.high[j] >= pos.tp:
                close_pos(j, pos.tp, "take_profit", True, m15.ts[j])
            elif j - pos.entry_idx + 1 >= max_hold_bars:
                close_pos(j, m15.close[j] * (1 - half - slip), "time", False, m15.ts[j])
        if pos is not None or j < warmup or j >= n - 1:
            continue
        if m15.ts[j + 1] != m15.ts[j] + tf:        # data gap: do not trade across it
            continue
        now = int(m15.ts[j] + tf)
        k4 = int(np.searchsorted(h4.ts + h4.tf_ms, now, side="right"))
        if k4 != cache_k:
            regime = detect_regime(window(h4, now), now, spread_bps=market.spread_bps).regime
            cache_k = k4
        if regime in BLOCKED:
            continue
        w15 = window(m15, now)
        if not w15.quality(now)[0]:
            continue
        prop = strategy.evaluate(w15, regime)
        if prop is None or prop.side is not Action.BUY:
            continue
        w1 = window(h1, now)
        if not w1.quality(now)[0] or len(w1) < 50:
            continue
        e50 = ind.ema(w1.close, 50)[-1]
        if not (e50 == e50) or w1.close[-1] <= e50:
            continue
        entry = m15.open[j + 1] * (1 + slip + half)
        if not (prop.stop < entry < prop.take_profit):
            continue
        _, cl, _, _ = unit_costs(entry, prop.stop, prop.take_profit, rules, market)
        size = size_position(equity, entry, prop.stop, rules, risk_pct, equity, cl)
        if not size.ok:
            continue
        pos = _Pos(j + 1, entry, prop.stop, prop.take_profit, size.qty, regime.value)

    if pos is not None:
        close_pos(n - 1, m15.close[-1] * (1 - half - slip), "end", False, m15.ts[-1])
    return trades
