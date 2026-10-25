import json
import time

from leapsh.api import Plugin
from leapsh.config import config_dir


class EventLogger(Plugin):
    def on_load(self):
        self.file = config_dir() / "events.log"
        self.on("*", self.log, priority=-100)
        self.add_command("evlog", self.cmd, "evlog on|off|show [N]|path – log událostí")

    def log(self, ev):
        if not self.setting("enabled", False) or ev.name in self.setting("skip", []):
            return
        data = {k: v for k, v in ev.data.items() if isinstance(v, (str, int, float, bool, type(None)))}
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, "a", encoding="utf-8") as f:
                f.write(f"{time.time():.3f} {ev.name} {json.dumps(data, ensure_ascii=False)}\n")
        except OSError:
            pass

    def cmd(self, shell, args):
        sub = args[0] if args else "show"
        if sub in ("on", "off"):
            self.set_setting("enabled", sub == "on")
            shell.say(f"logování událostí: {sub}  ({self.file})")
        elif sub == "path":
            shell.say(str(self.file))
        elif sub == "show":
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
            try:
                for line in self.file.read_text(encoding="utf-8").splitlines()[-n:]:
                    shell.say(line)
            except OSError:
                shell.say("log je prázdný")
        return 0
