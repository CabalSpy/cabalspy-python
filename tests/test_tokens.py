"""Token routes: since and cursor on transactions and holders. Offline, httpx is mocked."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from cabalspy import CabalSpy

OK = {
    "success": True,
    "data": {"token": {"mint": "m"}, "transactions": []},
    "pagination": {"limit": 50, "has_more": False, "next_cursor": None},
    "meta": {"request_id": "r1"},
}


def _client(seen: list[httpx.Request]) -> CabalSpy:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=json.dumps(OK).encode())

    return CabalSpy("k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CABALSPY_API_KEY", raising=False)
    monkeypatch.delenv("CABALSPY_BASE_URL", raising=False)


def test_transactions_passes_since_and_cursor() -> None:
    seen: list[httpx.Request] = []
    _client(seen).tokens.transactions(
        blockchain="solana", mint="m", since="2026-11-04T00:00:00Z", limit=50, cursor="c1"
    )
    q: Any = seen[0].url.params
    assert seen[0].url.path == "/v1/tokens/transactions"
    assert q["since"] == "2026-11-04T00:00:00Z"
    assert q["cursor"] == "c1"
    assert q["limit"] == "50"


def test_transactions_omits_unset_since() -> None:
    seen: list[httpx.Request] = []
    _client(seen).tokens.transactions(blockchain="solana", mint="m")
    assert "since" not in seen[0].url.params
    assert "cursor" not in seen[0].url.params


def test_holders_passes_cursor() -> None:
    seen: list[httpx.Request] = []
    _client(seen).tokens.holders(blockchain="bnb", mint="m", limit=10, cursor="h1")
    assert seen[0].url.path == "/v1/tokens/holders"
    assert seen[0].url.params["cursor"] == "h1"
