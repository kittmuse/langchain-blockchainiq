#!/usr/bin/env python3
"""Make one real paid call through the LangChain tool: the $0.01 brief.

Usage:

    AGENT_PRIVATE_KEY=0x... python examples/paid_brief_call.py

The key belongs to a wallet holding a little USDC on Base. Settlement is
gasless for the payer, so no ETH is needed. The script prints the brief
and the settlement receipt (including the transaction hash) that the
tool decoded from the PAYMENT-RESPONSE header.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_blockchainiq import get_blockchainiq_tools


def main() -> None:
    if not (os.environ.get("AGENT_PRIVATE_KEY") or os.environ.get("BLOCKCHAINIQ_PRIVATE_KEY")):
        sys.exit("Set AGENT_PRIVATE_KEY (or BLOCKCHAINIQ_PRIVATE_KEY) to a Base wallet key holding USDC.")
    tools = {tool.name: tool for tool in get_blockchainiq_tools()}
    result = json.loads(tools["blockchainiq_market_brief"].invoke({}))
    payment = result.pop("_payment", None)
    print(json.dumps(result, indent=2)[:2000])
    print("\n--- settlement proof ---")
    print(json.dumps(payment, indent=2))


if __name__ == "__main__":
    main()
