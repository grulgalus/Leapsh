import os

from leapsh.api import Addon


class GitPromptStash(Addon):
    def on_load(self):
        self.extend("git_info", self.add_stash)
        self.extend("git_format", self.fmt)

    def add_stash(self, info, **ctx):
        n = 0
        try:
            with open(os.path.join(info["gitdir"], "logs", "refs", "stash"), encoding="utf-8") as f:
                n = sum(1 for _ in f)
        except OSError:
            pass
        info["stash"] = n
        return info

    def fmt(self, text, info=None, **ctx):
        if info and info.get("stash"):
            return text + f" ≡{info['stash']}"
