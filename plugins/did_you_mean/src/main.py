from leapsh.api import Plugin


class DidYouMean(Plugin):
    def on_load(self):
        self.on("command_not_found", self.hint)

    def hint(self, ev):
        pool = set(self.shell.commands) | set(self.shell.aliases) | self.shell.executables()
        import difflib
        m = difflib.get_close_matches(ev.command, pool, n=3, cutoff=0.6)
        if m:
            self.say(f"\x1b[2mMyslel jsi: {', '.join(m)}?\x1b[0m")
