# langchain-blockchainiq

LangChain tools for the [Blockchain IQ](https://www.blockchainiq.co/agents)
x402 API: crypto market data that a LangChain agent buys **per call**, paying
in USDC on Base over the open [x402](https://www.x402.org) standard.

There is no Blockchain IQ account and no API key. An unpaid request returns
HTTP 402 with the price; the tool signs a USDC payment (EIP-3009
`transferWithAuthorization`, x402 protocol v2, scheme `exact`) and retries.
Settlement is gasless for the payer — the wallet needs a little USDC on Base
and no ETH.

Built for the [Blockchain IQ x402 build bounty](https://www.blockchainiq.co/blog/x402-build-bounties)
(the LangChain slot).

## Tools

| Tool | Price | What it returns |
| --- | --- | --- |
| `blockchainiq_catalog` | free | Every resource in the API, with prices and response shapes |
| `blockchainiq_sample` | free | Bitcoin network activity sample (test your parsing before paying) |
| `blockchainiq_market_brief` | **$0.01** | BTC, ETH, SOL and XRP prices with 24h/7d/30d moves and rank, scheduled events in the next 48 hours, and short risk flags — the opening call of a trading-agent loop |
| `blockchainiq_event_risk` | $0.05 | Market-moving events for the next 1–90 days (US data releases, FOMC/ECB/BoJ, Treasury auctions, crypto milestones), ranked by importance |

Paid tools return the API's JSON envelope plus a `_payment` field: the
settlement receipt decoded from the `PAYMENT-RESPONSE` header, including the
on-chain transaction hash — so an agent can cite proof that it paid.

## Install

```bash
pip install langchain-blockchainiq   # or from source: pip install .
```

## Quickstart

```python
import os
from langchain_blockchainiq import get_blockchainiq_tools

# A wallet holding a little USDC on Base. Use a dedicated wallet with a
# small balance, never a main wallet.
os.environ["AGENT_PRIVATE_KEY"] = "0x..."

tools = get_blockchainiq_tools()          # key read from the environment
brief = {t.name: t for t in tools}["blockchainiq_market_brief"]
print(brief.invoke({}))
```

Or hand the tools straight to an agent — see
[`examples/agent_with_tools.py`](examples/agent_with_tools.py):

```python
from langchain.agents import create_agent
from langchain_blockchainiq import get_blockchainiq_tools

agent = create_agent(model=..., tools=get_blockchainiq_tools())
```

A per-call spend control guards the wallet: calls priced above
`max_amount_usdc` (default **$0.10**) are refused before anything is signed.

```python
tools = get_blockchainiq_tools(max_amount_usdc="0.05")
```

The lower-level client is available too, for use outside LangChain:

```python
from langchain_blockchainiq import BlockchainIQClient

client = BlockchainIQClient(private_key="0x...", max_amount_usdc="0.10")
result = client.brief()
print(result.data)        # the brief
print(result.settlement)  # {'success': True, 'transaction': '0x…', …}
```

## Verified live paid call

On 2026-11-05 this integration's payment flow bought the brief
(`GET /api/x402/v1/brief`, $0.01) from an agent wallet on Base. The brief
came back with `asOf` 2026-11-05T15:30:24Z: BTC $76,378 (−5.24% 24h),
ETH $2,276.19, SOL $90.51, XRP $1.25, 3 events in the next 48 hours
(including the US jobs report, importance 3) and 2 risk flags.

Settlement receipt (decoded from the `PAYMENT-RESPONSE` header; full copies
in [`examples/output/`](examples/output/)):

```json
{
  "success": true,
  "payer": "0xB056f91CEde07263D8D5C405fa6EFFA8c89Bcf45",
  "transaction": "0x1821abf240c4065b411d53d5c66d488ddc0cea8e7ec41fab0e70e1b56304e694",
  "network": "eip155:8453"
}
```

Verify it on [Basescan](https://basescan.org/tx/0x1821abf240c4065b411d53d5c66d488ddc0cea8e7ec41fab0e70e1b56304e694):
a 0.01 USDC transfer from the payer to the API's payment address. See
[PROOF.md](PROOF.md) for how the call was executed and checked.

One operational note: the seller settles on-chain before answering, so a
paid call can take a couple of minutes to return. This client's default
timeout is 300 s for that reason.

## How the payment works

1. `GET` the resource with no headers → HTTP 402 with a `PAYMENT-REQUIRED`
   header (base64 JSON: price, USDC contract, network `eip155:8453`,
   payment address).
2. The client picks the Base/USDC `exact` option, checks it against the
   spend limit, and signs an EIP-3009 `TransferWithAuthorization` against
   the USDC contract's EIP-712 domain (`USD Coin`, version `2`).
3. It retries with the signed payment in the `PAYMENT-SIGNATURE` header
   (x402 v2 payload, echoing the accepted requirement).
4. HTTP 200 with the JSON data and a `PAYMENT-RESPONSE` header carrying
   the settlement transaction hash. A 404 or an error is never charged.

## Tests

Offline tests cover 402 parsing, EIP-3009 signature recovery and the spend
guard (no network, no funds — a public Hardhat test key is used):

```bash
pip install -e ".[dev]" && pytest
```

## Layout

- `langchain_blockchainiq/client.py` — the x402 v2 client (also usable standalone)
- `langchain_blockchainiq/tools.py` — the LangChain `StructuredTool`s
- `examples/paid_brief_call.py` — one real paid call through the tool
- `examples/agent_with_tools.py` — the tools inside a LangChain agent
- `examples/output/` — the recorded response and settlement of the live call

## License

MIT. Market data is Blockchain IQ's; this package is an independent
integration, not affiliated with or endorsed by Blockchain IQ. Data returned
by the API is market data and analysis, not investment advice.
