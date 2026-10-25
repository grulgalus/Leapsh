import json
import math
import os
import time

from leapsh.api import Plugin
from leapsh.config import config_dir


class Jump(Plugin):
    """Navštívené složky se ukládají do ~/.config/leapsh/dirs.json jako {cesta: [počet, naposledy]}."""

    def on_load(self):
        self.file = config_dir() / "dirs.json"
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self._dirty = 0
        self.on("dir_change", self.visited)
        self.on("shutdown", lambda ev: self.save())
        self.on("complete", self.complete)
        self.add_command("z", self.cmd, "z ČÁST_CESTY | z -l (seznam) | z -x CESTA (zapomenout)")

    def save(self):
        if not self._dirty:
            return
        keep = int(self.setting("max_entries", 500))
        if len(self.data) > keep:
            top = sorted(self.data.items(), key=lambda kv: -self.score(kv[1]))[:keep]
            self.data = dict(top)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.data), encoding="utf-8")
            self._dirty = 0
        except OSError:
            pass

    def visited(self, ev):
        new = ev.new
        if new and new != os.path.expanduser("~"):
            n, _ = self.data.get(new, [0, 0])
            self.data[new] = [n + 1, time.time()]
            self._dirty += 1
            if self._dirty >= 10:
                self.save()

    @staticmethod
    def score(entry, now=None):
        """frecency: četnost zvýhodněná čerstvostí (hodina ×4, den ×2, týden ×0.5, starší ×0.25)"""
        count, last = entry
        age = (now or time.time()) - last
        weight = 4 if age < 3600 else 2 if age < 86400 else 0.5 if age < 604800 else 0.25
        return count * weight

    def best(self, words):
        now, words = time.time(), [w.lower() for w in words]
        hits = []
        for path, entry in self.data.items():
            low = path.lower()
            if all(w in low for w in words) and os.path.isdir(path):
                bonus = 2 if words[-1] in os.path.basename(low) else 1       # shoda v názvu složky vítězí
                hits.append((self.score(entry, now) * bonus, path))
        return sorted(hits, reverse=True)

    def cmd(self, shell, args):
        if not args:
            return self._go(shell, os.path.expanduser("~"))
        if args[0] == "-l":
            for sc, path in self.best([""])[:15]:
                shell.say(f"{sc:8.1f}  {path}")
            return 0
        if args[0] == "-x" and len(args) > 1:
            self.data.pop(os.path.abspath(os.path.expanduser(args[1])), None)
            self._dirty += 1
            self.save()
            return 0
        if os.path.isdir(os.path.expanduser(args[0])) and len(args) == 1:       # z /cesta  = obyčejné cd
            return self._go(shell, os.path.expanduser(args[0]))
        hits = self.best(args)
        if not hits:
            shell.say(f"z: nic odpovídajícího '{' '.join(args)}' (zatím jsem tam nebyl?)")
            return 1
        return self._go(shell, hits[0][1])

    @staticmethod
    def _go(shell, path):
        try:
            os.chdir(path)
        except OSError as exc:
            shell.say(f"z: {exc}")
            return 1
        os.environ["OLDPWD"], os.environ["PWD"] = os.environ.get("PWD", ""), path
        shell.say(f"\x1b[2m{path}\x1b[0m")
        return 0

    def complete(self, ev):
        prev = ev.left.split()
        if prev[:1] == ["z"] and not ev.first:
            names = sorted({os.path.basename(p) for p in self.data if os.path.isdir(p)})
            found = [n for n in names if n.lower().startswith(ev.word.lower())]
            if found:
                ev.data["candidates"][:] = found
