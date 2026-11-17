# "Fast" H1 candidates, 8-year research, 2026-11-17

Data: Binance spot H1, BTC-USDT + ETH-USDT, 2018-07..2026-10 (73,004 bars per pair, 23 short gaps). Same costs, protocol and validator
as RESULTS_SLOW.md (fee 0.10%/side, spread 2 bps, slippage 2 bps). Six candidates declared in advance (donchian 24/48, ema_trend 12/48 and 24/96,
momentum 24/72). Cumulative candidates tried across all families: 18.

## Result: every fast candidate fails. Nothing is added to paper trading.
- DEV/VALIDATION: momentum_24 and donchian_24 rejected (losing); 4 of 6 pass selection with PF 1.2-2.0 and drawdowns 7-15%.
- FINAL (2025-26): all four selected candidates LOSE money:

| candidate | trades | net USDT | PF | maxDD |
|---|---|---|---|---|
| donchian_48 | 239 | -2.48 | 0.94 | 17.8% |
| ema_trend_12_48 | 430 | -4.98 | 0.92 | 22.6% |
| ema_trend_24_96 | 263 | -6.32 | 0.86 | 21.3% |
| momentum_72 | 580 | -13.33 | 0.79 | 35.1% |

- With fees doubled (0.20%/side) only ema_trend_24_96 passes selection and it loses 12.5 USDT on FINAL (PF 0.74, maxDD 28.5%); momentum_24 loses on every period.

## Reading
Costs of about 0.25-0.3% per round trip leave no room on 1-hour horizons: the edge that exists on H4 disappears. More trades means more drawdown and more fees.
Conclusion: on this account size and fee tier, the faster the strategy the worse; H4 is the practical lower bound among the tested families.
Not tested: different strategy families (e.g. order-flow/microstructure), maker-only execution (lower fees, but fill uncertainty), lower-fee accounts.
