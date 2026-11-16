# CryptoPilot AI (core, work in progress)

Spot-only, long-only decision core for OKX BTC/USDT and ETH/USDT. No profit is promised;
without a validated edge the system stays in observation (HOLD).

Implemented: candle validation (closed candles only), indicators (EMA, RSI, ATR, MACD, VWAP,
volume profile, volume z-score), regime detector, 4 strategies + registry with admission rules,
signal engine, profitability gate, position sizing, risk manager, central settings.
See `docs/STATUS.md` for what is **not** implemented (exchange, paper/demo, bot, Mini App, ...).

## Run tests
    python -m venv .venv && . .venv/bin/activate
    pip install -e ".[dev]"
    python -m pytest

## Configuration
Copy `.env.example` to `.env`. Secrets live only in environment variables. LIVE is blocked
unless `CP_LIVE_ENABLED=true` and a later owner confirmation exists.
