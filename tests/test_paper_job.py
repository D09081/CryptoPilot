import json
import os

import numpy as np

from conftest import make_candles
from cryptopilot import paper_job

H4 = 4 * 3600_000
NOW = 1_800_000_000_000


def fake_fetch_factory(n):
    rng = np.random.default_rng(5)
    base = {s: make_candles(100 * np.exp(np.cumsum(0.0007 + rng.normal(0, 0.012, 1100))), H4, now=NOW)
            for s in ("BTC-USDT", "ETH-USDT")}

    def fetch(inst, now_ms):
        c = base[inst]
        return type(c)(c.tf_ms, *(a[:n] for a in (c.ts, c.open, c.high, c.low, c.close, c.volume))), "okx"
    return fetch


def test_job_creates_state_and_report_then_resumes(tmp_path):
    d = str(tmp_path / "paper")
    paper_job.run_job(d, 55.0, NOW, fake_fetch_factory(600))          # first run: forward-only start
    assert sorted(os.listdir(d)) == ["REPORT.md", "ema_trend_30_100.json", "momentum_180.json",
                                     "momentum_360.json", "momentum_90.json"]
    s1 = json.load(open(f"{d}/momentum_180.json"))
    assert s1["trades"] == [] and s1["last_ts"] is not None
    text = paper_job.run_job(d, 55.0, NOW, fake_fetch_factory(1100))  # later run processes the new bars
    s2 = json.load(open(f"{d}/momentum_180.json"))
    assert s2["last_ts"] > s1["last_ts"] and s2["events"]
    assert "SIMULATION" in text and "momentum_180" in text and "No real orders" in text
    again = json.load(open(f"{d}/momentum_180.json"))
    paper_job.run_job(d, 55.0, NOW, fake_fetch_factory(1100))
    assert json.load(open(f"{d}/momentum_180.json")) == again          # idempotent


def test_pause_file_blocks_new_signals(tmp_path):
    d = str(tmp_path / "paper")
    os.makedirs(d)
    open(f"{d}/PAUSE", "w").close()
    paper_job.run_job(d, 55.0, NOW, fake_fetch_factory(600))
    paper_job.run_job(d, 55.0, NOW, fake_fetch_factory(1100))
    st = json.load(open(f"{d}/momentum_180.json"))
    assert st["trades"] == [] and st["pos"] is None and st["pending_entry"] is None
