# OKX Demo trading (stage 8)

Code: `cryptopilot/broker.py` (OKX adapter, DEMO ONLY: constructing it for live raises PermissionError),
`cryptopilot/executor.py` (idempotent orders, timeout handling, partial fills, protective stop, emergency sell, reconciliation),
`cryptopilot/demo.py` (mirrors one paper strategy onto the demo account), `scripts/demo_check.py`, `scripts/demo_run.py`,
workflow `.github/workflows/okx-demo.yml` (manual).

## What is verified, what is not
Verified: logic against an in-memory fake exchange (duplicates, timeouts, lost orders, partial fills, failed stop, failed emergency sell,
restart idempotency), request signing/headers/body formatting against reference computations, with mutation checks on the safety rules.
NOT verified: any real OKX response. Field names/endpoints follow OKX v5 docs from memory and may need small fixes on the first real run:
that is exactly what the demo account is for. Instrument minimum order values are not published by OKX as notional; `min_notional=1.0` is a placeholder.

## Setup (from a phone)
1. In the OKX app/site switch to **Demo trading** and create a demo API key (permission: Trade). Keep the passphrase. Menu names differ by version.
2. GitHub -> repository **Settings -> Secrets and variables -> Actions -> New repository secret**, three secrets:
   `OKX_DEMO_KEY`, `OKX_DEMO_SECRET`, `OKX_DEMO_PASSPHRASE`. Never paste them in chat or commits.
3. **Actions -> okx-demo -> Run workflow -> mode: check.** Green = reachable and credentials accepted. Red = open the log and read the error.
   Likely failure: OKX may refuse GitHub's US servers. Then the demo must run from a non-US host (e.g. a small VPS); the same scripts work there.
4. Only after `check` is green: mode `run` (one strategy, default momentum_90, env DEMO_STRATEGY to change). It places DEMO orders and commits `demo/*`.

Scheduling `run` is deliberately not enabled yet.
