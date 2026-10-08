"""Ensure migration redacts credentials and excludes unlisted user files."""
import json
import tempfile
import unittest
from pathlib import Path

from package_transfer import ROOT, allowed_user_file, sanitized_config


class TransferTests(unittest.TestCase):
    def test_redacts_all_config_credentials(self):
        sample = {
            "exchange": {"api_key": "exchange-key", "secret": "exchange-secret", "password": "pass"},
            "telegram": {"token": "telegram-token", "chat_id": "chat"},
            "api_server": {"password": "web-password", "jwt_secret_key": "jwt", "ws_token": "ws"},
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            cleaned = json.loads(sanitized_config(path))
        self.assertTrue(all(not value for section in cleaned.values() for value in section.values()))

    def test_unlisted_files_are_excluded(self):
        self.assertFalse(allowed_user_file(ROOT / "user_data" / "OKX_DEMO_KEYS.example.json"))
        self.assertFalse(allowed_user_file(ROOT / "user_data" / "market_data.sqlite"))


if __name__ == "__main__":
    unittest.main()
