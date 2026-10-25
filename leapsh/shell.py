"""Jádro shellu: příkazy, prompt, spouštění, historie."""
import os
import re
import signal
import sys
import time
from collections import namedtuple
from pathlib import Path

from ._fast import hostname, which
from .config import APP_DIR, Config, config_dir, is_termux
from .events import EventBus
from .loader import PluginManager
from .settings import PluginSettings
from .theme import RESET, render, style_code

Command = namedtuple("Command", "fn help owner")
ThemeDef = namedtuple("ThemeDef", "name data owner")

DEFAULT_PROMPT = "{green}{user}@{host}{reset}:{blue}{cwd}{reset}{symbol} "


class Shell:
    def __init__(self, config=None):
        self.config = config or Config()
        self.events = EventBus(on_error=self.report_error)
        self.commands = {}
        self.segments = {}
        self.themes = {}
        self.aliases = dict(self.config.data.get("aliases", {}))
        self.history = []
        self.last_rc = 0
        self.last_duration = 0.0
        self.running = True
        self.exit_code = 0
        self.editor = None
        self.manager = PluginManager(self)
        self.plugin_settings = PluginSettings(self)
        self.plugin_settings.migrate_legacy(self.config)
        self._seen_errors = set()
        self._err_count = {}
        self._exe_cache = None
        self.load_history()
        from .builtins import register_builtins
        register_builtins(self)

    # ---------- výstup ----------
    def say(self, text=""):
        print(text, flush=True)

    def warn(self, text):
        print(f"\x1b[2m[leapsh] {text}\x1b[0m", file=sys.stderr, flush=True)

    def report_error(self, owner, where, exc):
        if isinstance(exc, BrokenPipeError):  # např. `příkaz | head` – to není chyba pluginu
            return
        if where.startswith("event:") and owner not in ("core", "?"):
            n = self._err_count[owner] = self._err_count.get(owner, 0) + 1
            if n == 50:                      # pojistka: plugin, který pořád padá, přestane dostávat události
                self.events.off(owner=owner)
                self.manager.status[owner] = "error: vypnuto po 50 chybách v událostech"
                self.warn(f"plugin '{owner}' padá pořád dokola – jeho události jsou vypnuté (plugin reload {owner})")
        key = (owner, where, type(exc).__name__)
        if os.environ.get("LEAPSH_DEBUG"):
            import traceback
            traceback.print_exception(exc)
        elif key not in self._seen_errors:
            self.warn(f"chyba v '{owner}' ({where}): {exc}")
        self._seen_errors.add(key)

    # ---------- registry ----------
    def add_command(self, name, fn, help="", owner="core"):
        self.commands[name] = Command(fn, help, owner)

    def add_segment(self, name, fn, owner="core"):
        self.segments[name] = (fn, owner)

    def add_theme(self, name, data, owner="core"):
        self.themes[name] = ThemeDef(name, data, owner)
        return self.themes[name]

    def cleanup_owner(self, owner):
        self.events.off(owner=owner)
        self.commands = {k: v for k, v in self.commands.items() if v.owner != owner}
        self.segments = {k: v for k, v in self.segments.items() if v[1] != owner}
        self.themes = {k: v for k, v in self.themes.items() if v.owner != owner}

    # ---------- témata a prompt ----------
    def current_theme(self):
        return self.themes.get(self.config.data.get("theme"))

    def set_theme(self, name):
        if name not in self.themes:
            return False
        old = self.config.data.get("theme")
        self.config.data["theme"] = name
        self.config.save()
        self.events.emit("theme_change", old=old, new=name)
        return True

    def prompt_context(self):
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = "?"
        home = os.path.expanduser("~")
        short = "~" + cwd[len(home):] if cwd == home or cwd.startswith(home + os.sep) else cwd
        now = time.localtime()
        ms = self.last_duration * 1000
        t_str = f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.2f}s"
        s_col = "\x1b[1;32m✓" if self.last_rc == 0 else f"\x1b[1;31m✗ {self.last_rc}"
        perf = f"\x1b[1;30m[{s_col}\x1b[1;30m ⏱ \x1b[1;33m{t_str}\x1b[1;30m]\x1b[0m"
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
        host = hostname()
        return {
            "user": user, "host": host, "cwd": short, "cwd_full": cwd,
            "cwd_base": os.path.basename(cwd) or "/",
            "cwd_name": "~" if cwd == home else (os.path.basename(cwd) or "/"), "perf": perf,
            "symbol": "#" if hasattr(os, "geteuid") and os.geteuid() == 0 else "$",
            "rc": self.last_rc, "status": "" if self.last_rc == 0 else str(self.last_rc),
            "time": time.strftime("%H:%M", now), "time_s": time.strftime("%H:%M:%S", now),
            "date": time.strftime("%d.%m.", now), "termux": "termux" if is_termux() else "",
            "duration": self.last_duration,
        }

    def render_template(self, tpl, ctx, theme=None):
        colors = (theme.data.get("colors") if theme else None) or {}

        def resolve(name):
            if name in colors:
                return style_code(colors[name]) or ""
            code = style_code(name)
            if code is not None:
                return code
            if name == "status_color":
                return style_code(colors.get("ok", "green") if ctx["rc"] == 0 else colors.get("err", "red")) or ""
            if name in ctx:
                return ctx[name]
            seg = self.segments.get(name)
            if seg:
                try:
                    return seg[0](ctx) or ""
                except Exception as exc:
                    self.report_error(seg[1], f"segment:{name}", exc)
            return ""

        return render(tpl, resolve)

    def render_prompt(self):
        """Vrací (hlavička_před_řádkem, řádek_promptu, pravý_prompt)."""
        self.events.emit("prompt_before")
        theme = self.current_theme()
        data = theme.data if theme else {}
        ctx = self.prompt_context()
        if callable(data.get("prompt_fn")):      # téma jako funkce: add_theme(jméno, {"prompt_fn": fn(user, cwd, git, perf)})
            try:
                seg = self.segments.get("git_box")
                git = (seg[0](ctx) if seg else "") or ""
                text = str(data["prompt_fn"](ctx["user"], ctx["cwd"], git, ctx["perf"]))
            except Exception as exc:
                self.report_error(theme.owner, "theme_fn", exc)
                text = self.render_template(DEFAULT_PROMPT, ctx, None)
        else:
            text = self.render_template(data.get("prompt", DEFAULT_PROMPT), ctx, theme)
        ev = self.events.emit("prompt_render", prompt=text, ctx=ctx)
        text = ev.data["prompt"]
        rp = self.render_template(data["rprompt"], ctx, theme) if data.get("rprompt") else ""
        head, _, last = text.rpartition("\n")
        return head, last, rp

    # ---------- historie ----------
    # ---------- historie: ~/.config/leapsh/history (jeden příkaz na řádek) ----------
    def _history_file(self):
        custom = self.config.data.get("history_file")
        return Path(os.path.expanduser(custom)) if custom else config_dir() / "history"

    def load_history(self):
        size = int(self.config.data.get("history_size", 5000))
        self.history_path = self._history_file()
        try:
            with open(self.history_path, encoding="utf-8", errors="replace") as f:
                lines = [l.rstrip("\n") for l in f if l.strip()]
        except OSError:
            lines = []
        raw = len(lines)
        if self.config.data.get("history_dedupe", True):      # ponechá poslední výskyt každého příkazu
            seen, kept = set(), []
            for l in reversed(lines):
                if l not in seen:
                    seen.add(l)
                    kept.append(l)
            lines = kept[::-1]
        self.history = lines[-size:]
        if raw > len(self.history) + 200:                      # soubor otékl duplicitami -> sbalit
            self._write_history()

    def _write_history(self):
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(l + "\n" for l in self.history))
            os.replace(tmp, self.history_path)
        except OSError:
            pass

    def history_add(self, line):
        line = line.split("\n", 1)[0]
        if not line.strip() or line.startswith(" ") or (self.history and self.history[-1] == line):
            return
        if self.config.data.get("history_dedupe", True) and line in self.history:
            self.history.remove(line)
        self.history.append(line)
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.history_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)   # soukromé: jen vlastník
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:
            pass

    def history_clear(self):
        self.history = []
        self._write_history()

    def history_delete(self, number):
        if 1 <= number <= len(self.history):
            del self.history[number - 1]
            self._write_history()
            return True
        return False

    def expand_history(self, line):
        """!! · !$ · !N · !-N · !prefix  (mimo apostrofy). Vrací nový řádek, nebo None, když se odkaz nenašel."""
        if "!" not in line:
            return line
        h, out, i, quote = self.history, [], 0, False
        while i < len(line):
            c = line[i]
            if c == "'":
                quote = not quote
            elif c == "\\" and i + 1 < len(line):
                out.append(line[i:i + 2])
                i += 2
                continue
            elif c == "!" and not quote and i + 1 < len(line) and line[i + 1] not in " =\t":
                m = re.match(r"!(!|\$|-?\d+|[A-Za-z_./~][^\s;&|<>()]*)", line[i:])
                if m:
                    ref, rep = m.group(1), None
                    if ref == "!":
                        rep = h[-1] if h else None
                    elif ref == "$":
                        rep = h[-1].split()[-1] if h and h[-1].split() else None
                    elif re.fullmatch(r"-?\d+", ref):
                        n = int(ref)
                        rep = h[n - 1] if 1 <= n <= len(h) else h[n] if n < 0 and -n <= len(h) else None
                    else:
                        rep = next((x for x in reversed(h) if x.startswith(ref)), None)
                    if rep is None:
                        self.warn(f"!{ref}: v historii nenalezeno")
                        return None
                    out.append(rep)
                    i += len(m.group(0))
                    continue
            out.append(c)
            i += 1
        return "".join(out)

    # ---------- spouštění ----------
    def executables(self):
        path = os.environ.get("PATH", "")
        now = time.monotonic()
        c = self._exe_cache
        if c and c[0] == path and now - c[1] < 30:
            return c[2]
        names = set()
        for d in path.split(os.pathsep):
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_file() and os.access(e.path, os.X_OK):
                                names.add(e.name)
                        except OSError:
                            pass
            except OSError:
                continue
        self._exe_cache = (path, now, names)
        return names

    def expand_alias(self, line):
        parts = line.split(None, 1)
        if parts and parts[0] in self.aliases:
            return self.aliases[parts[0]] + (" " + parts[1] if len(parts) > 1 else "")
        return line

    def _cwd(self):
        try:
            return os.getcwd()
        except OSError:
            return None

    def run_line(self, line):
        """Spustí řádek. Řetěz s příkazy shellu (a; b && c) se rozdělí, každý příkaz má vlastní události."""
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            return self.last_rc
        segs = self._split_chain(line)
        if segs:
            rc = self.last_rc
            for op, seg in segs:
                if (op == "&&" and rc != 0) or (op == "||" and rc == 0):
                    continue
                rc = self._run_one(seg)
                if not self.running:
                    break
            return rc
        return self._run_one(line)

    def _run_one(self, line):
        ev = self.events.emit("command_before", line=line)
        if ev.cancelled:
            return self.last_rc
        line = ev.data["line"]
        command = self.expand_alias(line)
        old_cwd = self._cwd()
        start = time.monotonic()
        try:
            rc = self.dispatch(command)
        except KeyboardInterrupt:
            rc = 130
        except Exception as exc:            # chyba v jádru nesmí shell shodit
            self.warn(f"vnitřní chyba při spuštění '{command.split()[0] if command.split() else command}': "
                      f"{type(exc).__name__}: {exc}")
            if os.environ.get("LEAPSH_DEBUG"):
                import traceback
                traceback.print_exc()
            rc = 1
        duration = time.monotonic() - start
        self.last_rc, self.last_duration = rc, duration
        new_cwd = self._cwd()
        if new_cwd != old_cwd:
            self.events.emit("dir_change", old=old_cwd, new=new_cwd)
        first = command.split(None, 1)[0] if command.split() else ""
        if rc == 127:
            self.events.emit("command_not_found", line=line, command=first)
        self.events.emit("command_after", line=line, command=command, rc=rc, duration=duration)
        return rc

    def _split_chain(self, line):
        """Rozdělí řádek na části podle ; && || (mimo uvozovky). Vrací None, pokud to nedává smysl."""
        if any(x in line for x in ("$(", "`", "(", "{", "\n")):
            return None
        segs, cur, op, i, q, n = [], [], ";", 0, None, len(line)
        while i < n:
            c = line[i]
            if q:
                cur.append(c)
                if c == q:
                    q = None
                elif c == "\\" and q == '"' and i + 1 < n:
                    cur.append(line[i + 1])
                    i += 1
            elif c in "'\"":
                q = c
                cur.append(c)
            elif c == "\\" and i + 1 < n:
                cur += [c, line[i + 1]]
                i += 1
            elif line.startswith(("&&", "||"), i):
                segs.append((op, "".join(cur)))
                cur, op = [], line[i:i + 2]
                i += 1
            elif c == ";":
                segs.append((op, "".join(cur)))
                cur, op = [], ";"
            else:
                cur.append(c)
            i += 1
        segs.append((op, "".join(cur)))
        segs = [(o, t.strip()) for o, t in segs]
        if len(segs) > 1 and all(t for _, t in segs) and any(t.split()[0] in self.commands for _, t in segs):
            return segs
        return None

    def dispatch(self, line):
        segs = self._split_chain(line)
        if segs:
            rc = 0
            for op, seg in segs:
                if (op == "&&" and rc != 0) or (op == "||" and rc == 0):
                    continue
                rc = self._dispatch_one(self.expand_alias(seg))
                if not self.running:
                    break
            return rc
        return self._dispatch_one(line)

    @staticmethod
    def _first_operator(line):
        """Index prvního | > < mimo uvozovky, jinak None."""
        q, i = None, 0
        while i < len(line):
            c = line[i]
            if q:
                if c == q:
                    q = None
            elif c in "'\"":
                q = c
            elif c == "\\":
                i += 1
            elif c in "|<>":
                return i
            i += 1
        return None

    def _dispatch_one(self, line):
        first = line.split(None, 1)[0]
        cmd = self.commands.get(first)
        if cmd:
            idx = self._first_operator(line)
            if idx is not None:
                # příkaz leapshe s rourou/přesměrováním: levou část spustí podproces leapsh, zbytek bash
                left, right = line[:idx].strip(), line[idx:]
                wrapped = (f"PYTHONPATH={__import__("shlex").quote(str(APP_DIR))}${{PYTHONPATH:+:$PYTHONPATH}} LEAPSH_QUIET=1 "
                           f"{__import__("shlex").quote(sys.executable)} -m leapsh -c {__import__("shlex").quote(left)} {right}")
                return self._exec_external(wrapped)
            import shlex
            try:
                args = shlex.split(line)[1:]
            except ValueError as exc:
                self.warn(f"chyba v syntaxi: {exc}")
                return 2
            try:
                return int(cmd.fn(self, args) or 0)
            except KeyboardInterrupt:
                return 130
            except Exception as exc:
                self.report_error(cmd.owner, f"command:{first}", exc)
                return 1
        return self._exec_external(line)

    # slova, po kterých musí příkaz jít přes bash (builtiny a klíčová slova, která mění stav shellu)
    SHELL_WORDS = frozenset(
        "cd export unset source . pushd popd set shopt declare local typeset read alias unalias eval exec wait ulimit "
        "umask trap enable hash type command builtin if for while until case select function time coproc [[ { ( "
        "! return break continue shift getopts let fg bg jobs disown kill history complete compgen".split())
    _SPECIAL = re.compile(r"[|&;<>()$`\\*?\[\]{}~!#=\n]")
    _STATE_WORDS = re.compile(
        r"(^|[;&|(\s])(cd|export|unset|source|pushd|popd|set|shopt|declare|local|typeset|read|alias|unalias|eval|exec|"
        r"umask|ulimit|trap|hash|\.)(\s|$)|(^|[;&|(]\s*)[A-Za-z_]\w*=")

    _use_spawn = None      # None = zatím nezjištěno; False = posix_spawnp není (např. Android/Termux) -> subprocess

    def _spawn(self, argv, env=None):
        """Spustí proces a počká na něj. Vrací návratový kód (záporný = signál).
        Používá os.posix_spawnp (rychlé, bez importu subprocess); kde není (Android/Termux), padá zpět na subprocess."""
        env = env if env is not None else os.environ
        old = signal.signal(signal.SIGINT, lambda s, f: None)       # Ctrl-C ukončí potomka, ne shell
        try:
            if self._use_spawn is None:
                self._use_spawn = hasattr(os, "posix_spawnp")
            pid = None
            if self._use_spawn:
                try:
                    pid = os.posix_spawnp(argv[0], argv, env, setsigdef=(signal.SIGPIPE, signal.SIGXFSZ))
                except (AttributeError, NotImplementedError, TypeError):
                    self._use_spawn = False                        # tato platforma to neumí, příště rovnou subprocess
            if pid is None:
                import subprocess
                return subprocess.Popen(argv, env=dict(env)).wait()
            while True:
                try:
                    _, status = os.waitpid(pid, 0)
                    break
                except InterruptedError:
                    continue
            if hasattr(os, "waitstatus_to_exitcode"):
                return os.waitstatus_to_exitcode(status)
            return -(status & 0x7F) if status & 0x7F else status >> 8
        finally:
            signal.signal(signal.SIGINT, old)

    def _fast_exec(self, line):
        """Jednoduchý příkaz bez speciálních znaků se spustí přímo, bez bashe. None = použij bash."""
        if self._SPECIAL.search(line):
            return None
        try:
            argv = __import__("shlex").split(line) if ("'" in line or '"' in line or "\\" in line) else line.split()
        except ValueError:
            return None
        if not argv or argv[0] in self.SHELL_WORDS:
            return None
        try:
            rc = self._spawn(argv)
        except FileNotFoundError:
            self.warn(f"{argv[0]}: příkaz nenalezen")
            return 127
        except PermissionError:
            self.warn(f"{argv[0]}: přístup odepřen")
            return 126
        except OSError as exc:
            if exc.errno == 8:          # ENOEXEC: skript bez shebangu – nechť ho spustí bash
                return None
            self.warn(f"{argv[0]}: {exc.strerror or exc}")
            return 126
        return 128 - rc if rc < 0 else rc

    def _exec_external(self, line):
        rc = self._fast_exec(line)
        if rc is not None:
            return rc
        sh = os.environ.get("LEAPSH_SHELL") or which("bash") or which("sh") or "/bin/sh"
        if not self._STATE_WORDS.search(line):                      # nic, co mění cwd/prostředí -> bez „ocásku“
            try:
                rc = self._spawn([sh, "-c", line])
            except OSError as exc:
                self.warn(f"nelze spustit {sh}: {exc}")
                return 127
            return 128 - rc if rc < 0 else rc
        import tempfile
        fd, state = tempfile.mkstemp(prefix="leapsh-state-")
        os.close(fd)
        # za příkaz přidáme „ocásek“, který do souboru uloží cwd a prostředí → cd/export fungují
        script = (line + "\n__leapsh_rc=$?\n"
                  "printf '%s\\0' \"$PWD\" > \"$LEAPSH_STATE\"\n"
                  "env -0 >> \"$LEAPSH_STATE\" 2>/dev/null\n"
                  "exit $__leapsh_rc\n")
        env = dict(os.environ)
        env["LEAPSH_STATE"] = state
        try:
            rc = self._spawn([sh, "-c", script], env)
        except OSError as exc:
            self.warn(f"nelze spustit {sh}: {exc}")
            rc = 127
        self._apply_state(state)
        try:
            os.unlink(state)
        except OSError:
            pass
        return 128 - rc if rc < 0 else rc

    def _apply_state(self, path):
        try:
            with open(path, "rb") as f:
                parts = f.read().split(b"\0")
        except OSError:
            return
        if not parts or not parts[0]:
            return
        cwd = os.fsdecode(parts[0])
        if os.path.isdir(cwd) and cwd != self._cwd():
            try:
                os.chdir(cwd)
            except OSError:
                pass
        new = {}
        for item in parts[1:]:
            if b"=" in item:
                k, v = item.split(b"=", 1)
                new[os.fsdecode(k)] = os.fsdecode(v)
        if len(new) < 2:
            return
        skip = {"_", "LEAPSH_STATE", "SHLVL"}
        for k in list(os.environ):
            if k not in new and k not in skip:
                del os.environ[k]
        for k, v in new.items():
            if k not in skip and os.environ.get(k) != v:
                os.environ[k] = v

    # ---------- režimy ----------
    def run_lines(self, lines):
        rc = 0
        self.events.emit("startup", interactive=False)
        lines, merged, i = list(lines), [], 0
        while i < len(lines):                      # heredoc přes víc řádků slož do jednoho příkazu
            line, delim = lines[i], self._heredoc_delim(lines[i])
            i += 1
            if delim:
                while i < len(lines):
                    line += "\n" + lines[i]
                    i += 1
                    if lines[i - 1].strip() == delim:
                        break
                else:
                    line += "\n" + delim
            merged.append(line)
        for line in merged:
            if line.strip() and not line.lstrip().startswith("#"):
                rc = self.run_line(line)
            if not self.running:
                return self.exit_code
        self.events.emit("shutdown")
        return rc

    @staticmethod
    def _heredoc_delim(line):
        m = re.search(r"<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?", line) if "<<<" not in line else None
        return m.group(1) if m else None

    def _read_heredoc(self, line):
        """Řádek s `<<DELIM` si dočte další řádky až po DELIM ."""
        delim = self._heredoc_delim(line)
        if not delim:
            return line
        while True:
            try:
                more = self.editor.read_line(prompt="> ")
            except KeyboardInterrupt:
                more = None
            if more is None:                       # Ctrl-C/Ctrl-D: heredoc uzavřeme sami
                return line + "\n" + delim
            line += "\n" + more
            if more.strip() == delim:
                return line

    def run_rc(self):
        """~/.config/leapsh/rc: příkazy spouštěné při startu interaktivního shellu (aliasy, export, theme set …)."""
        rc = config_dir() / "rc"
        try:
            lines = rc.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            if line.strip() and not line.lstrip().startswith("#"):
                self.run_line(line)

    def repl(self):
        from .editor import LineEditor
        self.editor = LineEditor(self)
        self.events.emit("startup", interactive=True)
        if not os.environ.get("LEAPSH_NORC"):
            self.run_rc()
            self.last_rc, self.last_duration = 0, 0.0
        while self.running:
            try:
                line = self.editor.read_line()
            except KeyboardInterrupt:
                continue
            if line is None:
                self.say("exit")
                break
            expanded = self.expand_history(line)
            if expanded is None:
                continue
            if expanded != line:
                self.say(f"\x1b[2m{expanded}\x1b[0m")
                line = expanded
            self.history_add(line)
            line = self._read_heredoc(line)
            try:
                self.run_line(line)
            except Exception as exc:        # poslední záchranná síť: smyčka shellu nikdy nespadne
                self.warn(f"vnitřní chyba: {type(exc).__name__}: {exc}")
        self.events.emit("shutdown")
        return self.exit_code
