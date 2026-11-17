"""One scheduled DEMO run: paper decision for ONE strategy -> mirror onto the OKX demo account.
Env: OKX_DEMO_KEY, OKX_DEMO_SECRET, OKX_DEMO_PASSPHRASE; optional DEMO_STRATEGY (default momentum_90),
DEMO_DIR (default demo). Writes DEMO_REPORT.md. Exit code 1 if there are alerts (so the owner gets notified)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cryptopilot.broker import OkxBroker
from cryptopilot.demo import DemoMirror, new_demo_state
from cryptopilot.executor import Executor
from cryptopilot.paper_job import STRATEGIES, SYMBOLS, run_job


def main() -> int:
    name = os.environ.get("DEMO_STRATEGY", "momentum_90")
    d = os.environ.get("DEMO_DIR", "demo")
    strat = next(s for s in STRATEGIES if s.name == name)
    os.makedirs(d, exist_ok=True)
    run_job(os.path.join(d, "paper"), 55.0, strategies=[strat])            # decision (simulated sizing)
    paper = json.load(open(os.path.join(d, "paper", f"{name}.json")))
    pos = paper["pos"]
    desired = {"symbol": pos["symbol"], "qty": pos["qty"], "stop": pos["stop"], "entry_ts": pos["entry_ts"]} if pos else None

    broker = OkxBroker(os.environ["OKX_DEMO_KEY"], os.environ["OKX_DEMO_SECRET"], os.environ["OKX_DEMO_PASSPHRASE"])
    rules = {s: broker.instrument(s.replace("/", "-")) for s in SYMBOLS}
    path = os.path.join(d, f"{name}.json")
    st = json.load(open(path)) if os.path.exists(path) else new_demo_state(name)
    alerts = DemoMirror(Executor(broker), rules, st).sync(desired, int(time.time() * 1000))
    json.dump(st, open(path, "w"), indent=1, sort_keys=True)
    lines = ["# OKX DEMO mirror status", "", "DEMO account only (no real money).", f"Strategy: {name}",
             f"Desired (from paper engine): {desired}", f"Tracked on demo: {st['tracked']}", "", "Recent events:"]
    lines += [f"- {e['msg']}" for e in st["events"][-15:]] or ["- none"]
    lines += ["", "ALERTS: " + ("; ".join(alerts) if alerts else "none")]
    open(os.path.join(d, "DEMO_REPORT.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
