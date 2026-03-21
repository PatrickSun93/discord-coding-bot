"""LLM Router — MiniMax via Anthropic SDK (primary), Ollama via OpenAI-compat (fallback)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anthropic
from openai import AsyncOpenAI

from devbot.llm.tools_schema import ANTHROPIC_TOOLS, TOOLS, build_system_prompt

if TYPE_CHECKING:
    from devbot.config.settings import Config

logger = logging.getLogger(__name__)


@dataclass
class ToolDecision:
    tool: str
    args: dict[str, Any]
    source: str = ""        # which LLM produced this decision: "MiniMax" | "Ollama"
    latency_ms: int = 0     # round-trip time in milliseconds


class LLMRouter:
    def __init__(self, config: "Config"):
        self.config = config

        # MiniMax — Anthropic SDK (sync client wrapped in async calls)
        self._minimax_api_key = config.llm.primary.api_key
        self._minimax_model = config.llm.primary.model
        self._minimax_base_url = config.llm.primary.base_url or None

        # Ollama — OpenAI-compat async client
        self._ollama = AsyncOpenAI(
            base_url=config.llm.fallback.base_url,
            api_key=config.llm.fallback.api_key or "ollama",
        )
        self._ollama_model = config.llm.fallback.model

    def _get_system_prompt(self) -> str:
        return build_system_prompt(self.config)

    async def route(self, user_message: str, project_context: str = "") -> ToolDecision:
        """Route a user message to a tool decision."""
        context_prefix = f"Project context:\n{project_context}\n\n" if project_context else ""
        user_content = f"{context_prefix}Request: {user_message}"

        system_prompt = self._get_system_prompt()

        # Try primary (MiniMax via Anthropic SDK)
        try:
            logger.debug("Routing via MiniMax (%s)", self._minimax_model)
            t0 = time.monotonic()
            decision = await self._route_minimax(user_content, system_prompt)
            decision.source = "MiniMax"
            decision.latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "[Router] MiniMax (%dms) -> tool=%s args=%s",
                decision.latency_ms, decision.tool, decision.args,
            )
            return decision
        except Exception as exc:
            logger.warning("Primary LLM failed (%s), falling back to Ollama", exc)

        # Fallback (Ollama via OpenAI-compat)
        try:
            logger.debug("Routing via Ollama (%s)", self._ollama_model)
            t0 = time.monotonic()
            decision = await self._route_ollama(user_content, system_prompt)
            decision.source = "Ollama"
            decision.latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "[Router] Ollama (%dms) -> tool=%s args=%s",
                decision.latency_ms, decision.tool, decision.args,
            )
            return decision
        except Exception as exc:
            logger.error("Ollama fallback also failed: %s", exc)
            raise RuntimeError(
                f"Both LLMs failed. Ollama error: {exc}\n"
                f"Make sure you have pulled a model: `ollama pull {self._ollama_model}`"
            ) from exc

    async def _route_minimax(self, user_content: str, system_prompt: str) -> ToolDecision:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_minimax_sync, user_content, system_prompt
        )

    def _call_minimax_sync(self, user_content: str, system_prompt: str) -> ToolDecision:
        kwargs: dict = {"api_key": self._minimax_api_key}
        if self._minimax_base_url:
            kwargs["base_url"] = self._minimax_base_url
        client = anthropic.Anthropic(**kwargs)
        response = client.messages.create(
            model=self._minimax_model,
            max_tokens=1024,
            system=system_prompt,
            tools=ANTHROPIC_TOOLS,
            messages=[{"role": "user", "content": user_content}],
        )
        return self._parse_anthropic(response)

    async def _route_ollama(self, user_content: str, system_prompt: str) -> ToolDecision:
        response = await self._ollama.chat.completions.create(
            model=self._ollama_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            tools=TOOLS,
            tool_choice="auto",
            timeout=60,
        )
        return self._parse_openai(response)

    @staticmethod
    def _parse_anthropic(response) -> ToolDecision:
        for block in response.content:
            if block.type == "tool_use":
                return ToolDecision(tool=block.name, args=block.input)
        text = next(
            (block.text for block in response.content if hasattr(block, "text")), ""
        )
        return ToolDecision(tool="reply", args={"text": text})

    @staticmethod
    def _parse_openai(response) -> ToolDecision:
        import json
        choice = response.choices[0]
        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            return ToolDecision(
                tool=tc.function.name,
                args=json.loads(tc.function.arguments),
            )
        return ToolDecision(
            tool="reply",
            args={"text": choice.message.content or ""},
        )
