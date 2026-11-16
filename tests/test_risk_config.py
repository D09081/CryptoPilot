import pytest

from cryptopilot.config import Mode, capital_usdt, load_settings
from cryptopilot.models import Action, Regime, Signal
from cryptopilot.risk import HARD_CAPS, OpenPosition, PortfolioState, RiskLimits, RiskManager


def buy(symbol="BTC/USDT", qty=0.0002, entry=100_000.0, stop=99_000.0):
    return Signal(Action.BUY, symbol, Regime.UPTREND, "t", entry, stop, entry * 1.06, qty)


def sell(qty=0.001):
    return Signal(Action.SELL, "BTC/USDT", Regime.DOWNTREND, "t", 100_000.0, qty=qty)


def state(**kw):
    d = dict(equity=55.0, peak_equity=55.0, day_start_equity=55.0, free_quote=55.0, mode=Mode.PAPER)
    d.update(kw)
    return PortfolioState(**d)


RM = RiskManager()


def test_baseline_buy_approved():
    assert RM.evaluate(buy(), state()).approved


def test_hold_is_not_an_order():
    assert not RM.evaluate(Signal.hold("BTC/USDT", Regime.UNCERTAIN, []), state()).approved


def test_rejects_excess_trade_risk_recomputed_independently():
    sig = buy(qty=0.001)  # signal might claim anything; RM recomputes from price/qty
    d = RM.evaluate(sig, state())
    assert not d.approved and any("trade risk" in r for r in d.reasons)


def test_daily_loss_limit():
    d = RM.evaluate(buy(), state(equity=54.4, day_start_equity=55.0))
    assert not d.approved and "daily loss limit reached" in d.reasons


def test_max_drawdown_limit():
    d = RM.evaluate(buy(), state(equity=52.0, peak_equity=55.0, day_start_equity=52.0))
    assert not d.approved and "max drawdown reached" in d.reasons


def test_one_position_max_and_correlation():
    st = state(open_positions={"ETH/USDT": OpenPosition(0.01, 3000, 2900)})
    d = RM.evaluate(buy(), st)
    assert "max open positions reached" in d.reasons and "correlated position already open" in d.reasons


def test_free_usdt_check():
    d = RM.evaluate(buy(), state(free_quote=5.0))
    assert not d.approved and "insufficient free USDT" in d.reasons


def test_kill_halt_anomaly_block_buys_but_not_exits():
    for kw in ({"kill_switch": True}, {"trading_halted": True}, {"anomalies": ["stale data"]}):
        assert not RM.evaluate(buy(), state(**kw)).approved
        assert RM.evaluate(sell(), state(holdings={"BTC": 0.001}, **kw)).approved


def test_spot_sell_limited_to_holdings():
    assert not RM.evaluate(sell(0.002), state(holdings={"BTC": 0.001})).approved
    assert not RM.evaluate(sell(), state()).approved
    assert RM.evaluate(sell(), state(holdings={"BTC": 0.001})).approved


def test_mode_gates():
    assert not RM.evaluate(buy(), state(mode=Mode.OBSERVE)).approved
    assert not RM.evaluate(buy(), state(mode=Mode.BACKTEST)).approved
    assert not RM.evaluate(buy(), state(mode=Mode.LIVE, live_confirmed=False)).approved
    assert RM.evaluate(buy(), state(mode=Mode.LIVE, live_confirmed=True)).approved


def test_symbol_allowlist_and_invalid_stop():
    assert not RM.evaluate(buy(symbol="DOGE/USDT"), state()).approved
    assert not RM.evaluate(buy(stop=101_000.0), state()).approved


def test_limits_cannot_exceed_hard_caps():
    for k, cap in HARD_CAPS.items():
        with pytest.raises(ValueError):
            RiskLimits(**{k: cap * 2 if k != "max_open_positions" else 2})
    with pytest.raises(ValueError):
        RiskLimits(risk_per_trade_pct=0)


def test_limit_change_requires_owner_authorisation():
    rm = RiskManager()
    with pytest.raises(PermissionError):
        rm.update_limits(RiskLimits(risk_per_trade_pct=0.25), owner_authorized=False)
    rm.update_limits(RiskLimits(risk_per_trade_pct=0.25), owner_authorized=True)
    assert rm.limits.risk_per_trade_pct == 0.25
    assert not rm.evaluate(buy(qty=0.0002), state()).approved  # now stricter


# ---- config ----------------------------------------------------------------
def test_capital_conversion():
    assert capital_usdt(90.0) == pytest.approx(5000 / 90)
    for bad in (0, -1, None, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            capital_usdt(bad)


def test_default_mode_is_observe_and_live_needs_flag():
    assert load_settings({}).mode is Mode.OBSERVE
    with pytest.raises(ValueError):
        load_settings({"CP_MODE": "LIVE"})
    assert load_settings({"CP_MODE": "LIVE", "CP_LIVE_ENABLED": "true"}).mode is Mode.LIVE
    with pytest.raises(ValueError):
        load_settings({"CP_MODE": "YOLO"})
    assert load_settings({"CP_OWNER_TELEGRAM_ID": "42"}).owner_telegram_id == 42
