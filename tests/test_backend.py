import concurrent.futures
from contextlib import closing
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

from demo.server import make_server
from demo.storage import ApiError, Store

BASE = Path(__file__).resolve().parents[1] / "demo"


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.key = Fernet.generate_key()
        self.store = Store(self.path, self.key, auto_interval=10000)

    def create(self, **extra):
        return self.store.create_user({"name": "演示客户", "phone": "10012345678", "game": "虚构游戏", "account": "demo-account-secret", **extra})

    def assert_error(self, code, fn, *args, **kwargs):
        with self.assertRaises(ApiError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    def fixture_dir(self):
        folder = Path(self.temp.name) / "fixtures"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(BASE / "market_catalog.json", folder / "market_catalog.json")
        return folder

    def test_required_key_and_wrong_key_rejected(self):
        with self.assertRaises(RuntimeError):
            Store(Path(self.temp.name) / "missing.db", None)
        with self.assertRaises(RuntimeError):
            Store(Path(self.temp.name) / "invalid.db", "not-a-key")
        with self.assertRaises(RuntimeError):
            Store(self.path, Fernet.generate_key())
        self.assertEqual(len(self.store.users()["users"]), 12)

    def test_ciphertext_tamper_fails_startup(self):
        with self.store.connect(True) as conn:
            conn.execute("UPDATE users SET phone='corrupt-token' WHERE id=1")
        with self.assertRaises(RuntimeError):
            Store(self.path, self.key)

    def test_defaults_optional_limits_and_background_rotation(self):
        uid = self.create(name="单", account="x", emergencyContact="虚"*500)
        user = self.store.get_user(uid)
        self.assertNotEqual(user["name"], "单")
        self.assertNotEqual(user["account"], "x")
        primary = self.store.get_assets(uid)[0]
        self.assertEqual(primary["quantity"], 1)
        self.assertEqual(primary["currency"], "CNY")
        self.assertEqual(primary["disposition"], "inherit")
        self.assertIsNone(primary["costMinor"])
        self.assert_error(400, self.store.patch_asset, primary["id"], {"quantity": 2})
        self.assert_error(400, self.store.patch_asset, primary["id"], {"currency": None})
        self.assert_error(400, self.store.patch_asset, primary["id"], {"disposition": "bad"})
        self.assert_error(400, self.store.patch_user, uid, {"emergencyContact": "虚"*501})
        self.store.sweep(time.time()+10001)
        self.assertEqual(len(self.store.messages(1)["messages"]), 1)
        self.assertEqual(len(self.store.messages(2)["messages"]), 0)
        restarted = Store(self.path, self.key, auto_interval=10000)
        restarted.sweep(time.time()+20002)
        self.assertEqual(len(restarted.messages(2)["messages"]), 1)

    def test_single_primary_and_ownership_constraints(self):
        uid = self.create()
        assets = self.store.get_assets(uid)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["assetType"], "account")
        self.assert_error(409, self.store.create_asset, uid, {"assetType": "account", "name": "duplicate"})
        aid = self.store.create_asset(uid, {"name": "item", "quantity": 2, "costMinor": 300, "currency": "CNY"})
        self.assertEqual(self.store.get_assets(uid)[1]["parentAccountId"], assets[0]["id"])
        self.assert_error(400, self.store.patch_asset, aid, {"userId": 1})
        self.assert_error(400, self.store.patch_asset, aid, {"assetType": "account"})
        self.assert_error(400, self.store.create_asset, uid, {"name": "wrong", "parentAccountId": 1})
        with self.assertRaises(ApiError):
            with self.store.connect(True) as conn:
                self.store.insert(conn, "assets", {"userId": uid, "assetType": "account", "name": "bad", "createdAt": 1, "updatedAt": 1})
        with self.assertRaises(ApiError):
            with self.store.connect(True) as conn:
                self.store.insert(conn, "assets", {"userId": uid, "assetType": "item", "parentAccountId": 1, "name": "bad", "createdAt": 1, "updatedAt": 1})

    def test_unique_id_contract_and_transaction_rollback(self):
        uid = self.create(idCard="000000200001010099")
        before = len(self.store.users()["users"])
        self.assert_error(409, self.create, idCard="000000200001010099")
        self.assertEqual(len(self.store.users()["users"]), before)
        cid = self.store.create_contract(uid, {"number": "DEMO-001", "name": "登记", "status": "active"})
        self.assert_error(409, self.store.create_contract, 1, {"number": "DEMO-001", "name": "another"})
        self.assertEqual(self.store.get_contracts(uid)[0]["id"], cid)
        with self.store.connect() as conn:
            count = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        with self.assertRaises(RuntimeError):
            with self.store.connect(True) as conn:
                self.store.insert_user(conn, {"name": "rollback", "phone": "10000009999", "game": "demo", "account": "rollback"})
                raise RuntimeError("forced failure")
        self.assertEqual(len(self.store.users()["users"]), before)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0], count)

    def test_validation_boundaries_and_whitelists(self):
        bad = [{"phone": "１００１２３４５６７８"}, {"phone": "123"}, {"name": "x"*101}, {"age": True}, {"age": 151}, {"idCard": "x"*18}, {"account": "x"*129}, {"status": "已故"}, {"missedCount": 7}, {"password": "secret"}]
        for data in bad:
            with self.subTest(data=data):
                self.assert_error(400, self.create, **data)
        uid = self.create(age=150)
        for data in ({"name": "item", "quantity": 0}, {"name": "item", "quantity": True}, {"name": "item", "costMinor": -1}, {"name": "item", "currency": "cny"}, {"name": "item", "acquiredAt": "2025-02-29"}, {"name": "item", "notes": "x"*501}):
            self.assert_error(400, self.store.create_asset, uid, data)
        for data in ({"status": "signed"}, {"effectiveDate": "2026-10-20", "expiryDate": "2026-10-19"}, {"effectiveDate": "2026-2-01"}):
            self.assert_error(400, self.store.create_contract, uid, {"number": "D", "name": "n", **data})

    def test_edit_preserves_omitted_and_clears_optional(self):
        uid = self.create(email="fiction@example.invalid", address="虚构街道99号", idCard="000000200001010098", age=20)
        original = self.store.get_user(uid)
        self.store.patch_user(uid, {"gender": "女"})
        current = self.store.get_user(uid)
        self.assertEqual(current["email"], original["email"])
        self.assertEqual(current["name"], original["name"])
        self.store.patch_user(uid, {"email": None, "address": "", "age": None, "idCard": None})
        for key in ("email", "address", "age", "idCard"):
            self.assertIsNone(self.store.get_user(uid)[key])
        self.create(idCard="000000200001010098")
        self.assert_error(400, self.store.patch_user, uid, {"name": None})
        cid = self.store.create_contract(uid, {"number": "KEEP", "name": "keep", "effectiveDate": "2026-01-01", "expiryDate": "2026-12-31"})
        self.assert_error(400, self.store.patch_contract, cid, {"expiryDate": "2025-12-31"})
        self.store.patch_contract(cid, {"expiryDate": None})
        self.assertIsNone(self.store.get_contracts(uid)[0]["expiryDate"])

    def test_persistence_ciphertext_and_redaction(self):
        secrets = {"name": "隐私测试客户", "phone": "10098765432", "idCard": "000000200001010097", "email": "private@example.invalid", "address": "仅测试秘密地址123", "emergencyContact": "秘密联系人10099998888", "account": "ultra-secret-account"}
        uid = self.create(**secrets)
        aid = self.store.create_asset(uid, {"name": "private item", "account": "secret-item-account"})
        self.store.patch_asset(aid, {"notes": "registered"})
        restarted = Store(self.path, self.key)
        self.assertEqual(restarted.get_assets(uid)[1]["notes"], "registered")
        responses = json.dumps([restarted.users(), restarted.get_user(uid), restarted.overview(), restarted.get_assets(uid)])
        for value in [*secrets.values(), "secret-item-account"]:
            self.assertNotIn(value, responses)
        self.assertNotIn('"password"', responses)
        with self.store.connect() as conn:
            dump = "\n".join(conn.iterdump())
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        for value in [*secrets.values(), "secret-item-account"]:
            self.assertNotIn(value, dump)
        self.assertNotIn(self.key.decode(), dump)

    def test_migration_idempotence_status_ids_and_market_state(self):
        folder = self.fixture_dir()
        legacy = {"users": [{"id": 31, "name": "迁移演示", "phone": "10011112222", "game": "Steam 库存", "account": "wq_steam88", "password": "NEVER_IMPORT", "status": "已故", "missedCount": 7}], "nextUserId": 80}
        raw = json.dumps(legacy)
        (folder / "data.json").write_text(raw, encoding="utf-8")
        (folder / "market_state.json").write_text(json.dumps({"revision": 5, "flows": {"31:item": {"listed": True, "buyer": True, "decision": "sell", "scenario": 1}}}), encoding="utf-8")
        path = Path(self.temp.name) / "migrated.db"
        store = Store(path, self.key, folder)
        self.assertEqual(store.get_user(31)["missedCount"], 7)
        self.assertEqual(store.get_user(31)["status"], "已故")
        self.assertEqual(store.overview()["revision"], 5)
        self.assertEqual(store.overview()["flows"]["31:item"]["decision"], "sell")
        self.assertEqual(set(store.overview()["catalog"]["profiles"]), {"31"})
        self.assertEqual(len(store.get_assets(31)), 2)
        self.assertEqual(Store(path, self.key, folder).users()["users"], store.users()["users"])
        self.assertEqual((folder / "data.json").read_text(encoding="utf-8"), raw)
        self.assertEqual(store.create_user({"name": "新客", "phone": "10000000099", "game": "g", "account": "a"}), 80)
        with store.connect() as conn:
            self.assertNotIn("NEVER_IMPORT", "\n".join(conn.iterdump()))

    def test_corrupt_legacy_fails_and_migration_rolls_back(self):
        folder = self.fixture_dir()
        (folder / "data.json").write_text("{broken", encoding="utf-8")
        path = Path(self.temp.name) / "corrupt.db"
        with self.assertRaises(RuntimeError):
            Store(path, self.key, folder)
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM users").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM app_meta").fetchone()[0], 0)
        (folder / "data.json").write_text(json.dumps({"users": [{"id": 1, "name": "有效", "phone": "10011112222", "game": "g", "account": "a"}, {"id": 2, "name": "bad"}]}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            Store(path, self.key, folder)
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_concurrent_verification_and_creation(self):
        def send():
            try:
                return self.store.send_sms(1, "fictional verification")
            except ApiError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: send(), range(8)))
        self.assertEqual(results.count(409), 7)
        qid = next(value for value in results if value != 409)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self.create, phone=f"10012345{i:03d}") for i in range(5)]
            futures.append(pool.submit(self.store.reply, qid, "yes"))
            for future in futures:
                future.result()
        self.assertEqual(len(self.store.users()["users"]), 17)
        self.assertEqual(self.store.get_user(1)["status"], "健在")
        self.assertEqual(self.store.get_user(1)["missedCount"], 0)

    def test_verification_timeout_reply_and_confirmation(self):
        self.store.auto_send(False)
        for index in range(3):
            qid = self.store.send_sms(1, "test")
            self.store.sweep(time.time()+31)
            self.assertEqual(self.store.get_user(1)["missedCount"], index+1)
            self.assert_error(409, self.store.reply, qid, "yes")
        self.assertEqual(self.store.get_user(1)["status"], "疑似已故")
        qid = self.store.send_sms(1, "test")
        self.store.reply(qid, "yes")
        self.assertEqual(self.store.get_user(1)["missedCount"], 0)
        qid = self.store.send_sms(1, "test")
        self.store.reply(qid, "no")
        self.assertEqual(self.store.get_user(1)["status"], "已故")
        qid = self.store.send_sms(2, "test")
        self.store.confirm_dead(2)
        self.assert_error(409, self.store.reply, qid, "yes")
        self.assertEqual(self.store.messages(2)["messages"][0]["status"], "expired")

    def test_market_links_survive_account_change_and_state_machine(self):
        primary = self.store.get_user(3)["mainAccountId"]
        before = self.store.overview()["catalog"]["profiles"]["3"]
        self.store.patch_asset(primary, {"account": "changed-account", "game": "Changed game"})
        self.assertEqual(self.store.overview()["catalog"]["profiles"]["3"], before)
        aid = self.store.create_asset(3, {"name": "new item without market"})
        self.assertFalse(next(a for a in self.store.get_assets(3) if a["id"] == aid)["hasMarket"])
        uid = self.create()
        self.assert_error(404, self.store.market_flow, uid, "item", "list")
        self.store.market_flow(3, "item", "reset")
        self.assert_error(409, self.store.market_flow, 3, "item", "buyer")
        for action in ("list", "buyer", "hold", "revise", "sell", "scenario"):
            result = self.store.market_flow(3, "item", action)
            self.assertTrue(result["ok"])
        self.assert_error(409, self.store.market_flow, 3, "item", "buyout")
        self.assertEqual(Store(self.path, self.key).overview()["flows"]["3:item"]["decision"], "sell")

    def test_http_api_errors_and_shapes(self):
        server = make_server(port=0, db_path=self.path, key=self.key)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        root = f"http://127.0.0.1:{server.server_port}"
        def request(path, body=None, method="GET"):
            req = Request(root+path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"}, method=method)
            try:
                response = urlopen(req, timeout=5)
            except HTTPError as exc:
                response = exc
            with response:
                return response.status, json.load(response)
        self.assertEqual(request("/api/users")[0], 200)
        code, user = request("/api/archive/users/1")
        self.assertEqual(code, 200)
        self.assertEqual(user["id"], 1)
        self.assertNotIn("user", user)
        self.assertIn("assets", request("/api/archive/users/1/assets")[1])
        self.assertIn("contracts", request("/api/archive/users/1/contracts")[1])
        self.assertEqual(request("/api/archive/users/999999")[0], 404)
        self.assertEqual(request("/api/mobile/messages?userId=NaN")[0], 400)
        self.assertEqual(request("/api/users/add", [], "POST")[0], 400)
        self.assertEqual(request("/api/users/add", {"password": "bad"}, "POST")[0], 400)
        self.assertEqual(request("/api/archive/users/1", {"status": "已故"}, "PATCH")[0], 400)
        self.assertEqual(request("/api/save", {}, "POST")[1]["userCount"], 12)
        self.assertIn("自动保存", request("/api/save", {}, "POST")[1]["message"])
        self.assertEqual(request("/api/mobile/messages?userId=999999")[0], 404)
        code, result = request("/api/users/add", {"name": "接口客户", "phone": "10033334444", "game": "API", "account": "api-account"}, "POST")
        self.assertEqual(code, 200)
        uid = result["userId"]
        self.assertEqual(request(f"/api/archive/users/{uid}", {"email": "api@example.invalid"}, "PATCH")[0], 200)
        code, result = request(f"/api/archive/users/{uid}/assets", {"name": "api-item", "quantity": 2}, "POST")
        self.assertEqual(code, 200)
        self.assertEqual(request(f'/api/archive/assets/{result["assetId"]}', {"quantity": 3}, "PATCH")[0], 200)
        code, result = request(f"/api/archive/users/{uid}/contracts", {"name": "api-contract", "number": "API-01"}, "POST")
        self.assertEqual(code, 200)
        self.assertEqual(request(f'/api/archive/contracts/{result["contractId"]}', {"status": "active"}, "PATCH")[0], 200)
        self.assertEqual(request("/api/market/flow", {"userId": 3, "assetType": [], "action": "list"}, "POST")[0], 400)
        with self.assertRaises(ValueError):
            make_server(host="0.0.0.0", port=0, db_path=self.path, key=self.key)


if __name__ == "__main__":
    unittest.main()
