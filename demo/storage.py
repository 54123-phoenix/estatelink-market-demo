"""Transactional SQLite archive and verification service for fictional demo data."""
import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

try:
    from .fixtures import DEFAULT_USERS
except ImportError:
    from fixtures import DEFAULT_USERS

SENSITIVE = {"name", "phone", "idCard", "email", "address", "emergencyContact"}
USER_FIELDS = SENSITIVE | {"gender", "age"}
ASSET_FIELDS = {"assetType", "platform", "game", "name", "account", "quantity", "costMinor", "currency", "acquiredAt", "disposition", "notes", "parentAccountId"}
CONTRACT_FIELDS = {"number", "name", "status", "effectiveDate", "expiryDate"}
DEFAULT_SMS = "【用户池平台】尊敬的用户：我们正在进行例行的账户信息核对，请您在方便时打开本消息回复确认。如给您带来不便，敬请谅解。"


class ApiError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def fields(body, allowed):
    if not isinstance(body, dict):
        raise ApiError("请求体必须是对象")
    if set(body) - allowed:
        raise ApiError("不支持的字段：" + "、".join(sorted(set(body) - allowed)))


def text_value(value, name, maximum=100, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ApiError(name + " 必须是文本")
    value = value.strip()
    if not value:
        if required:
            raise ApiError(name + " 不能为空")
        return None
    if len(value) > maximum:
        raise ApiError(name + " 超出长度限制")
    return value


def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or value > (maximum if maximum is not None else 9223372036854775807):
        raise ApiError(name + " 不合法")
    return value


def date_value(value, name):
    value = text_value(value, name, 10)
    if value:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ApiError(name + " 必须是 YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ApiError(name + " 日期不合法") from None
    return value


def validate_user(body, creating=False):
    allowed = USER_FIELDS | ({"game", "platform", "account"} if creating else set())
    fields(body, allowed)
    result = {}
    for key, value in body.items():
        if key == "age":
            result[key] = None if value in (None, "") else integer(value, key, 1, 150)
        else:
            maximum = 500 if key in {"address", "emergencyContact"} else 128 if key == "account" else 100
            result[key] = text_value(value, key, maximum, key in {"name", "phone"} or (creating and key in {"game", "account"}))
    if creating:
        for key in ("name", "phone", "game", "account"):
            if not result.get(key):
                raise ApiError(key + " 不能为空")
    if "phone" in result and not re.fullmatch(r"[0-9]{11}", result["phone"]):
        raise ApiError("phone 必须是11位 ASCII 数字")
    if result.get("idCard") and not re.fullmatch(r"[0-9]{17}[0-9Xx]", result["idCard"]):
        raise ApiError("idCard 必须是18位身份证号")
    if result.get("idCard"):
        result["idCard"] = result["idCard"].upper()
    if result.get("gender") not in (None, "男", "女", "其他", "不透露"):
        raise ApiError("gender 不合法")
    return result


def validate_asset(body, creating=False, existing=None):
    allowed = ASSET_FIELDS if creating else ASSET_FIELDS - {"assetType", "parentAccountId"}
    fields(body, allowed)
    if creating and body.get("assetType", "item") != "item":
        raise ApiError("每位客户只能有一个主账号", 409)
    if "parentAccountId" in body:
        raise ApiError("parentAccountId 由服务端关联")
    result = {}
    for key, value in body.items():
        if key == "assetType":
            continue
        if key == "quantity":
            result[key] = integer(value, key, 1, 1 if existing and existing["assetType"] == "account" else None)
        elif key == "costMinor":
            result[key] = None if value in (None, "") else integer(value, key)
        elif key == "acquiredAt":
            result[key] = date_value(value, key)
        else:
            required = key == "name" or (existing and existing["assetType"] == "account" and key in {"game", "account"})
            result[key] = text_value(value, key, 500 if key == "notes" else 128 if key == "account" else 100, required)
    if creating and not result.get("name"):
        raise ApiError("name 不能为空")
    if result.get("currency") and not re.fullmatch(r"[A-Z]{3}", result["currency"]):
        raise ApiError("currency 必须是三位大写字母")
    if "currency" in result and not result["currency"]:
        raise ApiError("currency 必须是三位大写字母")
    if result.get("disposition") not in (None, "inherit", "sell_then_inherit", "donate", "memorial_close"):
        raise ApiError("disposition 不合法")
    return result


def validate_contract(body, existing=None):
    fields(body, CONTRACT_FIELDS)
    result = {}
    for key, value in body.items():
        result[key] = date_value(value, key) if key.endswith("Date") else text_value(value, key, 100, key in {"number", "name", "status"})
    merged = {**(existing or {}), **result}
    if not merged.get("number") or not merged.get("name"):
        raise ApiError("合同 number 和 name 不能为空")
    if merged.get("status", "draft") not in {"draft", "active", "terminated"}:
        raise ApiError("合同 status 不合法")
    if merged.get("effectiveDate") and merged.get("expiryDate") and merged["expiryDate"] < merged["effectiveDate"]:
        raise ApiError("到期日期不能早于生效日期")
    return result


def mask(key, value):
    if not value:
        return value
    if key == "name":
        return value[:1] + "**" if len(value) > 1 else "***"
    if key == "phone":
        return value[:3] + "****" + value[-4:]
    if key == "idCard":
        return "**************" + value[-4:]
    if key == "email":
        return value[:1] + "***@***" if len(value) > 1 else "***"
    if key == "account":
        return value[:2] + "***" + (value[-2:] if len(value) > 4 else "") if len(value) > 2 else "***"
    return value[:1] + "***" if len(value) > 1 else "***"


class Store:
    def __init__(self, db_path, key, base_dir=None, inquiry_timeout=30, auto_interval=30, auto_batch=1):
        if not key:
            raise RuntimeError("ESTATELINK_DATA_KEY 必需；请运行 generate_key.py 并安全设置环境变量")
        try:
            raw_key = key.encode("ascii") if isinstance(key, str) else key
            self.fernet = Fernet(raw_key)
            self.fingerprint_key = hmac.digest(base64.urlsafe_b64decode(raw_key), b"estatelink/id-fingerprint/v1", "sha256")
        except (ValueError, TypeError, UnicodeError):
            raise RuntimeError("ESTATELINK_DATA_KEY 格式错误") from None
        self.path = str(db_path)
        self.base = Path(base_dir or Path(__file__).parent)
        self.catalog = json.loads((self.base / "market_catalog.json").read_text(encoding="utf-8"))
        self.inquiry_timeout = inquiry_timeout
        self.auto_interval = auto_interval
        self.auto_batch = auto_batch
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def encrypt(self, value):
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii") if value else None

    def decrypt(self, value):
        return self.fernet.decrypt(value.encode("ascii")).decode("utf-8") if value else None

    def fingerprint(self, value):
        return hmac.new(self.fingerprint_key, value.encode("utf-8"), hashlib.sha256).hexdigest() if value else None

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            raise ApiError("身份证、合同编号或主账号重复，或资产归属无效", 409) from None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL, idCard TEXT, email TEXT, address TEXT, emergencyContact TEXT, gender TEXT, age INTEGER, id_fingerprint TEXT UNIQUE, status TEXT NOT NULL DEFAULT '健在', missedCount INTEGER NOT NULL DEFAULT 0, createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY AUTOINCREMENT, userId INTEGER NOT NULL REFERENCES users(id), assetType TEXT NOT NULL CHECK(assetType IN ('account','item')), parentAccountId INTEGER REFERENCES assets(id), platform TEXT, game TEXT, name TEXT NOT NULL, account TEXT, quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0 AND (assetType<>'account' OR quantity=1)), costMinor INTEGER CHECK(costMinor>=0), currency TEXT NOT NULL DEFAULT 'CNY', acquiredAt TEXT, disposition TEXT DEFAULT 'inherit', notes TEXT, createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL, CHECK ((assetType='account' AND parentAccountId IS NULL) OR (assetType='item' AND parentAccountId IS NOT NULL)));
                CREATE UNIQUE INDEX IF NOT EXISTS single_account ON assets(userId) WHERE assetType='account';
                CREATE TRIGGER IF NOT EXISTS item_owner BEFORE INSERT ON assets WHEN NEW.assetType='item' AND NOT EXISTS(SELECT 1 FROM assets WHERE id=NEW.parentAccountId AND userId=NEW.userId AND assetType='account') BEGIN SELECT RAISE(ABORT,'invalid parent'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_asset_owner BEFORE UPDATE OF userId,assetType,parentAccountId ON assets WHEN NEW.userId<>OLD.userId OR NEW.assetType<>OLD.assetType OR NEW.parentAccountId IS NOT OLD.parentAccountId BEGIN SELECT RAISE(ABORT,'immutable owner'); END;
                CREATE TABLE IF NOT EXISTS contracts (id INTEGER PRIMARY KEY AUTOINCREMENT, userId INTEGER NOT NULL REFERENCES users(id), number TEXT NOT NULL UNIQUE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','terminated')), effectiveDate TEXT, expiryDate TEXT, createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS inquiries (id INTEGER PRIMARY KEY AUTOINCREMENT, userId INTEGER NOT NULL REFERENCES users(id), content TEXT NOT NULL, sentAt REAL NOT NULL, expiresAt REAL NOT NULL, status TEXT NOT NULL, answer TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_pending ON inquiries(userId) WHERE status='pending';
                CREATE TABLE IF NOT EXISTS market_flows (userId INTEGER NOT NULL REFERENCES users(id), assetType TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(userId,assetType));
                CREATE TABLE IF NOT EXISTS market_profile_links (userId INTEGER NOT NULL REFERENCES users(id), assetType TEXT NOT NULL, assetId INTEGER NOT NULL REFERENCES assets(id), profileKey TEXT NOT NULL, PRIMARY KEY(userId,assetType));
                CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY, action TEXT NOT NULL, entityType TEXT NOT NULL, entityId INTEGER, source TEXT NOT NULL DEFAULT 'demo', createdAt INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
        with self.connect(write=True) as conn:
            if self.meta(conn, "schema_version"):
                try:
                    if self.decrypt(self.meta(conn, "key_check")) != "estatelink-v1":
                        raise InvalidToken
                    for row in conn.execute("SELECT name,phone,idCard,email,address,emergencyContact FROM users"):
                        for value in row:
                            self.decrypt(value)
                    for row in conn.execute("SELECT account FROM assets UNION ALL SELECT content FROM inquiries"):
                        self.decrypt(row[0])
                except (InvalidToken, AttributeError):
                    raise RuntimeError("ESTATELINK_DATA_KEY 与数据库不匹配") from None
                return
            data_path = self.base / "data.json"
            migration_source = "data.json"
            try:
                legacy = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {"users": DEFAULT_USERS}
                old_users = legacy["users"]
                if not isinstance(old_users, list) or not old_users:
                    raise ValueError
                for old in old_users:
                    payload = {k: v for k, v in old.items() if k in USER_FIELDS | {"game", "platform", "account"}}
                    data = validate_user(payload, True)
                    uid = integer(old["id"], "id", 1)
                    status = old.get("status", "健在")
                    if status not in {"健在", "未知", "疑似已故", "已故"}:
                        raise ValueError
                    missed = integer(old.get("missedCount", 0), "missedCount")
                    self.insert_user(conn, data, uid, status, missed)
                    profile_key = old["account"]
                    if profile_key in self.catalog["profiles"]:
                        aid = conn.execute("SELECT id FROM assets WHERE userId=? AND assetType='account'", (uid,)).fetchone()[0]
                        self.insert(conn, "market_profile_links", {"userId": uid, "assetType": "account", "assetId": aid, "profileKey": profile_key})
                        profile = self.catalog["profiles"][profile_key]
                        if "item" in profile:
                            iid = self.insert_asset(conn, uid, {"name": profile["item"]["name"], "game": old["game"]}, aid)
                            self.insert(conn, "market_profile_links", {"userId": uid, "assetType": "item", "assetId": iid, "profileKey": profile_key})
                if legacy.get("nextUserId"):
                    next_id = integer(legacy["nextUserId"], "nextUserId", 1)
                    conn.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='users'", (next_id - 1,))
                state_path = self.base / "market_state.json"
                if state_path.exists():
                    migration_source = "market_state.json"
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(state["flows"], dict):
                        raise ValueError
                    self.set_meta(conn, "revision", integer(state.get("revision", 0), "revision"))
                    for key, flow in state["flows"].items():
                        uid, kind = key.split(":")
                        uid = int(uid)
                        if kind not in {"account", "item"} or not isinstance(flow, dict):
                            raise ValueError
                        if conn.execute("SELECT 1 FROM market_profile_links WHERE userId=? AND assetType=?", (uid, kind)).fetchone():
                            normalized = {**self.default_flow(), **flow}
                            if type(normalized["listed"]) is not bool or type(normalized["buyer"]) is not bool or normalized["decision"] not in {None, "hold", "sell", "buyout"} or type(normalized["scenario"]) is not int or not 0 <= normalized["scenario"] < len(self.catalog["scenarios"]):
                                raise ValueError
                            self.insert(conn, "market_flows", {"userId": uid, "assetType": kind, "data": json.dumps(normalized)})
                else:
                    self.set_meta(conn, "revision", 0)
                    for row in conn.execute("SELECT l.* FROM market_profile_links l JOIN users u ON u.id=l.userId WHERE u.status='已故'").fetchall():
                        changes = {("wq_steam88", "item"): {"listed": True, "buyer": True}, ("wq_steam88", "account"): {"listed": True}, ("cj_mhxy63", "item"): {"listed": True, "buyer": True, "decision": "hold", "scenario": 2}}.get((row["profileKey"], row["assetType"]))
                        if changes:
                            self.insert(conn, "market_flows", {"userId": row["userId"], "assetType": row["assetType"], "data": json.dumps({**self.default_flow(), **changes, "updatedAt": self.now_ms()})})
            except (ValueError, TypeError, KeyError, OSError, ApiError) as exc:
                raise RuntimeError(migration_source + " 迁移失败；源文件未修改，请检查数据格式") from exc
            for key, value in {"schema_version": 1, "key_check": self.encrypt("estatelink-v1"), "auto_enabled": True, "auto_cursor": 0, "next_auto_at": time.time() + self.auto_interval}.items():
                self.set_meta(conn, key, value)

    @staticmethod
    def now_ms():
        return int(time.time() * 1000)

    @staticmethod
    def insert(conn, table, data):
        return conn.execute(f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join('?' for _ in data)})", tuple(data.values())).lastrowid

    @staticmethod
    def meta(conn, key, default=None):
        row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def set_meta(conn, key, value):
        conn.execute("INSERT INTO app_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def audit(self, conn, action, entity, entity_id):
        self.insert(conn, "audit_logs", {"action": action, "entityType": entity, "entityId": entity_id, "createdAt": self.now_ms()})

    def insert_user(self, conn, data, uid=None, status="健在", missed=0):
        now = self.now_ms()
        values = {key: self.encrypt(data.get(key)) if key in SENSITIVE else data.get(key) for key in USER_FIELDS}
        values.update(id_fingerprint=self.fingerprint(data.get("idCard")), status=status, missedCount=missed, createdAt=now, updatedAt=now)
        if uid is not None:
            values["id"] = uid
        uid = self.insert(conn, "users", values)
        self.insert(conn, "assets", {"userId": uid, "assetType": "account", "name": data["game"] + "账号", "game": data["game"], "platform": data.get("platform"), "account": self.encrypt(data["account"]), "createdAt": now, "updatedAt": now})
        self.audit(conn, "create", "user", uid)
        return uid

    def create_user(self, body):
        data = validate_user(body, True)
        with self.connect(True) as conn:
            return self.insert_user(conn, data)

    def require(self, conn, table, row_id):
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if not row:
            raise ApiError("记录不存在", 404)
        return dict(row)

    def user_projection(self, conn, row):
        user = dict(row)
        user.pop("id_fingerprint", None)
        for key in SENSITIVE:
            user[key] = mask(key, self.decrypt(user[key]))
        account = conn.execute("SELECT * FROM assets WHERE userId=? AND assetType='account'", (user["id"],)).fetchone()
        user.update(game=account["game"], platform=account["platform"], account=mask("account", self.decrypt(account["account"])), mainAccountId=account["id"])
        user["updatedAt"] = max(user["updatedAt"], account["updatedAt"])
        return user

    def get_user(self, uid):
        with self.connect() as conn:
            return self.user_projection(conn, self.require(conn, "users", uid))

    def patch_user(self, uid, body):
        data = validate_user(body)
        if "idCard" in data:
            data["id_fingerprint"] = self.fingerprint(data["idCard"])
        for key in SENSITIVE & data.keys():
            data[key] = self.encrypt(data[key])
        with self.connect(True) as conn:
            self.require(conn, "users", uid)
            self.update(conn, "users", uid, data)

    def update(self, conn, table, row_id, data):
        data = {**data, "updatedAt": self.now_ms()}
        conn.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in data)} WHERE id=?", (*data.values(), row_id))
        self.audit(conn, "update", table, row_id)

    def insert_asset(self, conn, uid, data, parent):
        now = self.now_ms()
        data = {**data, "userId": uid, "assetType": "item", "parentAccountId": parent, "createdAt": now, "updatedAt": now}
        if "account" in data:
            data["account"] = self.encrypt(data["account"])
        aid = self.insert(conn, "assets", data)
        self.audit(conn, "create", "asset", aid)
        return aid

    def get_assets(self, uid):
        with self.connect() as conn:
            self.require(conn, "users", uid)
            result = []
            for row in conn.execute("SELECT * FROM assets WHERE userId=? ORDER BY id", (uid,)):
                item = dict(row)
                item["account"] = mask("account", self.decrypt(item["account"]))
                item["hasMarket"] = bool(conn.execute("SELECT 1 FROM market_profile_links WHERE assetId=?", (item["id"],)).fetchone())
                result.append(item)
            return result

    def create_asset(self, uid, body):
        data = validate_asset(body, True)
        with self.connect(True) as conn:
            self.require(conn, "users", uid)
            parent = conn.execute("SELECT id FROM assets WHERE userId=? AND assetType='account'", (uid,)).fetchone()[0]
            return self.insert_asset(conn, uid, data, parent)

    def patch_asset(self, aid, body):
        with self.connect(True) as conn:
            current = self.require(conn, "assets", aid)
            data = validate_asset(body, existing=current)
            if "account" in data:
                data["account"] = self.encrypt(data["account"])
            self.update(conn, "assets", aid, data)

    def get_contracts(self, uid):
        with self.connect() as conn:
            self.require(conn, "users", uid)
            return [dict(row) for row in conn.execute("SELECT * FROM contracts WHERE userId=? ORDER BY id", (uid,))]

    def create_contract(self, uid, body):
        data = validate_contract(body)
        with self.connect(True) as conn:
            self.require(conn, "users", uid)
            cid = self.insert(conn, "contracts", {**data, "userId": uid, "createdAt": self.now_ms(), "updatedAt": self.now_ms()})
            self.audit(conn, "create", "contract", cid)
            return cid

    def patch_contract(self, cid, body):
        with self.connect(True) as conn:
            current = self.require(conn, "contracts", cid)
            self.update(conn, "contracts", cid, validate_contract(body, current))

    def users(self):
        now = time.time()
        with self.connect() as conn:
            result = []
            for row in conn.execute("SELECT * FROM users ORDER BY id"):
                item = self.user_projection(conn, row)
                pending = conn.execute("SELECT * FROM inquiries WHERE userId=? AND status='pending'", (item["id"],)).fetchone()
                item["pending"] = {"inquiryId": pending["id"], "remainMs": max(0, int((pending["expiresAt"]-now)*1000))} if pending else None
                result.append(item)
            return {"now": int(now*1000), "users": result, "autoSend": {"enabled": self.meta(conn, "auto_enabled", True), "intervalSec": self.auto_interval, "batch": self.auto_batch, "remainMs": max(0, int((self.meta(conn, "next_auto_at", now)-now)*1000))}}

    def messages(self, uid):
        now = time.time()
        with self.connect() as conn:
            self.require(conn, "users", uid)
            result = []
            for row in conn.execute("SELECT * FROM inquiries WHERE userId=? ORDER BY id", (uid,)):
                result.append({"id": row["id"], "content": self.decrypt(row["content"]), "sentAt": int(row["sentAt"]*1000), "status": row["status"], "answer": row["answer"], "remainMs": max(0, int((row["expiresAt"]-now)*1000)) if row["status"] == "pending" else 0})
            return {"now": int(now*1000), "messages": result}

    def send_sms(self, uid, content, conn=None):
        content = text_value(content, "content", 2000, True)
        if conn is None:
            with self.connect(True) as connection:
                return self.send_sms(uid, content, connection)
        self.require(conn, "users", uid)
        if conn.execute("SELECT 1 FROM inquiries WHERE userId=? AND status='pending'", (uid,)).fetchone():
            raise ApiError("该用户有一条待回复的询问", 409)
        now = time.time()
        qid = self.insert(conn, "inquiries", {"userId": uid, "content": self.encrypt(content), "sentAt": now, "expiresAt": now+self.inquiry_timeout, "status": "pending"})
        self.audit(conn, "send", "inquiry", qid)
        return qid

    def reply(self, qid, answer):
        if answer not in ("yes", "no"):
            raise ApiError("answer 只能是 yes 或 no")
        with self.connect(True) as conn:
            q = self.require(conn, "inquiries", qid)
            if q["status"] != "pending" or q["expiresAt"] <= time.time():
                raise ApiError("该询问已回复或已超时", 409)
            conn.execute("UPDATE inquiries SET status='answered',answer=? WHERE id=?", (answer, qid))
            changes = {"status": "健在" if answer == "yes" else "已故"}
            if answer == "yes":
                changes["missedCount"] = 0
            self.update(conn, "users", q["userId"], changes)

    def confirm_dead(self, uid):
        with self.connect(True) as conn:
            self.require(conn, "users", uid)
            self.update(conn, "users", uid, {"status": "已故"})
            conn.execute("UPDATE inquiries SET status='expired' WHERE userId=? AND status='pending'", (uid,))

    def auto_send(self, enabled):
        if type(enabled) is not bool:
            raise ApiError("enabled 必须是布尔值")
        with self.connect(True) as conn:
            self.set_meta(conn, "auto_enabled", enabled)
            if enabled:
                self.set_meta(conn, "next_auto_at", time.time()+self.auto_interval)

    def sweep(self, now=None):
        now = time.time() if now is None else now
        with self.connect(True) as conn:
            for q in conn.execute("SELECT * FROM inquiries WHERE status='pending' AND expiresAt<=?", (now,)).fetchall():
                conn.execute("UPDATE inquiries SET status='expired' WHERE id=?", (q["id"],))
                user = self.require(conn, "users", q["userId"])
                missed = user["missedCount"]+1
                self.update(conn, "users", user["id"], {"missedCount": missed, "status": "疑似已故" if missed>=3 and user["status"]!="已故" else user["status"]})
            if now < self.meta(conn, "next_auto_at", now+self.auto_interval):
                return
            self.set_meta(conn, "next_auto_at", now+self.auto_interval)
            if not self.meta(conn, "auto_enabled", True):
                return
            ids = [row[0] for row in conn.execute("SELECT id FROM users ORDER BY id")]
            cursor = self.meta(conn, "auto_cursor", 0)
            sent = 0
            for offset in range(len(ids)):
                uid = ids[cursor % len(ids)]
                cursor += 1
                status = conn.execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone()[0]
                if status not in {"健在", "未知"} or conn.execute("SELECT 1 FROM inquiries WHERE userId=? AND status='pending'", (uid,)).fetchone():
                    continue
                self.send_sms(uid, DEFAULT_SMS, conn)
                sent += 1
                if sent >= self.auto_batch:
                    break
            self.set_meta(conn, "auto_cursor", cursor)

    @staticmethod
    def default_flow():
        return {"listed": False, "buyer": False, "decision": None, "scenario": 0}

    def overview(self):
        with self.connect() as conn:
            profiles = {}
            for row in conn.execute("SELECT * FROM market_profile_links"):
                profiles.setdefault(str(row["userId"]), {})[row["assetType"]] = self.catalog["profiles"][row["profileKey"]][row["assetType"]]
            return {"users": [self.user_projection(conn, row) for row in conn.execute("SELECT * FROM users ORDER BY id")], "catalog": {**self.catalog, "profiles": profiles}, "flows": {f'{row["userId"]}:{row["assetType"]}': json.loads(row["data"]) for row in conn.execute("SELECT * FROM market_flows")}, "revision": self.meta(conn, "revision", 0), "asOf": self.now_ms()}

    def market_flow(self, uid, kind, action):
        if kind not in ("item", "account") or action not in ("list", "buyer", "hold", "sell", "buyout", "revise", "reset", "scenario"):
            raise ApiError("操作或资产类型不合法")
        with self.connect(True) as conn:
            user = self.require(conn, "users", uid)
            if not conn.execute("SELECT 1 FROM market_profile_links WHERE userId=? AND assetType=?", (uid, kind)).fetchone():
                raise ApiError("该资产尚未配置演示行情", 404)
            if user["status"] != "已故" and action not in {"scenario", "reset"}:
                raise ApiError("客户池状态尚未进入遗产处置", 409)
            row = conn.execute("SELECT data FROM market_flows WHERE userId=? AND assetType=?", (uid, kind)).fetchone()
            flow = {**self.default_flow(), **(json.loads(row[0]) if row else {})}
            if action == "list":
                if flow["listed"]:
                    raise ApiError("该资产已模拟挂售", 409)
                flow["listed"] = True
            elif action == "buyer":
                if not flow["listed"] or flow["buyer"]:
                    raise ApiError("请先挂售，且不要重复创建买家意向", 409)
                flow["buyer"] = True
            elif action in {"hold", "sell", "buyout"}:
                if not flow["buyer"] or flow["decision"]:
                    raise ApiError("当前没有待继承人决定的买家意向", 409)
                flow["decision"] = action
            elif action == "revise":
                if not flow["decision"]:
                    raise ApiError("当前没有可重新选择的决定", 409)
                flow["decision"] = None
            elif action == "scenario":
                flow["scenario"] = (flow["scenario"]+1) % len(self.catalog["scenarios"])
            elif action == "reset":
                flow = self.default_flow()
            if action == "reset":
                conn.execute("DELETE FROM market_flows WHERE userId=? AND assetType=?", (uid, kind))
            else:
                flow["updatedAt"] = self.now_ms()
                conn.execute("INSERT INTO market_flows VALUES (?,?,?) ON CONFLICT(userId,assetType) DO UPDATE SET data=excluded.data", (uid, kind, json.dumps(flow)))
            revision = self.meta(conn, "revision", 0)+1
            self.set_meta(conn, "revision", revision)
            self.audit(conn, action, "market", uid)
            return {"ok": True, "flow": flow, "revision": revision}
