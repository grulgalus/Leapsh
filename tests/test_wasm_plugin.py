"""WASM pluginy v shellu (ABI, sandbox) a nástroje init/compile/install."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_core import MANIFEST, ROOT, TMP_HOME, new_shell  # noqa: E402
from leapsh.devtools import compile_plugin, install_package, pack_plugin  # noqa: E402
from leapsh.scaffold import scaffold  # noqa: E402

ALLOC = '''(memory (export "memory") 1)
  (global $heap (mut i32) (i32.const 1024))
  (func (export "leapsh_alloc") (param $n i32) (result i32) (local $p i32)
    (local.set $p (global.get $heap))
    (global.set $heap (i32.add (local.get $p) (i32.and (i32.add (local.get $n) (i32.const 7)) (i32.const -8))))
    (local.get $p))'''


def make_plugin(name, wat, **manifest):
    d = Path(TMP_HOME) / "plugins" / name
    (d / "src").mkdir(parents=True, exist_ok=True)
    m = {"name": name, "version": "1.0.0", "type": "plugin", "runtime": "wasm", "wasm": "plugin.wasm"}
    m.update(manifest)
    (d / MANIFEST).write_text(json.dumps(m))
    (d / "src" / "plugin.wat").write_text(wat)            # shell ho sestaví sám
    return d


class TestWasmPluginRuntime(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def plugin(self, name, wat, **manifest):
        d = make_plugin(name, wat, **manifest)
        self.dirs.append(d)
        return d

    def test_template_plugin_runs_command_event_and_segment(self):
        d = Path(TMP_HOME) / "plugins" / "tpl_wasm"
        self.dirs.append(d)
        scaffold("wasm-wat", "tpl_wasm")
        sh = new_shell()
        self.assertEqual(sh.manager.status["tpl_wasm"], "loaded", sh.manager.status["tpl_wasm"])
        out = []
        sh.say = out.append
        self.assertEqual(sh.run_line("tpl_wasm"), 0)
        self.assertEqual(out, ["Ahoj z WASM pluginu!"])
        for _ in range(12):
            sh.events.emit("command_after", line="x", command="x", rc=0, duration=0.0)
        # 1× command_after od samotného spuštění příkazu + 12 ručně vyvolaných
        self.assertEqual(sh.segments["tpl_wasm"][0]({}), "13")
        self.assertEqual(sh.render_template("[{tpl_wasm}]", sh.prompt_context()), "[13]")

    def test_event_can_rewrite_line_and_cancel(self):
        self.plugin("rewriter", f'''(module (import "leapsh" "result" (func $r (param i32 i32)))
          {ALLOC}
          (data (i32.const 64) "echo prepsano")
          (func (export "leapsh_event") (param i32 i32 i32 i32) (result i32)
            (call $r (i32.const 64) (i32.const 13)) (i32.const 0)))''', events=["command_before"])
        self.plugin("vetoer", f'''(module {ALLOC}
          (func (export "leapsh_event") (param i32 i32 i32 i32) (result i32) (i32.const 1)))''',
                    events=["command_after"])
        sh = new_shell()
        ev = sh.events.emit("command_before", line="puvodni")
        self.assertEqual(ev.data["line"], "echo prepsano")
        self.assertTrue(sh.events.emit("command_after", line="x", rc=0).cancelled)

    def test_event_and_args_are_passed_as_json(self):
        self.plugin("echoer", f'''(module (import "leapsh" "say" (func $say (param i32 i32)))
          {ALLOC}
          (func (export "leapsh_command") (param $np i32) (param $nl i32) (param $ap i32) (param $al i32) (result i32)
            (call $say (local.get $ap) (local.get $al)) (i32.const 7)))''', commands=["echoer"])
        sh = new_shell()
        out = []
        sh.say = out.append
        rc = sh.run_line('echoer "a b" ž')
        self.assertEqual(json.loads(out[0]), ["a b", "ž"])
        self.assertEqual(rc, 7)                                  # návratová hodnota modulu = kód příkazu

    def test_sandbox_infinite_loop_trap_and_memory_bomb(self):
        self.plugin("evil", f'''(module {ALLOC}
          (func (export "leapsh_command") (param $np i32) (param $nl i32) (param $ap i32) (param $al i32) (result i32)
            (if (i32.eq (i32.load8_u (local.get $ap)) (i32.const 91))   ;; args začínají "[" vždy -> použijeme 2. znak
              (then))
            (if (i32.eq (i32.load8_u (i32.add (local.get $ap) (i32.const 2))) (i32.const 108)) ;; "l" = loop
              (then (loop $l (br $l))))
            (if (i32.eq (i32.load8_u (i32.add (local.get $ap) (i32.const 2))) (i32.const 116)) ;; "t" = trap
              (then unreachable))
            (if (i32.eq (i32.load8_u (i32.add (local.get $ap) (i32.const 2))) (i32.const 109)) ;; "m" = memory bomb
              (then (drop (memory.grow (i32.const 100000)))))
            (i32.const 0)))''', commands=["evil"], limits={"fuel": 10000, "memory_pages": 4})
        sh = new_shell()
        errors = []
        sh.report_error = lambda owner, where, exc: errors.append((owner, str(exc)))
        self.assertEqual(sh.run_line("evil loop"), 1)
        self.assertEqual(sh.run_line("evil trap"), 1)
        self.assertEqual(sh.run_line("evil mem"), 0)             # grow vrátí -1, modul pokračuje, shell žije
        self.assertEqual(sh.run_line("evil ok"), 0)
        self.assertTrue(any("limit instrukcí" in e[1] for e in errors), errors)
        self.assertTrue(any("unreachable" in e[1] for e in errors), errors)

    def test_bad_plugins_fail_to_load_not_the_shell(self):
        self.plugin("badimport", '(module (import "env" "system" (func (param i32))) (memory (export "memory") 1))')
        self.plugin("missingexport", f"(module {ALLOC})", commands=["x"])
        self.plugin("badwat", "(module (func (i32.nonsense)))")
        sh = new_shell()
        for n, text in (("badimport", "import"), ("missingexport", "leapsh_command"), ("badwat", "nonsense")):
            self.assertTrue(sh.manager.status[n].startswith("error"), (n, sh.manager.status[n]))
            self.assertIn(text, sh.manager.status[n])
        self.assertIn("git_prompt", sh.manager.loaded)


class TestDevtools(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_compile_python_catches_syntax_error_and_missing_class(self):
        d = scaffold("plugin", "pyp", root=self.tmp)
        log = []
        ok, pkg = compile_plugin(d, self.tmp / "dist", log=log.append)
        self.assertTrue(ok and pkg.name == "pyp-0.1.0.leapsh")
        (d / "src" / "main.py").write_text("def x(:\n")
        ok, pkg = compile_plugin(d, self.tmp / "dist", log=log.append)
        self.assertFalse(ok)
        self.assertTrue(any("main.py:1" in line for line in log))
        (d / "src" / "main.py").write_text("x = 1\n")
        self.assertFalse(compile_plugin(d, pack=False, log=log.append)[0])

    def test_compile_wasm_builds_validates_and_packs(self):
        d = scaffold("wasm-wat", "wp", root=self.tmp)
        (d / "src" / "plugin.wasm").unlink(missing_ok=True)
        log = []
        ok, pkg = compile_plugin(d, self.tmp / "dist", include_source=False, log=log.append)
        self.assertTrue(ok, log)
        names = zipfile.ZipFile(pkg).namelist()
        self.assertIn("wp/src/plugin.wasm", names)
        self.assertNotIn("wp/src/plugin.wat", names)             # --no-source
        # syntaktická chyba ve WAT
        (d / "src" / "plugin.wat").write_text("(module (func (br $nikde)))")
        self.assertFalse(compile_plugin(d, pack=False, log=log.append)[0])
        # nepovolený import
        (d / "src" / "plugin.wat").write_text(
            '(module (import "env" "x" (func)) (memory (export "memory") 1) (func (export "leapsh_command") '
            '(param i32 i32 i32 i32) (result i32) (i32.const 0)) (func (export "leapsh_alloc") (param i32) (result i32) (i32.const 0)))')
        log.clear()
        self.assertFalse(compile_plugin(d, pack=False, log=log.append)[0])
        self.assertTrue(any("import env.x" in line for line in log), log)

    def test_install_roundtrip_force_and_zip_slip(self):
        d = scaffold("plugin", "inst", root=self.tmp / "src_plugins")
        _, pkg = compile_plugin(d, self.tmp / "dist", log=lambda s: None)
        root = self.tmp / "installed"
        dest = install_package(pkg, root=root)
        self.assertTrue((dest / MANIFEST).is_file() and (dest / "src" / "main.py").is_file())
        with self.assertRaises(FileExistsError):
            install_package(pkg, root=root)
        install_package(pkg, force=True, root=root)
        evil = self.tmp / "evil.leapsh"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("evil/" + MANIFEST, json.dumps({"name": "evil"}))
            z.writestr("evil/../../escape.txt", "x")
        with self.assertRaises(ValueError):
            install_package(evil, root=root)
        self.assertFalse((self.tmp / "escape.txt").exists())

    def test_cli_scripts(self):
        env = dict(os.environ, LEAPSH_HOME=str(self.tmp / "cfg"), PYTHONPATH=str(ROOT))
        py = [sys.executable]
        r = subprocess.run(py + [str(ROOT / "tools" / "leapsh-plugin-init.py"), "cli_w", "--runtime", "wasm",
                                 "--dir", str(self.tmp)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "cli_w" / "src" / "plugin.wasm").is_file())
        r = subprocess.run(py + [str(ROOT / "tools" / "leapsh-compile-plugin.py"), str(self.tmp / "cli_w"), "-o",
                                 str(self.tmp / "out")], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / "out" / "cli_w-0.1.0.leapsh").is_file())
        r = subprocess.run(["sh", str(ROOT / "tools" / "leapsh-plugin-init.sh"), "cli_c", "--runtime", "wasm", "--lang",
                            "c", "--dir", str(self.tmp)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "cli_c" / "src" / "plugin.c").is_file())
        r = subprocess.run(py + [str(ROOT / "tools" / "leapsh-plugin-init.py"), "addon_x", "--type", "addon"],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)                     # addon bez --extends
        r = subprocess.run(py + [str(ROOT / "tools" / "leapsh-plugin-init.py"), "Bad-Name", "--dir", str(self.tmp)],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
