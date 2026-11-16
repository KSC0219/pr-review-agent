# Setup

## 1. Local install

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

## 2. Offline demo (no keys)

```bash
pr-review review --local examples --pr demo --llm baseline --auto-approve
```

This reads `examples/demo.diff`, runs the graph with the rule-based reviewer and writes the
review to `examples/out/demo.review.json`. Drop `--auto-approve` to see the approval prompt.

## 3. Use the Claude API

1. Create an API key at https://console.anthropic.com.
2. `cp .env.example .env` and set `ANTHROPIC_API_KEY`. Set `ANTHROPIC_MODEL` to a model your account can use.
3. Set `PRICE_INPUT_PER_MTOK` and `PRICE_OUTPUT_PER_MTOK` to that model's current prices so the cost report is right.
4. Load the variables and run:

```bash
export $(grep -v '^#' .env | xargs)
pr-review review --local examples --pr demo --llm anthropic
python eval/run_eval.py --llm anthropic
```

The evaluation makes 78 small API calls (26 PRs x 3 agents).

## 4. Review a real pull request from the terminal

1. Create a fine-grained GitHub token (Settings > Developer settings > Personal access tokens)
   with **Pull requests: Read and write** and **Contents: Read** on the repositories you want reviewed.
2. Run:

```bash
export GITHUB_TOKEN=github_pat_...
pr-review review --repo <owner>/<repo> --pr <number>
```

You are shown the summary and asked before anything is posted.

## 5. Automatic reviews with a webhook

1. Start the service: `uvicorn pr_review_agent.app:app --port 8000`
2. Expose it. For local testing: `ngrok http 8000`. For a permanent URL, deploy it (section 6).
3. In the GitHub repository: Settings > Webhooks > Add webhook
   - Payload URL: `https://<your-host>/webhook`
   - Content type: `application/json`
   - Secret: the same value as `GITHUB_WEBHOOK_SECRET`
   - Events: "Pull requests" only
4. Open a pull request. Then:

```bash
curl https://<your-host>/reviews?status=pending_approval
curl -X POST https://<your-host>/reviews/<review_id>/approve
```

## 6. Docker and deployment

```bash
docker build -t pr-review-agent .
docker run -p 8000:8000 --env-file .env pr-review-agent
```

The image runs on any container host. On Render: New > Web Service > connect the repository,
choose Docker, add the environment variables from `.env.example`, and use `/health` as the health check path.
On AWS, push the image to ECR and run it on App Runner or ECS Fargate with the same variables.

## 7. Use the MCP server from another client

The server is a normal stdio MCP server:

```json
{
  "mcpServers": {
    "pr-review-tools": {
      "command": "python",
      "args": ["-m", "pr_review_agent.mcp_server"],
      "env": {"GITHUB_TOKEN": "github_pat_..."}
    }
  }
}
```

`pr-review tools` lists the tools it exposes.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `baseline` |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | Model id |
| `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK` | `1.0`, `5.0` | USD per million tokens, for the cost report only |
| `PR_BACKEND` | `github` | `github` or `local` |
| `GITHUB_TOKEN` | | Token used by the MCP server |
| `GITHUB_WEBHOOK_SECRET` | | Shared secret for webhook signatures |
| `LOCAL_PR_DIR` | `examples` | Folder of `.diff` files in local mode |
| `AUTO_APPROVE` | `false` | Post without waiting for a human |
| `MAX_COMMENTS` | `10` | Cap on inline comments per review |
| `MCP_TRANSPORT` | `stdio` | `stdio` (subprocess) or `inprocess` |
| `TRACE_FILE` | `traces/trace.jsonl` | Where step traces are appended |
