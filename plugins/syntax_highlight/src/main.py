import os
import re

from leapsh.api import Plugin
from leapsh.theme import RESET, style_code

KEYWORDS = {"cd", "export", "if", "then", "else", "elif", "fi", "for", "in", "do", "done", "while", "until",
            "case", "esac", "echo", "exit", "source", "unset", "set", "read", "eval", "exec", "local",
            "return", "test", "true", "false", "type", "pwd", "kill", "wait", "trap", "umask", "jobs", "fg",
            "bg", "time", "command", "builtin", "pushd", "popd", "dirs", "printf", "shift"}
DEFAULT_COLORS = {"command": "green", "unknown": "red", "flag": "cyan", "str": "yellow", "var": "magenta",
                  "op": "bold blue", "path": "underline", "assign": "magenta", "partial": "", "arg": ""}
TOKEN = re.compile(r"""(?P<space>\s+)|(?P<str>"(?:[^"\\]|\\.)*"?|'[^']*'?)|(?P<op>\|\||&&|[|;&<>]+)"""
                   r"""|(?P<word>[^\s|;&<>"']+)""")


class SyntaxHighlight(Plugin):
    # extension point: highlight_token(color, token=, kind=, index=) -> nová barva (styl) pro token
    provides = ["highlight_token"]

    def on_load(self):
        self.on("input_render", self.render, priority=-5)

    def render(self, ev):
        ev.data["styler"] = self.highlight

    def color(self, kind, token, index):
        colors = dict(DEFAULT_COLORS, **self.setting("colors", {}))
        return self.run_extensions("highlight_token", colors.get(kind, ""), token=token, kind=kind, index=index)

    def highlight(self, text):
        sh = self.shell
        names = None
        out, expect_cmd, idx = [], True, 0
        for m in TOKEN.finditer(text):
            kind, tok = m.lastgroup, m.group()
            if kind == "space":
                out.append(tok)
                continue
            if kind == "op":
                expect_cmd = bool(re.search(r"[|;&]", tok))
            elif kind == "word":
                if expect_cmd:
                    if re.match(r"[A-Za-z_]\w*=", tok):
                        kind = "assign"
                    else:
                        if names is None:
                            names = set(sh.commands) | set(sh.aliases) | sh.executables() | KEYWORDS
                        path = os.path.expanduser(tok)
                        if tok in names or ("/" in tok and os.path.isfile(path) and os.access(path, os.X_OK)):
                            kind = "command"
                        elif m.end() == len(text) and any(n.startswith(tok) for n in names):
                            kind = "partial"   # ještě píše – nezačerveňuj
                        else:
                            kind = "unknown"
                        expect_cmd = False
                elif tok.startswith("-"):
                    kind = "flag"
                elif tok.startswith("$"):
                    kind = "var"
                elif os.path.exists(os.path.expanduser(tok)):
                    kind = "path"
                else:
                    kind = "arg"
            spec = self.color(kind, tok, idx)
            idx += 1
            code = style_code(spec) if spec else None
            out.append(f"{code}{tok}{RESET}" if code else tok)
        return "".join(out)
