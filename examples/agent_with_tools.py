#!/usr/bin/env python3
"""Use the Blockchain IQ tools inside a LangChain agent.

With an OpenAI key present this builds a tool-calling agent and asks it
for the market brief; without one it prints the tools an agent would
receive, so the wiring can be inspected offline.

    AGENT_PRIVATE_KEY=0x... OPENAI_API_KEY=sk-... python examples/agent_with_tools.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_blockchainiq import get_blockchainiq_tools


def main() -> None:
    tools = get_blockchainiq_tools()
    if not os.environ.get("OPENAI_API_KEY"):
        print("No OPENAI_API_KEY set; the agent would receive these tools:\n")
        for tool in tools:
            print(f"- {tool.name}: {tool.description.splitlines()[0]}")
        return
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    agent = create_agent(
        model=ChatOpenAI(model="gpt-4o-mini"),
        tools=tools,
        system_prompt=(
            "You are a trading-desk assistant. Before analysing the market, "
            "call blockchainiq_market_brief and base your answer on its data."
        ),
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Give me the market brief and the main event risks in the next 48 hours."}]}
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
