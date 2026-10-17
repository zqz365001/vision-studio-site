"""Small WSGI API and administrator interface for the vision studio site.

Python 3.11+, standard library only. Configure environment as described in README.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs


HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(HERE / "data" / "site.db")))
PUBLIC_ORIGINS = frozenset(
    origin.strip().rstrip("/")
    for origin in os.environ.get("PUBLIC_ORIGINS", "https://zqz365001.github.io").split(",")
    if origin.strip()
)
APP_ORIGIN = os.environ.get("APP_ORIGIN", "").rstrip("/")
SESSION_SECONDS = 8 * 60 * 60
STATUSES = {"new", "contacted", "closed"}
TYPES = {"vision", "sop"}
MAX_BODY = 16 * 1024


SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS inquiries (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    contact TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL CHECK(type IN ('vision', 'sop')),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'contacted', 'closed')),
    note TEXT NOT NULL DEFAULT '',
    ip_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS inquiries_created_at_idx ON inquiries(created_at DESC);
CREATE INDEX IF NOT EXISTS inquiries_ip_time_idx ON inquiries(ip_hash, created_at);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS rate_limits (
    scope TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    occurred_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_limits_lookup_idx ON rate_limits(scope, ip_hash, occurred_at);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


@contextmanager
def db():
    con = connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript(SCHEMA)


def create_admin():
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise ValueError("ADMIN_USERNAME must be 3-40 letters, digits, _, . or -")
    if len(password) < 14:
        raise ValueError("ADMIN_PASSWORD must have at least 14 characters")
    init_db()
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    with db() as con:
        con.execute(
            "INSERT INTO admins(username, password_salt, password_hash, created_at) VALUES(?,?,?,?)",
            (username, salt, password_hash, int(time.time())),
        )
    print("Administrator created. Clear ADMIN_PASSWORD from the environment now.")


class RequestError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def response(start_response, status, body=b"", content_type="application/json; charset=utf-8", headers=()):
    base = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
        ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"),
    ]
    start_response(status, base + list(headers))
    return [body]


def json_response(start_response, status, data, headers=()):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return response(start_response, status, body, headers=headers)


def read_json(environ):
    if environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower() != "application/json":
        raise RequestError("415 Unsupported Media Type", "需要 JSON 格式")
    try:
        size = int(environ.get("CONTENT_LENGTH", ""))
    except ValueError:
        raise RequestError("411 Length Required", "请求长度无效") from None
    if size <= 0 or size > MAX_BODY:
        raise RequestError("413 Payload Too Large", "请求内容过大或为空")
    try:
        data = json.loads(environ["wsgi.input"].read(size))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RequestError("400 Bad Request", "JSON 内容无效") from None
    if not isinstance(data, dict):
        raise RequestError("400 Bad Request", "需要 JSON 对象")
    return data


def field(data, key, maximum, required=False):
    value = data.get(key, "")
    if not isinstance(value, str):
        raise RequestError("400 Bad Request", f"{key} 格式无效")
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise RequestError("400 Bad Request", f"{key} 长度或内容无效")
    return value


def ip_hash(environ):
    # REMOTE_ADDR is supplied by the trusted WSGI server; never trust client X-Forwarded-For.
    secret = os.environ.get("RATE_LIMIT_SECRET", "")
    if len(secret) < 32:
        raise RequestError("503 Service Unavailable", "服务尚未配置")
    ip = environ.get("REMOTE_ADDR", "unknown")
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()


def consume_rate_limit(con, scope, key, limit, seconds):
    now = int(time.time())
    con.execute("DELETE FROM rate_limits WHERE occurred_at < ?", (now - 86400,))
    count = con.execute(
        "SELECT COUNT(*) FROM rate_limits WHERE scope=? AND ip_hash=? AND occurred_at>=?",
        (scope, key, now - seconds),
    ).fetchone()[0]
    if count >= limit:
        raise RequestError("429 Too Many Requests", "请求过于频繁，请稍后再试")
    con.execute("INSERT INTO rate_limits(scope, ip_hash, occurred_at) VALUES(?,?,?)", (scope, key, now))


def public_headers(origin):
    return (
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Methods", "POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Vary", "Origin"),
    )


def check_public_origin(environ):
    origin = environ.get("HTTP_ORIGIN", "")
    if origin not in PUBLIC_ORIGINS:
        raise RequestError("403 Forbidden", "来源不允许")
    return origin


def require_admin_origin(environ):
    if not APP_ORIGIN or environ.get("HTTP_ORIGIN", "") != APP_ORIGIN:
        raise RequestError("403 Forbidden", "来源不允许")


def require_session(environ, csrf=False):
    cookie = SimpleCookie()
    try:
        cookie.load(environ.get("HTTP_COOKIE", ""))
    except Exception:
        pass
    token = cookie.get("vision_admin")
    if not token:
        raise RequestError("401 Unauthorized", "请先登录")
    token_hash = hashlib.sha256(token.value.encode()).hexdigest()
    with db() as con:
        row = con.execute(
            "SELECT sessions.*, admins.username FROM sessions JOIN admins ON admins.id=sessions.admin_id "
            "WHERE token_hash=? AND expires_at>?",
            (token_hash, int(time.time())),
        ).fetchone()
    if row is None:
        raise RequestError("401 Unauthorized", "登录已过期")
    if csrf:
        require_admin_origin(environ)
        if not hmac.compare_digest(environ.get("HTTP_X_CSRF_TOKEN", ""), row["csrf_token"]):
            raise RequestError("403 Forbidden", "请求验证失败")
    return row


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def inquiry_dict(row, detail=False):
    data = {key: row[key] for key in ("id", "name", "contact", "company", "type", "status")}
    data["created_at"] = iso(row["created_at"])
    data["updated_at"] = iso(row["updated_at"])
    if detail:
        data["description"] = row["description"]
        data["note"] = row["note"]
    return data


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "")
    try:
        if path in ("/admin", "/admin/") and method == "GET":
            return response(start_response, "200 OK", (HERE / "admin.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/admin/admin.js" and method == "GET":
            return response(start_response, "200 OK", (HERE / "admin.js").read_bytes(), "text/javascript; charset=utf-8")
        if path == "/admin/admin.css" and method == "GET":
            return response(start_response, "200 OK", (HERE / "admin.css").read_bytes(), "text/css; charset=utf-8")

        if path == "/api/inquiries":
            origin = check_public_origin(environ)
            headers = public_headers(origin)
            if method == "OPTIONS":
                return response(start_response, "204 No Content", headers=headers)
            if method != "POST":
                raise RequestError("405 Method Not Allowed", "请求方法无效")
            data = read_json(environ)
            if field(data, "website", 200):
                return json_response(start_response, "202 Accepted", {"ok": True}, headers)
            name = field(data, "name", 80, True)
            contact = field(data, "contact", 120, True)
            if len(contact) < 3:
                raise RequestError("400 Bad Request", "联系方式过短")
            company = field(data, "company", 120)
            kind = field(data, "type", 20, True)
            if kind not in TYPES:
                raise RequestError("400 Bad Request", "咨询类型无效")
            description = field(data, "description", 3000, True)
            if len(description) < 10:
                raise RequestError("400 Bad Request", "需求描述至少 10 字")
            if data.get("consent") is not True:
                raise RequestError("400 Bad Request", "需要同意信息用于联系")
            key = ip_hash(environ)
            now = int(time.time())
            with db() as con:
                con.execute("BEGIN IMMEDIATE")
                consume_rate_limit(con, "inquiry", key, 5, 3600)
                con.execute(
                    "INSERT INTO inquiries(name, contact, company, type, description, ip_hash, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (name, contact, company, kind, description, key, now, now),
                )
            return json_response(start_response, "201 Created", {"ok": True}, headers)

        if path == "/api/admin/login" and method == "POST":
            require_admin_origin(environ)
            data = read_json(environ)
            username = field(data, "username", 40)
            password = data.get("password", "")
            if not isinstance(password, str) or len(password) > 256:
                raise RequestError("400 Bad Request", "登录信息无效")
            key = ip_hash(environ)
            with db() as con:
                con.execute("BEGIN IMMEDIATE")
                consume_rate_limit(con, "login", key, 10, 900)
                row = con.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            # Make unknown users take approximately the same PBKDF2 path.
            salt = row["password_salt"] if row else b"\0" * 16
            expected = row["password_hash"] if row else b"\0" * 32
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
            if not hmac.compare_digest(actual, expected) or row is None:
                raise RequestError("401 Unauthorized", "账号或密码错误")
            token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = int(time.time()) + SESSION_SECONDS
            with db() as con:
                con.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
                con.execute(
                    "INSERT INTO sessions(token_hash, admin_id, csrf_token, expires_at) VALUES(?,?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), row["id"], csrf_token, expires_at),
                )
            cookie = f"vision_admin={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={SESSION_SECONDS}"
            return json_response(start_response, "200 OK", {"username": row["username"], "csrf_token": csrf_token}, (("Set-Cookie", cookie),))

        if path == "/api/admin/me" and method == "GET":
            session = require_session(environ)
            return json_response(start_response, "200 OK", {"username": session["username"], "csrf_token": session["csrf_token"]})

        if path == "/api/admin/logout" and method == "POST":
            session = require_session(environ, csrf=True)
            with db() as con:
                con.execute("DELETE FROM sessions WHERE token_hash=?", (session["token_hash"],))
            return json_response(start_response, "200 OK", {"ok": True}, (("Set-Cookie", "vision_admin=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"),))

        if path == "/api/admin/summary" and method == "GET":
            require_session(environ)
            with db() as con:
                counts = {row["status"]: row["n"] for row in con.execute("SELECT status, COUNT(*) n FROM inquiries GROUP BY status")}
            return json_response(start_response, "200 OK", {"total": sum(counts.values()), "new": counts.get("new", 0), "contacted": counts.get("contacted", 0), "closed": counts.get("closed", 0)})

        if path == "/api/admin/inquiries" and method == "GET":
            require_session(environ)
            query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
            status = query.get("status", [""])[0]
            kind = query.get("type", [""])[0]
            if status and status not in STATUSES or kind and kind not in TYPES:
                raise RequestError("400 Bad Request", "筛选条件无效")
            sql = "SELECT * FROM inquiries WHERE 1=1"
            params = []
            if status:
                sql += " AND status=?"
                params.append(status)
            if kind:
                sql += " AND type=?"
                params.append(kind)
            sql += " ORDER BY created_at DESC, id DESC LIMIT 200"
            with db() as con:
                rows = con.execute(sql, params).fetchall()
            return json_response(start_response, "200 OK", {"items": [inquiry_dict(row) for row in rows]})

        match = re.fullmatch(r"/api/admin/inquiries/([1-9][0-9]{0,17})", path)
        if match and method in ("GET", "PATCH"):
            inquiry_id = int(match.group(1))
            if method == "GET":
                require_session(environ)
                with db() as con:
                    row = con.execute("SELECT * FROM inquiries WHERE id=?", (inquiry_id,)).fetchone()
            else:
                require_session(environ, csrf=True)
                data = read_json(environ)
                if not data or set(data) - {"status", "note"}:
                    raise RequestError("400 Bad Request", "更新内容无效")
                updates = []
                params = []
                if "status" in data:
                    status = field(data, "status", 20, True)
                    if status not in STATUSES:
                        raise RequestError("400 Bad Request", "状态无效")
                    updates.append("status=?")
                    params.append(status)
                if "note" in data:
                    updates.append("note=?")
                    params.append(field(data, "note", 4000))
                updates.append("updated_at=?")
                params.append(int(time.time()))
                params.append(inquiry_id)
                with db() as con:
                    con.execute(f"UPDATE inquiries SET {', '.join(updates)} WHERE id=?", params)
                    row = con.execute("SELECT * FROM inquiries WHERE id=?", (inquiry_id,)).fetchone()
            if row is None:
                raise RequestError("404 Not Found", "咨询不存在")
            return json_response(start_response, "200 OK", inquiry_dict(row, True))

        raise RequestError("404 Not Found", "页面不存在")
    except RequestError as exc:
        headers = ()
        if path == "/api/inquiries":
            origin = environ.get("HTTP_ORIGIN", "")
            if origin in PUBLIC_ORIGINS:
                headers = public_headers(origin)
        return json_response(start_response, exc.status, {"error": exc.message}, headers)
    except (sqlite3.Error, OSError):
        return json_response(start_response, "503 Service Unavailable", {"error": "服务暂不可用"})


if __name__ == "__main__":
    if sys.argv[1:] == ["init-db"]:
        init_db()
        print("Database initialized.")
    elif sys.argv[1:] == ["create-admin"]:
        create_admin()
    else:
        raise SystemExit("Usage: python app.py init-db | create-admin")
