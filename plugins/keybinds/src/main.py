from leapsh.api import Plugin


class Keybinds(Plugin):
    """Hodnota začínající '+' se jen vloží na řádek (bez Enteru)."""

    def on_load(self):
        self.on("key", self.on_key)
        self.add_command("bind", self.cmd_bind, "zkratky: bind | bind KLÁVESA PŘÍKAZ | bind -d KLÁVESA")

    def on_key(self, ev):
        cmd = self.setting("bindings", {}).get(ev.key)
        if not cmd:
            return
        if cmd.startswith("+"):
            ev.editor.insert(cmd[1:])
        else:
            ev.editor.set_buffer(cmd)
            ev.editor.submit()
        ev.cancel()

    def cmd_bind(self, shell, args):
        b = dict(self.setting("bindings", {}))
        if not args:
            for k, v in sorted(b.items()):
                shell.say(f"{k:<12} {v}")
            return 0
        if args[0] == "-d" and len(args) > 1:
            b.pop(args[1], None)
        elif len(args) >= 2:
            b[args[0]] = " ".join(args[1:])
        else:
            shell.say("použití: bind KLÁVESA PŘÍKAZ   (např. bind alt-s git status)")
            return 2
        self.set_setting("bindings", b)
        return 0
