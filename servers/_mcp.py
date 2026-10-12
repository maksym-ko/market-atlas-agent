"""MCP server class across SDK versions: FastMCP in mcp 1.x, renamed MCPServer in 2.x."""
try:
    from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x (required by langchain-mcp-adapters today)

__all__ = ["Server"]
