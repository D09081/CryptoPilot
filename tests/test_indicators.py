import numpy as np
import pytest

from cryptopilot import indicators as ind


def test_ema_constant_series():
    out = ind.ema(np.full(50, 7.0), 20)
    assert np.isnan(out[:19]).all() and np.allclose(out[19:], 7.0)


def test_sma_known_values():
    assert np.allclose(ind.sma([1, 2, 3, 4, 5], 3)[2:], [2, 3, 4])


def test_rsi_extremes():
    up = ind.rsi(np.arange(1, 40, dtype=float))
    assert up[-1] == 100.0
    assert ind.rsi(np.full(40, 5.0))[-1] == 50.0
    assert ind.rsi(np.arange(40, 1, -1, dtype=float))[-1] == 0.0


def test_atr_constant_range():
    c = np.full(40, 100.0)
    assert np.allclose(ind.atr(c + 1, c - 1, c)[13:], 2.0)


def test_macd_hist_is_line_minus_signal():
    c = 100 + np.cumsum(np.sin(np.arange(120)))
    line, sig, hist = ind.macd(c)
    m = ~np.isnan(hist)
    assert m.any() and np.allclose(hist[m], (line - sig)[m])


def test_vwap_cumulative_and_window():
    h = l = c = np.array([10.0, 20.0, 30.0])
    v = np.array([1.0, 1.0, 2.0])
    assert ind.vwap(h, l, c, v)[-1] == pytest.approx((10 + 20 + 60) / 4)
    assert ind.vwap(h, l, c, v, window=2)[-1] == pytest.approx((20 + 60) / 3)


def test_volume_profile_poc():
    close = np.array([100.0, 100.1, 100.2, 110.0])
    vp = ind.volume_profile(close, np.array([1, 1, 1, 50.0]), bins=5)
    assert vp["poc"] > 108


def test_volume_zscore_spike_and_excludes_self():
    v = np.array([100.0 + (i % 3) for i in range(30)] + [1000.0])
    z = ind.volume_zscore(v, 20)
    assert z[-1] > 10 and np.isnan(z[:20]).all()


@pytest.mark.parametrize("fn", [
    lambda c: ind.ema(c, 20), lambda c: ind.rsi(c), lambda c: ind.macd(c)[2],
    lambda c: ind.atr(c * 1.01, c * 0.99, c), lambda c: ind.volume_zscore(c),
    lambda c: ind.vwap(c, c, c, c + 1),
])
def test_no_lookahead(fn):
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(size=200))
    full, part = fn(c), fn(c[:120])
    assert np.allclose(full[:120], part, equal_nan=True)
