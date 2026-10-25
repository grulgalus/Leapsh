from leapsh.api import Plugin


class HelloEvents(Plugin):
    provides = ["greeting"]

    def on_load(self):
        self.count = 0
        self.on("input_change", self.typing)
        self.on("key", self.key)
        self.on("dir_change", lambda ev: self.say(f"→ přešel jsi do {ev.new}"))
        self.on("command_after", self.after)
        self.add_command("hello", self.hello, "pozdraví (rozšiřitelné addonem)")

    def typing(self, ev):
        self.count += 1          # ev.buffer = text, který uživatel právě píše

    def key(self, ev):
        if ev.key == "alt-h":    # vlastní zkratka
            ev.editor.insert("hello ")
            ev.cancel()

    def after(self, ev):
        if ev.rc != 0:
            self.say(f"\x1b[31m✗ '{ev.line}' skončil s kódem {ev.rc}\x1b[0m")

    def hello(self, shell, args):
        shell.say(self.run_extensions("greeting", f"Ahoj! Dosud jsi stiskl {self.count} kláves."))
        return 0
