import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import download_okx_candles as d  # noqa: E402

from cryptopilot.backtest import load_candles_csv  # noqa: E402

TF = 900_000
NOW = 10_000 * TF


def fake_opener(total=250):
    """Mimics OKX: newest first, 100 rows per page, `after` returns strictly older rows."""
    all_ts = [NOW - i * TF for i in range(total)]
    calls = []

    def opener(url, timeout=0):
        q = dict(p.split("=") for p in url.split("?")[1].split("&"))
        calls.append(q)
        older = [t for t in all_ts if "after" not in q or t < int(q["after"])][:100]
        data = [[str(t), "1", "2", "0.5", "1.5", "10", "0", "0", "1"] for t in older]

        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): pass
        return R(json.dumps({"code": "0", "msg": "", "data": data}).encode())
    opener.calls = calls
    return opener


def test_paginates_sorts_and_dedupes(tmp_path):
    op = fake_opener(250)
    rows = d.download("BTC-USDT", "15m", NOW - 1000 * TF, op, pause=0)
    ts = [int(r[0]) for r in rows]
    assert len(rows) == 250 and ts == sorted(set(ts))
    assert len(op.calls) == 4   # 3 data pages + 1 empty page = end of history


def test_respects_since_and_csv_roundtrip(tmp_path):
    rows = d.download("BTC-USDT", "15m", NOW - 120 * TF, fake_opener(250), pause=0)
    assert len(rows) == 121 and int(rows[0][0]) == NOW - 120 * TF
    p = tmp_path / "BTC-USDT_M15.csv"
    d.write_csv(str(p), rows)
    c = load_candles_csv(str(p), TF)
    assert len(c) == 121 and c.ts[-1] == NOW


def test_okx_error_raises():
    def bad(url, timeout=0):
        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): pass
        return R(json.dumps({"code": "50011", "msg": "Too many requests", "data": []}).encode())
    import pytest
    with pytest.raises(RuntimeError):
        d.fetch_page("BTC-USDT", "15m", None, bad, retries=1)
