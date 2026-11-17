# Readiness status (honest)

The project is **NOT ready** for Demo, Paper or Live trading. Only the decision core exists.

| # | Stage | Status |
|---|-------|--------|
| 1 | Audit | Done (repo was empty) |
| 2 | Architecture/refactor | Package skeleton only |
| 3 | Market data, indicators, regimes | Indicators + regime detector + candle validation done. **No OKX data client.** |
| 4 | Strategy / Signal / Profitability Gate | Done and unit-tested on synthetic data |
| 5 | Risk Manager, sizing | Done and unit-tested. **No Portfolio Manager persistence.** |
| 6 | Backtesting + Validator | Engine, metrics, validator, CSV loader and CLI (`scripts/run_backtest.py`) done and unit-tested. **Not yet run on real OKX data (no data access), so no strategy is validated or admitted and the engine always HOLDs.** Missing: parameter-sensitivity and per-regime checks, order-book-based costs. |
| 7 | Paper trading + Execution Engine | Not started |
| 8 | OKX Demo | Not started |
| 9 | Champion-Challenger, Market Memory | Not started |
| 10 | News / Whale / Order Flow | Not started |
| 11 | Telegram Bot | Not started |
| 12 | Mini App + Dashboard API | Not started |
| 13 | Monitoring, recovery, security | Not started (only Risk Manager vetoes, kill/halt/anomaly flags) |
| 14 | Integration tests, Docker, docs | Not started |

## Tests
`python -m pytest` -> see README. All tests use synthetic data and illustrative (non-OKX) exchange rules.
Synthetic tests prove the logic is correct, **not that any strategy is profitable.**

## Design decisions to review
- Strategies are CANDIDATE by default; only `StrategyRegistry.admit()` with independently validated stats (>=30 trades, positive net expectancy) enables one.
- Profitability Gate uses the Wilson lower bound of the validated win rate, never strategy "confidence".
- Risk Manager recomputes trade risk itself; limits are capped by `HARD_CAPS` and change only with owner authorisation.
- Thresholds (EMA separation 0.2%, volatility 1.25x/0.75x median, EV/cost ratio 0.5, min 30 trades) are unvalidated starting values.

## Stage 6 notes
- Backtest: signal from bar j close, fill at bar j+1 open; stop assumed first if stop and target are in the same bar; gaps fill at the open; data gaps block trading; spread/slippage are assumed constants.
- Smoke run on a synthetic random walk: no strategy passed validation (expected), and the strategies fire rarely (trend: 2 trades in 9,600 M15 bars). With so few trades the 30-trade OOS minimum may be hard to reach: thresholds need review on real data, not loosening to make something pass.
- Per-trade Sharpe/Sortino are not annualised.

## Data download
`scripts/download_okx_candles.py` fetches public OKX candles (no keys). Tested only against a mocked server: never run against real OKX from this environment (blocked).

`scripts/download_binance_vision.py`: fallback source (Binance monthly archives) used when OKX is unreachable (e.g. Colab/US IPs). Binance data is NOT OKX data; results must be re-validated on OKX candles. Tested only against mocked downloads.
