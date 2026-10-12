"""Builds the tools, checkpointer and graph once and shares them across browser sessions.

TOOLS_TRANSPORT=mcp (default): tools come from the market and research MCP servers over stdio,
kept open as persistent sessions. TOOLS_TRANSPORT=inproc: same tools as Python functions (tests, evals)."""
import asyncio
import os
import sys
from contextlib import AsyncExitStack

import aiosqlite
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app import config
from app.graph import build_graph, make_tools

_ready: asyncio.Future | None = None
_stop: asyncio.Event | None = None
_task: asyncio.Task | None = None
SERVERS = {"market": "servers.market_server", "research": "servers.research_server"}


def inproc_tools():
    from servers.research_server import research_external

    return make_tools() + [StructuredTool.from_function(research_external)]


async def mcp_tools(stack: AsyncExitStack):
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    client = MultiServerMCPClient({
        name: {"transport": "stdio", "command": sys.executable, "args": ["-m", module],
               "cwd": str(config.ROOT), "env": dict(os.environ)}
        for name, module in SERVERS.items()})
    tools = []
    for name in SERVERS:  # persistent sessions: one subprocess per server for the app's lifetime
        session = await stack.enter_async_context(client.session(name))
        tools += await load_mcp_tools(session)
    return tools


async def _owner(ready: asyncio.Future, stop: asyncio.Event) -> None:
    """Owns the MCP sessions and DB connection in one long-lived task: anyio requires cancel scopes
    to be entered and exited by the same task, so they can't live in a request handler's task."""
    try:
        async with AsyncExitStack() as stack:
            conn = await stack.enter_async_context(aiosqlite.connect(config.data_dir() / "state.db"))
            transport = os.getenv("TOOLS_TRANSPORT", "mcp")
            tools = await mcp_tools(stack) if transport == "mcp" else inproc_tools()
            ready.set_result(build_graph(tools, AsyncSqliteSaver(conn)))
            await stop.wait()
    except Exception as e:
        if not ready.done():
            ready.set_exception(e)
        else:
            raise


async def get_graph():
    global _ready, _stop, _task
    if _ready is None:
        _ready, _stop = asyncio.get_running_loop().create_future(), asyncio.Event()
        _task = asyncio.create_task(_owner(_ready, _stop))
    return await asyncio.shield(_ready)


async def close():
    if _task is not None:
        _stop.set()
        await _task
