"""Nastavení pluginů: jeden JSON soubor na plugin v ~/.config/leapsh/plugins/config/<plugin>.json.

Pořadí hodnot: config.json pluginu ("settings" = výchozí hodnoty)  <  soubor v plugins/config/  (to, co nastavil uživatel).
"""
import json
import os

from .config import config_dir

RESERVED_NAMES = ("config", "data")        # názvy složek v plugins/, které nejsou pluginy


def parse_value(raw, existing=None):
    """Text z příkazové řádky -> hodnota se stejným typem, jaký má existující hodnota (bool, číslo, text, seznam…)."""
    if not isinstance(raw, str):
        return raw
    if isinstance(existing, bool):
        low = raw.strip().lower()
        if low in ("true", "1", "yes", "ano", "on", "zapnuto"):
            return True
        if low in ("false", "0", "no", "ne", "off", "vypnuto"):
            return False
        raise ValueError("očekávám true nebo false")
    if isinstance(existing, str):
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            try:
                return json.loads(raw)
            except ValueError:
                pass
        return raw
    if isinstance(existing, int):
        try:
            return int(raw)
        except ValueError:
            raise ValueError("očekávám celé číslo") from None
    if isinstance(existing, float):
        try:
            return float(raw)
        except ValueError:
            raise ValueError("očekávám číslo") from None
    if isinstance(existing, (list, dict)):
        try:
            val = json.loads(raw)
        except ValueError:
            raise ValueError("očekávám JSON " + ("seznam [..]" if isinstance(existing, list) else "objekt {..}")) from None
        if not isinstance(val, type(existing)):
            raise ValueError("špatný typ (čekám " + ("seznam" if isinstance(existing, list) else "objekt") + ")")
        return val
    try:
        return json.loads(raw)
    except ValueError:
        return raw


class PluginSettings:
    def __init__(self, shell):
        self.shell = shell
        self._cache = {}

    @property
    def dir(self):
        return config_dir() / "plugins" / "config"

    def path(self, name):
        return self.dir / f"{name}.json"

    def reset_cache(self):
        self._cache.clear()

    def load(self, name):
        if name not in self._cache:
            try:
                data = json.loads(self.path(name).read_text(encoding="utf-8"))
                self._cache[name] = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._cache[name] = {}
        return self._cache[name]

    def get(self, name, key, default=None):
        return self.load(name).get(key, default)

    def names(self):
        try:
            return sorted(p.stem for p in self.dir.glob("*.json"))
        except OSError:
            return []

    def _save(self, name):
        data = self.load(name)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path(name).with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path(name))
        except OSError as exc:
            self.shell.warn(f"nelze uložit nastavení {name}: {exc}")

    def set(self, name, key, value):
        data = self.load(name)
        old = data.get(key)
        data[key] = value
        self._save(name)
        self.shell.events.emit("plugin_setting_change", plugin=name, key=key, old=old, new=value)

    def unset(self, name, key):
        data = self.load(name)
        if key not in data:
            return False
        old = data.pop(key)
        if data:
            self._save(name)
        else:
            self.path(name).unlink(missing_ok=True)
        self.shell.events.emit("plugin_setting_change", plugin=name, key=key, old=old, new=None)
        return True

    def migrate_legacy(self, config):
        """Starší verze držely nastavení pluginů v config.json ("settings"): přesune se do souborů."""
        old = config.data.pop("settings", None)
        if not isinstance(old, dict) or not old:
            return
        for name, values in old.items():
            if isinstance(values, dict) and values:
                merged = dict(values)
                merged.update(self.load(name))          # co už je v souboru, má přednost
                self._cache[name] = merged
                self._save(name)
        config.save()
