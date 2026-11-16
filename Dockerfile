FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV MCP_TRANSPORT=stdio \
    TRACE_FILE=/app/traces/trace.jsonl
EXPOSE 8000
CMD ["uvicorn", "pr_review_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
