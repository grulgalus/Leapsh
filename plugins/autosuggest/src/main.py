from leapsh.api import Plugin


class Autosuggest(Plugin):
    def on_load(self):
        self.on("input_render", self.render)
        self.on("key", self.key, priority=10)

    def suggest(self, buf):
        if not buf or buf.startswith(" "):
            return ""
        for h in reversed(self.shell.history):
            if h.startswith(buf) and h != buf:
                return h[len(buf):]
        return ""

    def render(self, ev):
        if ev.cursor == len(ev.buffer):
            ev.data["ghost"] = self.suggest(ev.buffer)

    def key(self, ev):
        if ev.key in ("right", "end", "ctrl-e") and ev.cursor == len(ev.buffer):
            g = self.suggest(ev.buffer)
            if g:
                ev.editor.insert(g)
                ev.cancel()
