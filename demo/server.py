"""Loopback-only standard-library HTTP entry point for the archive demo."""
import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    from .storage import ApiError, Store, fields, integer
except ImportError:
    from storage import ApiError, Store, fields, integer

BASE_DIR = Path(__file__).resolve().parent
PORT = 3000
INQUIRY_TIMEOUT = float(os.environ.get("INQUIRY_TIMEOUT", "30"))
AUTO_INTERVAL = float(os.environ.get("AUTO_INTERVAL", "30"))
AUTO_BATCH = int(os.environ.get("AUTO_BATCH", "1"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Request bodies and personally identifying values never enter logs.
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path):
        try:
            content = path.read_bytes()
        except OSError:
            return self.send_json(404, {"error": "文件不存在"})
        self.send_response(200)
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or path.suffix == ".js" else ""))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024 * 1024:
                raise ValueError
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeError):
            raise ApiError("请求体不是合法 JSON 或超过大小限制") from None
        if not isinstance(body, dict):
            raise ApiError("请求体必须是对象")
        return body

    def dispatch(self, method):
        try:
            self.route(method)
        except ApiError as exc:
            self.send_json(exc.code, {"error": str(exc)})
        except Exception:
            # Do not echo exceptions: SQL values, paths or tokens may be sensitive.
            self.send_json(500, {"error": "服务处理失败"})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        store = self.server.store
        if method == "GET":
            static = {"/": "admin.html", "/mobile": "mobile.html", "/market-admin": "market-admin.html", "/archive-admin": "archive-admin.html"}
            for filename in ("market.css", "market.js", "market-admin.css", "market-admin.js", "archive.css", "archive-common.js", "archive-admin.js", "archive-mobile.js", "admin-pool.js", "archive-admin.css"):
                static["/" + filename] = filename
            if path in static:
                return self.serve_file(BASE_DIR / "views" / static[path])
            if path.startswith("/assets/"):
                root = (BASE_DIR / "assets").resolve()
                asset = (root / unquote(path[len("/assets/"):])).resolve()
                if not asset.is_relative_to(root) or asset.suffix != ".webp":
                    raise ApiError("文件不存在", 404)
                return self.serve_file(asset)
            if path == "/api/users":
                return self.send_json(200, store.users())
            if path == "/api/mobile/users":
                return self.send_json(200, {"users": store.users()["users"]})
            if path == "/api/mobile/messages":
                try:
                    uid = int(parse_qs(parsed.query).get("userId", ["0"])[0])
                except ValueError:
                    raise ApiError("userId 不合法") from None
                integer(uid, "userId", 1)
                return self.send_json(200, store.messages(uid))
            if path == "/api/market/overview":
                return self.send_json(200, store.overview())
        archive_user = re.fullmatch(r"/api/archive/users/([0-9]+)(?:/(assets|contracts))?", path)
        archive_record = re.fullmatch(r"/api/archive/(assets|contracts)/([0-9]+)", path)
        if archive_user:
            uid = int(archive_user[1])
            section = archive_user[2]
            if method == "GET":
                result = {"assets": store.get_assets(uid)} if section == "assets" else {"contracts": store.get_contracts(uid)} if section == "contracts" else store.get_user(uid)
                return self.send_json(200, result)
            body = self.read_body()
            if method == "PATCH" and section is None:
                store.patch_user(uid, body)
                return self.send_json(200, {"ok": True, "userId": uid})
            if method == "POST" and section == "assets":
                return self.send_json(200, {"ok": True, "assetId": store.create_asset(uid, body)})
            if method == "POST" and section == "contracts":
                return self.send_json(200, {"ok": True, "contractId": store.create_contract(uid, body)})
        if archive_record and method == "PATCH":
            row_id = int(archive_record[2])
            body = self.read_body()
            if archive_record[1] == "assets":
                store.patch_asset(row_id, body)
                return self.send_json(200, {"ok": True, "assetId": row_id})
            store.patch_contract(row_id, body)
            return self.send_json(200, {"ok": True, "contractId": row_id})
        if method == "POST":
            body = self.read_body()
            if path == "/api/users/add":
                return self.send_json(200, {"ok": True, "userId": store.create_user(body)})
            if path == "/api/save":
                fields(body, set())
                return self.send_json(200, {"ok": True, "userCount": len(store.users()["users"]), "message": "所有更改已自动保存到 SQLite，无需手动保存"})
            if path == "/api/auto-send":
                fields(body, {"enabled"})
                store.auto_send(body.get("enabled"))
                return self.send_json(200, {"ok": True, "enabled": body["enabled"]})
            if path == "/api/users/confirm-dead":
                fields(body, {"userId"})
                store.confirm_dead(integer(body.get("userId"), "userId", 1))
                return self.send_json(200, {"ok": True})
            if path == "/api/sms/send":
                fields(body, {"userId", "content"})
                qid = store.send_sms(integer(body.get("userId"), "userId", 1), body.get("content"))
                return self.send_json(200, {"ok": True, "inquiryId": qid})
            if path == "/api/mobile/reply":
                fields(body, {"inquiryId", "answer"})
                store.reply(integer(body.get("inquiryId"), "inquiryId", 1), body.get("answer"))
                return self.send_json(200, {"ok": True})
            if path == "/api/market/flow":
                fields(body, {"userId", "assetType", "action"})
                result = store.market_flow(integer(body.get("userId"), "userId", 1), body.get("assetType"), body.get("action"))
                return self.send_json(200, result)
        raise ApiError("Not Found", 404)


def make_server(host="127.0.0.1", port=PORT, *, db_path=None, key=None, base_dir=None):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("服务仅允许监听 127.0.0.1 或 localhost")
    store = Store(db_path or os.environ.get("ESTATELINK_DB_PATH", str(BASE_DIR / "estatelink.sqlite3")), key if key is not None else os.environ.get("ESTATELINK_DATA_KEY"), base_dir=base_dir, inquiry_timeout=INQUIRY_TIMEOUT, auto_interval=AUTO_INTERVAL, auto_batch=AUTO_BATCH)
    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store
    return server


def background_loop(store, stopped):
    while not stopped.wait(1):
        try:
            store.sweep()
        except Exception:
            print("[后台任务] 本轮处理失败，下一轮重试")


def main():
    server = make_server()
    stopped = threading.Event()
    threading.Thread(target=background_loop, args=(server.store, stopped), daemon=True).start()
    print(f"虚构演示服务：http://127.0.0.1:{PORT}/ （资料自动保存；身份切换仅为演示）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()


if __name__ == "__main__":
    main()
