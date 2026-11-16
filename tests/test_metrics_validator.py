from dataclasses import dataclass

import pytest

from cryptopilot.metrics import compute_stats, group_stats
from cryptopilot.strategies import StrategyRegistry
from cryptopilot.validator import ValidationParams, validate

H = 3_600_000


@dataclass
class T:
    pnl: float
    entry_ts: int = 0
    exit_ts: int = 0
    symbol: str = "BTC/USDT"
    strategy: str = "s"


def mk(pnls, start=1000, hold=2):
    return [T(p, start + i * 10 * H, start + i * 10 * H + hold * H) for i, p in enumerate(pnls)]


def test_empty_stats():
    assert compute_stats([], 100).n_trades == 0


def test_stats_known_values():
    s = compute_stats(mk([10, -5, 10, -5]), 100)
    assert s.n_trades == 4 and s.wins == 2 and s.net_profit == 10
    assert s.win_rate == 0.5 and s.avg_win == 10 and s.avg_loss == -5
    assert s.profit_factor == 2.0 and s.expectancy == 2.5 and s.avg_holding_hours == 2
    assert s.max_drawdown_pct == pytest.approx(5 / 110 * 100, rel=1e-6)
    assert s.sharpe_per_trade > 0 and s.sortino_per_trade > 0


def test_all_wins_profit_factor_inf_and_zero_dd():
    s = compute_stats(mk([1, 2, 3]), 100)
    assert s.profit_factor == float("inf") and s.max_drawdown_pct == 0


def test_group_by_symbol():
    ts = mk([5, -1]) + [T(2.0, symbol="ETH/USDT")]
    g = group_stats(ts, lambda t: t.symbol, 100)
    assert set(g) == {"BTC/USDT", "ETH/USDT"} and g["BTC/USDT"].n_trades == 2


def good(n=60):
    return mk([2.0 if i % 3 else -1.0 for i in range(n)])


def test_validator_passes_good_oos_and_admits():
    rep = validate(good(), 1000.0, oos_start_ts=0)
    assert rep.passed, rep.checks
    reg = StrategyRegistry()
    reg.admit("breakout", rep.to_strategy_stats("oos"))
    assert reg.status("breakout").value == "admitted"


def test_validator_ignores_in_sample_trades():
    ts = good()
    cutoff = ts[-1].entry_ts + 1          # everything is in-sample
    rep = validate(ts, 1000.0, oos_start_ts=cutoff)
    assert not rep.passed and rep.stats.n_trades == 0
    with pytest.raises(ValueError):
        rep.to_strategy_stats("x")


@pytest.mark.parametrize("pnls,failed", [
    ([2.0 if i % 3 else -1.0 for i in range(10)], "sample_size"),
    ([-1.0] * 40, "net_expectancy_positive"),
    ([1.0, -0.95] * 20, "profit_factor"),
    ([5.0] * 20 + [-6.0] * 20, "walk_forward_consistency"),
])
def test_validator_fails(pnls, failed):
    rep = validate(mk(pnls), 1000.0, 0)
    assert not rep.passed
    assert failed in [n for n, ok, _ in rep.checks if not ok]


def test_validator_drawdown_limit():
    rep = validate(good(), 1000.0, 0, ValidationParams(max_drawdown_pct=0.001))
    assert "max_drawdown" in [n for n, ok, _ in rep.checks if not ok]


def test_validator_is_deterministic():
    assert validate(good(), 1000.0, 0).checks == validate(good(), 1000.0, 0).checks
