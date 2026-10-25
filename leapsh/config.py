"""Cesty a konfigurace."""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "leapsh"
MANIFEST = "config.json"        # manifest pluginu: <složka>/config.json
LEGACY_MANIFESTS = ("gluesh.json",)   # starší název z verze 2.x, pořád se čte
LEGACY_HOMES = ("boltsh", "gluesh", "plush")    # staré složky v ~/.config, ze kterých se jednorázově převezmou data

DEFAULTS = {
    "theme": "rounded",
    "lang": "cs",
    "startup_msg": True,
    "permissions": {},
    "termux": {"auto": True},
    "warn_not_termux": True,
    "disabled": ["highlight_rainbow"],
    "aliases": {"ll": "ls -la --color=auto", "la": "ls -A --color=auto", "ls": "ls --color=auto", "grep": "grep --color=auto", "c": "clear"},
    "history_size": 5000,
    "history_dedupe": True,
    "tab_cycle": True,
}


_TERMUX = None


def is_termux():
    """Jsme v Termuxu? (jednou zjistí a zapamatuje; pravidla viz env_check.detect_termux)"""
    global _TERMUX
    if _TERMUX is None:
        from .env_check import detect_termux
        _TERMUX = detect_termux()
    return _TERMUX


def platform_tags():
    tags = {"any", sys.platform}
    if sys.platform.startswith("linux"):
        tags.add("linux")
    if is_termux():
        tags |= {"termux", "android"}
    return tags


def config_dir():
    if os.environ.get("LEAPSH_HOME"):
        return Path(os.environ["LEAPSH_HOME"])
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "leapsh"


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "config.json"
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"[leapsh] nelze uložit konfiguraci: {e}", file=sys.stderr)
