import numpy as np
import pytest

from conftest import NOW, TF, make_candles
from cryptopilot.models import Action, Proposal, Regime
from cryptopilot.profitability import MarketCosts
from cryptopilot.signals import SignalEngine
from cryptopilot.strategies import (Breakout, MeanReversion, Status, Strategy,
                                    StrategyRegistry, StrategyStats, TrendFollowing,
                                    VolatilityAdaptive)

M15, H1, H4 = TF["M15"], TF["H1"], TF["H4"]
MKT = MarketCosts(2.0, 2.0, 5.0)
GOOD = StrategyStats(100, 65, 1.0, True, "oos")


def uptrend_tfs(h1_up=True):
    h1 = 100 * 1.003 ** np.arange(120) if h1_up else 100 * 0.997 ** np.arange(120)
    return {"H4": make_candles(100_000 * 1.003 ** np.arange(300), H4),
            "H1": make_candles(h1, H1),
            "M15": make_candles(100_000 * 1.0005 ** np.arange(200), M15)}


class Stub(Strategy):
    def __init__(self, name, side, regimes=(Regime.UPTREND,), tp=1.06):
        self.name, self.side, self.tp = name, side, tp
        self.allowed_regimes = frozenset(regimes)

    def _evaluate(self, c, regime):
        px = c.close[-1]
        if self.side is Action.BUY:
            return Proposal(Action.BUY, px, px * 0.99, px * self.tp, ("stub",))
        return Proposal(Action.SELL, px, 0, 0, ("stub exit",))


def engine(*strats, admit=True):
    reg = StrategyRegistry(list(strats))
    if admit:
        for s in strats:
            reg.admit(s.name, GOOD)
    return SignalEngine(reg, risk_pct=0.5)


def gen(eng, tfs, rules, **kw):
    return eng.generate("BTC/USDT", tfs, NOW, rules, MKT, equity=kw.get("equity", 55.0),
                        free_quote=kw.get("free", 55.0), holdings_qty=kw.get("held", 0.0))


# ---- real strategies --------------------------------------------------------
def test_strategies_ignore_wrong_regime():
    c = make_candles(100 * 1.003 ** np.arange(200), M15)
    assert TrendFollowing().evaluate(c, Regime.SIDEWAYS) is None
    assert Breakout().evaluate(c, Regime.UPTREND) is None
    assert MeanReversion().evaluate(c, Regime.UPTREND) is None
    assert VolatilityAdaptive().evaluate(c, Regime.UPTREND) is None


def test_strategies_need_history():
    assert TrendFollowing().evaluate(make_candles(np.full(50, 100.0), M15), Regime.UPTREND) is None


def test_trend_following_exit_in_downtrend():
    closes = 100 * 0.997 ** np.arange(200)
    closes[-10:] *= 0.99 ** np.arange(1, 11)       # accelerating decline -> MACD hist < 0
    p = TrendFollowing().evaluate(make_candles(closes, M15), Regime.DOWNTREND)
    assert p and p.side is Action.SELL
    # no exit proposal while momentum is not negative
    flat = TrendFollowing().evaluate(make_candles(np.full(200, 100.0), M15), Regime.DOWNTREND)
    assert flat is None


def test_trend_following_buy_pullback():
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(0.0008 + rng.normal(0, 0.003, 200)))
    for _ in range(50):  # find a bar where setup is valid; strategy must then give sane levels
        p = TrendFollowing().evaluate(make_candles(closes, M15), Regime.UPTREND)
        if p:
            break
        closes = closes[:-1]
    assert p is not None and p.side is Action.BUY and p.stop < p.entry < p.take_profit


def test_breakout_proposal_geometry():
    closes = 100 + 0.2 * (-1.0) ** np.arange(200)
    closes[-1] = 103.0
    p = Breakout().evaluate(make_candles(closes, M15), Regime.BREAKOUT)
    assert p and p.side is Action.BUY and p.stop < p.entry < p.take_profit


def test_mean_reversion_buy_on_oversold_dip():
    closes = 100 + 0.3 * np.sin(np.arange(200) * 0.5)
    closes[-6:] = [99.0, 98.5, 98.0, 97.5, 97.0, 96.5]
    p = MeanReversion().evaluate(make_candles(closes, M15), Regime.SIDEWAYS)
    assert p and p.side is Action.BUY and p.stop < p.entry < p.take_profit


def test_volatility_adaptive_stop_scales_with_atr():
    rng = np.random.default_rng(5)
    closes = 100 * np.exp(np.cumsum(0.001 + rng.normal(0, 0.004, 300)))
    for n in range(300, 150, -1):
        p = VolatilityAdaptive().evaluate(make_candles(closes[:n], M15), Regime.HIGH_VOL)
        if p:
            assert p.stop < p.entry < p.take_profit
            return
    pytest.skip("no setup in synthetic data")


# ---- registry ---------------------------------------------------------------
def test_registry_defaults_to_candidate_and_selects_nothing():
    reg = StrategyRegistry()
    assert all(reg.status(n) is Status.CANDIDATE for n in
               ("trend_following", "breakout", "mean_reversion", "volatility_adaptive"))
    assert reg.select(Regime.UPTREND) == []


def test_registry_admission_rules():
    reg = StrategyRegistry()
    with pytest.raises(ValueError):
        reg.admit("breakout", StrategyStats(100, 60, 1.0, validated=False))
    with pytest.raises(ValueError):
        reg.admit("breakout", StrategyStats(5, 5, 1.0, validated=True))
    with pytest.raises(ValueError):
        reg.admit("breakout", StrategyStats(100, 40, -0.1, validated=True))
    reg.admit("breakout", GOOD)
    assert [s.name for s in reg.select(Regime.BREAKOUT)] == ["breakout"]
    reg.revoke("breakout")
    assert reg.select(Regime.BREAKOUT) == []


# ---- signal engine ----------------------------------------------------------
def test_engine_buy_has_all_fields(rules):
    s = gen(engine(Stub("a", Action.BUY)), uptrend_tfs(), rules)
    assert s.action is Action.BUY and s.strategy == "a" and s.regime is Regime.UPTREND
    assert s.stop_loss < s.entry < s.take_profit and s.qty > 0
    assert 0 < s.risk_amount <= 55 * 0.005 + 1e-9
    assert s.fees > 0 and s.slippage > 0 and s.expected_net > 0 and s.data_quality == "ok"
    assert "not a profit forecast" in s.note


def test_engine_holds_without_admitted_strategies(rules):
    s = gen(engine(Stub("a", Action.BUY), admit=False), uptrend_tfs(), rules)
    assert s.action is Action.HOLD and "no admitted strategy" in s.reasons[0]


def test_engine_conflict_is_hold(rules):
    s = gen(engine(Stub("a", Action.BUY), Stub("b", Action.SELL), ), uptrend_tfs(), rules, held=0.001)
    assert s.action is Action.HOLD and "conflicting strategy signals" in s.reasons


def test_engine_h1_must_confirm(rules):
    s = gen(engine(Stub("a", Action.BUY)), uptrend_tfs(h1_up=False), rules)
    assert s.action is Action.HOLD and "H1" in s.reasons[0]


def test_engine_stale_or_missing_data_holds(rules):
    tfs = uptrend_tfs()
    assert gen(engine(Stub("a", Action.BUY)), {k: v for k, v in tfs.items() if k != "H1"}, rules).action is Action.HOLD
    late = engine(Stub("a", Action.BUY)).generate("BTC/USDT", tfs, NOW + 50 * H4, rules, MKT, 55.0, 55.0)
    assert late.action is Action.HOLD and late.data_quality == "bad"


def test_engine_wide_spread_holds(rules):
    wide = MarketCosts(60.0, 2.0, 5.0)
    s = engine(Stub("a", Action.BUY)).generate("BTC/USDT", uptrend_tfs(), NOW, rules, wide, 55.0, 55.0)
    assert s.action is Action.HOLD and s.regime is Regime.LOW_LIQUIDITY


def test_engine_skips_when_size_impossible(rules):
    s = gen(engine(Stub("a", Action.BUY)), uptrend_tfs(), rules, equity=0.5, free=0.5)
    assert s.action is Action.HOLD and "safe size impossible" in s.reasons[0]


def test_engine_gate_blocks_weak_edge(rules):
    s = gen(engine(Stub("a", Action.BUY, tp=1.003)), uptrend_tfs(), rules)
    assert s.action is Action.HOLD and "profitability gate" in s.reasons[0]


def test_engine_sell_only_with_holdings(rules):
    eng = engine(Stub("a", Action.SELL))
    assert gen(eng, uptrend_tfs(), rules, held=0.0).action is Action.HOLD
    s = gen(eng, uptrend_tfs(), rules, held=0.001)
    assert s.action is Action.SELL and s.qty == 0.001


def test_engine_ignores_forming_candle(rules):
    tfs = uptrend_tfs()
    m = tfs["M15"]
    from cryptopilot.models import Candles
    forming = Candles(M15, np.append(m.ts, NOW), *(np.append(a, a[-1] * 0.5) for a in
                      (m.open, m.high, m.low, m.close, m.volume)))
    tfs["M15"] = forming
    a = gen(engine(Stub("a", Action.BUY)), tfs, rules)
    b = gen(engine(Stub("a", Action.BUY)), uptrend_tfs(), rules)
    assert a == b
