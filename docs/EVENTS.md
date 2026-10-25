# Události

| událost | data | `cancel()` dělá |
|---|---|---|
| `startup` | interactive | – |
| `shutdown` | – | – |
| `prompt_before` | – | – |
| `prompt_render` | prompt (měnitelný), ctx | – |
| `key` | key, char, buffer, cursor, editor | zruší výchozí akci klávesy |
| `input_change` | buffer, previous, cursor, editor | – |
| `input_render` | buffer, cursor, ghost (šedý návrh), styler (funkce text→obarvený text) | – |
| `idle` | seconds, editor – po každé vteřině bez klávesy; po dlouhé akci zavolej `ev.editor.reset_idle()` | – |
| `complete` | word, first, buffer, candidates (přidávej) | – |
| `command_before` | line (měnitelný) | příkaz se nespustí |
| `command_after` | line, command, rc, duration | – |
| `command_not_found` | line, command | – |
| `dir_change` | old, new | – |
| `theme_change` | old, new | – |
| `plugin_loaded` / `plugin_unloaded` | name, kind | – |
| `*` | libovolná událost | – |

## Jména kláves (`ev.key`)

Písmena a znaky jako jsou (`a`, `Ž`, `/`), dále `enter`, `tab`, `shift-tab`, `backspace`, `delete`, `esc`,
`up`, `down`, `left`, `right`, `home`, `end`, `pageup`, `pagedown`, `insert`, `f1`–`f12`,
`ctrl-a` … `ctrl-z`, `alt-<znak>`, `alt-backspace` a kombinace se šipkami (`ctrl-left`, `alt-right`, …).

## Příklady

Zakázat `rm -rf /`:
```python
def guard(ev):
    if ev.line.strip().startswith("rm -rf /"):
        self.say("Tohle ne.")
        ev.cancel()
self.on("command_before", guard)
```

Vlastní doplňování:
```python
self.on("complete", lambda ev: ev.data["candidates"].extend(["main", "dev"]) if ev.word[:1] == "m" else None)
```

Reakce na psaní:
```python
self.on("input_change", lambda ev: ...)   # ev.buffer je aktuální text
```
