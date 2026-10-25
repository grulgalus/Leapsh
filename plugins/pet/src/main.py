import json
import time

from leapsh.api import Plugin
from leapsh.config import config_dir

FACES = [(80, "(^‿^)", "green"), (55, "(•‿•)", "cyan"), (30, "(•_•)", "yellow"), (0, "(;_;)", "red")]


class Pet(Plugin):
    # extension point: pet_face(face, mood=, level=, name=) -> upravený obličej (addon přidá třeba klobouk)
    provides = ["pet_face"]

    def on_load(self):
        self.file = config_dir() / "pet.json"
        self.s = {"name": "Leapy", "xp": 0, "mood": 70.0, "ts": time.time()}
        try:
            self.s.update(json.loads(self.file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        hours = (time.time() - self.s["ts"]) / 3600
        if self.s["mood"] > 30:  # bez pozornosti mu pomalu klesá nálada (ne pod 30)
            self.s["mood"] = max(30.0, self.s["mood"] - hours * 4)
        self._n = 0
        self.on("command_after", self.after)
        self.on("shutdown", lambda ev: self.save())
        self.add_segment("pet", self.segment)
        self.add_command("pet", self.cmd, "mazlíček: pet | pet feed | pet stroke | pet name JMÉNO")

    @property
    def level(self):
        return 1 + int(self.s["xp"] // 25)

    def save(self):
        self.s["ts"] = time.time()
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.s), encoding="utf-8")
        except OSError:
            pass

    def after(self, ev):
        if ev.rc == 130:
            return
        old = self.level
        if ev.rc == 0:
            self.s["xp"] += 1
            self.s["mood"] = min(100.0, self.s["mood"] + 2)
        else:
            self.s["mood"] = max(0.0, self.s["mood"] - 6)
        if self.level > old:
            self.say(f"\x1b[1;35m🎉 {self.s['name']} dosáhl levelu {self.level}!\x1b[0m")
        self._n += 1
        if self._n % 10 == 0:
            self.save()

    def face(self):
        m = self.s["mood"]
        for limit, face, color in FACES:
            if m >= limit:
                break
        face = self.run_extensions("pet_face", face, mood=m, level=self.level, name=self.s["name"])
        return face, color

    def segment(self, ctx):
        face, color = self.face()
        return f" {self.style(color)}{face}\x1b[0m"

    def cmd(self, shell, args):
        sub = args[0] if args else "status"
        s = self.s
        if sub == "feed":
            s["mood"] = min(100.0, s["mood"] + 25)
            shell.say(f"{s['name']}: ňam ňam! 🍖")
        elif sub in ("stroke", "pet"):
            s["mood"] = min(100.0, s["mood"] + 8)
            shell.say(f"{s['name']} příjemně vrní… ♥")
        elif sub == "name" and len(args) > 1:
            s["name"] = " ".join(args[1:])[:20]
            shell.say(f"Od teď se jmenuje {s['name']}.")
        face, color = self.face()
        bar = int(s["mood"] // 10)
        shell.say(f"\n  {self.style(color)}{face}\x1b[0m  {s['name']}   level {self.level}   {int(s['xp'])} xp")
        shell.say(f"  nálada [{'█' * bar}{'░' * (10 - bar)}] {int(s['mood'])} %")
        shell.say(f"  do dalšího levelu: {25 - int(s['xp']) % 25} úspěšných příkazů\n")
        self.save()
        return 0
