"""Loopback relay. Executes no game code or OS commands."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Busy(Exception):
    pass


class Broker:
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = None

    def execute(self, code, timeout=20):
        with self.condition:
            if self.pending is not None:
                raise Busy("Another command is active")
            task = {"id": secrets.token_hex(16), "code": code, "delivered": False}
            self.pending = task
            self.condition.notify_all()
            try:
                if not self.condition.wait_for(lambda: "result" in task, timeout):
                    raise TimeoutError("No result before deadline; client execution may still be running")
                return task["result"]
            finally:
                self.pending = None

    def poll(self, timeout=10):
        with self.condition:
            if not self.condition.wait_for(
                lambda: self.pending is not None and not self.pending["delivered"], timeout
            ):
                return None
            self.pending["delivered"] = True
            return {key: self.pending[key] for key in ("id", "code")}

    def complete(self, task_id, result):
        with self.condition:
            task = self.pending
            if (task is None or task["id"] != task_id or not task["delivered"]
                    or "result" in task):
                return False
            task["result"] = result
            self.condition.notify_all()
            return True


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        pass

    def reply(self, status, data):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(encoded)
        except OSError:
            pass

    def allowed_request(self):
        if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                or self.headers.get("Origin") is not None):
            self.reply(403, {"error": "Host or Origin rejected"})
            return False
        return True

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("JSON required")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 262144:
            raise ValueError("Body must be between 1 and 262144 bytes")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def do_GET(self):
        if self.path != "/task":
            self.reply(404, {"error": "Unknown route"})
        elif self.allowed_request():
            self.reply(200, {"task": self.server.broker.poll()})

    def do_POST(self):
        if self.path not in ("/execute", "/result"):
            self.reply(404, {"error": "Unknown route"})
            return
        if not self.allowed_request():
            return
        try:
            data = self.body()
            if self.path == "/execute":
                code = data.get("code")
                if not isinstance(code, str) or not code.strip():
                    raise ValueError("Nonempty code required")
                self.reply(200, self.server.broker.execute(code))
            else:
                if not isinstance(data.get("id"), str) or not isinstance(data.get("output"), str):
                    raise ValueError("String id and output required")
                if type(data.get("ok")) is not bool:
                    raise ValueError("Boolean ok required")
                accepted = self.server.broker.complete(data["id"], {"ok": data["ok"], "output": data["output"]})
                self.reply(200 if accepted else 409, {"accepted": accepted})
        except Busy as exc:
            self.reply(409, {"error": str(exc)})
        except TimeoutError as exc:
            self.reply(504, {"error": str(exc)})
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {"error": str(exc)})


def create_server(port=28430):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.broker = Broker()
    return server


if __name__ == "__main__":
    server = create_server()
    print("Roblox bridge listening on 127.0.0.1:28430", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
