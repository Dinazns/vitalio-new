"""Tests for field-level profile encryption."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet

from app import config
from app.services import field_encryption as fe
from app.services.field_encryption import encrypt_value, decrypt_value, encrypt_profile_fields, decrypt_profile_fields


class TestFieldEncryption(unittest.TestCase):
    def setUp(self):
        self._orig_key = config.FIELD_ENCRYPTION_KEY
        config.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")
        fe._fernet = None
        fe._warned_missing_key = False

    def tearDown(self):
        config.FIELD_ENCRYPTION_KEY = self._orig_key

        fe._fernet = None
        fe._warned_missing_key = False

    def test_roundtrip_scalar(self):
        plain = "+33601020304"
        enc = encrypt_value(plain)
        self.assertTrue(str(enc).startswith("enc:v1:"))
        self.assertEqual(decrypt_value(enc), plain)

    def test_plaintext_backward_compat(self):
        self.assertEqual(decrypt_value("hello"), "hello")

    def test_profile_fields_roundtrip(self):
        doc = {
            "phone": "0612345678",
            "address_line1": "12 rue Example",
            "emergency_contact": {"phone": "0698765432", "email": "a@b.com", "first_name": "Jean"},
        }
        stored = encrypt_profile_fields(doc)
        self.assertNotEqual(stored["phone"], doc["phone"])
        restored = decrypt_profile_fields(stored)
        self.assertEqual(restored["phone"], doc["phone"])
        self.assertEqual(restored["address_line1"], doc["address_line1"])
        self.assertEqual(restored["emergency_contact"]["email"], "a@b.com")


if __name__ == "__main__":
    unittest.main()
