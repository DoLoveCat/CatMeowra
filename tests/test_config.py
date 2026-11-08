import json
import tempfile
import unittest
from pathlib import Path

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_available_without_a_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.json")
        self.assertEqual(config["server"]["port"], 8000)
        self.assertEqual(config["recording"]["retention_days"], 5)

    def test_user_values_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"camera": {"index": 2}}), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config["camera"]["index"], 2)
        self.assertEqual(config["camera"]["width"], 1280)

    def test_unknown_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"camera": {"mystery": True}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown config key"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
