"""Realtime client for the CabalSpy gateway.

One socket carries every stream. Subscriptions are remembered and re-sent after a
reconnect, so a dropped connection does not silently stop the data flow.

    from cabalspy import AsyncCabalSpy

    async with AsyncCabalSpy() as client:
        rt = client.realtime()

        @rt.on("position_update")
        def _(msg):
            print(msg["data"])

        await rt.connect()
        await rt.subscribe(stream="tx", blockchain="solana", type="kol")
        await rt.run_forever()

Note that ``position_update`` arrives on two different channels with two entirely
different payloads: ``tx.<chain>.<type>`` sends one wallet and one trade, while
``holder.<chain>`` sends every holder of a token. Branch on ``msg["channel"]``, or
use :func:`is_tx_position_update`.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import websockets

from ._constants import CHAINS, WALLET_TYPES_BY_CHAIN, wallet_type_is_valid
from ._errors import APIConnectionError, BadRequestError, CabalSpyError

Handler = Callable[[dict[str, Any]], Any]

GATEWAY_EVENTS = (
    "position_update",
    "wallet_count",
    "signal",
    "kol_bundle",
    "holder_update",
    "balance_update",
    "init",
)


def is_tx_position_update(message: dict[str, Any]) -> bool:
    """True for the per-trade variant that arrives on the tx channel."""
    data = message.get("data") or {}
    return "wallet" in data and "transaction" in data


def is_holder_position_update(message: dict[str, Any]) -> bool:
    """True for the token-wide variant that arrives on the holder channel."""
    return "holders" in (message.get("data") or {})


def _validate_subscription(sub: dict[str, Any]) -> None:
    stream = sub.get("stream")

    if stream == "bundle":
        chain = sub.get("blockchain", "solana")
        if chain != "solana":
            raise BadRequestError(
                "The bundle stream is currently available for solana only",
                code="invalid_parameter",
                parameter="blockchain",
                allowed=["solana"],
            )
        interval = sub.get("mc_interval")
        if interval is not None and not 1 <= interval <= 30:
            raise BadRequestError(
                "mc_interval must be between 1 and 30",
                code="invalid_parameter",
                parameter="mc_interval",
            )
        return

    chain = sub.get("blockchain")
    if not chain:
        raise BadRequestError(
            f"Stream {stream!r} requires blockchain",
            code="missing_parameter",
            parameter="blockchain",
            allowed=list(CHAINS),
        )
    if chain not in CHAINS:
        raise BadRequestError(
            f"Unknown blockchain {chain!r}",
            code="invalid_parameter",
            parameter="blockchain",
            allowed=list(CHAINS),
        )

    if stream == "tx":
        wtype = sub.get("type")
        if not wallet_type_is_valid(chain, str(wtype)):
            allowed = list(WALLET_TYPES_BY_CHAIN[chain])
            raise BadRequestError(
                f"{chain} supports only: {', '.join(allowed)}",
                code="invalid_parameter",
                parameter="type",
                allowed=allowed,
            )

    if stream == "signal" and sub.get("smart") and chain == "eth":
        raise BadRequestError(
            "Smart money signals are not available on eth, kol only",
            code="invalid_parameter",
            parameter="smart",
        )

    if stream == "balance" and not sub.get("wallet"):
        raise BadRequestError(
            "Stream 'balance' requires wallet", code="missing_parameter", parameter="wallet"
        )


class CabalSpyRealtime:
    """Async websocket client. Obtain one via ``client.realtime()``."""

    def __init__(
        self,
        ws_url: str,
        api_key: str,
        *,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        ping_interval: float = 25.0,
    ) -> None:
        self._url = f"{ws_url.rstrip('/')}/?apiKey={quote(api_key, safe='')}"
        self._safe_url = f"{ws_url.rstrip('/')}/?apiKey=***"
        self.reconnect = reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval

        self._ws: Any = None
        self._subs: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, list[Handler]] = {}
        self._attempt = 0
        self._closed = False
        self._reader: asyncio.Task[None] | None = None
        self._pinger: asyncio.Task[None] | None = None

    # ── handlers ─────────────────────────────────────────────────────────

    def on(self, event: str, handler: Handler | None = None) -> Any:
        """Registers a handler. Usable directly or as a decorator.

        Gateway events: position_update, wallet_count, signal, kol_bundle,
        holder_update, balance_update, init.
        SDK events: open, close, error, ack, message.
        """
        def register(fn: Handler) -> Handler:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return register if handler is None else register(handler)

    def off(self, event: str, handler: Handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    async def _emit(self, event: str, payload: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(payload)
                if isinstance(result, Awaitable):
                    await result
            except Exception as exc:  # a throwing handler must not kill the socket
                if event != "error":
                    await self._emit("error", exc)

    # ── connection ───────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connects and returns once the gateway has accepted the socket."""
        self._closed = False
        try:
            self._ws = await websockets.connect(self._url, open_timeout=20)
        except Exception as exc:
            raise APIConnectionError(
                f"Could not connect to {self._safe_url}: {exc}", code="ws_error"
            ) from exc

        self._attempt = 0
        self._reader = asyncio.create_task(self._read_loop())
        if self.ping_interval:
            self._pinger = asyncio.create_task(self._ping_loop())
        await self._emit("open", None)
        for sub in list(self._subs.values()):
            await self._send({"op": "subscribe", **sub})

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                await self._dispatch(message)
        except websockets.ConnectionClosed as exc:
            await self._emit("close", exc)
            if not self._closed and self.reconnect:
                await self._schedule_reconnect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._emit("error", exc)

    async def _dispatch(self, message: dict[str, Any]) -> None:
        await self._emit("message", message)
        event = message.get("event")
        if isinstance(event, str):
            await self._emit(event, message)
            return
        kind = message.get("type")
        if kind in ("subscribed", "unsubscribed", "connected"):
            await self._emit("ack", message)
            return
        if kind == "error" or message.get("success") is False:
            await self._emit(
                "error",
                CabalSpyError(str(message.get("message") or "Gateway error"), code="gateway_error"),
            )

    async def _schedule_reconnect(self) -> None:
        delay = min(self.reconnect_delay * (2 ** self._attempt), self.max_reconnect_delay)
        self._attempt += 1
        await asyncio.sleep(delay + random.random() * 0.25)
        if self._closed:
            return
        try:
            await self.connect()
        except Exception as exc:
            await self._emit("error", exc)
            if not self._closed and self.reconnect:
                await self._schedule_reconnect()

    async def _ping_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self.ping_interval)
                await self._send({"op": "ping"})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            pass

    # ── subscriptions ────────────────────────────────────────────────────

    @staticmethod
    def _key(sub: dict[str, Any]) -> str:
        target = sub.get("token") or sub.get("wallet") or "*"
        wtype = sub.get("type") or "+".join(sub.get("wallet_types") or [])
        return f"{sub.get('stream')}:{sub.get('blockchain', 'solana')}:{wtype}:{target}"

    async def subscribe(self, **sub: Any) -> None:
        """Subscribes to a stream. Re-sent automatically after a reconnect.

        Streams and their fields:
          tx       blockchain, type, token
          count    blockchain, token
          signal   blockchain, token, kol={...}, smart={...},
                   include_wallets, exclude_wallets, min_win_rate
          bundle   token, mode="events"|"full", mc_interval=1..30   (solana only)
          holder   blockchain, token, wallet_types=[...]
          balance  blockchain, wallet, wallet_types=[...]
        """
        _validate_subscription(sub)
        if sub.get("stream") == "bundle":
            sub = {**sub, "blockchain": "solana"}
        self._subs[self._key(sub)] = sub
        await self._send({"op": "subscribe", **sub})

    async def subscribe_channel(self, channel: str) -> None:
        """Channel shorthand, for example "tx.solana.kol.*" or "bundle.solana.<MINT>"."""
        await self._send({"op": "subscribe", "channel": channel})

    async def unsubscribe(self, **sub: Any) -> None:
        self._subs.pop(self._key(sub), None)
        await self._send({"op": "unsubscribe", **sub})

    async def list_subscriptions(self) -> None:
        """Asks the server for its subscription list. The reply arrives as "ack"."""
        await self._send({"op": "subscriptions"})

    # ── lifecycle ────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Blocks until the connection is closed with :meth:`close`."""
        while not self._closed:
            await asyncio.sleep(0.25)

    async def close(self) -> None:
        """Closes the socket and disables reconnecting."""
        self._closed = True
        for task in (self._pinger, self._reader):
            if task and not task.done():
                task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def __aenter__(self) -> "CabalSpyRealtime":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
