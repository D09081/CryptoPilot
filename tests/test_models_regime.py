import numpy as np

from conftest import NOW, TF, make_candles
from cryptopilot.models import Candles, Regime
from cryptopilot.regime import detect_regime

H4 = TF["H4"]


def test_closed_drops_forming_candle():
    c = make_candles(np.full(10, 100.0), H4)
    extra = Candles(H4, np.append(c.ts, NOW), *(np.append(a, a[-1]) for a in
                    (c.open, c.high, c.low, c.close, c.volume)))
    assert len(extra) == 11 and len(extra.closed(NOW)) == 10


def test_quality_detects_problems():
    c = make_candles(np.full(10, 100.0), H4)
    assert c.quality(NOW)[0]
    assert "stale data" in c.quality(NOW + 10 * H4)[1]
    gap = Candles(H4, np.delete(c.ts, 4), *(np.delete(a, 4) for a in
                  (c.open, c.high, c.low, c.close, c.volume)))
    assert "gap in candles" in gap.quality(NOW)[1]
    bad = Candles(H4, c.ts, c.open, c.high * 0.5, c.low, c.close, c.volume)
    assert "inconsistent OHLC" in bad.quality(NOW)[1]
    nan = Candles(H4, c.ts, c.open, c.high, c.low, np.where(np.arange(10) == 3, np.nan, c.close), c.volume)
    assert not nan.quality(NOW)[0]


def test_uptrend():
    assert detect_regime(make_candles(100 * 1.003 ** np.arange(300), H4), NOW).regime is Regime.UPTREND


def test_downtrend():
    assert detect_regime(make_candles(100 * 0.997 ** np.arange(300), H4), NOW).regime is Regime.DOWNTREND


def test_sideways():
    closes = 100 + 0.2 * (-1.0) ** np.arange(300)
    assert detect_regime(make_candles(closes, H4), NOW).regime is Regime.SIDEWAYS


def test_insufficient_data_is_uncertain():
    r = detect_regime(make_candles(np.full(100, 100.0), H4), NOW)
    assert r.regime is Regime.UNCERTAIN


def test_stale_data_is_uncertain():
    r = detect_regime(make_candles(100 * 1.003 ** np.arange(300), H4), NOW + 20 * H4)
    assert r.regime is Regime.UNCERTAIN and "stale data" in r.reasons


def test_wide_spread_is_low_liquidity():
    c = make_candles(100 * 1.003 ** np.arange(300), H4)
    assert detect_regime(c, NOW, spread_bps=50).regime is Regime.LOW_LIQUIDITY


def test_panic_on_crash_with_volume():
    closes = 100 + 0.2 * (-1.0) ** np.arange(300)
    closes[-1] = 90.0
    vol = 100.0 + (np.arange(300) % 5)
    vol[-1] = 5000
    assert detect_regime(make_candles(closes, H4, volume=vol), NOW).regime is Regime.PANIC


def test_breakout_needs_volume():
    closes = 100 + 0.2 * (-1.0) ** np.arange(300)
    closes[-1] = 103.0
    vol = 100.0 + (np.arange(300) % 5)
    assert detect_regime(make_candles(closes, H4, volume=vol), NOW).regime is not Regime.BREAKOUT
    vol[-1] = 5000
    assert detect_regime(make_candles(closes, H4, volume=vol), NOW).regime is Regime.BREAKOUT


def test_false_breakout():
    closes = 100 + 0.2 * (-1.0) ** np.arange(300)
    closes[-2], closes[-1] = 103.0, 100.0
    assert detect_regime(make_candles(closes, H4), NOW).regime is Regime.FALSE_BREAKOUT


def test_high_volatility():
    closes = 100 + 0.2 * (-1.0) ** np.arange(300)
    c = make_candles(closes, H4, wick=0.001)
    wide = make_candles(closes, H4, wick=0.001)
    high = wide.high.copy(); low = wide.low.copy()
    high[-3:] *= 1.02; low[-3:] *= 0.98
    wide = Candles(H4, wide.ts, wide.open, high, low, wide.close, wide.volume)
    assert detect_regime(wide, NOW).regime is Regime.HIGH_VOL
    assert detect_regime(c, NOW).regime is Regime.SIDEWAYS
