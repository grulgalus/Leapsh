import sys

from leapsh._fast import which
from leapsh.api import Addon


class CmdTimerNotify(Addon):
    def on_load(self):
        self.extend("slow_command", self.notify)

    def notify(self, value, **ctx):
        d = value.get("duration", 0)
        if d < float(self.setting("threshold", 30)):
            return
        title = "leapsh: příkaz dokončen"
        body = f"{value.get('line', '')[:60]} (rc={value.get('rc')}, {d:.0f}s)"
        if which("termux-notification"):
            __import__('subprocess').Popen(["termux-notification", "--title", title, "--content", body])
        elif which("notify-send"):
            __import__('subprocess').Popen(["notify-send", title, body])
        else:
            sys.stdout.write("\a")
