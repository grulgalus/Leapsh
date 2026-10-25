"""Doplňování Tabem jako plugin.

Jak to funguje: editor při Tabu vyvolá událost `complete` s výchozími kandidáty (příkazy / soubory). Tento plugin podle kontextu
(jaký je příkaz a kolikátý argument se píše) kandidáty nahradí. Zdroje, v tomto pořadí:
  1. poskytovatelé (provider) pro konkrétní příkaz: vestavěné níže + addony přes extension point `tab_providers`;
  2. deklarativní specifikace: klíč "completions" v config.json libovolného pluginu a "specs" v nastavení tohoto pluginu.
Poskytovatel je funkce provider(ctx) -> seznam | None  (None = nech výchozí doplňování souborů).
"""
import os
import re
from types import SimpleNamespace

from leapsh.api import Plugin

SHELL_SUBS = {
    "plugin": ["list", "info", "enable", "disable", "set", "unset", "settings", "create", "compile", "install",
               "reload", "perms", "revoke"],
    "addon": ["list", "create"],
    "theme": ["list", "set", "preview", "new"],
    "history": ["-c", "-s", "-d", "--path", "all"],
    "config": ["get", "set", "unset", "reset", "toggle", "add", "remove", "keys", "diff", "validate", "undo", "export",
               "import", "path", "plugins", "edit"],
}
PLUGIN_NAME_ARG = {"info", "enable", "disable", "set", "unset", "settings", "revoke", "perms"}
GIT_SUBS = ["status", "add", "commit", "push", "pull", "checkout", "switch", "branch", "log", "diff", "merge", "rebase",
            "stash", "clone", "fetch", "reset", "tag", "remote", "show", "init", "restore", "rm", "mv", "cherry-pick",
            "bisect", "blame", "clean", "config", "describe", "grep", "revert", "submodule", "worktree"]
GIT_REF_SUBS = {"checkout", "switch", "branch", "merge", "rebase", "diff", "log", "show", "cherry-pick", "reset",
                "revert", "describe", "blame", "tag"}
PKG_SUBS = ["install", "update", "upgrade", "search", "show", "list-installed", "list-all", "uninstall", "reinstall",
            "files", "autoclean", "clean", "edit-sources", "remove"]
APT_SUBS = ["install", "update", "upgrade", "full-upgrade", "remove", "purge", "autoremove", "search", "show", "list",
            "edit-sources", "download", "clean"]
WRAPPERS = {"sudo", "doas", "time", "env", "nohup", "command", "exec", "xargs", "nice", "watch", "tsu"}


def segment_words(left):
    """Slova aktuálního jednoduchého příkazu před rozepsaným slovem (po posledním | ; &&)."""
    seg = re.split(r"\|\||&&|[|;&]", left)[-1].lstrip()
    parts = seg.split()
    return parts if (not seg or seg[-1].isspace()) else parts[:-1]


def find_git_dir(start):
    d = start
    while True:
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return g
        if os.path.isfile(g):
            try:
                with open(g, encoding="utf-8") as f:
                    t = f.read().strip()
                if t.startswith("gitdir:"):
                    p = t[7:].strip()
                    return p if os.path.isabs(p) else os.path.join(d, p)
            except OSError:
                pass
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def git_refs(gd, kinds=("heads", "tags", "remotes")):
    """Větve, tagy a vzdálené větve z .git (čtením souborů, bez volání gitu)."""
    out = set()
    common = gd
    try:
        with open(os.path.join(gd, "commondir"), encoding="utf-8") as f:     # worktree
            common = os.path.normpath(os.path.join(gd, f.read().strip()))
    except OSError:
        pass
    for kind in kinds:
        base = os.path.join(common, "refs", kind)
        for root, _, files in os.walk(base):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), base).replace(os.sep, "/")
                if kind == "remotes":
                    rel = rel.split("/", 1)[1] if "/" in rel else rel
                    if rel == "HEAD":
                        continue
                out.add(rel)
    try:
        with open(os.path.join(common, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(("#", "^")) or " " not in line:
                    continue
                ref = line.split(" ", 1)[1].strip()
                for kind in kinds:
                    if ref.startswith(f"refs/{kind}/"):
                        name = ref[len(f"refs/{kind}/"):]
                        out.add(name.split("/", 1)[1] if kind == "remotes" and "/" in name else name)
    except OSError:
        pass
    return sorted(out)


def git_remotes(gd):
    try:
        with open(os.path.join(gd, "config"), encoding="utf-8") as f:
            return re.findall(r'^\[remote "([^"]+)"\]', f.read(), re.M)
    except OSError:
        return []


def ssh_hosts():
    hosts, home = set(), os.path.expanduser("~/.ssh")
    try:
        with open(os.path.join(home, "config"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"\s*Host\s+(.+)", line, re.I)
                if m:
                    hosts.update(h for h in m.group(1).split() if not re.search(r"[*?!]", h))
    except OSError:
        pass
    try:
        with open(os.path.join(home, "known_hosts"), encoding="utf-8", errors="replace") as f:
            for line in f:
                first = line.split(" ", 1)[0]
                if first.startswith(("|", "#", "@")) or not first:
                    continue
                for h in first.split(","):
                    h = re.sub(r"^\[|\]:\d+$|\]$", "", h)
                    if h:
                        hosts.add(h)
    except OSError:
        pass
    return sorted(hosts)


def package_names():
    """Názvy balíčků z apt seznamů (Termux: $PREFIX/var/lib/apt/lists; Debian: /var/lib/apt/lists). Jen nekomprimované."""
    names, dirs = set(), [os.path.join(os.environ.get("PREFIX", ""), "var/lib/apt/lists"), "/var/lib/apt/lists"]
    for d in dirs:
        try:
            files = [f for f in os.listdir(d) if f.endswith("Packages")]
        except OSError:
            continue
        for fn in files:
            try:
                with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("Package: "):
                            names.add(line[9:].strip())
            except OSError:
                pass
        if names:
            break
    return sorted(names)


class Tabcomplete(Plugin):
    # extension point: tab_providers(dict příkaz -> provider(ctx)) – addon přidá/změní poskytovatele
    provides = ["tab_providers"]

    def on_load(self):
        self._pkgs = None
        self.builtin = {
            "plugin": self.p_plugin, "addon": self.p_addon, "theme": self.p_theme, "history": self.p_static("history"),
            "config": self.p_config, "help": self.p_help, "unalias": self.p_unalias, "git": self.p_git,
            "pkg": self.p_pkg, "apt": self.p_pkg, "apt-get": self.p_pkg, "ssh": self.p_ssh, "scp": self.p_ssh,
            "sftp": self.p_ssh, "mosh": self.p_ssh, "export": self.p_env, "unset": self.p_env, "printenv": self.p_env,
        }
        self.on("complete", self.complete, priority=100)
        self.add_command("tabcomplete", self.cmd, "tabcomplete 'git ch' – ukáže, co by Tab nabídl (ladění doplňování)")

    # ---------- hlavní obsluha události ----------
    def complete(self, ev):
        ic = bool(self.setting("ignore_case", False))
        ev.data["ignore_case"] = ic
        found = self.candidates(ev.word, ev.left, ev.first, ev.data.get("editor"), ev.data.get("dirs_only", False),
                                list(ev.data["candidates"]))
        if found is not None:
            ev.data["candidates"][:] = found

    def candidates(self, word, left, first, editor=None, dirs_only=False, current=None):
        """Vrátí nový seznam kandidátů, nebo None (= nech výchozí)."""
        ic = bool(self.setting("ignore_case", False))
        low = word.lower() if ic else word

        def match(items):
            return [i for i in items if (i.lower() if ic else i).startswith(low)]
        if word.startswith("$") and not word.startswith("$("):
            return match(["$" + k for k in os.environ])
        words = segment_words(left)
        while words and words[0] in WRAPPERS and len(words) >= 1:
            words = words[1:]
            first = not words
        if first or not words:
            if ic and word and editor is not None and "/" not in word:
                return sorted(set(current or []) | set(editor._command_candidates(word, True)))
            return None
        cmd = os.path.basename(words[0])
        ctx = SimpleNamespace(words=words, n=len(words), word=word, cmd=cmd, shell=self.shell, plugin=self,
                              cwd=os.getcwd())
        providers = self.run_extensions("tab_providers", dict(self.builtin))
        cands = None
        if not word.startswith("-") or cmd in ("git", "plugin"):
            fn = providers.get(cmd)
            if fn:
                cands = fn(ctx)
        if cands is None:
            cands = self.spec_candidates(cmd, ctx)
        if cands is not None:
            found = match(cands)
            if found:
                return found
        if ic and editor is not None:                               # bez shody: aspoň soubory bez ohledu na velikost
            files = editor._file_candidates(word, dirs_only, True)
            if files:
                return sorted(set(current or []) | set(files))
        return None

    # ---------- deklarativní specifikace ----------
    def all_specs(self):
        specs = []
        m = self.shell.manager
        for inst in list(m.loaded.values()) + list(m.addons.values()):
            s = inst.manifest.get("completions")
            if isinstance(s, dict):
                specs.append(s)
        user = self.setting("specs", {})
        if isinstance(user, dict):
            specs.append(user)
        return specs

    def spec_candidates(self, cmd, ctx):
        spec = None
        for s in self.all_specs():
            if cmd in s:
                spec = s[cmd]
        if spec is None:
            return None
        if isinstance(spec, list):
            return spec
        if isinstance(spec, dict):
            if ctx.words[-1] in spec and ctx.n > 1:                 # za přepínačem: jeho hodnoty
                return spec[ctx.words[-1]]
            return spec.get(str(ctx.n), spec.get("*"))
        return None

    # ---------- poskytovatelé ----------
    def p_static(self, name):
        return lambda ctx: SHELL_SUBS[name] if ctx.n == 1 else None

    def p_plugin(self, ctx):
        if ctx.n == 1:
            return SHELL_SUBS["plugin"]
        sub = ctx.words[1]
        found = self.shell.manager.found
        if ctx.n == 2 and sub in PLUGIN_NAME_ARG:
            return sorted(found)
        if ctx.n == 3 and sub in ("set", "unset"):                   # klíče nastavení pluginu
            return sorted(found[ctx.words[2]].manifest.get("settings", {})) if ctx.words[2] in found else None
        if ctx.n == 4 and sub == "set" and ctx.words[2] in found:    # hodnoty bool nastavení
            dflt = found[ctx.words[2]].manifest.get("settings", {}).get(ctx.words[3])
            return ["true", "false"] if isinstance(dflt, bool) else None
        if ctx.n == 2 and sub in ("create", "new"):
            return ["--wasm", "--c", "--theme"] if ctx.word.startswith("-") else None
        return None

    def p_addon(self, ctx):
        if ctx.n == 1:
            return SHELL_SUBS["addon"]
        if ctx.n == 3 and ctx.words[1] in ("create", "new"):
            return sorted(self.shell.manager.found)
        return None

    def p_theme(self, ctx):
        if ctx.n == 1:
            return SHELL_SUBS["theme"]
        if ctx.words[1] in ("set", "preview"):
            return sorted(self.shell.themes)
        return None

    def p_help(self, ctx):
        return sorted(self.shell.commands) if ctx.n == 1 else None

    def p_unalias(self, ctx):
        return sorted(self.shell.aliases)

    def p_config(self, ctx):
        from leapsh.configcmd import _read, flat_keys
        sh = self.shell
        if ctx.n == 1:
            return SHELL_SUBS["config"]
        sub = ctx.words[1]
        keys = flat_keys(sh.config.data)
        for name, e in sh.manager.found.items():
            keys += [f"plugins.{name}.{k}" for k in e.manifest.get("settings", {})]
        if ctx.n == 2 and sub in ("get", "set", "unset", "reset", "toggle", "add", "remove"):
            if sub in ("toggle", "add", "remove"):                      # jen klíče vhodného typu
                want = bool if sub == "toggle" else list
                ok = []
                for k in set(keys):
                    f, v = _read(sh, k.split("."))
                    if f and isinstance(v, want):
                        ok.append(k)
                return sorted(ok)
            return sorted(set(keys))
        if ctx.n >= 3 and sub in ("add", "remove") and ctx.words[2] == "disabled":
            return sorted(sh.manager.found)
        if ctx.n == 2 and sub in ("export", "import"):
            return None
        if ctx.n == 2 and sub == "plugins":
            return sorted(sh.manager.found)
        if sub == "set" and ctx.n >= 3:
            if ctx.words[ctx.n - 1] in ("na", "to", "="):
                key = ctx.words[2]
            else:
                key = ctx.words[2]
            if ctx.n not in (3, 4):
                return None
            if key == "theme":
                return sorted(sh.themes)
            parts = key.split(".")
            if parts[0] == "plugins" and len(parts) == 3 and parts[1] in sh.manager.found:
                cur = sh.plugin_settings.load(parts[1]).get(parts[2], sh.manager.found[parts[1]].manifest.get("settings", {}).get(parts[2]))
            else:
                cur = sh.config.data
                for p in parts:
                    cur = cur.get(p) if isinstance(cur, dict) else None
            if isinstance(cur, bool):
                return ["true", "false"]
        return None

    def p_git(self, ctx):
        if ctx.n == 1:
            return GIT_SUBS
        sub = ctx.words[1]
        gd = find_git_dir(ctx.cwd)
        if not gd:
            return None
        if sub in GIT_REF_SUBS:
            return git_refs(gd)
        if sub in ("push", "pull", "fetch"):
            if ctx.n == 2:
                return sorted(git_remotes(gd))
            return git_refs(gd, ("heads",))
        if sub == "remote" and ctx.n == 2:
            return ["add", "remove", "rename", "show", "set-url", "-v", "prune"]
        return None

    def p_pkg(self, ctx):
        subs = APT_SUBS if ctx.cmd != "pkg" else PKG_SUBS
        if ctx.n == 1:
            return subs
        if ctx.words[1] in ("install", "show", "reinstall", "remove", "uninstall", "files") and len(ctx.word) >= 2:
            if self._pkgs is None:
                self._pkgs = package_names()
            return [p for p in self._pkgs if p.startswith(ctx.word)][:300] or None
        return None

    def p_ssh(self, ctx):
        if ":" in ctx.word:
            return None
        hosts = ssh_hosts()
        if "@" in ctx.word:
            user = ctx.word.split("@", 1)[0]
            return [f"{user}@{h}" for h in hosts]
        return hosts or None

    def p_env(self, ctx):
        return sorted(os.environ)

    # ---------- příkaz pro ladění ----------
    def cmd(self, shell, args):
        text = " ".join(args)
        if not text:
            shell.say("použití: tabcomplete 'git ch'   (doplní poslední slovo)")
            return 2
        m = re.search(r"[^\s|;&<>]*$", text)
        word, start = m.group(0), m.start()
        before = text[:start].rstrip()
        first = before == "" or before.endswith(("|", ";", "&&", "||", "&", "("))
        found = self.candidates(word, text, first)
        if found is None:
            shell.say("(výchozí doplňování: příkazy a soubory)")
            return 0
        for c in found[:60]:
            shell.say(c)
        if len(found) > 60:
            shell.say(f"… a dalších {len(found) - 60}")
        return 0
