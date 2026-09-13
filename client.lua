-- Local client connector. Start bridge.py first. No tokens are required.
local env = getgenv()
env.WYATT_BRIDGE_RUNNING = false -- Stop the previous single-client connector if present.
if env.WYATT_BRIDGE_STOP then pcall(env.WYATT_BRIDGE_STOP) end
assert(type(request) == "function", "HTTP request support required")
local Http = game:GetService("HttpService")
local Players = game:GetService("Players")
local running = true
local url = "http://127.0.0.1:28430"
local clientId = env.WYATT_CLIENT_ID or Http:GenerateGUID(false)
env.WYATT_CLIENT_ID = clientId
local refs, ids, nextId = {}, setmetatable({}, {__mode = "k"}), 0
local connections, eventQueue = {}, {}
local socket = nil
local function ref(inst)
    if not ids[inst] then nextId = nextId + 1; ids[inst] = tostring(nextId); refs[tostring(nextId)] = inst end
    return {ref = ids[inst], name = inst.Name, class = inst.ClassName, path = inst:GetFullName()}
end
local function resolve(value)
    if value == "game" or value == "" or value == nil then return game end
    if refs[value] then return refs[value] end
    local current = game
    for part in string.gmatch(value, "[^%.]+") do
        if part ~= "game" then current = current:FindFirstChild(part); assert(current, "Instance not found: " .. value) end
    end
    return current
end
local function serialize(value, depth, visited)
    depth, visited = depth or 0, visited or {}
    local kind = typeof(value)
    if kind == "Instance" then return ref(value) end
    if kind == "nil" then return {type = "nil"} end
    if kind == "number" then return (value == value and math.abs(value) < math.huge) and value or tostring(value) end
    if kind == "boolean" or kind == "string" then return value end
    if kind ~= "table" then return {type = kind, value = tostring(value)} end
    if depth >= 4 or visited[value] then return "[truncated/cycle]" end
    visited[value] = true
    local output, count = {}, 0
    for key, item in pairs(value) do
        count = count + 1
        if count > 50 then output._truncated = true; break end
        output[tostring(key)] = serialize(item, depth + 1, visited)
    end
    visited[value] = nil
    return output
end
local function decode(value)
    if type(value) ~= "table" then return value end
    if value.ref then return resolve(value.ref) end
    if value.type == "Vector3" then return Vector3.new(unpack(value.value)) end
    if value.type == "Color3" then return Color3.new(unpack(value.value)) end
    if value.type == "CFrame" then return CFrame.new(unpack(value.value)) end
    if value.type == "nil" then return nil end
    local result = {}; for k, v in pairs(value) do result[k] = decode(v) end; return result
end
local function send(path, body)
    local response = request({Url = url .. path, Method = body and "POST" or "GET",
        Headers = {["Content-Type"] = "application/json"}, Body = body and Http:JSONEncode(body) or nil})
    assert(response and response.StatusCode == 200, "Bridge request failed")
    return Http:JSONDecode(response.Body)
end
local function caps()
    return {decompile = type(decompile) == "function", source = true, execute = type(loadstring) == "function",
        websocket = type(WebSocket) == "table" and type(WebSocket.connect) == "function",
        cobalt = env.Cobalt ~= nil, gui_input = pcall(function() return game:GetService("VirtualInputManager") end)}
end
local function register()
    return send("/register", {client_id = clientId, place_id = game.PlaceId, job_id = game.JobId,
        name = game.Name, capabilities = caps()})
end
local function event(level, message)
    if #eventQueue >= 100 then table.remove(eventQueue, 1) end
    table.insert(eventQueue, {level = tostring(level), message = string.sub(tostring(message), 1, 4000)})
end
local handlers = {}
handlers.capabilities = caps
handlers.info = function()
    local player = Players.LocalPlayer
    return {client_id = clientId, place_id = game.PlaceId, job_id = game.JobId, name = game.Name,
        player = player and ref(player), players = #Players:GetPlayers(), capabilities = caps()}
end
-- Selectors: ClassName, #Name, *, [Property=value], [@Attribute=value], descendant and > child.
local function matches(inst, selector)
    local base = selector:match("^[^%[]*") or "*"
    local class, name = base:match("^([^#]*)#(.+)$")
    class = class or base
    if class ~= "" and class ~= "*" and not inst:IsA(class) then return false end
    if name and inst.Name ~= name then return false end
    for key, expected in selector:gmatch("%[([^=%]]+)=([^%]]+)%]") do
        expected = expected:gsub('^["\']', ''):gsub('["\']$', '')
        local ok, actual = pcall(function()
            if key:sub(1, 1) == "@" then return inst:GetAttribute(key:sub(2)) end
            return inst[key]
        end)
        if not ok or tostring(actual) ~= expected then return false end
    end
    return true
end
handlers.search_instances = function(a)
    local tokens = {}; for token in (a.selector or "*"):gsub(">", " > "):gmatch("%S+") do table.insert(tokens, token) end
    local roots, direct = {resolve(a.root)}, false
    local limit = math.clamp(tonumber(a.limit) or 50, 1, 200)
    local scanned, truncated = 0, false
    for _, token in ipairs(tokens) do
        if token == ">" then direct = true else
            local found, seen = {}, {}
            for _, root in ipairs(roots) do
                for _, inst in ipairs(direct and root:GetChildren() or root:GetDescendants()) do
                    scanned = scanned + 1
                    if scanned > 30000 then truncated = true; break end
                    if not seen[inst] and matches(inst, token) then
                        seen[inst] = true; table.insert(found, inst)
                        if #found >= limit then truncated = true; break end
                    end
                end
                if truncated then break end
            end
            roots, direct = found, false
        end
    end
    local output = {}; for _, inst in ipairs(roots) do table.insert(output, ref(inst)) end
    return {instances = output, truncated = truncated, scanned = scanned}
end
handlers.tree = function(a)
    local budget = math.clamp(tonumber(a.limit) or 100, 1, 500)
    local maxDepth = math.clamp(tonumber(a.depth) or 3, 0, 8)
    local function walk(inst, depth)
        budget = budget - 1
        local node = ref(inst); node.children = {}
        local children = inst:GetChildren(); node.child_count = #children
        if depth < maxDepth then
            for _, child in ipairs(children) do
                if budget <= 0 then break end
                table.insert(node.children, walk(child, depth + 1))
            end
        end
        node.truncated = #node.children < #children
        return node
    end
    return walk(resolve(a.root), 0)
end
handlers.properties = function(a)
    local inst = resolve(a.target); local result = ref(inst)
    result.attributes = serialize(inst:GetAttributes()); result.properties = {}
    for _, name in ipairs(a.names or {"Name", "ClassName", "Parent"}) do
        local ok, value = pcall(function() return inst[name] end)
        result.properties[name] = ok and serialize(value) or {error = tostring(value)}
    end
    return result
end
handlers.set_property = function(a) local inst = resolve(a.target); inst[a.name] = decode(a.value); return ref(inst) end
handlers.set_attribute = function(a) local inst = resolve(a.target); inst:SetAttribute(a.name, decode(a.value)); return ref(inst) end
local function source(inst)
    assert(inst:IsA("LuaSourceContainer"), "Target is not a script")
    local ok, text = pcall(function() return inst.Source end)
    if ok and type(text) == "string" then return text, "source" end
    assert(type(decompile) == "function", "Source unavailable; this runtime has no decompiler")
    return decompile(inst), "decompiled"
end
handlers.read_script = function(a)
    local inst = resolve(a.target); local text, origin = source(inst)
    local first = math.max(1, tonumber(a.start_line) or 1)
    local count = math.clamp(tonumber(a.line_count) or 120, 1, 300)
    local lines, number = {}, 0
    for line in (text .. "\n"):gmatch("(.-)\n") do
        number = number + 1
        if number >= first and number < first + count then table.insert(lines, line) end
    end
    return {script = ref(inst), origin = origin, start_line = first, total_lines = number,
        source = table.concat(lines, "\n"):sub(1, 30000)}
end
handlers.inspect_scripts = function(a)
    local scripts = {}
    for _, inst in ipairs(resolve(a.root):GetDescendants()) do
        if inst:IsA("LuaSourceContainer") then table.insert(scripts, inst) end
    end
    table.sort(scripts, function(x, y) return x:GetFullName() < y:GetFullName() end)
    local offset = math.max(0, tonumber(a.offset) or 0)
    local limit = math.clamp(tonumber(a.limit) or 20, 1, 20)
    local result = {}
    for i = offset + 1, math.min(#scripts, offset + limit) do
        local item = ref(scripts[i])
        if a.include_source then
            local ok, text, origin = pcall(source, scripts[i])
            if ok then item.source = text:sub(1, 4000); item.origin = origin; item.truncated = #text > 4000
            else item.error = tostring(text) end
        end
        table.insert(result, item)
    end
    return {scripts = result, total = #scripts, next_offset = offset + #result, truncated = offset + #result < #scripts}
end
handlers.search_sources = function(a)
    a.include_source = false
    local batch = handlers.inspect_scripts(a)
    local found = {}
    for _, item in ipairs(batch.scripts) do
        local ok, text = pcall(source, resolve(item.ref))
        if ok then
            local index = text:lower():find((a.query or ""):lower(), 1, true)
            if index then
                item.offset = index
                item.source = text:sub(math.max(1, index - 120), index + 600)
                table.insert(found, item)
            end
        else item.error = tostring(text) end
    end
    batch.scripts = found; batch.scope = "Literal search across full sources in this paginated batch"
    return batch
end
handlers.execute = function(a)
    assert(type(loadstring) == "function", "Code execution unsupported")
    local fn, err = loadstring(a.code or ""); assert(fn, err)
    if a.wait_result == false then
        task.spawn(function() local ok, result = pcall(fn); if not ok then event("error", result) end end)
        return {scheduled = true}
    end
    return serialize(fn())
end
handlers.click = function(a)
    local button = resolve(a.target); assert(button:IsA("GuiButton"), "GuiButton required")
    assert(button.Visible and button.AbsoluteSize.X > 0 and button.AbsoluteSize.Y > 0, "Button is not visible")
    local position = button.AbsolutePosition + button.AbsoluteSize / 2
    local screen = button:FindFirstAncestorWhichIsA("ScreenGui")
    if screen and not screen.IgnoreGuiInset then position = position + game:GetService("GuiService"):GetGuiInset() end
    local input = game:GetService("VirtualInputManager")
    input:SendMouseButtonEvent(position.X, position.Y, 0, true, game, 0)
    input:SendMouseButtonEvent(position.X, position.Y, 0, false, game, 0)
    return {clicked = ref(button)}
end
handlers.type_text = function(a)
    local box = resolve(a.target); assert(box:IsA("TextBox"), "TextBox required")
    box:CaptureFocus(); box.Text = a.text or ""; box:ReleaseFocus(a.submit == true)
    return {target = ref(box), text = box.Text, submitted = a.submit == true}
end
local function cobalt()
    local c = env.Cobalt
    assert(c and c.shared and c.shared.Logs, "Load a trusted Cobalt copy explicitly before using remote spy")
    return c
end
handlers.remote_logs = function(a)
    local logs = cobalt().shared.Logs
    local rows = {}
    for _, direction in ipairs({"Outgoing", "Incoming"}) do
        if not a.direction or a.direction == "Both" or direction == a.direction then
            for inst, log in pairs(logs[direction] or {}) do
                if typeof(inst) == "Instance" and inst.Name:lower():find((a.filter or ""):lower(), 1, true) then
                    local calls = {}
                    if not a.summary_only then
                        for i = math.max(1, #log.Calls - 2), #log.Calls do
                            table.insert(calls, serialize(log.Calls[i].Arguments))
                        end
                    end
                    table.insert(rows, {remote = ref(inst), direction = direction, count = #log.Calls,
                        blocked = log.Blocked, ignored = log.Ignored, calls = calls})
                end
                if #rows >= math.clamp(tonumber(a.limit) or 20, 1, 100) then return rows end
            end
        end
    end
    return rows
end
handlers.remote_rule = function(a)
    local inst = resolve(a.target)
    local logs = cobalt().shared.Logs[a.direction or "Outgoing"]
    assert(logs and logs[inst], "Remote has not been logged in that direction")
    local log = logs[inst]
    if a.blocked ~= nil and (log.Blocked == true) ~= a.blocked then log:Block() end
    if a.ignored ~= nil and (log.Ignored == true) ~= a.ignored then log:Ignore() end
    return {remote = ref(inst), blocked = log.Blocked, ignored = log.Ignored}
end
handlers.fire_remote = function(a)
    local inst = resolve(a.target); local args = {}; local values = a.arguments or {}
    for i, value in ipairs(values) do args[i] = decode(value) end
    if inst:IsA("RemoteEvent") then inst:FireServer(unpack(args, 1, #values)); return {sent = true} end
    assert(inst:IsA("RemoteFunction"), "RemoteEvent or RemoteFunction required")
    return serialize(inst:InvokeServer(unpack(args, 1, #values)))
end

env.WYATT_BRIDGE_STOP = function()
    running = false
    for _, connection in ipairs(connections) do connection:Disconnect() end
    if socket then pcall(function() socket:Close() end) end
end
register()
table.insert(connections, game:GetService("LogService").MessageOut:Connect(function(message, kind) event(kind, message) end))
task.spawn(function()
    while running do
        pcall(register)
        if not socket and caps().websocket then
            local ok, ws = pcall(WebSocket.connect, "ws://127.0.0.1:28431/ingest")
            if ok then socket = ws end
        end
        task.wait(10)
    end
end)
task.spawn(function()
    while running do
        task.wait(0.3)
        if #eventQueue > 0 then
            local batch = eventQueue; eventQueue = {}
            local body = {client_id = clientId, events = batch}
            local ok = false
            if socket then ok = pcall(function() socket:Send(Http:JSONEncode(body)) end) end
            if not ok then
                if socket then pcall(function() socket:Close() end); socket = nil end
                pcall(send, "/events", body)
            end
        end
    end
end)
task.spawn(function()
    while running do
        local ok, payload = pcall(send, "/task?client_id=" .. clientId)
        if ok and payload.task and running then
            local command = payload.task
            local fn = handlers[command.operation]
            local success, output = pcall(function() assert(fn, "Unsupported operation"); return fn(command.args or {}) end)
            local body = {client_id = clientId, id = command.id, ok = success, output = output}
            local encoded, text = pcall(Http.JSONEncode, Http, body)
            if not encoded or #text > 220000 then body.output = "Result too large or not serializable; narrow the request"; body.ok = false end
            pcall(send, "/result", body)
        elseif not ok then task.wait(2) end
    end
end)
print("Wyatt bridge connected: " .. clientId)
