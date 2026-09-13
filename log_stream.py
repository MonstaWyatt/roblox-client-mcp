"""WebSocket ingress and live log subscribers, restricted to loopback."""
import json
import time
from http import HTTPStatus
from urllib.parse import urlsplit, parse_qs
from websockets.sync.server import serve
from websockets.exceptions import ConnectionClosed


def create_log_server(sessions, port=28431):
    def gate(connection, request):
        if request.headers.get('Origin') is not None or request.headers.get('Host') != f'127.0.0.1:{port}':
            return connection.respond(HTTPStatus.FORBIDDEN, 'Host or Origin rejected')
        if urlsplit(request.path).path not in ('/ingest', '/events'):
            return connection.respond(HTTPStatus.NOT_FOUND, 'Unknown route')

    def handler(socket):
        url = urlsplit(socket.request.path)
        try:
            if url.path == '/ingest':
                for message in socket:
                    data = json.loads(message)
                    sessions.add_events(data['client_id'], data['events'])
            else:
                params = parse_qs(url.query)
                cursor = int(params.get('after', ['0'])[0])
                key = params.get('client_id', [None])[0]
                while True:
                    batch = sessions.read_events(cursor, key)
                    socket.send(json.dumps(batch))
                    cursor = batch['cursor']
                    time.sleep(0.25)
        except (ConnectionClosed, ValueError, KeyError, TypeError):
            socket.close()
    return serve(handler, '127.0.0.1', port, process_request=gate, max_size=1000000, origins=[None])
