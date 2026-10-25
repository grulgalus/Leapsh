"""Hledání a načítání pluginů, témat a addonů."""
import importlib.util
import json
import sys
from pathlib import Path

from .api import Addon, Plugin, ThemePlugin
import os

from .config import APP_DIR, LEGACY_MANIFESTS, MANIFEST, config_dir, platform_tags
from .settings import RESERVED_NAMES


def entry_file(src, manifest, name, strict=True):
    """Vstupní .py soubor pluginu: "main" z config.json, jinak main.py, <jméno>.py, nebo jediný .py v src/."""
    if manifest.get("main"):
        f = src / manifest["main"]
        if f.is_file() or not strict:
            return f if f.is_file() else None
        raise FileNotFoundError(f"src/{manifest['main']} z config.json neexistuje")
    for cand in ("main.py", f"{name}.py"):
        if (src / cand).is_file():
            return src / cand
    pys = sorted(p for p in src.glob("*.py") if not p.name.startswith("_")) if src.is_dir() else []
    if len(pys) == 1:
        return pys[0]
    if not strict:
        return None
    if not pys:
        raise FileNotFoundError("v src/ není žádný .py soubor (a ani WASM modul)")
    raise RuntimeError(f"src/ obsahuje víc souborů ({', '.join(p.name for p in pys)}); "
                       f'vstupní soubor uveď v config.json: "main": "…"')


def _vtuple(v):
    return tuple(int(x) for x in __import__("re").findall(r"\d+", v)[:3]) or (0,)


def detect_runtime(path, manifest):
    """runtime z config.json; bez něj: .py v src/ = python, .wasm/.wat/.c/.rs = wasm."""
    if manifest.get("runtime") in ("python", "wasm"):
        return manifest["runtime"]
    src = Path(path) / "src"
    if src.is_dir():
        if any(src.glob("*.py")):
            return "python"
        if any(p.suffix in (".wasm", ".wat", ".c", ".rs") for p in src.iterdir()):
            return "wasm"
    return "python"


class Entry:
    def __init__(self, name, manifest, path, kind):
        self.name, self.manifest, self.path, self.kind = name, manifest, Path(path), kind


class PluginManager:
    def __init__(self, shell):
        self.shell = shell
        self.found = {}
        self.loaded = {}   # pluginy a témata
        self.addons = {}
        self.status = {}

    # ---------- hledání ----------
    @staticmethod
    def bases(sub):
        out = [APP_DIR / sub, config_dir() / sub]          # uživatelský adresář přebíjí vestavěný
        if sub == "plugins" and os.environ.get("LEAPSH_DEV"):
            out.append(config_dir() / "plugins-dev")        # vývojářský režim (--dev)
        return out

    def discover(self):
        """Plugin = složka s <shell>.json (manifest) a kódem v src/."""
        self.found.clear()
        for sub in ("plugins", "addons"):
            for base in self.bases(sub):
                if not base.is_dir():
                    continue
                for d in sorted(base.iterdir()):
                    if d.name in RESERVED_NAMES:        # plugins/config/ = nastavení pluginů, ne plugin
                        continue
                    mpath = next((d / n for n in (MANIFEST,) + LEGACY_MANIFESTS if (d / n).is_file()), None)
                    if mpath is None:
                        continue
                    try:
                        manifest = json.loads(mpath.read_text(encoding="utf-8"))
                    except (OSError, ValueError) as exc:
                        self.status[d.name] = f"error: špatný {mpath.name}: {exc}"
                        continue
                    name = manifest.setdefault("name", d.name)
                    kind = manifest.get("type", "plugin")
                    if sub == "addons" or kind == "addon":
                        kind = "addon"
                    elif kind not in ("plugin", "theme"):
                        kind = "plugin"
                    self.found[name] = Entry(name, manifest, d, kind)

    @staticmethod
    def platform_ok(manifest):
        wanted = manifest.get("platforms")
        return not wanted or bool(set(wanted) & platform_tags())

    # ---------- načítání ----------
    def load_all(self):
        self.discover()
        for kind_group in (("plugin", "theme"), ("addon",)):
            for name, e in sorted(self.found.items()):
                if e.kind in kind_group:
                    self.load(name)

    def load(self, name, _stack=()):
        e = self.found.get(name)
        if e is None:
            self.status[name] = "error: nenalezen"
            return False
        if name in self.loaded or name in self.addons:
            return True
        if name in _stack:
            self.status[name] = "error: cyklická závislost"
            return False
        if name in self.shell.config.data.get("disabled", []):
            self.status[name] = "disabled"
            return False
        if not self.platform_ok(e.manifest):
            self.status[name] = "skipped: jen pro " + ", ".join(e.manifest["platforms"])
            return False
        need = e.manifest.get("min_shell")
        if need:
            from . import __version__
            if _vtuple(__version__) < _vtuple(str(need)):
                self.status[name] = f"skipped: potřebuje leapsh ≥ {need} (máš {__version__})"
                return False
        stack = _stack + (name,)
        for dep in e.manifest.get("requires", []):
            if not self.load(dep, stack):
                self.status[name] = f"skipped: chybí závislost {dep}"
                return False
        target = None
        if e.kind == "addon":
            tname = e.manifest.get("extends")
            if not tname:
                self.status[name] = "error: addon nemá klíč 'extends'"
                return False
            if not self.load(tname, stack):
                self.status[name] = f"skipped: cílový plugin {tname} není aktivní"
                return False
            target = self.loaded[tname]
        old_flag = sys.dont_write_bytecode
        bundled = APP_DIR in e.path.parents
        sys.dont_write_bytecode = not bundled   # uživatelské pluginy bez .pyc (hot-reload = čerstvý zdroj), vestavěné s .pyc (rychlý start)
        try:
            inst = self._instantiate(e, target)
            inst.on_load()
        except Exception as exc:
            self.shell.cleanup_owner(name)
            self._forget_modules(name)
            self.status[name] = f"error: {exc}"
            self.shell.report_error(name, "load", exc)
            return False
        finally:
            sys.dont_write_bytecode = old_flag
        (self.addons if e.kind == "addon" else self.loaded)[name] = inst
        self.status[name] = "loaded"
        self.shell.events.emit("plugin_loaded", name=name, kind=e.kind)
        return True

    def _instantiate(self, e, target):
        if detect_runtime(e.path, e.manifest) == "wasm" and e.kind == "plugin":
            from .wasm_plugin import WasmPlugin
            return WasmPlugin(self.shell, e.manifest, e.path)
        src = e.path / "src"
        if e.kind == "theme" and not entry_file(src, e.manifest, e.name, strict=False):
            return ThemePlugin(self.shell, e.manifest, e.path)
        main = entry_file(src, e.manifest, e.name)
        modname = f"leapsh_ext_{e.name}"
        # src/ je balíček: v main.py jde dělat `from .pomocnik import x`
        spec = importlib.util.spec_from_file_location(modname, main, submodule_search_locations=[str(src)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        base = Addon if e.kind == "addon" else Plugin
        cls = None
        for c in list(vars(mod).values()):
            if isinstance(c, type) and issubclass(c, base) and c.__module__ == modname \
                    and c not in (Plugin, Addon, ThemePlugin):
                cls = c
                break
        if cls is None:
            raise RuntimeError(f"{main.name} neobsahuje třídu odvozenou od {base.__name__}")
        if e.kind == "addon":
            return cls(self.shell, e.manifest, e.path, target)
        return cls(self.shell, e.manifest, e.path)

    # ---------- odebírání ----------
    def _teardown(self, inst, name):
        try:
            inst.on_unload()
        except Exception as exc:
            self.shell.report_error(name, "unload", exc)
        if inst.kind == "addon":
            inst._detach()
        self.shell.cleanup_owner(name)
        self._forget_modules(name)
        self.shell.events.emit("plugin_unloaded", name=name, kind=inst.kind)

    @staticmethod
    def _forget_modules(name):
        base = f"leapsh_ext_{name}"
        for k in [k for k in sys.modules if k == base or k.startswith(base + ".")]:
            del sys.modules[k]

    def unload(self, name):
        if name in self.addons:
            self._teardown(self.addons.pop(name), name)
            self.status[name] = "unloaded"
            return True
        p = self.loaded.get(name)
        if p is None:
            return False
        for an, a in list(self.addons.items()):
            if a.target is p:
                self._teardown(self.addons.pop(an), an)
                self.status[an] = f"skipped: cílový plugin {name} není aktivní"
        self._teardown(self.loaded.pop(name), name)
        self.status[name] = "unloaded"
        return True

    def unload_all(self):
        for name in list(self.addons):
            self.unload(name)
        for name in list(self.loaded):
            self.unload(name)

    def reload_all(self):
        self.unload_all()
        self.status.clear()
        self.load_all()

    def reload(self, name):
        """Znovu načte jeden plugin (i s jeho addony) – změny v kódu i v config.json se projeví bez restartu."""
        if name not in self.found:
            self.discover()
        if name not in self.found:
            return False
        self.unload(name)
        self.discover()
        self.status.pop(name, None)
        self.shell._err_count.pop(name, None)
        ok = self.load(name)
        for an, e in list(self.found.items()):
            if e.kind == "addon" and e.manifest.get("extends") == name:
                self.status.pop(an, None)
                self.load(an)
        return ok

    def enable(self, name):
        dis = self.shell.config.data.setdefault("disabled", [])
        if name in dis:
            dis.remove(name)
            self.shell.config.save()
        ok = self.load(name)
        for an, e in self.found.items():
            if e.kind == "addon" and e.manifest.get("extends") == name:
                self.load(an)
        return ok

    def disable(self, name):
        dis = self.shell.config.data.setdefault("disabled", [])
        if name not in dis:
            dis.append(name)
            self.shell.config.save()
        self.unload(name)
        self.status[name] = "disabled"

    def addons_of(self, name):
        return [a for a in self.addons.values() if a.target.name == name]
