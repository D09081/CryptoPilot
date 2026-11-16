"""Causal technical indicators: value at index i depends only on data[:i+1]."""
from __future__ import annotations

import numpy as np


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def sma(x, n: int) -> np.ndarray:
    x = _arr(x)
    out = np.full(x.shape, np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x, n: int) -> np.ndarray:
    """EMA seeded with the SMA of the first n valid values."""
    x = _arr(x)
    out = np.full(x.shape, np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) == 0:
        return out
    s = valid[0]
    if len(x) - s < n:
        return out
    a = 2.0 / (n + 1)
    out[s + n - 1] = x[s:s + n].mean()
    for i in range(s + n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _wilder(x: np.ndarray, n: int, start: int) -> np.ndarray:
    out = np.full(x.shape, np.nan)
    if len(x) - start < n:
        return out
    out[start + n - 1] = x[start:start + n].mean()
    for i in range(start + n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    c = _arr(close)
    out = np.full(c.shape, np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag, al = g[:n].mean(), l[:n].mean()

    def val(a, b):
        if b == 0:
            return 100.0 if a > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + a / b)

    out[n] = val(ag, al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + g[i - 1]) / n
        al = (al * (n - 1) + l[i - 1]) / n
        out[i] = val(ag, al)
    return out


def true_range(high, low, close) -> np.ndarray:
    h, l, c = _arr(high), _arr(low), _arr(close)
    tr = h - l
    if len(c) > 1:
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    return tr


def atr(high, low, close, n: int = 14) -> np.ndarray:
    return _wilder(true_range(high, low, close), n, 0)


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    c = _arr(close)
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def vwap(high, low, close, volume, window: int | None = None) -> np.ndarray:
    tp = (_arr(high) + _arr(low) + _arr(close)) / 3.0
    v = _arr(volume)
    pv = tp * v
    if window is None:
        cv, cpv = np.cumsum(v), np.cumsum(pv)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cv > 0, cpv / cv, np.nan)
    out = np.full(v.shape, np.nan)
    for i in range(window - 1, len(v)):
        sv = v[i - window + 1:i + 1].sum()
        if sv > 0:
            out[i] = pv[i - window + 1:i + 1].sum() / sv
    return out


def volume_profile(close, volume, bins: int = 24) -> dict:
    c, v = _arr(close), _arr(volume)
    if len(c) == 0:
        raise ValueError("empty input")
    vols, edges = np.histogram(c, bins=bins, weights=v)
    k = int(np.argmax(vols))
    return {"edges": edges, "volumes": vols, "poc": float((edges[k] + edges[k + 1]) / 2)}


def volume_zscore(volume, n: int = 20) -> np.ndarray:
    """z-score of each bar's volume against the *previous* n bars (excludes itself)."""
    v = _arr(volume)
    out = np.full(v.shape, np.nan)
    for i in range(n, len(v)):
        w = v[i - n:i]
        sd = w.std()
        out[i] = (v[i] - w.mean()) / sd if sd > 0 else 0.0
    return out
