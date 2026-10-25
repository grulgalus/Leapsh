import os

from leapsh import __version__
from leapsh._fast import which
from leapsh.api import Plugin

LOGO = [r"    ____    ", r"   / ___|   ", r"  | |  _    ", r"  | |_| |   ", r"   \____|   ", r"            "]


class Toolbox(Plugin):
    def on_load(self):
        self.add_command("cmds", self.cmds, "přehledná tabulka všech příkazů")
        self.add_command("py", self.py, "py KÓD – spustí Python (proměnná shell = tento shell)")
        self.add_command("ai", self.ai, "ai dotaz – rychlá odpověď z cht.sh (potřebuje curl)")
        self.add_command("gfetch", self.fetch, "informace o systému a shellu")

    def cmds(self, shell, args):
        names = sorted(shell.commands)
        out = ["\x1b[1;35m╭─ 💡 HELP ───────────────────╮\x1b[0m"]
        for i in range(0, len(names), 2):
            row = "".join(f"\x1b[1;35m│\x1b[0m  \x1b[1;32m{n:<15}\x1b[0m" for n in names[i:i + 2])
            out.append(row)
        out.append("\x1b[1;35m╰─────────────────────────────╯\x1b[0m")
        shell.say("\n".join(out))
        return 0

    def py(self, shell, args):
        code = " ".join(args)
        env = {"shell": shell, "os": os, "__name__": "leapsh_py"}
        try:
            try:
                res = eval(compile(code, "<py>", "eval"), env)
                if res is not None:
                    shell.say(repr(res))
            except SyntaxError:
                exec(compile(code, "<py>", "exec"), env)
        except Exception as exc:
            shell.say(f"\x1b[1;31m[!] {type(exc).__name__}: {exc}\x1b[0m")
            return 1
        return 0

    def ai(self, shell, args):
        if not args:
            shell.say("použití: ai jak zabalit složku tar")
            return 2
        if not which("curl"):
            shell.say("chybí curl (v Termuxu: pkg install curl)")
            return 1
        from urllib.parse import quote
        import subprocess
        url = "cht.sh/" + "+".join(quote(a) for a in args) + "?T"
        return subprocess.run(["curl", "-s", url]).returncode

    def fetch(self, shell, args):
        x = self.xapi
        m = shell.manager
        info = [
            f"\x1b[1;32mUSER:\x1b[0m   {os.environ.get('USER', 'user')}",
            f"\x1b[1;32mSHELL:\x1b[0m  leapsh {__version__}",
            f"\x1b[1;32mIP:\x1b[0m     {x.ip()}",
            f"\x1b[1;32mBAT:\x1b[0m    {x.battery()}",
            f"\x1b[1;32mLANG:\x1b[0m   {str(x.lang()).upper()}",
            f"\x1b[1;32mTHEME:\x1b[0m  {x.theme()}   \x1b[1;32mPLUGINS:\x1b[0m {len(m.loaded)}+{len(m.addons)}",
        ]
        shell.say()
        for logo, line in zip(LOGO, info):
            shell.say(f"\x1b[1;36m{logo}\x1b[0m {line}")
        shell.say()
        return 0
