"""MCP server: the briefing's read-only tools for any MCP client (e.g. Claude Desktop).

Exposes the same tools as app/tools.py, with the same Pydantic schemas and descriptions,
over the official Python MCP SDK (stdio). Every call takes a `user_id`: the user's
entitlements come from the users table (never from the caller's arguments), and the call
goes through the same validation, entitlement filters and audit log as the web app.

Run:  make mcp   (or: python -m mcp_server.server)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # also works when run as a script

import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from app import tools  # noqa: E402

# Read-only tools only: the eight briefing tools, plus get_source (what a citation opens)
MCP_TOOLS = {t.__name__: t for t in [*tools.AGENT_TOOLS, tools.get_source]}
USER_ID = {"type": "string", "description": "Who is asking, e.g. u1 (Alex) or u2 (Sam). Their entitlements "
                                            "come from the users table and decide what they may see."}


def input_schema(tool) -> dict:
    """The tool's Pydantic request schema, with the required user_id added first."""
    schema = tool.request_model.model_json_schema()
    return schema | {"properties": {"user_id": USER_ID, **schema.get("properties", {})},
                     "required": ["user_id", *schema.get("required", [])]}


def tool_definitions() -> list[types.Tool]:
    return [types.Tool(name=name, description=" ".join((tool.__doc__ or "").split()), inputSchema=input_schema(tool),
                       annotations=types.ToolAnnotations(readOnlyHint=True))
            for name, tool in MCP_TOOLS.items()]


def run_tool(name: str, arguments: dict | None) -> dict:
    """One call: a known tool, a known user, then the tool itself (validated, filtered, audited)."""
    arguments = dict(arguments or {})
    if name not in MCP_TOOLS:
        return {"ok": False, "error": "unknown_tool"}
    user = tools.load_user(str(arguments.pop("user_id", "")))
    if user is None:
        return {"ok": False, "error": "unknown_user"}
    return MCP_TOOLS[name](user, **arguments).model_dump(mode="json")


async def list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=tool_definitions())


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    result = run_tool(params.name, params.arguments)
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))],
                                structuredContent=result, isError=not result.get("ok", False))


server = Server("client-briefing", instructions="Read-only tools over the client briefing data. Pass user_id on "
                                                "every call; results are filtered by that user's entitlements.",
                on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
