import numpy as np
import pytest

from cryptopilot.models import Candles
from cryptopilot.sizing import ExchangeRules

TF = {"H4": 4 * 3600_000, "H1": 3600_000, "M15": 900_000}
NOW = 1_800_000_000_000  # arbitrary; every series' last candle closes exactly at NOW


def make_candles(closes, tf_ms, now=NOW, volume=None, wick=0.001):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    high = np.maximum(opens, closes) * (1 + wick)
    low = np.minimum(opens, closes) * (1 - wick)
    vol = np.asarray(volume, dtype=float) if volume is not None else 100.0 + (np.arange(n) % 5)
    ts = now - (n - np.arange(n)) * tf_ms
    return Candles(tf_ms, ts.astype(np.int64), opens, high, low, closes, vol)


@pytest.fixture
def rules():
    # Illustrative fixture values (NOT real OKX rules).
    return ExchangeRules("BTC/USDT", tick_size=0.1, lot_step=1e-8, min_qty=1e-5,
                         min_notional=1.0, taker_fee=0.001, maker_fee=0.0008)
