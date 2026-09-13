# Wyatt Roblox Client MCP

A personal fork of [0xCiel/Roblox-Exploiting-MCP](https://github.com/0xCiel/Roblox-Exploiting-MCP), retaining the upstream MIT license and attribution.

This first version provides a localhost bridge without token setup for one connected Roblox client. It exposes one MCP tool, `execute`, which sends Luau to the client and returns its output. It does not yet provide screenshots, dedicated movement controls, or a code browser. Server-only scripts are not available through a client bridge.

## Changes from upstream

- Replaced the C++ relay with a Python standard-library relay.
- Bound the listener to `127.0.0.1:28430`.
- No tokens or environment variables required.
- Rejected browser Origin headers and unexpected Host headers.
- Correlated each result with an unpredictable task ID; rejected stale results.
- Rejected simultaneous commands instead of overwriting a shared code buffer.
- Added request limits, client backoff, and finite relay waits.
- Renamed `mcp.py` to `agent_server.py` to avoid shadowing the installed `mcp` package.

## Local setup

Requires Python 3.10+ and a client runtime supporting `getgenv`, `request`, and `loadstring`. No executor is bundled, installed, or downloaded by this project.

1. Create a virtual environment and install `requirements.txt` into it.
2. Start `python bridge.py` from this folder. The relay itself needs only Python's standard library.
3. Configure your MCP client to launch the virtual environment's Python with the absolute path to `agent_server.py`. It communicates using stdio.
4. Run the local `client.lua` contents in your compatible game client. Connect only one game client per relay.
5. Test `execute` with a harmless return value before making changes.

Set `getgenv().WYATT_BRIDGE_RUNNING = false` to stop polling after the current request or command finishes. Stop the relay to stop accepting new commands. Neither action forcibly terminates already-running Luau.

## Boundaries and remaining work

The bridge accepts commands from local programs without authentication. Any local process that can reach the port can submit Luau, receive pending commands, or return results for a delivered task. Host and Origin checks limit browser access but do not authenticate local programs. Executed Luau has the permissions of the connected client runtime.

A 20-second relay timeout means no result arrived in time. It does not cancel game execution. Never automatically retry an action after a timeout. Long-running code can keep the client busy until the client runtime is reset.

The relay supports one client and one active request. Multi-client pairing, session identity, stronger resource limits, and an explicit cancellation protocol remain future work.

Next planned features are connection metadata, typed inspection tools, bounded player actions, and a separate screenshot integration. Each needs testing in an authorized test environment before live use.

## Verification

Run `python -m unittest -v test_bridge.py`.

The six tests cover loopback binding, browser/Host rejection, input size checks, a complete tokenless relay roundtrip with a simulated client, concurrent request rejection, and stale/forged task IDs. They do not execute Luau or prove compatibility with a particular executor. Roblox integration and the full MCP handshake still need verification.
