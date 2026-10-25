from leapsh.api import Plugin


def fmt(sec):
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}m {s:02d}s"


class CmdTimer(Plugin):
    # extension point: slow_command (value = data události command_after: line, rc, duration)
    provides = ["slow_command"]

    def on_load(self):
        self.on("command_after", self.after)
        self.add_segment("last_time", self.segment)

    def after(self, ev):
        if ev.duration >= float(self.setting("threshold", 3)):
            self.say(f"\x1b[2m⏱  {fmt(ev.duration)}\x1b[0m")
            self.run_extensions("slow_command", dict(ev.data))

    def segment(self, ctx):
        d = ctx.get("duration", 0)
        return fmt(d) if d >= float(self.setting("threshold", 3)) else ""
