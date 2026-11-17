"""Forward Paper Trading engine for the slow H4 strategies.

Simulation, no real orders. Decision on a closed bar, fill at the NEXT bar's open, with fees, spread
and slippage; stops are checked on bar highs/lows (stop first), gaps fill at the open. Every BUY goes
through the RiskManager (one position at a time across BTC/ETH, correlation block, daily loss,
drawdown). State is a JSON-serialisable dict so the job can be restarted at any time; bars already
processed are never processed twice."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from .config import Mode
from .models import Action, Candles, Regime, Signal
from .profitability import MarketCosts, unit_costs
from .risk import OpenPosition, PortfolioState, RiskManager
from .sizing import ExchangeRules, size_position
from .slow import SlowStrategy

MAX_EVENTS = 200


def new_state(strategy: str, equity: float) -> dict:
    return {"strategy": strategy, "initial_equity": equity, "cash": equity, "peak": equity,
            "day": None, "day_start_equity": equity, "pos": None, "pending_entry": None,
            "last_ts": None, "trades": [], "events": [], "source": None}


class PaperEngine:
    def __init__(self, strat: SlowStrategy, rules: Dict[str, ExchangeRules], market: MarketCosts,
                 risk: RiskManager, state: dict, symbols: List[str], paused: bool = False):
        self.s, self.rules, self.m, self.rm, self.st = strat, rules, market, risk, state
        self.symbols, self.paused = symbols, paused
        self.half = market.spread_bps / 1e4 / 2
        self.slip = market.slippage_bps / 1e4
        self.sslip = market.stop_slippage_bps / 1e4

    # -- helpers ------------------------------------------------------------
    def _event(self, ts: int, msg: str) -> None:
        self.st["events"].append({"ts": ts, "msg": msg})
        del self.st["events"][:-MAX_EVENTS]

    def _equity(self, closes: Dict[str, float]) -> float:
        p = self.st["pos"]
        return self.st["cash"] + (p["qty"] * closes.get(p["symbol"], p["entry"]) if p else 0.0)

    def _close(self, ts: int, px: float, reason: str) -> None:
        p, r = self.st["pos"], self.rules[self.st["pos"]["symbol"]]
        fee_out = p["qty"] * px * r.taker_fee
        self.st["cash"] += p["qty"] * px - fee_out
        pnl = p["qty"] * (px - p["entry"]) - p["fee_in"] - fee_out
        self.st["trades"].append({"symbol": p["symbol"], "strategy": self.s.name, "entry_ts": p["entry_ts"],
                                  "exit_ts": ts, "entry": p["entry"], "exit": px, "qty": p["qty"],
                                  "pnl": pnl, "fees": p["fee_in"] + fee_out, "exit_reason": reason})
        self._event(ts, f"EXIT {p['symbol']} @ {px:.4f} ({reason}) pnl {pnl:+.4f}")
        self.st["pos"] = None

    def _try_enter(self, sym: str, c: Candles, j: int, atr: float, equity: float) -> None:
        r = self.rules[sym]
        ts = int(c.ts[j])
        entry = c.open[j] * (1 + self.slip + self.half)
        stop = entry - self.s.stop_atr * atr
        if not 0 < stop < entry:
            return self._event(ts, f"SKIP {sym}: invalid stop")
        _, cl, _, _ = unit_costs(entry, stop, entry * 1.5, r, self.m)
        size = size_position(equity, entry, stop, r, self.rm.limits.risk_per_trade_pct, self.st["cash"], cl)
        if not size.ok:
            return self._event(ts, f"SKIP {sym}: {size.reason}")
        sig = Signal(Action.BUY, sym, Regime.UPTREND, self.s.name, entry, stop, entry * 1.5, size.qty,
                     size.risk_amount, reasons=("slow trend entry",), data_quality="ok")
        ps = PortfolioState(equity=equity, peak_equity=self.st["peak"], day_start_equity=self.st["day_start_equity"],
                            free_quote=self.st["cash"], mode=Mode.PAPER, trading_halted=self.paused)
        dec = self.rm.evaluate(sig, ps)
        if not dec.approved:
            return self._event(ts, f"RISK REJECT {sym}: {'; '.join(dec.reasons)}")
        fee_in = size.qty * entry * r.taker_fee
        self.st["cash"] -= size.qty * entry + fee_in
        self.st["pos"] = {"symbol": sym, "entry_ts": ts, "entry": entry, "stop": stop, "qty": size.qty,
                          "fee_in": fee_in, "pending_exit": False}
        self._event(ts, f"ENTER {sym} qty {size.qty:.8f} @ {entry:.4f} stop {stop:.4f}")

    # -- main step ------------------------------------------------------------
    def process(self, data: Dict[str, Candles]) -> int:
        """Process all newly closed bars. Returns number of bar-times processed."""
        prep = {s: self.s.prepare(data[s]) for s in self.symbols}
        idx = {s: {int(t): i for i, t in enumerate(data[s].ts)} for s in self.symbols}
        common = sorted(set.intersection(*(set(idx[s]) for s in self.symbols)))
        if not common:
            raise RuntimeError("no common bars between symbols")
        if self.st["last_ts"] is None:                      # start forward-only: no history is traded
            self.st["last_ts"] = common[-1]
            self._event(common[-1], "paper trading started (forward only)")
            return 0
        tf, done = data[self.symbols[0]].tf_ms, 0
        for ts in (t for t in common if t > self.st["last_ts"]):
            if ts - self.st["last_ts"] > tf:
                self._event(ts, "WARNING: missed bars between runs; entries skipped for this bar")
            contiguous = ts - self.st["last_ts"] == tf
            closes = {s: float(data[s].close[idx[s][ts]]) for s in self.symbols}
            day = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat()
            eq_open = self._equity({s: float(data[s].open[idx[s][ts]]) for s in self.symbols})
            if self.st["day"] != day:
                self.st["day"], self.st["day_start_equity"] = day, eq_open
            for s in self.symbols:
                c, d, j = data[s], prep[s], idx[s][ts]
                # fill a pending entry at this bar's open FIRST, so the entry bar itself is
                # checked against the stop / exit signal exactly like the batch backtester
                pe = self.st["pending_entry"]
                if pe and pe["symbol"] == s:
                    self.st["pending_entry"] = None
                    if self.st["pos"] is None:
                        self._try_enter(s, c, j, pe["atr"], self._equity(closes))
                p = self.st["pos"]
                if p and p["symbol"] == s:
                    if p["pending_exit"]:
                        self._close(ts, c.open[j] * (1 - self.half - self.slip), "signal")
                    elif c.low[j] <= p["stop"]:
                        self._close(ts, min(p["stop"], c.open[j]) * (1 - self.half - self.sslip), "stop")
                    elif self.s.exit(d, j):
                        p["pending_exit"] = True
                if (self.st["pos"] is None and self.st["pending_entry"] is None and contiguous
                        and not self.paused and self.s.entry(d, j)):
                    self.st["pending_entry"] = {"symbol": s, "atr": float(d["atr"][j]), "ts": ts}
                    self._event(ts, f"SIGNAL {s}: entry at next open")
            eq = self._equity(closes)
            self.st["peak"] = max(self.st["peak"], eq)
            self.st["last_ts"] = ts
            done += 1
        return done

    def equity_now(self, data: Dict[str, Candles]) -> float:
        return self._equity({s: float(data[s].close[-1]) for s in self.symbols})
