"""A small x402 v2 client for the Blockchain IQ API (USDC on Base).

The Blockchain IQ API sells crypto market data per call over the open
x402 standard: no account, no API key. An unpaid request returns HTTP 402
with a ``PAYMENT-REQUIRED`` header naming the price; the client signs a
USDC payment (EIP-3009 ``transferWithAuthorization``, scheme ``exact``)
and retries. Settlement is gasless for the payer: the signed authorization
is relayed by the seller's facilitator, so the wallet needs USDC only,
never ETH for gas.

Reference: https://www.blockchainiq.co/agents and the free catalogue at
https://www.blockchainiq.co/api/x402/v1
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import requests
from eth_account import Account

BASE_URL = "https://www.blockchainiq.co/api/x402/v1"
NETWORK = "eip155:8453"  # Base mainnet
CHAIN_ID = 8453
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DECIMALS = 6


class BlockchainIQError(Exception):
    """Base error for this client."""


class PaymentRequired(BlockchainIQError):
    """The resource is paid and no usable wallet/payment is available."""


class SpendLimitExceeded(BlockchainIQError):
    """The price of a call exceeds the configured per-call spend limit."""


def _b64decode_json(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _b64encode_json(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decode_payment_response(header_value: str) -> dict:
    """Decode a ``PAYMENT-RESPONSE`` header into the settlement receipt.

    The receipt carries ``success``, ``transaction`` (the on-chain
    settlement hash), ``network`` and ``payer``.
    """
    return _b64decode_json(header_value)


@dataclass
class CallResult:
    """One API call: the JSON envelope plus the settlement, if paid."""

    data: dict
    settlement: Optional[dict] = None
    status_code: int = 200

    def as_dict(self) -> dict:
        out = dict(self.data)
        if self.settlement is not None:
            out["_payment"] = self.settlement
        return out


class BlockchainIQClient:
    """Client for the Blockchain IQ x402 API.

    ``private_key`` is the payer wallet's key (an account holding a little
    USDC on Base). ``max_amount_usdc`` is a spend control: any single call
    priced above it is refused before signing, mirroring the spend control
    in Blockchain IQ's own Node example.
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        *,
        max_amount_usdc: Decimal | str | float = "0.10",
        base_url: str = BASE_URL,
        timeout: float = 300.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._account = Account.from_key(private_key) if private_key else None
        self.max_amount_units = int(Decimal(str(max_amount_usdc)) * 10**USDC_DECIMALS)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def payer_address(self) -> Optional[str]:
        return self._account.address if self._account else None

    # -- payment construction -------------------------------------------------

    @staticmethod
    def select_requirement(payment_required: dict) -> dict:
        """Pick the Base/USDC ``exact`` option from a 402 payload."""
        for option in payment_required.get("accepts", []):
            if (
                option.get("scheme") == "exact"
                and option.get("network") == NETWORK
                and option.get("asset", "").lower() == USDC_BASE.lower()
            ):
                return option
        raise PaymentRequired(
            "No supported payment option (exact / Base / USDC) in the 402 response."
        )

    def build_payment_header(self, requirement: dict) -> str:
        """Sign an EIP-3009 authorization and return the header value.

        The returned string goes in the ``PAYMENT-SIGNATURE`` header of the
        retried request (x402 protocol version 2).
        """
        if self._account is None:
            raise PaymentRequired(
                "This resource is paid, but the client has no wallet. "
                "Pass private_key=... (a wallet holding USDC on Base)."
            )
        amount = int(requirement["amount"])
        if amount > self.max_amount_units:
            raise SpendLimitExceeded(
                f"Call costs {amount / 10**USDC_DECIMALS:.2f} USDC, above the "
                f"per-call limit of {self.max_amount_units / 10**USDC_DECIMALS:.2f} USDC."
            )
        extra = requirement.get("extra") or {}
        now = int(time.time())
        authorization = {
            "from": self._account.address,
            "to": requirement["payTo"],
            "value": str(amount),
            "validAfter": str(now - 60),
            "validBefore": str(now + int(requirement.get("maxTimeoutSeconds", 300))),
            "nonce": "0x" + secrets.token_hex(32),
        }
        domain = {
            "name": extra.get("name", "USD Coin"),
            "version": extra.get("version", "2"),
            "chainId": CHAIN_ID,
            "verifyingContract": requirement["asset"],
        }
        types = {
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        }
        message = {
            "from": authorization["from"],
            "to": authorization["to"],
            "value": amount,
            "validAfter": int(authorization["validAfter"]),
            "validBefore": int(authorization["validBefore"]),
            "nonce": bytes.fromhex(authorization["nonce"][2:]),
        }
        signed = self._account.sign_typed_data(
            domain_data=domain, message_types=types, message_data=message
        )
        payload = {
            "x402Version": 2,
            # x402 v2: the client echoes back the payment requirement it
            # accepted; servers reject payloads without it.
            "accepted": requirement,
            "payload": {
                "signature": signed.signature.hex()
                if signed.signature.hex().startswith("0x")
                else "0x" + signed.signature.hex(),
                "authorization": authorization,
            },
        }
        return _b64encode_json(payload)

    # -- HTTP -----------------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None) -> CallResult:
        """GET a resource, paying through x402 when the resource is priced.

        Note: a paid call can take a while to answer — the seller settles
        the payment on-chain before responding (observed at ~2 minutes),
        hence the generous default timeout.
        """
        if path.startswith("http"):
            url = path
        elif path:
            url = f"{self.base_url}/{path.lstrip('/')}"
        else:
            url = self.base_url
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code == 402:
            header = response.headers.get("payment-required")
            if not header:
                raise PaymentRequired("HTTP 402 without a PAYMENT-REQUIRED header.")
            requirement = self.select_requirement(_b64decode_json(header))
            payment_header = self.build_payment_header(requirement)
            response = self.session.get(
                url,
                params=params,
                headers={"PAYMENT-SIGNATURE": payment_header},
                timeout=self.timeout,
            )
        if response.status_code != 200:
            raise BlockchainIQError(
                f"GET {url} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        settlement = None
        payment_response = response.headers.get("payment-response")
        if payment_response:
            settlement = decode_payment_response(payment_response)
        return CallResult(
            data=response.json(), settlement=settlement, status_code=response.status_code
        )

    # -- Resources ------------------------------------------------------------

    def catalog(self) -> CallResult:
        """Free: every resource, price and response shape."""
        return self.get("")

    def sample(self) -> CallResult:
        """Free: Bitcoin network activity sample, to test parsing unpaid."""
        return self.get("sample")

    def brief(self) -> CallResult:
        """Paid, $0.01: BTC/ETH/SOL/XRP brief, next-48h events, risk flags."""
        return self.get("brief")

    def event_risk(self, days: int = 7, min_importance: int = 1) -> CallResult:
        """Paid, $0.05: scheduled market-moving events for the next N days."""
        return self.get(
            "event-risk", params={"days": days, "minImportance": min_importance}
        )

    def macro(self) -> CallResult:
        """Paid, $0.05: US macro indicators from official sources."""
        return self.get("macro")

    def calendar(self) -> CallResult:
        """Paid, $0.03: 90 days of economic and crypto events."""
        return self.get("calendar")
