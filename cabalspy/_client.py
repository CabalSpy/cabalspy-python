"""HTTP clients for the CabalSpy API, synchronous and asynchronous.

The resource classes are shared between both clients. Their methods simply return
whatever the underlying requester returns: a dict on the sync client, an awaitable
on the async one. That keeps the endpoint surface defined exactly once.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, AsyncIterator, Iterator, Mapping, Sequence

import httpx

from ._constants import (
    BATCH_MAX_ADDRESSES,
    BATCH_MAX_MINTS,
    CHAINS,
    WALLET_TYPES_BY_CHAIN,
    AnalyticsMode,
    Chain,
    Period,
    SignalMode,
    WalletType,
    wallet_type_is_valid,
)
from ._errors import (
    APIConnectionError,
    BadRequestError,
    CabalSpyError,
    InvalidResponseError,
    RateLimit,
    RateLimitError,
    error_from_status,
    is_retryable,
)

__all__ = ["CabalSpy", "AsyncCabalSpy", "Envelope"]

DEFAULT_BASE_URL = "https://api.cabalspy.xyz/v1"
DEFAULT_WS_URL = "wss://stream.cabalspy.xyz"
SDK_VERSION = "0.2.0"


class Envelope:
    """A full API response: data plus pagination, meta and rate limit headers."""

    __slots__ = ("data", "pagination", "meta", "rate_limit", "status")

    def __init__(
        self,
        data: Any,
        pagination: dict[str, Any] | None,
        meta: dict[str, Any],
        rate_limit: RateLimit,
        status: int,
    ) -> None:
        self.data = data
        self.pagination = pagination
        self.meta = meta
        self.rate_limit = rate_limit
        self.status = status

    def __repr__(self) -> str:
        keys = list(self.data)[:5] if isinstance(self.data, dict) else type(self.data).__name__
        return f"Envelope(status={self.status}, data_keys={keys})"


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drops None and empty values so they never reach the query string."""
    if not params:
        return {}
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        out[key] = "true" if value is True else "false" if value is False else value
    return out


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _backoff(attempt: int, last: BaseException | None) -> float:
    """Server Retry-After wins over our own exponential backoff."""
    if isinstance(last, RateLimitError) and last.retry_after is not None:
        return min(last.retry_after, 60.0)
    return min(0.5 * (2 ** (attempt - 1)), 8.0) + random.random() * 0.25


def _validate_chain_type(chain: str, wallet_type: str | None) -> None:
    """Rejects impossible chain and wallet type combinations before the request."""
    if chain not in CHAINS:
        raise BadRequestError(
            f"Unknown blockchain {chain!r}",
            code="invalid_parameter",
            parameter="blockchain",
            allowed=list(CHAINS),
        )
    if wallet_type is not None and not wallet_type_is_valid(chain, wallet_type):
        allowed = list(WALLET_TYPES_BY_CHAIN[chain])  # type: ignore[index]
        raise BadRequestError(
            f"{chain} supports only: {', '.join(allowed)}",
            code="invalid_parameter",
            parameter="type",
            allowed=allowed,
        )


# ═══════════════════════════════════════════════════════════════════════════
#  RESOURCES  (shared between the sync and async clients)
# ═══════════════════════════════════════════════════════════════════════════


class _Resource:
    def __init__(self, client: "_BaseClient") -> None:
        self._c = client


class SystemResource(_Resource):
    def health(self) -> Any:
        """GET /v1/health — Redis, MySQL and websocket status per chain and type.

        Answers without the success/data envelope, so it is fetched unwrapped.
        """
        return self._c._get_plain("/health")

    def meta(self) -> Any:
        """GET /v1/meta — available chains, types, periods, limits, wallet counts."""
        return self._c._get_plain("/meta")


class WalletsResource(_Resource):
    def list(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/wallets — every tracked wallet for one chain and wallet type.

        Omitting ``limit`` returns every wallet.
        """
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/wallets", {"blockchain": blockchain, "type": type, "limit": limit, "cursor": cursor}
        )

    def history(
        self,
        *,
        blockchain: Chain,
        address: str,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/wallets/history — trade history. Server default 500, max 1000."""
        _validate_chain_type(blockchain, None)
        return self._c._get(
            "/wallets/history",
            {"blockchain": blockchain, "address": address, "limit": limit, "cursor": cursor},
        )

    def lookup(self, address: str) -> Any:
        """GET /v1/wallets/lookup — searches an address across all chains and types.

        Takes no blockchain argument by design. Note that for EVM chains the same
        address can exist on several of them; the endpoint returns the first match
        in the server's registry order, which may not be the chain you meant.
        """
        return self._c._get("/wallets/lookup", {"address": address})

    def leaderboard(
        self,
        *,
        blockchain: Chain,
        type: WalletType = "kol",
        period: Period = "1d",
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Any:
        """GET /v1/wallets/leaderboard — ranking for the given period."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/wallets/leaderboard",
            {
                "blockchain": blockchain,
                "type": type,
                "period": period,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def tracker(self, *, blockchain: Chain, address: str, period: Period = "1d") -> Any:
        """GET /v1/wallets/tracker — period stats and open positions for a wallet."""
        _validate_chain_type(blockchain, None)
        return self._c._get(
            "/wallets/tracker",
            {"blockchain": blockchain, "address": address, "period": period},
        )

    def holdings(self, *, blockchain: Chain, address: str) -> Any:
        """GET /v1/wallets/holdings — current onchain holdings, period independent."""
        _validate_chain_type(blockchain, None)
        return self._c._get("/wallets/holdings", {"blockchain": blockchain, "address": address})

    def pnl_calendar(self, *, blockchain: Chain, address: str) -> Any:
        """GET /v1/wallet/pnl_calendar — daily PNL calendar.

        This endpoint only exists under /wallet/, singular.
        """
        _validate_chain_type(blockchain, None)
        return self._c._get("/wallet/pnl_calendar", {"blockchain": blockchain, "address": address})

    def connections(self, *, blockchain: Chain, address: str, limit: int | None = None) -> Any:
        """GET /v1/wallets/connections — wallets whose traded tokens overlap, 30d."""
        _validate_chain_type(blockchain, None)
        return self._c._get(
            "/wallets/connections",
            {"blockchain": blockchain, "address": address, "limit": limit},
        )

    def batch(
        self,
        *,
        blockchain: Chain,
        addresses: Sequence[str],
        type: WalletType = "kol",
        fields: Sequence[str] | None = None,
        period: Period = "7d",
    ) -> Any:
        """POST /v1/wallets/batch — up to 100 addresses in one request."""
        _validate_chain_type(blockchain, type)
        if not addresses:
            raise BadRequestError(
                "addresses must not be empty", code="missing_parameter", parameter="addresses"
            )
        if len(addresses) > BATCH_MAX_ADDRESSES:
            raise BadRequestError(
                f"At most {BATCH_MAX_ADDRESSES} addresses per request, received {len(addresses)}",
                code="invalid_parameter",
                parameter="addresses",
            )
        body: dict[str, Any] = {
            "blockchain": blockchain,
            "type": type,
            "addresses": list(addresses),
            "period": period,
        }
        if fields is not None:
            body["fields"] = list(fields)
        return self._c._post("/wallets/batch", body)


class TokensResource(_Resource):
    def transactions(
        self,
        *,
        blockchain: Chain,
        mint: str,
        type: WalletType | None = None,
        limit: int | None = None,
    ) -> Any:
        """GET /v1/tokens/transactions — trades by tracked wallets in this token."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/tokens/transactions",
            {"blockchain": blockchain, "mint": mint, "type": type, "limit": limit},
        )

    def stats(self, *, blockchain: Chain, mint: str, type: WalletType | None = None) -> Any:
        """GET /v1/tokens/stats — aggregated token statistics.

        Omitting ``type`` merges every wallet type of that chain. Note that this
        endpoint does not pass the native price into its market cap builder, so
        market_cap_usd, price_usd and sol_price_usd come back None even on Solana.
        tokens/holders returns them populated.
        """
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/tokens/stats", {"blockchain": blockchain, "mint": mint, "type": type}
        )

    def holders(
        self,
        *,
        blockchain: Chain,
        mint: str,
        type: WalletType | None = None,
        limit: int | None = None,
    ) -> Any:
        """GET /v1/tokens/holders — tracked holders, sorted by balance."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/tokens/holders",
            {"blockchain": blockchain, "mint": mint, "type": type, "limit": limit},
        )

    def batch(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        mints: Sequence[str],
        fields: Sequence[str] | None = None,
    ) -> Any:
        """POST /v1/tokens/batch — up to 100 mints in one request."""
        _validate_chain_type(blockchain, type)
        if not mints:
            raise BadRequestError(
                "mints must not be empty", code="missing_parameter", parameter="mints"
            )
        if len(mints) > BATCH_MAX_MINTS:
            raise BadRequestError(
                f"At most {BATCH_MAX_MINTS} mints per request, received {len(mints)}",
                code="invalid_parameter",
                parameter="mints",
            )
        body: dict[str, Any] = {"blockchain": blockchain, "type": type, "mints": list(mints)}
        if fields is not None:
            body["fields"] = list(fields)
        return self._c._post("/tokens/batch", body)


class TransactionsResource(_Resource):
    def latest(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        limit: int | None = None,
        mint: str | None = None,
    ) -> Any:
        """GET /v1/transactions/latest — most recent trades by tracked wallets."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/transactions/latest",
            {"blockchain": blockchain, "type": type, "limit": limit, "mint": mint},
        )

    def timerange(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        seconds: int | None = None,
        minutes: int | None = None,
        limit: int | None = None,
        mint: str | None = None,
    ) -> Any:
        """GET /v1/transactions/timerange — trades in the last N, capped at 60 minutes."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/transactions/timerange",
            {
                "blockchain": blockchain,
                "type": type,
                "seconds": seconds,
                "minutes": minutes,
                "limit": limit,
                "mint": mint,
            },
        )

    def count(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        seconds: int | None = None,
        minutes: int | None = None,
        hours: int | None = None,
        mint: str | None = None,
    ) -> Any:
        """GET /v1/transactions/count — trade count and unique wallets, up to 24h."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/transactions/count",
            {
                "blockchain": blockchain,
                "type": type,
                "seconds": seconds,
                "minutes": minutes,
                "hours": hours,
                "mint": mint,
            },
        )

    def volume(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        seconds: int | None = None,
        minutes: int | None = None,
        hours: int | None = None,
        mint: str | None = None,
    ) -> Any:
        """GET /v1/transactions/volume — volume in native currency and USD, up to 24h."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/transactions/volume",
            {
                "blockchain": blockchain,
                "type": type,
                "seconds": seconds,
                "minutes": minutes,
                "hours": hours,
                "mint": mint,
            },
        )


class SignalsResource(_Resource):
    def list(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        mode: SignalMode,
        limit: int | None = None,
        min_wallets: int | None = None,
        min_value: float | None = None,
        hours: int | None = None,
        **gated: Any,
    ) -> Any:
        """GET /v1/signals — live clusters, entries and exits.

        Smart money is unavailable on eth. Setting any gated filter (``kol``,
        ``smart``, ``kol_min_buy``, ``kol_exit``, ``include_wallets``,
        ``min_win_rate``, ``min_token_age`` and so on) switches the server into
        gated mode, which applies an AND gate across wallet types.
        """
        _validate_chain_type(blockchain, type)
        params: dict[str, Any] = {
            "blockchain": blockchain,
            "type": type,
            "mode": mode,
            "limit": limit,
            "min_wallets": min_wallets,
            "min_value": min_value,
            "hours": hours,
        }
        params.update(gated)
        return self._c._get("/signals", params)

    def history(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        days: int | str | None = None,
        limit: int | None = None,
        mode: SignalMode | None = None,
        **gated: Any,
    ) -> Any:
        """GET /v1/signals/history — backtest over 7, 30 or 90 days, or "all"."""
        _validate_chain_type(blockchain, type)
        params: dict[str, Any] = {
            "blockchain": blockchain,
            "type": type,
            "days": days,
            "limit": limit,
            "mode": mode,
        }
        params.update(gated)
        return self._c._get("/signals/history", params)


class AnalyticsResource(_Resource):
    def get(
        self,
        *,
        blockchain: Chain,
        type: WalletType,
        mode: AnalyticsMode,
        period: Period = "7d",
        limit: int | None = None,
    ) -> Any:
        """GET /v1/analytics — volume_trend, most_traded, win_rate or top_performers."""
        _validate_chain_type(blockchain, type)
        return self._c._get(
            "/analytics",
            {
                "blockchain": blockchain,
                "type": type,
                "mode": mode,
                "period": period,
                "limit": limit,
            },
        )


class BundleResource(_Resource):
    def get(self, *, mint: str, blockchain: str = "solana") -> Any:
        """GET /v1/bundle — snapshot of the bundle stream. Solana only."""
        if blockchain != "solana":
            raise BadRequestError(
                "The bundle endpoint is available for solana only",
                code="invalid_parameter",
                parameter="blockchain",
                allowed=["solana"],
            )
        return self._c._get("/bundle", {"blockchain": "solana", "mint": mint})


# ═══════════════════════════════════════════════════════════════════════════
#  CLIENTS
# ═══════════════════════════════════════════════════════════════════════════


class _BaseClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        ws_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        headers: Mapping[str, str] | None = None,
        pays_per_call: bool = False,
    ) -> None:
        key = api_key or os.environ.get("CABALSPY_API_KEY")
        if not key and not pays_per_call:
            raise CabalSpyError(
                "Missing credentials. Pass api_key=, set CABALSPY_API_KEY, or hand in an "
                "http_client that pays per call with x402.",
                code="missing_api_key",
            )
        self._api_key = key or ""

        #: True when requests are paid per call rather than authenticated by key.
        self.pays_per_call = bool(pays_per_call and not key)
        self.base_url = (base_url or os.environ.get("CABALSPY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.ws_url = (ws_url or os.environ.get("CABALSPY_WS_URL") or DEFAULT_WS_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._extra_headers = dict(headers or {})
        #: Rate limit state from the most recent request.
        self.last_rate_limit = RateLimit()

        self.system = SystemResource(self)
        self.wallets = WalletsResource(self)
        self.tokens = TokensResource(self)
        self.transactions = TransactionsResource(self)
        self.signals = SignalsResource(self)
        self.analytics = AnalyticsResource(self)
        self.bundle = BundleResource(self)

    # ── plumbing shared by both clients ──────────────────────────────────

    def _request_headers(self, json_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"cabalspy-python/{SDK_VERSION}",
        }
        # Omitted when paying per call: an empty bearer token is rejected before
        # the server ever offers a price, so the payment flow never starts.
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if json_body:
            headers["Content-Type"] = "application/json"
        headers.update(self._extra_headers)
        return headers

    def _interpret(self, response: httpx.Response, method: str, path: str) -> Envelope:
        """Turns an HTTP response into an Envelope, or raises the right error."""
        rate_limit = RateLimit(
            _int_header(response.headers, "X-RateLimit-Limit"),
            _int_header(response.headers, "X-RateLimit-Remaining"),
            _int_header(response.headers, "X-RateLimit-Reset"),
        )
        self.last_rate_limit = rate_limit

        try:
            parsed: Any = response.json() if response.content else None
        except ValueError:
            parsed = None

        if response.status_code >= 400:
            body = parsed.get("error") if isinstance(parsed, dict) else None
            raise error_from_status(
                response.status_code,
                body if isinstance(body, dict) else None,
                rate_limit,
                _int_header(response.headers, "Retry-After"),
                f"HTTP {response.status_code} on {method} {path}",
            )

        if not isinstance(parsed, dict) or "data" not in parsed:
            raise InvalidResponseError(
                f"Unexpected response shape on {method} {path}: no data field",
                status=response.status_code,
                code="invalid_response",
                rate_limit=rate_limit,
            )

        return Envelope(
            parsed["data"],
            parsed.get("pagination"),
            parsed.get("meta") or {},
            rate_limit,
            response.status_code,
        )

    def _connection_error(self, exc: Exception, method: str, path: str) -> APIConnectionError:
        if isinstance(exc, httpx.TimeoutException):
            return APIConnectionError(
                f"Request timed out after {self.timeout}s: {method} {path}", code="timeout"
            )
        return APIConnectionError(f"Network error: {exc}", code="connection_error")

    # Overridden by the concrete clients.
    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _post(self, path: str, body: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _get_plain(self, path: str) -> Any:  # pragma: no cover
        raise NotImplementedError

    def websocket_url(self) -> str:
        """The gateway URL including the auth query parameter."""
        from urllib.parse import quote

        return f"{self.ws_url}/?apiKey={quote(self._api_key, safe='')}"


class CabalSpy(_BaseClient):
    """Synchronous client.

        from cabalspy import CabalSpy

        client = CabalSpy()                      # reads CABALSPY_API_KEY
        wallet = client.wallets.lookup("As7H...")
    """

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        http_client = kwargs.pop("http_client", None)
        # A caller-supplied client may be one that pays for 402 responses, which
        # is what makes an API key optional.
        kwargs.setdefault("pays_per_call", http_client is not None)
        super().__init__(api_key, **kwargs)
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._owns_http = http_client is None

    def __enter__(self) -> "CabalSpy":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _send(self, method: str, path: str, params: Any = None, body: Any = None) -> Envelope:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(_backoff(attempt, last))
            try:
                response = self._http.request(
                    method,
                    url,
                    params=_clean_params(params),
                    json=body,
                    headers=self._request_headers(body is not None),
                )
            except httpx.HTTPError as exc:
                last = self._connection_error(exc, method, path)
                continue
            try:
                return self._interpret(response, method, path)
            except CabalSpyError as exc:
                if is_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: {method} {path}")

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._send("GET", path, params=params).data

    def _post(self, path: str, body: Any) -> Any:
        return self._send("POST", path, body=body).data

    def _get_plain(self, path: str) -> Any:
        """For /health and /meta, which answer without the success/data envelope."""
        response = self._http.get(
            f"{self.base_url}{path}", headers=self._request_headers(False)
        )
        if response.status_code >= 400:
            raise error_from_status(
                response.status_code, None, RateLimit(), None,
                f"HTTP {response.status_code} on GET {path}",
            )
        parsed = response.json()
        return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed

    def get_raw(self, path: str, params: Mapping[str, Any] | None = None) -> Envelope:
        """Escape hatch: any GET, returning the full envelope."""
        return self._send("GET", path, params=params)

    def post_raw(self, path: str, body: Any) -> Envelope:
        """Escape hatch: any POST, returning the full envelope."""
        return self._send("POST", path, body=body)

    def pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, max_pages: int = 100
    ) -> Iterator[Envelope]:
        """Walks a cursor paginated route and yields whole pages.

        Pages are yielded rather than individual items because the key holding the
        array differs from endpoint to endpoint. /wallets/history nests its
        pagination inside ``data`` instead of on the envelope; both are handled.
        """
        query = dict(params or {})
        cursor = query.pop("cursor", None)
        for _ in range(max_pages):
            page = self._send("GET", path, params={**query, "cursor": cursor})
            inner = page.data.get("pagination") if isinstance(page.data, dict) else None
            pagination = page.pagination or inner
            page.pagination = pagination
            yield page
            if not pagination or not pagination.get("has_more"):
                return
            cursor = pagination.get("next_cursor")
            if not cursor:
                return

    def realtime(self, **kwargs: Any) -> Any:
        """Opens an async realtime client. The gateway is async only."""
        from ._realtime import CabalSpyRealtime

        return CabalSpyRealtime(self.ws_url, self._api_key, **kwargs)


class AsyncCabalSpy(_BaseClient):
    """Asynchronous client.

        from cabalspy import AsyncCabalSpy

        async with AsyncCabalSpy() as client:
            wallet = await client.wallets.lookup("As7H...")
    """

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        http_client = kwargs.pop("http_client", None)
        # A caller-supplied client may be one that pays for 402 responses, which
        # is what makes an API key optional.
        kwargs.setdefault("pays_per_call", http_client is not None)
        super().__init__(api_key, **kwargs)
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._owns_http = http_client is None

    async def __aenter__(self) -> "AsyncCabalSpy":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _send(self, method: str, path: str, params: Any = None, body: Any = None) -> Envelope:
        import asyncio

        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        last: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(_backoff(attempt, last))
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=_clean_params(params),
                    json=body,
                    headers=self._request_headers(body is not None),
                )
            except httpx.HTTPError as exc:
                last = self._connection_error(exc, method, path)
                continue
            try:
                return self._interpret(response, method, path)
            except CabalSpyError as exc:
                if is_retryable(exc) and attempt < self.max_retries:
                    last = exc
                    continue
                raise
        raise last or APIConnectionError(f"Request failed: {method} {path}")

    async def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return (await self._send("GET", path, params=params)).data

    async def _post(self, path: str, body: Any) -> Any:
        return (await self._send("POST", path, body=body)).data

    async def _get_plain(self, path: str) -> Any:
        response = await self._http.get(
            f"{self.base_url}{path}", headers=self._request_headers(False)
        )
        if response.status_code >= 400:
            raise error_from_status(
                response.status_code, None, RateLimit(), None,
                f"HTTP {response.status_code} on GET {path}",
            )
        parsed = response.json()
        return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed

    async def get_raw(self, path: str, params: Mapping[str, Any] | None = None) -> Envelope:
        return await self._send("GET", path, params=params)

    async def post_raw(self, path: str, body: Any) -> Envelope:
        return await self._send("POST", path, body=body)

    async def pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, max_pages: int = 100
    ) -> AsyncIterator[Envelope]:
        """Async version of :meth:`CabalSpy.pages`."""
        query = dict(params or {})
        cursor = query.pop("cursor", None)
        for _ in range(max_pages):
            page = await self._send("GET", path, params={**query, "cursor": cursor})
            inner = page.data.get("pagination") if isinstance(page.data, dict) else None
            pagination = page.pagination or inner
            page.pagination = pagination
            yield page
            if not pagination or not pagination.get("has_more"):
                return
            cursor = pagination.get("next_cursor")
            if not cursor:
                return

    def realtime(self, **kwargs: Any) -> Any:
        from ._realtime import CabalSpyRealtime

        return CabalSpyRealtime(self.ws_url, self._api_key, **kwargs)
