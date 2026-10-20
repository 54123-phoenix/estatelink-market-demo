import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

PORT = 3000
# 演示默认 30 秒无回应记为一次未回应；正式环境建议改为 24 * 3600（24小时）
import os
INQUIRY_TIMEOUT = float(os.environ.get("INQUIRY_TIMEOUT", "30"))
# 连续未回应达到此次数后，自动标记为"疑似已故"并标红置顶
MAX_MISSED = 3

BASE_DIR = Path(__file__).parent
ASSET_DIR = (BASE_DIR / "assets").resolve()

# 以下身份字段均为无效占位值：身份证地区码 000000、手机号段 100、密码 DEMO_ONLY。
users = [
    {"id": 1, "name": "张伟", "gender": "男", "age": 34, "idCard": "000000199203150001", "game": "王者荣耀", "account": "zw_game001", "password": "DEMO_ONLY_01", "phone": "10000000001", "status": "健在", "missedCount": 0},
    {"id": 2, "name": "李娜", "gender": "女", "age": 28, "idCard": "000000199607080002", "game": "原神", "account": "lina_genshin", "password": "DEMO_ONLY_02", "phone": "10000000002", "status": "健在", "missedCount": 0},
    {"id": 3, "name": "王强", "gender": "男", "age": 56, "idCard": "000000196911230003", "game": "Steam 库存", "account": "wq_steam88", "password": "DEMO_ONLY_03", "phone": "10000000003", "status": "已故", "missedCount": 3},
    {"id": 4, "name": "刘洋", "gender": "男", "age": 41, "idCard": "000000198404120004", "game": "魔兽世界", "account": "ly_wow_cn", "password": "DEMO_ONLY_04", "phone": "10000000004", "status": "未知", "missedCount": 1},
    {"id": 5, "name": "陈静", "gender": "女", "age": 63, "idCard": "000000196204300005", "game": "梦幻西游", "account": "cj_mhxy63", "password": "DEMO_ONLY_05", "phone": "10000000005", "status": "已故", "missedCount": 3},
    {"id": 6, "name": "赵磊", "gender": "男", "age": 25, "idCard": "000000200002180006", "game": "英雄联盟", "account": "zl_lol2000", "password": "DEMO_ONLY_06", "phone": "10000000006", "status": "健在", "missedCount": 0},
    {"id": 7, "name": "孙悦", "gender": "女", "age": 31, "idCard": "000000199408120007", "game": "和平精英", "account": "sy_peace31", "password": "DEMO_ONLY_07", "phone": "10000000007", "status": "健在", "missedCount": 0},
    {"id": 8, "name": "周杰", "gender": "男", "age": 45, "idCard": "000000198002180008", "game": "DNF", "account": "zj_dnf80", "password": "DEMO_ONLY_08", "phone": "10000000008", "status": "健在", "missedCount": 0},
    {"id": 9, "name": "吴倩", "gender": "女", "age": 52, "idCard": "000000197211090009", "game": "欢乐斗地主", "account": "wq_ddZ52", "password": "DEMO_ONLY_09", "phone": "10000000009", "status": "未知", "missedCount": 0},
    {"id": 10, "name": "郑浩", "gender": "男", "age": 29, "idCard": "000000199604250010", "game": "CS2 库存", "account": "zh_cs296", "password": "DEMO_ONLY_10", "phone": "10000000010", "status": "健在", "missedCount": 0},
    {"id": 11, "name": "冯丽", "gender": "女", "age": 38, "idCard": "000000198709300011", "game": "剑网3", "account": "fl_jx387", "password": "DEMO_ONLY_11", "phone": "10000000011", "status": "健在", "missedCount": 0},
    {"id": 12, "name": "何军", "gender": "男", "age": 67, "idCard": "000000195806120012", "game": "QQ象棋", "account": "hj_xq58", "password": "DEMO_ONLY_12", "phone": "10000000012", "status": "未知", "missedCount": 0},
]

# 询问记录：{ id, userId, content, sentAt, expiresAt, status: pending/answered/expired, answer: yes/no/None }
inquiries = []
next_inquiry_id = 1
next_user_id = 13
lock = threading.Lock()

DATA_FILE = BASE_DIR / "data.json"
DEFAULT_SMS = "【用户池平台】尊敬的用户：我们正在进行例行的账户信息核对，请您在方便时打开本消息回复确认。如给您带来不便，敬请谅解。"
# 自动定期发送询问短信的间隔（秒），测试默认 30 秒；正式环境建议 24 * 3600
AUTO_INTERVAL = float(os.environ.get("AUTO_INTERVAL", "30"))
# 每轮最多询问的用户数：用户量大时轮流普查，而非同时给所有人发短信
AUTO_BATCH = int(os.environ.get("AUTO_BATCH", "1"))
auto_send_enabled = True
auto_cursor = 0
next_auto_at = time.time() + AUTO_INTERVAL


def save_data():
    DATA_FILE.write_text(
        json.dumps({"users": users, "nextUserId": next_user_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_data():
    global users, next_user_id
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        users = data["users"]
        next_user_id = data.get("nextUserId") or max(u["id"] for u in users) + 1
        print(f"[启动] 已从 {DATA_FILE.name} 加载 {len(users)} 个用户")
    except (OSError, json.JSONDecodeError, KeyError):
        pass


load_data()

MARKET_CATALOG = json.loads((BASE_DIR / "market_catalog.json").read_text(encoding="utf-8"))
MARKET_STATE_FILE = BASE_DIR / "market_state.json"
market_flows = {}
market_revision = 0


def default_market_flow():
    return {"listed": False, "buyer": False, "decision": None, "scenario": 0}


def seed_market_flows():
    """首次启动时给两份示例遗产安排不同进度，方便展示总览。"""
    examples = {
        "wq_steam88": {
            "item": {"listed": True, "buyer": True},
            "account": {"listed": True},
        },
        "cj_mhxy63": {
            "item": {"listed": True, "buyer": True, "decision": "hold", "scenario": 2},
        },
    }
    now_ms = int(time.time() * 1000)
    seeded = {}
    for user in users:
        if user["status"] != "已故":
            continue
        for asset_type, changes in examples.get(user["account"], {}).items():
            seeded[f'{user["id"]}:{asset_type}'] = {
                **default_market_flow(), **changes, "updatedAt": now_ms,
            }
    return seeded


def save_market_state():
    pending_file = MARKET_STATE_FILE.with_suffix(".tmp")
    pending_file.write_text(
        json.dumps({"revision": market_revision, "flows": market_flows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pending_file.replace(MARKET_STATE_FILE)


def load_market_state():
    global market_flows, market_revision
    try:
        data = json.loads(MARKET_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data["flows"], dict):
            raise ValueError("flows must be an object")
        market_flows = data["flows"]
        market_revision = int(data.get("revision", 0))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        market_flows = seed_market_flows()
        market_revision = 0


load_market_state()


def auto_send_loop():
    """每隔 AUTO_INTERVAL 秒，轮流给 AUTO_BATCH 位健在/未知且没有待回复询问的用户发送确认短信"""
    global next_auto_at, next_inquiry_id, auto_cursor
    while True:
        time.sleep(1)
        now = time.time()
        if now < next_auto_at:
            continue
        next_auto_at = now + AUTO_INTERVAL
        if not auto_send_enabled:
            continue
        sent_names = []
        with lock:
            n = len(users)
            checked = 0
            while len(sent_names) < AUTO_BATCH and checked < n and n > 0:
                u = users[auto_cursor % n]
                auto_cursor += 1
                checked += 1
                if u["status"] not in ("健在", "未知"):
                    continue
                if any(q["userId"] == u["id"] and q["status"] == "pending" for q in inquiries):
                    continue
                inquiries.append({
                    "id": next_inquiry_id,
                    "userId": u["id"],
                    "content": DEFAULT_SMS,
                    "sentAt": now,
                    "expiresAt": now + INQUIRY_TIMEOUT,
                    "status": "pending",
                    "answer": None,
                })
                next_inquiry_id += 1
                sent_names.append(u["name"])
        if sent_names:
            print(f'[自动发送] 本轮询问：{"、".join(sent_names)}')


def timeout_sweeper():
    while True:
        time.sleep(1)
        now = time.time()
        with lock:
            for q in inquiries:
                if q["status"] == "pending" and now > q["expiresAt"]:
                    q["status"] = "expired"
                    u = next((x for x in users if x["id"] == q["userId"]), None)
                    if not u:
                        continue
                    u["missedCount"] += 1
                    print(f'[超时] {u["name"]} 未回应第 {u["missedCount"]} 次')
                    if u["missedCount"] >= MAX_MISSED and u["status"] != "已故":
                        u["status"] = "疑似已故"
                        print(f'[状态变更] {u["name"]} 连续 {MAX_MISSED} 次未回应 → 疑似已故')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, file_path, content_type="text/html; charset=utf-8"):
        try:
            content = file_path.read_bytes()
        except OSError:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("404 Not Found".encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self.serve_file(BASE_DIR / "views" / "admin.html")
        if path == "/mobile":
            return self.serve_file(BASE_DIR / "views" / "mobile.html")
        if path == "/market-admin":
            return self.serve_file(BASE_DIR / "views" / "market-admin.html")
        if path == "/market.css":
            return self.serve_file(BASE_DIR / "views" / "market.css", "text/css; charset=utf-8")
        if path == "/market.js":
            return self.serve_file(BASE_DIR / "views" / "market.js", "text/javascript; charset=utf-8")
        if path == "/market-admin.css":
            return self.serve_file(BASE_DIR / "views" / "market-admin.css", "text/css; charset=utf-8")
        if path == "/market-admin.js":
            return self.serve_file(BASE_DIR / "views" / "market-admin.js", "text/javascript; charset=utf-8")
        if path.startswith("/assets/"):
            asset_path = (ASSET_DIR / unquote(path[len("/assets/"):])).resolve()
            try:
                asset_path.relative_to(ASSET_DIR)
            except ValueError:
                return self.send_error(404)
            if asset_path.suffix != ".webp":
                return self.send_error(404)
            return self.serve_file(asset_path, "image/webp")

        if path == "/api/market/overview":
            with lock:
                result = {
                    "users": [
                        {key: u[key] for key in ("id", "name", "phone", "game", "account", "status", "missedCount")}
                        for u in users
                    ],
                    "catalog": MARKET_CATALOG,
                    "flows": {key: dict(flow) for key, flow in market_flows.items()},
                    "revision": market_revision,
                    "asOf": int(time.time() * 1000),
                }
            return self.send_json(200, result)

        if path == "/api/users":
            now = time.time()
            with lock:
                result = []
                for u in users:
                    p = next((q for q in inquiries if q["userId"] == u["id"] and q["status"] == "pending"), None)
                    item = dict(u)
                    item["pending"] = {"inquiryId": p["id"], "remainMs": max(0, int((p["expiresAt"] - now) * 1000))} if p else None
                    result.append(item)
            return self.send_json(200, {
                "now": int(now * 1000),
                "users": result,
                "autoSend": {
                    "enabled": auto_send_enabled,
                    "intervalSec": AUTO_INTERVAL,
                    "batch": AUTO_BATCH,
                    "remainMs": max(0, int((next_auto_at - now) * 1000)),
                },
            })

        if path == "/api/mobile/messages":
            user_id = int(parse_qs(parsed.query).get("userId", ["0"])[0])
            now = time.time()
            with lock:
                msgs = [
                    {
                        "id": q["id"],
                        "content": q["content"],
                        "sentAt": int(q["sentAt"] * 1000),
                        "status": q["status"],
                        "answer": q["answer"],
                        "remainMs": max(0, int((q["expiresAt"] - now) * 1000)) if q["status"] == "pending" else 0,
                    }
                    for q in inquiries if q["userId"] == user_id
                ]
            return self.send_json(200, {"now": int(now * 1000), "messages": msgs})

        if path == "/api/mobile/users":
            with lock:
                mobile_users = [
                    {
                        "id": u["id"],
                        "name": u["name"],
                        "phone": u["phone"],
                        "game": u["game"],
                        "account": u["account"],
                        "status": u["status"],
                    }
                    for u in users
                ]
            return self.send_json(200, {"users": mobile_users})

        self.send_json(404, {"error": "Not Found"})

    def do_POST(self):
        global next_inquiry_id
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self.read_body()
        except Exception:
            return self.send_json(400, {"error": "请求体不是合法 JSON"})

        if path == "/api/market/flow":
            global market_revision
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "请求体必须是对象"})
            user_id = body.get("userId")
            asset_type = body.get("assetType")
            action = body.get("action")
            if type(user_id) is not int or asset_type not in ("item", "account"):
                return self.send_json(400, {"error": "账号或资产类型不合法"})
            if action not in ("list", "buyer", "hold", "sell", "buyout", "revise", "reset", "scenario"):
                return self.send_json(400, {"error": "操作不合法"})
            with lock:
                user = next((u for u in users if u["id"] == user_id), None)
                if not user:
                    return self.send_json(404, {"error": "客户池账号不存在"})
                profile = MARKET_CATALOG["profiles"].get(user["account"], {})
                if asset_type not in profile:
                    return self.send_json(404, {"error": "该资产尚未配置演示行情"})
                if user["status"] != "已故" and action not in ("scenario", "reset"):
                    return self.send_json(409, {"error": "客户池状态尚未进入遗产处置"})
                flow_key = f"{user_id}:{asset_type}"
                flow = {**default_market_flow(), **market_flows.get(flow_key, {})}
                if action == "list":
                    if flow["listed"]:
                        return self.send_json(409, {"error": "该资产已模拟挂售"})
                    flow["listed"] = True
                elif action == "buyer":
                    if not flow["listed"] or flow["buyer"]:
                        return self.send_json(409, {"error": "请先挂售，且不要重复创建买家意向"})
                    flow["buyer"] = True
                elif action in ("hold", "sell", "buyout"):
                    if not flow["buyer"] or flow["decision"]:
                        return self.send_json(409, {"error": "当前没有待继承人决定的买家意向"})
                    flow["decision"] = action
                elif action == "revise":
                    if not flow["decision"]:
                        return self.send_json(409, {"error": "当前没有可重新选择的决定"})
                    flow["decision"] = None
                elif action == "scenario":
                    flow["scenario"] = (flow["scenario"] + 1) % len(MARKET_CATALOG["scenarios"])
                elif action == "reset":
                    flow = default_market_flow()

                if action == "reset":
                    market_flows.pop(flow_key, None)
                else:
                    flow["updatedAt"] = int(time.time() * 1000)
                    market_flows[flow_key] = flow
                market_revision += 1
                revision = market_revision
                save_market_state()
            return self.send_json(200, {"ok": True, "flow": flow, "revision": revision})

        if path == "/api/sms/send":
            with lock:
                u = next((x for x in users if x["id"] == body.get("userId")), None)
                if not u:
                    return self.send_json(404, {"error": "用户不存在"})
                content = (body.get("content") or "").strip()
                if not content:
                    return self.send_json(400, {"error": "短信内容不能为空"})
                if any(q["userId"] == u["id"] and q["status"] == "pending" for q in inquiries):
                    return self.send_json(409, {"error": "该用户有一条待回复的询问，请等待回复或超时后再发"})
                now = time.time()
                q = {
                    "id": next_inquiry_id,
                    "userId": u["id"],
                    "content": content,
                    "sentAt": now,
                    "expiresAt": now + INQUIRY_TIMEOUT,
                    "status": "pending",
                    "answer": None,
                }
                next_inquiry_id += 1
                inquiries.append(q)
            print(f'[短信发出] → {u["name"]}（{u["phone"]}）：{content}')
            return self.send_json(200, {"ok": True, "inquiryId": q["id"]})

        if path == "/api/mobile/reply":
            with lock:
                q = next((x for x in inquiries if x["id"] == body.get("inquiryId")), None)
                if not q:
                    return self.send_json(404, {"error": "询问不存在"})
                if q["status"] != "pending":
                    return self.send_json(409, {"error": "该询问已回复或已超时"})
                answer = body.get("answer")
                if answer not in ("yes", "no"):
                    return self.send_json(400, {"error": "answer 只能是 yes 或 no"})
                q["status"] = "answered"
                q["answer"] = answer
                u = next((x for x in users if x["id"] == q["userId"]), None)
                if u:
                    if answer == "yes":
                        u["status"] = "健在"
                        u["missedCount"] = 0
                    else:
                        u["status"] = "已故"
            if u:
                print(f'[收到回复] {u["name"]} 回复"{"是" if answer == "yes" else "不是"}" → 状态：{u["status"]}')
            return self.send_json(200, {"ok": True})

        if path == "/api/users/add":
            global next_user_id
            required = ["name", "gender", "age", "idCard", "game", "account", "password", "phone"]
            missing = [f for f in required if not str(body.get(f) or "").strip()]
            if missing:
                return self.send_json(400, {"error": "请填写完整：" + "、".join(missing)})
            if body.get("gender") not in ("男", "女"):
                return self.send_json(400, {"error": "性别只能是 男 或 女"})
            id_card = str(body["idCard"]).strip()
            if len(id_card) != 18:
                return self.send_json(400, {"error": "身份证号必须是18位"})
            phone = str(body["phone"]).strip()
            if len(phone) != 11 or not phone.isdigit():
                return self.send_json(400, {"error": "电话号必须是11位数字"})
            try:
                age = int(body["age"])
                if age <= 0 or age > 150:
                    raise ValueError
            except (ValueError, TypeError):
                return self.send_json(400, {"error": "年龄不合法"})
            with lock:
                if any(u["idCard"] == id_card for u in users):
                    return self.send_json(409, {"error": "该身份证号已存在"})
                u = {
                    "id": next_user_id,
                    "name": str(body["name"]).strip(),
                    "gender": body["gender"],
                    "age": age,
                    "idCard": id_card,
                    "game": str(body["game"]).strip(),
                    "account": str(body["account"]).strip(),
                    "password": str(body["password"]).strip(),
                    "phone": phone,
                    "status": "健在",
                    "missedCount": 0,
                }
                next_user_id += 1
                users.append(u)
            print(f'[新增用户] {u["name"]}（{u["phone"]}）')
            return self.send_json(200, {"ok": True, "userId": u["id"]})

        if path == "/api/users/confirm-dead":
            with lock:
                u = next((x for x in users if x["id"] == body.get("userId")), None)
                if not u:
                    return self.send_json(404, {"error": "用户不存在"})
                u["status"] = "已故"
                # 人工确认后，未完成的询问全部作废
                for q in inquiries:
                    if q["userId"] == u["id"] and q["status"] == "pending":
                        q["status"] = "expired"
            print(f'[人工确认] {u["name"]} 经核实 → 已故')
            return self.send_json(200, {"ok": True})

        if path == "/api/save":
            with lock:
                save_data()
            print(f"[保存] 数据已写入 {DATA_FILE.name}（{len(users)} 个用户）")
            return self.send_json(200, {"ok": True, "userCount": len(users)})

        if path == "/api/auto-send":
            global auto_send_enabled, next_auto_at
            enabled = body.get("enabled")
            if not isinstance(enabled, bool):
                return self.send_json(400, {"error": "enabled 必须是布尔值"})
            auto_send_enabled = enabled
            if enabled:
                next_auto_at = time.time() + AUTO_INTERVAL
            print(f'[自动发送] {"已开启" if enabled else "已关闭"}')
            return self.send_json(200, {"ok": True, "enabled": auto_send_enabled})

        self.send_json(404, {"error": "Not Found"})


if __name__ == "__main__":
    threading.Thread(target=timeout_sweeper, daemon=True).start()
    threading.Thread(target=auto_send_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("服务已启动：")
    print(f"  网页端（用户池管理）：http://localhost:{PORT}/")
    print(f"  手机端（模拟APP）：   http://localhost:{PORT}/mobile")
    print(f"  询问超时时长：{INQUIRY_TIMEOUT:.0f} 秒（未回应 {MAX_MISSED} 次自动标红置顶）")
    print(f"  自动定期发送：每 {AUTO_INTERVAL:.0f} 秒询问 {AUTO_BATCH} 位用户（{'默认开启' if auto_send_enabled else '默认关闭'}）")
    server.serve_forever()
