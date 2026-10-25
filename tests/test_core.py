import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_HOME = tempfile.mkdtemp(prefix="leapsh-test-")
os.environ["LEAPSH_HOME"] = TMP_HOME
os.environ["HOME"] = TMP_HOME      # testy nesmí záviset na domovském adresáři uživatele

from leapsh import __version__                 # noqa: E402
from leapsh.config import MANIFEST, Config                    # noqa: E402
from leapsh.events import EventBus                  # noqa: E402
from leapsh.shell import Shell                      # noqa: E402
from leapsh.theme import style_code, visible_len    # noqa: E402


def new_shell():
    cfg = Config(Path(TMP_HOME) / f"cfg-{time.time_ns()}.json")
    sh = Shell(cfg)
    sh.history_path = Path(TMP_HOME) / "hist"
    sh.manager.load_all()
    return sh


def run(cmd, **kw):
    env = dict(os.environ, LEAPSH_HOME=TMP_HOME, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "leapsh", "-c", cmd], capture_output=True, text=True,
                          env=env, timeout=30, **kw)


class TestEvents(unittest.TestCase):
    def test_priority_cancel_stop_wildcard(self):
        bus, seen = EventBus(), []
        bus.on("x", lambda e: seen.append("low"), priority=0)
        bus.on("x", lambda e: seen.append("high"), priority=10)
        bus.on("*", lambda e: seen.append("wild:" + e.name))
        ev = bus.emit("x", a=1)
        self.assertEqual(seen, ["high", "low", "wild:x"])
        self.assertEqual(ev.a, 1)
        bus.on("y", lambda e: e.cancel(), priority=5)
        bus.on("y", lambda e: e.stop(), priority=1)
        bus.on("y", lambda e: seen.append("never"), priority=0)
        self.assertTrue(bus.emit("y").cancelled)
        self.assertNotIn("never", seen)

    def test_handler_error_is_isolated(self):
        errors = []
        bus = EventBus(on_error=lambda *a: errors.append(a))
        bus.on("x", lambda e: 1 / 0, owner="bad")
        bus.on("x", lambda e: e.data.update(ok=True))
        ev = bus.emit("x")
        self.assertTrue(ev.data["ok"])
        self.assertEqual(errors[0][0], "bad")

    def test_off_by_owner(self):
        bus = EventBus()
        bus.on("x", lambda e: None, owner="a")
        bus.on("x", lambda e: None, owner="b")
        bus.off(owner="a")
        self.assertEqual(bus.count("x"), 1)


class TestTheme(unittest.TestCase):
    def test_styles(self):
        self.assertEqual(style_code("bold red"), "\x1b[1;31m")
        self.assertEqual(style_code("208"), "\x1b[38;5;208m")
        self.assertEqual(style_code("#ff8800"), "\x1b[38;2;255;136;0m")
        self.assertEqual(style_code("on_blue"), "\x1b[44m")
        self.assertIsNone(style_code("cwd"))
        self.assertEqual(visible_len("\x1b[31mabc\x1b[0m"), 3)

    def test_all_bundled_themes_render(self):
        sh = new_shell()
        self.assertTrue({"classic", "neon", "minimal", "dracula"} <= set(sh.themes))
        for name in sh.themes:
            sh.config.data["theme"] = name
            head, last, rp = sh.render_prompt()
            self.assertTrue(last, name)


class TestPlugins(unittest.TestCase):
    def test_bundled_load(self):
        sh = new_shell()
        for n in ("git_prompt", "cmd_timer", "autosuggest", "keybinds", "did_you_mean", "event_logger"):
            self.assertIn(n, sh.manager.loaded)
        self.assertIn("git_prompt_stash", sh.manager.addons)
        self.assertEqual(sh.manager.status["termux_extras"].split(":")[0], "skipped")

    def test_disable_enable_plugin_takes_addon_with_it(self):
        sh = new_shell()
        sh.manager.disable("git_prompt")
        self.assertNotIn("git_prompt", sh.manager.loaded)
        self.assertNotIn("git_prompt_stash", sh.manager.addons)
        self.assertNotIn("git", sh.segments)
        sh.manager.enable("git_prompt")
        self.assertIn("git_prompt_stash", sh.manager.addons)
        self.assertIn("git", sh.segments)

    def test_git_segment_with_stash_addon(self):
        repo = Path(tempfile.mkdtemp())
        (repo / ".git" / "logs" / "refs").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/hlavni\n")
        (repo / ".git" / "logs" / "refs" / "stash").write_text("a\nb\n")
        sh = new_shell()
        sh.manager.loaded["git_prompt"].set_setting("dirty", False)
        old = os.getcwd()
        os.chdir(repo)
        try:
            out = sh.segments["git"][0]({})
        finally:
            os.chdir(old)
        self.assertIn("hlavni", out)
        self.assertIn("≡2", out)
        sh.manager.unload("git_prompt_stash")
        os.chdir(repo)
        try:
            sh.manager.loaded["git_prompt"]._cache = (None, 0, "")
            out = sh.segments["git"][0]({})
        finally:
            os.chdir(old)
        self.assertNotIn("≡", out)

    def test_addon_on_theme_and_wrap(self):
        sh = new_shell()
        self.assertIn("{time_s}", sh.themes["neon"].data["rprompt"])
        sh.manager.unload("neon_clock")
        self.assertNotIn("{time_s}", sh.themes["neon"].data["rprompt"])
        # wrap()
        from leapsh.api import Addon
        tgt = sh.manager.loaded["cmd_timer"]
        ad = Addon(sh, {"name": "w"}, ".", tgt)
        ad.wrap("segment", lambda orig, ctx: "X" + orig(ctx))
        self.assertTrue(tgt.segment({"duration": 99}).startswith("X"))
        ad._detach()
        self.assertFalse(tgt.segment({"duration": 99}).startswith("X"))

    def test_scaffold_generates_loadable_plugin_and_addon(self):
        sh = new_shell()
        rc = sh.run_line("plugin new demo_one")
        self.assertEqual(rc, 0)
        self.assertIn("demo_one", sh.manager.loaded)
        self.assertEqual(sh.run_line("addon new demo_add demo_one"), 0)
        self.assertIn("demo_add", sh.manager.addons)
        self.assertEqual(sh.run_line("demo_one"), 0)
        self.assertEqual(sh.run_line("theme new fresh"), 0)
        self.assertIn("fresh", sh.themes)

    def test_broken_plugin_does_not_crash(self):
        d = Path(TMP_HOME) / "plugins" / "broken"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / MANIFEST).write_text(json.dumps({"name": "broken"}))
        (d / "src" / "main.py").write_text("raise RuntimeError('bum')\n")
        try:
            sh = new_shell()
            self.assertTrue(sh.manager.status["broken"].startswith("error"))
            self.assertIn("git_prompt", sh.manager.loaded)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestShell(unittest.TestCase):
    def test_cd_and_export_persist(self):
        r = run("cd /tmp; export FOO=bar; pwd; echo $FOO")
        self.assertEqual(r.stdout.split("\n")[:2], ["/tmp", "bar"])

    def test_chain_and_builtin_mix(self):
        r = run('false || echo fallback && leapsh')
        self.assertIn("fallback", r.stdout)
        self.assertIn(f"leapsh {__version__}", r.stdout)

    def test_pipe_with_builtin(self):
        r = run("events | head -2")
        self.assertEqual(len(r.stdout.strip().split("\n")), 2)

    def test_alias_and_command_events(self):
        sh = new_shell()
        log = []
        sh.events.on("command_before", lambda e: e.data.update(line=e.line.replace("HELLO", "echo ahoj")))
        sh.events.on("command_after", lambda e: log.append((e.line, e.rc)))
        sh.run_line("HELLO")
        self.assertEqual(log[-1], ("echo ahoj", 0))
        sh.events.on("command_before", lambda e: e.cancel() if "zakazano" in e.line else None)
        n = len(log)
        sh.run_line("echo zakazano")
        self.assertEqual(len(log), n)

    def test_exit_code_and_not_found(self):
        self.assertEqual(run("exit 3").returncode, 3)
        sh = new_shell()
        seen = []
        sh.events.on("command_not_found", lambda e: seen.append(e.command))
        self.assertEqual(sh.run_line("neexistujici_prikaz_xyz"), 127)
        self.assertEqual(seen, ["neexistujici_prikaz_xyz"])

    def test_dir_change_event(self):
        sh = new_shell()
        seen = []
        sh.events.on("dir_change", lambda e: seen.append(e.new))
        old = os.getcwd()
        try:
            sh.run_line("cd /tmp")
        finally:
            os.chdir(old)
        self.assertEqual(seen, ["/tmp"])


@unittest.skipUnless(hasattr(os, "fork"), "pty test potřebuje fork")
class TestInteractive(unittest.TestCase):
    def _session(self, keys, expect, timeout=8, pre=0.8, home=None):
        import pty
        import select
        env = dict(os.environ, LEAPSH_HOME=home or TMP_HOME, PYTHONPATH=str(ROOT), TERM="xterm", LEAPSH_QUIET="1")
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, "-m", "leapsh"], env)
        out = b""

        def pump(sec):
            nonlocal out
            stop = time.time() + sec
            while time.time() < stop:
                if select.select([fd], [], [], 0.05)[0]:
                    try:
                        out += os.read(fd, 65536)
                    except OSError:
                        return

        try:
            pump(pre)
            for k in keys:
                os.write(fd, k)
                pump(0.25)
            end = time.time() + timeout
            while time.time() < end and expect.encode() not in out:
                pump(0.2)
        finally:
            try:
                os.write(fd, b"\x04")
            except OSError:
                pass
            time.sleep(0.2)
            try:
                os.kill(pid, 9)
            except OSError:
                pass
            os.waitpid(pid, 0)
        return out.decode("utf-8", "replace")

    def test_typing_and_enter(self):
        out = self._session([b"echo ahoj-svete\r"], "ahoj-svete\r\n")
        self.assertIn("ahoj-svete", out)

    def test_keybind_event_runs_command(self):
        # keybinds plugin: Ctrl+G -> git status -sb ; ověříme přes vlastní zkratku
        env_cfg = Path(TMP_HOME) / "plugins" / "config" / "keybinds.json"      # nastavení pluginu = vlastní soubor
        env_cfg.parent.mkdir(parents=True, exist_ok=True)
        env_cfg.write_text(json.dumps({"bindings": {"ctrl-g": "echo klavesa-funguje"}}))
        try:
            out = self._session([b"\x07"], "klavesa-funguje\r\n")
        finally:
            env_cfg.unlink()
        self.assertIn("klavesa-funguje", out)

    def test_ctrl_c_and_editing(self):
        out = self._session([b"echo spatne", b"\x15", b"echo dobre-ok\r"], "dobre-ok\r\n")
        self.assertIn("dobre-ok", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
