from leapsh.api import Plugin

DEFAULT_FIXES = {
    "sl": "ls", "ls-la": "ls -la", "gti": "git", "gits": "git", "cd..": "cd ..", "claer": "clear",
    "clera": "clear", "pyhton": "python", "pytohn": "python", "grpe": "grep", "gerp": "grep",
    "mkdr": "mkdir", "suod": "sudo", "sduo": "sudo", "exot": "exit", "eixt": "exit", "ecoh": "echo",
}


class Autocorrect(Plugin):
    # extension point: autocorrect_fixes(dict) -> dict (addon může přidat vlastní opravy)
    provides = ["autocorrect_fixes"]

    def on_load(self):
        self.on("command_before", self.fix, priority=10)

    def fixes(self):
        merged = dict(DEFAULT_FIXES)
        merged.update(self.setting("fixes", {}))
        return self.run_extensions("autocorrect_fixes", merged)

    def fix(self, ev):
        line = ev.data["line"]
        parts = line.split(None, 1)
        if not parts:
            return
        repl = self.fixes().get(parts[0])
        if repl is None:
            return
        new = repl + (" " + parts[1] if len(parts) > 1 else "")
        if self.setting("announce", True):
            self.say(f"\x1b[2m↪ {new}\x1b[0m")
        ev.data["line"] = new
