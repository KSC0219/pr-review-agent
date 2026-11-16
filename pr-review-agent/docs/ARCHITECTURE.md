# Architecture

## Request flow

1. GitHub sends a `pull_request` webhook (`opened`, `synchronize` or `reopened`) to `POST /webhook`.
2. `app.py` verifies the `X-Hub-Signature-256` HMAC, returns `202` immediately and starts the review as a background task.
3. `service.py` starts the LangGraph workflow with a new `review_id`, which is also the checkpoint thread id.
4. **fetch** calls the MCP tool `get_pr_diff`.
5. **bug**, **security** and **tests** run in parallel. Each one sends the annotated diff to the LLM with its own system prompt and validates the result.
6. **merge** deduplicates, ranks and caps the findings, and writes the summary.
7. **approval** raises a LangGraph `interrupt`. The graph state is checkpointed and the review shows up under `GET /reviews?status=pending_approval`.
8. A human calls `/approve` or `/reject`. The graph resumes from the checkpoint with `Command(resume=...)`.
9. **post** calls the MCP tool `post_review`, which creates one GitHub review with inline comments.

## Graph state

| Key | Type | Written by | Notes |
|---|---|---|---|
| `review_id`, `repo`, `pr_number`, `auto_approve` | input | caller | |
| `diff` | `str` | fetch | raw unified diff |
| `raw_findings` | `list[dict]` | bug, security, tests | reducer `operator.add`, so parallel branches append |
| `usage` | `list[dict]` | bug, security, tests | tokens, cost, latency per agent |
| `dropped` | `int` | bug, security, tests | findings removed by the line guardrail |
| `findings`, `summary` | | merge | final comment list |
| `approved` | `bool` | approval | |
| `post_result` | `str` | post | review URL (or file path in local mode) |

The reducers on `raw_findings`, `usage` and `dropped` are what make the parallel fan-out safe:
three nodes write to the same keys in the same step and LangGraph combines them.

## Design decisions

**Why three agents instead of one prompt.**
A single "review this PR" prompt mixes concerns and tends to produce long, unfocused output.
Splitting by concern keeps each prompt short, lets the calls run in parallel, and makes it possible
to measure and tune recall per category.

**Why the merge step is plain code, not another LLM call.**
Deduplication, severity ranking and capping are deterministic rules. Doing them in code is free,
instant and testable. An LLM supervisor would add cost and a new source of error for no benefit here.

**Why MCP.**
The graph only knows tool names (`get_pr_diff`, `post_review`). The MCP server owns credentials and
the GitHub API details. This gives two things: the backend can be swapped (GitHub, local folder,
later GitLab) without touching the agent, and the same server works with any MCP client.
In production the server runs as a stdio subprocess; in tests the client connects to it in-process.
Both paths speak the real MCP protocol.

**Why forced tool calling for output.**
`tool_choice={"type": "tool", "name": "report_findings"}` makes the model return JSON matching a schema.
Each item is then validated with Pydantic; invalid items are dropped and counted.

**Why the line guardrail.**
GitHub only accepts inline comments on lines that are part of the diff. LLMs sometimes cite a nearby
context line or an invented line number. The guardrail keeps a finding only if `(file, line)` is a line
the PR added. Dropped findings are counted in the trace so the rate can be monitored.

**Why human approval by default.**
A bot that posts wrong comments on every PR gets muted quickly. The interrupt lets a maintainer
see the summary first. Set `AUTO_APPROVE=true` once precision is trusted. Clean reviews (no findings)
skip approval.

**Why a rule-based baseline.**
It answers "is the LLM worth its cost?" with a number, and lets the whole pipeline, CI and demo run
without an API key.

## Tracing

`tracing.py` writes one JSON line per node run:

```json
{"ts": 1794849857.648, "review_id": "f5ed1e88d736", "node": "security", "duration_ms": 812.4,
 "findings": 1, "dropped": 0, "input_tokens": 913, "output_tokens": 148, "cost_usd": 0.001653}
```

This is enough to compute cost per review, latency per agent and guardrail drop rate with `jq` or pandas.

## Security notes

- Webhook payloads are rejected unless the HMAC signature matches (`hmac.compare_digest`, constant time).
- The GitHub token is read only by the MCP server process.
- `LocalBackend` resolves paths and refuses anything outside its folder.
- PR content is untrusted input to the LLM. The agents have no tools of their own, so a prompt injection
  in a diff can at worst produce a wrong comment, which the human approval step can reject.
  The approval endpoints have no authentication yet; put the service behind a private network or add an API key before exposing it.

## Possible extensions

- Give agents the `get_file_content` tool so they can read surrounding code before deciding.
- Persistent checkpointer (SQLite/Postgres) so pending approvals survive restarts.
- Route small diffs to a cheaper model and large ones to a stronger model.
- Post the approval request to Slack with approve/reject buttons.
- Chunk large diffs per file.
