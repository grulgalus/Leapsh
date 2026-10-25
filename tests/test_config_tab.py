"""Příkaz config, plugin tabcomplete (+ addon), cyklování Tabem a nové vlastnosti plugin systému."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from test_core import MANIFEST, ROOT, TMP_HOME, TestInteractive, new_shell  # noqa: E402
from leapsh.config import Config  # noqa: E402
from leapsh.editor import LineEditor  # noqa: E402
from leapsh.shell import Shell  # noqa: E402


class Base(unittest.TestCase):
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
        self.out = []
        sh.say = self.out.append
        return sh


class TestConfigCommand(Base):
    def test_show_get_set_unset_reset(self):
        sh = self.shell()
        sh.run_line("config")
        self.assertTrue(any('"theme"' in x for x in self.out))
        self.assertEqual(sh.run_line("config set startup_msg ne"), 0)             # bool: česky
        self.assertIs(sh.config.data["startup_msg"], False)
        saved = json.loads((self.home / "config.json").read_text())
        self.assertFalse(saved["startup_msg"])                                     # uloženo na disk
        self.assertEqual(sh.run_line("config set history_size na 300"), 0)         # „na“ jako oddělovač
        self.assertEqual(sh.config.data["history_size"], 300)
        self.assertEqual(sh.run_line("config set history_size=250"), 0)            # klíč=hodnota
        self.assertEqual(sh.config.data["history_size"], 250)
        self.assertEqual(sh.run_line("config set history_size moc"), 1)            # špatný typ se odmítne
        self.assertEqual(sh.config.data["history_size"], 250)
        self.assertEqual(sh.run_line("config set history_size 0"), 1)
        self.assertEqual(sh.run_line("config reset history_size"), 0)
        self.assertEqual(sh.config.data["history_size"], 5000)
        self.out.clear()
        sh.run_line("config get termux.auto")
        self.assertEqual(self.out, ["true"])
        self.assertEqual(sh.run_line("config get neexistuje"), 1)
        self.out.clear()
        sh.run_line("config theme")                                                # zkratka pro get
        self.assertEqual(self.out, ['"rounded"'])

    def test_theme_and_aliases_apply_immediately(self):
        sh = self.shell()
        seen = []
        sh.events.on("config_change", lambda e: seen.append((e.key, e.new)))
        self.assertEqual(sh.run_line("config set theme nesmysl"), 1)
        self.assertEqual(sh.config.data["theme"], "rounded")
        self.assertEqual(sh.run_line("config set theme dracula"), 0)
        self.assertEqual(sh.current_theme().name, "dracula")
        self.assertEqual(sh.run_line("config set aliases.gs git status -sb"), 0)
        self.assertEqual(sh.aliases["gs"], "git status -sb")                       # alias platí hned
        sh.run_line("config unset aliases.gs")
        self.assertNotIn("gs", sh.aliases)
        self.assertIn(("theme", "dracula"), seen)

    def test_plugin_settings_through_config(self):
        sh = self.shell()
        self.assertEqual(sh.run_line("config set plugins.cmd_timer.threshold 11"), 0)
        self.assertEqual(json.loads((self.home / "plugins" / "config" / "cmd_timer.json").read_text()), {"threshold": 11})
        self.assertEqual(sh.run_line("config set plugins.cmd_timer.threshold abc"), 1)
        self.assertEqual(sh.run_line("config set plugins.git_prompt.dirty false"), 0)
        self.out.clear()
        sh.run_line("config get plugins.cmd_timer.threshold")
        self.assertEqual(self.out, ["11"])
        sh.run_line("config plugins cmd_timer")
        self.assertTrue(any("threshold" in x for x in self.out))
        sh.run_line("config unset plugins.cmd_timer.threshold")
        self.assertFalse((self.home / "plugins" / "config" / "cmd_timer.json").exists())

    def test_new_value_types_for_new_keys(self):
        sh = self.shell()
        sh.run_line('config set moje.cislo 5')
        sh.run_line("config set moje.pole '[\"a\",\"b\"]'")        # JSON s uvozovkami patří do apostrofů
        sh.run_line('config set moje.text ahoj svete')
        self.assertEqual(sh.config.data["moje"], {"cislo": 5, "pole": ["a", "b"], "text": "ahoj svete"})


class TestConfigAdvanced(Base):
    def test_toggle_add_remove(self):
        sh = self.shell()
        self.assertEqual(sh.run_line("config toggle startup_msg"), 0)
        self.assertIs(sh.config.data["startup_msg"], False)
        sh.run_line("config toggle startup_msg")
        self.assertIs(sh.config.data["startup_msg"], True)
        self.assertEqual(sh.run_line("config toggle theme"), 1)                      # není bool
        self.assertEqual(sh.run_line("config toggle plugins.git_prompt.dirty"), 0)   # i nastavení pluginu
        self.assertIs(sh.manager.loaded["git_prompt"].setting("dirty"), False)
        self.assertEqual(sh.run_line("config add disabled pet"), 0)
        self.assertEqual(sh.run_line("config add disabled pet"), 0)                  # bez duplicit
        self.assertEqual(sh.config.data["disabled"].count("pet"), 1)
        self.assertNotIn("pet", sh.manager.loaded)                                   # a platí hned (pluginy se načetly znovu)
        self.assertEqual(sh.run_line("config remove disabled pet"), 0)
        self.assertIn("pet", sh.manager.loaded)
        self.assertEqual(sh.run_line("config add theme x"), 1)                       # není seznam

    def test_typo_guard_and_force(self):
        sh = self.shell()
        self.assertEqual(sh.run_line("config set histroy_size 10"), 1)
        self.assertTrue(any("history_size" in x for x in self.out))
        self.assertNotIn("histroy_size", sh.config.data)
        self.assertEqual(sh.run_line("config set histroy_size 10 --force"), 0)       # vědomě vlastní klíč
        self.assertEqual(sh.run_line("config set moje_vlastni 1"), 0)                # nic podobného = povoleno

    def test_undo_and_redo(self):
        sh = self.shell()
        sh.run_line("config set history_size 111")
        sh.run_line("config set history_size 222")
        self.assertEqual(sh.run_line("config undo"), 0)
        self.assertEqual(sh.config.data["history_size"], 111)
        self.assertEqual(json.loads((self.home / "config.json").read_text())["history_size"], 111)
        sh.run_line("config undo")                                                   # podruhé = zpět
        self.assertEqual(sh.config.data["history_size"], 222)
        sh.run_line("config set aliases.zz echo zz")
        sh.run_line("config undo")
        self.assertNotIn("zz", sh.aliases)                                           # i aliasy se vrátí

    def test_undo_without_backup(self):
        self.assertEqual(self.shell().run_line("config undo"), 1)

    def test_diff_keys_validate(self):
        sh = self.shell()
        sh.run_line("config set history_size 77")
        sh.run_line("config set moje.klic 1")
        self.out.clear()
        sh.run_line("config diff")
        text = "\n".join(self.out)
        self.assertIn("history_size", text)
        self.assertIn("5000", text)
        self.assertIn("moje.klic", text)
        self.assertNotIn("startup_msg", text)                                         # beze změny = nezobrazí se
        self.out.clear()
        sh.run_line("config keys hist")
        text = "\n".join(self.out)
        self.assertIn("history_size", text)
        self.assertIn("kolik příkazů", text)
        self.assertIn("* history_size", text)                                         # označeno jako změněné
        self.out.clear()
        self.assertEqual(sh.run_line("config validate"), 0)
        sh.config.data["history_size"] = "moc"
        sh.config.data["theme"] = "neexistuje"
        self.out.clear()
        self.assertEqual(sh.run_line("config validate"), 1)
        text = "\n".join(self.out)
        self.assertIn("history_size: čekám číslo", text)
        self.assertIn("téma 'neexistuje'", text)

    def test_export_import_roundtrip(self):
        sh = self.shell()
        sh.run_line("config set theme dracula")
        sh.run_line("config set history_size 321")
        sh.run_line("config set plugins.cmd_timer.threshold 9")
        f = self.home / "zaloha.json"
        self.assertEqual(sh.run_line(f"config export {f}"), 0)
        bundle = json.loads(f.read_text())
        self.assertEqual(bundle["config"]["theme"], "dracula")
        self.assertEqual(bundle["plugins"]["cmd_timer"], {"threshold": 9})
        # jiná instalace: čistý domov
        other = Path(tempfile.mkdtemp())
        try:
            os.environ["LEAPSH_HOME"] = str(other)
            sh2 = Shell(Config(other / "config.json"))
            sh2.manager.load_all()
            sh2.say = lambda *a, **k: None
            self.assertEqual(sh2.run_line(f"config import {f}"), 0)
            self.assertEqual(sh2.config.data["theme"], "dracula")
            self.assertEqual(sh2.config.data["history_size"], 321)
            self.assertEqual(sh2.manager.loaded["cmd_timer"].setting("threshold"), 9)
            self.assertEqual(sh2.current_theme().name, "dracula")
            sh2.run_line("config undo")                                              # import jde vrátit
            self.assertEqual(sh2.config.data["history_size"], 5000)
        finally:
            os.environ["LEAPSH_HOME"] = str(self.home)
            shutil.rmtree(other, ignore_errors=True)

    def test_import_merge_and_bad_files(self):
        sh = self.shell()
        sh.run_line("config set history_size 500")
        f = self.home / "cast.json"
        f.write_text(json.dumps({"config": {"tab_cycle": False}}))
        self.assertEqual(sh.run_line(f"config import {f} --merge"), 0)
        self.assertEqual((sh.config.data["history_size"], sh.config.data["tab_cycle"]), (500, False))   # sloučeno
        bad = self.home / "spatny.json"
        bad.write_text("{nejson")
        self.assertEqual(sh.run_line(f"config import {bad}"), 1)
        self.assertEqual(sh.run_line("config import /neexistuje.json"), 1)
        f.write_text(json.dumps({"config": {"theme": "nesmysl"}}))
        sh.run_line(f"config import {f}")
        self.assertIn(sh.config.data["theme"], sh.themes)                              # neplatné téma se nepřevezme

    def test_completion_of_new_subcommands(self):
        from test_config_tab import TestTabcomplete
        tc = TestTabcomplete("test_shell_commands_and_config_keys").tc
        sh = self.shell()
        self.assertIn("undo", tc("config ", sh=sh))
        self.assertIn("startup_msg", tc("config toggle ", sh=sh))
        self.assertNotIn("theme", tc("config toggle ", sh=sh))                        # jen bool klíče
        self.assertIn("disabled", tc("config add ", sh=sh))
        self.assertIn("pet", tc("config add disabled ", sh=sh))


class TestTabcomplete(Base):
    def tc(self, text, ed=False, sh=None):
        sh = sh or self.shell()
        import re
        m = re.search(r"[^\s|;&<>]*$", text)
        word, before = m.group(0), text[:m.start()].rstrip()
        first = before == "" or before.endswith(("|", ";", "&&", "||", "&", "("))
        plugin = sh.manager.loaded["tabcomplete"]
        return plugin.candidates(word, text, first, LineEditor(sh) if ed else None)

    def test_shell_commands_and_config_keys(self):
        self.assertIn("enable", self.tc("plugin "))
        self.assertEqual(self.tc("plugin en"), ["enable"])
        self.assertIn("tabcomplete", self.tc("plugin disable "))
        self.assertIn("threshold", self.tc("plugin set cmd_timer "))
        self.assertEqual(self.tc("plugin set git_prompt dirty "), ["true", "false"])
        self.assertIn("rounded", self.tc("theme set "))
        self.assertIn("plugins.cmd_timer.threshold", self.tc("config get plugins.cmd"))
        self.assertEqual(self.tc("config set theme dra"), ["dracula"])
        self.assertEqual(self.tc("config set startup_msg "), ["true", "false"])
        self.assertIn("get", self.tc("config "))
        self.assertIsNone(self.tc("ls "))                        # jinde výchozí doplňování souborů

    def test_git_refs(self):
        repo = self.home / "repo"
        g = repo / ".git"
        (g / "refs" / "heads" / "feat").mkdir(parents=True)
        (g / "refs" / "tags").mkdir(parents=True)
        (g / "refs" / "remotes" / "origin").mkdir(parents=True)
        for f in ("refs/heads/main", "refs/heads/feat/x", "refs/tags/v1", "refs/remotes/origin/devel", "refs/remotes/origin/HEAD"):
            (g / f).write_text("0" * 40)
        (g / "packed-refs").write_text("# pack\n" + "1" * 40 + " refs/heads/stara\n" + "2" * 40 + " refs/tags/v0\n^" + "3" * 40 + "\n")
        (g / "config").write_text('[remote "origin"]\n\turl = x\n[remote "backup"]\n\turl = y\n')
        sh = self.shell()
        old = os.getcwd()
        os.chdir(repo)
        try:
            self.assertEqual(self.tc("git ch", sh=sh), ["checkout", "cherry-pick"])
            refs = self.tc("git checkout ", sh=sh)
            for r in ("main", "feat/x", "v1", "devel", "stara", "v0"):
                self.assertIn(r, refs)
            self.assertNotIn("HEAD", refs)
            self.assertEqual(self.tc("git checkout fe", sh=sh), ["feat/x"])
            self.assertEqual(self.tc("git push ", sh=sh), ["backup", "origin"])
            self.assertEqual(self.tc("git push origin ma", sh=sh), ["main"])
            self.assertIsNone(self.tc("git add ", sh=sh))        # soubory řeší výchozí doplňování
        finally:
            os.chdir(old)

    def test_pkg_ssh_env_and_sudo(self):
        pre = self.home / "usr"
        (pre / "var" / "lib" / "apt" / "lists").mkdir(parents=True)
        (pre / "var/lib/apt/lists/x_Packages").write_text("Package: neovim\nVersion: 1\n\nPackage: nmap\n\nPackage: git\n")
        ssh = self.home / ".ssh"
        ssh.mkdir()
        (ssh / "config").write_text("Host server1 *.wild\n  HostName a\nHost !neg dev\n")
        (ssh / "known_hosts").write_text("[pi.local]:2222 ssh-rsa AAA\n|1|hash ssh-rsa BBB\n10.0.0.5,laptop ssh-ed25519 CCC\n")
        sh = self.shell()
        with mock.patch.dict(os.environ, {"PREFIX": str(pre), "HOME": str(self.home), "MOJE_PROM": "1"}):
            sh.manager.loaded["tabcomplete"]._pkgs = None
            self.assertEqual(self.tc("pkg install ne", sh=sh), ["neovim"])
            self.assertIsNone(self.tc("pkg install n", sh=sh))           # od 2 znaků, ať se nevypisují tisíce balíčků
            self.assertEqual(self.tc("pkg install nm", sh=sh), ["nmap"])
            self.assertEqual(self.tc("pkg ins", sh=sh), ["install"])
            hosts = self.tc("ssh ", sh=sh)
            for h in ("server1", "dev", "pi.local", "10.0.0.5", "laptop"):
                self.assertIn(h, hosts)
            self.assertNotIn("*.wild", hosts)
            self.assertEqual(self.tc("ssh root@ser", sh=sh), ["root@server1"])
            self.assertEqual(self.tc("echo $MOJE_P", sh=sh), ["$MOJE_PROM"])
            self.assertIn("MOJE_PROM", self.tc("export MOJE_", sh=sh))
            self.assertEqual(self.tc("sudo git sta", sh=sh), self.tc("git sta", sh=sh))     # sudo se přeskočí
            self.assertIn("status", self.tc("sudo git sta", sh=sh))

    def test_specs_manifest_completions_and_addon(self):
        sh = self.shell()
        self.assertEqual(self.tc("pet f", sh=sh), ["feed"])                      # z config.json pluginu pet
        self.assertEqual(self.tc("docker ru", sh=sh), ["run"])                   # addon tabcomplete_extra
        sh.plugin_settings.set("tabcomplete", "specs", {"mytool": {"1": ["start", "stop"], "--mode": ["fast", "slow"], "*": ["x"]}})
        self.assertEqual(self.tc("mytool s", sh=sh), ["start", "stop"])
        self.assertEqual(self.tc("mytool start --mode ", sh=sh), ["fast", "slow"])
        self.assertEqual(self.tc("mytool start ", sh=sh), ["x"])
        sh.manager.unload("tabcomplete_extra")
        self.assertIsNone(self.tc("docker ru", sh=sh))                           # addon pryč = poskytovatel pryč

    def test_ignore_case_and_debug_command(self):
        d = self.home / "files"
        d.mkdir()
        (d / "Dokument.txt").write_text("x")
        sh = self.shell()
        old = os.getcwd()
        os.chdir(d)
        try:
            self.assertEqual(self.tc("cat dok", ed=True, sh=sh), None)           # výchozí: rozlišuje velikost
            sh.plugin_settings.set("tabcomplete", "ignore_case", True)
            self.assertEqual(self.tc("cat dok", ed=True, sh=sh), ["Dokument.txt"])
            self.assertEqual(self.tc("PLUGIN en", sh=sh), None)                  # příkaz sám se neparsuje jinak
        finally:
            os.chdir(old)
        sh.run_line("tabcomplete 'git ch'")
        self.assertIn("checkout", self.out)


class TestTabCycling(TestInteractive):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        for n in ("aa1", "aa2", "aa3"):
            Path(self.d, n).write_text("x")
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_repeated_tab_cycles_forward(self):
        out = self._session([b"ls aa\t", b"\t", b"\t", b"\r"], "aa2\r\n", home=tempfile.mkdtemp())
        self.assertTrue("aa2\r\n" in out, "druhý Tab po nabídce měl vybrat aa2")

    def test_shift_tab_goes_back(self):
        out = self._session([b"ls aa\t", b"\x1b[Z", b"\r"], "aa3\r\n", home=tempfile.mkdtemp())
        self.assertTrue("aa3\r\n" in out, "Shift-Tab měl vybrat poslední kandidát")

    def test_other_key_stops_cycling(self):
        out = self._session([b"ls aa\t", b"\t", b"x", b"\r"], "aa1x", home=tempfile.mkdtemp())
        self.assertIn("aa1x", out)                                               # po písmenu se už nic nemění


for _n in ("test_typing_and_enter", "test_keybind_event_runs_command", "test_ctrl_c_and_editing"):
    setattr(TestTabCycling, _n, None)


class TestPluginSystem(Base):
    def make(self, name, manifest=None, code="from leapsh.api import Plugin\nclass P(Plugin):\n    def on_load(self):\n        self.add_command('%s', lambda sh, a: 0)\n"):
        d = self.home / "plugins" / name
        (d / "src").mkdir(parents=True)
        (d / MANIFEST).write_text(json.dumps(dict({"name": name}, **(manifest or {}))))
        (d / "src" / f"{name}.py").write_text(code % name if "%s" in code else code)
        return d

    def test_min_shell(self):
        self.make("novinka", {"min_shell": "99.0.0"})
        self.make("stare", {"min_shell": "1.0"})
        sh = self.shell()
        self.assertTrue(sh.manager.status["novinka"].startswith("skipped: potřebuje leapsh ≥ 99.0.0"))
        self.assertEqual(sh.manager.status["stare"], "loaded")

    def test_reload_single_plugin_picks_up_code_and_manifest_changes(self):
        d = self.make("meni_se", {"description": "v1"})
        sh = self.shell()
        self.assertIn("meni_se", sh.commands)
        (d / "src" / "meni_se.py").write_text("from leapsh.api import Plugin\nclass P(Plugin):\n    def on_load(self):\n        self.add_command('nove_jmeno', lambda sh, a: 0)\n")
        (d / MANIFEST).write_text(json.dumps({"name": "meni_se", "description": "v2"}))
        self.assertEqual(sh.run_line("plugin reload meni_se"), 0)
        self.assertIn("nove_jmeno", sh.commands)
        self.assertNotIn("meni_se", sh.commands)
        self.assertEqual(sh.manager.found["meni_se"].manifest["description"], "v2")
        self.assertEqual(sh.run_line("plugin reload nenalezeny_plugin"), 1)
        self.assertIn("git_prompt", sh.manager.loaded)                           # ostatní zůstaly

    def test_reload_takes_addons_along(self):
        sh = self.shell()
        self.assertIn("git_prompt_stash", sh.manager.addons)
        self.assertEqual(sh.run_line("plugin reload git_prompt"), 0)
        self.assertIn("git_prompt_stash", sh.manager.addons)

    def test_circuit_breaker_disables_endlessly_failing_plugin(self):
        self.make("padajici", None, "from leapsh.api import Plugin\nclass P(Plugin):\n    def on_load(self):\n        self.on('command_after', lambda ev: 1/0)\n")
        sh = self.shell()
        sh.warn = lambda *a, **k: None
        for _ in range(55):
            sh.events.emit("command_after", line="x", command="x", rc=0, duration=0.0)
        self.assertTrue(sh.manager.status["padajici"].startswith("error: vypnuto"))
        self.assertNotIn("padajici", sh.events.owned_by("padajici"))
        self.assertEqual(sh.run_line("plugin reload padajici"), 0)              # po reloadu zase žije
        self.assertEqual(sh.manager.status["padajici"], "loaded")

    def test_unknown_manifest_keys_are_flagged(self):
        from leapsh.devtools import compile_plugin
        d = self.make("preklep", {"descripton": "x", "version": "1"})
        log = []
        compile_plugin(d, pack=False, log=log.append)
        self.assertTrue(any("descripton" in l for l in log), log)

    def test_settings_info_shown(self):
        sh = self.shell()
        sh.run_line("plugin settings tabcomplete")
        self.assertTrue(any("ignore_case" in x and "velikost" in x for x in self.out), self.out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
