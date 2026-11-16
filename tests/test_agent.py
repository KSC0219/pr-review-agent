"""Unit and end-to-end tests. No network and no API key needed."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from eval.dataset import CASES, build_diff, expected_lines
from eval.run_eval import score_case, summarise
from pr_review_agent.agents import build_summary, merge_findings, run_specialist
from pr_review_agent.app import create_app, verify_signature
from pr_review_agent.backends import LocalBackend
from pr_review_agent.baseline import BaselineLLM
from pr_review_agent.diff_parser import annotate, parse_diff
from pr_review_agent.llm import FakeLLM
from pr_review_agent.mcp_server import build_server
from pr_review_agent.models import Finding
from pr_review_agent.service import ReviewService
from pr_review_agent.tool_client import ToolClient
from pr_review_agent.tracing import Tracer

DIFF = """diff --git a/src/main/java/A.java b/src/main/java/A.java
--- a/src/main/java/A.java
+++ b/src/main/java/A.java
@@ -10,4 +10,5 @@
     void run() {
-        old();
+        String sql = "SELECT * FROM t WHERE id = " + id;
+        if (name == "x") { }
     }
"""
FILE = "src/main/java/A.java"


def finding(line=11, category="bug", severity="medium", file=FILE, title="t"):
    return Finding(file=file, line=line, category=category, severity=severity, title=title, explanation="e")


# ------------------------------------------------------------ diff parser
def test_parse_diff_tracks_new_line_numbers():
    (f,) = parse_diff(DIFF)
    assert f.path == FILE
    assert f.added_line_numbers == {11, 12}
    assert f.added[0][1].strip().startswith("String sql")


def test_parse_diff_handles_multiple_files_and_deleted_file():
    diff = DIFF + "diff --git a/B.java b/B.java\n--- a/B.java\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-gone\n" \
        + "diff --git a/C.java b/C.java\n--- /dev/null\n+++ b/C.java\n@@ -0,0 +1,2 @@\n+one\n+two\n"
    files = parse_diff(diff)
    assert [f.path for f in files] == [FILE, "C.java"]
    assert files[1].added_line_numbers == {1, 2}


def test_annotate_shows_line_numbers_and_markers():
    text = annotate(parse_diff(DIFF))
    assert f"=== FILE: {FILE} ===" in text
    assert "   11 + " in text
    assert "      - " in text


# ----------------------------------------------------------------- agents
async def test_guardrail_drops_findings_on_lines_the_pr_did_not_add():
    files = parse_diff(DIFF)
    llm = FakeLLM(lambda agent, _: [
        {"file": FILE, "line": 11, "severity": "high", "title": "real", "explanation": "x"},
        {"file": FILE, "line": 10, "severity": "high", "title": "context line", "explanation": "x"},
        {"file": "Other.java", "line": 11, "severity": "high", "title": "wrong file", "explanation": "x"},
        {"file": FILE, "line": 12, "severity": "catastrophic", "title": "bad schema", "explanation": "x"},
    ])
    kept, _, dropped = await run_specialist("security", llm, annotate(files), files)
    assert [f.title for f in kept] == ["real"]
    assert kept[0].category == "security"
    assert dropped == 3


def test_merge_deduplicates_nearby_findings_and_keeps_highest_severity():
    merged = merge_findings([finding(11, severity="low", title="a"), finding(12, severity="high", title="b"),
                             finding(11, category="security", title="c")], max_comments=10)
    assert sorted(f.title for f in merged) == ["b", "c"]


def test_merge_caps_comment_count_keeping_most_severe():
    items = [finding(line=10 * i, severity="low") for i in range(1, 6)] + [finding(line=500, severity="high", title="top")]
    merged = merge_findings(items, max_comments=3)
    assert len(merged) == 3
    assert any(f.title == "top" for f in merged)


def test_summary_counts_by_category():
    assert "No issues" in build_summary([])
    text = build_summary([finding(), finding(20, category="security")])
    assert "**2** issue(s): 1 bug, 1 security, 0 missing-test" in text


async def test_baseline_rules_fire_on_seeded_defects():
    files = parse_diff(DIFF)
    llm = BaselineLLM()
    bugs, _ = await llm.review("bug", "", annotate(files))
    sec, _ = await llm.review("security", "", annotate(files))
    assert [b["line"] for b in bugs] == [12]
    assert [s["line"] for s in sec] == [11]


# -------------------------------------------------------------- MCP layer
@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "7.diff").write_text(DIFF, encoding="utf-8")
    return tmp_path


async def test_mcp_server_exposes_tools_and_serves_diff(workspace):
    tools = ToolClient.in_process(build_server(LocalBackend(str(workspace))))
    assert set(await tools.list_tools()) == {"get_pr_diff", "get_file_content", "post_review"}
    assert await tools.call("get_pr_diff", {"repo": "o/r", "pr_number": "7"}) == DIFF


async def test_mcp_tool_error_is_raised(workspace):
    tools = ToolClient.in_process(build_server(LocalBackend(str(workspace))))
    with pytest.raises(RuntimeError):
        await tools.call("get_pr_diff", {"repo": "o/r", "pr_number": "../../etc/passwd"})


# ------------------------------------------------------------- full graph
def make_service(workspace, auto_approve=False, llm=None):
    tools = ToolClient.in_process(build_server(LocalBackend(str(workspace))))
    return ReviewService(llm or BaselineLLM(), tools, Tracer(None), auto_approve=auto_approve)


async def test_graph_runs_three_agents_in_parallel_and_posts(workspace):
    llm = FakeLLM(lambda agent, _: [{"file": FILE, "line": 11, "severity": "high", "title": agent, "explanation": "x"}])
    service = make_service(workspace, auto_approve=True, llm=llm)
    record = await service.start("o/r", "7")
    assert sorted(llm.calls) == ["bug", "security", "tests"]
    assert record["status"] == "posted"
    posted = json.loads((workspace / "out" / "7.review.json").read_text())
    assert len(posted["comments"]) == 3
    assert {c["line"] for c in posted["comments"]} == {11}
    assert [e["node"] for e in service.tracer.events][0] == "fetch"
    assert [e["node"] for e in service.tracer.events][-1] == "post"


async def test_human_approval_pauses_then_posts(workspace):
    service = make_service(workspace)
    record = await service.start("o/r", "7")
    assert record["status"] == "pending_approval"
    assert not (workspace / "out").exists()
    record = await service.decide(record["review_id"], approved=True)
    assert record["status"] == "posted"
    assert (workspace / "out" / "7.review.json").exists()


async def test_rejected_review_is_never_posted(workspace):
    service = make_service(workspace)
    record = await service.start("o/r", "7")
    record = await service.decide(record["review_id"], approved=False)
    assert record["status"] == "rejected"
    assert not (workspace / "out").exists()
    with pytest.raises(ValueError):
        await service.decide(record["review_id"], approved=True)


async def test_clean_pr_needs_no_approval(workspace):
    service = make_service(workspace, llm=FakeLLM(lambda *_: []))
    record = await service.start("o/r", "7")
    assert record["findings"] == []
    assert record["status"] == "posted"


# ---------------------------------------------------------------- webhook
def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature():
    assert verify_signature("s", b"body", sign("s", b"body"))
    assert not verify_signature("s", b"body", sign("other", b"body"))
    assert not verify_signature("", b"body", sign("", b"body"))
    assert not verify_signature("s", b"body", None)


def test_webhook_rejects_bad_signature_and_runs_review(workspace):
    service = make_service(workspace)
    client = TestClient(create_app(service, webhook_secret="s"))
    body = json.dumps({"action": "opened", "repository": {"full_name": "o/r"}, "pull_request": {"number": 7}}).encode()
    headers = {"X-GitHub-Event": "pull_request", "Content-Type": "application/json"}

    assert client.post("/webhook", content=body, headers={**headers, "X-Hub-Signature-256": "sha256=bad"}).status_code == 401

    ok = client.post("/webhook", content=body, headers={**headers, "X-Hub-Signature-256": sign("s", body)})
    assert ok.status_code == 202 and ok.json() == {"accepted": "o/r#7"}

    (pending,) = client.get("/reviews", params={"status": "pending_approval"}).json()
    approved = client.post(f"/reviews/{pending['review_id']}/approve")
    assert approved.json()["status"] == "posted"
    assert client.post(f"/reviews/{pending['review_id']}/approve").status_code == 409
    assert client.post("/reviews/nope/approve").status_code == 404


def test_webhook_ignores_other_events(workspace):
    client = TestClient(create_app(make_service(workspace), webhook_secret="s"))
    body = b"{}"
    r = client.post("/webhook", content=body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": sign("s", body)})
    assert r.json() == {"ignored": "push"}


# ------------------------------------------------------------- evaluation
def test_every_eval_case_builds_a_valid_diff():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        (parsed,) = parse_diff(build_diff(case))
        for exp in expected_lines(case):
            assert exp["line"] in parsed.added_line_numbers, case["id"]


def test_scoring_matches_by_category_file_and_line_tolerance():
    expected = [{"file": FILE, "line": 11, "category": "bug"}]
    hit = {"file": FILE, "line": 12, "category": "bug"}
    wrong_category = {"file": FILE, "line": 11, "category": "tests"}
    far = {"file": FILE, "line": 30, "category": "bug"}
    assert score_case(expected, [hit, wrong_category]) == {"tp": 1, "fn": 0, "fp": 1}
    assert score_case(expected, [far]) == {"tp": 0, "fn": 1, "fp": 1}
    assert score_case([], []) == {"tp": 0, "fn": 0, "fp": 0}


def test_summary_metrics():
    rows = [
        {"category": "bug", "expected": 1, "tp": 1, "fn": 0, "fp": 1, "cost_usd": 0.01, "latency_s": 1, "dropped": 0},
        {"category": "bug", "expected": 1, "tp": 0, "fn": 1, "fp": 0, "cost_usd": 0.01, "latency_s": 3, "dropped": 1},
        {"category": "clean", "expected": 0, "tp": 0, "fn": 0, "fp": 0, "cost_usd": 0.0, "latency_s": 2, "dropped": 0},
    ]
    s = summarise(rows)
    assert s["recall"] == 0.5 and s["precision"] == 0.5
    assert s["clean_cases_with_no_comments"] == 1
    assert s["by_category"]["bug"]["recall"] == 0.5
    assert s["avg_latency_s"] == 2.0


# ------------------------------------------------------- Anthropic adapter
async def test_anthropic_adapter_parses_forced_tool_call_and_costs(monkeypatch):
    from types import SimpleNamespace

    from pr_review_agent.config import load_settings
    from pr_review_agent.llm import AnthropicLLM

    captured = {}

    class FakeMessages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            block = SimpleNamespace(type="tool_use", input={"findings": [{"file": FILE, "line": 11}]})
            return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=1000, output_tokens=200))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("PRICE_INPUT_PER_MTOK", "1.0")
    monkeypatch.setenv("PRICE_OUTPUT_PER_MTOK", "5.0")
    llm = AnthropicLLM(load_settings())
    llm._client = SimpleNamespace(messages=FakeMessages())
    findings, usage = await llm.review("bug", "system prompt", "diff text")
    assert findings == [{"file": FILE, "line": 11}]
    assert captured["tool_choice"] == {"type": "tool", "name": "report_findings"}
    assert usage.cost_usd == pytest.approx(0.002)
