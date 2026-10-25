from leapsh.api import Plugin


class __CLASS__(Plugin):
    # Extension pointy, do kterých se můžou zapojit addony (volitelné):
    provides = ["my_point"]

    def on_load(self):
        # 1) události:  self.on("název_události", handler)   (viz příkaz `events`)
        self.on("command_after", self.after)
        # 2) nový příkaz:  self.add_command("jméno", fn, "nápověda")
        self.add_command("__NAME__", self.cmd, "ukázkový příkaz pluginu __NAME__")
        # 3) segment promptu, použitelný v tématu jako {__NAME__}
        self.add_segment("__NAME__", lambda ctx: "")

    def after(self, ev):
        # ev.line, ev.rc, ev.duration ...
        pass

    def cmd(self, shell, args):
        # řetězec projde extension pointem – addony ho můžou upravit
        text = self.run_extensions("my_point", self.setting("hello", "ahoj"))
        shell.say(text)
        return 0

    def on_unload(self):
        pass
