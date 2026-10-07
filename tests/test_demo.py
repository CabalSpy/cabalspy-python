"""Demo key support: classmethods, the demo object and DemoLimitError. No network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from cabalspy import (
    DEMO_API_KEY,
    AsyncCabalSpy,
    CabalSpy,
    CabalSpyError,
    DemoLimitError,
    RateLimitError,
)

UPGRADE = {
    "test_key": "https://apidashboard.cabalspy.xyz/",
    "pay_per_call": "https://www.cabalspy.xyz/x402/",
    "docs": "https://docs.cabalspy.xyz",
}

DEMO_OK = {
    "success": True,
    "data": {"wallets": [{"wallet_address": "abc"}]},
    "pagination": {"limit": 5, "has_more": False, "next_cursor": None},
    "meta": {"request_id": "r1"},
    "demo": {"notice": "Demo data, 15 minutes delayed", "remaining_today": 19, "upgrade": UPGRADE},
}

DEMO_SPENT = {
    "success": False,
    "error": {
        "code": "demo_limit_reached",
        "message": "Demo limit reached",
        "resets_in_seconds": 3600,
    },
    "demo": True,
    "upgrade": UPGRADE,
}


def _transport(status: int, body: dict[str, Any], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=json.dumps(body).encode(), headers={"X-CabalSpy-Demo": "true"})

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CABALSPY_API_KEY", raising=False)
    monkeypatch.delenv("CABALSPY_BASE_URL", raising=False)


def test_demo_constant() -> None:
    assert DEMO_API_KEY == "demo"


def test_sync_demo_uses_demo_key_and_default_base_url() -> None:
    seen: list[httpx.Request] = []
    http = httpx.Client(transport=_transport(200, DEMO_OK, seen))
    client = CabalSpy.demo(http_client=http)

    assert client.is_demo
    assert client.base_url == "https://api.cabalspy.xyz/v1"
    data = client.wallets.list(blockchain="solana", type="kol")

    assert data == DEMO_OK["data"]
    assert seen[0].headers["Authorization"] == "Bearer demo"
    assert str(seen[0].url).startswith("https://api.cabalspy.xyz/v1/wallets")
    assert client.last_demo is not None and client.last_demo["remaining_today"] == 19


def test_demo_object_on_envelope() -> None:
    seen: list[httpx.Request] = []
    client = CabalSpy.demo(http_client=httpx.Client(transport=_transport(200, DEMO_OK, seen)))
    env = client.get_raw("/wallets", {"blockchain": "solana", "type": "kol"})
    assert env.demo == DEMO_OK["demo"]
    assert env.pagination == DEMO_OK["pagination"]


def test_non_demo_response_has_no_demo_object() -> None:
    body = {k: v for k, v in DEMO_OK.items() if k != "demo"}
    client = CabalSpy("real-key", http_client=httpx.Client(transport=_transport(200, body, [])))
    env = client.get_raw("/wallets")
    assert env.demo is None and client.last_demo is None and not client.is_demo


def test_demo_accepts_constructor_options() -> None:
    client = CabalSpy.demo(timeout=5.0, max_retries=0, base_url="https://example.test/v1/")
    assert client.timeout == 5.0 and client.max_retries == 0
    assert client.base_url == "https://example.test/v1"
    assert client.websocket_url() == "wss://stream.cabalspy.xyz/?apiKey=demo"
    client.close()


def test_demo_limit_error_is_mapped_and_not_retried() -> None:
    seen: list[httpx.Request] = []
    client = CabalSpy.demo(http_client=httpx.Client(transport=_transport(429, DEMO_SPENT, seen)))

    with pytest.raises(DemoLimitError) as info:
        client.wallets.list(blockchain="solana", type="kol")

    exc = info.value
    assert isinstance(exc, RateLimitError)
    assert exc.status == 429 and exc.code == "demo_limit_reached"
    assert exc.resets_in_seconds == 3600
    assert exc.upgrade == UPGRADE
    assert len(seen) == 1  # a spent daily budget is not retried


def test_plain_rate_limit_still_raises_rate_limit_error() -> None:
    body = {"success": False, "error": {"code": "rate_limit_exceeded", "message": "slow down"}}
    seen: list[httpx.Request] = []
    client = CabalSpy("k", max_retries=0, http_client=httpx.Client(transport=_transport(429, body, seen)))
    with pytest.raises(RateLimitError) as info:
        client.wallets.lookup("abc")
    assert not isinstance(info.value, DemoLimitError)


def test_async_demo() -> None:
    async def run() -> None:
        seen: list[httpx.Request] = []
        http = httpx.AsyncClient(transport=_transport(200, DEMO_OK, seen))
        async with AsyncCabalSpy.demo(http_client=http) as client:
            assert client.is_demo
            data = await client.wallets.list(blockchain="solana", type="kol")
            assert data == DEMO_OK["data"]
            assert client.last_demo["remaining_today"] == 19  # type: ignore[index]
        assert seen[0].headers["Authorization"] == "Bearer demo"
        await http.aclose()

    asyncio.run(run())


def test_async_demo_limit_error() -> None:
    async def run() -> None:
        http = httpx.AsyncClient(transport=_transport(429, DEMO_SPENT, []))
        client = AsyncCabalSpy.demo(http_client=http)
        with pytest.raises(DemoLimitError) as info:
            await client.wallets.list(blockchain="solana", type="kol")
        assert info.value.resets_in_seconds == 3600
        await http.aclose()

    asyncio.run(run())


def test_no_key_does_not_fall_back_to_demo() -> None:
    with pytest.raises(CabalSpyError) as info:
        CabalSpy()
    assert info.value.code == "missing_api_key"
    assert "CabalSpy.demo()" in str(info.value)
    assert "apidashboard.cabalspy.xyz" in str(info.value)


def test_http_client_without_key_still_pays_per_call() -> None:
    # cabalspy-x402 relies on CabalSpy(http_client=...) working without a key.
    sync = CabalSpy(http_client=httpx.Client())
    asyn = AsyncCabalSpy(http_client=httpx.AsyncClient())
    assert sync.pays_per_call and asyn.pays_per_call
    assert "Authorization" not in sync._request_headers(False)
    assert not sync.is_demo
