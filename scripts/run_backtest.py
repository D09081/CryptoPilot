"""Backtest + validate all strategies on OKX candle CSVs.

Usage: python scripts/run_backtest.py DATA_DIR --symbol BTC-USDT --equity 55 --oos-fraction 0.4
Expects DATA_DIR/{SYMBOL}_{H4|H1|M15}.csv (OKX raw rows or header CSV, see backtest.load_candles_csv).
The first (1 - oos_fraction) of M15 history is in-sample (for development); the rest is never
used to tune anything and is the only part the validator evaluates. Prints a report; admits nothing."""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptopilot.backtest import load_candles_csv, run_backtest
from cryptopilot.metrics import compute_stats
from cryptopilot.profitability import MarketCosts
from cryptopilot.sizing import ExchangeRules
from cryptopilot.strategies import StrategyRegistry
from cryptopilot.validator import validate

TF = {"H4": 4 * 3600_000, "H1": 3600_000, "M15": 900_000}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--symbol", default="BTC-USDT")
    ap.add_argument("--equity", type=float, default=55.0, help="USDT")
    ap.add_argument("--oos-fraction", type=float, default=0.4)
    ap.add_argument("--spread-bps", type=float, default=2.0)
    ap.add_argument("--slippage-bps", type=float, default=2.0)
    ap.add_argument("--stop-slippage-bps", type=float, default=5.0)
    ap.add_argument("--taker-fee", type=float, default=0.001, help="check your real OKX tier")
    ap.add_argument("--maker-fee", type=float, default=0.0008)
    ap.add_argument("--min-notional", type=float, default=1.0, help="check real OKX rule")
    a = ap.parse_args(argv)
    tfs = {k: load_candles_csv(os.path.join(a.data_dir, f"{a.symbol}_{k}.csv"), v) for k, v in TF.items()}
    rules = ExchangeRules(a.symbol.replace("-", "/"), 0.1, 1e-8, 1e-5, a.min_notional, a.taker_fee, a.maker_fee)
    mkt = MarketCosts(a.spread_bps, a.slippage_bps, a.stop_slippage_bps)
    m = tfs["M15"]
    oos_ts = int(m.ts[int(len(m) * (1 - a.oos_fraction))])
    print(f"{a.symbol}: {len(m)} M15 bars, out-of-sample from ts={oos_ts}")
    print("Costs are ASSUMED (spread/slippage constant; no historical order book).")
    for s in StrategyRegistry()._s.values():
        trades = run_backtest(a.symbol.replace("-", "/"), tfs, s, rules, mkt, a.equity)
        rep = validate(trades, a.equity, oos_ts)
        full = compute_stats(trades, a.equity)
        print(f"\n== {s.name}: all-period trades={full.n_trades} net={full.net_profit:.4f}; "
              f"OOS trades={rep.stats.n_trades} net={rep.stats.net_profit:.4f} "
              f"PF={rep.stats.profit_factor:.2f} -> {'PASS' if rep.passed else 'FAIL'}")
        for name, ok, detail in rep.checks:
            print(f"   [{'x' if ok else ' '}] {name}: {detail}")


if __name__ == "__main__":
    main()
