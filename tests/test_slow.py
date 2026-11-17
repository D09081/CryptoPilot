import numpy as np
import pytest

from conftest import make_candles
from cryptopilot.models import Candles
from cryptopilot.profitability import MarketCosts
from cryptopilot.slow import CANDIDATES, SlowStrategy, run_slow_backtest

H4 = 4 * 3600_000
NOW = 1_800_000_000_000
Z = MarketCosts(0.0, 0.0, 0.0)


def series(n=900, drift=0.0006, vol=0.01, seed=1):
    rng = np.random.default_rng(seed)
    return make_candles(100 * np.exp(np.cumsum(drift + rng.normal(0, vol, n))), H4, now=NOW)


def test_all_candidates_run_and_are_one_at_a_time(rules):
    c = series()
    for s in CANDIDATES:
        t = sorted(run_slow_backtest("BTC/USDT", c, s, rules, Z, 10_000), key=lambda x: x.entry_ts)
        assert all(t[i].exit_ts <= t[i + 1].entry_ts for i in range(len(t) - 1))
        assert all(x.exit_reason in ("stop", "signal", "end") for x in t)


def test_entry_at_next_open_and_stop_below_entry(rules):
    c = series()
    t = run_slow_backtest("BTC/USDT", c, SlowStrategy("donchian", 60), rules, Z, 10_000)
    assert t
    idx = {int(ts): i for i, ts in enumerate(c.ts)}
    for x in t:
        assert x.entry == pytest.approx(c.open[idx[x.entry_ts]])      # zero costs: exact open


def test_no_lookahead_truncation(rules):
    c = series(1000)
    cut = 800
    short = Candles(H4, *(a[:cut] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume)))
    for s in CANDIDATES:
        a = run_slow_backtest("BTC/USDT", c, s, rules, Z, 10_000)
        b = run_slow_backtest("BTC/USDT", short, s, rules, Z, 10_000)
        lim = int(c.ts[cut - 2])
        ea = [t for t in a if t.exit_ts < lim and t.exit_reason != "end"]
        eb = [t for t in b if t.exit_ts < lim and t.exit_reason != "end"]
        assert ea == eb


def test_costs_reduce_pnl(rules):
    c = series()
    s = SlowStrategy("ema_trend", 50, 200)
    free = sum(t.pnl for t in run_slow_backtest("BTC/USDT", c, s, rules, Z, 10_000))
    paid = sum(t.pnl for t in run_slow_backtest("BTC/USDT", c, s, rules, MarketCosts(5, 5, 10), 10_000))
    assert paid < free


def test_risk_per_trade_respected(rules):
    c = series()
    for t in run_slow_backtest("BTC/USDT", c, SlowStrategy("momentum", 180), rules, Z, 1000.0):
        if t.exit_reason == "stop":
            assert -t.pnl <= 1000 * 0.005 * 1.5          # stop loss bounded near budget (gap slack)


def test_crash_gap_fills_at_open(rules):
    closes = 100 * 1.004 ** np.arange(700)
    closes[-1] = 50.0                                      # last bar crashes through the stop
    c = make_candles(closes, H4, now=NOW)
    t = run_slow_backtest("BTC/USDT", c, SlowStrategy("ema_trend", 50, 200), rules, Z, 10_000)
    last = t[-1]
    assert last.exit_reason in ("stop", "end") and last.exit <= 100 * 1.004 ** 698
