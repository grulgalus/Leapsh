import json
import time

from leapsh._fast import which
from leapsh.api import Plugin


class TermuxExtras(Plugin):
    def on_load(self):
        self._val, self._ts, self._busy = "", 0.0, False
        self.add_segment("battery", self.segment)
        self.add_command("battery", self.cmd_battery, "stav baterie (termux-battery-status)")
        self.add_command("tnotify", self.cmd_notify, "tnotify TEXT – pošle notifikaci Androidu")

    def _read(self):
        if not which("termux-battery-status"):
            return None
        try:
            import subprocess
            out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5).stdout
            return json.loads(out)
        except (OSError, ValueError, __import__('subprocess').TimeoutExpired):
            return None

    def _refresh(self):
        d = self._read()
        if d:
            p = int(d.get("percentage", 0))
            col = "green" if p > 50 else "yellow" if p > 20 else "red"
            self._val = f"{self.style(col)}🔋{p}%{'⚡' if d.get('status') == 'CHARGING' else ''}\x1b[0m"
        self._ts, self._busy = time.monotonic(), False

    def segment(self, ctx):
        # termux-battery-status je pomalý → obnova na pozadí, prompt jen vezme poslední hodnotu
        if not self._busy and time.monotonic() - self._ts > 60:
            self._busy = True
            __import__('_thread').start_new_thread(self._refresh, ())
        return self._val

    def cmd_battery(self, shell, args):
        d = self._read()
        if not d:
            shell.say("termux-battery-status nejde spustit (pkg install termux-api + aplikace Termux:API)")
            return 1
        shell.say(f"{d.get('percentage')} % ({d.get('status')}), {d.get('temperature')} °C")
        return 0

    def cmd_notify(self, shell, args):
        if not which("termux-notification"):
            shell.say("chybí termux-notification (pkg install termux-api)")
            return 1
        __import__('subprocess').run(["termux-notification", "--title", "leapsh", "--content", " ".join(args)])
        return 0
