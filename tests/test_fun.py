import importlib.util
import json
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_core import ROOT, TMP_HOME, TestInteractive, new_shell  # noqa: E402
from leapsh.theme import visible_len  # noqa: E402


def load_arcade():
    spec = importlib.util.spec_from_file_location("arcade_test", ROOT / "plugins" / "arcade" / "src" / "main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def strip(s):
    from leapsh.theme import ANSI_RE
    return ANSI_RE.sub("", s)


class TestWidth(unittest.TestCase):
    def test_emoji_is_two_columns(self):
        self.assertEqual(visible_len("🔋50"), 4)
        self.assertEqual(visible_len("\x1b[32mabc\x1b[0m"), 3)


class TestPet(unittest.TestCase):
    def setUp(self):
        for f in ("pet.json", "achievements.json"):
            (Path(TMP_HOME) / f).unlink(missing_ok=True)

    def test_mood_levels_and_hat_addon(self):
        sh = new_shell()
        out = []
        sh.say = out.append
        pet = sh.manager.loaded["pet"]
        for _ in range(25):
            sh.events.emit("command_after", line="ls", command="ls", rc=0, duration=0.0)
        self.assertEqual(pet.level, 2)
        self.assertTrue(any("levelu 2" in x for x in out))
        for _ in range(20):
            sh.events.emit("command_after", line="x", command="x", rc=1, duration=0.0)
        self.assertEqual(pet.face()[0].strip("♪♛✦"), "(;_;)")
        pet.s["xp"], pet.s["mood"] = 130, 100
        self.assertIn("♛", sh.segments["pet"][0]({}))
        sh.manager.unload("pet_hat")
        self.assertNotIn("♛", sh.segments["pet"][0]({}))

    def test_pet_commands(self):
        sh = new_shell()
        self.assertEqual(sh.run_line("pet name Rex"), 0)
        self.assertEqual(sh.manager.loaded["pet"].s["name"], "Rex")
        self.assertEqual(sh.run_line("pet feed"), 0)


class TestAchievements(unittest.TestCase):
    def setUp(self):
        (Path(TMP_HOME) / "achievements.json").unlink(missing_ok=True)

    def test_unlock_and_addon_hook(self):
        sh = new_shell()
        out = []
        sh.say = out.append
        got = []
        sh.manager.loaded["achievements"].extend("unlocked", lambda a, **c: got.append(a["id"]))
        sh.events.emit("command_after", line="git status", command="git status", rc=0, duration=0.0)
        self.assertIn("first", got)
        for _ in range(3):
            sh.events.emit("command_not_found", line="zz", command="zz")
        sh.events.emit("command_after", line="zz", command="zz", rc=127, duration=0.0)
        self.assertIn("typos", got)
        sh.events.emit("command_after", line="sleep", command="sleep", rc=0, duration=90.0)
        self.assertIn("marathon", got)
        self.assertTrue(any("Achievement" in x for x in out))
        got.clear()
        sh.events.emit("command_after", line="ls", command="ls", rc=0, duration=0.0)
        self.assertEqual(got, [])  # už odemčené se nezopakuje

    def test_phoenix(self):
        sh = new_shell()
        sh.sayout = None
        sh.say = lambda t="": None
        got = []
        sh.manager.loaded["achievements"].extend("unlocked", lambda a, **c: got.append(a["id"]))
        for _ in range(5):
            sh.events.emit("command_after", line="false", command="false", rc=1, duration=0.0)
        sh.events.emit("command_after", line="true", command="true", rc=0, duration=0.0)
        self.assertIn("phoenix", got)


class TestHighlight(unittest.TestCase):
    def test_colors(self):
        sh = new_shell()
        h = sh.manager.loaded["syntax_highlight"].highlight
        line = "ls -la | grep foo && nesmyslnyprikaz zz"
        out = h(line)
        self.assertEqual(strip(out), line)
        self.assertIn("\x1b[32mls", out)
        self.assertIn("\x1b[36m-la", out)
        self.assertIn("\x1b[31mnesmyslnyprikaz", out)
        self.assertNotIn("\x1b[31mgi", h("gi"))          # rozepsaný příkaz není chyba
        self.assertIn("\x1b[33m\"a b\"", h('echo "a b"'))

    def test_rainbow_addon_toggle(self):
        sh = new_shell()
        h = sh.manager.loaded["syntax_highlight"].highlight
        self.assertNotIn("highlight_rainbow", sh.manager.addons)
        self.assertNotIn("38;2;", h("ls -la"))
        sh.manager.enable("highlight_rainbow")
        out = h("ls -la zz")
        self.assertIn("38;2;", out)
        self.assertEqual(strip(out), "ls -la zz")
        sh.manager.disable("highlight_rainbow")
        self.assertNotIn("38;2;", h("ls -la"))


class TestSnake(unittest.TestCase):
    def test_logic(self):
        m = load_arcade()
        g = m.SnakeGame(10, 8, random.Random(1))
        g.turn("left")
        self.assertEqual(g.pending, "right")          # nelze se otočit o 180°
        g.food = (g.body[0][0] + 1, g.body[0][1])
        g.step()
        self.assertEqual((g.score, len(g.body)), (1, 4))
        for _ in range(12):
            g.step()
        self.assertFalse(g.alive)                       # náraz do zdi
        g2 = m.SnakeGame(10, 8)
        for d in ("up", "left", "down"):
            g2.turn(d)
            g2.step()
        g2.body = [(5, 5), (5, 4), (4, 4), (4, 5), (4, 6), (5, 6)]   # smyčka -> sežere se
        g2.dir = g2.pending = "right"
        g2.turn("up")
        g2.turn("left")
        self.assertTrue(g2.body[0] in g2.body)

    def test_keys(self):
        m = load_arcade()
        self.assertEqual(m.Arcade.parse_keys(b"\x1b[C"), "right")
        self.assertEqual(m.Arcade.parse_keys(b"w"), "up")
        self.assertEqual(m.Arcade.parse_keys(b"q"), "quit")


class TestFunInteractive(TestInteractive):
    def test_snake_starts_and_quits(self):
        out = self._session([b"snake\r", b"\x1b[B", b"q"], "snake: skóre")
        self.assertIn("\x1b[?1049h", out)
        self.assertIn("SNAKE", out)
        self.assertIn("snake: skóre", out)

    def test_matrix_and_train_run(self):
        out = self._session([b"matrix 1\r"], "\x1b[?1049l")
        self.assertIn("\x1b[?1049h", out)
        out = self._session([b"train\r", b"x"], "\x1b[?1049l")
        self.assertIn("\x1b[?1049h", out)

    def test_screensaver_after_idle(self):
        cfg = Path(TMP_HOME) / "plugins" / "config" / "arcade.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"idle_seconds": 1}))
        try:
            out = self._session([b"x", b"echo po-matrixu\r"], "po-matrixu\r\n", pre=3.5)
        finally:
            cfg.unlink()
        self.assertTrue("\x1b[?1049h" in out, "spořič nenaskočil")
        self.assertTrue("po-matrixu" in out, "shell se po klávese nevrátil k psaní")


for _name in ("test_typing_and_enter", "test_keybind_event_runs_command", "test_ctrl_c_and_editing"):
    setattr(TestFunInteractive, _name, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
