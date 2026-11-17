# Slow H4 trend candidates: 8-year research (2026-11-17)

Data: Binance spot (NOT OKX), BTC-USDT + ETH-USDT, H4, 2018-07-01 .. 2026-10-31 (18,263 bars per pair, 6 short exchange gaps; entries are skipped across a gap, indicators treat the series as continuous).
Account 55 USDT per pair, risk 0.5% per trade, 3*ATR stop, long-only spot, assumed costs: fee 0.10%/side, spread 2 bps, slippage 2 bps, stop slippage 5 bps.
Protocol fixed in advance (see `scripts/run_slow_research.py`): 6 candidates, selection on DEV (<2023) and VALIDATION (2023-2024), then a single FINAL look (2025-2026). 6 candidates tried in total; nothing was tuned.

## Selection (DEV and VALIDATION, pooled over both pairs)
All 6 candidates were profitable with PF 3-11 in both periods and were selected. Max drawdown on the 55 USDT equity: 1.9-4.5%.

## FINAL (2025-01 .. 2026-10), validator verdict: NO candidate admitted
| candidate | trades | net USDT | PF | maxDD | failed check |
|---|---|---|---|---|---|
| momentum_360 | 22 | +8.43 | 3.99 | 2.3% | sample size 22 < 30 (all other checks pass) |
| momentum_180 | 81 | +9.44 | 2.22 | 5.6% | bootstrap 95% lower bound -0.012 (only miss) |
| ema_trend_50_200 | 27 | +5.80 | 2.14 | 5.4% | sample size, bootstrap |
| ema_trend_100_400 | 15 | +1.45 | 1.51 | 3.8% | sample size, bootstrap |
| donchian_120 | 30 | +1.73 | 1.31 | 7.4% | bootstrap |
| donchian_60 | 47 | +1.94 | 1.25 | 5.2% | bootstrap |
Validator thresholds were NOT relaxed after seeing results.

## Pooled net by year (USDT; 110 USDT total equity)
| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| ema_trend_50_200 | -0.6 | 19.9 | 56.0 | 2.9 | -3.7 | 11.8 | 5.3 | 4.8 | 1.0 |
| momentum_180 | -1.3 | 12.2 | 35.9 | 5.7 | -2.4 | 15.4 | 7.0 | 6.2 | 3.3 |
| momentum_360 | -1.3 | 14.2 | 56.0 | 0.1 | -2.3 | 17.2 | 6.5 | 4.1 | 4.3 |

## Honest reading
- Positive in 7 of 9 calendar years, small losses in the 2018 and 2022 bear markets (they sit in cash/stop out); that is the expected trend-following profile.
- Most of the profit is 2019-2021. Recent years are much smaller: 2025-26 combined is single-digit USDT. Edge decay or just a calmer regime: unknown.
- Absolute returns are modest by design: 0.5% risk with wide stops gives small positions. Not a path to large profit on 55 USDT.
- Hindsight/selection bias remains: trend following was chosen because it is known to have worked in crypto; 6 candidates were tried; 2025-26 had already been seen in a preliminary run (momentum_180, donchian_60 passed it first). Costs are assumed, data is not OKX.
- Strategies are NOT connected to the Signal Engine / execution yet and none is admitted.

## Decision
No LIVE. Best candidates for forward PAPER trading: momentum_180 and momentum_360. Forward paper results are the only genuinely new out-of-sample evidence; they decide admission.
