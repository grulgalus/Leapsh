
from leapsh._fast import which
from leapsh.api import Addon


class TermuxHaptics(Addon):
    def on_load(self):
        self.on("command_after", self.buzz)

    def buzz(self, ev):
        if ev.rc not in (0, 130) and which("termux-vibrate"):
            __import__('subprocess').Popen(["termux-vibrate", "-d", str(self.setting("duration_ms", 80))])
