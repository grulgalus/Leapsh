"""Termux detekce, doctor, autocd, z (jump), kontextové doplňování, rychlé spouštění, rc soubor."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from test_core import MANIFEST, ROOT, TMP_HOME, new_shell  # noqa: E402
from leapsh import env_check  # noqa: E402
from leapsh.config import Config  # noqa: E402


def fake_bin(tmp, name, body="exit 0"):
    d = Path(tmp) / "bin"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(f"#!/bin/sh\n{body}\n")
    f.chmod(0o755)
    return str(d)


class TestTermuxDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = Config(Path(self.tmp) / "config.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **kw):
        base = {"PATH": "/usr/bin:/bin", "HOME": self.tmp}
        base.update(kw)
        return mock.patch.dict(os.environ, base, clear=True)

    def test_detect_by_env_and_by_pkg_command(self):
        with self.env(TERMUX_VERSION="0.118"):
            self.assertTrue(env_check.detect_termux())
        with self.env(PREFIX="/data/data/com.termux/files/usr"):
            self.assertTrue(env_check.detect_termux())
        with self.env():
            self.assertFalse(env_check.detect_termux())
        # `pkg` sám nestačí (FreeBSD apod.) – musí to být Termux
        path = fake_bin(self.tmp, "pkg")
        with self.env(PATH=path + ":/usr/bin"):
            self.assertFalse(env_check.detect_termux())
        tpath = fake_bin(Path(self.tmp) / "termux-home", "pkg")
        with self.env(PATH=tpath + ":/usr/bin"):
            self.assertTrue(env_check.detect_termux())          # cesta obsahuje „termux“

    def test_not_termux_warns_and_config_records_it(self):
        with self.env():
            notes = env_check.check_environment(self.cfg, probe=False)
        self.assertEqual(self.cfg.data["termux"]["available"], False)
        self.assertEqual(notes[0][0], "info")
        self.assertIn("Nejsi v Termuxu", notes[0][1])
        saved = json.loads((Path(self.tmp) / "config.json").read_text())
        self.assertFalse(saved["termux"]["available"])           # zapsáno do config.json
        self.cfg.data["warn_not_termux"] = False
        with self.env():
            self.assertEqual(env_check.check_environment(self.cfg, probe=False), [])

    def test_termux_without_api_warns(self):
        with self.env(TERMUX_VERSION="1"):
            notes = env_check.check_environment(self.cfg, probe=False)
        self.assertEqual((self.cfg.data["termux"]["available"], self.cfg.data["termux"]["api"]), (True, False))
        self.assertEqual(notes[0][0], "warn")
        self.assertIn("pkg install termux-api", notes[0][1])

    def test_termux_with_api_package_and_probe(self):
        good = fake_bin(self.tmp, "termux-battery-status", 'echo \'{"percentage": 77, "status": "FULL"}\'')
        with self.env(TERMUX_VERSION="1", PATH=good + ":/usr/bin:/bin"):
            notes = env_check.check_environment(self.cfg, probe=False)
            self.assertEqual(notes, [])
            self.assertTrue(self.cfg.data["termux"]["api"])
            env_check._probe_api(self.cfg)
        self.assertTrue(self.cfg.data["termux"]["api_working"])
        bad = fake_bin(Path(self.tmp) / "b2", "termux-battery-status", "exit 1")
        with self.env(TERMUX_VERSION="1", PATH=bad + ":/usr/bin:/bin"):
            env_check._probe_api(self.cfg)
            notes = env_check.check_environment(self.cfg, probe=False)
        self.assertFalse(self.cfg.data["termux"]["api_working"])
        self.assertIn("aplikace Termux:API neodpovídá", notes[0][1])

    def test_auto_false_keeps_manual_values(self):
        self.cfg.data["termux"] = {"auto": False, "available": True, "api": True, "api_working": True}
        with self.env():
            env_check.check_environment(self.cfg, probe=False)
        self.assertTrue(self.cfg.data["termux"]["available"])

    def test_migrates_old_home_once(self):
        base = Path(self.tmp) / "xdg"
        (base / "gluesh").mkdir(parents=True)
        (base / "gluesh" / "history").write_text("echo stare\n")
        with self.env(XDG_CONFIG_HOME=str(base)):
            self.assertEqual(env_check.migrate_legacy_home(), base / "gluesh")
            self.assertEqual((base / "leapsh" / "history").read_text(), "echo stare\n")
            self.assertIsNone(env_check.migrate_legacy_home())      # podruhé už ne


class TestDoctorAndStartup(unittest.TestCase):
    def test_doctor_runs_and_reports(self):
        sh = new_shell()
        out = []
        sh.say = out.append
        self.assertEqual(sh.run_line("doctor"), 0)
        text = "\n".join(out)
        for needle in ("leapsh", "Termux", "konfigurace", "historie", "pluginy:"):
            self.assertIn(needle, text)

    def test_startup_notice_for_non_termux_in_a_real_session(self):
        env = dict(os.environ, LEAPSH_HOME=tempfile.mkdtemp(), PYTHONPATH=str(ROOT), TERM="xterm")
        for k in ("TERMUX_VERSION", "PREFIX", "LEAPSH_QUIET"):
            env.pop(k, None)
        import pty
        import select
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, "-m", "leapsh"], env)
        out = b""
        end = time.time() + 6
        while time.time() < end and b"Nejsi v Termuxu" not in out:
            if select.select([fd], [], [], 0.2)[0]:
                out += os.read(fd, 65536)
        os.write(fd, b"\x04")
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        self.assertIn("Nejsi v Termuxu".encode(), out)
        self.assertIn("⚡".encode(), out)                        # čas startu v hlavičce
        self.assertTrue(json.loads((Path(env["LEAPSH_HOME"]) / "config.json").read_text())["termux"]["available"] is False)


class TestFastSpawn(unittest.TestCase):
    def test_simple_commands_skip_bash(self):
        sh = new_shell()
        calls = []
        orig = sh._spawn
        sh._spawn = lambda argv, env=None: calls.append(argv) or orig(argv, env)
        self.assertEqual(sh.run_line("true"), 0)
        self.assertEqual(sh.run_line("false"), 1)
        self.assertEqual(calls, [["true"], ["false"]])           # přímo, bez bash -c
        calls.clear()
        sh.run_line("echo $HOME")
        sh.run_line("true | cat")
        self.assertTrue(all(c[0].endswith("bash") for c in calls))     # speciální znaky -> bash

    def test_missing_permission_and_signals(self):
        sh = new_shell()
        self.assertEqual(sh.run_line("tohle_neexistuje_xyz --x"), 127)
        d = tempfile.mkdtemp()
        f = Path(d) / "noexec"
        f.write_text("#!/bin/sh\necho x\n")
        self.assertEqual(sh.run_line(f"{f}"), 126)
        script = Path(d) / "nobang"
        script.write_text("echo bez-shebangu\n")
        script.chmod(0o755)
        self.assertEqual(sh.run_line(f"{script}"), 0)            # ENOEXEC -> spadne na bash
        self.assertEqual(sh.run_line("sh -c 'kill -TERM $$'"), 128 + 15)

    def test_state_only_captured_when_needed_and_cd_still_works(self):
        sh = new_shell()
        seen = []
        orig = sh._apply_state
        sh._apply_state = lambda p: seen.append(p) or orig(p)
        sh.run_line("ls / > /dev/null")
        self.assertEqual(seen, [])
        old = os.getcwd()
        try:
            sh.run_line("cd /tmp && true")
            self.assertEqual(os.getcwd(), "/tmp")
            sh.run_line("export ZZ_TEST=ahoj")
            self.assertEqual(os.environ["ZZ_TEST"], "ahoj")
        finally:
            os.chdir(old)
            os.environ.pop("ZZ_TEST", None)
        self.assertEqual(len(seen), 2)

    def test_faster_than_bash_wrapper(self):
        sh = new_shell()

        def best(line, rounds=5, n=20):          # minimum z více kol: odolné proti zátěži stroje
            times = []
            for _ in range(rounds):
                t = time.perf_counter()
                for _ in range(n):
                    sh.run_line(line)
                times.append(time.perf_counter() - t)
            return min(times)
        self.assertLess(best("true"), best("true && true"))     # druhý příkaz jde přes bash



class TestNoPosixSpawn(unittest.TestCase):
    """Android/Termux nemá os.posix_spawnp – shell musí fungovat přes subprocess (a nespadnout)."""

    def test_works_without_posix_spawnp(self):
        saved = os.posix_spawnp
        del os.posix_spawnp
        old = os.getcwd()
        try:
            sh = new_shell()
            self.assertEqual(sh.run_line("true"), 0)                      # rychlá cesta -> subprocess
            self.assertEqual(sh.run_line("false"), 1)
            self.assertEqual(sh.run_line("echo $HOME > /dev/null"), 0)     # bash
            self.assertEqual(sh.run_line("cd /tmp"), 0)                    # bash + zachycení stavu (to padalo)
            self.assertEqual(os.getcwd(), "/tmp")
            self.assertEqual(sh.run_line("tohle_neexistuje_xyz"), 127)
            self.assertEqual(sh.run_line("sh -c 'kill -TERM $$'"), 128 + 15)
            self.assertFalse(sh._use_spawn)
        finally:
            os.posix_spawnp = saved
            os.chdir(old)

    def test_spawn_errors_never_kill_the_shell(self):
        sh = new_shell()
        sh._spawn = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertEqual(sh.run_line("ls /"), 1)                          # chyba se nahlásí, shell žije
        sh._spawn = lambda *a, **k: (_ for _ in ()).throw(AttributeError("nic"))
        self.assertEqual(sh.run_line("cd /tmp"), 1)


class TestShellExtras(unittest.TestCase):
    def test_autocd_and_jump(self):
        home = Path(tempfile.mkdtemp())
        (home / "projekty" / "web").mkdir(parents=True)
        old = os.getcwd()
        sh = new_shell()
        try:
            os.chdir(home)
            self.assertEqual(sh.run_line("projekty"), 0)
            self.assertEqual(os.getcwd(), str(home / "projekty"))
            sh.run_line("web")
            self.assertEqual(os.getcwd(), str(home / "projekty" / "web"))
            os.chdir("/")
            self.assertEqual(sh.run_line("z web"), 0)
            self.assertEqual(os.getcwd(), str(home / "projekty" / "web"))
            self.assertEqual(sh.run_line("z neexistuje_vubec"), 1)
        finally:
            os.chdir(old)
            shutil.rmtree(home, ignore_errors=True)

    def test_contextual_completion(self):
        sh = new_shell()

        def comp(left, word, first=False):
            ev = sh.events.emit("complete", word=word, first=first, buffer=left + word, left=left + word,
                                candidates=["soubor.txt"])
            return sorted(ev.data["candidates"])
        self.assertIn("enable", comp("plugin ", ""))
        self.assertEqual(comp("plugin en", "en"), ["enable"])
        self.assertIn("git_prompt", comp("plugin disable ", ""))
        self.assertIn("rounded", comp("theme set ", ""))
        self.assertEqual(comp("ls ", ""), ["soubor.txt"])          # jinde zůstává doplňování souborů
        self.assertIn("status", comp("git ", ""))

    def test_rc_file_runs_at_start(self):
        home = tempfile.mkdtemp()
        Path(home, "rc").write_text("# komentář\nalias rcprobe='echo rc-funguje'\n")
        env = dict(os.environ, LEAPSH_HOME=home, PYTHONPATH=str(ROOT), TERM="xterm", LEAPSH_QUIET="1")
        import pty
        import select
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, "-m", "leapsh"], env)
        time.sleep(0.8)
        os.write(fd, b"rcprobe\r")
        out = b""
        end = time.time() + 6
        while time.time() < end and b"rc-funguje\r\n" not in out:
            if select.select([fd], [], [], 0.2)[0]:
                out += os.read(fd, 65536)
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        shutil.rmtree(home, ignore_errors=True)
        self.assertIn(b"rc-funguje\r\n", out)

    def test_flexible_entry_and_manifest_names(self):
        d = Path(TMP_HOME) / "plugins" / "volne_jmeno"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / MANIFEST).write_text(json.dumps({"name": "volne_jmeno"}))
        (d / "src" / "cokoliv.py").write_text("from leapsh.api import Plugin\nclass P(Plugin):\n    def on_load(self):\n        self.add_command('vj', lambda s, a: 0)\n")
        legacy = Path(TMP_HOME) / "plugins" / "stary_manifest"
        (legacy / "src").mkdir(parents=True, exist_ok=True)
        (legacy / "gluesh.json").write_text(json.dumps({"name": "stary_manifest"}))
        (legacy / "src" / "x.py").write_text("from leapsh.api import Plugin\nclass Q(Plugin):\n    pass\n")
        two = Path(TMP_HOME) / "plugins" / "dva_soubory"
        (two / "src").mkdir(parents=True, exist_ok=True)
        (two / MANIFEST).write_text(json.dumps({"name": "dva_soubory"}))
        for n in ("a.py", "b.py"):
            (two / "src" / n).write_text("from leapsh.api import Plugin\nclass R(Plugin):\n    pass\n")
        try:
            sh = new_shell()
            self.assertEqual(sh.manager.status["volne_jmeno"], "loaded")
            self.assertIn("vj", sh.commands)
            self.assertEqual(sh.manager.status["stary_manifest"], "loaded")      # starší gluesh.json se pořád čte
            self.assertTrue(sh.manager.status["dva_soubory"].startswith("error"))
            self.assertIn('"main"', sh.manager.status["dva_soubory"])             # návod, co udělat
        finally:
            for x in (d, legacy, two):
                shutil.rmtree(x, ignore_errors=True)

    def test_python_plugin_can_use_wasm_module(self):
        from leapsh.wat import assemble
        d = Path(TMP_HOME) / "plugins" / "hybrid"
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / MANIFEST).write_text(json.dumps({"name": "hybrid"}))
        (d / "src" / "fast.wat").write_text('(module (func (export "add3") (param i32 i32 i32) (result i32) '
                                            '(i32.add (i32.add (local.get 0) (local.get 1)) (local.get 2))))')
        (d / "src" / "hybrid.py").write_text(
            "from leapsh.api import Plugin\nclass H(Plugin):\n    def on_load(self):\n"
            "        self.w = self.load_wasm('fast')\n        self.add_command('add3', lambda sh, a: sh.say(str(self.w.call('add3', 1, 2, 3))) or 0)\n")
        try:
            sh = new_shell()
            out = []
            sh.say = out.append
            self.assertEqual(sh.manager.status["hybrid"], "loaded", sh.manager.status["hybrid"])
            sh.run_line("add3")
            self.assertEqual(out, ["6"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
