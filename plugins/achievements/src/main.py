import json
import time

from leapsh.api import Plugin
from leapsh.config import config_dir

# id, název, popis, podmínka(state, ctx)
ACH = [
    ("first", "První kroky", "spustil jsi první příkaz", lambda s, c: s["commands"] >= 1),
    ("hundred", "Stovkař", "100 příkazů", lambda s, c: s["commands"] >= 100),
    ("thousand", "Tisícovka", "1000 příkazů", lambda s, c: s["commands"] >= 1000),
    ("typos", "Prstoklad", "3 překlepy v příkazech po sobě", lambda s, c: s["nf_streak"] >= 3),
    ("owl", "Noční sova", "příkaz mezi půlnocí a pátou ránem", lambda s, c: 0 <= c["hour"] < 5),
    ("bird", "Ranní ptáče", "příkaz mezi pátou a sedmou ránem", lambda s, c: 5 <= c["hour"] < 7),
    ("marathon", "Maratonec", "příkaz, který běžel přes minutu", lambda s, c: c["duration"] >= 60),
    ("explorer", "Průzkumník", "25× změna složky", lambda s, c: s["dirs"] >= 25),
    ("git", "Git guru", "20 git příkazů", lambda s, c: s["git"] >= 20),
    ("phoenix", "Fénix", "úspěch po pěti chybách v řadě", lambda s, c: c.get("phoenix", False)),
    ("pianist", "Pianista", "5000 stisků kláves", lambda s, c: s["keys"] >= 5000),
]


class Achievements(Plugin):
    # extension point: unlocked(ach) – ach = {"id", "title", "desc"}
    provides = ["unlocked"]

    def on_load(self):
        self.file = config_dir() / "achievements.json"
        self.s = {"commands": 0, "errors": 0, "nf_streak": 0, "err_streak": 0, "dirs": 0, "git": 0,
                  "keys": 0, "unlocked": {}}
        try:
            self.s.update(json.loads(self.file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.on("command_after", self.after)
        self.on("command_not_found", lambda ev: self.s.__setitem__("nf_streak", self.s["nf_streak"] + 1))
        self.on("dir_change", lambda ev: self.s.__setitem__("dirs", self.s["dirs"] + 1))
        self.on("key", lambda ev: self.s.__setitem__("keys", self.s["keys"] + 1), priority=-50)
        self.on("shutdown", lambda ev: self.save())
        self.add_command("achievements", self.cmd, "seznam trofejí")

    def save(self):
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.s), encoding="utf-8")
        except OSError:
            pass

    def after(self, ev):
        s = self.s
        s["commands"] += 1
        ctx = {"hour": time.localtime().tm_hour, "duration": ev.duration}
        if ev.rc != 127:
            s["nf_streak"] = 0
        if ev.rc == 0:
            if s["err_streak"] >= 5:
                ctx["phoenix"] = True
            s["err_streak"] = 0
        elif ev.rc != 130:
            s["err_streak"] += 1
            s["errors"] += 1
        if ev.line.split()[:1] == ["git"]:
            s["git"] += 1
        for aid, title, desc, check in ACH:
            if aid not in s["unlocked"] and check(s, ctx):
                self.unlock(aid, title, desc)
        if s["commands"] % 10 == 0:
            self.save()

    def unlock(self, aid, title, desc):
        self.s["unlocked"][aid] = time.time()
        self.say(f"\x1b[1;33m🏆 Achievement odemčen: {title}\x1b[0m \x1b[2m– {desc}\x1b[0m")
        self.run_extensions("unlocked", {"id": aid, "title": title, "desc": desc})
        self.save()

    def cmd(self, shell, args):
        done = self.s["unlocked"]
        shell.say(f"\nTrofeje: {len(done)}/{len(ACH)}   (příkazů: {self.s['commands']}, kláves: {self.s['keys']})\n")
        for aid, title, desc, _ in ACH:
            mark = "\x1b[1;33m🏆\x1b[0m" if aid in done else "\x1b[2m··\x1b[0m"
            shell.say(f"  {mark} {title:<14} \x1b[2m{desc}\x1b[0m")
        shell.say()
        return 0
