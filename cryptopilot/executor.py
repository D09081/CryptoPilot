"""Execution Engine: idempotent order handling on top of a Broker.

Guarantees (all covered by tests with a fake broker):
  * deterministic client order ids => a repeated call/restart finds the existing order instead of buying twice;
  * on a timeout the order status is queried first; the order is resent only with the SAME id after it is
    confirmed absent (the exchange rejects duplicate ids);
  * partial fills are protected for the quantity actually received (net of fees taken in the base asset);
  * if the protective stop cannot be placed, the emergency protocol sells the position at market;
  * the engine only manages quantity it opened itself; it never sells other balances on the account.
Not covered: real exchange behaviour (never run against OKX from the build environment)."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .broker import BrokerError, BrokerTimeout, OrderInfo
from .sizing import ExchangeRules, floor_to_step


def client_id(strategy: str, bar_ts: int, tag: str) -> str:
    """<=32 chars, alphanumeric: stable for the same (strategy, bar, action)."""
    return "cp" + hashlib.sha1(strategy.encode()).hexdigest()[:8] + str(int(bar_ts)) + tag


@dataclass
class OpenResult:
    opened: bool
    qty: float = 0.0
    avg_px: float = 0.0
    stop_id: str = ""
    emergency: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class CloseResult:
    closed: bool
    qty: float = 0.0
    avg_px: float = 0.0
    notes: List[str] = field(default_factory=list)


class Executor:
    def __init__(self, broker, sleep: Callable[[float], None] = time.sleep, polls: int = 5, poll_wait: float = 1.0):
        self.b, self.sleep, self.polls, self.poll_wait = broker, sleep, polls, poll_wait
        self.halted = False                    # kill switch: blocks new entries only, never exits/protection

    # -- idempotent market order ---------------------------------------------------
    def _wait_terminal(self, inst, cl_id) -> Optional[OrderInfo]:
        info = None
        for _ in range(self.polls):
            info = self.b.get_order(inst, cl_id)
            if info is not None and info.state in ("filled", "canceled"):
                return info
            self.sleep(self.poll_wait)
        return info

    def market(self, inst: str, side: str, qty: float, cl_id: str, rules: ExchangeRules, notes: List[str]
               ) -> Optional[OrderInfo]:
        info = self.b.get_order(inst, cl_id)
        if info is not None:                                   # restart / repeat: order already exists
            notes.append(f"order {cl_id} already exists ({info.state}); not resent")
        else:
            try:
                self.b.place_market(inst, side, qty, cl_id, rules)
            except BrokerTimeout:
                notes.append("timeout on submit: checking order status before any retry")
                for _ in range(self.polls):
                    info = self.b.get_order(inst, cl_id)
                    if info is not None:
                        break
                    self.sleep(self.poll_wait)
                if info is None:                               # confirmed absent -> resend with the SAME id
                    notes.append("order absent after timeout: resending with the same client id")
                    try:
                        self.b.place_market(inst, side, qty, cl_id, rules)
                    except BrokerTimeout:
                        info = self.b.get_order(inst, cl_id)
                        if info is None:
                            notes.append("still unknown after retry: giving up, manual reconciliation needed")
                            return None
        info = self._wait_terminal(inst, cl_id)
        if info is not None and info.state == "partially_filled":
            notes.append("order still partially filled: cancelling remainder is exchange-side (market); using filled qty")
        return info

    # -- open / close --------------------------------------------------------------
    def open_position(self, inst: str, qty: float, stop_px: float, strategy: str, bar_ts: int,
                      rules: ExchangeRules) -> OpenResult:
        res = OpenResult(False)
        if self.halted:
            res.notes.append("halted: new entries blocked")
            return res
        try:
            info = self.market(inst, "buy", qty, client_id(strategy, bar_ts, "B"), rules, res.notes)
        except BrokerError as e:
            res.notes.append(f"buy rejected: {e}")
            return res
        if info is None or info.filled_qty <= 0:
            res.notes.append("no fill")
            return res
        base = inst.split("-")[0]
        try:
            avail = self.b.balance(base)
        except BrokerError:
            avail = info.filled_qty * 0.998                     # fee is taken in the base asset: stay conservative
            res.notes.append("balance unavailable: assuming fill net of a 0.2% fee")
        sellable = floor_to_step(min(info.filled_qty, avail), rules.lot_step)
        res.opened, res.qty, res.avg_px = True, sellable, info.avg_px
        stop_cl = client_id(strategy, bar_ts, "S")
        try:
            res.stop_id = self._place_stop_safely(inst, sellable, stop_px, stop_cl, rules, res.notes)
        except BrokerError as e:
            res.notes.append(f"STOP FAILED ({e}): emergency sell")
            res.emergency = True
            try:
                sell = self.market(inst, "sell", sellable, client_id(strategy, bar_ts, "E"), rules, res.notes)
                res.opened = not (sell is not None and sell.filled_qty > 0)
            except BrokerError as e2:
                res.notes.append(f"EMERGENCY SELL FAILED ({e2}): position unprotected, manual action required")
        return res

    def _place_stop_safely(self, inst, qty, px, cl_id, rules, notes) -> str:
        try:
            return self.b.place_stop(inst, qty, px, cl_id, rules)
        except BrokerTimeout:
            notes.append("timeout on stop: checking pending stops")
            for s in self.b.pending_stops(inst):
                if s["cl_id"] == cl_id:
                    return s["algo_id"]
            raise BrokerError("stop not found after timeout")

    def close_position(self, inst: str, qty: float, stop_id: str, strategy: str, bar_ts: int,
                       rules: ExchangeRules, stop_px: float = 0.0) -> CloseResult:
        res = CloseResult(False)
        if stop_id:
            try:
                self.b.cancel_stop(inst, stop_id)
            except BrokerError as e:
                res.notes.append(f"cancel stop: {e} (it may already have triggered)")
        base = inst.split("-")[0]
        try:
            qty = floor_to_step(min(qty, self.b.balance(base)), rules.lot_step)
        except BrokerError:
            res.notes.append("balance unavailable: selling tracked quantity")
            qty = floor_to_step(qty, rules.lot_step)
        if qty < rules.min_qty:
            res.notes.append("nothing left to sell (stop probably triggered)")
            res.closed = True
            return res
        try:
            info = self.market(inst, "sell", qty, client_id(strategy, bar_ts, "X"), rules, res.notes)
        except BrokerError as e:
            info = None
            res.notes.append(f"sell rejected: {e}")
        if info is None or info.filled_qty <= 0:
            if stop_px > 0:                                    # keep the position protected
                try:
                    self.b.place_stop(inst, qty, stop_px, client_id(strategy, bar_ts, "R"), rules)
                    res.notes.append("sell failed: protective stop re-placed")
                except BrokerError as e:
                    res.notes.append(f"RE-PROTECT FAILED ({e})")
            return res
        res.closed, res.qty, res.avg_px = True, info.filled_qty, info.avg_px
        return res

    # -- reconciliation ------------------------------------------------------------
    def reconcile(self, inst: str, tracked_qty: float, rules: ExchangeRules, tol_steps: float = 2.0) -> List[str]:
        """Compare what WE think we hold with the exchange. Balances beyond tracked_qty are ignored
        (the demo account may hold other assets); a shortfall or an unprotected position is reported."""
        issues = []
        base = inst.split("-")[0]
        bal = self.b.balance(base)
        if tracked_qty > 0:
            if bal + tol_steps * rules.lot_step < tracked_qty:
                issues.append(f"exchange balance {bal} < tracked position {tracked_qty}")
            stops = self.b.pending_stops(inst)
            if not stops:
                issues.append("tracked position has NO protective stop on the exchange")
        else:
            if self.b.pending_stops(inst):
                issues.append("exchange has a stop but no tracked position")
        return issues
