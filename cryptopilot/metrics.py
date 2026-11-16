"""Performance statistics, computed from net (after-cost) trade results.
Sharpe/Sortino are per-trade ratios (not annualised) and are labelled as such."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Sequence

import numpy as np


@dataclass(frozen=True)
class Stats:
    n_trades: int = 0
    wins: int = 0
    net_profit: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_per_trade: float = 0.0
    sortino_per_trade: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_holding_hours: float = 0.0


def compute_stats(trades: Sequence, initial_equity: float) -> Stats:
    n = len(trades)
    if n == 0:
        return Stats()
    pnl = np.array([t.pnl for t in trades], dtype=float)
    win, loss = pnl[pnl > 0], pnl[pnl <= 0]
    gw, gl = float(win.sum()), float(-loss.sum())
    pf = float("inf") if gl == 0 and gw > 0 else (gw / gl if gl > 0 else 0.0)
    eq = initial_equity + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[initial_equity], eq]))[1:]
    dd = float(((peak - eq) / peak).max() * 100)
    r = pnl / initial_equity
    sd = r.std()
    down = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2)))
    hold = np.mean([(t.exit_ts - t.entry_ts) for t in trades]) / 3_600_000
    return Stats(
        n_trades=n, wins=int(len(win)), net_profit=float(pnl.sum()), win_rate=len(win) / n,
        avg_win=float(win.mean()) if len(win) else 0.0,
        avg_loss=float(loss.mean()) if len(loss) else 0.0,
        profit_factor=pf, expectancy=float(pnl.mean()),
        sharpe_per_trade=float(r.mean() / sd) if sd > 0 else 0.0,
        sortino_per_trade=float(r.mean() / down) if down > 0 else 0.0,
        max_drawdown_pct=dd, avg_holding_hours=float(hold))


def group_stats(trades: Sequence, key: Callable, initial_equity: float) -> Dict[str, Stats]:
    groups = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    return {k: compute_stats(v, initial_equity) for k, v in sorted(groups.items())}
