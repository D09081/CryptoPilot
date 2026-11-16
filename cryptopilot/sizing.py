"""Exchange rules and position sizing (spot, long only)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional


@dataclass(frozen=True)
class ExchangeRules:
    symbol: str
    tick_size: float
    lot_step: float
    min_qty: float
    min_notional: float
    taker_fee: float
    maker_fee: float = 0.0


def floor_to_step(x: float, step: float) -> float:
    d, s = Decimal(str(x)), Decimal(str(step))
    return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)


@dataclass(frozen=True)
class SizeResult:
    qty: float
    notional: float
    risk_amount: float
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.qty > 0


def size_position(equity: float, entry: float, stop: float, rules: ExchangeRules,
                  risk_pct: float, free_quote: float,
                  extra_loss_per_unit: float = 0.0) -> SizeResult:
    """Qty such that the worst-case loss (price move to stop + fees/slippage per unit)
    does not exceed risk_pct of equity, floored to the lot step and capped by free cash.
    If a safe size is impossible the trade is skipped (qty=0 with a reason)."""
    if not (equity > 0 and entry > 0 and 0 < stop < entry):
        return SizeResult(0.0, 0.0, 0.0, "invalid entry/stop/equity")
    loss_per_unit = (entry - stop) + extra_loss_per_unit
    budget = equity * risk_pct / 100.0
    qty = floor_to_step(budget / loss_per_unit, rules.lot_step)
    cash_qty = floor_to_step(max(free_quote, 0.0) / (entry * (1 + rules.taker_fee)), rules.lot_step)
    qty = min(qty, cash_qty)
    if qty < rules.min_qty:
        return SizeResult(0.0, 0.0, 0.0, "below minimum quantity: safe size impossible")
    if qty * entry < rules.min_notional:
        return SizeResult(0.0, 0.0, 0.0, "below minimum notional: safe size impossible")
    return SizeResult(qty, qty * entry, qty * loss_per_unit)
