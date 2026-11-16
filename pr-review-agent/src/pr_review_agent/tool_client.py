"""Thin MCP client used by the graph nodes.

The agent never imports the GitHub backend directly. Every read and write
goes through an MCP tool call, so the tool layer can be swapped or reused.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import MCPServer


class ToolClient:
    def __init__(self, target: MCPServer | StdioServerParameters | str):
        self._target = target

    @classmethod
    def stdio(cls) -> "ToolClient":
        """Launch `pr_review_agent.mcp_server` as a subprocess."""
        return cls(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "pr_review_agent.mcp_server"],
                env=dict(os.environ),
            )
        )

    @classmethod
    def in_process(cls, server: MCPServer) -> "ToolClient":
        return cls(server)

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        async with Client(self._target) as client:
            result = await client.call_tool(name, arguments)
        text = "".join(getattr(block, "text", "") for block in result.content)
        if result.is_error:
            raise RuntimeError(f"MCP tool {name} failed: {text}")
        return text

    async def list_tools(self) -> list[str]:
        async with Client(self._target) as client:
            result = await client.list_tools()
        return [t.name for t in result.tools]
