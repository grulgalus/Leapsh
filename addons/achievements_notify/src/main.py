import sys

from leapsh._fast import which
from leapsh.api import Addon


class AchievementsNotify(Addon):
    def on_load(self):
        self.extend("unlocked", self.notify)

    def notify(self, ach, **ctx):
        if which("termux-vibrate"):
            __import__('subprocess').Popen(["termux-vibrate", "-d", "200"])
        if which("termux-notification"):
            __import__('subprocess').Popen(["termux-notification", "--title", "🏆 " + ach["title"], "--content", ach["desc"]])
        elif not which("termux-vibrate"):
            sys.stdout.write("\a")
