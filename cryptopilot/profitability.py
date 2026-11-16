"""Profitability Gate: expected value after all costs, with statistical uncertainty.

The win probability is *not* the strategy "confidence". It is the lower bound of a
Wilson interval on the win rate observed in independent validation. Without a
validated sample the gate always rejects."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .sizing import ExchangeRules
from .strategies import StrategyStats


@dataclass(frozen=True)
class MarketCosts:
    spread_bps: float
    slippage_bps: float          # expected slippage on market entry
    stop_slippage_bps: float     # extra adverse slippage when a stop is hit


@dataclass(frozen=True)
class GateParams:
    min_trades: int = 30
    z: float = 1.645                 # one-sided ~95%
    min_ev_cost_ratio: float = 0.5   # EV must be >= ratio * expected costs
    partial_fill_prob: float = 0.05  # reduces expected filled size


@dataclass(frozen=True)
class GateResult:
    passed: bool
    ev_per_unit: float
    ev_total: float
    win_prob_lb: float
    cost_win_per_unit: float
    cost_loss_per_unit: float
    fees_total: float
    slippage_total: float
    reasons: Tuple[str, ...]


def wilson_lower_bound(wins: int, n: int, z: float) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def unit_costs(entry: float, stop: float, tp: float, rules: ExchangeRules, m: MarketCosts):
    """Per-unit costs for a winning and a losing trade (quote currency, positive numbers)."""
    half_spread = entry * m.spread_bps / 1e4 / 2
    fee_in = entry * rules.taker_fee
    slip_in = entry * m.slippage_bps / 1e4
    common = fee_in + slip_in + 2 * half_spread
    cost_win = common + tp * rules.maker_fee
    cost_loss = common + stop * rules.taker_fee + stop * m.stop_slippage_bps / 1e4
    return cost_win, cost_loss, fee_in, slip_in


def evaluate_gate(entry: float, stop: float, tp: float, qty: float, rules: ExchangeRules,
                  market: MarketCosts, stats: Optional[StrategyStats],
                  params: GateParams = GateParams()) -> GateResult:
    reasons = []
    cw, cl, fee_in, slip_in = unit_costs(entry, stop, tp, rules, market)
    fees_total = qty * (fee_in + tp * rules.maker_fee)
    slip_total = qty * slip_in

    def reject(msg, p=0.0, ev=0.0):
        return GateResult(False, ev, ev * qty, p, cw, cl, fees_total, slip_total, tuple(reasons + [msg]))

    if stats is None or not stats.validated:
        return reject("no independently validated statistics: no proven edge")
    if stats.n_trades < params.min_trades:
        return reject(f"sample too small ({stats.n_trades} < {params.min_trades})")
    if not (stop < entry < tp):
        return reject("invalid stop/entry/take-profit geometry")
    if qty < rules.min_qty or qty * entry < rules.min_notional:
        return reject("below exchange minimum order size")

    p = wilson_lower_bound(stats.wins, stats.n_trades, params.z)
    net_win = (tp - entry) - cw
    net_loss = -((entry - stop) + cl)
    ev = p * net_win + (1 - p) * net_loss
    exp_cost = p * cw + (1 - p) * cl
    if ev <= 0:
        return reject("expected value after costs is not positive", p, ev)
    if ev < params.min_ev_cost_ratio * exp_cost:
        return reject("edge too small relative to costs and uncertainty", p, ev)
    ev_total = ev * qty * (1 - params.partial_fill_prob * 0.5)
    return GateResult(True, ev, ev_total, p, cw, cl, fees_total, slip_total, ("edge exceeds costs",))
