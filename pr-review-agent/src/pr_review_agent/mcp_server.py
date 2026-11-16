"""MCP server that exposes pull request tools.

Run standalone with `python -m pr_review_agent.mcp_server` (stdio transport).
Any MCP client can use it: this project's LangGraph agent, Claude Desktop,
or an IDE assistant.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .backends import PRBackend, make_backend
from .config import load_settings


def build_server(backend: PRBackend | None = None) -> MCPServer:
    server = MCPServer(
        "pr-review-tools",
        instructions="Tools for reading a pull request and posting a code review on it.",
    )
    state: dict[str, PRBackend] = {}

    def _backend() -> PRBackend:
        # Created lazily so the server can start (and list tools) without credentials.
        if "b" not in state:
            state["b"] = backend or make_backend(load_settings())
        return state["b"]

    @server.tool()
    def get_pr_diff(repo: str, pr_number: str) -> str:
        """Return the unified diff of a pull request. `repo` is "owner/name"."""
        return _backend().get_pr_diff(repo, pr_number)

    @server.tool()
    def get_file_content(repo: str, path: str, ref: str = "HEAD") -> str:
        """Return the full content of one file at a git ref, for extra context."""
        return _backend().get_file_content(repo, path, ref)

    @server.tool()
    def post_review(repo: str, pr_number: str, summary: str, comments: list[dict]) -> str:
        """Post a review. Each comment is {"path": str, "line": int, "body": str}."""
        for c in comments:
            if not {"path", "line", "body"} <= set(c):
                raise ValueError("each comment needs path, line and body")
        return _backend().post_review(repo, pr_number, summary, comments)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
