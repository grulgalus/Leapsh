"""Historie: soubor ~/.config/leapsh/history, Ctrl-R, !!, ořezávání, práva souboru."""
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_core import TestInteractive, new_shell  # noqa: E402
from leapsh.config import Config  # noqa: E402
from leapsh.shell import Shell  # noqa: E402


def shell_in(home, **cfg):
    os.environ["LEAPSH_HOME"] = str(home)
    c = Config(Path(home) / "config.json")
    c.data.update(cfg)
    return Shell(c)


class TestHistoryFile(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.old = os.environ.get("LEAPSH_HOME")

    def tearDown(self):
        os.environ["LEAPSH_HOME"] = self.old
        shutil.rmtree(self.home, ignore_errors=True)

    def test_default_path_is_config_dir_history_and_is_private(self):
        sh = shell_in(self.home)
        self.assertEqual(sh.history_path, self.home / "history")
        sh.history_add("echo a")
        self.assertEqual((self.home / "history").read_text(), "echo a\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.home / "history").st_mode), 0o600)

    def test_persists_between_sessions_dedupes_and_ignores_space_prefix(self):
        sh = shell_in(self.home)
        for c in ("ls", "pwd", " tajne", "ls", "echo x"):
            sh.history_add(c)
        self.assertEqual(sh.history, ["pwd", "ls", "echo x"])
        sh2 = shell_in(self.home)
        self.assertEqual(sh2.history, ["pwd", "ls", "echo x"])        # načteno z disku, bez duplicit

    def test_trim_compacts_file_and_custom_path(self):
        (self.home / "history").write_text("".join(f"cmd{i % 3}\n" for i in range(600)))
        sh = shell_in(self.home)
        self.assertEqual(sh.history, ["cmd0", "cmd1", "cmd2"])
        self.assertEqual((self.home / "history").read_text().count("\n"), 3)   # soubor se sbalil
        other = self.home / "my" / "hist.txt"
        sh = shell_in(self.home, history_file=str(other))
        sh.history_add("echo z")
        self.assertEqual(other.read_text(), "echo z\n")

    def test_history_size_limit(self):
        (self.home / "history").write_text("".join(f"c{i}\n" for i in range(50)))
        sh = shell_in(self.home, history_size=10)
        self.assertEqual(sh.history, [f"c{i}" for i in range(40, 50)])

    def test_expansion(self):
        sh = shell_in(self.home)
        for c in ("echo one two", "ls -la /tmp", "git status"):
            sh.history_add(c)
        self.assertEqual(sh.expand_history("sudo !!"), "sudo git status")
        self.assertEqual(sh.expand_history("cd !$"), "cd status")
        self.assertEqual(sh.expand_history("!2"), "ls -la /tmp")
        self.assertEqual(sh.expand_history("!-3"), "echo one two")
        self.assertEqual(sh.expand_history("!ls"), "ls -la /tmp")
        self.assertEqual(sh.expand_history("echo '!!' hotovo!"), "echo '!!' hotovo!")   # apostrofy a "!" na konci
        self.assertEqual(sh.expand_history("[ ! -f x ]"), "[ ! -f x ]")
        self.assertIsNone(sh.expand_history("!nic_takoveho"))

    def test_history_command(self):
        sh = shell_in(self.home)
        out = []
        sh.say = out.append
        for c in ("alpha", "beta", "gamma"):
            sh.history_add(c)
        sh.run_line("history -s ta")
        self.assertEqual([l.split()[1] for l in out], ["beta"])
        out.clear()
        sh.run_line("history -d 1")
        self.assertEqual(sh.history, ["beta", "gamma"])
        self.assertEqual((self.home / "history").read_text(), "beta\ngamma\n")
        sh.run_line("history -c")
        self.assertEqual((self.home / "history").read_text(), "")


class TestHistoryInteractive(TestInteractive):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_file_survives_restart_and_up_arrow_recalls(self):
        self._session([b"echo hist-one\r", b"echo hist-two\r"], "hist-two\r\n", home=self.home)
        lines = (Path(self.home) / "history").read_text().splitlines()
        self.assertEqual(lines, ["echo hist-one", "echo hist-two"])
        out = self._session([b"\x1b[A\r"], "hist-two\r\n", home=self.home)        # šipka nahoru + Enter
        self.assertTrue(out.count("hist-two") >= 2, "poslední příkaz se nevrátil")

    def test_ctrl_r_searches_and_runs(self):
        (Path(self.home) / "history").write_text("echo alfa-1\necho beta-2\necho gamma-3\n")
        out = self._session([b"\x12", b"alfa", b"\r"], "alfa-1\r\n", home=self.home)
        self.assertTrue("(hledání)" in out and "alfa-1\r\n" in out, "Ctrl-R nenašel příkaz")

    def test_bang_bang_runs_previous(self):
        (Path(self.home) / "history").write_text("echo opakuj-me\n")
        out = self._session([b"!!\r"], "opakuj-me\r\n", home=self.home)
        self.assertTrue("opakuj-me\r\n" in out)

    def test_pageup_prefix_search(self):
        (Path(self.home) / "history").write_text("echo aaa-1\nls /tmp\necho aaa-2\n")
        out = self._session([b"echo", b"\x1b[5~", b"\x1b[5~", b"\r"], "aaa-1\r\n", home=self.home)
        self.assertTrue("aaa-1\r\n" in out, "PageUp nenašel starší příkaz začínající 'echo'")


for _n in ("test_typing_and_enter", "test_keybind_event_runs_command", "test_ctrl_c_and_editing"):
    setattr(TestHistoryInteractive, _n, None)

if __name__ == "__main__":
    unittest.main(verbosity=2)
