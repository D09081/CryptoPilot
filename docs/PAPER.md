# Paper trading (forward test), runs on GitHub Actions

What runs: `.github/workflows/paper.yml` every 4 hours (shortly after each H4 candle closes, UTC) and on demand.
It fetches closed H4 candles (OKX first, Binance public host as fallback), simulates `momentum_180` and `momentum_360`
(two separate paper accounts, 55 USDT each), and commits `paper/*.json` + `paper/REPORT.md` back to the repo.
No keys, no secrets, no real orders.

Rules in the simulation: decision on a closed bar, fill at the next bar's open, fee 0.10%/side, spread 2 bps,
slippage 2 bps (5 bps on stops), 0.5% risk per trade, 3*ATR stop, max ONE open position across BTC and ETH
(the Risk Manager also blocks correlated positions, daily loss >= 1% and drawdown >= 5%). Forward only: history is not traded.

Note: the 8-year backtest allowed one position per pair independently, so it traded more than the live rules allow;
forward results will be lower in trade count.

Control: create an empty file `paper/PAUSE` to stop new entries (open positions are still managed). Delete it to resume.
Exchange rules (lot size, minimum order) are PLACEHOLDERS and must be checked against OKX before trusting small-size behaviour.
If the price source switches between runs, an event is logged: simulated fills are then only approximate.
Not verified from the build environment: that OKX/Binance endpoints are reachable from GitHub runners. The first run answers this.
GitHub may disable scheduled workflows after 60 days of repository inactivity; re-enable them in the Actions tab if so.
