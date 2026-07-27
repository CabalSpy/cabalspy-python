"""Chains, wallet types, currencies and the API's timestamp quirk."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

Chain = Literal["solana", "bnb", "base", "eth", "rh"]
WalletType = Literal["kol", "smart", "whale"]
Period = Literal["6h", "1d", "7d", "30d"]
Currency = Literal["SOL", "BNB", "ETH"]
SignalMode = Literal["cluster", "entry", "exit"]
AnalyticsMode = Literal["volume_trend", "most_traded", "win_rate", "top_performers"]

CHAINS: tuple[Chain, ...] = ("solana", "bnb", "base", "eth", "rh")

#: Which wallet types each chain actually has. Mirrors CHAIN_REGISTRY on the server.
WALLET_TYPES_BY_CHAIN: dict[Chain, tuple[WalletType, ...]] = {
    "solana": ("kol", "smart", "whale"),
    "bnb": ("kol", "smart"),
    "base": ("kol", "smart"),
    "eth": ("kol",),
    "rh": ("kol", "smart"),
}

CURRENCY_BY_CHAIN: dict[Chain, Currency] = {
    "solana": "SOL",
    "bnb": "BNB",
    "base": "ETH",
    "eth": "ETH",
    "rh": "ETH",
}

#: Chains for which the REST API returns market cap, price and unrealized PNL.
#: On every other chain those REST fields come back None.
#:
#: The websocket gateway is different: it computes market cap for all chains, so
#: position_update, holder_update and signal events carry populated market cap
#: and unrealized PNL on bnb, base, eth and rh as well.
MARKETCAP_CHAINS_REST: tuple[Chain, ...] = ("solana",)

PERIODS: tuple[Period, ...] = ("6h", "1d", "7d", "30d")
SIGNAL_MODES: tuple[SignalMode, ...] = ("cluster", "entry", "exit")
ANALYTICS_MODES: tuple[AnalyticsMode, ...] = (
    "volume_trend",
    "most_traded",
    "win_rate",
    "top_performers",
)

BATCH_MAX_MINTS = 100
BATCH_MAX_ADDRESSES = 100
MAX_LIMIT = 200

#: Maximum time windows the feed endpoints accept before clamping.
TIMERANGE_MAX_SECONDS = 60 * 60
VOLUME_MAX_SECONDS = 24 * 60 * 60


def wallet_type_is_valid(chain: str, wallet_type: str) -> bool:
    """True when the chain actually has that wallet type.

    Takes plain str so it can be used to validate untrusted input, not just
    values a type checker has already narrowed to Chain and WalletType.
    """
    for known, types in WALLET_TYPES_BY_CHAIN.items():
        if known == chain:
            return wallet_type in types
    return False


def parse_api_date(value: str | None) -> datetime | None:
    """Parses the timestamps the API returns inside ``data``, as UTC.

    Timestamps in response bodies come back as ``"YYYY-MM-DD HH:MM:SS"`` with no
    timezone marker. Naive parsing treats them as local time, which silently
    shifts every value by the machine's UTC offset. This helper always reads them
    as UTC and also accepts the proper ISO form used by ``meta.timestamp``.

    Returns None for empty input or anything unparseable, rather than raising.
    """
    if not value:
        return None
    text = value.strip()
    try:
        if len(text) == 19 and text[10] == " ":
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None
