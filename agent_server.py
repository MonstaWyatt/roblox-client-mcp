"""Stdio MCP adapter. Keep its control token out of client Lua."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Wyatt Roblox Client")
opener = build_opener(ProxyHandler({}))


@mcp.tool()
def execute(code: str) -> str:
    """Execute Luau in the connected client and return its output.

    Only client-accessible state is available. Use a return statement for output.
    A relay timeout does not stop code in the game. Never automatically retry
    timed-out actions, since they might already have taken effect.
    """
    token = os.environ.get("ROBLOX_CONTROL_TOKEN")
    if not token:
        return json.dumps({"error": "ROBLOX_CONTROL_TOKEN is not configured"})
    request = Request(
        "http://127.0.0.1:28430/execute",
        data=json.dumps({"code": code}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
    )
    try:
        with opener.open(request, timeout=25) as response:
            return response.read().decode()
    except HTTPError as exc:
        return exc.read().decode()
    except (URLError, TimeoutError) as exc:
        return json.dumps({"error": str(exc), "retry_safe": False})


if __name__ == "__main__":
    mcp.run()
