# Proof of the live paid call

**Resource:** `GET https://www.blockchainiq.co/api/x402/v1/brief`
**Price:** 0.01 USDC (10,000 base units), x402 v2, scheme `exact`, Base (`eip155:8453`)
**Payer wallet:** `0xB056f91CEde07263D8D5C405fa6EFFA8c89Bcf45`
**Paid to:** `0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e` (from the 402 `PAYMENT-REQUIRED` header)
**Settlement transaction:** `0x1821abf240c4065b411d53d5c66d488ddc0cea8e7ec41fab0e70e1b56304e694`
**Basescan:** https://basescan.org/tx/0x1821abf240c4065b411d53d5c66d488ddc0cea8e7ec41fab0e70e1b56304e694
**When:** 2026-11-05, response `asOf` 2026-11-05T15:30:24.263Z
**Wallet balance:** 0.019 USDC before, 0.009 USDC after (exactly −0.01)

Recorded evidence in this repository:

- `examples/output/brief-response.json` — the full JSON body returned after payment
- `examples/output/brief-settlement.json` — the decoded `PAYMENT-RESPONSE` header:
  `{"success": true, "payer": "0xB056f91CEde07263D8D5C405fa6EFFA8c89Bcf45", "transaction": "0x1821ab…e694", "network": "eip155:8453"}`

## How it was executed

The payment itself was made from the payer wallet above through the x402 v2
`exact` flow described in the README (402 → signed EIP-3009 authorization →
`PAYMENT-SIGNATURE` retry → 200 + settlement header), using Blockchain IQ's
reference `@x402/fetch` client from `blockchainiq.co/agents`. The seller's
settlement is slow (the successful call took ~2 minutes to answer), which is
why this package's client defaults to a 300 s timeout.

This package's own client was verified against the same flow:

- Its payment payload is byte-for-byte the same protocol object (x402 v2,
  `accepted` requirement echoed, EIP-3009 authorization against the USDC
  EIP-712 domain `USD Coin` v2 on chain 8453) — see `tests/test_payment.py`,
  which also recovers the signer address from the produced signature.
- Its free tools (`blockchainiq_catalog`, `blockchainiq_sample`) were run
  live against the API through the LangChain layer.
- A payload missing the v2 `accepted` field was rejected by the server with
  an immediate 402; adding it (as this package now does) let the call
  proceed to settlement.
