import numpy as np
import pytest

from conftest import TF, make_candles
from cryptopilot.backtest import load_candles_csv, run_backtest, window
from cryptopilot.models import Action, Candles, Proposal, Regime
from cryptopilot.profitability import MarketCosts
from cryptopilot.strategies import Strategy

M15, H1, H4 = TF["M15"], TF["H1"], TF["H4"]
NOW = 1_800_000_000_000
MKT = MarketCosts(0.0, 0.0, 0.0)


class EveryBar(Strategy):
    """Buys whenever allowed; stop/tp as fixed fractions of the signal close."""
    name = "every_bar"
    allowed_regimes = frozenset({Regime.UPTREND})

    def __init__(self, stop=0.99, tp=1.02):
        self.stop, self.tp = stop, tp

    def _evaluate(self, c, regime):
        px = c.close[-1]
        return Proposal(Action.BUY, px, px * self.stop, px * self.tp, ("t",))


def tfs_from(m15_closes, up=True):
    h4 = make_candles(100 * 1.003 ** np.arange(300), H4, now=NOW)
    h1 = make_candles(100 * 1.003 ** np.arange(400), H1, now=NOW)
    return {"H4": h4, "H1": h1, "M15": make_candles(m15_closes, M15, now=NOW)}


def test_window_excludes_forming_candle():
    c = make_candles(np.full(50, 100.0), M15, now=NOW)
    assert len(window(c, NOW)) == 50
    assert len(window(c, NOW - 1)) == 49
    assert len(window(c, NOW - M15)) == 49
    assert len(window(c, NOW, n=10)) == 10


def test_entry_fills_at_next_open_and_tp(rules):
    closes = np.full(200, 100.0)
    c = make_candles(closes, M15, now=NOW)
    tf = tfs_from(closes)
    o, h, l, cl = c.open.copy(), c.high.copy(), c.low.copy(), c.close.copy()
    o[121] = 100.5; h[121] = 101.0      # entry bar open differs from signal close 100
    h[130] = 103.0                      # take profit (102) reached later
    tf["M15"] = Candles(M15, c.ts, o, h, l, cl, c.volume)
    t = run_backtest("BTC/USDT", tf, EveryBar(), rules, MKT, equity=10_000)
    first = [x for x in t if x.entry_ts == int(c.ts[121])]
    assert first and first[0].entry == pytest.approx(100.5)   # NOT the signal close
    assert first[0].exit_reason == "take_profit" and first[0].exit == pytest.approx(102.0)


def test_stop_wins_when_both_hit_same_bar(rules):
    closes = np.full(200, 100.0)
    c = make_candles(closes, M15, now=NOW)
    h, l = c.high.copy(), c.low.copy()
    h[122] = 110.0; l[122] = 90.0       # same bar touches TP (102) and stop (99)
    tf = tfs_from(closes)
    tf["M15"] = Candles(M15, c.ts, c.open, h, l, c.close, c.volume)
    t = run_backtest("BTC/USDT", tf, EveryBar(), rules, MKT, equity=10_000)
    tr = [x for x in t if x.entry_ts == int(c.ts[121])][0]
    assert tr.exit_reason == "stop" and tr.exit <= 99.0 and tr.pnl < 0


def test_gap_down_fills_at_open_not_stop(rules):
    closes = np.full(200, 100.0)
    c = make_candles(closes, M15, now=NOW)
    o, h, l, cl = c.open.copy(), c.high.copy(), c.low.copy(), c.close.copy()
    o[122] = 95.0; h[122] = 96.0; l[122] = 94.0; cl[122] = 95.0
    tf = tfs_from(closes)
    tf["M15"] = Candles(M15, c.ts, o, h, l, cl, c.volume)
    tr = [x for x in run_backtest("BTC/USDT", tf, EveryBar(), rules, MKT, 10_000)
          if x.entry_ts == int(c.ts[121])][0]
    assert tr.exit_reason == "stop" and tr.exit == pytest.approx(95.0)


def test_costs_reduce_pnl(rules):
    closes = 100 * 1.0004 ** np.arange(260)
    base = run_backtest("BTC/USDT", tfs_from(closes), EveryBar(), rules, MKT, 10_000)
    costly = run_backtest("BTC/USDT", tfs_from(closes), EveryBar(), rules,
                          MarketCosts(10.0, 5.0, 10.0), 10_000)
    assert base and costly
    assert sum(t.fees for t in base) > 0
    assert sum(t.pnl for t in costly) < sum(t.pnl for t in base)


def test_no_lookahead_future_data_does_not_change_past_trades(rules):
    rng = np.random.default_rng(11)
    closes = 100 * np.exp(np.cumsum(0.0003 + rng.normal(0, 0.002, 300)))
    full = tfs_from(closes)
    cut = 220
    short = dict(full)
    m = full["M15"]
    short["M15"] = Candles(M15, *(a[:cut] for a in (m.ts, m.open, m.high, m.low, m.close, m.volume)))
    a = run_backtest("BTC/USDT", full, EveryBar(), rules, MKT, 10_000)
    b = run_backtest("BTC/USDT", short, EveryBar(), rules, MKT, 10_000)
    ts_cut = int(m.ts[cut - 1])
    early_a = [t for t in a if t.exit_ts < ts_cut and t.exit_reason != "end"]
    early_b = [t for t in b if t.exit_ts < ts_cut and t.exit_reason != "end"]
    assert early_a == early_b and len(early_a) > 0


def test_one_position_at_a_time(rules):
    rng = np.random.default_rng(2)
    closes = 100 * np.exp(np.cumsum(0.0003 + rng.normal(0, 0.002, 300)))
    t = run_backtest("BTC/USDT", tfs_from(closes), EveryBar(), rules, MKT, 10_000)
    t = sorted(t, key=lambda x: x.entry_ts)
    assert all(t[i].exit_ts <= t[i + 1].entry_ts for i in range(len(t) - 1))


def test_position_risk_within_budget(rules):
    closes = np.full(200, 100.0)
    t = run_backtest("BTC/USDT", tfs_from(closes), EveryBar(), rules, MKT, 10_000)
    assert t and all(x.qty * 1.0 <= 10_000 * 0.005 + 1e-6 for x in t)   # risk = qty*(1.0 stop dist)


def test_gap_in_data_blocks_entry(rules):
    closes = np.full(200, 100.0)
    c = make_candles(closes, M15, now=NOW)
    h = c.high.copy(); h[121:] = 103.0          # TP hit on every entry bar -> always flat
    c = Candles(M15, c.ts, c.open, h, c.low, c.close, c.volume)
    keep = np.ones(200, bool); keep[130] = False
    tf = tfs_from(closes)
    tf["M15"] = Candles(M15, *(a[keep] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume)))
    entries = {x.entry_ts for x in run_backtest("BTC/USDT", tf, EveryBar(), rules, MKT, 10_000)}
    assert int(c.ts[129]) in entries                      # trades fine before the gap
    assert int(c.ts[131]) not in entries                  # signal bar 129 is followed by a gap
    assert all(e <= int(c.ts[129]) for e in entries)      # series with a gap in its window is not traded


def test_csv_loader_okx_raw_and_header(tmp_path):
    raw = tmp_path / "raw.csv"      # OKX layout, newest first, one unconfirmed + one duplicate
    raw.write_text("3000,1,2,0.5,1.5,10,0,0,0\n2000,1,2,0.5,1.5,10,0,0,1\n1000,1,2,0.5,1.4,10,0,0,1\n1000,1,2,0.5,1.4,10,0,0,1\n")
    c = load_candles_csv(str(raw), 1000)
    assert list(c.ts) == [1000, 2000] and c.close[0] == 1.4
    hdr = tmp_path / "h.csv"
    hdr.write_text("timestamp,open,high,low,close,volume\n2000,1,2,0.5,1.5,10\n1000,1,2,0.5,1.4,5\n")
    c2 = load_candles_csv(str(hdr), 1000)
    assert list(c2.ts) == [1000, 2000] and c2.volume[0] == 5
    with pytest.raises(ValueError):
        (tmp_path / "e.csv").write_text("")
        load_candles_csv(str(tmp_path / "e.csv"), 1000)
