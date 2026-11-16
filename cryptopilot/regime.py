"""Market Regime Detector. Uses closed candles only; ambiguity or bad data -> UNCERTAIN."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from . import indicators as ind
from .models import Candles, Regime

MIN_BARS = 210  # EMA200 + warm-up
MIN_TREND_SEP = 0.002  # EMAs must be separated by >=0.2% to call a trend


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    reasons: Tuple[str, ...]


def detect_regime(candles: Candles, now_ms: int, spread_bps: Optional[float] = None,
                  max_spread_bps: float = 15.0, min_quote_volume: float = 0.0) -> RegimeResult:
    c = candles.closed(now_ms)
    ok, problems = c.quality(now_ms)
    if not ok:
        return RegimeResult(Regime.UNCERTAIN, tuple(problems))
    if len(c) < MIN_BARS:
        return RegimeResult(Regime.UNCERTAIN, (f"need {MIN_BARS} bars, have {len(c)}",))

    close, high, low, vol = c.close, c.high, c.low, c.volume
    if spread_bps is not None and spread_bps > max_spread_bps:
        return RegimeResult(Regime.LOW_LIQUIDITY, (f"spread {spread_bps:.1f} bps > {max_spread_bps}",))
    if min_quote_volume > 0 and float((close[-20:] * vol[-20:]).mean()) < min_quote_volume:
        return RegimeResult(Regime.LOW_LIQUIDITY, ("average quote volume below minimum",))

    a = ind.atr(high, low, close, 14)
    e20, e50, e200 = (ind.ema(close, n) for n in (20, 50, 200))
    vz = ind.volume_zscore(vol, 20)
    px, atr_now = close[-1], a[-1]

    if close[-1] - close[-2] <= -3 * atr_now and vz[-1] >= 3:
        return RegimeResult(Regime.PANIC, ("sharp drop on abnormal volume",))

    # Breakout levels use only bars strictly before the bar being judged.
    lvl_prev = high[-22:-2].max()
    lvl_now = high[-21:-1].max()
    if close[-2] > lvl_prev and close[-1] < lvl_prev:
        return RegimeResult(Regime.FALSE_BREAKOUT, ("closed back below broken level",))
    if close[-1] > lvl_now and vz[-1] >= 2:
        return RegimeResult(Regime.BREAKOUT, ("close above 20-bar high on volume",))

    sep_fast = (e20[-1] - e50[-1]) / e50[-1]
    sep_slow = (e50[-1] - e200[-1]) / e200[-1]
    if sep_fast > MIN_TREND_SEP and sep_slow > MIN_TREND_SEP and px > e50[-1]:
        return RegimeResult(Regime.UPTREND, ("EMA20>EMA50>EMA200, price>EMA50",))
    if sep_fast < -MIN_TREND_SEP and sep_slow < -MIN_TREND_SEP and px < e50[-1]:
        return RegimeResult(Regime.DOWNTREND, ("EMA20<EMA50<EMA200, price<EMA50",))

    hist = a[-101:-1]
    hist = hist[~np.isnan(hist)]
    if len(hist) >= 50:
        med = float(np.median(hist))
        if np.mean(hist < atr_now) >= 0.9 and atr_now >= 1.25 * med:
            return RegimeResult(Regime.HIGH_VOL, ("ATR in top decile of last 100 bars and >=1.25x median",))
        if np.mean(hist <= atr_now) <= 0.1 and atr_now <= 0.75 * med:
            return RegimeResult(Regime.LOW_VOL, ("ATR in bottom decile of last 100 bars and <=0.75x median",))

    if abs(e20[-1] - e50[-1]) / e50[-1] < 0.003 and abs(px - e50[-1]) / e50[-1] < 0.01:
        return RegimeResult(Regime.SIDEWAYS, ("EMAs converged, price near EMA50",))
    return RegimeResult(Regime.UNCERTAIN, ("no regime criteria met",))
