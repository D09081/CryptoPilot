import hashlib
import hmac
import base64
import json
import socket
import urllib.error

import pytest

from cryptopilot import broker as B
from cryptopilot.broker import BrokerError, BrokerTimeout, OkxBroker, OrderInfo, fmt, sign
from cryptopilot.executor import Executor, client_id
from cryptopilot.sizing import ExchangeRules

RULES = ExchangeRules("BTC/USDT", 0.1, 1e-8, 1e-5, 1.0, 0.001, 0.001)
INST = "BTC-USDT"


class Fake:
    """In-memory exchange with scriptable failures."""

    def __init__(self):
        self.orders, self.stops, self.bal = {}, {}, {"BTC": 0.0}
        self.place_calls, self.stop_calls = [], []
        self.timeout_submit_accepted = 0      # submit times out but the order IS accepted
        self.timeout_submit_lost = 0          # submit times out and the order is NOT accepted
        self.reject_buy = False
        self.stop_mode = "ok"                 # ok | reject | timeout_accepted | timeout_lost
        self.fill_ratio = 1.0
        self.fee_base = 0.001
        self.sell_reject = False
        self.balance_fail = False

    def _execute(self, side, qty, cl):
        filled = qty * self.fill_ratio
        if side == "buy":
            self.bal["BTC"] += filled * (1 - self.fee_base)
        else:
            self.bal["BTC"] -= filled
        self.orders[cl] = OrderInfo(cl, "filled" if self.fill_ratio == 1 else "partially_filled", filled, 100_000.0, 0.1)

    def place_market(self, inst, side, qty, cl, rules):
        self.place_calls.append((side, qty, cl))
        if cl in self.orders:
            raise BrokerError("duplicate client order id", "51016")
        if side == "buy" and self.reject_buy:
            raise BrokerError("insufficient balance", "51008")
        if side == "sell" and self.sell_reject:
            raise BrokerError("sell rejected", "51000")
        if self.timeout_submit_lost:
            self.timeout_submit_lost -= 1
            raise BrokerTimeout("timeout")
        self._execute(side, qty, cl)
        if self.timeout_submit_accepted:
            self.timeout_submit_accepted -= 1
            raise BrokerTimeout("timeout")

    def get_order(self, inst, cl):
        return self.orders.get(cl)

    def balance(self, ccy):
        if self.balance_fail:
            raise BrokerTimeout("t")
        return self.bal.get(ccy, 0.0)

    def place_stop(self, inst, qty, px, cl, rules):
        self.stop_calls.append((qty, px, cl))
        if self.stop_mode == "reject":
            raise BrokerError("algo rejected", "51000")
        if self.stop_mode == "timeout_lost":
            raise BrokerTimeout("t")
        self.stops["algo1"] = {"algo_id": "algo1", "cl_id": cl, "qty": qty, "trigger": px}
        if self.stop_mode == "timeout_accepted":
            raise BrokerTimeout("t")
        return "algo1"

    def pending_stops(self, inst):
        return list(self.stops.values())

    def cancel_stop(self, inst, algo_id):
        self.stops.pop(algo_id, None)


def ex(f):
    return Executor(f, sleep=lambda s: None, polls=3)


def test_happy_path_protects_quantity_actually_received_net_of_fee():
    f = Fake()
    r = ex(f).open_position(INST, 0.0010, 95_000.0, "s", 1_000, RULES)
    assert r.opened and not r.emergency and r.stop_id == "algo1"
    assert r.qty == pytest.approx(0.000999)                # 0.001 bought, 0.1% fee taken in BTC
    assert f.stop_calls[0][0] == pytest.approx(0.000999)


def test_timeout_but_order_accepted_is_not_resent():
    f = Fake(); f.timeout_submit_accepted = 1
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.opened and len(f.place_calls) == 1            # exactly ONE order submitted


def test_timeout_and_order_lost_resends_once_with_same_id():
    f = Fake(); f.timeout_submit_lost = 1
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.opened and len(f.place_calls) == 2 and f.place_calls[0][2] == f.place_calls[1][2]


def test_repeat_call_or_restart_never_buys_twice():
    f = Fake()
    ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    before = f.bal["BTC"]
    ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)      # same strategy + bar
    assert len([c for c in f.place_calls if c[0] == "buy"]) == 1 and f.bal["BTC"] == before


def test_definite_reject_opens_nothing():
    f = Fake(); f.reject_buy = True
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert not r.opened and f.stop_calls == []


def test_partial_fill_protects_only_filled_quantity():
    f = Fake(); f.fill_ratio = 0.4
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.opened and r.qty == pytest.approx(0.0004 * 0.999) and f.stop_calls[0][0] == pytest.approx(r.qty)


def test_stop_failure_triggers_emergency_sell():
    f = Fake(); f.stop_mode = "reject"
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.emergency and not r.opened and f.bal["BTC"] == pytest.approx(0, abs=1e-8)
    assert any(c[0] == "sell" for c in f.place_calls)


def test_stop_timeout_but_stop_exists_is_accepted():
    f = Fake(); f.stop_mode = "timeout_accepted"
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.opened and not r.emergency and r.stop_id == "algo1"


def test_stop_timeout_and_lost_goes_emergency():
    f = Fake(); f.stop_mode = "timeout_lost"
    assert ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES).emergency


def test_emergency_sell_failure_is_reported_loudly():
    f = Fake(); f.stop_mode = "reject"; f.sell_reject = True
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.emergency and r.opened and any("manual action required" in n for n in r.notes)


def test_halt_blocks_entries_but_not_exits():
    f = Fake(); e = ex(f)
    r = e.open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    e.halted = True
    assert not e.open_position(INST, 0.001, 95_000.0, "s", 2_000, RULES).opened
    c = e.close_position(INST, r.qty, r.stop_id, "s", 3_000, RULES, 95_000.0)
    assert c.closed and f.bal["BTC"] == pytest.approx(0, abs=1e-8) and f.stops == {}


def test_close_when_stop_already_triggered_sells_nothing():
    f = Fake(); e = ex(f)
    r = e.open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    f.bal["BTC"] = 0.0; f.stops.clear()                    # exchange stop fired
    c = e.close_position(INST, r.qty, r.stop_id, "s", 3_000, RULES)
    assert c.closed and not any(x[0] == "sell" for x in f.place_calls)


def test_never_sells_more_than_tracked_even_if_account_holds_more():
    f = Fake(); f.bal["BTC"] = 1.0                         # demo account pre-funded with other BTC
    e = ex(f)
    r = e.open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    e.close_position(INST, r.qty, r.stop_id, "s", 3_000, RULES)
    assert f.bal["BTC"] == pytest.approx(1.0 + 0.001 * 0.999 - r.qty, abs=1e-7)
    assert f.bal["BTC"] > 0.99


def test_failed_exit_re_protects_position():
    f = Fake(); e = ex(f)
    r = e.open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    f.sell_reject = True
    c = e.close_position(INST, r.qty, r.stop_id, "s", 3_000, RULES, stop_px=95_000.0)
    assert not c.closed and f.stops and any("re-placed" in n for n in c.notes)


def test_balance_failure_does_not_leave_position_unprotected():
    f = Fake(); f.balance_fail = True
    r = ex(f).open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert r.opened and r.stop_id == "algo1" and r.qty <= 0.001


def test_reconcile():
    f = Fake(); e = ex(f)
    assert e.reconcile(INST, 0.0, RULES) == []
    r = e.open_position(INST, 0.001, 95_000.0, "s", 1_000, RULES)
    assert e.reconcile(INST, r.qty, RULES) == []
    f.stops.clear()
    assert any("NO protective stop" in i for i in e.reconcile(INST, r.qty, RULES))
    f.bal["BTC"] = 0.0
    assert any("balance" in i for i in e.reconcile(INST, r.qty, RULES))
    f.stops["x"] = {"algo_id": "x", "cl_id": "", "qty": 1, "trigger": 1}
    assert any("no tracked" in i for i in e.reconcile(INST, 0.0, RULES))


def test_client_id_stable_short_alnum():
    a, b = client_id("momentum_180", 1_790_000_000_000, "B"), client_id("momentum_180", 1_790_000_000_000, "B")
    assert a == b and len(a) <= 32 and a.isalnum()
    assert client_id("momentum_180", 1, "B") != client_id("momentum_90", 1, "B")


# ---- OKX adapter ---------------------------------------------------------------
def test_signature_matches_reference_computation():
    msg = "2020-12-08T09:08:57.715ZGET/api/v5/account/balance?ccy=USDT"
    expect = base64.b64encode(hmac.new(b"secret", msg.encode(), hashlib.sha256).digest()).decode()
    assert sign("secret", "2020-12-08T09:08:57.715Z", "GET", "/api/v5/account/balance?ccy=USDT", "") == expect


def test_fmt_floors_to_step_without_exponent():
    assert fmt(0.000123456789, 1e-8) == "0.00012345" and fmt(95_123.456, 0.1) == "95123.4"
    assert "e" not in fmt(0.00000123, 1e-8)


class Resp:
    def __init__(self, obj): self._b = json.dumps(obj).encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_okx_refuses_live_and_missing_credentials():
    with pytest.raises(PermissionError):
        OkxBroker("k", "s", "p", demo=False)
    with pytest.raises(ValueError):
        OkxBroker("", "s", "p")


def test_okx_demo_header_signature_and_order_body():
    seen = {}

    def opener(req, timeout=0):
        seen["req"], seen["timeout"] = req, timeout
        return Resp({"code": "0", "msg": "", "data": [{"ordId": "1"}]})

    b = OkxBroker("key", "secret", "pass", opener=opener)
    b.place_market(INST, "buy", 0.00123456789, "cpabc1", RULES)
    r = seen["req"]
    h = {k.lower(): v for k, v in r.header_items()}
    assert h["x-simulated-trading"] == "1" and h["ok-access-key"] == "key" and h["ok-access-passphrase"] == "pass"
    body = json.loads(r.data)
    assert body == {"instId": INST, "tdMode": "cash", "side": "buy", "ordType": "market", "sz": "0.00123456",
                    "tgtCcy": "base_ccy", "clOrdId": "cpabc1"}
    ts = h["ok-access-timestamp"]
    assert h["ok-access-sign"] == sign("secret", ts, "POST", "/api/v5/trade/order", r.data.decode())
    assert seen["timeout"] > 0


def test_okx_error_mapping_and_timeouts():
    def err(req, timeout=0):
        return Resp({"code": "1", "msg": "All operations failed", "data": [{"sCode": "51008", "sMsg": "Insufficient balance"}]})
    with pytest.raises(BrokerError) as e:
        OkxBroker("k", "s", "p", opener=err).place_market(INST, "buy", 1, "c", RULES)
    assert e.value.code == "51008" and not isinstance(e.value, BrokerTimeout)

    def to(req, timeout=0):
        raise socket.timeout()
    with pytest.raises(BrokerTimeout):
        OkxBroker("k", "s", "p", opener=to).place_market(INST, "buy", 1, "c", RULES)

    def conn(req, timeout=0):
        raise urllib.error.URLError("reset")
    with pytest.raises(BrokerTimeout):
        OkxBroker("k", "s", "p", opener=conn).place_market(INST, "buy", 1, "c", RULES)


def test_okx_order_not_found_returns_none_and_parses_fills():
    def nf(req, timeout=0):
        return Resp({"code": "1", "msg": "", "data": [{"sCode": "51603", "sMsg": "Order does not exist"}]})
    assert OkxBroker("k", "s", "p", opener=nf).get_order(INST, "c") is None

    def ok(req, timeout=0):
        return Resp({"code": "0", "data": [{"state": "filled", "accFillSz": "0.001", "avgPx": "100000", "fee": "-0.0000010"}]})
    o = OkxBroker("k", "s", "p", opener=ok).get_order(INST, "c")
    assert o.state == "filled" and o.filled_qty == 0.001 and o.avg_px == 100000 and o.fee_quote == pytest.approx(1e-6)


def test_okx_instrument_balance_and_stops_parsing():
    def op(req, timeout=0):
        if "instruments" in req.full_url:
            return Resp({"code": "0", "data": [{"tickSz": "0.1", "lotSz": "0.00000001", "minSz": "0.00001"}]})
        if "balance" in req.full_url:
            return Resp({"code": "0", "data": [{"details": [{"ccy": "BTC", "availBal": "0.5"}]}]})
        return Resp({"code": "0", "data": [{"algoId": "9", "algoClOrdId": "cpX", "sz": "0.001", "slTriggerPx": "95000"}]})
    b = OkxBroker("k", "s", "p", opener=op)
    r = b.instrument(INST)
    assert (r.tick_size, r.lot_step, r.min_qty) == (0.1, 1e-8, 1e-5) and r.symbol == "BTC/USDT"
    assert b.balance("BTC") == 0.5 and b.balance("USDT") == 0.0
    assert b.pending_stops(INST) == [{"algo_id": "9", "cl_id": "cpX", "qty": 0.001, "trigger": 95000.0}]


# ---- demo mirror ---------------------------------------------------------------
from cryptopilot.demo import DemoMirror, new_demo_state  # noqa: E402

RULESMAP = {"BTC/USDT": RULES}
DES = {"symbol": "BTC/USDT", "qty": 0.001, "stop": 95_000.0, "entry_ts": 1_000}


def mirror(f, st=None):
    st = st if st is not None else new_demo_state("s")
    return DemoMirror(ex(f), RULESMAP, st), st


def test_mirror_open_then_idempotent_then_close():
    f = Fake(); m, st = mirror(f)
    assert m.sync(DES, 10) == [] and st["tracked"]["qty"] == pytest.approx(0.000999)
    m2, _ = mirror(f, st)
    assert m2.sync(DES, 11) == []                                   # same desired: nothing more is bought
    assert len([c for c in f.place_calls if c[0] == "buy"]) == 1
    assert m2.sync(None, 12) == [] and st["tracked"] is None and f.stops == {}


def test_mirror_detects_exchange_side_stop_and_does_not_sell():
    f = Fake(); m, st = mirror(f)
    m.sync(DES, 10)
    f.bal["BTC"] = 0.0; f.stops.clear()
    m.sync(None, 20)
    assert st["tracked"] is None and not any(c[0] == "sell" for c in f.place_calls)
    assert any("triggered on exchange" in e["msg"] for e in st["events"])


def test_mirror_alerts_on_missing_stop_and_on_emergency():
    f = Fake(); m, st = mirror(f)
    m.sync(DES, 10)
    f.stops.clear()
    assert any("NO protective stop" in a for a in m.sync(DES, 20))
    g = Fake(); g.stop_mode = "reject"; m2, st2 = mirror(g)
    assert any("EMERGENCY" in a for a in m2.sync(DES, 10)) and st2["tracked"] is None


def test_mirror_alerts_when_close_fails():
    f = Fake(); m, st = mirror(f)
    m.sync(DES, 10)
    f.sell_reject = True
    assert any("close of BTC/USDT failed" in a for a in m.sync(None, 20)) and st["tracked"] is not None
