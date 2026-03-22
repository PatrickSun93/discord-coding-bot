"""Test MiniMax API call via Anthropic SDK with the current config."""
import asyncio

from devbot.config.settings import load_config
from devbot.llm.router import LLMRouter


async def main():
    cfg = load_config()
    print(f"base_url : {cfg.llm.primary.base_url}")
    print(f"model    : {cfg.llm.primary.model}")
    print(f"api_key  : {'configured' if cfg.llm.primary.api_key else 'missing'}")
    print()

    router = LLMRouter(cfg)
    print("Calling MiniMax...")
    decision = await router._route_minimax(
        "Request: use claude to add a hello world function to project test",
        router._get_system_prompt(),
    )
    print(f"tool : {decision.tool}")
    print(f"args : {decision.args}")

asyncio.run(main())
