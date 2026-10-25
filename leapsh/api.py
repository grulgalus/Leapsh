"""API pro pluginy, addony a témata."""
from collections import defaultdict
from pathlib import Path


class Extension:
    kind = "plugin"

    def __init__(self, shell, manifest, path):
        self.shell = shell
        self.manifest = manifest
        self.path = Path(path)
        self.name = manifest["name"]

    @property
    def version(self):
        return self.manifest.get("version", "0")

    # --- životní cyklus (přepiš) ---
    def on_load(self):
        pass

    def on_unload(self):
        pass

    # --- pomocníci ---
    def on(self, event, fn, priority=0):
        """Přihlásí handler události: fn(ev)."""
        self.shell.events.on(event, fn, priority, owner=self.name)

    def add_command(self, name, fn, help=""):
        """Nový příkaz shellu: fn(shell, args) -> int."""
        self.shell.add_command(name, fn, help, owner=self.name)

    def add_segment(self, name, fn):
        """Segment promptu {name}: fn(ctx) -> str."""
        self.shell.add_segment(name, fn, owner=self.name)

    def add_theme(self, name, data):
        return self.shell.add_theme(name, data, owner=self.name)

    def setting(self, key, default=None):
        """Nastavení pluginu: soubor ~/.config/<shell>/plugins/config/<plugin>.json, jinak výchozí z config.json pluginu."""
        user = self.shell.plugin_settings.load(self.name)
        if key in user:
            return user[key]
        return self.manifest.get("settings", {}).get(key, default)

    def settings(self):
        """Všechna nastavení (výchozí + uživatelská) jako slovník."""
        out = dict(self.manifest.get("settings", {}))
        out.update(self.shell.plugin_settings.load(self.name))
        return out

    def set_setting(self, key, value):
        self.shell.plugin_settings.set(self.name, key, value)

    def say(self, text=""):
        self.shell.say(text)

    def load_wasm(self, name, imports=None, fuel=5_000_000, max_pages=64):
        """Načte WASM modul ze src/ (zadej jméno souboru .wasm nebo .wat) do sandboxu a vrátí wasm.Instance.
        Python plugin tak může volat rychlé/izolované funkce: inst = self.load_wasm("fast.wasm"); inst.call("sum", 1, 2)"""
        from .wasm import Instance
        from .wasm_plugin import load_module_bytes
        p = self.path / "src" / name
        data = load_module_bytes(p.with_suffix(".wasm"), p.with_suffix(".wat") if p.with_suffix(".wat").exists() else None)
        return Instance(data, imports or {}, fuel=fuel, max_pages=max_pages)

    @property
    def xapi(self):
        """XAPI s oprávněními: xapi.battery(), xapi.ip(), …"""
        from .xapi import XAPI
        if not hasattr(self, "_xapi"):
            self._xapi = XAPI(self.shell, self.name)
        return self._xapi

    def style(self, spec):
        from .theme import style_code
        return style_code(spec) or ""


class Plugin(Extension):
    """Základ pluginu. Plugin může nabídnout 'extension points', do kterých se zapojují addony."""
    kind = "plugin"
    provides = []

    def __init__(self, shell, manifest, path):
        super().__init__(shell, manifest, path)
        self.extensions = defaultdict(list)

    def extend(self, point, fn, owner=None):
        self.extensions[point].append((owner or self.name, fn))

    def remove_extensions(self, owner):
        for point in list(self.extensions):
            self.extensions[point] = [(o, f) for o, f in self.extensions[point] if o != owner]

    def run_extensions(self, point, value, **ctx):
        """Pošle value postupně všemi rozšířeními: fn(value, **ctx). Vrácená hodnota (ne None) nahradí value."""
        for owner, fn in list(self.extensions.get(point, [])):
            try:
                res = fn(value, **ctx)
                if res is not None:
                    value = res
            except Exception as exc:
                self.shell.report_error(owner, f"extension:{point}", exc)
        return value


class ThemePlugin(Plugin):
    """Téma definované jen v config.json (klíč "theme" nebo "themes"), bez kódu."""
    kind = "theme"

    def on_load(self):
        """V manifestu klíč "theme" (jedno téma) nebo "themes" (seznam – balíček témat)."""
        defs = self.manifest.get("themes") or [self.manifest.get("theme", {})]
        self.themes = {}
        for t in defs:
            tid = t.get("name") or self.name.removeprefix("theme_")
            self.themes[tid] = t
            self.add_theme(tid, t)
        self.theme = defs[0]
        self.theme_id = self.theme.get("name") or self.name.removeprefix("theme_")


class Addon(Extension):
    """Doplněk existujícího pluginu. self.target je instance rozšiřovaného pluginu."""
    kind = "addon"

    def __init__(self, shell, manifest, path, target):
        super().__init__(shell, manifest, path)
        self.target = target
        self._wraps = []

    def extend(self, point, fn):
        """Zapojí fn do extension pointu cílového pluginu."""
        self.target.extend(point, fn, owner=self.name)

    def wrap(self, method_name, wrapper):
        """Obalí metodu cílového pluginu: wrapper(original, *args, **kwargs)."""
        t = self.target
        had = method_name in vars(t)
        prev = vars(t).get(method_name)
        orig = getattr(t, method_name)

        def wrapped(*a, **k):
            return wrapper(orig, *a, **k)

        setattr(t, method_name, wrapped)
        self._wraps.append((method_name, had, prev))

    def _detach(self):
        for m, had, prev in reversed(self._wraps):
            if had:
                setattr(self.target, m, prev)
            else:
                try:
                    delattr(self.target, m)
                except AttributeError:
                    pass
        self._wraps.clear()
        self.target.remove_extensions(self.name)
