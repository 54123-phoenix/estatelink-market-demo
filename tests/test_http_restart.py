"""Exercise persistence across an actual HTTP server shutdown and reopening."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet
from demo.server import make_server


class HttpRestartTests(unittest.TestCase):
    def test_all_scenes_survive_server_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Fernet.generate_key()
            path = Path(folder) / "restart.sqlite3"

            def start():
                server = make_server(port=0, key=key, db_path=path)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                return server, thread

            def stop(server, thread):
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            def request(server, endpoint, body=None):
                data = json.dumps(body).encode() if body is not None else None
                req = Request(f"http://127.0.0.1:{server.server_port}" + endpoint,
                              data=data, headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=5) as response:
                    return json.load(response)

            server, thread = start()
            try:
                uid = request(server, "/api/users/add", {
                    "name": "重启演示客户", "phone": "10000008888",
                    "game": "CS2", "account": "restart-demo-account",
                })["userId"]
                prefix = f"/api/archive/users/{uid}"
                request(server, prefix + "/assets", {"name": "重启测试道具", "quantity": 3})
                request(server, prefix + "/contracts", {"number": "RESTART-001", "name": "演示合同"})
                qid = request(server, "/api/sms/send", {"userId": uid, "content": "虚构核验"})["inquiryId"]
                request(server, "/api/mobile/reply", {"inquiryId": qid, "answer": "yes"})
                for action in ("reset", "list", "buyer", "hold"):
                    request(server, "/api/market/flow", {"userId": 3, "assetType": "account", "action": action})
                expected = {suffix: request(server, prefix + suffix) for suffix in ("", "/assets", "/contracts")}
                expected_flow = request(server, "/api/market/overview")["flows"]["3:account"]
            finally:
                stop(server, thread)

            server, thread = start()
            try:
                for suffix, response in expected.items():
                    self.assertEqual(request(server, prefix + suffix), response)
                messages = request(server, f"/api/mobile/messages?userId={uid}")["messages"]
                self.assertEqual(messages[0]["answer"], "yes")
                self.assertEqual(messages[0]["status"], "answered")
                self.assertEqual(request(server, "/api/market/overview")["flows"]["3:account"], expected_flow)
                self.assertEqual(len(request(server, "/api/users")["users"]), 13)
            finally:
                stop(server, thread)


if __name__ == "__main__":
    unittest.main()
