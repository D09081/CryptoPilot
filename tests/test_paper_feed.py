import copy
import io
import json
import urllib.error

import numpy as np
import pytest

from conftest import make_candles
from cryptopilot import feed
from cryptopilot.models import Candles
from cryptopilot.paper import PaperEngine, new_state
from cryptopilot.profitability import MarketCosts
from cryptopilot.risk import RiskManager
from cryptopilot.sizing import ExchangeRules
from cryptopilot.slow import SlowStrategy, run_slow_backtest

H4 = 4 * 3600_000
NOW = 1_800_000_000_000
MKT = MarketCosts(2.0, 2.0, 5.0)
STRAT = SlowStrategy("momentum", 180)
START = 409           # last_ts index: processing starts at bar 410 (same warm-up as the backtester)


def walk(n=1100, seed=1, drift=0.0007, vol=0.012):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(drift + rng.normal(0, vol, n)))


def rules_for(sym):
    return ExchangeRules(sym, 0.1, 1e-8, 1e-5, 1.0, 0.001, 0.001)


def engine(symbols, state, paused=False):
    return PaperEngine(STRAT, {s: rules_for(s) for s in symbols}, MKT, RiskManager(), state, symbols, paused)


def one_symbol_data(n=1100, seed=1):
    return {"BTC/USDT": make_candles(walk(n, seed), H4, now=NOW)}


def key(trades):
    return [(t["entry_ts"], t["exit_ts"], t["exit_reason"]) for t in trades]


def test_matches_batch_backtester_single_symbol():
    data = one_symbol_data()
    c = data["BTC/USDT"]
    st = new_state(STRAT.name, 10_000.0)
    st["last_ts"] = int(c.ts[START])
    engine(["BTC/USDT"], st).process(data)
    bt = [t for t in run_slow_backtest("BTC/USDT", c, STRAT, rules_for("BTC/USDT"), MKT, 10_000.0)
          if t.exit_reason != "end" and t.entry_ts > c.ts[START]]
    assert len(bt) >= 3
    assert key(st["trades"]) == [(t.entry_ts, t.exit_ts, t.exit_reason) for t in bt]
    for a, b in zip(st["trades"], bt):
        assert a["entry"] == pytest.approx(b.entry) and a["exit"] == pytest.approx(b.exit)


def test_restart_gives_identical_result_and_is_idempotent():
    data = one_symbol_data()
    c = data["BTC/USDT"]
    cut = 800
    part = {"BTC/USDT": Candles(H4, *(a[:cut] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume)))}
    one = new_state(STRAT.name, 10_000.0); one["last_ts"] = int(c.ts[START])
    engine(["BTC/USDT"], one).process(data)
    two = new_state(STRAT.name, 10_000.0); two["last_ts"] = int(c.ts[START])
    engine(["BTC/USDT"], two).process(part)
    two = json.loads(json.dumps(two))                      # persisted between runs
    engine(["BTC/USDT"], two).process(data)
    assert two["trades"] == one["trades"] and two["cash"] == pytest.approx(one["cash"])
    before = copy.deepcopy(two)
    assert engine(["BTC/USDT"], two).process(data) == 0 and two == before


def test_first_run_is_forward_only():
    data = one_symbol_data()
    st = new_state(STRAT.name, 55.0)
    assert engine(["BTC/USDT"], st).process(data) == 0
    assert st["trades"] == [] and st["pos"] is None and st["last_ts"] == int(data["BTC/USDT"].ts[-1])


def test_two_pairs_never_hold_two_positions():
    data = {"BTC/USDT": make_candles(walk(2000, 1), H4, now=NOW),
            "ETH/USDT": make_candles(walk(2000, 2), H4, now=NOW)}
    st = new_state(STRAT.name, 10_000.0)
    st["last_ts"] = int(data["BTC/USDT"].ts[START])
    engine(list(data), st).process(data)
    t = sorted(st["trades"], key=lambda x: x["entry_ts"])
    assert len(t) >= 5 and {x["symbol"] for x in t} == {"BTC/USDT", "ETH/USDT"}
    assert all(t[i]["exit_ts"] <= t[i + 1]["entry_ts"] for i in range(len(t) - 1))


def test_pause_blocks_new_entries_only():
    data = one_symbol_data()
    st = new_state(STRAT.name, 10_000.0); st["last_ts"] = int(data["BTC/USDT"].ts[START])
    engine(["BTC/USDT"], st, paused=True).process(data)
    assert st["trades"] == [] and st["pos"] is None and st["cash"] == 10_000.0


def test_risk_manager_rejects_entries_in_deep_drawdown():
    data = one_symbol_data()
    st = new_state(STRAT.name, 10_000.0); st["last_ts"] = int(data["BTC/USDT"].ts[START])
    st["peak"] = 1e9                                       # equity is far below its peak -> max drawdown
    engine(["BTC/USDT"], st).process(data)
    assert st["trades"] == [] and any("RISK REJECT" in e["msg"] and "drawdown" in e["msg"] for e in st["events"])


def test_missed_bars_warns_and_skips_entry():
    data = one_symbol_data()
    c = data["BTC/USDT"]
    cut = 600                                              # feed window starts after our last processed bar
    trimmed = {"BTC/USDT": Candles(H4, *(a[cut:] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume)))}
    st = new_state(STRAT.name, 10_000.0); st["last_ts"] = int(c.ts[START])
    engine(["BTC/USDT"], st).process(trimmed)
    assert any("missed bars" in e["msg"] for e in st["events"])


# ---- feed -------------------------------------------------------------------
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass


def okx_opener(n_total=900, fail=False):
    ts_all = [NOW - (i + 1) * H4 for i in range(n_total)]           # all closed, newest first

    def op(url, timeout=0):
        if fail:
            raise urllib.error.HTTPError(url, 403, "geo", {}, None)
        after = None
        for part in url.split("?")[1].split("&"):
            if part.startswith("after="):
                after = int(part[6:])
        page = [t for t in ts_all if after is None or t < after][:300]
        rows = [[str(t), "1", "2", "0.5", "1.5", "10", "0", "0", "1"] for t in page]
        if after is None:
            rows.insert(0, [str(NOW), "1", "2", "0.5", "1.5", "10", "0", "0", "0"])   # forming candle
        return Resp(json.dumps({"code": "0", "msg": "", "data": rows}).encode())
    return op


def test_okx_feed_pages_and_drops_forming():
    c, src = feed.fetch_closed_h4("BTC-USDT", NOW + 1, 700, okx_opener())
    assert src == "okx" and len(c) >= 700 and c.ts[-1] == NOW - H4
    assert np.all(np.diff(c.ts) == H4)


def test_fallback_to_binance_when_okx_blocked():
    def op(url, timeout=0):
        if "okx.com" in url:
            raise urllib.error.HTTPError(url, 403, "geo", {}, None)
        rows = [[NOW - (i + 1) * H4, "1", "2", "0.5", "1.5", "10"] for i in range(1000)][::-1]
        return Resp(json.dumps(rows).encode())
    c, src = feed.fetch_closed_h4("BTC-USDT", NOW + 1, 700, op)
    assert src == "binance" and len(c) == 1000


def test_all_sources_fail_raises():
    def op(url, timeout=0):
        raise urllib.error.URLError("down")
    with pytest.raises(RuntimeError, match="all sources failed"):
        feed.fetch_closed_h4("BTC-USDT", NOW, 700, op)


def test_stale_feed_rejected():
    with pytest.raises(RuntimeError):
        feed.fetch_closed_h4("BTC-USDT", NOW + 30 * H4, 700, okx_opener())
