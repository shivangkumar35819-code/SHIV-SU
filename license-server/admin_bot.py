"""Private Telegram administration of the existing license database.

No inbound port is required. Run one poller per bot token alongside server.py.
"""
import base64
import hashlib
import json
import os
import re
import time
import urllib.request

from cryptography.fernet import Fernet

import server


HELP = """SHIV KSU - License Manager

/genkey - Generate a random key
/custom Rahul123 - Create exactly Rahul123
/status Rahul123 - Check a key
/list - Show licenses (20 per page)
/revoke Rahul123 - Block future logins
/reset Rahul123 - Allow a replacement device
/cancel - Cancel custom key entry

Keys are case-sensitive. List entries use hashed IDs; use id:HASH instead of a key to manage a listed entry.
Login is saved in the current app: revoking or resetting blocks future verification, but cannot sign out an already activated offline app."""

KEYBOARD = {"keyboard": [["/genkey", "/custom"], ["/list", "/help"]],
            "resize_keyboard": True, "is_persistent": True}


def telegram(token, method, payload):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.load(response)
            if not result.get("ok"):
                raise ValueError()
            return result["result"]
    except Exception:
        # Exception messages from urllib contain the token-bearing URL.
        raise RuntimeError("Telegram request failed; check connectivity and bot configuration") from None


class AdminBot:
    def __init__(self, token, admin_id, secret):
        if not token or not str(admin_id).isdigit() or int(admin_id) <= 0 or len(secret) < 32:
            raise ValueError("Configure ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_ID and SERVER_SECRET (32+ characters)")
        self.token = token
        self.admin_id = int(admin_id)
        self.identity = hashlib.sha256(token.encode()).hexdigest()
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
        server.init_db()
        with server.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bot_replies (
                    bot TEXT NOT NULL, update_id INTEGER NOT NULL,
                    reply BLOB NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(bot, update_id));
                CREATE TABLE IF NOT EXISTS bot_state (
                    bot TEXT PRIMARY KEY, waiting_custom INTEGER NOT NULL DEFAULT 0);
            """)

    def allowed(self, message):
        return (message.get("chat", {}).get("type") == "private"
                and message.get("chat", {}).get("id") == self.admin_id
                and message.get("from", {}).get("id") == self.admin_id
                and not message.get("from", {}).get("is_bot", False))

    def command(self, db, text):
        parts = text.strip().split(maxsplit=1)
        if not parts:
            return HELP
        command = parts[0].split("@", 1)[0].lower()
        argument = parts[1] if len(parts) > 1 else ""
        if command in ("/start", "/help", "/cancel"):
            db.execute("INSERT OR REPLACE INTO bot_state VALUES (?,0)", (self.identity,))
            return HELP if command != "/cancel" else "Cancelled."
        if command in ("/custom", "/key") and not argument:
            db.execute("INSERT OR REPLACE INTO bot_state VALUES (?,1)", (self.identity,))
            return "Send your exact custom key as the next message, or /cancel."
        waiting = db.execute("SELECT waiting_custom FROM bot_state WHERE bot=?", (self.identity,)).fetchone()
        if not text.startswith("/") and waiting and waiting[0]:
            command, argument = "/custom", text
        if command in ("/genkey", "/custom", "/key"):
            try:
                key = server.create_license(argument if argument else None, connection=db)
            except ValueError as error:
                return str(error)
            db.execute("INSERT OR REPLACE INTO bot_state VALUES (?,0)", (self.identity,))
            return f"Key created:\n{key}\n\nOne device. Copy the complete key into the app."
        if command == "/list":
            if argument and (not argument.isdigit() or len(argument) > 6):
                return "Usage: /list PAGE (starting at 1)"
            page = int(argument or "1")
            if page < 1:
                return "Page must be at least 1."
            rows = db.execute("SELECT id,device,revoked FROM licenses ORDER BY id LIMIT 21 OFFSET ?",
                              ((page - 1) * 20,)).fetchall()
            if not rows:
                return "No licenses on this page."
            lines = [f"Licenses - page {page}"]
            for row in rows[:20]:
                state = "revoked" if row["revoked"] else "bound" if row["device"] else "unused"
                lines.append(f"id:{row['id']}  {state}")
            if len(rows) > 20:
                lines.append(f"Next: /list {page + 1}")
            return "\n".join(lines)
        if command in ("/status", "/revoke", "/reset"):
            if not argument:
                return f"Usage: {command} KEY or {command} id:HASH"
            if argument.startswith("id:"):
                license_id = argument[3:]
                if not re.fullmatch(r"[0-9a-f]{64}", license_id):
                    return "Use the complete id:HASH from /list."
            else:
                license_id = server.digest(argument)
            row = db.execute("SELECT * FROM licenses WHERE id=?", (license_id,)).fetchone()
            if not row:
                return "License not found."
            if command == "/status":
                return (f"id:{license_id}\nStatus: {'revoked' if row['revoked'] else 'active'}"
                        f"\nDevice: {'bound' if row['device'] else 'unused'}")
            if command == "/revoke":
                db.execute("UPDATE licenses SET revoked=1 WHERE id=?", (license_id,))
            else:
                db.execute("UPDATE licenses SET device=NULL WHERE id=?", (license_id,))
            db.execute("DELETE FROM sessions WHERE license=?", (license_id,))
            db.execute("DELETE FROM challenges WHERE license=?", (license_id,))
            return ("License revoked for future logins." if command == "/revoke"
                    else "Device binding reset. Revoked licenses remain revoked.")
        return "Unknown command. Send /help."

    def process(self, update):
        message = update.get("message", {})
        if not self.allowed(message) or not isinstance(message.get("text"), str):
            return
        update_id = update["update_id"]
        # Mutation and encrypted reply commit together. Retries reuse the same key.
        with server.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reply,delivered FROM bot_replies WHERE bot=? AND update_id=?",
                             (self.identity, update_id)).fetchone()
            if row and row["delivered"]:
                return
            if row:
                reply = self.cipher.decrypt(row["reply"]).decode()
            else:
                reply = self.command(db, message["text"])
                db.execute("INSERT INTO bot_replies(bot,update_id,reply) VALUES (?,?,?)",
                           (self.identity, update_id, self.cipher.encrypt(reply.encode())))
            db.commit()
        telegram(self.token, "sendMessage", {"chat_id": self.admin_id, "text": reply,
                 "reply_markup": KEYBOARD})
        with server.connect() as db:
            db.execute("UPDATE bot_replies SET delivered=1 WHERE bot=? AND update_id=?",
                       (self.identity, update_id))
            # Keep the newest processed update for the restart offset; purge old secrets.
            db.execute("DELETE FROM bot_replies WHERE bot=? AND delivered=1 AND update_id<?",
                       (self.identity, update_id))

    def run(self):
        with server.connect() as db:
            row = db.execute("SELECT MAX(update_id) FROM bot_replies WHERE bot=? AND delivered=1",
                             (self.identity,)).fetchone()
        offset = (row[0] + 1) if row[0] is not None else 0
        while True:
            try:
                updates = telegram(self.token, "getUpdates", {
                    "offset": offset, "timeout": 25, "allowed_updates": ["message"]})
                for update in updates:
                    self.process(update)
                    offset = update["update_id"] + 1
            except Exception:
                print("Admin bot operation failed; retrying without logging private data.", flush=True)
                time.sleep(5)


if __name__ == "__main__":
    AdminBot(os.environ.get("ADMIN_BOT_TOKEN", ""), os.environ.get("TELEGRAM_ADMIN_ID", ""),
             os.environ.get("SERVER_SECRET", "")).run()
