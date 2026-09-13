"""Client routing, bounded event history, and a confined local script library."""
import re
import threading
import time
from collections import deque
from pathlib import Path
from bridge import Broker

READ_TOOLS = {'info', 'search_instances', 'tree', 'properties', 'inspect_scripts', 'read_script', 'search_sources', 'remote_logs', 'capabilities'}
WRITE_TOOLS = {'execute', 'set_property', 'set_attribute', 'click', 'type_text', 'fire_remote', 'remote_rule'}
OTHER_TOOLS = set()


class Sessions:
    def __init__(self, clock=time.monotonic):
        self.lock = threading.RLock()
        self.clock = clock
        self.clients = {}
        self.active = None
        self.actions = False
        self.events = deque(maxlen=1000)
        self.sequence = 0

    def prune(self):
        for key, client in list(self.clients.items()):
            if self.clock() - client['seen'] > 45:
                del self.clients[key]
        if self.active not in self.clients:
            self.active = next(iter(self.clients), None)

    def register(self, data):
        key = data.get('client_id')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key):
            raise ValueError('Valid client_id required')
        with self.lock:
            self.prune()
            if key not in self.clients:
                if len(self.clients) >= 16:
                    raise ValueError('Client limit reached')
                self.clients[key] = {'broker': Broker(), 'seen': self.clock(), 'metadata': {}}
            self.clients[key]['seen'] = self.clock()
            self.clients[key]['metadata'] = {k: data.get(k) for k in ('place_id', 'job_id', 'name', 'capabilities')}
            if self.active is None:
                self.active = key
            return {'client_id': key, 'active': self.active, 'actions_enabled': self.actions}

    def get(self, key=None, touch=False):
        with self.lock:
            self.prune()
            key = key or self.active
            if key not in self.clients:
                raise ValueError('No matching client connected')
            if touch:
                self.clients[key]['seen'] = self.clock()
            return key, self.clients[key]['broker']

    def listing(self):
        with self.lock:
            self.prune()
            return {'active': self.active, 'actions_enabled': self.actions, 'clients': [
                {'client_id': key, **c['metadata'], 'role': 'primary' if key == self.active else 'secondary'}
                for key, c in self.clients.items()]}

    def select(self, key):
        with self.lock:
            self.get(key)
            self.active = key
            return self.listing()

    def dispatch(self, operation, args, key=None):
        if operation not in READ_TOOLS | WRITE_TOOLS | OTHER_TOOLS:
            raise ValueError('Unknown operation')
        with self.lock:
            if operation in WRITE_TOOLS and not self.actions:
                raise ValueError('Observation mode: enable actions explicitly before modifying the game')
            key, broker = self.get(key)
        result = broker.execute({'operation': operation, 'args': args}, timeout=25)
        return {'client_id': key, **result}

    def add_events(self, key, events):
        self.get(key, touch=True)
        if not isinstance(events, list) or len(events) > 100:
            raise ValueError('At most 100 events per batch')
        with self.lock:
            for event in events:
                if not isinstance(event, dict):
                    continue
                self.sequence += 1
                self.events.append({'sequence': self.sequence, 'client_id': key,
                                    'level': str(event.get('level', 'info'))[:40],
                                    'message': str(event.get('message', ''))[:8000], 'time': time.time()})

    def read_events(self, after=0, key=None):
        with self.lock:
            return {'cursor': self.sequence, 'events': [e for e in self.events if e['sequence'] > after
                    and (key is None or e['client_id'] == key)],
                    'dropped': bool(self.events and after and after < self.events[0]['sequence'] - 1)}


class ScriptHub:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def file(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
            raise ValueError('Use a simple script name: letters, numbers, underscores, or hyphens')
        if name.upper() in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(COM|LPT)[0-9]', name.upper()):
            raise ValueError('Reserved Windows filename')
        result = (self.root / (name + '.lua')).resolve()
        if result.parent != self.root:
            raise ValueError('Script path escapes library')
        return result

    def save(self, name, code, overwrite=False):
        if not isinstance(code, str) or len(code.encode()) > 200000:
            raise ValueError('Script must be text under 200 KB')
        with self.file(name).open('w' if overwrite else 'x', encoding='utf-8') as file:
            file.write(code)
        return {'saved': name}

    def load(self, name):
        return self.file(name).read_text(encoding='utf-8')

    def list(self):
        return sorted(p.stem for p in self.root.glob('*.lua') if not p.is_symlink())
