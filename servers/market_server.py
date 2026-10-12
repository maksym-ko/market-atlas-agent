"""MCP market server: the agent loads these tools over MCP; also usable from Claude Desktop.
Note: an MCP client has no approval gate of its own; rely on its tool-approval prompts for gated tools."""
from app.tools import ALL
from servers._mcp import Server

server = Server("Market")
for tool_function in ALL:
    server.tool()(tool_function)

if __name__ == "__main__":
    server.run(transport="stdio")
