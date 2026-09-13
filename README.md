# Wyatt Roblox Client MCP

A personal fork of [0xCiel/Roblox-Exploiting-MCP](https://github.com/0xCiel/Roblox-Exploiting-MCP), retaining its MIT license and attribution.

Connect one or more running Roblox clients to an AI through localhost. The bridge starts in observation mode. No authentication tokens are required.

## Start here on Windows

Install Python 3.10 or newer, then run these commands from this repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe bridge.py
```

Keep that terminal open. The bridge listens on `127.0.0.1:28430`, with live logs on `127.0.0.1:28431`.

In your compatible executor, run the contents of [client.lua](client.lua), or load that same file from your running local bridge:

```lua
loadstring(game:HttpGet("http://127.0.0.1:28430/client.lua"))()
```

Configure your MCP application to launch `.venv/Scripts/python.exe` with the absolute path to `agent_server.py`. The adapter uses stdio and shares the running local bridge. No environment variables or tokens are needed. Restart the MCP application after updating its tool definitions.

After updating from the earlier version, stop the old bridge, reinstall requirements, restart it, and rerun the updated client script.

## Features and tools

| Feature | Tools / behavior |
| --- | --- |
| Code execution | `execute`, with returned output or asynchronous scheduling through `wait_result=false` |
| Script inspection | `inspect_scripts`, `read_script`, paginated full-source literal `search_sources`, local embedding-based `semantic_search` |
| Instances | `search_instances`, `instance_tree`, `instance_properties`, `set_property` for properties or attributes |
| Remote spy and firing | `remote_spy`, `remote_rule` for block/ignore toggles through an already-loaded Cobalt copy, `fire_remote` for events/functions |
| Live console logs | Client WebSocket streaming, HTTP fallback, `get_logs` with cursors, and `view_logs.py` for live terminal output |
| GUI interaction | `click_button` via virtual mouse input; `type_text` focuses a TextBox, sets text, and optionally submits |
| Windows integration | `list_processes`, `list_windows`, and `screenshot` with an explicit Roblox window handle |
| Multiple clients | `list_clients`, `select_client`, explicit client IDs on game tools, automatic active-client promotion after disconnect |
| Multiple bridge processes | Extra bridge processes wait as secondaries and automatically promote after primary exit. MCP adapters relay through the same primary |
| Local script hub | `script_library`, `save_script`, `load_script`, `run_script`; scripts stay in the ignored `script_library/` folder |

There are 26 registered MCP tools. Tools return the originating client ID so observations from different games can be kept separate.

### Observation and action modes

Observation mode supports game info, hierarchy/property reads, script inspection, logs, and screenshots. It rejects arbitrary code execution, property changes, GUI actions, remote firing/blocking, and saved script execution.

Use `set_action_mode(true)` explicitly when you want those actions. Use `set_action_mode(false)` to return to observation. Mode applies to the whole local bridge and resets to observation after a primary restart. Inspection/decompilation can still consume client resources; keep batches small.

Without tokens, any local process that can reach the port can use the bridge or change mode. Host/Origin validation and localhost binding are retained; observation mode is a workflow default, not authentication or a sandbox.

### Script inspection and semantic search

The client tries readable `Source`, then the executor's `decompile` function. Only client-visible scripts are accessible. Decompilation support and quality depend on the runtime; server-only scripts cannot be recovered by this connector.

`inspect_scripts` and `search_sources` process 20 scripts per call. Use `next_offset` to continue. Literal search examines complete sources within that batch and returns compact excerpts. `read_script` supports line ranges. Semantic search embeds the first 4000 characters of each readable source in its requested batch; it does not claim to search an entire game automatically.

For semantic search, install [Ollama](https://ollama.com/) separately and prepare a local model:

```powershell
ollama pull embeddinggemma
```

Keep Ollama running at `127.0.0.1:11434`. `semantic_search` uses its `/api/embed` endpoint. No source is sent to a cloud embedding service. Missing Ollama/model errors are returned rather than silently substituting keyword search. Model installation is not performed by this repository.

### Selectors and values

Supported selector subset:

- `TextButton`
- `#Play`
- `ScreenGui TextButton`
- `Frame > TextButton`
- `Part[@Team=Blue]`
- `TextButton[Visible=true]`

Spaces select descendants and `>` selects direct children. Names and filter values containing spaces are not supported by this subset. Use returned instance refs for exact targets, especially duplicate or punctuated names. Queries report truncation and have scan/result limits. Refs are local to one connector session.

Typed mutation/remote argument values may use `{ "type": "Vector3", "value": [1,2,3] }`, `Color3`, `CFrame`, or `{ "ref": "12" }`. General code execution covers other runtime-specific types.

### Cobalt remote interception

Load a trusted [Cobalt](https://github.com/notpoiu/cobalt) copy in the same executor first. The connector integrates with `getgenv().Cobalt.shared.Logs` and its Block/Ignore methods. It does not download or silently execute Cobalt.

`remote_spy` reads intercepted incoming/outgoing calls. A remote must have appeared in Cobalt's log before applying a block/ignore rule. `remote_rule` targets its exact instance ref, avoiding ambiguous names. Rule changes and firing require action mode. Unloading Cobalt uses Cobalt's own controls; stopping this connector does not undo another tool's hooks.

### Logs, screenshots, and disconnects

To watch live console logs in another terminal:

```powershell
.\.venv\Scripts\python.exe view_logs.py
```

The client uses WebSockets when supported, otherwise posts log batches over HTTP. Subscribers still receive WebSocket updates. The server retains 1000 events; cursors report discarded history. Client buffering is bounded and may drop messages under overload or disconnect.

Screenshots require Windows and a currently visible, non-minimized Roblox window selected from `list_windows`. The tool returns a PNG image through MCP. It does not foreground a window, capture unrelated applications, launch programs, or terminate Roblox.

An inactive client expires after 45 seconds. Another client becomes active automatically; pin `client_id` when targeting matters. After bridge failover, connectors re-register. In-flight commands are not replayed. A relay timeout does not stop Luau that is already running, so never automatically retry an action after a timeout.

Stop the client with:

```lua
getgenv().WYATT_BRIDGE_STOP()
```

This disconnects this connector's log listener and transport. It does not forcibly stop already-running Luau. Stop every bridge process to prevent a standby from promoting.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_bridge.py test_features.py test_client.py
```

For Lua tests, set `LUAU_EXE` to a real Luau CLI binary. Without it the Lua test is explicitly skipped. `lua_test_template.luau` supplies a simulated game, never an executor.

Tests cover routing, observation mode, stale/wrong task IDs, script path confinement, HTTP and WebSocket boundaries, log streaming, local embedding ranking with a mocked model, the actual MCP stdio handshake, process failover, and mocked Lua handler behavior. Executor-specific hooks, decompilation, GUI behavior, live Roblox capture, and real model inference still require integration testing. No executor or Cobalt is installed by the test suite.
