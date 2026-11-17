"""Broker interface (exchange adapter boundary) and OKX adapter (DEMO ONLY for now).

The OKX adapter refuses to be built for the live exchange: live trading stays disabled until the
owner explicitly enables it in a later, separately reviewed step."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from .sizing import ExchangeRules

BASE_URL = "https://www.okx.com"


class BrokerError(Exception):
    """Definite failure: the exchange answered and refused (or the request was malformed)."""

    def __init__(self, msg: str, code: str = ""):
        super().__init__(msg)
        self.code = code


class BrokerTimeout(BrokerError):
    """Outcome UNKNOWN (timeout / dropped connection). Never blindly resend: query the order first."""


@dataclass(frozen=True)
class OrderInfo:
    cl_ord_id: str
    state: str                # live | partially_filled | filled | canceled
    filled_qty: float = 0.0
    avg_px: float = 0.0
    fee_quote: float = 0.0    # positive number, quote currency (best effort)


def sign(secret: str, ts: str, method: str, path_with_query: str, body: str) -> str:
    msg = f"{ts}{method.upper()}{path_with_query}{body}".encode()
    return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()


def fmt(x: float, step: float) -> str:
    """Floor x to the step and render without exponent (OKX wants plain decimal strings)."""
    d, s = Decimal(str(x)), Decimal(str(step))
    return format((d / s).to_integral_value(rounding="ROUND_DOWN") * s, "f")


class OkxBroker:
    def __init__(self, key: str, secret: str, passphrase: str, demo: bool = True,
                 opener: Callable = urllib.request.urlopen, now: Callable[[], dt.datetime] = None,
                 taker_fee: float = 0.001, min_notional: float = 1.0):
        if not demo:
            raise PermissionError("live OKX trading is disabled: only demo trading is allowed at this stage")
        if not (key and secret and passphrase):
            raise ValueError("OKX demo credentials are missing")
        self._k, self._s, self._p = key, secret, passphrase
        self._open = opener
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.taker_fee, self.min_notional = taker_fee, min_notional

    # -- transport --------------------------------------------------------------
    def _call(self, method: str, path: str, params: Optional[dict] = None, body: Optional[object] = None):
        pq = path + ("?" + urllib.parse.urlencode(params) if params else "")
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        ts = self._now().strftime("%Y-%m-%dT%H:%M:%S.") + f"{self._now().microsecond // 1000:03d}Z"
        headers = {"Content-Type": "application/json", "OK-ACCESS-KEY": self._k,
                   "OK-ACCESS-SIGN": sign(self._s, ts, method, pq, payload),
                   "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self._p,
                   "x-simulated-trading": "1"}                      # demo trading flag
        req = urllib.request.Request(BASE_URL + pq, data=payload.encode() if body is not None else None,
                                     headers=headers, method=method)
        try:
            with self._open(req, timeout=15) as r:
                data = json.loads(r.read().decode())
        except (socket.timeout, TimeoutError) as e:
            raise BrokerTimeout("request timed out") from e
        except urllib.error.HTTPError as e:
            raise BrokerError(f"HTTP {e.code}", str(e.code)) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise BrokerTimeout("request timed out") from e
            raise BrokerTimeout(f"connection problem: {e.reason}") from e   # unknown outcome for writes
        except json.JSONDecodeError as e:
            raise BrokerTimeout("unreadable response") from e
        if data.get("code") != "0":
            inner = (data.get("data") or [{}])[0]
            raise BrokerError(f"OKX {inner.get('sCode') or data.get('code')}: "
                              f"{inner.get('sMsg') or data.get('msg')}", str(inner.get("sCode") or data.get("code")))
        return data["data"]

    # -- queries -----------------------------------------------------------------
    def instrument(self, inst: str) -> ExchangeRules:
        d = self._call("GET", "/api/v5/public/instruments", {"instType": "SPOT", "instId": inst})[0]
        return ExchangeRules(inst.replace("-", "/"), float(d["tickSz"]), float(d["lotSz"]), float(d["minSz"]),
                             self.min_notional, self.taker_fee, self.taker_fee)

    def balance(self, ccy: str) -> float:
        d = self._call("GET", "/api/v5/account/balance", {"ccy": ccy})
        for det in d[0].get("details", []):
            if det["ccy"] == ccy:
                return float(det["availBal"] or 0)
        return 0.0

    def get_order(self, inst: str, cl_ord_id: str) -> Optional[OrderInfo]:
        try:
            d = self._call("GET", "/api/v5/trade/order", {"instId": inst, "clOrdId": cl_ord_id})[0]
        except BrokerError as e:
            if e.code == "51603":                                   # order does not exist
                return None
            raise
        return OrderInfo(cl_ord_id, d["state"], float(d.get("accFillSz") or 0), float(d.get("avgPx") or 0),
                         abs(float(d.get("fee") or 0)))

    def pending_stops(self, inst: str) -> List[dict]:
        rows = self._call("GET", "/api/v5/trade/orders-algo-pending", {"ordType": "conditional", "instId": inst})
        return [{"algo_id": r["algoId"], "cl_id": r.get("algoClOrdId", ""), "qty": float(r["sz"]),
                 "trigger": float(r["slTriggerPx"])} for r in rows]

    # -- actions -----------------------------------------------------------------
    def place_market(self, inst: str, side: str, qty: float, cl_ord_id: str, rules: ExchangeRules) -> None:
        self._call("POST", "/api/v5/trade/order", body={
            "instId": inst, "tdMode": "cash", "side": side, "ordType": "market",
            "sz": fmt(qty, rules.lot_step), "tgtCcy": "base_ccy", "clOrdId": cl_ord_id})

    def place_stop(self, inst: str, qty: float, trigger_px: float, cl_ord_id: str, rules: ExchangeRules) -> str:
        d = self._call("POST", "/api/v5/trade/order-algo", body={
            "instId": inst, "tdMode": "cash", "side": "sell", "ordType": "conditional",
            "sz": fmt(qty, rules.lot_step), "slTriggerPx": fmt(trigger_px, rules.tick_size),
            "slOrdPx": "-1", "algoClOrdId": cl_ord_id})            # -1 = market order when triggered
        return d[0]["algoId"]

    def cancel_stop(self, inst: str, algo_id: str) -> None:
        self._call("POST", "/api/v5/trade/cancel-algos", body=[{"algoId": algo_id, "instId": inst}])
