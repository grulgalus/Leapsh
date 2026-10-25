from leapsh.api import Addon


class HelloShout(Addon):
    def on_load(self):
        self.extend("greeting", lambda text, **ctx: text.upper())
