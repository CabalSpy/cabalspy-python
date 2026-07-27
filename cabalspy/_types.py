"""Response shapes, derived from live responses and from the server source.

These are :class:`TypedDict` definitions, so they cost nothing at runtime and
give editors and type checkers something to work with. Responses stay plain
dicts, which means unknown fields the server adds later are never dropped.

Two conventions worth knowing:

1. Timestamps inside ``data`` are NOT ISO 8601. They come back as
   ``"YYYY-MM-DD HH:MM:SS"`` with no timezone, which naive parsing reads as local
   time. Use :func:`cabalspy.parse_api_date`. Only ``meta.timestamp`` is ISO.

2. ``realized_pnl`` is computed as ``total_sell - total_buy``. A wallet that has
   bought and not yet sold reports its whole investment as a loss and
   ``realized_pnl_percentage: -100``. Treat it as net flow and check
   ``still_holding`` before showing it to a user.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from ._constants import Chain, Currency, WalletType

# ── envelope ─────────────────────────────────────────────────────────────────


class ResponseMeta(TypedDict):
    request_id: str
    cached: bool
    cache_age_seconds: int
    version: str
    timestamp: str


class Pagination(TypedDict):
    limit: int
    total: int
    has_more: bool
    next_cursor: str | None


# ── shared ───────────────────────────────────────────────────────────────────


class WalletProfile(TypedDict, total=False):
    wallet_address: str
    name: str
    image_url: str
    twitter: str
    telegram: str
    copytrade_link: str
    type: WalletType
    blockchain: Chain
    currency: Currency
    active_hours: str


class TokenBlock(TypedDict, total=False):
    """Token block from tokens/stats, tokens/holders and tokens/transactions.

    The USD fields are only populated where the endpoint passes the native price
    into the market cap builder. tokens/holders does; tokens/stats and
    tokens/transactions do not, so market_cap_usd, price_usd and sol_price_usd
    come back None there even on Solana.
    """

    blockchain: Chain
    currency: Currency
    mint: str
    token_name: str
    token_supply: float
    token_decimals: int
    market_cap: float | None
    market_cap_usd: float | None
    market_cap_currency: Currency | None
    price: float | None
    price_usd: float | None
    sol_price_usd: float | None
    pool: str | None
    on_curve: bool | None
    bonding_curve_progress: float | None


class HoldingsAfter(TypedDict):
    token_amount: float
    token_amount_peak: float
    supply_pct: float
    supply_pct_peak: float
    bag_pct: float
    still_holding: bool


# ── wallets/tracker ──────────────────────────────────────────────────────────


class PeriodStats(TypedDict, total=False):
    period: str
    buy_txn: int
    sell_txn: int
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    volume: float
    volume_usd: float
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    win_count: int
    loss_count: int
    best_trade_pnl: float
    worst_trade_pnl: float
    largest_buy: float
    avg_hold_time_minutes: float


class WinRateDistribution(TypedDict, total=False):
    below_zero: int
    above_zero_to_100: int
    above_100_to_500: int
    above_500: int
    closed_count: int
    win_count: int
    win_rate_percentage: float


class ActiveTokensSummary(TypedDict, total=False):
    """A summary object, not a list, despite the plural name."""

    active_tokens_count: int
    still_holding_count: int
    avg_position_size: float


class WalletTrackerResponse(TypedDict, total=False):
    wallet: str
    profile: WalletProfile
    period_stats: PeriodStats
    period_active_tokens: ActiveTokensSummary
    period_win_rate_distribution: WinRateDistribution
    period_history_tokens: list[dict[str, Any]]
    period_realized_pnl_chart: list[dict[str, Any]]
    period_trades: list[dict[str, Any]]


# ── tokens/stats ─────────────────────────────────────────────────────────────


class TotalHolders(TypedDict, total=False):
    kol_count: int
    smart_count: int
    whale_count: int
    still_holding_count: int


class TotalHoldings(TypedDict, total=False):
    token_amount: float
    token_amount_peak: float
    supply_pct: float
    supply_pct_peak: float


class TokenTotalStatistics(TypedDict, total=False):
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    total_volume: float
    total_volume_usd: float
    net_flow: float
    net_flow_usd: float
    buying_pressure: float
    avg_position_size: float
    largest_position: float
    first_entry_time: str
    first_entry_type: WalletType
    first_entry_wallet_address: str
    latest_entry_time: str
    latest_entry_type: WalletType
    latest_entry_wallet_address: str
    time_since_first_entry_hours: float


class TraderHoldings(TypedDict, total=False):
    token_amount: float
    token_amount_peak: float
    supply_pct: float
    supply_pct_peak: float
    bag_pct: float
    still_holding: bool
    entry_market_cap: float | None
    entry_market_cap_usd: float | None
    unrealized_pnl_sol: float | None
    unrealized_pnl_usd: float | None
    unrealized_pnl_pct: float | None
    remaining_sol: float | None
    remaining_usd: float | None


class TraderStats(TypedDict, total=False):
    buy: float
    buy_usd: float
    buy_count: int
    buy_tokens: float
    sell: float
    sell_usd: float
    sell_count: int
    sell_tokens: float
    volume_buy: float
    volume_buy_usd: float
    volume_sell: float
    volume_sell_usd: float
    avg_buy_price: float
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    first_trade_at: str
    last_trade_at: str


class TokenTrader(TypedDict, total=False):
    profile: WalletProfile
    trader_holdings: TraderHoldings
    trader_stats: TraderStats


class TokenStatsResponse(TypedDict, total=False):
    token: TokenBlock
    total_holders: TotalHolders
    total_holdings: TotalHoldings
    total_statistics: TokenTotalStatistics
    traders: list[TokenTrader]


# ── signals ──────────────────────────────────────────────────────────────────


class SignalTokenBlock(TypedDict, total=False):
    """Token block on the signals endpoint. Carries no market cap at all."""

    blockchain: Chain
    currency: Currency
    mint: str
    token_name: str
    token_supply: float
    token_decimals: int


class SignalWallet(TypedDict, total=False):
    profile: WalletProfile
    bought_at: str
    is_active: bool
    still_holding: bool
    buy_txn: int
    sell_txn: int
    buy_tokens: float
    sell_tokens: float
    held_tokens: float
    held_tokens_peak: float
    bag_pct: float
    supply_pct: float
    supply_pct_peak: float
    total_buy: float
    total_buy_usd: float
    total_sell: float
    total_sell_usd: float
    realized_pnl: float
    realized_pnl_usd: float
    realized_pnl_percentage: float
    window_buy_txn: int
    window_invested: float
    window_invested_usd: float
    window_tokens_bought: float


class SignalWindow(TypedDict, total=False):
    hours: float
    wallet_count: int
    first_buy_at: str
    latest_buy_at: str
    time_span_minutes: float
    total_invested: float
    total_invested_usd: float
    avg_invested: float
    avg_invested_usd: float
    total_tokens_bought: float
    supply_pct_bought: float


class ClusterSignal(TypedDict, total=False):
    signal_type: Literal["cluster", "entry", "exit"]
    signal_strength: str
    currency: Currency
    token: SignalTokenBlock
    token_stats: dict[str, Any]
    wallets: list[SignalWallet]
    window: SignalWindow


class SignalsResponse(TypedDict, total=False):
    blockchain: Chain
    type: WalletType
    currency: Currency
    mode: Literal["cluster", "entry", "exit"]
    signals: list[ClusterSignal]


# ── feed ─────────────────────────────────────────────────────────────────────


class FeedTransaction(TypedDict, total=False):
    tx_signature: str
    mint: str
    token_name: str
    token_supply: float | None
    token_decimals: int | None
    transaction_type: Literal["buy", "sell"]
    value: float
    value_usd: float | None
    currency: Currency
    token_amount: float | None
    price_per_token: float | None
    price_per_token_usd: float | None
    created_at: str
    profile: WalletProfile
    holdings_after: HoldingsAfter


class TransactionsListResponse(TypedDict, total=False):
    blockchain: Chain
    type: WalletType
    mode: Literal["latest", "timerange"]
    currency: Currency
    count: int
    transactions: list[FeedTransaction]
    time_window_seconds: int
    warnings: list[str]


class CountResponse(TypedDict, total=False):
    blockchain: Chain
    type: WalletType
    mode: Literal["count"]
    count: int
    wallet_count: int
    time_window_seconds: int
    mint: str
    warnings: list[str]


class VolumeResponse(TypedDict, total=False):
    blockchain: Chain
    type: WalletType
    mode: Literal["volume"]
    volume: float
    volume_usd: float | None
    currency: Currency
    time_window_seconds: int
    mint: str
    warnings: list[str]


# ── bundle ───────────────────────────────────────────────────────────────────


class BundlePosition(TypedDict, total=False):
    held: float
    peak: float
    bought_tokens: float
    sold_tokens: float
    bag_pct: float | None
    supply_pct: float | None
    invested: float
    invested_usd: float | None
    max_single_buy: float
    buy_txn: int
    sell_txn: int
    sold_value: float
    sold_value_usd: float | None
    realized_pnl_sol: float
    realized_pnl_usd: float | None
    entry_market_cap: float | None
    entry_market_cap_usd: float | None
    unrealized_pnl_sol: float | None
    unrealized_pnl_usd: float | None
    unrealized_pnl_pct: float | None
    remaining_sol: float | None
    remaining_usd: float | None
    first_buy_at: str | None
    last_activity_at: str | None


class BundleWallet(TypedDict, total=False):
    address: str
    is_kol: bool
    transaction_type: Literal["buy", "sell"]
    signature: str | None
    entry_source: str | None
    position_source: Literal["live"]
    profile: WalletProfile
    position: BundlePosition
    fee_lamports: int | None
    block_index: int | None
    adjacent_to_kol: bool | None
    same_fee: bool | None
    occurrences: int | None


class BundleEntry(TypedDict, total=False):
    bundle_id: str | None
    kol_wallet: str | None
    kol_profile: WalletProfile | None
    confidence: float | None
    jito_confirmed: bool | None
    proof_type: str | None
    slot: int | None
    wallet_count: int
    proof: Any
    verify_hint: Any
    detected_at: str | None
    bundle_wallets: list[BundleWallet]


class BundleResponse(TypedDict, total=False):
    blockchain: Literal["solana"]
    token: TokenBlock
    bundles: list[BundleEntry]


# ── system ───────────────────────────────────────────────────────────────────


class HealthResponse(TypedDict, total=False):
    status: Literal["ok", "degraded"]
    version: str
    components: dict[str, Any]
    latency_ms: float


class MetaResponse(TypedDict, total=False):
    chains: list[Chain]
    wallet_types: list[WalletType]
    periods: list[str]
    currencies: dict[str, str]
    wallet_counts: dict[str, dict[str, int]]
    limits: dict[str, int]
