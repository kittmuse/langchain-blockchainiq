"""Offline tests: 402 parsing, payment signing, and the spend guard.

No network and no real funds: the key below is Hardhat's well-known
public test account #0, used only to check that signatures recover to
the right address.
"""

import base64
import json
import os
import sys

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_blockchainiq.client import (
    BlockchainIQClient,
    SpendLimitExceeded,
)

TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDRESS = Account.from_key(TEST_KEY).address

# The accepts entry of the real HTTP 402 returned by GET /api/x402/v1/brief
# (captured 2026-11-05; prices and addresses are the seller's public terms).
BRIEF_REQUIREMENT = {
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "10000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payTo": "0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e",
    "maxTimeoutSeconds": 300,
    "extra": {"name": "USD Coin", "version": "2"},
}


def test_select_requirement_picks_base_usdc_exact():
    payload = {"x402Version": 2, "accepts": [BRIEF_REQUIREMENT]}
    assert BlockchainIQClient.select_requirement(payload) == BRIEF_REQUIREMENT


def test_payment_header_signs_recoverable_eip3009_authorization():
    client = BlockchainIQClient(private_key=TEST_KEY)
    header = client.build_payment_header(BRIEF_REQUIREMENT)
    payment = json.loads(base64.b64decode(header))
    assert payment["x402Version"] == 2
    # x402 v2: the accepted requirement is echoed back to the server.
    assert payment["accepted"]["scheme"] == "exact"
    assert payment["accepted"]["network"] == "eip155:8453"
    assert payment["accepted"]["amount"] == "10000"
    auth = payment["payload"]["authorization"]
    assert auth["from"] == TEST_ADDRESS
    assert auth["to"] == BRIEF_REQUIREMENT["payTo"]
    assert auth["value"] == "10000"

    signable = encode_typed_data(
        domain_data={
            "name": "USD Coin",
            "version": "2",
            "chainId": 8453,
            "verifyingContract": BRIEF_REQUIREMENT["asset"],
        },
        message_types={
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        },
        message_data={
            "from": auth["from"],
            "to": auth["to"],
            "value": int(auth["value"]),
            "validAfter": int(auth["validAfter"]),
            "validBefore": int(auth["validBefore"]),
            "nonce": bytes.fromhex(auth["nonce"][2:]),
        },
    )
    recovered = Account.recover_message(signable, signature=payment["payload"]["signature"])
    assert recovered == TEST_ADDRESS


def test_spend_guard_refuses_calls_above_the_limit():
    client = BlockchainIQClient(private_key=TEST_KEY, max_amount_usdc="0.005")
    with pytest.raises(SpendLimitExceeded):
        client.build_payment_header(BRIEF_REQUIREMENT)
