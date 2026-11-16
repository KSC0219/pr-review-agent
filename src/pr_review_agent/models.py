"""Shared data models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["bug", "security", "tests"]
Severity = Literal["low", "medium", "high"]

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


class Finding(BaseModel):
    """One review comment anchored to a line that the PR added."""

    file: str
    line: int = Field(ge=1, description="Line number in the new version of the file")
    category: Category
    severity: Severity = "medium"
    title: str
    explanation: str = ""
    suggestion: str = ""
    agent: str = ""

    def to_comment_body(self) -> str:
        icon = {"bug": "🐛", "security": "🔒", "tests": "🧪"}[self.category]
        body = f"{icon} **{self.title}** ({self.severity})\n\n{self.explanation}".rstrip()
        if self.suggestion:
            body += f"\n\n**Suggested fix:** {self.suggestion}"
        return body


class Usage(BaseModel):
    """Token and cost accounting for one LLM call."""

    agent: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
