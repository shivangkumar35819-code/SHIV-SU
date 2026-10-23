"""License verification service. Run behind the supplied HTTPS reverse proxy."""
import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sqlite3
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

CHAT_ID = "7614397503"
TTL = 30
DB = os.environ.get("DATABASE_PATH", "data/licenses.sqlite3")


class Rejected(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS licenses (
          id TEXT PRIMARY KEY, device TEXT, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS challenges (
          id TEXT PRIMARY KEY, license TEXT UNIQUE, device TEXT, key TEXT,
          code TEXT, expires REAL, attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, license TEXT, device TEXT, key TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS rates (id TEXT PRIMARY KEY, time REAL);
        CREATE TABLE IF NOT EXISTS nonces (id TEXT PRIMARY KEY, expires REAL);
        """)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def code_hash(challenge, code):
    return hmac.new(os.environ["SERVER_SECRET"].encode(),
                    f"{challenge}:{code}".encode(), hashlib.sha256).hexdigest()


def public_key(encoded):
    try:
        key = serialization.load_der_public_key(base64.b64decode(encoded, validate=True))
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048:
            raise ValueError()
        return key
    except Exception:
        raise Rejected("invalid_request", 400) from None


def proof(key, signature, message):
    try:
        public_key(key).verify(base64.b64decode(signature, validate=True), message.encode(),
                               padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise Rejected("invalid_proof") from None


def location(ip):
    # No location permission or third-party IP lookup. Optional local GeoLite2 database.
    path = os.environ.get("GEOIP_DATABASE")
    if not path:
        return "Unavailable (IP location not configured)"
    try:
        import geoip2.database
        with geoip2.database.Reader(path) as reader:
            result = reader.city(ip)
            return ", ".join(filter(None, [result.city.name, result.country.name])) or "Unavailable"
    except Exception:
        return "Unavailable"


def send_code(code, ip, device):
    stamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M:%S %p IST")
    message = ("🔔 LOGIN VERIFICATION REQUEST\n━━━━━━━━━━━━━━━━━━━━\n"
               f"🌐 IP: {ip}\n📍 Location: {location(ip)}\n🕒 Date & time: {stamp}\n"
               f"📱 Device: {device}\n━━━━━━━━━━━━━━━━━━━━\n"
               f"🔐 Code: {code}\n⏳ Expires in 30 seconds")
    payload = json.dumps({"chat_id": CHAT_ID, "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if not json.load(response).get("ok"):
                raise ValueError()
    except Exception:
        # Never return/log Telegram URLs: they contain the bot secret.
        raise Rejected("delivery_failed", 503) from None


def request_code(data, ip):
    license_id = digest(data["license"])
    key = data["public_key"]
    public_key(key)
    device = digest(key)
    now = time.time()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM rates WHERE time<?", (now - 86400,))
        db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        db.execute("DELETE FROM challenges WHERE expires<?", (now,))
        for rate in ("ip:" + ip, "license:" + license_id):
            row = db.execute("SELECT time FROM rates WHERE id=?", (digest(rate),)).fetchone()
            if row and now - row[0] < TTL:
                db.rollback()
                raise Rejected("rate_limited", 429)
        for rate in ("ip:" + ip, "license:" + license_id):
            db.execute("INSERT OR REPLACE INTO rates VALUES (?,?)", (digest(rate), now))
        db.commit()
        row = db.execute("SELECT * FROM licenses WHERE id=?", (license_id,)).fetchone()
        if not row or row["revoked"]:
            raise Rejected("invalid_license")
        if row["device"] and row["device"] != device:
            raise Rejected("device_bound")
        challenge, code = secrets.token_urlsafe(24), f"{secrets.randbelow(1000000):06d}"
        # Invalidate the previous code before sending its replacement.
        db.execute("DELETE FROM challenges WHERE license=?", (license_id,))
        send_code(code, ip, data["device"].replace("\n", " ")[:100])
        # Expiry starts after Telegram accepts delivery; response carries remaining lifetime.
        expires = time.time() + TTL
        db.execute("INSERT INTO challenges VALUES (?,?,?,?,?,?,0)",
                   (challenge, license_id, device, key, code_hash(challenge, code), expires))
    return {"challenge": challenge, "expires_in": TTL}


def verify_code(data):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM challenges WHERE id=?", (data["challenge"],)).fetchone()
        if not row or time.time() >= row["expires"] or row["attempts"] >= 5:
            raise Rejected("code_expired")
        proof(row["key"], data["signature"], row["id"] + ":" + data["code"])
        if not hmac.compare_digest(row["code"], code_hash(row["id"], data["code"])):
            db.execute("UPDATE challenges SET attempts=attempts+1 WHERE id=?", (row["id"],))
            db.commit()
            raise Rejected("invalid_code")
        license_row = db.execute("SELECT * FROM licenses WHERE id=?", (row["license"],)).fetchone()
        if not license_row or license_row["revoked"]:
            raise Rejected("invalid_license")
        if license_row["device"] and license_row["device"] != row["device"]:
            raise Rejected("device_bound")
        db.execute("UPDATE licenses SET device=? WHERE id=?", (row["device"], row["license"]))
        db.execute("DELETE FROM challenges WHERE license=?", (row["license"],))
        db.execute("DELETE FROM sessions WHERE license=?", (row["license"],))
        token = secrets.token_urlsafe(48)
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (
            digest(token), row["license"], row["device"], row["key"], time.time() + 86400))
        db.commit()
    return {"token": token, "expires_in": 86400}


def validate_session(data):
    now = time.time()
    if abs(now - int(data["timestamp"])) > 60 or not 16 <= len(data["nonce"]) <= 100:
        raise Rejected("session_expired", 401)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT s.*, l.revoked, l.device AS bound FROM sessions s
                            JOIN licenses l ON l.id=s.license WHERE s.token=?""",
                         (digest(data["token"]),)).fetchone()
        if not row or row["expires"] <= now or row["revoked"] or row["bound"] != row["device"]:
            raise Rejected("session_expired", 401)
        proof(row["key"], data["signature"], ":".join([data["token"], data["timestamp"], data["nonce"]]))
        db.execute("DELETE FROM nonces WHERE expires<?", (now,))
        try:
            db.execute("INSERT INTO nonces VALUES (?,?)", (digest(data["token"] + data["nonce"]), now+120))
        except sqlite3.IntegrityError:
            raise Rejected("invalid_proof") from None
        db.commit()
    return {"valid": True}


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass  # No personal data, codes or secrets in request logs.

    def do_GET(self):
        payload = b'{"ok":true}' if self.path == "/healthz" else b'{"error":"not_found"}'
        self.send_response(200 if self.path == "/healthz" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        status = 200
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 12000:
                raise Rejected("invalid_request", 400)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or any(not isinstance(v, str) or len(v)>4096 for v in data.values()):
                raise Rejected("invalid_request", 400)
            ip = self.client_address[0]
            # Only the private Caddy container can connect in production.
            if os.environ.get("TRUST_PROXY") == "1":
                ip = self.headers.get("X-Forwarded-For", ip).split(",")[0].strip()
            ipaddress.ip_address(ip)
            if self.path == "/v1/request":
                result = request_code(data, ip)
            elif self.path == "/v1/verify":
                result = verify_code(data)
            elif self.path == "/v1/session":
                result = validate_session(data)
            else:
                raise Rejected("not_found", 404)
        except Rejected as e:
            status, result = e.status, {"error": e.code}
        except (ValueError, KeyError, TypeError):
            status, result = 400, {"error": "invalid_request"}
        except Exception:
            status, result = 503, {"error": "unavailable"}
        payload = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "create-license", "revoke", "reset-device"])
    parser.add_argument("--license")
    args = parser.parse_args()
    init_db()
    if args.command == "create-license":
        key = secrets.token_urlsafe(24)
        with connect() as db:
            db.execute("INSERT INTO licenses(id) VALUES (?)", (digest(key),))
        print(key)
    elif args.command in ("revoke", "reset-device"):
        if not args.license:
            parser.error("--license is required")
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if args.command == "revoke":
                db.execute("UPDATE licenses SET revoked=1 WHERE id=?", (digest(args.license),))
            else:
                db.execute("UPDATE licenses SET device=NULL WHERE id=?", (digest(args.license),))
            db.execute("DELETE FROM sessions WHERE license=?", (digest(args.license),))
            db.execute("DELETE FROM challenges WHERE license=?", (digest(args.license),))
            db.commit()
    else:
        if not os.environ.get("TELEGRAM_BOT_TOKEN") or len(os.environ.get("SERVER_SECRET", "")) < 32:
            parser.error("Configure TELEGRAM_BOT_TOKEN and a random SERVER_SECRET (32+ characters)")
        ThreadingHTTPServer((os.environ.get("BIND_HOST", "127.0.0.1"),
                             int(os.environ.get("BIND_PORT", "8080"))), Handler).serve_forever()
