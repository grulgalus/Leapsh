import os
import time

from leapsh.api import Plugin


def find_gitdir(start):
    d = start
    while True:
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return d, g
        if os.path.isfile(g):  # worktree / submodul
            try:
                with open(g, encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt.startswith("gitdir:"):
                    p = txt[7:].strip()
                    return d, p if os.path.isabs(p) else os.path.join(d, p)
            except OSError:
                pass
        parent = os.path.dirname(d)
        if parent == d:
            return None, None
        d = parent


class GitPrompt(Plugin):
    # extension pointy, do kterých se mohou zapojit addony:
    #   git_info   (info: dict)       -> vrátí upravený dict
    #   git_format (text: str, info)  -> vrátí upravený text (bez barev)
    provides = ["git_info", "git_format"]

    def on_load(self):
        self._cache = (None, 0.0, "")
        self._dirty, self._busy = {}, set()
        self.add_segment("git", self.segment)
        self.add_segment("git_box", self.segment_box)   # ─[git:větev] pro motivy
        self.add_command("gitinfo", self.cmd_info, "ukáže info o git repozitáři v aktuální složce")

    def dirty_status(self, root):
        """`git status` běží na pozadí; prompt na něj čeká nejvýš 80 ms, jinak ukáže poslední známý stav (a příště je čerstvý)."""
        import _thread
        ts, val = self._dirty.get(root, (0.0, None))
        if time.monotonic() - ts < 2.0 or root in self._busy:
            return val
        box = []
        self._busy.add(root)

        def work():
            import subprocess
            try:
                r = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "-uno"], cwd=root,
                                   capture_output=True, text=True, timeout=10)
                v = bool(r.stdout.strip()) if r.returncode == 0 else None
            except Exception:
                v = None
            self._dirty[root] = (time.monotonic(), v)
            box.append(v)
            self._busy.discard(root)

        _thread.start_new_thread(work, ())
        for _ in range(16):
            if box:
                return box[0]
            time.sleep(0.005)
        return val

    def info(self):
        root, gitdir = find_gitdir(os.getcwd())
        if not gitdir:
            return None
        try:
            with open(os.path.join(gitdir, "HEAD"), encoding="utf-8") as f:
                head = f.read().strip()
        except OSError:
            return None
        branch = head[16:] if head.startswith("ref: refs/heads/") else head[:7]
        dirty = self.dirty_status(root) if self.setting("dirty", True) else None
        info = {"branch": branch, "dirty": dirty, "root": root, "gitdir": gitdir}
        return self.run_extensions("git_info", info)

    def cached_info(self):
        cwd, ts, info = self._cache
        if cwd == os.getcwd() and time.monotonic() - ts < 1.0:
            return info
        info = self.info()
        self._cache = (os.getcwd(), time.monotonic(), info)
        return info

    def segment(self, ctx):
        info = self.cached_info()
        if not info:
            return ""
        text = " (" + info["branch"] + ("*" if info["dirty"] else "") + ")"
        text = self.run_extensions("git_format", text, info=info)
        color = self.setting("dirty_color", "red") if info["dirty"] else self.setting("color", "yellow")
        return self.style(color) + text + "\x1b[0m"

    def segment_box(self, ctx):
        info = self.cached_info()
        if not info:
            return ""
        return f"\x1b[1;34m─[\x1b[1;35mgit:{info['branch']}{'*' if info['dirty'] else ''}\x1b[1;34m]\x1b[0m"

    def cmd_info(self, shell, args):
        info = self.info()
        if not info:
            shell.say("tady není git repozitář")
            return 1
        for k, v in info.items():
            shell.say(f"{k}: {v}")
        return 0
