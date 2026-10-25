"""Nastavení pluginů v ~/.config/<shell>/plugins/config/<plugin>.json a migrace ze starého config.json."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_core import MANIFEST  # noqa: E402
from leapsh.config import Config  # noqa: E402
from leapsh.settings import parse_value  # noqa: E402
from leapsh.shell import Shell  # noqa: E402


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.old = os.environ.get("LEAPSH_HOME")
        os.environ["LEAPSH_HOME"] = str(self.home)

    def tearDown(self):
        os.environ["LEAPSH_HOME"] = self.old
        shutil.rmtree(self.home, ignore_errors=True)

    def shell(self):
        sh = Shell(Config(self.home / "config.json"))
        sh.manager.load_all()
        sh.say = lambda *a, **k: None
        return sh

    def test_file_location_and_defaults(self):
        sh = self.shell()
        p = sh.manager.loaded["cmd_timer"]
        self.assertEqual(p.setting("threshold"), 3)                          # výchozí z config.json pluginu
        sh.run_line("plugin set cmd_timer threshold 7")
        f = self.home / "plugins" / "config" / "cmd_timer.json"
        self.assertEqual(json.loads(f.read_text()), {"threshold": 7})        # vlastní soubor v plugins/config/
        self.assertEqual(p.setting("threshold"), 7)
        sh.run_line("plugin unset cmd_timer threshold")
        self.assertFalse(f.exists())
        self.assertEqual(p.setting("threshold"), 3)

    def test_typed_values_are_enforced(self):
        sh = self.shell()
        self.assertEqual(sh.run_line("plugin set cmd_timer threshold abc"), 1)     # číslo čekáme
        self.assertEqual(sh.run_line("plugin set git_prompt dirty maybe"), 1)      # bool čekáme
        self.assertEqual(sh.run_line("plugin set git_prompt dirty ne"), 0)
        self.assertIs(sh.manager.loaded["git_prompt"].setting("dirty"), False)
        self.assertEqual(sh.run_line("plugin set git_prompt color blue"), 0)
        self.assertEqual(sh.manager.loaded["git_prompt"].setting("color"), "blue")

    def test_migration_from_old_config_json(self):
        (self.home / "config.json").write_text(json.dumps({"theme": "mono", "settings": {"cmd_timer": {"threshold": 9}}}))
        (self.home / "plugins" / "config").mkdir(parents=True)
        (self.home / "plugins" / "config" / "arcade.json").write_text('{"idle_seconds": 5}')
        sh = self.shell()
        self.assertEqual(sh.manager.loaded["cmd_timer"].setting("threshold"), 9)
        self.assertNotIn("settings", json.loads((self.home / "config.json").read_text()))   # ze config.json zmizelo
        self.assertEqual(json.loads((self.home / "plugins" / "config" / "arcade.json").read_text()), {"idle_seconds": 5})

    def test_config_folder_is_not_a_plugin_and_name_is_reserved(self):
        sh = self.shell()
        (self.home / "plugins" / "config").mkdir(parents=True, exist_ok=True)
        (self.home / "plugins" / "config" / MANIFEST).write_text('{"name": "config"}')   # i kdyby tam byl manifest
        sh.manager.discover()
        self.assertNotIn("config", sh.manager.found)
        self.assertEqual(sh.run_line("plugin create config"), 1)

    def test_change_event_and_wasm_setting(self):
        sh = self.shell()
        seen = []
        sh.events.on("plugin_setting_change", lambda e: seen.append((e.plugin, e.key, e.old, e.new)))
        sh.run_line("plugin set cmd_timer threshold 4")
        sh.run_line("plugin set cmd_timer threshold 6")
        self.assertEqual(seen, [("cmd_timer", "threshold", None, 4), ("cmd_timer", "threshold", 4, 6)])

    def test_parse_value(self):
        self.assertIs(parse_value("ano", True), True)
        self.assertEqual(parse_value("12", 3), 12)
        self.assertEqual(parse_value("0.5", 1.0), 0.5)
        self.assertEqual(parse_value("true", "text"), "true")             # u textu zůstane text
        self.assertEqual(parse_value('["a"]', []), ["a"])
        with self.assertRaises(ValueError):
            parse_value("{}", [])
        self.assertEqual(parse_value("42", None), 42)
        self.assertEqual(parse_value("ahoj", None), "ahoj")


if __name__ == "__main__":
    unittest.main(verbosity=2)
