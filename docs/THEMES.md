# Témata

Téma je plugin s `"type": "theme"`. Nejjednodušší je čisté JSON (žádný Python):

```json
{
  "name": "theme_moje", "version": "1.0.0", "type": "theme",
  "theme": {
    "name": "moje",
    "colors": {"ok": "green", "err": "red", "akcent": "bold #ff8800"},
    "prompt": "{akcent}{cwd}{reset}{git}\n{status_color}❯{reset} ",
    "rprompt": "{dim}{time}{reset}"
  }
}
```
`theme new moje` vytvoří kostru, `theme set moje` ho zapne, `theme preview` ukáže všechna.

## Proměnné v šabloně `{...}`

| skupina | názvy |
|---|---|
| styly | `reset bold dim italic underline reverse`, barvy `black red green yellow blue magenta cyan white gray bright_*`, pozadí `on_red`…, 256 barev `{208}`, truecolor `{#ff8800}`; kombinace v aliasech: `"bold #ff8800"` |
| vlastní aliasy | cokoli z `colors` (aliasy mají přednost) |
| stav | `{status_color}` (barva `ok`/`err` podle posledního návratového kódu), `{rc}`, `{status}` (prázdné při 0), `{duration}` |
| informace | `{user} {host} {cwd} {cwd_full} {cwd_base} {symbol} {time} {time_s} {date} {termux}` |
| segmenty z pluginů | `{git}`, `{last_time}`, `{battery}` (Termux), … |

`\n` v `prompt` dělá víceřádkový prompt (poslední řádek je ten, kam se píše). `rprompt` se kreslí vpravo a zmizí, když by se nevešel.

## Téma s kódem

Plugin může registrovat téma v `on_load`: `self.add_theme("jméno", {...})`. Addon může živý slovník tématu měnit
(`self.target.theme`) – viz `addons/neon_clock`.

## Další proměnné a pokročilá témata

| proměnná | význam |
|---|---|
| `{perf}` | telemetrie posledního příkazu: `[✓ ⏱ 12ms]` nebo `[✗ 127 ⏱ 3ms]` |
| `{cwd_name}` | jen název složky (`~` pro domovskou) |
| `{git_box}` | `─[git:větev*]` (plugin git_prompt) |

**Balíček témat:** v `config.json` místo `"theme"` dej `"themes": [ {...}, {...} ]`; jeden plugin pak zaregistruje víc témat
(viz `plugins/themes_extra`).

**Téma jako funkce:** Python plugin může zaregistrovat téma, které prompt počítá kódem:
```python
def prompt(user, cwd, git, perf):
    return f"\n{user} {cwd}{git} {perf}\n> "
self.add_theme("moje", {"prompt_fn": prompt})
```
