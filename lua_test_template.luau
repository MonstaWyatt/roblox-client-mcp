local function instance(name, class, parent, source)
    local item = {Name = name, ClassName = class, Parent = parent, Source = source, children = {}, attrs = {}, _instance = true}
    if parent then table.insert(parent.children, item) end
    function item:IsA(kind)
        return kind == self.ClassName or (kind == 'LuaSourceContainer' and (self.ClassName == 'LocalScript' or self.ClassName == 'ModuleScript'))
    end
    function item:GetFullName() return self.Parent and self.Parent:GetFullName() .. '.' .. self.Name or self.Name end
    function item:GetChildren() return self.children end
    function item:GetDescendants()
        local out = {}
        for _, child in ipairs(self.children) do
            table.insert(out, child)
            for _, nested in ipairs(child:GetDescendants()) do table.insert(out, nested) end
        end
        return out
    end
    function item:FindFirstChild(name) for _, child in ipairs(self.children) do if child.Name == name then return child end end end
    function item:GetAttributes() return self.attrs end
    function item:GetAttribute(name) return self.attrs[name] end
    function item:SetAttribute(name, value) self.attrs[name] = value end
    return item
end
local game = instance('game', 'DataModel')
local workspace = instance('Workspace', 'Workspace', game)
local part = instance('Ball', 'Part', workspace); part.attrs.Team = 'Blue'
local script = instance('Rewards', 'LocalScript', workspace, 'local coins = 10\nreturn coins')
local remote = instance('Award', 'RemoteEvent', workspace)
function remote:FireServer(...) self.sent = {...} end
local functionRemote = instance('Query', 'RemoteFunction', workspace)
function functionRemote:InvokeServer(...) return 12 end
local services = {HttpService = {GenerateGUID = function() return 'mock-client' end}, Players = {}}
function game:GetService(name) return services[name] end
local env = {Cobalt = {shared = {Logs = {Outgoing = {}, Incoming = {}}}}}
local log = {Calls = {{Arguments = {'coin', 2}}}, Blocked = false, Ignored = false}
function log:Block() self.Blocked = not self.Blocked end
function log:Ignore() self.Ignored = not self.Ignored end
env.Cobalt.shared.Logs.Outgoing[remote] = log
local sandbox = setmetatable({game = game, getgenv = function() return env end, request = function() end,
    typeof = function(value) if type(value) == 'table' and value._instance then return 'Instance' end return typeof(value) end}, {__index = getfenv()})
local all, compileError = loadstring(FULL_SOURCE)
assert(all, compileError)
local prefix = assert(loadstring(HANDLER_SOURCE .. '\nreturn handlers'))
setfenv(prefix, sandbox)
local handlers = prefix()
local found = handlers.search_instances({selector = 'Workspace > Part[@Team=Blue]'})
assert(#found.instances == 1 and found.instances[1].name == 'Ball', 'selector failed')
local id = found.instances[1].ref
assert(handlers.properties({target = id}).attributes.Team == 'Blue')
handlers.set_attribute({target = id, name = 'Team', value = 'Red'})
assert(part.attrs.Team == 'Red')
assert(handlers.tree({root = 'Workspace', depth = 0}).truncated)
local read = handlers.read_script({target = 'Workspace.Rewards', start_line = 2, line_count = 1})
assert(read.source == 'return coins' and read.total_lines == 2, 'script range failed')
assert(#handlers.search_sources({query = 'coins'}).scripts == 1)
assert(handlers.execute({code = 'return 42'}) == 42)
handlers.fire_remote({target = 'Workspace.Award', arguments = {3}})
assert(remote.sent[1] == 3)
assert(handlers.fire_remote({target = 'Workspace.Query'}) == 12)
assert(#handlers.remote_logs({}) == 1)
handlers.remote_rule({target = 'Workspace.Award', blocked = true, ignored = true})
assert(log.Blocked and log.Ignored)
handlers.remote_rule({target = 'Workspace.Award', blocked = true, ignored = true})
assert(log.Blocked and log.Ignored, 'rule should be idempotent')
print('Lua connector syntax and mocked inspection/execution/remote behavior passed')
