"""Kontrola prostředí při startu: Termux, Termux:API, jednorázové převzetí dat ze starých složek.

Výsledek se zapisuje do ~/.config/leapsh/config.json:
    "termux": {"available": true, "api": true, "api_working": true}
available = jsme v Termuxu (příkaz `pkg` + Termux), api = je nainstalovaný balíček termux-api,
api_working = aplikace Termux:API opravdu odpovídá (ověřuje se na pozadí, aby start nebyl pomalejší).
"""
import json
import os
from ._fast import which
from .config import LEGACY_HOMES, config_dir

API_PROBE = "termux-battery-status"


def detect_termux():
    """Termux = proměnné prostředí Termuxu, nebo příkaz `pkg` v Termuxu (ne pkg z FreeBSD apod.)."""
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get("PREFIX", ""):
        return True
    pkg = which("pkg")
    return bool(pkg and (os.path.isdir("/data/data/com.termux") or "termux" in os.path.realpath(pkg).lower()))


def _probe_api(config):
    """Na pozadí: odpovídá aplikace Termux:API? (balíček sám nestačí – bez aplikace volání visí/selže)"""
    import subprocess
    ok = False
    try:
        r = subprocess.run([API_PROBE], capture_output=True, text=True, timeout=6)
        ok = r.returncode == 0 and "percentage" in json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        ok = False
    t = config.data.setdefault("termux", {})
    if t.get("api_working") != ok:
        t["api_working"] = ok
        config.save()


def check_environment(config, probe=True):
    """Aktualizuje config["termux"] a vrátí seznam upozornění [(úroveň, text)] pro začátek relace."""
    t = config.data.get("termux")
    t = t if isinstance(t, dict) else {}
    old = dict(t)
    if t.get("auto", True):
        t["available"] = detect_termux()
        t["api"] = bool(t["available"] and which(API_PROBE))
        if not t["available"]:
            t["api_working"] = False
    config.data["termux"] = t
    notices = []
    if t.get("available"):
        if not t.get("api"):
            notices.append(("warn", "V Termuxu chybí Termux:API – nebudou fungovat baterie, notifikace ani vibrace. "
                                    "Oprava: pkg install termux-api a nainstaluj aplikaci Termux:API (F-Droid)."))
        else:
            if probe:
                import threading
                threading.Thread(target=_probe_api, args=(config,), daemon=True).start()
            if t.get("api_working") is False:
                notices.append(("warn", "Balíček termux-api je nainstalovaný, ale aplikace Termux:API neodpovídá. "
                                        "Spusť ji alespoň jednou a povol jí oprávnění."))
    elif config.data.get("warn_not_termux", True):
        notices.append(("info", "Nejsi v Termuxu – funkce jen pro Termux (baterie, vibrace, notifikace, Termux:API) "
                                "nebudou dostupné. Všechno ostatní funguje. "
                                '(Vypnout toto hlášení: "warn_not_termux": false v config.json)'))
    if t != old:
        config.save()
    return notices


def migrate_legacy_home():
    """Při prvním spuštění převezme historii, konfiguraci a data ze starých složek (~/.config/gluesh, ~/.config/plush)."""
    if os.environ.get("LEAPSH_HOME"):
        return None
    new = config_dir()
    if new.exists():
        return None
    base = new.parent
    for name in LEGACY_HOMES:
        old = base / name
        if old.is_dir():
            import shutil
            shutil.copytree(old, new, ignore=shutil.ignore_patterns("__pycache__", "*.tmp", "events.log"))
            return old
    return None
