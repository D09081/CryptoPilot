"""Mirror a paper-trading strategy's position onto the OKX DEMO account (never live).

The strategy engine decides (``desired`` position); this layer only makes the demo account match it,
through the Executor. It tracks the quantity IT opened and never touches other balances."""
from __future__ import annotations

from typing import Dict, List, Optional

from .broker import BrokerError
from .executor import Executor
from .sizing import ExchangeRules


def new_demo_state(strategy: str) -> dict:
    return {"strategy": strategy, "tracked": None, "events": []}


class DemoMirror:
    def __init__(self, executor: Executor, rules: Dict[str, ExchangeRules], state: dict):
        self.ex, self.rules, self.st = executor, rules, state

    def _ev(self, ts: int, msg: str) -> None:
        self.st["events"].append({"ts": ts, "msg": msg})
        del self.st["events"][:-200]

    def sync(self, desired: Optional[dict], bar_ts: int) -> List[str]:
        """desired: None or {"symbol", "qty", "stop", "entry_ts"}. Returns problems to alert on."""
        alerts: List[str] = []
        strat, t = self.st["strategy"], self.st["tracked"]
        if t:
            inst, r = t["symbol"].replace("/", "-"), self.rules[t["symbol"]]
            try:
                held = self.ex.b.balance(inst.split("-")[0])
            except BrokerError as e:
                alerts.append(f"cannot read balance: {e}")
                held = t["qty"]
            if held < t["qty"] * 0.5:                           # exchange stop already fired
                self._ev(bar_ts, f"{t['symbol']}: protective stop triggered on exchange")
                self.st["tracked"] = t = None
            elif desired is None or desired["symbol"] != t["symbol"]:
                res = self.ex.close_position(inst, t["qty"], t["stop_id"], strat, bar_ts, r, t["stop_px"])
                self._ev(bar_ts, f"CLOSE {t['symbol']}: closed={res.closed} @ {res.avg_px}; " + "; ".join(res.notes))
                if res.closed:
                    self.st["tracked"] = t = None
                else:
                    alerts.append(f"close of {t['symbol']} failed: manual check needed")
        if t is None and desired is not None:
            sym = desired["symbol"]
            res = self.ex.open_position(sym.replace("/", "-"), desired["qty"], desired["stop"], strat,
                                        desired["entry_ts"], self.rules[sym])
            self._ev(bar_ts, f"OPEN {sym}: opened={res.opened} qty={res.qty} @ {res.avg_px}; " + "; ".join(res.notes))
            if res.opened:
                self.st["tracked"] = {"symbol": sym, "qty": res.qty, "stop_id": res.stop_id,
                                      "stop_px": desired["stop"], "entry_ts": desired["entry_ts"],
                                      "avg_px": res.avg_px}
            if res.emergency:
                alerts.append(f"EMERGENCY protocol ran on {sym}: " + "; ".join(res.notes))
        elif t is not None:
            inst, r = t["symbol"].replace("/", "-"), self.rules[t["symbol"]]
            for issue in self.ex.reconcile(inst, t["qty"], r):
                alerts.append(issue)
                self._ev(bar_ts, "RECONCILE: " + issue)
        return alerts
