"""READ-ONLY connectivity check for OKX DEMO: instrument rules + balances. Places no orders.
Env: OKX_DEMO_KEY, OKX_DEMO_SECRET, OKX_DEMO_PASSPHRASE (keys created in OKX *demo trading* mode)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cryptopilot.broker import BrokerError, OkxBroker


def main() -> int:
    b = OkxBroker(os.environ.get("OKX_DEMO_KEY", ""), os.environ.get("OKX_DEMO_SECRET", ""),
                  os.environ.get("OKX_DEMO_PASSPHRASE", ""))
    try:
        for inst in ("BTC-USDT", "ETH-USDT"):
            r = b.instrument(inst)
            print(f"{inst}: tick={r.tick_size} lot={r.lot_step} minSz={r.min_qty}")
        for ccy in ("USDT", "BTC", "ETH"):
            print(f"{ccy} available (demo): {b.balance(ccy)}")
    except BrokerError as e:
        print(f"FAILED: {e}")
        return 1
    print("OK: OKX demo reachable and credentials accepted (read-only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
