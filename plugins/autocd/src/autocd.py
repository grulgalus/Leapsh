import os
import shlex

from leapsh.api import Plugin


class Autocd(Plugin):
    def on_load(self):
        self.on("command_before", self.rewrite, priority=5)

    def rewrite(self, ev):
        try:
            parts = shlex.split(ev.data["line"])
        except ValueError:
            return
        if len(parts) != 1:
            return
        word = parts[0]
        sh = self.shell
        if word in sh.commands or word in sh.aliases or word in sh.executables():
            return
        if os.path.isdir(os.path.expanduser(word)):
            ev.data["line"] = "cd -- " + shlex.quote(word)
