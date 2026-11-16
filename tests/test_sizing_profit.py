import pytest

from cryptopilot.profitability import (GateParams, MarketCosts, evaluate_gate,
                                       unit_costs, wilson_lower_bound)
from cryptopilot.sizing import ExchangeRules, floor_to_step, size_position
from cryptopilot.strategies import StrategyStats

MKT = MarketCosts(spread_bps=2.0, slippage_bps=2.0, stop_slippage_bps=5.0)
GOOD = StrategyStats(n_trades=100, wins=65, expectancy_net=1.0, validated=True, source="oos")


def test_floor_to_step_precision():
    assert floor_to_step(0.123456789, 1e-5) == pytest.approx(0.12345)
    assert floor_to_step(1.0, 0.1) == pytest.approx(1.0)
    assert floor_to_step(0.3, 0.1) == pytest.approx(0.3)   # no float artefact (0.29999 -> 0.2)


def test_size_respects_risk_budget(rules):
    s = size_position(55.0, 100_000, 99_000, rules, 0.5, free_quote=55.0)
    assert s.ok and s.risk_amount <= 55 * 0.005 + 1e-9


def test_size_includes_extra_costs(rules):
    a = size_position(55.0, 100_000, 99_000, rules, 0.5, 55.0)
    b = size_position(55.0, 100_000, 99_000, rules, 0.5, 55.0, extra_loss_per_unit=500)
    assert b.qty < a.qty


def test_skip_below_min_qty(rules):
    s = size_position(55.0, 100_000, 50_000, rules, 0.01, 55.0)
    assert not s.ok and "minimum" in s.reason


def test_skip_below_min_notional():
    r = ExchangeRules("X", 0.1, 1e-8, 1e-5, min_notional=50.0, taker_fee=0.001)
    assert not size_position(55.0, 100_000, 99_000, r, 0.5, 55.0).ok


def test_cash_cap(rules):
    s = size_position(10_000.0, 100_000, 99_000, rules, 0.5, free_quote=20.0)
    assert s.ok and s.notional * (1 + rules.taker_fee) <= 20.0


@pytest.mark.parametrize("stop", [0.0, -1.0, 100_000, 101_000])
def test_invalid_stop(rules, stop):
    assert not size_position(55.0, 100_000, stop, rules, 0.5, 55.0).ok


def test_wilson_bounds():
    assert wilson_lower_bound(0, 0, 1.645) == 0.0
    assert wilson_lower_bound(60, 100, 1.645) < 0.6
    assert wilson_lower_bound(600, 1000, 1.645) > wilson_lower_bound(60, 100, 1.645)


def test_costs_are_positive_and_loss_costs_more(rules):
    cw, cl, fee_in, slip_in = unit_costs(100_000, 99_000, 106_000, rules, MKT)
    assert cw > 0 and cl > cw and fee_in == pytest.approx(100.0)


def test_gate_rejects_without_validated_stats(rules):
    for st in (None, StrategyStats(100, 90, 5.0, validated=False)):
        g = evaluate_gate(100_000, 99_000, 106_000, 0.0002, rules, MKT, st)
        assert not g.passed and "no independently validated" in g.reasons[-1]


def test_gate_rejects_small_sample(rules):
    g = evaluate_gate(100_000, 99_000, 106_000, 0.0002, rules, MKT, StrategyStats(10, 9, 5.0, True))
    assert not g.passed and "sample too small" in g.reasons[-1]


def test_gate_rejects_negative_ev(rules):
    g = evaluate_gate(100_000, 99_000, 100_500, 0.0002, rules, MKT, StrategyStats(100, 40, 1.0, True))
    assert not g.passed and g.ev_per_unit < 0


def test_gate_passes_strong_edge(rules):
    g = evaluate_gate(100_000, 99_000, 106_000, 0.0002, rules, MKT, GOOD)
    assert g.passed and g.ev_total > 0 and g.win_prob_lb < 0.65


def test_gate_rejects_edge_small_vs_costs(rules):
    g = evaluate_gate(100_000, 99_000, 106_000, 0.0002, rules, MKT, GOOD, GateParams(min_ev_cost_ratio=20.0))
    assert not g.passed and "relative to costs" in g.reasons[-1]


def test_gate_rejects_min_order(rules):
    g = evaluate_gate(100_000, 99_000, 106_000, 1e-6, rules, MKT, GOOD)
    assert not g.passed and "minimum order" in g.reasons[-1]


def test_gate_rejects_bad_geometry(rules):
    assert not evaluate_gate(100_000, 101_000, 106_000, 0.0002, rules, MKT, GOOD).passed
