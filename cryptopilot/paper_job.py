"""One scheduled paper-trading run: fetch -> process new closed bars -> save state -> write report."""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List

from .feed import fetch_closed_h4
from .metrics import compute_stats
from .models import Candles
from .paper import PaperEngine, new_state
from .profitability import MarketCosts
from .risk import RiskManager
from .sizing import ExchangeRules
from .slow import SlowStrategy

SYMBOLS = ["BTC/USDT", "ETH/USDT"]
# momentum_180/360: from the slow family. ema_trend_30_100 and momentum_90: the two "active" candidates with the
# highest DEV+VALIDATION net profit (chosen WITHOUT looking at the 2025-26 final period).
STRATEGIES = [SlowStrategy("momentum", 180), SlowStrategy("momentum", 360),
              SlowStrategy("ema_trend", 30, 100), SlowStrategy("momentum", 90)]
MARKET = MarketCosts(2.0, 2.0, 5.0)
# PLACEHOLDER exchange rules: verify against OKX instrument data before relying on size/min-notional results.
RULES = {s: ExchangeRules(s, 0.1, 1e-8, 1e-5, 1.0, 0.001, 0.001) for s in SYMBOLS}


def _load(path: str, name: str, equity: float) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return new_state(name, equity)


def _save(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _utc(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000))


def report(states: Dict[str, dict], prices: Dict[str, float], source: str, now_ms: int) -> str:
    out = ["# CryptoPilot: paper trading status", "",
           "**SIMULATION. No real orders, no real money.** Prices source: " + source +
           ". Fills, fees (0.10%/side), spread and slippage are simulated assumptions.",
           f"Updated: {_utc(now_ms)} UTC.", ""]
    for name, st in states.items():
        pos = st["pos"]
        eq = st["cash"] + (pos["qty"] * prices.get(pos["symbol"], pos["entry"]) if pos else 0.0)
        stats = compute_stats([_T(t) for t in st["trades"]], st["initial_equity"])
        out += [f"## {name}", "",
                f"- Equity: {eq:.4f} USDT (start {st['initial_equity']:.2f}), change {100*(eq/st['initial_equity']-1):+.2f}%",
                f"- Position: " + (f"{pos['symbol']} qty {pos['qty']:.8f} entry {pos['entry']:.4f} stop {pos['stop']:.4f}"
                                   + (" (exit signal pending)" if pos["pending_exit"] else "") if pos else "none (cash)"),
                f"- Pending entry: " + (f"{st['pending_entry']['symbol']}" if st["pending_entry"] else "none"),
                f"- Closed trades: {stats.n_trades}, net {stats.net_profit:+.4f} USDT, win rate {100*stats.win_rate:.0f}%, "
                f"profit factor {stats.profit_factor:.2f}, max drawdown {stats.max_drawdown_pct:.2f}%",
                f"- Last processed bar: {_utc(st['last_ts']) if st['last_ts'] else 'n/a'} UTC", "",
                "Recent events:", ""]
        out += [f"- {_utc(e['ts'])}  {e['msg']}" for e in st["events"][-12:]] or ["- none"]
        out.append("")
    out += ["Admission to real money requires a validated sample (>= 30 trades), positive net result and the owner's "
            "separate consent. This report alone is not a recommendation to trade."]
    return "\n".join(out) + "\n"


class _T:
    def __init__(self, d):
        self.pnl, self.entry_ts, self.exit_ts = d["pnl"], d["entry_ts"], d["exit_ts"]


def run_job(state_dir: str, equity: float = 55.0, now_ms: int | None = None,
            fetch: Callable = fetch_closed_h4, strategies=None) -> str:
    os.makedirs(state_dir, exist_ok=True)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    paused = os.path.exists(os.path.join(state_dir, "PAUSE"))
    data: Dict[str, Candles] = {}
    sources = set()
    for s in SYMBOLS:
        data[s], src = fetch(s.replace("/", "-"), now_ms)
        sources.add(src)
    source = "+".join(sorted(sources))
    states = {}
    for strat in (strategies or STRATEGIES):
        path = os.path.join(state_dir, f"{strat.name}.json")
        st = _load(path, strat.name, equity)
        if st.get("source") and st["source"] != source:
            st["events"].append({"ts": int(data[SYMBOLS[0]].ts[-1]), "msg": f"price source changed {st['source']} -> {source}"})
        st["source"] = source
        PaperEngine(strat, RULES, MARKET, RiskManager(), st, SYMBOLS, paused).process(data)
        _save(path, st)
        states[strat.name] = st
    text = report(states, {s: float(data[s].close[-1]) for s in SYMBOLS}, source, now_ms)
    with open(os.path.join(state_dir, "REPORT.md"), "w") as f:
        f.write(text)
    return text
