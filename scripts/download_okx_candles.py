"""Download public OKX candles to CSV (no API key needed, standard library only).

Usage:  python download_okx_candles.py [--days 730] [--out data]
Creates data/BTC-USDT_H4.csv, _H1.csv, _M15.csv and the same for ETH-USDT.
Only public market data is requested; nothing is sent to OKX except the query."""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "https://www.okx.com/api/v5/market/history-candles"
BARS = {"H4": ("4H", 4 * 3600_000), "H1": ("1H", 3600_000), "M15": ("15m", 900_000)}


def fetch_page(inst, bar, after, opener=urllib.request.urlopen, retries=5):
    q = {"instId": inst, "bar": bar, "limit": "100"}
    if after:
        q["after"] = str(after)
    url = URL + "?" + urllib.parse.urlencode(q)
    for attempt in range(retries):
        try:
            with opener(url, timeout=20) as r:
                body = json.loads(r.read().decode())
            if body.get("code") == "0":
                return body["data"]
            raise RuntimeError(f"OKX error {body.get('code')}: {body.get('msg')}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(1 + attempt * 2)


def download(inst, bar, since_ms, opener=urllib.request.urlopen, pause=0.15):
    rows, after = {}, None
    while True:
        page = fetch_page(inst, bar, after, opener)
        if not page:
            break
        for r in page:
            rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in page)
        if oldest <= since_ms or (after is not None and oldest >= after):
            break
        after = oldest
        time.sleep(pause)
    return [rows[k] for k in sorted(rows) if k >= since_ms]


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume", "confirm"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[8]])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--out", default="data")
    ap.add_argument("--symbols", nargs="+", default=["BTC-USDT", "ETH-USDT"])
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    since = int((time.time() - a.days * 86400) * 1000)
    for inst in a.symbols:
        for name, (bar, _) in BARS.items():
            path = os.path.join(a.out, f"{inst}_{name}.csv")
            print(f"{inst} {name} ...", end=" ", flush=True)
            rows = download(inst, bar, since)
            write_csv(path, rows)
            print(f"{len(rows)} candles -> {path}")
    print("Done. Send the files (or a zip of the folder) back.")


if __name__ == "__main__":
    sys.exit(main())
