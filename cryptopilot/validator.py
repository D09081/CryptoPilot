"""Strategy Validator: decides whether backtest results justify *admission* of a strategy.

Only trades whose entry is at/after ``oos_start_ts`` (data the strategy was never tuned on)
are evaluated. Passing this validator is necessary, not sufficient: Paper/Demo trading and
the owner's separate consent are still required before any real money is used.

NOT implemented yet: parameter-sensitivity analysis and per-regime breadth checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from .metrics import Stats, compute_stats
from .strategies import StrategyStats


@dataclass(frozen=True)
class ValidationParams:
    min_trades: int = 30
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 10.0
    n_chunks: int = 3
    min_positive_chunks: int = 2
    bootstrap: int = 2000
    alpha: float = 0.05
    seed: int = 7


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    stats: Stats
    checks: Tuple[Tuple[str, bool, str], ...]

    def to_strategy_stats(self, source: str) -> StrategyStats:
        if not self.passed:
            raise ValueError("validation failed: strategy cannot be admitted")
        return StrategyStats(self.stats.n_trades, self.stats.wins, self.stats.expectancy,
                             True, source)


def validate(trades: Sequence, initial_equity: float, oos_start_ts: int,
             params: ValidationParams = ValidationParams()) -> ValidationReport:
    oos = sorted((t for t in trades if t.entry_ts >= oos_start_ts), key=lambda t: t.entry_ts)
    st = compute_stats(oos, initial_equity)
    checks = []

    def add(name, ok, detail):
        checks.append((name, bool(ok), detail))

    add("sample_size", st.n_trades >= params.min_trades,
        f"{st.n_trades} out-of-sample trades (need {params.min_trades})")
    add("net_expectancy_positive", st.expectancy > 0, f"expectancy {st.expectancy:.6f} after costs")
    add("profit_factor", st.profit_factor >= params.min_profit_factor,
        f"PF {st.profit_factor:.2f} (need {params.min_profit_factor})")
    add("max_drawdown", st.max_drawdown_pct <= params.max_drawdown_pct,
        f"{st.max_drawdown_pct:.2f}% (limit {params.max_drawdown_pct}%)")

    if len(oos) >= params.n_chunks:
        chunks = np.array_split(np.array([t.pnl for t in oos]), params.n_chunks)
        pos = sum(1 for c in chunks if c.mean() > 0)
        add("walk_forward_consistency", pos >= params.min_positive_chunks,
            f"{pos}/{params.n_chunks} consecutive windows profitable (need {params.min_positive_chunks})")
    else:
        add("walk_forward_consistency", False, "too few trades for windows")

    if len(oos) >= 2:
        rng = np.random.default_rng(params.seed)
        pnl = np.array([t.pnl for t in oos])
        means = rng.choice(pnl, size=(params.bootstrap, len(pnl))).mean(axis=1)
        lo = float(np.quantile(means, params.alpha))
        add("bootstrap_expectancy_lower_bound", lo > 0,
            f"{int((1 - params.alpha) * 100)}% lower bound of expectancy {lo:.6f}")
    else:
        add("bootstrap_expectancy_lower_bound", False, "too few trades")

    return ValidationReport(all(c[1] for c in checks), st, tuple(checks))
