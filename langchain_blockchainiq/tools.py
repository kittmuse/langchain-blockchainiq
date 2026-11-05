"""LangChain tools for the Blockchain IQ x402 API.

Each tool is a standard LangChain ``StructuredTool``: drop them into any
LangChain agent (``create_agent``, AgentExecutor, LangGraph tool nodes)
and the agent can buy Blockchain IQ market data per call, paying in USDC
on Base through x402. No Blockchain IQ account or API key exists; the
wallet is the only credential.

Tools and prices (USDC, paid only when the call succeeds):

- ``blockchainiq_catalog``    — free, lists every resource and price
- ``blockchainiq_sample``     — free Bitcoin network-activity sample
- ``blockchainiq_market_brief`` — $0.01, BTC/ETH/SOL/XRP brief + 48h events
- ``blockchainiq_event_risk`` — $0.05, market-moving events, next N days

Paid tools return the API's JSON envelope plus a ``_payment`` field with
the settlement receipt (transaction hash, payer, network) decoded from
the response's ``PAYMENT-RESPONSE`` header, so the agent can cite proof
of payment.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from .client import BlockchainIQClient

__all__ = ["get_blockchainiq_tools", "BlockchainIQClient"]


def _client_from_env(
    private_key: Optional[str], max_amount_usdc: Decimal | str | float
) -> BlockchainIQClient:
    key = (
        private_key
        or os.environ.get("BLOCKCHAINIQ_PRIVATE_KEY")
        or os.environ.get("AGENT_PRIVATE_KEY")
    )
    return BlockchainIQClient(private_key=key, max_amount_usdc=max_amount_usdc)


class _NoArgs(BaseModel):
    pass


class EventRiskArgs(BaseModel):
    days: int = Field(
        default=7, ge=1, le=90, description="Look-ahead window in days (1-90)."
    )
    min_importance: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Minimum event importance: 1 = everything, 3 = only major events.",
    )


def get_blockchainiq_tools(
    private_key: Optional[str] = None,
    *,
    max_amount_usdc: Decimal | str | float = "0.10",
    client: Optional[BlockchainIQClient] = None,
) -> list[BaseTool]:
    """Build the Blockchain IQ tools for a LangChain agent.

    ``private_key`` defaults to the ``BLOCKCHAINIQ_PRIVATE_KEY`` (or
    ``AGENT_PRIVATE_KEY``) environment variable. Without a key the free
    tools still work and the paid tools raise a clear error. The per-call
    spend limit defaults to $0.10 and refuses dearer calls before signing.
    """
    client = client or _client_from_env(private_key, max_amount_usdc)

    def _run(result) -> str:
        return json.dumps(result.as_dict())

    def catalog() -> str:
        """List every Blockchain IQ resource with its price (free)."""
        return _run(client.catalog())

    def sample() -> str:
        """Fetch the free Bitcoin network-activity sample (no payment)."""
        return _run(client.sample())

    def market_brief() -> str:
        """Buy the $0.01 market brief: BTC, ETH, SOL and XRP prices with
        24h/7d/30d moves and rank, scheduled events in the next 48 hours,
        and short risk flags. The opening call of a trading-agent loop."""
        return _run(client.brief())

    def event_risk(days: int = 7, min_importance: int = 1) -> str:
        """Buy the $0.05 event-risk list: scheduled market-moving events
        (US data releases, FOMC/ECB/BoJ decisions, Treasury auctions,
        crypto milestones) for the next `days` days."""
        return _run(client.event_risk(days=days, min_importance=min_importance))

    return [
        StructuredTool.from_function(
            func=catalog,
            name="blockchainiq_catalog",
            description=(
                "List every Blockchain IQ x402 resource with its price and "
                "response shape. Free, no payment. Call this first to see "
                "what data can be bought."
            ),
            args_schema=_NoArgs,
        ),
        StructuredTool.from_function(
            func=sample,
            name="blockchainiq_sample",
            description=(
                "Free sample of Blockchain IQ data: Bitcoin network activity "
                "(transactions, active addresses, fees) for its latest day. "
                "No payment; use it to test the integration."
            ),
            args_schema=_NoArgs,
        ),
        StructuredTool.from_function(
            func=market_brief,
            name="blockchainiq_market_brief",
            description=(
                "Buy the Blockchain IQ market brief for $0.01 USDC (paid via "
                "x402 on Base): BTC, ETH, SOL and XRP prices with 24h/7d/30d "
                "moves and market-cap rank, scheduled macro and crypto events "
                "in the next 48 hours, and short risk flags. Refreshed every "
                "minute. Returns the data plus a _payment receipt with the "
                "settlement transaction hash."
            ),
            args_schema=_NoArgs,
        ),
        StructuredTool.from_function(
            func=event_risk,
            name="blockchainiq_event_risk",
            description=(
                "Buy Blockchain IQ event risk for $0.05 USDC (paid via x402 "
                "on Base): scheduled market-moving events for the next N "
                "days (US CPI/jobs/GDP releases, FOMC, ECB and Bank of Japan "
                "decisions, Treasury auctions, crypto and regulatory "
                "milestones), each ranked by importance with its source. "
                "Returns the data plus a _payment receipt."
            ),
            args_schema=EventRiskArgs,
        ),
    ]
