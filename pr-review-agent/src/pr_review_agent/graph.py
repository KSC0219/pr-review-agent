"""LangGraph workflow.

    fetch ──┬─> bug ──────┐
            ├─> security ─┼─> merge ─> approval ─> post
            └─> tests ────┘                 └────> (rejected: end)

The three reviewers run in parallel. `approval` pauses the graph with a
LangGraph interrupt until a human approves or rejects the review.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents import AGENTS, build_summary, merge_findings, run_specialist
from .diff_parser import annotate, parse_diff
from .llm import LLM
from .models import Finding
from .tool_client import ToolClient
from .tracing import Tracer


class ReviewState(TypedDict, total=False):
    review_id: str
    repo: str
    pr_number: str
    auto_approve: bool
    diff: str
    raw_findings: Annotated[list[dict], operator.add]
    usage: Annotated[list[dict], operator.add]
    dropped: Annotated[int, operator.add]
    findings: list[dict]
    summary: str
    approved: bool
    post_result: str


def build_graph(llm: LLM, tools: ToolClient, tracer: Tracer, max_comments: int = 10):
    async def fetch(state: ReviewState) -> dict:
        with tracer.span(state["review_id"], "fetch") as span:
            diff = await tools.call("get_pr_diff", {"repo": state["repo"], "pr_number": state["pr_number"]})
            span["diff_chars"] = len(diff)
        return {"diff": diff}

    def make_reviewer(agent: str):
        async def reviewer(state: ReviewState) -> dict:
            files = parse_diff(state["diff"])
            with tracer.span(state["review_id"], agent) as span:
                findings, usage, dropped = await run_specialist(agent, llm, annotate(files), files)
                span.update(findings=len(findings), dropped=dropped, input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens, cost_usd=usage.cost_usd)
            return {
                "raw_findings": [f.model_dump() for f in findings],
                "usage": [usage.model_dump()],
                "dropped": dropped,
            }

        return reviewer

    async def merge(state: ReviewState) -> dict:
        with tracer.span(state["review_id"], "merge") as span:
            raw = [Finding(**f) for f in state.get("raw_findings", [])]
            final = merge_findings(raw, max_comments)
            span.update(before=len(raw), after=len(final))
        return {"findings": [f.model_dump() for f in final], "summary": build_summary(final)}

    async def approval(state: ReviewState) -> dict:
        if state.get("auto_approve") or not state.get("findings"):
            return {"approved": True}
        decision = interrupt({"summary": state["summary"], "findings": state["findings"]})
        return {"approved": bool(decision.get("approved"))}

    async def post(state: ReviewState) -> dict:
        with tracer.span(state["review_id"], "post") as span:
            comments = [
                {"path": f["file"], "line": f["line"], "body": Finding(**f).to_comment_body()}
                for f in state["findings"]
            ]
            result = await tools.call(
                "post_review",
                {"repo": state["repo"], "pr_number": state["pr_number"],
                 "summary": state["summary"], "comments": comments},
            )
            span["comments"] = len(comments)
        return {"post_result": result}

    graph = StateGraph(ReviewState)
    graph.add_node("fetch", fetch)
    for agent in AGENTS:
        graph.add_node(agent, make_reviewer(agent))
        graph.add_edge("fetch", agent)
    graph.add_node("merge", merge)
    graph.add_edge(list(AGENTS), "merge")
    graph.add_node("approval", approval)
    graph.add_node("post", post)
    graph.add_edge(START, "fetch")
    graph.add_edge("merge", "approval")
    graph.add_conditional_edges("approval", lambda s: "post" if s.get("approved") else END, ["post", END])
    graph.add_edge("post", END)
    return graph.compile(checkpointer=InMemorySaver())
