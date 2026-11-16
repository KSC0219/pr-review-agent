"""LLM providers behind one small interface.

`AnthropicLLM` forces a tool call so the model must return findings as JSON
that matches a schema. `BaselineLLM` (see baseline.py) and `FakeLLM` implement
the same interface without any network call.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from .config import Settings
from .models import Usage

FINDINGS_TOOL = {
    "name": "report_findings",
    "description": "Report review findings for the pull request. Use an empty list if there are none.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer", "description": "New-file line number of an added (+) line"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "title": {"type": "string"},
                        "explanation": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["file", "line", "severity", "title", "explanation"],
                },
            }
        },
        "required": ["findings"],
    },
}


class LLM(Protocol):
    async def review(self, agent: str, system: str, annotated_diff: str) -> tuple[list[dict], Usage]: ...


class AnthropicLLM:
    def __init__(self, settings: Settings):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic()
        self._settings = settings

    async def review(self, agent: str, system: str, annotated_diff: str) -> tuple[list[dict], Usage]:
        started = time.perf_counter()
        response = await self._client.messages.create(
            model=self._settings.anthropic_model,
            max_tokens=2000,
            system=system,
            tools=[FINDINGS_TOOL],
            tool_choice={"type": "tool", "name": "report_findings"},
            messages=[{"role": "user", "content": f"Review this pull request diff:\n\n{annotated_diff}"}],
        )
        findings: list[dict] = []
        for block in response.content:
            if block.type == "tool_use":
                findings = list(block.input.get("findings", []))
        tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
        cost = (tokens_in * self._settings.price_in + tokens_out * self._settings.price_out) / 1_000_000
        usage = Usage(
            agent=agent,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=round(cost, 6),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return findings, usage


class FakeLLM:
    """Test double: returns whatever the supplied function returns."""

    def __init__(self, fn: Callable[[str, str], list[dict]]):
        self._fn = fn
        self.calls: list[str] = []

    async def review(self, agent: str, system: str, annotated_diff: str) -> tuple[list[dict], Usage]:
        self.calls.append(agent)
        return self._fn(agent, annotated_diff), Usage(agent=agent)


def make_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "baseline":
        from .baseline import BaselineLLM

        return BaselineLLM()
    return AnthropicLLM(settings)
