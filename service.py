"""Feature service and primary/secondary localhost failover."""
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler
from bridge import Handler, Busy, create_server
from features import Sessions, ScriptHub
from log_stream import create_log_server


class FeatureHandler(Handler):
    def do_GET(self):
        if not self.allowed_request():
            return
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        key = params.get('client_id', [None])[0]
        try:
            if url.path == '/health':
                self.reply(200, {'service': 'wyatt-roblox', 'protocol': 2, 'role': 'primary'})
            elif url.path == '/clients':
                self.reply(200, self.server.sessions.listing())
            elif url.path == '/task':
                if not key:
                    raise ValueError('client_id required; register the updated client first')
                _, broker = self.server.sessions.get(key, touch=True)
                task = broker.poll()
                if task:
                    command = task.pop('code')
                    task.update(command)
                self.reply(200, {'task': task})
            elif url.path == '/events':
                self.reply(200, self.server.sessions.read_events(int(params.get('after', ['0'])[0]), key))
            elif url.path == '/scripts':
                self.reply(200, {'scripts': self.server.hub.list()})
            elif url.path == '/client.lua':
                data = Path(__file__).with_name('client.lua').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.reply(404, {'error': 'Unknown route'})
        except (ValueError, KeyError, OSError) as exc:
            self.reply(400, {'error': str(exc)})

    def do_POST(self):
        if not self.allowed_request():
            return
        try:
            data = self.body()
            key = data.get('client_id')
            sessions = self.server.sessions
            if self.path == '/register':
                result = sessions.register(data)
            elif self.path == '/heartbeat':
                sessions.get(key, touch=True)
                result = {'ok': True}
            elif self.path == '/select':
                result = sessions.select(key)
            elif self.path == '/mode':
                if type(data.get('actions')) is not bool:
                    raise ValueError('Boolean actions required')
                with sessions.lock:
                    sessions.actions = data['actions']
                result = {'actions_enabled': sessions.actions}
            elif self.path in ('/tool', '/execute'):
                operation = 'execute' if self.path == '/execute' else data.get('operation')
                args = {'code': data.get('code')} if self.path == '/execute' else data.get('args', {})
                if not isinstance(args, dict):
                    raise ValueError('Object args required')
                result = sessions.dispatch(operation, args, key)
            elif self.path == '/result':
                if not key or not isinstance(data.get('id'), str) or type(data.get('ok')) is not bool:
                    raise ValueError('client_id, id, and boolean ok required')
                _, broker = sessions.get(key, touch=True)
                accepted = broker.complete(data['id'], {'ok': data['ok'], 'output': data.get('output')})
                self.reply(200 if accepted else 409, {'accepted': accepted})
                return
            elif self.path == '/events':
                sessions.add_events(key, data.get('events'))
                result = {'ok': True}
            elif self.path == '/scripts/save':
                result = self.server.hub.save(data.get('name'), data.get('code'), data.get('overwrite') is True)
            elif self.path == '/scripts/load':
                result = {'code': self.server.hub.load(data.get('name'))}
            elif self.path == '/scripts/run':
                result = sessions.dispatch('execute', {'code': self.server.hub.load(data.get('name'))}, key)
            else:
                self.reply(404, {'error': 'Unknown route'})
                return
            self.reply(200, result)
        except Busy as exc:
            self.reply(409, {'error': str(exc)})
        except TimeoutError as exc:
            self.reply(504, {'error': str(exc), 'retry_safe': False})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.reply(400, {'error': str(exc)})


def feature_server(port=28430, hub_root=None):
    server = create_server(port)
    server.RequestHandlerClass = FeatureHandler
    server.sessions = Sessions()
    server.hub = ScriptHub(hub_root or Path(__file__).with_name('script_library'))
    return server


def run(port=28430, log_port=28431):
    opener = build_opener(ProxyHandler({}))
    while True:
        try:
            server = feature_server(port)
        except OSError:
            try:
                with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                    if json.loads(response.read()).get('service') != 'wyatt-roblox':
                        raise RuntimeError('Port 28430 belongs to a different application')
            except OSError:
                time.sleep(1)
                continue
            print('Secondary standby: reusing the primary bridge; promotion on disconnect.', flush=True)
            while True:
                time.sleep(2)
                try:
                    with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                        if json.loads(response.read()).get('service') != 'wyatt-roblox':
                            raise RuntimeError('Port owner changed')
                except OSError:
                    break
            continue
        try:
            with create_log_server(server.sessions, log_port) as logs:
                threading.Thread(target=logs.serve_forever, daemon=True).start()
                print(f'Primary bridge: http://127.0.0.1:{port} | live logs: ws://127.0.0.1:{log_port}/events', flush=True)
                try:
                    server.serve_forever()
                finally:
                    logs.shutdown()
        finally:
            server.server_close()
        return
