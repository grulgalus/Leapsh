from leapsh.api import Addon


class __CLASS__(Addon):
    def on_load(self):
        # self.target je instance rozšiřovaného pluginu (__TARGET__)
        # a) zapojit se do extension pointu pluginu:
        self.extend("my_point", self.upravit)
        # b) obalit metodu pluginu (wrapper dostane originál jako první argument):
        # self.wrap("segment", lambda orig, ctx: orig(ctx) + "!")
        # c) addon smí všechno, co plugin: self.on(...), self.add_command(...), self.add_segment(...)

    def upravit(self, value, **ctx):
        return value + " (upraveno addonem __NAME__)"

    def on_unload(self):
        pass  # wrap() i extend() se při odebrání addonu uklidí samy
