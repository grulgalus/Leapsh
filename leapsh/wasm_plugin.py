"""WASM plugin: modul běží v sandboxu (leapsh/wasm.py) a komunikuje se shellem přes ABI v1.

Manifest (config.json):
    "runtime": "wasm", "wasm": "plugin.wasm",
    "commands": {"jméno": "nápověda"}, "events": ["command_after"], "segments": ["jméno"],
    "limits": {"fuel": 2000000, "memory_pages": 64}

Co modul exportuje:
    memory                                  (povinné)
    leapsh_alloc(size) -> ptr               (povinné, když se předávají řetězce)
    leapsh_free(ptr, size)                  (volitelné; hostitel uvolňuje v opačném pořadí než alokoval)
    leapsh_on_load() / leapsh_on_unload()   (volitelné)
    leapsh_event(name_ptr, name_len, json_ptr, json_len) -> int      0 = pokračuj, 1 = zruš událost
    leapsh_command(name_ptr, name_len, args_ptr, args_len) -> int    návratový kód příkazu; args = JSON pole
    leapsh_segment(name_ptr, name_len) -> int                        text vrať přes import result()
Co modul smí importovat (modul "leapsh"):
    say(ptr, len)  warn(ptr, len)  result(ptr, len)  setting_int(key_ptr, key_len, default) -> i32  time_ms() -> i64
"""
import json
import time
from pathlib import Path

from .api import Plugin
from .wasm import M64, Instance, Trap, WasmError
from .wat import WatError, assemble

ALLOWED_IMPORTS = {"say", "warn", "result", "setting_int", "time_ms"}
RESULT_FIELDS = {"command_before": "line", "prompt_render": "prompt"}


def locate(src, manifest):
    """-> (výstupní .wasm, zdroj .wat/.c/.rs | None). Jméno z "wasm" v config.json, jinak podle souborů v src/."""
    src = Path(src)
    if manifest.get("wasm"):
        stem = Path(manifest["wasm"]).stem
    else:
        stems = sorted({p.stem for p in src.iterdir() if p.suffix in (".wasm", ".wat", ".c", ".rs")}) if src.is_dir() else []
        if "plugin" in stems or not stems:
            stem = "plugin"
        elif len(stems) == 1:
            stem = stems[0]
        else:
            raise RuntimeError(f"src/ obsahuje víc WASM zdrojů ({', '.join(stems)}); uveď v config.json: \"wasm\": \"…\"")
    out = src / (manifest.get("wasm") or f"{stem}.wasm")
    source = next((src / f"{stem}{ext}" for ext in (".wat", ".c", ".rs") if (src / f"{stem}{ext}").is_file()), None)
    return out, source


def load_module_bytes(out, source):
    """Hotový .wasm, nebo (při vývoji) sestavení z .wat za běhu."""
    if out.is_file():
        return out.read_bytes()
    if source is not None and source.suffix == ".wat":
        try:
            return assemble(source.read_text(encoding="utf-8"))
        except WatError as exc:
            raise RuntimeError(f"{source.name}: {exc}") from None
    raise FileNotFoundError(f"chybí {out.name} – spusť leapsh-compile-plugin {out.parent.parent}")


class WasmPlugin(Plugin):
    runtime = "wasm"

    def on_load(self):
        man = self.manifest
        out, source = locate(self.path / "src", man)
        data = load_module_bytes(out, source)
        lim = man.get("limits", {})
        self._result, self.inst = None, None
        self.inst = Instance(data, imports={"leapsh": self._host()}, fuel=int(lim.get("fuel", 2_000_000)),
                             max_pages=int(lim.get("memory_pages", 64)))
        commands = man.get("commands", {})
        commands = {c: "" for c in commands} if isinstance(commands, list) else commands
        events, segments = man.get("events", []), man.get("segments", [])
        for need, present in (("leapsh_command", commands), ("leapsh_event", events), ("leapsh_segment", segments)):
            if present and not self.inst.has(need):
                raise RuntimeError(f"manifest deklaruje {need.split('_')[1]}, ale modul neexportuje {need}")
        for name, help_ in commands.items():
            self.add_command(name, lambda sh, args, n=name: self._command(n, args), help_ or f"(WASM: {self.name})")
        for ev in events:
            self.on(ev, lambda e, n=ev: self._event(n, e))
        for seg in segments:
            self.add_segment(seg, lambda ctx, n=seg: self._segment(n))
        if self.inst.has("leapsh_on_load"):
            self.call("leapsh_on_load")

    def on_unload(self):
        if self.inst and self.inst.has("leapsh_on_unload"):
            self.call("leapsh_on_unload")

    # ---------- hostitelské funkce (jediné, co modul vidí) ----------
    def _host(self):
        def text(ptr, n):
            return self.inst.read(ptr, n).decode("utf-8", "replace") if self.inst else ""

        def say(p, n):
            self.shell.say(text(p, n))

        def warn(p, n):
            self.shell.warn(text(p, n))

        def result(p, n):
            self._result = text(p, n)

        def setting_int(kp, kn, default):
            try:
                return int(self.setting(text(kp, kn), default)) & 0xFFFFFFFF
            except (TypeError, ValueError):
                return default & 0xFFFFFFFF

        return {"say": say, "warn": warn, "result": result, "setting_int": setting_int,
                "time_ms": lambda: int(time.time() * 1000) & M64}

    # ---------- volání do modulu ----------
    def call(self, export, *args):
        """Bezpečné volání exportu; chyba (past, limit) se nahlásí a vrátí se None."""
        try:
            return self.inst.call(export, *args)
        except (Trap, WasmError) as exc:
            self.shell.report_error(self.name, f"wasm:{export}", exc)
            return None

    def _put(self, text, allocs):
        b = text.encode("utf-8")
        if not b:
            return 0, 0
        ptr = self.inst.call("leapsh_alloc", len(b))
        self.inst.write(ptr, b)
        allocs.append((ptr, len(b)))
        return ptr, len(b)

    def _free(self, allocs):
        if self.inst.has("leapsh_free"):
            for ptr, n in reversed(allocs):
                try:
                    self.inst.call("leapsh_free", ptr, n)
                except (Trap, WasmError):
                    break

    def _invoke(self, export, *texts):
        allocs, res = [], None
        try:
            ptrs = []
            for t in texts:
                ptrs += self._put(t, allocs)
            self._result = None
            res = self.inst.call(export, *ptrs)
        except (Trap, WasmError) as exc:
            self.shell.report_error(self.name, f"wasm:{export}", exc)
        finally:
            try:
                self._free(allocs)
            except Exception:
                pass
        return res

    def _event(self, name, ev):
        data = {k: v for k, v in ev.data.items() if v is None or isinstance(v, (str, int, float, bool))}
        rc = self._invoke("leapsh_event", name, json.dumps(data, ensure_ascii=False))
        if rc == 1:
            ev.cancel()
        field = RESULT_FIELDS.get(name)
        if field and self._result:
            ev.data[field] = self._result

    def _command(self, name, args):
        rc = self._invoke("leapsh_command", name, json.dumps(list(args), ensure_ascii=False))
        return 1 if rc is None else int(rc)

    def _segment(self, name):
        self._invoke("leapsh_segment", name)
        return self._result or ""
