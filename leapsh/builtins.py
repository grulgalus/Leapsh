"""Vestavěné příkazy shellu."""
import json
import os

from . import __version__
from .config import config_dir, is_termux
from .configcmd import cmd_config
from .events import KNOWN_EVENTS
from .loader import detect_runtime
from .theme import RESET


def register_builtins(sh):
    for name, fn, help in [
        ("help", cmd_help, "nápověda: help [příkaz]"),
        ("exit", cmd_exit, "ukončí shell: exit [kód]"),
        ("quit", cmd_exit, "ukončí shell"),
        ("q", cmd_exit, "ukončí shell"),
        ("alias", cmd_alias, "aliasy: alias [jméno=hodnota]"),
        ("unalias", cmd_unalias, "smaže alias: unalias jméno"),
        ("history", cmd_history, "historie: history [N|all] | -s TEXT | -d Č | -c | --path;  !! !$ !N !text"),
        ("reload", cmd_reload, "znovu načte konfiguraci a všechny pluginy"),
        ("plugin", cmd_plugin, "správa pluginů: plugin list|info|enable|disable|set|create|compile|install|reload"),
        ("addon", cmd_addon, "správa addonů: addon list|create NÁZEV PLUGIN"),
        ("theme", cmd_theme, "témata: theme list|set|preview|new"),
        ("events", cmd_events, "seznam událostí, na které se dají věšet pluginy"),
        ("config", cmd_config, "config [get|set|unset|reset|path|plugins|edit] – zobrazí/změní konfiguraci"),
        ("doctor", cmd_doctor, "diagnostika: prostředí, Termux/API, historie, pluginy"),
        ("leapsh", cmd_leapsh, "informace o shellu"),
    ]:
        sh.add_command(name, fn, help, owner="core")


def cmd_help(sh, args):
    if args:
        c = sh.commands.get(args[0])
        if not c:
            sh.say(f"help: neznámý příkaz {args[0]}")
            return 1
        sh.say(f"{args[0]} – {c.help or 'bez popisu'}  [{c.owner}]")
        return 0
    sh.say(f"leapsh {__version__} – vestavěné příkazy a příkazy z pluginů:\n")
    for name, c in sorted(sh.commands.items(), key=lambda kv: (kv[1].owner != "core", kv[1].owner, kv[0])):
        owner = "" if c.owner == "core" else f"  [{c.owner}]"
        sh.say(f"  {name:<12} {c.help}{owner}")
    sh.say("\nOstatní příkazy se spouštějí přes bash/sh (rouru, &&, přesměrování apod. zvládne ten).")
    return 0


def cmd_exit(sh, args):
    sh.running = False
    try:
        sh.exit_code = int(args[0]) if args else 0
    except ValueError:
        sh.exit_code = 2
    return sh.exit_code


def cmd_alias(sh, args):
    if not args:
        for k, v in sorted(sh.aliases.items()):
            sh.say(f"alias {k}='{v}'")
        return 0
    text = " ".join(args)
    if "=" not in text:
        v = sh.aliases.get(text)
        sh.say(f"alias {text}='{v}'" if v else f"alias: {text}: nenalezen")
        return 0 if v else 1
    name, val = text.split("=", 1)
    sh.aliases[name.strip()] = val.strip()
    sh.config.data["aliases"] = dict(sh.aliases)
    sh.config.save()
    return 0


def cmd_unalias(sh, args):
    rc = 0
    for a in args:
        if a in sh.aliases:
            del sh.aliases[a]
        else:
            sh.say(f"unalias: {a}: nenalezen")
            rc = 1
    sh.config.data["aliases"] = dict(sh.aliases)
    sh.config.save()
    return rc


def cmd_history(sh, args):
    """history [N | all] · history -s TEXT · history -d ČÍSLO · history -c · history --path"""
    if args and args[0] in ("-c", "--clear"):
        sh.history_clear()
        sh.say("historie smazána")
        return 0
    if args and args[0] in ("-p", "--path"):
        sh.say(f"{sh.history_path}  ({len(sh.history)} příkazů)")
        return 0
    if args and args[0] == "-d" and len(args) > 1 and args[1].isdigit():
        ok = sh.history_delete(int(args[1]))
        sh.say("smazáno" if ok else "takové číslo v historii není")
        return 0 if ok else 1
    if args and args[0] in ("-s", "--search") and len(args) > 1:
        needle = " ".join(args[1:]).lower()
        hits = [(i, l) for i, l in enumerate(sh.history, 1) if needle in l.lower()]
        for i, l in hits[-50:]:
            sh.say(f"{i:5}  {l}")
        return 0 if hits else 1
    n = len(sh.history) if args and args[0] == "all" else int(args[0]) if args and args[0].isdigit() else 20
    start = max(0, len(sh.history) - n)
    for i, l in enumerate(sh.history[start:], start + 1):
        sh.say(f"{i:5}  {l}")
    return 0


def cmd_reload(sh, args):
    sh.config.load()
    sh.aliases = dict(sh.config.data.get("aliases", {}))
    sh.plugin_settings.reset_cache()
    sh.plugin_settings.migrate_legacy(sh.config)
    sh.manager.reload_all()
    n = len(sh.manager.loaded) + len(sh.manager.addons)
    sh.say(f"načteno: {n} (pluginy/témata/addony)")
    return 0


def cmd_leapsh(sh, args):
    m = sh.manager
    sh.say(f"leapsh {__version__}  •  {'Termux' if is_termux() else 'Linux'}  •  "
           f"pluginy: {len(m.loaded)}, addony: {len(m.addons)}  •  téma: {sh.config.data.get('theme')}")
    sh.say(f"konfigurace: {sh.config.path}")
    sh.say(f"uživatelské pluginy: {config_dir() / 'plugins'}")
    sh.say(f"uživatelské addony:  {config_dir() / 'addons'}")
    return 0


# ---------------- plugin ----------------
def _status_line(sh, name, e, indent=""):
    st = sh.manager.status.get(name, "?")
    mark = "✓" if st == "loaded" else "✗" if st.startswith(("error", "disabled")) else "·"
    ver = e.manifest.get("version", "")
    desc = e.manifest.get("description", "")
    extra = "" if st == "loaded" else f"  ({st})"
    kind = e.kind if e.kind != "plugin" else ("wasm" if detect_runtime(e.path, e.manifest) == "wasm" else "py")
    sh.say(f"{indent}{mark} {name:<20} {ver:<7} {kind:<6} {desc}{extra}")


def cmd_plugin(sh, args):
    m = sh.manager
    sub = args[0] if args else "list"
    rest = args[1:]
    if sub == "list":
        m.discover() if not m.found else None
        mains = {n: e for n, e in sorted(m.found.items()) if e.kind != "addon"}
        addons = [e for e in m.found.values() if e.kind == "addon"]
        for n, e in mains.items():
            _status_line(sh, n, e)
            for a in sorted(addons, key=lambda x: x.name):
                if a.manifest.get("extends") == n:
                    _status_line(sh, a.name, a, "   └ ")
        for a in addons:
            if a.manifest.get("extends") not in mains:
                _status_line(sh, a.name, a)
        return 0
    if sub == "info" and rest:
        e = m.found.get(rest[0])
        if not e:
            sh.say(f"plugin: {rest[0]} nenalezen")
            return 1
        inst = m.loaded.get(rest[0]) or m.addons.get(rest[0])
        sh.say(f"{e.name} {e.manifest.get('version', '')}  [{e.kind}]")
        sh.say(f"  popis:   {e.manifest.get('description', '')}")
        sh.say(f"  cesta:   {e.path}")
        sh.say(f"  stav:    {m.status.get(e.name, '?')}")
        for key in ("requires", "extends", "platforms"):
            if e.manifest.get(key):
                sh.say(f"  {key}: {e.manifest[key]}")
        if inst:
            if getattr(inst, "provides", None):
                sh.say(f"  extension pointy: {', '.join(inst.provides)}")
            cmds = [k for k, v in sh.commands.items() if v.owner == e.name]
            segs = [k for k, v in sh.segments.items() if v[1] == e.name]
            if cmds:
                sh.say(f"  příkazy:  {', '.join(cmds)}")
            if segs:
                sh.say(f"  segmenty: {', '.join('{' + s + '}' for s in segs)}")
            evs = sh.events.owned_by(e.name)
            if evs:
                sh.say(f"  události: {', '.join(evs)}")
            if e.kind != "addon":
                ads = [a.name for a in m.addons_of(e.name)]
                if ads:
                    sh.say(f"  addony:   {', '.join(ads)}")
        stg = dict(e.manifest.get("settings", {}))
        stg.update(sh.plugin_settings.load(e.name))
        if stg:
            sh.say(f"  nastavení: {json.dumps(stg, ensure_ascii=False)}")
            sh.say(f"             ({sh.plugin_settings.path(e.name)})")
        return 0
    if sub in ("enable", "disable") and rest:
        if rest[0] not in m.found:
            sh.say(f"plugin: {rest[0]} nenalezen")
            return 1
        if sub == "enable":
            ok = m.enable(rest[0])
            sh.say(("zapnuto: " if ok else "nepodařilo se zapnout: ") + f"{rest[0]} ({m.status.get(rest[0])})")
            return 0 if ok else 1
        m.disable(rest[0])
        sh.say(f"vypnuto: {rest[0]}")
        return 0
    if sub in ("set", "unset", "settings") and rest:
        from .settings import parse_value
        name = rest[0]
        if name not in m.found:
            sh.say(f"plugin: {name} nenalezen")
            return 1
        inst = m.loaded.get(name) or m.addons.get(name)
        defaults = m.found[name].manifest.get("settings", {})
        if sub == "settings" or len(rest) == 1:
            cur = dict(defaults)
            cur.update(sh.plugin_settings.load(name))
            sh.say(f"{sh.plugin_settings.path(name)}" + ("" if sh.plugin_settings.path(name).exists() else "  (zatím neexistuje, platí výchozí)"))
            for k, v in sorted(cur.items()):
                mark = "*" if k in sh.plugin_settings.load(name) else " "
                info = m.found[name].manifest.get("settings_info", {}).get(k, "")
                sh.say(f" {mark} {k} = {json.dumps(v, ensure_ascii=False)}" + (f"   # {info}" if info else ""))
            return 0
        if sub == "unset":
            ok = sh.plugin_settings.unset(name, rest[1])
            sh.say("vráceno na výchozí" if ok else "klíč není nastavený")
            return 0 if ok else 1
        if len(rest) < 3:
            sh.say("použití: plugin set NÁZEV KLÍČ HODNOTA")
            return 2
        key, raw = rest[1], " ".join(rest[2:])
        existing = sh.plugin_settings.load(name).get(key, defaults.get(key))
        try:
            val = parse_value(raw, existing)
        except ValueError as exc:
            sh.say(f"✗ {name}.{key}: {exc} (nyní {json.dumps(existing, ensure_ascii=False)})")
            return 1
        sh.plugin_settings.set(name, key, val)
        sh.say(f"{name}.{key} = {json.dumps(val, ensure_ascii=False)}")
        return 0
    if sub == "reload":
        if rest:
            ok = m.reload(rest[0])
            sh.say(f"{rest[0]}: " + ("znovu načten" if ok else m.status.get(rest[0], "nenalezen")))
            return 0 if ok else 1
        return cmd_reload(sh, [])
    if sub == "perms":
        perms = sh.config.data.get("permissions", {})
        names = [rest[0]] if rest else sorted(perms)
        if not any(perms.get(n) for n in names):
            sh.say("žádná udělená ani zamítnutá oprávnění")
        for n in names:
            for p, ok in sorted(perms.get(n, {}).items()):
                sh.say(f"  {'✓' if ok else '✗'} {n:<22} {p}")
        return 0
    if sub == "revoke" and rest:
        perms = sh.config.data.setdefault("permissions", {})
        if len(rest) > 1:
            perms.get(rest[0], {}).pop(rest[1], None)
        else:
            perms.pop(rest[0], None)
        sh.config.save()
        sh.say("oprávnění smazána – plugin se zeptá znovu")
        return 0
    if sub in ("new", "create") and rest:
        kind = "theme" if "--theme" in rest else "wasm-c" if "--c" in rest else "wasm-wat" if "--wasm" in rest else "plugin"
        name = [r for r in rest if not r.startswith("--")][0]
        rc = _new(sh, kind, name, None)
        return rc
    if sub == "compile":
        from .devtools import compile_plugin
        target = rest[0] if rest else "."
        ok, pkg = compile_plugin(target, pack="--no-pack" not in rest, log=sh.say)
        return 0 if ok else 1
    if sub == "install" and rest:
        from .devtools import install_package
        try:
            dest = install_package(rest[0], force="--force" in rest)
        except (ValueError, OSError) as exc:
            sh.say(f"✗ {exc}")
            return 1
        sh.manager.discover()
        sh.say(f"✓ nainstalováno: {dest}  (načti: reload)")
        return 0
    sh.say("použití: plugin list | info N | enable N | disable N | set N KLÍČ HODNOTA | unset N KLÍČ | settings N | create N [--theme|--wasm|--c] | compile CESTA | install BALÍČEK | reload | perms | revoke")
    return 2


def _new(sh, kind, name, target):
    from .scaffold import scaffold
    try:
        dest = scaffold(kind, name, target)
    except Exception as exc:
        sh.say(f"nelze vytvořit: {exc}")
        return 1
    if kind == "wasm-wat":                       # WASM plugin ve WAT se rovnou sestaví do plugin.wasm
        from .devtools import compile_plugin
        compile_plugin(dest, pack=False, log=lambda text: None)
    sh.manager.discover()
    ok = sh.manager.load(name)
    sh.say(f"vytvořeno: {dest}  ({'načteno' if ok else sh.manager.status.get(name)})")
    sh.say("uprav soubory a spusť 'reload'")
    return 0


# ---------------- addon ----------------
def cmd_addon(sh, args):
    sub = args[0] if args else "list"
    if sub == "list":
        m = sh.manager
        found = [e for e in m.found.values() if e.kind == "addon"]
        if not found:
            sh.say("žádné addony")
        for e in sorted(found, key=lambda x: x.name):
            _status_line(sh, e.name, e)
            sh.say(f"      rozšiřuje: {e.manifest.get('extends')}")
        return 0
    if sub in ("new", "create") and len(args) >= 3:
        return _new(sh, "addon", args[1], args[2])
    sh.say("použití: addon list | addon create NÁZEV CÍLOVÝ_PLUGIN")
    return 2


# ---------------- theme ----------------
def cmd_theme(sh, args):
    sub = args[0] if args else "list"
    cur = sh.config.data.get("theme")
    if sub == "list":
        for n in sorted(sh.themes):
            sh.say(f"{'*' if n == cur else ' '} {n}")
        return 0
    if sub == "set" and len(args) > 1:
        if not sh.set_theme(args[1]):
            sh.say(f"téma {args[1]} neexistuje (theme list)")
            return 1
        return 0
    if sub == "preview":
        names = args[1:] or sorted(sh.themes)
        ctx = sh.prompt_context()
        for n in names:
            t = sh.themes.get(n)
            if not t:
                continue
            sh.say(f"── {n}")
            sh.say(sh.render_template(t.data.get("prompt", ""), ctx, t) + RESET)
            if t.data.get("rprompt"):
                sh.say("   (vpravo) " + sh.render_template(t.data["rprompt"], ctx, t) + RESET)
        return 0
    if sub == "new" and len(args) > 1:
        return _new(sh, "theme", "theme_" + args[1].removeprefix("theme_"), None)
    sh.say("použití: theme list | set NÁZEV | preview [NÁZEV...] | new NÁZEV")
    return 2


# ---------------- events ----------------
def cmd_events(sh, args):
    for name, desc in KNOWN_EVENTS.items():
        n = sh.events.count(name)
        sh.say(f"{name:<18} {n:>2} handlerů  {desc}")
    return 0


# ---------------- doctor ----------------
def cmd_doctor(sh, args):
    import platform
    import shutil
    import stat
    import sys
    ok, warn = "\x1b[32m✓\x1b[0m", "\x1b[33m!\x1b[0m"
    t = sh.config.data.get("termux", {})
    rows = [(ok, f"leapsh {__version__}, Python {platform.python_version()} ({platform.python_implementation()}), "
                 f"{platform.system()} {platform.machine()}")]
    if t.get("available"):
        rows.append((ok, "Termux: ano"))
        rows.append((ok if t.get("api") else warn, "Termux:API balíček: " + ("je" if t.get("api") else
                     "chybí (pkg install termux-api)")))
        if t.get("api"):
            rows.append((ok if t.get("api_working") else warn, "Termux:API aplikace: " +
                         ("odpovídá" if t.get("api_working") else "neodpovídá / ještě neověřeno (spusť aplikaci Termux:API)")))
    else:
        rows.append((warn, "Termux: ne – funkce jen pro Termux (baterie, vibrace, notifikace) nejsou dostupné"))
    cfg = sh.config.path
    rows.append((ok if cfg.exists() else warn, f"konfigurace: {cfg}" + ("" if cfg.exists() else " (zatím neexistuje)")))
    hp = sh.history_path
    try:
        mode = stat.S_IMODE(hp.stat().st_mode)
        rows.append((ok if mode == 0o600 else warn, f"historie: {hp}, {len(sh.history)} příkazů, práva {mode:o}"))
    except OSError:
        rows.append((ok, f"historie: {hp}, zatím prázdná"))
    term = os.environ.get("TERM", "?")
    tc = os.environ.get("COLORTERM", "") in ("truecolor", "24bit")
    rows.append((ok if tc else warn, f"terminál: TERM={term}, truecolor: {'ano' if tc else 'ne (některá témata budou mít jiné barvy)'}"))
    cur = sh.config.data.get("theme")
    rows.append((ok if cur in sh.themes else warn, f"téma: {cur}" + ("" if cur in sh.themes else " (neexistuje – theme list)")))
    m = sh.manager
    bad = {n: s for n, s in m.status.items() if s.startswith("error")}
    rows.append((ok if not bad else warn, f"pluginy: {len(m.loaded)}, addony: {len(m.addons)}, chyby: {len(bad)}"))
    for n, s in bad.items():
        rows.append((warn, f"   {n}: {s}"))
    tools = [("git", "git_prompt"), ("curl", "příkaz ai"), ("clang", "WASM pluginy v C (volitelné)")]
    for tool, why in tools:
        rows.append((ok if shutil.which(tool) else warn, f"{tool}: {'je' if shutil.which(tool) else 'chybí'} ({why})"))
    if getattr(sh, "startup_ms", None):
        rows.append((ok, f"start shellu: {sh.startup_ms:.0f} ms"))
    for mark, text in rows:
        sh.say(f" {mark} {text}")
    return 0
