from leapsh.api import Addon

PALETTE = ["#ff5555", "#ffb86c", "#f1fa8c", "#50fa7b", "#8be9fd", "#bd93f9", "#ff79c6"]


class HighlightRainbow(Addon):
    def on_load(self):
        self.extend("highlight_token", self.paint)

    def paint(self, color, kind="", index=0, **ctx):
        if kind == "unknown":
            return None
        return PALETTE[index % len(PALETTE)]
