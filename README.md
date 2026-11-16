# PR Review Agent

A multi-agent pull request reviewer for Java / Spring Boot repositories.
Three specialist LLM agents (bugs, security, missing tests) review a PR in parallel,
their findings are merged, a human approves, and the review is posted to GitHub as inline comments.
All GitHub access goes through a custom **MCP server**.

**Stack:** Python, LangGraph, Model Context Protocol (MCP), Claude API, FastAPI, Docker, GitHub Actions

```
                 ┌──────────────┐
 GitHub webhook  │   FastAPI    │        ┌────────────────────────────────────────────┐
 ───────────────>│  /webhook    │───────>│              LangGraph workflow            │
                 └──────────────┘        │                                            │
                                         │  fetch ─┬─> bug agent ──────┐              │
                 ┌──────────────┐        │         ├─> security agent ─┼─> merge      │
 Human reviewer  │ /reviews/{id}│<──────>│         └─> tests agent ────┘     │        │
 approve/reject  │  /approve    │        │                                   v        │
                 └──────────────┘        │                  approval (interrupt) ─> post
                                         └─────┬──────────────────────────────────┬───┘
                                               │ MCP tool call                    │ MCP tool call
                                               v                                  v
                                         ┌────────────────────────────────────────────┐
                                         │  MCP server: get_pr_diff, get_file_content,│
                                         │              post_review                   │
                                         └───────────────────┬────────────────────────┘
                                                             v
                                                     GitHub REST API
```

## What it does

- **Three specialist agents, run in parallel.** Each has one job and its own prompt, which keeps prompts short and makes each agent's quality measurable on its own.
- **Structured output.** The model is forced to call a `report_findings` tool, so every finding is schema-validated JSON (file, line, severity, title, explanation, suggestion).
- **Line guardrail.** Any finding that does not point at a line the PR actually added is dropped before posting. This removes hallucinated locations, which GitHub would reject anyway.
- **Merge step.** Overlapping findings are deduplicated, ranked by severity and capped (default 10 comments).
- **Human in the loop.** The graph pauses on a LangGraph interrupt. Nothing is posted until someone calls `/reviews/{id}/approve`.
- **MCP tool layer.** The agent never calls GitHub directly. The same MCP server can be plugged into Claude Desktop or an IDE assistant.
- **Tracing and cost.** Every node writes a JSONL trace line with duration, tokens and cost.
- **Evaluation.** A 26-PR seeded-defect set with a rule-based baseline to compare against.

## Quick start (no API key needed)

```bash
git clone https://github.com/KSC0219/pr-review-agent.git
cd pr-review-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                                   # 21 tests
pr-review review --local examples --pr demo --llm baseline --auto-approve
python eval/run_eval.py --llm baseline      # scores the rule-based baseline
```

## Run with the Claude API

```bash
cp .env.example .env        # then fill in ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)

pr-review review --local examples --pr demo --llm anthropic
python eval/run_eval.py --llm anthropic     # writes eval/results/anthropic.json
```

## Run on real pull requests

See [docs/SETUP.md](docs/SETUP.md) for the GitHub token, webhook and deployment steps. Short version:

```bash
export GITHUB_TOKEN=...  GITHUB_WEBHOOK_SECRET=...  ANTHROPIC_API_KEY=...
uvicorn pr_review_agent.app:app --port 8000

# or review a single PR from the terminal
pr-review review --repo <owner>/<repo> --pr <number>
```

| Endpoint | Purpose |
|---|---|
| `POST /webhook` | GitHub `pull_request` events (HMAC-SHA256 signature verified) |
| `GET /reviews?status=pending_approval` | Reviews waiting for a human |
| `POST /reviews/{id}/approve` | Post the review to the PR |
| `POST /reviews/{id}/reject` | Discard the review |
| `GET /health` | Liveness check |

## Evaluation

The set in [`eval/dataset.py`](eval/dataset.py) contains 26 small pull requests:
8 with a planted bug, 8 with a planted vulnerability, 4 that add untested logic and 6 clean PRs
that should get no comments. A finding counts as correct when it has the right category
and lands within 2 lines of the planted defect.

| Reviewer | Recall | Precision | Clean PRs with no comments | Avg cost / PR |
|---|---|---|---|---|
| Rule-based baseline | 60% (12/20) | 100% | 6/6 | $0 |
| LLM agents (Claude) | _run `eval/run_eval.py --llm anthropic`_ | | | |

Baseline recall by category: bugs 3/8, security 5/8, missing tests 4/4. The regex rules miss
defects that need reasoning about meaning (integer division, resource leak, concurrent modification,
path traversal, missing authorization). Those are the cases the LLM agents are there for.
Details and limitations: [docs/EVALUATION.md](docs/EVALUATION.md).

## Project layout

```
src/pr_review_agent/
  mcp_server.py    MCP server exposing the three PR tools
  tool_client.py   MCP client used by the graph (stdio subprocess or in-process)
  backends.py      GitHub REST backend and a local-folder backend
  diff_parser.py   Unified diff parser with new-file line numbers
  agents.py        Specialist prompts, line guardrail, merge and summary
  llm.py           Claude adapter (forced tool call) and test double
  baseline.py      Rule-based reviewer used as the evaluation baseline
  graph.py         LangGraph workflow with parallel fan-out and interrupt
  service.py       Starts reviews and resumes them after approval
  app.py           FastAPI webhook and approval endpoints
  tracing.py       JSONL step tracing
  cli.py           `pr-review` command
eval/              Seeded-defect dataset, scorer and results
tests/             21 pytest tests (no network needed)
docs/              Architecture, setup and evaluation notes
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design, state, and why each choice was made
- [docs/SETUP.md](docs/SETUP.md): local run, GitHub webhook, Docker, deployment
- [docs/EVALUATION.md](docs/EVALUATION.md): dataset, metrics, results, limitations

## Limitations

- Reviews the diff only. It does not yet pull surrounding files for context (the `get_file_content` tool exists for this).
- Pending approvals are held in memory, so they are lost on restart. Swap `InMemorySaver` for a SQLite or Postgres checkpointer to persist them.
- Very large diffs are sent whole; there is no chunking yet.
- The evaluation set is small and synthetic. It measures seeded defects, not real-world review quality.

## License

MIT
