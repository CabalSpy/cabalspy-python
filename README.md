# CabalSpy Python SDK — KOL and smart money wallet tracking API

Official Python client for the **CabalSpy API**: a realtime multichain data layer for labeled wallets, covering **Solana, Base, BNB Chain, Ethereum and Robinhood Chain**.

Track what Key Opinion Leaders, smart money wallets and whales are actually buying — with PnL, holder data, cluster signals and bundle detection. Full REST coverage, six WebSocket streams, sync and async.

```bash
pip install cabalspy
```

Realtime needs one extra dependency:

```bash
pip install "cabalspy[realtime]"
```

**What you can build with it:** copy-trading bots, KOL leaderboards, memecoin alert systems, wallet analytics dashboards, bundle and sniper detection, portfolio and PnL trackers.

## Quick start

```python
from cabalspy import CabalSpy

client = CabalSpy()  # reads CABALSPY_API_KEY

# Who is this wallet? Searches every chain and wallet type.
wallet = client.wallets.lookup("As7HjL7dzzvbRbaD3WCun47robib2kmAKRXMvjHkSMB5")
print(wallet["name"], wallet["type"])

# Best KOL wallets on Solana over 7 days
board = client.wallets.leaderboard(blockchain="solana", type="kol", period="7d", limit=25)

# Live cluster signals: 5+ KOLs buying the same token within an hour
signals = client.signals.list(
    blockchain="solana", type="kol", mode="cluster", min_wallets=5, hours=1
)
for signal in signals["signals"]:
    print(signal["token"]["token_name"], signal["window"]["wallet_count"])
```

## Async

Every method exists on `AsyncCabalSpy` with the same signature.

```python
import asyncio
from cabalspy import AsyncCabalSpy

async def main():
    async with AsyncCabalSpy() as client:
        stats = await client.tokens.stats(blockchain="solana", mint="5ti9ASui...")
        print(stats["total_holders"])

asyncio.run(main())
```

## Realtime

One socket carries every stream. Subscriptions are remembered and re-sent after a reconnect.

```python
import asyncio
from cabalspy import AsyncCabalSpy, is_tx_position_update

async def main():
    async with AsyncCabalSpy() as client:
        rt = client.realtime()

        @rt.on("position_update")
        def on_trade(msg):
            if is_tx_position_update(msg):
                data = msg["data"]
                print(data["profile"]["name"], data["transaction"]["action"], data["token"]["mint"])

        @rt.on("kol_bundle")
        def on_bundle(msg):
            print("bundle", msg["data"]["bundle_id"])

        await rt.connect()
        await rt.subscribe(stream="tx", blockchain="solana", type="kol", token="*")
        await rt.subscribe(stream="bundle", token="MINT_ADDRESS", mode="full", mc_interval=5)
        await rt.subscribe(
            stream="signal",
            blockchain="solana",
            kol={"min_buy": 2, "entry_at": [3, 5, 10], "exit_at": [2, 0]},
        )
        await rt.run_forever()

asyncio.run(main())
```

> **`position_update` arrives on two channels with two different payloads.**
> `tx.<chain>.<type>` sends one wallet and one trade. `holder.<chain>` sends every holder of a
> token. Use `is_tx_position_update()` and `is_holder_position_update()` to tell them apart.

## Chain coverage

| Chain | Identifier | Currency | Wallet types |
|---|---|---|---|
| Solana | `solana` | SOL | `kol`, `smart`, `whale` |
| BNB Chain | `bnb` | BNB | `kol`, `smart` |
| Base | `base` | ETH | `kol`, `smart` |
| Ethereum | `eth` | ETH | `kol` |
| Robinhood Chain | `rh` | ETH | `kol`, `smart` |

Impossible combinations are rejected before a request goes out, so a typo costs no credits:

```python
client.wallets.list(blockchain="eth", type="whale")
# BadRequestError: eth supports only: kol (code=invalid_parameter, parameter=type)
```

> **Market cap availability differs between REST and websocket.**
>
> On **REST**, `market_cap*`, `price*`, `unrealized_pnl_*` and `remaining_*` are populated for
> Solana only; on the other chains they come back `None`. Realized PnL, invested amounts, holdings
> and counters work everywhere.
>
> On the **websocket gateway** the same fields are populated on every chain, because the gateway
> runs its own multichain price service. REST also zeroes `unrealized_pnl_*` once a position is
> fully sold; the gateway does not.

### KOL tracking API for Solana

The deepest coverage of the five. Solana is the only chain with `whale` wallets, live market cap, pump.fun bonding curve progress, and the `bundle` endpoint that detects KOL wallets buying through Jito bundles alongside side wallets.

```python
client.bundle.get(mint="MINT_ADDRESS")
```

### KOL tracking API for Base, BNB Chain and Robinhood Chain

All three carry `kol` and `smart` wallets. Robinhood Chain is Robinhood's Ethereum L2 on the Arbitrum Orbit stack, with ETH as the gas token.

```python
client.transactions.volume(blockchain="rh", type="kol", hours=24)
client.wallets.leaderboard(blockchain="bnb", type="kol", period="7d")
```

### KOL tracking API for Ethereum

Ethereum mainnet carries `kol` wallets only; smart money signals are unavailable there.

## Endpoints

**Wallets** — `list`, `history`, `lookup`, `leaderboard`, `tracker`, `holdings`, `pnl_calendar`, `connections`, `batch`

**Tokens** — `transactions`, `stats`, `holders`, `batch`

**Transactions** — `latest`, `timerange` (max 60 min), `count`, `volume` (max 24 h)

**Signals** — `list` (modes `cluster`, `entry`, `exit`), `history` (7, 30, 90 days or `"all"`)

**Analytics** — `get` (modes `volume_trend`, `most_traded`, `win_rate`, `top_performers`)

**Bundles** — `get` (Solana only)

**System** — `health`, `meta`

Batch endpoints take at most 100 addresses or mints. `wallets.list` and `wallets.leaderboard` return everything when `limit` is omitted.

Setting any gated filter on `signals.list` (`kol`, `smart`, `kol_min_buy`, `kol_exit`, `include_wallets`, `min_win_rate`, `min_token_age`, …) switches the server into gated mode, which applies an AND gate across wallet types.

## Errors

```python
from cabalspy import NotFoundError, RateLimitError, InsufficientCreditsError

try:
    client.wallets.tracker(blockchain="solana", address=addr)
except NotFoundError:
    ...                                  # wallet is not tracked
except InsufficientCreditsError:
    ...                                  # billing
except RateLimitError as exc:
    print(exc.retry_after)
```

| Class | Status | Codes |
|---|---|---|
| `BadRequestError` | 400 | `missing_parameter`, `invalid_parameter`, `invalid_body` |
| `AuthenticationError` | 401 | `missing_api_key` |
| `PermissionError` | 403 | `invalid_api_key` |
| `InsufficientCreditsError` | 403 | `insufficient_credits` |
| `NotFoundError` | 404 | `wallet_not_found`, `token_not_found` |
| `RateLimitError` | 429 | `rate_limit_exceeded` |
| `ServerError` | 5xx | `internal_error`, `service_unavailable` |
| `APIConnectionError` | – | network failure, timeout |

Every error carries `.code`, `.request_id` and `.docs`; `BadRequestError` also carries `.parameter` and `.allowed`.

`429`, `5xx` and network errors are retried automatically with exponential backoff and jitter. A server-sent `Retry-After` wins over the SDK's own backoff.

```python
client = CabalSpy(max_retries=3, timeout=15.0)
client.wallets.lookup(addr)
print(client.last_rate_limit)   # RateLimit(limit=..., remaining=..., reset=...)
```

## Timestamps

Timestamps inside `data` come back as `"YYYY-MM-DD HH:MM:SS"` with no timezone. `datetime.fromisoformat` and friends read those as **local time**, which silently shifts every value. Use the helper:

```python
from cabalspy import parse_api_date

parse_api_date("2026-07-25 21:33:14")   # 2026-07-25 21:33:14+00:00, always UTC
parse_api_date("2026-07-25T21:33:14Z")  # ISO works too
```

Only `meta.timestamp` is proper ISO 8601.

## A note on `realized_pnl`

It is computed as `total_sell - total_buy`. A wallet that has bought and not yet sold therefore reports its whole investment as a loss, with `realized_pnl_percentage: -100`. Check `still_holding` before showing that number to a user.

## Pagination

`pages()` yields whole envelopes, since the key holding the array differs per endpoint.

```python
for page in client.pages("/wallets/history", {"blockchain": "solana", "address": addr, "limit": 20}):
    print(page.pagination["total"], len(page.data["token_overview"]))
```

`/wallets/history` nests its pagination inside `data` rather than on the envelope; `pages()` handles both, so callers do not have to care.

## Configuration

```python
CabalSpy(
    api_key=None,                          # falls back to CABALSPY_API_KEY
    base_url="https://api.cabalspy.xyz/v1",
    ws_url="wss://stream.cabalspy.xyz",
    timeout=30.0,
    max_retries=2,
    headers={},
    http_client=None,                      # bring your own httpx.Client
)
```

Read the key from the environment or a secret manager, never from source. Use the SDK server side: in a client-side application the key would be readable by anyone.

## Raw access

For endpoints not yet wrapped, or when you want the full envelope:

```python
env = client.get_raw("/wallets/leaderboard", {"blockchain": "bnb", "period": "30d"})
print(env.status, env.meta["cached"], env.rate_limit.remaining, env.pagination)

data = client.post_raw("/some/new/endpoint", {"foo": "bar"}).data
```

## Docs and support

Full API reference: [docs.cabalspy.xyz](https://docs.cabalspy.xyz) · free API key: [apidashboard.cabalspy.xyz](https://apidashboard.cabalspy.xyz/)

## License

MIT
