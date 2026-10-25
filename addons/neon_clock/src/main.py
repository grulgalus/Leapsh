from leapsh.api import Addon


class NeonClock(Addon):
    """Addon může upravit i téma – self.target.theme je živý slovník tématu."""

    def on_load(self):
        t = self.target.theme
        self._orig = t.get("rprompt", "")
        t["rprompt"] = "{gray}{date}{reset} " + self._orig.replace("{time}", "{time_s}")

    def on_unload(self):
        self.target.theme["rprompt"] = self._orig
