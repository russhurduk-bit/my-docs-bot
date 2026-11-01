import base64
import os
import secrets
import unittest
from unittest.mock import patch


class VaultKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("VAULT_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
        from services import vault

        cls.vault = vault

    def test_rejects_missing_key(self):
        with patch.dict(os.environ, {"VAULT_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "VAULT_KEY is required"):
                self.vault._load_key()

    def test_rejects_wrong_length(self):
        with patch.dict(os.environ, {"VAULT_KEY": base64.b64encode(b"short").decode()}):
            with self.assertRaisesRegex(RuntimeError, "32 bytes"):
                self.vault._load_key()

    def test_accepts_256_bit_key(self):
        key = secrets.token_bytes(32)
        with patch.dict(os.environ, {"VAULT_KEY": base64.b64encode(key).decode()}):
            self.assertEqual(self.vault._load_key(), key)
