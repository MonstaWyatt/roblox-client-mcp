import asyncio
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from features import Sessions, ScriptHub
from service import feature_server
from log_stream import create_log_server
from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sessions = Sessions(lambda: self.now)
        for name in ('first', 'second'):
            self.sessions.register({'client_id': name, 'place_id': name})

    def test_observation_mode_rejects_every_mutating_tool(self):
        from features import WRITE_TOOLS
        for operation in WRITE_TOOLS:
            with self.assertRaisesRegex(ValueError, 'Observation mode'):
                self.sessions.dispatch(operation, {})

    def test_client_isolation(self):
        with ThreadPoolExecutor() as pool:
            first = pool.submit(self.sessions.dispatch, 'info', {}, 'first')
            second = pool.submit(self.sessions.dispatch, 'tree', {}, 'second')
            a = self.sessions.get('first')[1]
            b = self.sessions.get('second')[1]
            ta, tb = a.poll(1), b.poll(1)
            self.assertFalse(b.complete(ta['id'], {'ok': True}))
            a.complete(ta['id'], {'ok': True, 'output': 'a'})
            b.complete(tb['id'], {'ok': True, 'output': 'b'})
            self.assertEqual(first.result()['client_id'], 'first')
            self.assertEqual(second.result()['client_id'], 'second')

    def test_primary_client_promotion_and_reconnect(self):
        self.now = 30
        self.sessions.get('second', touch=True)
        self.now = 46
        self.assertEqual(self.sessions.listing()['active'], 'second')
        self.sessions.register({'client_id': 'first'})
        self.assertEqual(self.sessions.select('first')['active'], 'first')

    def test_logs_are_bounded_and_filtered(self):
        for i in range(11):
            self.sessions.add_events('first', [{'message': str(i)} for _ in range(100)])
        self.sessions.add_events('second', [{'message': 'other'}])
        result = self.sessions.read_events(1, 'first')
        self.assertTrue(result['dropped'])
        self.assertLessEqual(len(result['events']), 1000)
        self.assertTrue(all(e['client_id'] == 'first' for e in result['events']))

    def test_script_hub_confines_paths_and_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = ScriptHub(directory)
            hub.save('hello', 'return 1')
            self.assertEqual(hub.load('hello'), 'return 1')
            with self.assertRaises(FileExistsError): hub.save('hello', 'return 2')
            for name in ('../escape', 'C:/escape', '', 'CON/x', 'a.lua'):
                with self.assertRaises(ValueError): hub.save(name, 'x')
            hub.save('hello', 'return 3', True)
            self.assertEqual(hub.list(), ['hello'])


class FeatureHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = feature_server(0, self.temp.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def call(self, route, data=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            conn.request('POST' if data is not None else 'GET', route,
                json.dumps(data) if data is not None else None, {'Content-Type': 'application/json'})
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read())
        finally: conn.close()

    def test_registration_route_and_action_gate(self):
        self.assertEqual(self.call('/register', {'client_id': 'sample'})[0], 200)
        self.assertEqual(self.call('/execute', {'code': 'return 1'})[0], 400)
        self.call('/mode', {'actions': True})
        with ThreadPoolExecutor() as pool:
            future = pool.submit(self.call, '/execute', {'code': 'return 1', 'client_id': 'sample'})
            status, poll = self.call('/task?client_id=sample')
            self.assertEqual(status, 200)
            self.assertEqual(poll['task']['operation'], 'execute')
            self.call('/result', {'client_id': 'sample', 'id': poll['task']['id'], 'ok': True, 'output': 1})
            self.assertEqual(future.result()[1]['output'], 1)
        self.assertEqual(self.call('/clients')[1]['active'], 'sample')

    def test_script_save_load_and_no_execution_in_observation_mode(self):
        self.call('/scripts/save', {'name': 'one', 'code': 'return 1'})
        self.assertEqual(self.call('/scripts/load', {'name': 'one'})[1]['code'], 'return 1')
        self.assertEqual(self.call('/scripts/run', {'name': 'one'})[0], 400)


class WebsocketTests(unittest.TestCase):
    def test_stream_ingress_and_origin_rejection(self):
        sessions = Sessions()
        sessions.register({'client_id': 'logs'})
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with create_log_server(sessions, port) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with self.assertRaises(InvalidStatus):
                    with connect(f'ws://127.0.0.1:{port}/events', origin='https://example.com', proxy=None): pass
                with connect(f'ws://127.0.0.1:{port}/ingest', proxy=None) as ingest:
                    ingest.send(json.dumps({'client_id': 'logs', 'events': [{'message': 'hello'}]}))
                    with connect(f'ws://127.0.0.1:{port}/events', proxy=None) as stream:
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            event = json.loads(stream.recv(timeout=2))
                            if event['events']:
                                self.assertEqual(event['events'][0]['message'], 'hello')
                                break
                        else: self.fail('No streamed event')
            finally: server.shutdown(); thread.join()


class SemanticTests(unittest.TestCase):
    def test_embedding_ranking_uses_local_endpoint(self):
        from semantic import semantic_rank
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"embeddings":[[1,0],[0,1],[1,0]]}'
        class Opener:
            def open(self, request, timeout):
                assert request.full_url == 'http://127.0.0.1:11434/api/embed'
                return Response()
        with patch('semantic.build_opener', return_value=Opener()):
            result = semantic_rank('rewards', [{'path': 'a', 'source': 'camera'}, {'path': 'b', 'source': 'coins'}])
        self.assertEqual(result['matches'][0]['path'], 'b')


class McpTests(unittest.TestCase):
    def test_real_stdio_handshake_and_schemas(self):
        async def check():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=sys.executable, args=[str(Path('agent_server.py').resolve())])
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertEqual(len(names), 26)
                    self.assertTrue({'screenshot', 'remote_spy', 'semantic_search', 'run_script'} <= names)
        asyncio.run(check())



class FailoverTests(unittest.TestCase):
    def test_two_bridge_processes_promote_without_replaying(self):
        from urllib.request import build_opener, ProxyHandler
        opener = build_opener(ProxyHandler({}))
        ports = []
        for _ in range(2):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); ports.append(probe.getsockname()[1])
        command = [sys.executable, '-c', f'from service import run; run({ports[0]}, {ports[1]})']
        primary = secondary = None
        def healthy():
            try:
                with opener.open(f'http://127.0.0.1:{ports[0]}/health', timeout=0.5) as response:
                    return json.loads(response.read()).get('service') == 'wyatt-roblox'
            except OSError: return False
        def wait_health():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if healthy(): return
                time.sleep(0.1)
            self.fail('Bridge did not become healthy')
        try:
            primary = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_health()
            secondary = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.6)
            self.assertIsNone(secondary.poll())
            primary.terminate(); primary.wait(timeout=5)
            wait_health()
            self.assertIsNone(secondary.poll())
        finally:
            for process in (primary, secondary):
                if process and process.poll() is None:
                    process.terminate(); process.wait(timeout=5)


class CaptureTests(unittest.TestCase):
    def test_capture_rejects_unlisted_window(self):
        from windows_capture import capture
        with patch('windows_capture.windows', return_value=[]):
            with self.assertRaises(ValueError): capture(123)

    def test_capture_returns_png_for_selected_window(self):
        from windows_capture import capture
        from PIL import Image
        with patch('windows_capture.windows', return_value=[{'hwnd': 123}]), patch('windows_capture.ctypes.windll') as windll, patch('PIL.ImageGrab.grab', return_value=Image.new('RGB', (10, 10))) as grab:
            windll.user32.IsIconic.return_value = 0
            self.assertTrue(capture(123).startswith(bytes([137, 80, 78, 71])))
            grab.assert_called_once_with(window=123)


if __name__ == '__main__': unittest.main()
