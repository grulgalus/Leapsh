"""Příkaz `config`: zobrazí konfiguraci a umí ji měnit, kontrolovat, zálohovat a přenášet."""
import json
import os
import re
import sys

from .config import DEFAULTS
from .settings import parse_value

USAGE = """config                              zobrazí config.json
config keys [TEXT]                  známé klíče s typem, výchozí hodnotou a popisem
config get KLÍČ                     hodnota (tečková cesta: termux.auto, aliases.ll)
config set KLÍČ [na|to|=] HODNOTA   změní hodnotu; typ se hlídá, změna platí hned
config toggle KLÍČ                  přepne true/false
config add KLÍČ HODNOTA…            přidá do seznamu (config add disabled pet)
config remove KLÍČ HODNOTA…         odebere ze seznamu
config unset KLÍČ                   smaže klíč      ·  config reset KLÍČ  vrátí výchozí hodnotu
config diff                         co se liší od výchozího stavu
config validate                     zkontroluje typy a hodnoty
config undo                         vrátí poslední změnu (a znovu = vrátí zpět)
config export [SOUBOR|-]            záloha konfigurace i nastavení pluginů do jednoho JSON
config import SOUBOR [--merge]      obnoví ze zálohy (bez --merge nahradí)
config plugins [PLUGIN]             nastavení pluginů (soubory v plugins/config/)
config path  ·  config edit         kde jsou soubory  ·  otevřít v $EDITOR
Klíč plugins.NÁZEV.KLÍČ mění nastavení pluginu. JSON s uvozovkami dej do apostrofů: '["a","b"]'."""

SEP_WORDS = ("na", "to", "=")

# známé klíče: název -> (typ, popis)
KEYS = {
    "theme": ("text", "aktivní téma (theme list)"),
    "aliases": ("objekt", "aliasy: jméno -> příkaz"),
    "disabled": ("seznam", "vypnuté pluginy (plugin enable/disable)"),
    "history_size": ("číslo", "kolik příkazů držet v historii"),
    "history_dedupe": ("bool", "mazat duplicity v historii"),
    "history_file": ("text", "jiná cesta k souboru historie"),
    "termux": ("objekt", "detekce Termuxu (zapisuje shell při startu)"),
    "termux.auto": ("bool", "zjišťovat Termux automaticky při startu"),
    "warn_not_termux": ("bool", "upozornit při startu mimo Termux"),
    "startup_msg": ("bool", "ukázat hlavičku při startu"),
    "tab_cycle": ("bool", "opakovaný Tab prochází nabídku"),
    "lang": ("text", "jazyk (čte ho XAPI)"),
    "permissions": ("objekt", "oprávnění pluginů (plugin perms)"),
}
TYPES = {"bool": bool, "číslo": int, "text": str, "seznam": list, "objekt": dict}


# ---------------------------------------------------------------- pomocné
def colorize(text):
    def line(l):
        l = re.sub(r'^(\s*)"([^"]+)":', lambda m: f'{m.group(1)}\x1b[36m"{m.group(2)}"\x1b[0m:', l)
        l = re.sub(r':\s("(?:[^"\\]|\\.)*")(,?)$', lambda m: f': \x1b[32m{m.group(1)}\x1b[0m{m.group(2)}', l)
        l = re.sub(r':\s(-?\d[\d.]*)(,?)$', lambda m: f': \x1b[33m{m.group(1)}\x1b[0m{m.group(2)}', l)
        l = re.sub(r':\s(true|false|null)(,?)$', lambda m: f': \x1b[35m{m.group(1)}\x1b[0m{m.group(2)}', l)
        l = re.sub(r'^(\s+)("(?:[^"\\]|\\.)*")(,?)$', lambda m: f'{m.group(1)}\x1b[32m{m.group(2)}\x1b[0m{m.group(3)}', l)
        return l
    return "\n".join(line(l) for l in text.splitlines())


def dumps(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def short(value, n=44):
    t = json.dumps(value, ensure_ascii=False)
    return t if len(t) <= n else t[:n - 1] + "…"


def _split(key):
    return [p for p in key.split(".") if p]


def _walk(data, parts):
    cur = data
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return False, None
    return True, cur


def _plugin_target(parts):
    """plugins.NAME.KLÍČ -> (NAME, KLÍČ|None); jinak None."""
    if len(parts) >= 2 and parts[0] in ("plugins", "settings"):
        return parts[1], ".".join(parts[2:]) or None
    return None


def flat_keys(data, prefix=""):
    """Všechny klíče v tečkové notaci (pro doplňování Tabem)."""
    out = []
    for k, v in data.items():
        out.append(prefix + k)
        if isinstance(v, dict) and v and not prefix.startswith("permissions") and k != "permissions":
            out += flat_keys(v, prefix + k + ".")
    return out


def flatten(data, prefix=""):
    """Slovník -> {tečková cesta: hodnota} (listy: skaláry, seznamy, prázdné slovníky)."""
    out = {}
    for k, v in data.items():
        if isinstance(v, dict) and v:
            out.update(flatten(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def _default_for(parts):
    ok, val = _walk(DEFAULTS, parts)
    return val if ok else None


def _known_tops():
    return sorted(set(DEFAULTS) | {k.split(".")[0] for k in KEYS})


def _typo_of(top):
    import difflib
    close = difflib.get_close_matches(top, _known_tops(), n=1, cutoff=0.7)
    return close[0] if close and close[0] != top else None


# ---------------------------------------------------------------- zálohy, znovunačtení
def backup(sh):
    """Před změnou uloží předchozí config.json do config.json.bak (jedna úroveň; slouží `config undo`)."""
    try:
        sh.config.path.parent.mkdir(parents=True, exist_ok=True)
        bak = sh.config.path.with_suffix(".json.bak")
        if sh.config.path.exists():
            bak.write_bytes(sh.config.path.read_bytes())
        else:                                   # první změna v čisté instalaci: zálohuje se aktuální (výchozí) stav
            bak.write_text(dumps(sh.config.data), encoding="utf-8")
    except OSError:
        pass


def reload_all_config(sh, old_data=None):
    """Po obnově/importu: projeví se aliasy, historie, vypnuté pluginy a téma."""
    sh.aliases = dict(sh.config.data.get("aliases", {}))
    sh.load_history()
    sh.plugin_settings.reset_cache()
    if old_data is None or old_data.get("disabled") != sh.config.data.get("disabled"):
        sh.manager.reload_all()
    if old_data is None or old_data.get("theme") != sh.config.data.get("theme"):
        sh.events.emit("theme_change", old=(old_data or {}).get("theme"), new=sh.config.data.get("theme"))
    sh.events.emit("config_change", key="*", old=None, new=None)


def apply_change(sh, key, old, new):
    """Co je potřeba udělat, aby se změna projevila hned (bez restartu)."""
    top = key.split(".")[0]
    if top == "aliases":
        sh.aliases = dict(sh.config.data.get("aliases", {}))
    elif top == "theme":
        sh.events.emit("theme_change", old=old, new=new)
    elif top in ("history_size", "history_file", "history_dedupe"):
        sh.load_history()
    elif top == "disabled":
        sh.manager.reload_all()
    sh.events.emit("config_change", key=key, old=old, new=new)


# ---------------------------------------------------------------- čtení / zápis hodnot
def _read(sh, parts):
    """-> (nalezeno, hodnota). Pro plugins.NÁZEV.KLÍČ bere uživatelskou hodnotu, jinak výchozí z config.json pluginu."""
    pt = _plugin_target(parts)
    if pt:
        name, k = pt
        user = sh.plugin_settings.load(name)
        if k is None:
            return True, user
        dflt = sh.manager.found[name].manifest.get("settings", {}) if name in sh.manager.found else {}
        if k in user:
            return True, user[k]
        return (k in dflt), dflt.get(k)
    return _walk(sh.config.data, parts)


def _validate_known(sh, parts, value):
    """Kontroly známých klíčů; vrací text chyby nebo None."""
    if parts == ["theme"] and value not in sh.themes:
        return f"téma '{value}' neexistuje. Dostupná: {', '.join(sorted(sh.themes))}"
    if parts == ["history_size"] and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        return "history_size musí být kladné celé číslo"
    if parts == ["disabled"] and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        return "disabled musí být seznam názvů pluginů"
    if parts == ["aliases"] and not (isinstance(value, dict) and all(isinstance(v, str) for v in value.values())):
        return "aliases musí být objekt {jméno: příkaz}"
    return None


def _write(sh, key, value, force=False):
    """Zapíše hodnotu klíče (včetně kontrol, zálohy, uložení a okamžitého použití). Vrací návratový kód."""
    parts = _split(key)
    pt = _plugin_target(parts)
    if pt:
        name, k = pt
        if k is None:
            sh.say("použití: config set plugins.NÁZEV.KLÍČ HODNOTA")
            return 2
        sh.plugin_settings.set(name, k, value)
        sh.say(f"{key} = {json.dumps(value, ensure_ascii=False)}")
        return 0
    found, old = _walk(sh.config.data, parts)
    if not found and len(parts) == 1 and not force and parts[0] not in _known_tops():
        sug = _typo_of(parts[0])
        if sug:
            sh.say(f"✗ neznámý klíč '{parts[0]}'. Myslel jsi '{sug}'? (vlastní klíč přidáš s --force)")
            return 1
    err = _validate_known(sh, parts, value)
    if err:
        sh.say(f"✗ {err}")
        return 1
    backup(sh)
    cur = sh.config.data
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value
    sh.config.save()
    sh.say(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    apply_change(sh, key, old, value)
    return 0


def _typed(sh, key, raw):
    """Text z příkazové řádky -> hodnota podle typu stávající (nebo výchozí) hodnoty. (hodnota, chyba)"""
    parts = _split(key)
    found, existing = _read(sh, parts)
    if not found and not _plugin_target(parts):
        existing = _default_for(parts)
    try:
        return parse_value(raw, existing), None
    except ValueError as exc:
        return None, f"✗ {key}: {exc} (nyní {json.dumps(existing, ensure_ascii=False)})"


# ---------------------------------------------------------------- podpříkazy
def _cmd_keys(sh, rest):
    needle = " ".join(rest).lower()
    rows = []
    for key, (typ, desc) in KEYS.items():
        if needle and needle not in key.lower() and needle not in desc.lower():
            continue
        found, cur = _walk(sh.config.data, _split(key))
        dflt = _default_for(_split(key))
        mark = " " if (not found or cur == dflt) else "*"
        shown = cur if found else dflt
        rows.append((mark, key, typ, "—" if shown is None else short(shown, 28), desc))
    if not rows:
        sh.say("nic nenalezeno")
        return 1
    w = max(len(r[1]) for r in rows)
    sh.say(f"  {'klíč':<{w}}  {'typ':<7} {'hodnota':<28} popis      (* = změněno oproti výchozímu)")
    for mark, key, typ, val, desc in rows:
        sh.say(f"{mark} {key:<{w}}  {typ:<7} {val:<28} {desc}")
    return 0


def _cmd_diff(sh):
    cur, dflt = flatten(sh.config.data), flatten(DEFAULTS)
    lines = []
    for k in sorted(set(cur) | set(dflt)):
        if k.startswith("termux.") and k != "termux.auto":
            continue                                                  # zapisuje shell sám
        if k not in dflt:
            lines.append(f"\x1b[32m+ {k} = {short(cur[k], 70)}\x1b[0m")
        elif k not in cur:
            lines.append(f"\x1b[31m- {k}\x1b[0m   (výchozí {short(dflt[k], 50)})")
        elif cur[k] != dflt[k]:
            lines.append(f"\x1b[33m~ {k}: {short(dflt[k], 30)} → {short(cur[k], 40)}\x1b[0m")
    if not lines:
        sh.say("konfigurace odpovídá výchozímu stavu")
    for l in lines:
        sh.say(l if sys.stdout.isatty() else re.sub(r"\x1b\[[0-9;]*m", "", l))
    return 0


def _cmd_validate(sh):
    errs, notes, d = [], [], sh.config.data
    for key, (typ, _) in KEYS.items():
        found, val = _walk(d, _split(key))
        if found and (not isinstance(val, TYPES[typ]) or (typ == "číslo" and isinstance(val, bool))):
            errs.append(f"{key}: čekám {typ}, je {json.dumps(val, ensure_ascii=False)[:40]}")
    for k in d:
        if k not in _known_tops():
            sug = _typo_of(k)
            notes.append(f"vlastní klíč '{k}'" + (f" (překlep? myslel jsi '{sug}')" if sug else ""))
    if d.get("theme") not in sh.themes:
        errs.append(f"theme: téma '{d.get('theme')}' neexistuje (theme list)")
    for n in d.get("disabled", []) if isinstance(d.get("disabled"), list) else []:
        if n not in sh.manager.found:
            notes.append(f"disabled: plugin '{n}' není nainstalovaný")
    if isinstance(d.get("history_size"), int) and d["history_size"] < 1:
        errs.append("history_size: musí být kladné číslo")
    for e in errs:
        sh.say(f"  ✗ {e}")
    for n in notes:
        sh.say(f"  ! {n}")
    for name in sh.plugin_settings.names():
        if name not in sh.manager.found:
            sh.say(f"  ! plugins/config/{name}.json patří pluginu, který není nainstalovaný")
        else:
            dflt = sh.manager.found[name].manifest.get("settings", {})
            for k, v in sh.plugin_settings.load(name).items():
                if k in dflt and type(dflt[k]) is not type(v) and not (isinstance(dflt[k], (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool)):
                    errs.append(f"plugins.{name}.{k}: čekám {type(dflt[k]).__name__}, je {type(v).__name__}")
                    sh.say(f"  ✗ {errs[-1]}")
    if not errs:
        sh.say("✓ konfigurace je v pořádku" + (f" ({len(notes)} poznámek)" if notes else ""))
    return 1 if errs else 0


def _cmd_undo(sh):
    bak = sh.config.path.with_suffix(".json.bak")
    if not bak.exists():
        sh.say("není co vracet (zatím žádná záloha)")
        return 1
    import copy
    old_data = copy.deepcopy(sh.config.data)
    prev = bak.read_bytes()
    try:
        json.loads(prev.decode("utf-8"))
    except ValueError:
        sh.say("záloha je poškozená")
        return 1
    bak.write_bytes(sh.config.path.read_bytes() if sh.config.path.exists() else b"{}")     # undo podruhé = redo
    sh.config.path.write_bytes(prev)
    sh.config.data = copy.deepcopy(DEFAULTS)
    sh.config.load()
    reload_all_config(sh, old_data)
    sh.say("vráceno na předchozí stav (znovu `config undo` = zpět)")
    return 0


def _cmd_export(sh, rest):
    import time
    bundle = {"leapsh": __import__("leapsh").__version__, "config": sh.config.data,
              "plugins": {n: sh.plugin_settings.load(n) for n in sh.plugin_settings.names()}}
    text = dumps(bundle) + "\n"
    target = rest[0] if rest else time.strftime("leapsh-config-%Y%m%d-%H%M%S.json")
    if target == "-":
        sh.say(text.rstrip())
        return 0
    try:
        with open(os.path.expanduser(target), "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        sh.say(f"✗ {exc}")
        return 1
    sh.say(f"✓ uloženo do {target}  ({len(bundle['plugins'])} nastavení pluginů)")
    return 0


def _deep_merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = v
    return a


def _cmd_import(sh, rest):
    import copy
    files = [r for r in rest if not r.startswith("--")]
    if not files:
        sh.say("použití: config import SOUBOR [--merge]")
        return 2
    try:
        with open(os.path.expanduser(files[0]), encoding="utf-8") as f:
            bundle = json.load(f)
    except (OSError, ValueError) as exc:
        sh.say(f"✗ {exc}")
        return 1
    if not isinstance(bundle, dict):
        sh.say("✗ soubor musí obsahovat JSON objekt")
        return 1
    cfg = bundle["config"] if isinstance(bundle.get("config"), dict) else {k: v for k, v in bundle.items() if k not in ("leapsh", "plugins")}
    plugins = bundle.get("plugins", {}) if isinstance(bundle.get("plugins"), dict) else {}
    old_data = copy.deepcopy(sh.config.data)
    backup(sh)
    if "--merge" in rest:
        _deep_merge(sh.config.data, cfg)
    else:
        sh.config.data = _deep_merge(copy.deepcopy(DEFAULTS), cfg)
    err = _validate_known(sh, ["theme"], sh.config.data.get("theme")) if sh.config.data.get("theme") else None
    if err:
        sh.config.data["theme"] = old_data.get("theme", DEFAULTS["theme"])
        sh.say(f"! {err} – téma ponecháno")
    sh.config.save()
    n = 0
    for name, values in plugins.items():
        if isinstance(values, dict):
            for k, v in values.items():
                sh.plugin_settings.set(name, k, v)
                n += 1
    reload_all_config(sh, old_data)
    sh.say(f"✓ importováno ({'sloučeno' if '--merge' in rest else 'nahrazeno'}), {n} hodnot nastavení pluginů; `config undo` to vrátí")
    return 0


def _cmd_list_edit(sh, sub, rest):
    """config add/remove KLÍČ HODNOTA…"""
    if len(rest) < 2:
        sh.say(f"použití: config {sub} KLÍČ HODNOTA…")
        return 2
    key, items = rest[0], rest[1:]
    parts = _split(key)
    found, cur = _read(sh, parts)
    if found and not isinstance(cur, list):
        sh.say(f"✗ {key} není seznam")
        return 1
    new = list(cur) if found else []
    for it in items:
        if sub == "add" and it not in new:
            new.append(it)
        elif sub == "remove":
            if it not in new:
                sh.say(f"! {it} v {key} není")
            else:
                new.remove(it)
    return _write(sh, key, new)


# ---------------------------------------------------------------- vstup
def cmd_config(sh, args):
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    sub = args[0] if args else "show"
    rest = args[1:]
    data = sh.config.data
    if sub in ("-h", "--help", "help"):
        sh.say(USAGE)
        return 0
    if sub in ("show", "list"):
        text = dumps(data)
        sh.say(f"# {sh.config.path}")
        sh.say(colorize(text) if sys.stdout.isatty() else text)
        sh.say(f"# nastavení pluginů: {sh.plugin_settings.dir}  (config plugins)   ·   popisy klíčů: config keys")
        return 0
    if sub == "keys":
        return _cmd_keys(sh, rest)
    if sub == "diff":
        return _cmd_diff(sh)
    if sub == "validate":
        return _cmd_validate(sh)
    if sub == "undo":
        return _cmd_undo(sh)
    if sub == "export":
        return _cmd_export(sh, rest)
    if sub == "import":
        return _cmd_import(sh, rest)
    if sub in ("add", "remove"):
        return _cmd_list_edit(sh, sub, rest)
    if sub == "path":
        sh.say(f"config:            {sh.config.path}")
        sh.say(f"záloha (undo):     {sh.config.path.with_suffix('.json.bak')}")
        sh.say(f"historie:          {sh.history_path}")
        sh.say(f"pluginy:           {sh.config.path.parent / 'plugins'}")
        sh.say(f"nastavení pluginů: {sh.plugin_settings.dir}")
        return 0
    if sub == "plugins":
        names = rest[:1] or sh.plugin_settings.names()
        if not names:
            sh.say("žádné nastavení pluginů zatím není (výchozí hodnoty jsou v config.json pluginů)")
        for n in names:
            sh.say(f"# {sh.plugin_settings.path(n)}")
            sh.say(dumps(sh.plugin_settings.load(n)))
        return 0
    if sub == "edit":
        from ._fast import which
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or next(
            (e for e in ("nano", "vim", "vi") if which(e)), None)
        if not editor:
            sh.say("nastav $EDITOR (nebo nainstaluj nano)")
            return 1
        sh.config.path.parent.mkdir(parents=True, exist_ok=True)
        if not sh.config.path.exists():
            sh.config.save()
        backup(sh)
        import copy
        old_data = copy.deepcopy(sh.config.data)
        rc = sh._spawn(editor.split() + [str(sh.config.path)])
        sh.config.data = copy.deepcopy(DEFAULTS)
        sh.config.load()
        reload_all_config(sh, old_data)
        sh.say("config.json načten znovu (`config validate` ho zkontroluje, `config undo` vrátí změny)")
        return rc

    if sub == "get":
        if not rest:
            sh.say(USAGE)
            return 2
        found, val = _read(sh, _split(rest[0]))
        if not found or (val is None and _plugin_target(_split(rest[0]))):
            sh.say(f"klíč {rest[0]} neexistuje")
            return 1
        sh.say(dumps(val) if isinstance(val, (dict, list)) else json.dumps(val, ensure_ascii=False))
        return 0

    if sub == "toggle":
        if not rest:
            sh.say("použití: config toggle KLÍČ")
            return 2
        found, val = _read(sh, _split(rest[0]))
        if not found or not isinstance(val, bool):
            sh.say(f"✗ {rest[0]} není true/false" if found else f"klíč {rest[0]} neexistuje")
            return 1
        return _write(sh, rest[0], not val)

    if sub in ("set", "unset", "reset"):
        if not rest:
            sh.say(USAGE)
            return 2
        key, value_tokens = rest[0], rest[1:]
        if sub == "set" and "=" in key and not value_tokens:
            key, _, first = key.partition("=")
            value_tokens = [first]
        if sub == "set" and value_tokens and value_tokens[0] in SEP_WORDS:
            value_tokens = value_tokens[1:]
        if sub == "set" and not value_tokens:
            sh.say("chybí hodnota: config set KLÍČ HODNOTA")
            return 2
        parts = _split(key)
        if not parts:
            sh.say("prázdný klíč")
            return 2
        pt = _plugin_target(parts)
        if sub in ("unset", "reset"):
            if pt:
                name, k = pt
                if k is None:
                    sh.say("použití: config unset plugins.NÁZEV.KLÍČ")
                    return 2
                ok = sh.plugin_settings.unset(name, k)
                sh.say("vráceno na výchozí" if ok else "klíč není nastavený")
                return 0 if ok else 1
            found, old = _walk(sh.config.data, parts)
            if sub == "unset":
                if not found:
                    sh.say(f"klíč {key} neexistuje")
                    return 1
                backup(sh)
                _, parent = _walk(sh.config.data, parts[:-1])
                del parent[parts[-1]]
                sh.config.save()
                sh.say(f"{key} smazáno")
                apply_change(sh, key, old, None)
                return 0
            dflt = _default_for(parts)
            if dflt is None:
                sh.say(f"{key} nemá výchozí hodnotu (použij config unset)")
                return 1
            return _write(sh, key, json.loads(json.dumps(dflt)))
        val, err = _typed(sh, key, " ".join(value_tokens))
        if err:
            sh.say(err)
            return 1
        rc = _write(sh, key, val, force)
        if rc == 0 and parts == ["disabled"]:
            sh.say("(pluginy se načítají znovu)")
        return rc

    # `config KLÍČ` = zkratka pro get
    return cmd_config(sh, ["get", sub])
