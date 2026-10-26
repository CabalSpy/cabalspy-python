"""Calls: /v1/calls, /v1/calls/stats and the call stream. Offline, httpx is mocked."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from cabalspy import BadRequestError, CabalSpy, CabalSpyRealtime

CALLS_OK = {
    "success": True,
    "data": [{"call_id": "c_1", "blockchain": "solana", "tier": "good", "tier_label": "Good Token"}],
    "pagination": {"limit": 1, "total": 1, "has_more": False, "next_cursor": None},
    "meta": {"request_id": "r1"},
}


def _client(body: dict[str, Any], seen: list[httpx.Request]) -> CabalSpy:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(body).encode())

    return CabalSpy("k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CABALSPY_API_KEY", raising=False)
    monkeypatch.delenv("CABALSPY_BASE_URL", raising=False)


def test_calls_list_joins_chains_and_tiers() -> None:
    seen: list[httpx.Request] = []
    calls = _client(CALLS_OK, seen).calls.list(blockchain=["solana", "bnb"], tier="good", limit=1)
    assert calls[0]["call_id"] == "c_1"
    assert seen[0].url.path == "/v1/calls"
    assert seen[0].url.params["blockchain"] == "solana,bnb"
    assert seen[0].url.params["tier"] == "good"
    assert "since" not in seen[0].url.params


def test_calls_list_rejects_unknown_tier_before_request() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(BadRequestError) as err:
        _client(CALLS_OK, seen).calls.list(tier=["good", "nope"])
    assert err.value.parameter == "tier"
    assert seen == []


def test_calls_stats() -> None:
    seen: list[httpx.Request] = []
    body = {**CALLS_OK, "data": {"period": "30d"}}
    stats = _client(body, seen).calls.stats(period="30d", blockchain="eth")
    assert stats["period"] == "30d"
    assert seen[0].url.path == "/v1/calls/stats"
    assert seen[0].url.params["period"] == "30d"
    with pytest.raises(BadRequestError):
        _client(body, []).calls.stats(period="2y")  # type: ignore[arg-type]


def test_call_stream_defaults_to_every_chain_and_validates() -> None:
    rt = CabalSpyRealtime("wss://x", "k")
    sent: list[dict[str, Any]] = []

    async def capture(payload: dict[str, Any]) -> None:
        sent.append(payload)

    rt._send = capture  # type: ignore[method-assign]
    asyncio.run(rt.subscribe(stream="call", tiers=["good"]))
    assert sent[-1] == {"op": "subscribe", "stream": "call", "tiers": ["good"], "blockchain": "*"}
    with pytest.raises(BadRequestError):
        asyncio.run(rt.subscribe(stream="call", blockchain="base"))
    with pytest.raises(BadRequestError):
        asyncio.run(rt.subscribe(stream="call", tiers=["nope"]))
