# Addony

Addon je **doplněk existujícího pluginu**. Žije v `~/.config/leapsh/addons/<jmeno>/` a má stejnou strukturu jako plugin (`config.json` + `src/`):

```json
{ "name": "muj_addon", "version": "1.0.0", "type": "addon", "extends": "git_prompt", "description": "…" }
```

Načte se po svém cílovém pluginu. Když je plugin vypnutý nebo chybí, addon se přeskočí; když plugin znovu zapneš (`plugin enable`), addon se načte s ním. Vypnutí pluginu odebere i jeho addony.

```python
from leapsh.api import Addon

class MujAddon(Addon):
    def on_load(self):
        # self.target = instance rozšiřovaného pluginu
        self.extend("git_format", self.upravit)
```

## Tři způsoby, jak rozšířit plugin

1. **Extension point** – plugin v kódu zavolá `value = self.run_extensions("bod", value, **ctx)` a addon se zapojí `self.extend("bod", fn)`;
   `fn(value, **ctx)` vrátí novou hodnotu (nebo `None` = beze změny). Body pluginu vidíš v `plugin info`.
   - `git_prompt`: `git_info(info)`, `git_format(text, info=)`
   - `cmd_timer`: `slow_command(data)`
2. **`self.wrap("metoda", wrapper)`** – obalí libovolnou metodu cílového pluginu: `wrapper(original, *args, **kwargs)`.
   Funguje i na pluginy, které žádné extension pointy nenabízí.
3. **Přímá úprava** – `self.target.theme[...]` u témat, `self.target.setting(...)` apod.

Addon má navíc všechno, co plugin: `self.on(...)`, `self.add_command(...)`, `self.add_segment(...)`, nastavení.
Při odebrání se `extend()` i `wrap()` uklidí samy; vlastní změny vrať v `on_unload()`.

`addon create jmeno cílový_plugin` vytvoří kostru.
