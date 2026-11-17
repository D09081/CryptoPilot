# Backtest results (stage 6, first real-data run)

Run date: 2026-11-17. **Data: Binance spot (not OKX)**, 2024-11-01 .. 2026-10-31, BTC-USDT and ETH-USDT,
H4/H1/M15, 70,080 M15 bars per pair, no gaps. Equity 55 USDT (about 5,000 RUB), risk 0.5% per trade.
Assumed costs: taker 0.10%, maker 0.08%, spread 2 bps, slippage 2 bps, stop slippage 5 bps (constants; no historical order book).
Last 40% of the history is out-of-sample (validator evaluates only that part). Strategy parameters were NOT tuned.

## Verdict: no strategy passed validation. Nothing is admitted; the engine stays in HOLD.

| Pair | Strategy | OOS trades | OOS net (USDT) | PF | Result |
|---|---|---|---|---|---|
| BTC | trend_following | 187 | -16.64 | 0.42 | FAIL |
| BTC | breakout | 13 | -1.93 | 0.28 | FAIL |
| BTC | mean_reversion | 1 | +0.05 | n/a | FAIL (1 trade) |
| BTC | volatility_adaptive | 69 | -6.41 | 0.41 | FAIL |
| ETH | trend_following | 182 | -11.74 | 0.57 | FAIL |
| ETH | breakout | 15 | +0.25 | 1.12 | FAIL (sample, PF, bootstrap) |
| ETH | mean_reversion | 2 | -0.53 | 0.00 | FAIL |
| ETH | volatility_adaptive | 60 | -2.62 | 0.68 | FAIL |

## Diagnostic: zero costs
With all costs set to zero the strategies are close to break-even (BTC trend PF 0.99, vol-adaptive 0.96; ETH PF 1.09 / 1.53 on few trades).
Reading: the signals carry no demonstrated edge, and realistic costs (about 0.2-0.3% round trip) on a 55 USDT account with a 0.5% risk budget turn them clearly negative.
This also indicates the backtest engine is behaving sensibly (no phantom profits).

## What this does NOT show
- Not OKX data; costs and spread are assumptions. Fee tier and minimum order rules must be checked on the real OKX account.
- Mean reversion and breakout produce too few trades to judge.
- Results are for the current strategy definitions only. Do not tweak parameters until the OOS part looks good: that would be overfitting. Any new idea must be validated on data it was not developed on (e.g. keep a final untouched period).

## Consequence
LIVE trading is not justified. Do not use real money. Next sensible steps: decide whether to research different strategy ideas (with a held-out final period), or to continue building the infrastructure (paper trading, bot, Mini App) around a system that currently trades nothing.
