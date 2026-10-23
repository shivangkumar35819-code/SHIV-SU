import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import server


class LoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = patch.object(server, "DB", self.temp.name + "/test.sqlite3")
        self.db.start()
        self.addCleanup(self.db.stop)
        self.environment = patch.dict(os.environ, {"SERVER_SECRET": "test-only-secret" * 4})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = patch.object(server.time, "time", return_value=1000)
        self.time = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.delivery = patch.object(server, "send_code")
        self.send = self.delivery.start()
        self.addCleanup(self.delivery.stop)
        server.init_db()
        self.license = "a-long-private-test-license"
        with server.connect() as db:
            db.execute("INSERT INTO licenses(id) VALUES (?)", (server.digest(self.license),))

    def key(self, index=0):
        return base64.b64encode(self.keys[index].public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()

    def sign(self, text, index=0):
        return base64.b64encode(self.keys[index].sign(text.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()

    def request(self, index=0):
        return server.request_code({"license": self.license, "public_key": self.key(index),
                                    "device": "Test device"}, "203.0.113.5")

    def verify(self, challenge, code=None, index=0):
        code = code if code is not None else self.send.call_args.args[0]
        return server.verify_code({"challenge": challenge, "code": code,
                                   "signature": self.sign(challenge + ":" + code, index)})

    def assert_rejected(self, reason, operation):
        with self.assertRaises(server.Rejected) as error:
            operation()
        self.assertEqual(reason, error.exception.code)

    def test_expiry_exactly_at_30_seconds(self):
        challenge = self.request()["challenge"]
        self.time.return_value = 1030
        self.assert_rejected("code_expired", lambda: self.verify(challenge))

    def test_valid_at_29_seconds_and_single_use(self):
        challenge = self.request()["challenge"]
        self.time.return_value = 1029
        self.assertIn("token", self.verify(challenge))
        self.assert_rejected("code_expired", lambda: self.verify(challenge))

    def test_second_device_refused(self):
        challenge = self.request()["challenge"]
        self.verify(challenge)
        self.time.return_value = 1031
        self.assert_rejected("device_bound", lambda: self.request(1))

    def test_rate_limit_and_replacement_code(self):
        old = self.request()["challenge"]
        self.assert_rejected("rate_limited", self.request)
        self.time.return_value = 1031
        new = self.request()["challenge"]
        self.assertNotEqual(new, old)
        self.assert_rejected("code_expired", lambda: self.verify(old))
        self.assertIn("token", self.verify(new))

    def test_five_wrong_attempts_lock_challenge(self):
        challenge = self.request()["challenge"]
        wrong = "999999" if self.send.call_args.args[0] != "999999" else "888888"
        for _ in range(5):
            self.assert_rejected("invalid_code", lambda: self.verify(challenge, wrong))
        self.assert_rejected("code_expired", lambda: self.verify(challenge))

    def test_stolen_code_without_device_key_rejected(self):
        challenge = self.request()["challenge"]
        self.assert_rejected("invalid_proof", lambda: self.verify(challenge, index=1))

    def test_session_proof_replay_and_revocation(self):
        token = self.verify(self.request()["challenge"])["token"]
        data = {"token": token, "timestamp": "1000", "nonce": "a-unique-random-test-nonce"}
        data["signature"] = self.sign(":".join(data.values()))
        self.assertTrue(server.validate_session(data)["valid"])
        self.assert_rejected("invalid_proof", lambda: server.validate_session(data))
        with server.connect() as db:
            db.execute("UPDATE licenses SET revoked=1")
        self.assert_rejected("session_expired", lambda: server.validate_session(data))

    def test_delivery_failure_creates_no_challenge(self):
        self.send.side_effect = server.Rejected("delivery_failed", 503)
        self.assert_rejected("delivery_failed", self.request)
        with server.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM challenges").fetchone()[0])

    def test_only_fixed_recipient_and_expected_message_fields(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return b'{"ok":true}'
        import json
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-placeholder"}), \
             patch.object(server.urllib.request, "urlopen", return_value=Response()) as urlopen:
            # The production function is mocked elsewhere in tests; invoke its original here.
            self.delivery.stop()
            server.send_code("123456", "203.0.113.5", "Test device")
            data = json.loads(urlopen.call_args.args[0].data)
            self.assertEqual("7614397503", data["chat_id"])
            for field in ("LOGIN VERIFICATION REQUEST", "IP:", "Location:", "Date & time:", "Device:", "123456", "30 seconds"):
                self.assertIn(field, data["text"])


if __name__ == "__main__":
    unittest.main()
