"""Risk Manager: server-side veto over every order. It recomputes risk itself and
does not trust the signal's own numbers. AI/strategies/UI cannot change limits."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List

from .config import Mode, SYMBOLS
from .models import Action, Signal

HARD_CAPS = {"risk_per_trade_pct": 0.5, "daily_loss_pct": 1.0,
             "max_drawdown_pct": 5.0, "max_open_positions": 1}
CORRELATED_GROUPS = (frozenset({"BTC/USDT", "ETH/USDT"}),)


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 0.5
    daily_loss_pct: float = 1.0
    max_drawdown_pct: float = 5.0
    max_open_positions: int = 1
    fee_rate: float = 0.001

    def __post_init__(self):
        for k, cap in HARD_CAPS.items():
            v = getattr(self, k)
            if not (0 < v <= cap):
                raise ValueError(f"{k}={v} outside (0, {cap}]")


@dataclass
class OpenPosition:
    qty: float
    entry: float
    stop: float


@dataclass
class PortfolioState:
    equity: float
    peak_equity: float
    day_start_equity: float
    free_quote: float
    mode: Mode = Mode.OBSERVE
    live_confirmed: bool = False
    trading_halted: bool = False
    kill_switch: bool = False
    anomalies: List[str] = field(default_factory=list)
    open_positions: Dict[str, OpenPosition] = field(default_factory=dict)
    holdings: Dict[str, float] = field(default_factory=dict)   # base asset -> qty


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple


class RiskManager:
    def __init__(self, limits: RiskLimits = RiskLimits(), allowed_symbols=SYMBOLS):
        self._limits = limits
        self.allowed_symbols = tuple(allowed_symbols)

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    def update_limits(self, new: RiskLimits, owner_authorized: bool) -> None:
        """Limits can only change with explicit owner authorisation; they are always
        re-validated against HARD_CAPS (RiskLimits.__post_init__)."""
        if not owner_authorized:
            raise PermissionError("risk limit change requires owner authorisation")
        self._limits = new

    def evaluate(self, sig: Signal, st: PortfolioState) -> RiskDecision:
        L, r = self._limits, []
        if sig.action is Action.HOLD:
            return RiskDecision(False, ("HOLD is not an order",))
        if sig.symbol not in self.allowed_symbols:
            r.append("symbol not allowed")
        if st.mode in (Mode.OBSERVE, Mode.BACKTEST):
            r.append(f"mode {st.mode.value} does not place orders")
        if st.mode is Mode.LIVE and not st.live_confirmed:
            r.append("LIVE not confirmed by owner")
        if sig.qty <= 0:
            r.append("non-positive quantity")

        if sig.action is Action.SELL:
            # Exits reduce risk: allowed even when halted/killed, but only up to real holdings.
            base = sig.symbol.split("/")[0]
            if sig.qty > st.holdings.get(base, 0.0) + 1e-12:
                r.append("spot sell exceeds actual holdings (no shorting)")
            return RiskDecision(not r, tuple(r) or ("exit approved",))

        # --- BUY (new risk) ---
        if st.kill_switch:
            r.append("kill switch active")
        if st.trading_halted:
            r.append("trading halted")
        if st.anomalies:
            r.append("anomaly: " + "; ".join(st.anomalies))
        if not (0 < sig.stop_loss < sig.entry):
            r.append("invalid stop loss")
        else:
            notional = sig.qty * sig.entry
            fees = 2 * L.fee_rate * notional
            risk = (sig.entry - sig.stop_loss) * sig.qty + fees
            budget = st.equity * L.risk_per_trade_pct / 100
            if risk > budget * (1 + 1e-9):
                r.append(f"trade risk {risk:.4f} > {budget:.4f}")
            open_risk = sum((p.entry - p.stop) * p.qty for p in st.open_positions.values())
            if open_risk + risk > budget * L.max_open_positions * (1 + 1e-9):
                r.append("aggregate risk too high")
            if notional * (1 + L.fee_rate) > st.free_quote:
                r.append("insufficient free USDT")
        if len(st.open_positions) >= L.max_open_positions:
            r.append("max open positions reached")
        for grp in CORRELATED_GROUPS:
            if sig.symbol in grp and any(s in grp and s != sig.symbol for s in st.open_positions):
                r.append("correlated position already open")
        if st.day_start_equity > 0 and \
                (st.day_start_equity - st.equity) / st.day_start_equity * 100 >= L.daily_loss_pct:
            r.append("daily loss limit reached")
        if st.peak_equity > 0 and (st.peak_equity - st.equity) / st.peak_equity * 100 >= L.max_drawdown_pct:
            r.append("max drawdown reached")
        return RiskDecision(not r, tuple(r) or ("approved",))
