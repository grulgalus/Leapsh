import os
import random

from leapsh.api import Plugin

TIPS = [
    "Zkus `snake` – hra přímo v shellu.",
    "`plugin new nazev` vytvoří vlastní plugin a hned ho načte.",
    "`theme preview` ukáže všechna témata, `theme set neon` přepne.",
    "Ctrl+G spustí `git status -sb` (plugin keybinds, změníš přes `bind`).",
    "`pet feed` nakrmí mazlíčka. Úspěšné příkazy ho těší, chyby mrzí.",
    "`achievements` ukáže, jaké trofeje už máš.",
    "`train` projede vlak. (`sl` se záměrně opraví na `ls`, viz autocorrect.)",
    "Po chvíli nečinnosti naskočí matrix. Vypneš ho: `plugin set arcade screensaver false`.",
    "`plugin disable syntax_highlight` vypne barvy při psaní, `plugin enable highlight_rainbow` je změní na duhu.",
    "→ nebo End přijme šedý návrh z historie.",
    "Plugin můžeš napsat i ve WASM: `plugin create muj --wasm`.",
    "`leapsh-compile-plugin .` zkontroluje plugin a zabalí ho do .leapsh balíčku.",
    "`events` ukáže všechny události, na které se dají věšet pluginy.",
]


class Motd(Plugin):
    # extension point: tips(list) -> upravený seznam tipů
    provides = ["tips"]

    def on_load(self):
        self.on("startup", self.show)

    def show(self, ev):
        if not ev.interactive or os.environ.get("LEAPSH_QUIET"):
            return
        tips = self.run_extensions("tips", list(TIPS))
        if tips:
            self.say(f"\x1b[2m💡 {random.choice(tips)}\x1b[0m")
