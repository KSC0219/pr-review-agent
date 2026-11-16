"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    anthropic_model: str
    price_in: float
    price_out: float
    pr_backend: str
    github_token: str
    webhook_secret: str
    local_pr_dir: str
    auto_approve: bool
    max_comments: int
    mcp_transport: str
    trace_file: str


def load_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        price_in=float(os.getenv("PRICE_INPUT_PER_MTOK", "1.0")),
        price_out=float(os.getenv("PRICE_OUTPUT_PER_MTOK", "5.0")),
        pr_backend=os.getenv("PR_BACKEND", "github"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        local_pr_dir=os.getenv("LOCAL_PR_DIR", "examples"),
        auto_approve=_bool("AUTO_APPROVE", False),
        max_comments=int(os.getenv("MAX_COMMENTS", "10")),
        mcp_transport=os.getenv("MCP_TRANSPORT", "stdio"),
        trace_file=os.getenv("TRACE_FILE", "traces/trace.jsonl"),
    )
