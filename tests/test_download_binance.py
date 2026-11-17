import datetime as dt
import io
import os
import sys
import urllib.error
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import download_binance_vision as b  # noqa: E402

from cryptopilot.backtest import load_candles_csv  # noqa: E402

TF = 900_000


def make_zip(first_ts, n, micro=False, header=False):
    lines = ["open_time,open,high,low,close,volume"] if header else []
    for i in range(n):
        t = first_ts + i * TF
        t = t * 1000 if micro else t
        lines.append(f"{t},1,2,0.5,1.5,10,0,0,0,0,0,0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(lines))
    return buf.getvalue()


def test_month_list_excludes_current_and_wraps_year():
    assert b.month_list(3, dt.date(2026, 1, 15)) == [(2025, 10), (2025, 11), (2025, 12)]
    assert (2026, 11) not in b.month_list(24, dt.date(2026, 11, 17))


def test_microsecond_timestamps_normalised():
    ms = b.parse_zip(make_zip(1_700_000_000_000, 3))
    us = b.parse_zip(make_zip(1_700_000_000_000, 3, micro=True))
    assert [r[0] for r in ms] == [r[0] for r in us]
    assert ms[0][0] == 1_700_000_000_000


def test_header_row_skipped():
    assert len(b.parse_zip(make_zip(1_700_000_000_000, 3, header=True))) == 3


def test_download_merges_months_skips_404_and_roundtrips(tmp_path):
    t0 = 1_700_000_000_000 // TF * TF
    blobs = {(2025, 1): make_zip(t0, 5), (2025, 3): make_zip(t0 + 5 * TF, 5, micro=True)}

    def opener(url, timeout=0):
        for (y, m), blob in blobs.items():
            if f"-{y}-{m:02d}.zip" in url:
                class R(io.BytesIO):
                    def __enter__(s): return s
                    def __exit__(s, *a): pass
                return R(blob)
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    rows = b.download("BTCUSDT", "15m", [(2025, 1), (2025, 2), (2025, 3)], opener)
    assert len(rows) == 10
    p = tmp_path / "BTC-USDT_M15.csv"
    b.write_csv(str(p), rows)
    c = load_candles_csv(str(p), TF)
    assert len(c) == 10 and c.ts[0] == t0


def test_other_http_errors_propagate():
    import pytest

    def opener(url, timeout=0):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        b.fetch("http://x", opener)
