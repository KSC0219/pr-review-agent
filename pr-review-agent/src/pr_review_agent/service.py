"""Runs reviews and keeps track of the ones waiting for human approval."""

from __future__ import annotations

import uuid

from langgraph.types import Command

from .config import Settings, load_settings
from .graph import build_graph
from .llm import LLM, make_llm
from .mcp_server import build_server
from .tool_client import ToolClient
from .tracing import Tracer


class ReviewService:
    def __init__(self, llm: LLM, tools: ToolClient, tracer: Tracer | None = None,
                 max_comments: int = 10, auto_approve: bool = False):
        self.tracer = tracer or Tracer(None)
        self.auto_approve = auto_approve
        self.graph = build_graph(llm, tools, self.tracer, max_comments)
        self.reviews: dict[str, dict] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ReviewService":
        settings = settings or load_settings()
        tools = ToolClient.in_process(build_server()) if settings.mcp_transport == "inprocess" else ToolClient.stdio()
        return cls(make_llm(settings), tools, Tracer(settings.trace_file),
                   settings.max_comments, settings.auto_approve)

    def _snapshot(self, review_id: str, state: dict) -> dict:
        waiting = "__interrupt__" in state
        if waiting:
            status = "pending_approval"
        elif state.get("post_result"):
            status = "posted"
        elif state.get("approved") is False:
            status = "rejected"
        else:
            status = "done"
        usage = state.get("usage", [])
        record = {
            "review_id": review_id,
            "repo": state.get("repo"),
            "pr_number": state.get("pr_number"),
            "status": status,
            "summary": state.get("summary", ""),
            "findings": state.get("findings", []),
            "dropped_by_guardrail": state.get("dropped", 0),
            "post_result": state.get("post_result"),
            "cost_usd": round(sum(u["cost_usd"] for u in usage), 6),
            "tokens": sum(u["input_tokens"] + u["output_tokens"] for u in usage),
        }
        self.reviews[review_id] = record
        return record

    async def start(self, repo: str, pr_number: str, auto_approve: bool | None = None) -> dict:
        review_id = uuid.uuid4().hex[:12]
        config = {"configurable": {"thread_id": review_id}}
        state = await self.graph.ainvoke(
            {"review_id": review_id, "repo": repo, "pr_number": str(pr_number),
             "auto_approve": self.auto_approve if auto_approve is None else auto_approve},
            config,
        )
        return self._snapshot(review_id, state)

    async def decide(self, review_id: str, approved: bool) -> dict:
        record = self.reviews.get(review_id)
        if record is None:
            raise KeyError(review_id)
        if record["status"] != "pending_approval":
            raise ValueError(f"review {review_id} is {record['status']}, not pending approval")
        config = {"configurable": {"thread_id": review_id}}
        state = await self.graph.ainvoke(Command(resume={"approved": approved}), config)
        return self._snapshot(review_id, state)
