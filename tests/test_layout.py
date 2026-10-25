"""Formát pluginů (složka / config.json / src/), témata, oprávnění, řetězení příkazů a drobnosti jádra."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_core import MANIFEST, ROOT, TMP_HOME, TestInteractive, new_shell  # noqa: E402


def run_env(cmd, home, *flags, **extra):
    env = dict(os.environ, HOME=home, LEAPSH_HOME=home + "/cfg", PYTHONPATH=str(ROOT), **extra)
    return subprocess.run([sys.executable, "-m", "leapsh", *flags, "-c", cmd], capture_output=True, text=True,
                          env=env, timeout=30)


class TestLayout(unittest.TestCase):
    def test_every_bundled_extension_uses_the_layout(self):
        for sub in ("plugins", "addons"):
            for d in (ROOT / sub).iterdir():
                self.assertTrue((d / MANIFEST).is_file(), d)
                self.assertFalse(list(d.glob("*.py")), f"{d}: kód patří do src/")
                m = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
                if m.get("type") != "theme" and m.get("runtime") != "wasm":
                    from leapsh.loader import entry_file
                    self.assertTrue(entry_file(d / "src", m, m["name"]).is_file(), d)   # libovolné jméno .py

    def test_src_is_a_package_relative_imports_work_and_reload_is_clean(self):
        d = Path(TMP_HOME) / "plugins" / "multi"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / MANIFEST).write_text(json.dumps({"name": "multi"}))
        (d / "src" / "helper.py").write_text("VALUE = 'v1'\n")
        (d / "src" / "main.py").write_text(
            "from leapsh.api import Plugin\nfrom .helper import VALUE\n"
            "class Multi(Plugin):\n    def on_load(self):\n        self.add_command('multi', lambda sh, a: sh.say(VALUE) or 0)\n")
        try:
            sh = new_shell()
            self.assertEqual(sh.manager.status["multi"], "loaded", sh.manager.status["multi"])
            (d / "src" / "helper.py").write_text("VALUE = 'v2'\n")
            sh.manager.reload_all()
            out = []
            sh.say = out.append
            sh.run_line("multi")
            self.assertEqual(out, ["v2"])
            self.assertFalse(list(d.rglob("*.pyc")), "plugin nesmí zanechávat .pyc")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_create_makes_folder_json_src(self):
        sh = new_shell()
        self.assertEqual(sh.run_line("plugin create layout_demo"), 0)
        d = Path(TMP_HOME) / "plugins" / "layout_demo"
        self.assertTrue((d / MANIFEST).is_file() and (d / "src" / "main.py").is_file())
        self.assertIn("layout_demo", sh.manager.loaded)
        shutil.rmtree(d, ignore_errors=True)

    def test_create_wasm_builds_the_module(self):
        sh = new_shell()
        self.assertEqual(sh.run_line("plugin create wasm_build_demo --wasm"), 0)
        d = Path(TMP_HOME) / "plugins" / "wasm_build_demo"
        try:
            self.assertTrue((d / "src" / "plugin.wasm").is_file())
            self.assertIn("wasm_build_demo", sh.manager.loaded)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_theme_pack_and_perf_telemetry(self):
        sh = new_shell()
        for t in ("rounded", "hacker", "mono", "cyberpunk", "grid", "classic", "neon", "minimal", "dracula"):
            self.assertIn(t, sh.themes)
            sh.config.data["theme"] = t
            self.assertTrue(sh.render_prompt()[1], t)
        sh.config.data["theme"] = "rounded"
        sh.last_rc, sh.last_duration = 3, 0.25
        head, last, _ = sh.render_prompt()
        self.assertIn("✗ 3", head)
        self.assertIn("250ms", head)
        self.assertEqual(sh.config.data["theme"], "rounded")

    def test_theme_as_function(self):
        sh = new_shell()
        sh.add_theme("fn", {"prompt_fn": lambda u, c, g, p: f"\nFN[{u}]\n>> "}, owner="test")
        sh.config.data["theme"] = "fn"
        head, last, _ = sh.render_prompt()
        self.assertIn("FN[", head)
        self.assertEqual(last, ">> ")

    def test_xapi_permissions(self):
        sh = new_shell()
        x = sh.manager.loaded["toolbox"].xapi
        self.assertEqual(x.battery(), "N/A")                     # bez terminálu = zamítnuto
        self.assertEqual(sh.config.data["permissions"], {})      # a nic se neuložilo
        sh.config.data["permissions"] = {"toolbox": {"read_language": True, "read_theme": False}}
        self.assertEqual(x.lang(), "cs")
        self.assertEqual(x.theme(), "N/A")
        sh.run_line("plugin revoke toolbox read_theme")
        self.assertNotIn("read_theme", sh.config.data["permissions"]["toolbox"])


class TestShellBits(unittest.TestCase):
    def test_chain_commands_get_their_own_hooks(self):
        home = tempfile.mkdtemp()
        try:
            r = run_env("sl /tmp > /dev/null; plugin list | head -1; gti --version | head -1", home)
            self.assertIn("↪ ls /tmp", r.stdout)
            self.assertIn("↪ git --version", r.stdout)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_dev_mode_loads_plugins_dev(self):
        home = tempfile.mkdtemp()
        d = Path(home) / "cfg" / "plugins-dev" / "devp" / "src"
        d.mkdir(parents=True)
        (d.parent / MANIFEST).write_text(json.dumps({"name": "devp"}))
        (d / "main.py").write_text("from leapsh.api import Plugin\nclass D(Plugin):\n    def on_load(self):\n"
                                   "        self.add_command('devp', lambda sh, a: sh.say('dev-ok') or 0)\n")
        try:
            self.assertNotIn("dev-ok", run_env("devp", home).stdout)
            self.assertIn("dev-ok", run_env("devp", home, "--dev").stdout)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_py_cmds_and_exit_aliases(self):
        sh = new_shell()
        out = []
        sh.say = out.append
        sh.run_line("py 1+2")
        self.assertEqual(out[0], "3")
        self.assertEqual(sh.run_line("py 1/0"), 1)
        out.clear()
        sh.run_line("cmds")
        self.assertIn("cmds", out[0])
        h = tempfile.mkdtemp()
        self.assertEqual(run_env("q", h).returncode, 0)
        shutil.rmtree(h, ignore_errors=True)

    def test_heredoc_from_stdin_and_unterminated(self):
        env = dict(os.environ, LEAPSH_HOME=TMP_HOME, HOME=TMP_HOME, PYTHONPATH=str(ROOT))
        for text in ("cat <<EOF\nheredoc-radek\nEOF\n", "cat <<EOF\nheredoc-radek\n"):
            r = subprocess.run([sys.executable, "-m", "leapsh"], input=text, capture_output=True, text=True, env=env)
            self.assertIn("heredoc-radek", r.stdout)
            self.assertNotIn("__leapsh_rc", r.stdout)


class TestHeredocInteractive(TestInteractive):
    def test_heredoc_typed_interactively(self):
        out = self._session([b"cat <<EOF\r", b"heredoc-ok\r", b"EOF\r"], "heredoc-ok\r\n")
        self.assertTrue("heredoc-ok\r\n" in out, "heredoc nevypsal řádek")


for _n in ("test_typing_and_enter", "test_keybind_event_runs_command", "test_ctrl_c_and_editing"):
    setattr(TestHeredocInteractive, _n, None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
