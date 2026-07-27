"""CabalSpy — realtime multichain data for labeled wallets.

KOL, smart money and whale wallet tracking across Solana, BNB Chain, Base,
Ethereum and Robinhood Chain.

    from cabalspy import CabalSpy

    client = CabalSpy()                                  # reads CABALSPY_API_KEY
    board = client.wallets.leaderboard(blockchain="solana", period="7d", limit=25)

Async and realtime:

    from cabalspy import AsyncCabalSpy

    async with AsyncCabalSpy() as client:
        signals = await client.signals.list(
            blockchain="solana", type="kol", mode="cluster", min_wallets=5
        )

Docs: https://docs.cabalspy.xyz
"""

from ._client import AsyncCabalSpy, CabalSpy, Envelope
from ._constants import (
    ANALYTICS_MODES,
    BATCH_MAX_ADDRESSES,
    BATCH_MAX_MINTS,
    CHAINS,
    CURRENCY_BY_CHAIN,
    MARKETCAP_CHAINS_REST,
    MAX_LIMIT,
    PERIODS,
    SIGNAL_MODES,
    TIMERANGE_MAX_SECONDS,
    VOLUME_MAX_SECONDS,
    WALLET_TYPES_BY_CHAIN,
    AnalyticsMode,
    Chain,
    Currency,
    Period,
    SignalMode,
    WalletType,
    parse_api_date,
    wallet_type_is_valid,
)
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    CabalSpyError,
    InsufficientCreditsError,
    InvalidResponseError,
    NotFoundError,
    RateLimit,
    RateLimitError,
    ServerError,
)
from ._errors import PermissionError_ as PermissionError
from ._realtime import (
    GATEWAY_EVENTS,
    CabalSpyRealtime,
    is_holder_position_update,
    is_tx_position_update,
)
from ._types import (
    ActiveTokensSummary,
    BundleEntry,
    BundlePosition,
    BundleResponse,
    BundleWallet,
    ClusterSignal,
    CountResponse,
    FeedTransaction,
    HealthResponse,
    HoldingsAfter,
    MetaResponse,
    Pagination,
    PeriodStats,
    ResponseMeta,
    SignalsResponse,
    SignalWallet,
    SignalWindow,
    TokenBlock,
    TokenStatsResponse,
    TokenTrader,
    TraderHoldings,
    TraderStats,
    TransactionsListResponse,
    VolumeResponse,
    WalletProfile,
    WalletTrackerResponse,
    WinRateDistribution,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # clients
    "CabalSpy",
    "AsyncCabalSpy",
    "CabalSpyRealtime",
    "Envelope",
    # errors
    "CabalSpyError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionError",
    "InsufficientCreditsError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "APIConnectionError",
    "InvalidResponseError",
    "RateLimit",
    # constants and helpers
    "CHAINS",
    "WALLET_TYPES_BY_CHAIN",
    "CURRENCY_BY_CHAIN",
    "MARKETCAP_CHAINS_REST",
    "PERIODS",
    "SIGNAL_MODES",
    "ANALYTICS_MODES",
    "BATCH_MAX_MINTS",
    "BATCH_MAX_ADDRESSES",
    "MAX_LIMIT",
    "TIMERANGE_MAX_SECONDS",
    "VOLUME_MAX_SECONDS",
    "GATEWAY_EVENTS",
    "parse_api_date",
    "wallet_type_is_valid",
    "is_tx_position_update",
    "is_holder_position_update",
    # type aliases
    "Chain",
    "WalletType",
    "Period",
    "Currency",
    "SignalMode",
    "AnalyticsMode",
    # response types
    "ResponseMeta",
    "Pagination",
    "WalletProfile",
    "TokenBlock",
    "HoldingsAfter",
    "PeriodStats",
    "WinRateDistribution",
    "ActiveTokensSummary",
    "WalletTrackerResponse",
    "TokenStatsResponse",
    "TokenTrader",
    "TraderHoldings",
    "TraderStats",
    "ClusterSignal",
    "SignalWallet",
    "SignalWindow",
    "SignalsResponse",
    "FeedTransaction",
    "TransactionsListResponse",
    "CountResponse",
    "VolumeResponse",
    "BundleResponse",
    "BundleEntry",
    "BundleWallet",
    "BundlePosition",
    "HealthResponse",
    "MetaResponse",
]
