"""Centralised, server-side settings. No secrets are stored here (secrets are
read by the exchange/bot adapters straight from environment variables)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

SYMBOLS = ("BTC/USDT", "ETH/USDT")
CAPITAL_RUB = 5000.0


class Mode(str, Enum):
    OBSERVE = "OBSERVE"
    BACKTEST = "BACKTEST"
    DEMO = "DEMO"
    PAPER = "PAPER"
    LIVE = "LIVE"


def capital_usdt(rub_per_usdt: float, capital_rub: float = CAPITAL_RUB) -> float:
    """Convert the RUB capital to USDT using a *live* RUB/USDT rate (never hardcoded)."""
    if rub_per_usdt is None or not math.isfinite(rub_per_usdt) or rub_per_usdt <= 0:
        raise ValueError("invalid RUB/USDT rate")
    return capital_rub / rub_per_usdt


@dataclass(frozen=True)
class Settings:
    mode: Mode = Mode.OBSERVE
    live_enabled: bool = False
    owner_telegram_id: Optional[int] = None
    database_url: str = "sqlite:///cryptopilot.db"


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    raw_mode = env.get("CP_MODE", "OBSERVE").upper()
    try:
        mode = Mode(raw_mode)
    except ValueError as exc:
        raise ValueError(f"unknown CP_MODE: {raw_mode}") from exc
    live_enabled = env.get("CP_LIVE_ENABLED", "false").lower() == "true"
    if mode is Mode.LIVE and not live_enabled:
        raise ValueError("CP_MODE=LIVE requires CP_LIVE_ENABLED=true (explicit owner opt-in)")
    owner = env.get("CP_OWNER_TELEGRAM_ID")
    return Settings(
        mode=mode,
        live_enabled=live_enabled,
        owner_telegram_id=int(owner) if owner else None,
        database_url=env.get("CP_DATABASE_URL", "sqlite:///cryptopilot.db"),
    )
