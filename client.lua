-- Set getgenv().ROBLOX_CLIENT_TOKEN locally before running this client.
-- Keep the control token exclusively in the Python processes.
local env = getgenv()
assert(not env.WYATT_BRIDGE_RUNNING, "Bridge already running in this client")
local token = env.ROBLOX_CLIENT_TOKEN
assert(type(token) == "string" and #token >= 32, "Client token required")
assert(type(request) == "function" and type(loadstring) == "function", "Compatible client runtime required")
local http = game:GetService("HttpService")
local url = "http://127.0.0.1:28430"

local function send(route, method, body)
    local response = request({
        Url = url .. route,
        Method = method,
        Headers = { ["Authorization"] = "Bearer " .. token, ["Content-Type"] = "application/json" },
        Body = body and http:JSONEncode(body) or nil,
    })
    if response.StatusCode == 401 or response.StatusCode == 403 then
        env.WYATT_BRIDGE_RUNNING = false
        error("Bridge authentication rejected")
    end
    assert(response.StatusCode == 200, "Bridge request failed")
    return http:JSONDecode(response.Body)
end

env.WYATT_BRIDGE_RUNNING = true
task.spawn(function()
    while env.WYATT_BRIDGE_RUNNING do
        local connected, payload = pcall(send, "/task", "GET")
        if connected and payload.task then
            local command = payload.task
            local fn, compileError = loadstring(command.code)
            local ok, result = false, compileError
            if fn then ok, result = pcall(fn) end
            local output = tostring(result)
            if #output > 16000 then output = "Output exceeded 16000 bytes; return a smaller result" end
            -- Do not rerun code when submitting a result fails.
            pcall(send, "/result", "POST", { id = command.id, ok = ok, output = output })
        elseif not connected then
            task.wait(2)
        end
    end
end)
