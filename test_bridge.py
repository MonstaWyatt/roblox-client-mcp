import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from bridge import Broker, Busy, create_server


class BrokerTests(unittest.TestCase):
    def test_correlated_result_and_concurrent_rejection(self):
        broker = Broker()
        with ThreadPoolExecutor() as pool:
            result = pool.submit(broker.execute, "return 'hello'", 2)
            task = broker.poll(1)
            self.assertEqual(task["code"], "return 'hello'")
            self.assertIsNone(broker.poll(0))
            with self.assertRaises(Busy):
                broker.execute("second")
            self.assertFalse(broker.complete("wrong-id", {}))
            self.assertTrue(broker.complete(task["id"], {"ok": True, "output": "hello"}))
            self.assertEqual(result.result(), {"ok": True, "output": "hello"})
            self.assertFalse(broker.complete(task["id"], {}))

    def test_expired_result_cannot_complete_new_task(self):
        broker = Broker()
        with ThreadPoolExecutor() as pool:
            old = pool.submit(broker.execute, "old", 0.05)
            task = broker.poll(1)
            with self.assertRaises(TimeoutError):
                old.result()
            new = pool.submit(broker.execute, "new", 2)
            current = broker.poll(1)
            self.assertFalse(broker.complete(task["id"], {"output": "old"}))
            self.assertTrue(broker.complete(current["id"], {"output": "new"}))
            self.assertEqual(new.result()["output"], "new")


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def call(self, path, data=None, extra=None):
        headers = {"Content-Type": "application/json"}
        headers.update(extra or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            conn.request("POST" if data is not None else "GET", path,
                         json.dumps(data) if data is not None else None, headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_listener_is_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_browser_and_host_rejected(self):
        self.assertEqual(self.call("/task", extra={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.call("/task", extra={"Host": "example.com"})[0], 403)

    def test_invalid_and_oversized_body(self):
        self.assertEqual(self.call("/execute", {"code": 3})[0], 400)
        self.assertEqual(self.call("/execute", {"code": "a" * 262144})[0], 400)

    def test_tokenless_roundtrip_and_wrong_task_id(self):
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(self.call, "/execute", {"code": "return 'ok'"})
            status, payload = self.call("/task")
            self.assertEqual(status, 200)
            task = payload["task"]
            self.assertEqual(self.call("/result", {"id": "wrong", "ok": True, "output": "fake"})[0], 409)
            self.assertEqual(self.call("/result", {"id": task["id"], "ok": True, "output": "ok"})[0], 200)
            self.assertEqual(pending.result(), (200, {"ok": True, "output": "ok"}))


if __name__ == "__main__":
    unittest.main()
