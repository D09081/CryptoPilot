"""Live H4 candle feed with source fallback (public endpoints, no keys).

Order: OKX (target exchange) -> Binance public market-data host. The source actually used is returned
so it can be logged: fills simulated on a different venue's prices are only approximate."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Callable, List, Tuple

import numpy as np

from .models import Candles

H4_MS = 4 * 3600_000


def _get(url: str, opener, timeout: int = 20):
    with opener(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _to_candles(rows: List[List[float]]) -> Candles:
    rows = sorted({int(r[0]): r for r in rows}.values(), key=lambda r: int(r[0]))
    a = np.array([[float(x) for x in r[:6]] for r in rows])
    return Candles(H4_MS, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])


def fetch_okx(inst: str, n: int, opener=urllib.request.urlopen) -> Candles:
    rows, after = [], None
    while len(rows) < n:
        q = {"instId": inst, "bar": "4H", "limit": "300"}
        if after:
            q["after"] = str(after)
        body = _get("https://www.okx.com/api/v5/market/candles?" + urllib.parse.urlencode(q), opener)
        if body.get("code") != "0":
            raise RuntimeError(f"OKX error {body.get('code')}: {body.get('msg')}")
        page = body["data"]
        if not page:
            break
        rows += [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in page if r[8] == "1"]
        after = min(int(r[0]) for r in page)
    if not rows:
        raise RuntimeError("OKX returned no candles")
    return _to_candles(rows)


def fetch_binance(inst: str, n: int, opener=urllib.request.urlopen) -> Candles:
    sym = inst.replace("-", "")
    url = ("https://data-api.binance.vision/api/v3/klines?" +
           urllib.parse.urlencode({"symbol": sym, "interval": "4h", "limit": str(min(n, 1000))}))
    body = _get(url, opener)
    if not isinstance(body, list) or not body:
        raise RuntimeError("Binance returned no candles")
    return _to_candles([[r[0], r[1], r[2], r[3], r[4], r[5]] for r in body])


SOURCES: List[Tuple[str, Callable]] = [("okx", fetch_okx), ("binance", fetch_binance)]


def fetch_closed_h4(inst: str, now_ms: int, n: int = 700, opener=urllib.request.urlopen,
                    sources=None) -> Tuple[Candles, str]:
    errors = []
    for name, fn in (sources or SOURCES):
        try:
            c = fn(inst, n, opener).closed(now_ms)
            ok, problems = c.quality(now_ms, max_stale_bars=3)
            if not ok:
                raise RuntimeError("bad data: " + "; ".join(problems))
            if len(c) < 450:
                raise RuntimeError(f"only {len(c)} bars")
            return c, name
        except Exception as e:  # noqa: BLE001 - any failure -> try next source
            errors.append(f"{name}: {e}")
    raise RuntimeError("all sources failed: " + " | ".join(errors))
