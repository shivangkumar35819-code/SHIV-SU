import os
import tempfile
import unittest
from unittest.mock import patch

import admin_bot
import server


class AdminBotTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        database = patch.object(server, "DB", os.path.join(folder.name, "licenses.sqlite3"))
        database.start()
        self.addCleanup(database.stop)
        network = patch.object(admin_bot, "telegram", return_value={"message_id": 1})
        self.network = network.start()
        self.addCleanup(network.stop)
        self.bot = admin_bot.AdminBot("test-token", "123", "test-secret" * 5)

    def update(self, text, number=1, sender=123, chat=123, kind="private"):
        return {"update_id": number, "message": {"text": text,
                "from": {"id": sender}, "chat": {"id": chat, "type": kind}}}

    def reply(self):
        return self.network.call_args.args[2]["text"]

    def test_only_owner_private_messages_are_accepted(self):
        for update in (self.update("/genkey", sender=999),
                       self.update("/genkey", chat=999),
                       self.update("/genkey", kind="group")):
            self.bot.process(update)
        self.network.assert_not_called()
        with server.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM licenses").fetchone()[0])

    def test_custom_key_wizard_and_duplicate(self):
        self.bot.process(self.update("/custom"))
        self.bot.process(self.update("Rahul123", 2))
        self.assertIn("\nRahul123\n", self.reply())
        self.bot.process(self.update("/custom Rahul123", 3))
        self.assertIn("already exists", self.reply())
        with server.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM licenses").fetchone()[0])

    def test_random_key_retry_is_atomic_and_reply_is_encrypted(self):
        self.network.side_effect = RuntimeError("delivery failed")
        update = self.update("/genkey")
        with self.assertRaises(RuntimeError):
            self.bot.process(update)
        original_reply = self.reply()
        key = original_reply.splitlines()[1]
        with server.connect() as db:
            stored = db.execute("SELECT reply,delivered FROM bot_replies").fetchone()
            self.assertNotIn(key.encode(), stored["reply"])
            self.assertEqual(0, stored["delivered"])
        self.network.side_effect = None
        self.bot.process(update)
        self.assertEqual(original_reply, self.reply())
        self.network.reset_mock()
        self.bot.process(update)
        self.network.assert_not_called()
        with server.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM licenses").fetchone()[0])

    def test_list_status_reset_and_revoke_use_same_database(self):
        server.create_license("ExactKey")
        license_id = server.digest("ExactKey")
        with server.connect() as db:
            db.execute("UPDATE licenses SET device='device' WHERE id=?", (license_id,))
            db.execute("INSERT INTO sessions VALUES ('token',?,'device','key',999999)", (license_id,))
            db.execute("INSERT INTO challenges VALUES ('challenge',?,'device','key','code',999999,0)",
                       (license_id,))
        self.bot.process(self.update("/list"))
        self.assertIn("id:" + license_id, self.reply())
        self.bot.process(self.update("/reset id:" + license_id, 2))
        with server.connect() as db:
            self.assertIsNone(db.execute("SELECT device FROM licenses").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM challenges").fetchone()[0])
        self.bot.process(self.update("/revoke ExactKey", 3))
        self.bot.process(self.update("/status ExactKey", 4))
        self.assertIn("revoked", self.reply())
        self.bot.process(self.update("/custom ExactKey", 5))
        self.assertIn("already exists", self.reply())

    def test_invalid_input_and_cancel_do_not_create_keys(self):
        for number, text in enumerate(("/custom", "/cancel", "ignored", "/custom bad\nkey",
                                      "/revoke", "/list -1", "/reset id:bad"), 1):
            self.bot.process(self.update(text, number))
        with server.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM licenses").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
