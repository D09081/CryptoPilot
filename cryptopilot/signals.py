"""Signal Engine: regime -> admitted strategies -> conflict check -> sizing -> profitability gate.
Any failed step yields HOLD with the reasons. The Risk Manager is applied afterwards, separately."""
from __future__ import annotations

from typing import Dict, Optional

from . import indicators as ind
from .models import Action, Candles, Regime, Signal
from .profitability import GateParams, MarketCosts, evaluate_gate, unit_costs
from .regime import detect_regime
from .sizing import ExchangeRules, size_position
from .strategies import StrategyRegistry

H4, H1, M15 = "H4", "H1", "M15"


class SignalEngine:
    def __init__(self, registry: StrategyRegistry, risk_pct: float, gate: GateParams = GateParams()):
        self.registry = registry
        self.risk_pct = risk_pct
        self.gate = gate

    def generate(self, symbol: str, tfs: Dict[str, Candles], now_ms: int, rules: ExchangeRules,
                 market: MarketCosts, equity: float, free_quote: float,
                 holdings_qty: float = 0.0) -> Signal:
        # Closed candles only, per timeframe, validated independently.
        closed: Dict[str, Candles] = {}
        for tf in (H4, H1, M15):
            if tf not in tfs:
                return Signal.hold(symbol, Regime.UNCERTAIN, [f"missing timeframe {tf}"], "bad")
            c = tfs[tf].closed(now_ms)
            ok, problems = c.quality(now_ms)
            if not ok:
                return Signal.hold(symbol, Regime.UNCERTAIN, [f"{tf}: {p}" for p in problems], "bad")
            closed[tf] = c

        rr = detect_regime(closed[H4], now_ms, spread_bps=market.spread_bps)
        if rr.regime in (Regime.UNCERTAIN, Regime.LOW_LIQUIDITY, Regime.PANIC, Regime.FALSE_BREAKOUT):
            return Signal.hold(symbol, rr.regime, ("regime blocks trading",) + rr.reasons, "ok")

        strategies = self.registry.select(rr.regime)
        if not strategies:
            return Signal.hold(symbol, rr.regime, ["no admitted strategy for this regime"], "ok")

        proposals = [(s, s.evaluate(closed[M15], rr.regime)) for s in strategies]
        proposals = [(s, p) for s, p in proposals if p is not None]
        if not proposals:
            return Signal.hold(symbol, rr.regime, ["admitted strategies see no setup"], "ok")
        if len({p.side for _, p in proposals}) > 1:
            return Signal.hold(symbol, rr.regime, ["conflicting strategy signals"], "ok")

        strat, prop = max(proposals, key=lambda sp: self.registry.stats(sp[0].name).expectancy_net)

        if prop.side is Action.SELL:
            if holdings_qty <= 0:
                return Signal.hold(symbol, rr.regime, ["exit signal but no holdings (spot: no shorting)"], "ok")
            return Signal(Action.SELL, symbol, rr.regime, strat.name, entry=prop.entry,
                          qty=holdings_qty, reasons=prop.reasons, data_quality="ok")

        # BUY: H1 confirmation on the higher timeframe's own closed candles.
        h1 = closed[H1]
        e50 = ind.ema(h1.close, 50)[-1]
        if not (e50 == e50) or h1.close[-1] <= e50:
            return Signal.hold(symbol, rr.regime, ["H1 does not confirm (close <= EMA50)"], "ok")

        cw, cl, _, _ = unit_costs(prop.entry, prop.stop, prop.take_profit, rules, market)
        size = size_position(equity, prop.entry, prop.stop, rules, self.risk_pct, free_quote, cl)
        if not size.ok:
            return Signal.hold(symbol, rr.regime, [size.reason], "ok")

        g = evaluate_gate(prop.entry, prop.stop, prop.take_profit, size.qty, rules, market,
                          self.registry.stats(strat.name), self.gate)
        if not g.passed:
            return Signal.hold(symbol, rr.regime, ("profitability gate: " + g.reasons[-1],), "ok")

        return Signal(Action.BUY, symbol, rr.regime, strat.name, prop.entry, prop.stop,
                      prop.take_profit, size.qty, size.risk_amount, g.fees_total, g.slippage_total,
                      g.ev_total, prop.reasons + g.reasons, "ok")
