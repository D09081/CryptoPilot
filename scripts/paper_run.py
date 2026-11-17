"""Scheduled paper-trading run. Exit code != 0 if no price source worked (GitHub then emails the owner)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cryptopilot.paper_job import run_job

if __name__ == "__main__":
    print(run_job(os.environ.get("PAPER_DIR", "paper"), float(os.environ.get("PAPER_EQUITY", "55"))))
