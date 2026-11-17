"""Download public Binance spot candles (monthly archives from data.binance.vision) to CSV.
FALLBACK source when OKX is unreachable. These are BINANCE prices/volumes, not OKX:
good enough to study whether strategies have an edge, but re-validate on OKX data later.
Only complete past months are used. No API key; standard library only.

Usage: python download_binance_vision.py [--months 24] [--out data]
Writes data/BTC-USDT_H4.csv, _H1.csv, _M15.csv (and ETH-USDT) in the format the backtester reads."""
import argparse
import csv
import datetime as dt
import io
import os
import sys
import urllib.error
import urllib.request
import zipfile

BASE = "https://data.binance.vision/data/spot/monthly/klines/{sym}/{iv}/{sym}-{iv}-{y}-{m:02d}.zip"
INTERVALS = {"H4": "4h", "H1": "1h", "M15": "15m"}


def month_list(n, today=None):
    today = today or dt.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((y, m))
    return sorted(out)


def parse_zip(blob):
    """Return rows [ts_ms, o, h, l, c, vol]. Binance spot switched to MICROsecond timestamps in 2025."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            with z.open(name) as f:
                for r in csv.reader(io.TextIOWrapper(f)):
                    if not r or not r[0].strip().isdigit():
                        continue
                    ts = int(r[0])
                    if ts > 10 ** 14:
                        ts //= 1000
                    rows.append([ts, r[1], r[2], r[3], r[4], r[5]])
    return rows


def fetch(url, opener=urllib.request.urlopen):
    try:
        with opener(url, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def download(sym, iv, months, opener=urllib.request.urlopen):
    rows = {}
    for y, m in months:
        blob = fetch(BASE.format(sym=sym, iv=iv, y=y, m=m), opener)
        if blob is None:
            print(f"  (no archive for {y}-{m:02d})", end=" ")
            continue
        for r in parse_zip(blob):
            rows[r[0]] = r
    return [rows[k] for k in sorted(rows)]


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume", "confirm"])
        for r in rows:
            w.writerow(r + ["1"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--out", default="data")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    ap.add_argument("--only", nargs="+", default=list(INTERVALS), choices=list(INTERVALS),
                    help="e.g. --only H4 to fetch only 4h candles")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    months = month_list(a.months)
    for sym in a.symbols:
        pair = sym.replace("USDT", "-USDT")
        for name, iv in ((k, v) for k, v in INTERVALS.items() if k in a.only):
            print(f"{sym} {iv} ...", end=" ", flush=True)
            rows = download(sym, iv, months)
            path = os.path.join(a.out, f"{pair}_{name}.csv")
            write_csv(path, rows)
            print(f"{len(rows)} candles -> {path}")
    print("Done (Binance data, not OKX).")


if __name__ == "__main__":
    sys.exit(main())
