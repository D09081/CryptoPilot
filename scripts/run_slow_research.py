"""Research protocol for the slow H4 candidates (no tuning on the final period).

Periods (UTC): DEV < --dev-end <= VALIDATION < --val-end <= FINAL.
Step 1: print every pre-registered candidate on DEV and VALIDATION (all 6 are reported, nothing hidden).
Step 2: SELECTION RULE (fixed in advance): candidate must have, on BOTH dev and validation, pooled over
        the pairs: net > 0, profit factor >= 1.2 and >= 10 trades.
Step 3: only selected candidates are evaluated ONCE on FINAL by the validator. Nothing is tuned afterwards.
Need H4 CSVs: DATA_DIR/{BTC-USDT,ETH-USDT}_H4.csv"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptopilot.backtest import load_candles_csv
from cryptopilot.metrics import compute_stats
from cryptopilot.profitability import MarketCosts
from cryptopilot.sizing import ExchangeRules
from cryptopilot.slow import ACTIVE_CANDIDATES, CANDIDATES, FAST_CANDIDATES, run_slow_backtest
from cryptopilot.validator import validate

H4 = 4 * 3600_000


def ts(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def line(label, st):
    return (f"{label:<24} trades={st.n_trades:<4} net={st.net_profit:>8.3f} PF={st.profit_factor:>5.2f} "
            f"win={st.win_rate*100:>4.0f}% maxDD={st.max_drawdown_pct:>5.1f}%")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--dev-end", default="2023-01-01")
    ap.add_argument("--val-end", default="2025-01-01")
    ap.add_argument("--equity", type=float, default=55.0)
    ap.add_argument("--symbols", nargs="+", default=["BTC-USDT", "ETH-USDT"])
    ap.add_argument("--taker-fee", type=float, default=0.001)
    ap.add_argument("--set", choices=["slow", "active", "fast"], default="slow")
    ap.add_argument("--tf", choices=["H4", "H1"], default="H4", help="candle files to read (fast set uses H1)")
    a = ap.parse_args(argv)
    dev_end, val_end = ts(a.dev_end), ts(a.val_end)
    cands = {"slow": CANDIDATES, "active": ACTIVE_CANDIDATES, "fast": FAST_CANDIDATES}[a.set]
    tf_ms = 3600_000 if a.tf == "H1" else H4
    mkt = MarketCosts(2.0, 2.0, 5.0)
    data = {s: load_candles_csv(os.path.join(a.data_dir, f"{s}_{a.tf}.csv"), tf_ms) for s in a.symbols}
    for s, c in data.items():
        d0 = dt.datetime.fromtimestamp(c.ts[0] / 1000, dt.timezone.utc).date()
        d1 = dt.datetime.fromtimestamp(c.ts[-1] / 1000, dt.timezone.utc).date()
        print(f"{s}: {len(c)} {a.tf} bars {d0}..{d1}")
    print(f"Periods: DEV < {a.dev_end} <= VALIDATION < {a.val_end} <= FINAL. Costs assumed. Candidates tried: {len(cands)}.\n")

    trades = {}
    for strat in cands:
        allt = []
        for s, c in data.items():
            r = ExchangeRules(s.replace("-", "/"), 0.1, 1e-8, 1e-5, 1.0, a.taker_fee, a.taker_fee)
            allt += run_slow_backtest(s.replace("-", "/"), c, strat, r, mkt, a.equity)
        trades[strat.name] = allt

    selected = []
    for name, allt in trades.items():
        dev = [t for t in allt if t.entry_ts < dev_end]
        val = [t for t in allt if dev_end <= t.entry_ts < val_end]
        sd, sv = compute_stats(dev, a.equity), compute_stats(val, a.equity)
        print(line(name + " DEV", sd)); print(line(name + " VAL", sv))
        ok = all(s.net_profit > 0 and s.profit_factor >= 1.2 and s.n_trades >= 10 for s in (sd, sv))
        print(f"   -> {'SELECTED for final test' if ok else 'rejected'}\n")
        if ok:
            selected.append(name)

    print("=== FINAL period (touched once, selected candidates only) ===")
    if not selected:
        print("No candidate passed the selection rule. Nothing is evaluated on FINAL and nothing is admitted.")
        return
    for name in selected:
        fin = [t for t in trades[name] if t.entry_ts >= val_end]
        rep = validate(fin, a.equity, val_end)
        print(line(name + " FINAL", rep.stats), "->", "PASS" if rep.passed else "FAIL")
        for n_, ok, det in rep.checks:
            print(f"   [{'x' if ok else ' '}] {n_}: {det}")


if __name__ == "__main__":
    main()
