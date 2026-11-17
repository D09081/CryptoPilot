# "Active" H4 candidates (faster lookbacks), 8-year research, 2026-11-17

Same data, costs, protocol and validator as docs/RESULTS_SLOW.md. Six more pre-registered candidates
(donchian 20/40, ema_trend 20/50 and 30/100, momentum 42/90). Cumulative candidates tried: 12.
Trade counts are pooled over BTC and ETH with one position per pair (the live rules allow one position in total, so live will trade less).

## Result: no candidate admitted
All six were profitable on DEV (<2023) and VALIDATION (2023-24) with PF 2.0-3.5, then weaker on FINAL (2025-26):

| candidate | FINAL trades | net USDT | PF | maxDD | fails |
|---|---|---|---|---|---|
| momentum_90 | 119 | +6.82 | 1.63 | 8.3% | bootstrap |
| ema_trend_30_100 | 42 | +7.05 | 2.09 | 6.0% | bootstrap |
| donchian_40 | 59 | +2.60 | 1.32 | 4.6% | bootstrap |
| momentum_42 | 179 | +3.74 | 1.26 | 6.1% | bootstrap |
| ema_trend_20_50 | 80 | +3.35 | 1.28 | 7.3% | bootstrap |
| donchian_20 | 122 | +2.40 | 1.16 | 7.2% | PF, walk-forward, bootstrap |

Cost stress (fees doubled to 0.20%/side): final net falls by 30-80% (donchian_20 0.5 USDT, PF 1.03; momentum_42 PF 1.07). The faster the strategy, the more the edge depends on costs.

## Reading
- More trades did not buy a bigger edge: gross profit per trade shrinks while costs per trade stay fixed. Drawdown is larger (6-9% vs 2-5%).
- The only benefit of activity is faster accumulation of forward evidence.
- Forward paper accounts: ema_trend_30_100 and momentum_90 (top two by DEV+VALIDATION net profit, selected without using FINAL) were added next to momentum_180/360.
- Still: not OKX data, assumed costs, 12 candidates tried (multiple-testing risk), 2025-26 already seen. Nothing is approved for real money.
