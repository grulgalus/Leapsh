# Psaní pluginů

Plugin = **složka** v `~/.config/leapsh/plugins/<jmeno>/` (nebo v `plugins/` u projektu) s manifestem `config.json`:

```
muj_plugin/
├── config.json        manifest
└── src/               veškerý kód
    ├── muj_plugin.py  třída odvozená od leapsh.api.Plugin; soubor se může jmenovat libovolně (u čistých témat není potřeba)
    └── pomocnik.py    další moduly: `from .pomocnik import neco`
```
`src/` se načítá jako balíček, takže si pluginy nekolidují jmény modulů. Při `reload` se načte vždy aktuální zdroj (žádné `.pyc`).
Stejná struktura platí pro addony (`addons/<jmeno>/`) i témata. `plugin create jmeno` ji vygeneruje.

Plugin může být **Python** (`src/main.py`) nebo **WASM** (`"runtime": "wasm"`, viz `docs/WASM.md`). Nástroje `leapsh-plugin-init` a `leapsh-compile-plugin`: `docs/TOOLS.md`.

## config.json

| klíč | význam |
|---|---|
| `name` | jedinečné jméno (výchozí je název složky) |
| `version`, `description` | zobrazí se v `plugin list` |
| `type` | `plugin` (výchozí) nebo `theme` |
| `requires` | seznam pluginů, které se musí načíst dřív |
| `platforms` | např. `["termux"]` – jinde se plugin přeskočí (`linux`, `termux`, `any`) |
| `settings` | výchozí nastavení; uživatel je přebije v `config.json` nebo přes `plugin set` |
| `main` | jiný soubor v `src/` než `main.py` |
| `permissions` | informativní seznam oprávnění, která plugin používá (`self.xapi`, viz sekce Oprávnění) |

## API třídy Plugin

| metoda | k čemu |
|---|---|
| `on_load()` / `on_unload()` | životní cyklus; při unload se události, příkazy a segmenty uklidí samy |
| `self.on(událost, fn, priority=0)` | `fn(ev)`; vyšší priorita běží dřív |
| `self.add_command(jméno, fn, nápověda)` | `fn(shell, args) -> int` |
| `self.add_segment(jméno, fn)` | `fn(ctx) -> str`, v tématu jako `{jméno}` |
| `self.add_theme(jméno, dict)` | zaregistruje téma z kódu |
| `self.setting(klíč, výchozí)` / `self.set_setting(klíč, hodnota)` | čtení/zápis nastavení |
| `self.say(text)` | výpis |
| `self.style("bold red")` | ANSI kód |
| `self.provides = [...]` + `self.run_extensions(bod, hodnota, **ctx)` | extension pointy pro addony (viz ADDONS.md) |
| `self.xapi` | XAPI s oprávněními: `xapi.battery()`, `ip()`, `lang()`, `theme()`, `set_conf()` (první použití se zeptá uživatele) |
| `self.shell` | celý shell: `shell.history`, `shell.aliases`, `shell.config`, `shell.run_line(...)`, `shell.executables()` … |

## Události

`ev.name`, `ev.data`, přístup k datům jako atributy (`ev.rc`). `ev.cancel()` zruší výchozí akci, `ev.stop()` zastaví další handlery.
Seznam je v `docs/EVENTS.md` nebo příkazem `events`.

## Editor z klávesových událostí

`ev.editor` nabízí: `insert(text)`, `set_buffer(text, cursor=None)`, `move(pos)`, `submit()`, `print_above(text)`, `bell()` a čtení `buffer`, `cursor`.

## Barvení řádku a nečinnost

- `input_render`: nastav `ev.data["styler"] = fn` – `fn(text)` vrátí text s ANSI barvami (viz `plugins/syntax_highlight`). Barva nesmí měnit délku textu bez escape sekvencí.
- `idle`: spořiče, hodiny, upozornění. Po akci, která trvala dlouho, zavolej `ev.editor.reset_idle()` a `ev.editor.redraw()`.
- Pro celoobrazovkové věci je v `plugins/arcade/src/main.py` hotové `cbreak(fd)`, `alt_screen()` a `swallow_key(fd)`.

## Ladění

`LEAPSH_DEBUG=1 leapsh` vypisuje kompletní tracebacky chyb v pluginech. `evlog on` zapisuje události do souboru.

## Oprávnění (XAPI)

Plugin, který chce číst baterii, IP, jazyk nebo téma, se při prvním použití zeptá uživatele:

```
🛡️ LEAPSH SECURITY  Plugin muj_plugin chce oprávnění: read_battery
Povolit trvale? [Y/n]:
```
Odpověď se uloží do `config.json` (`permissions`). Správa: `plugin perms`, `plugin revoke NÁZEV [oprávnění]`.
Bez terminálu (skript, `-c`) se oprávnění nepovolí a nic se neukládá. V kódu: `self.xapi.battery()`, `.ip()`, `.lang()`, `.theme()`,
`.set_conf(klíč, hodnota)`. XAPI je vázané na konkrétní plugin, takže cizí kód ho nemůže zneužít pod jiným jménem.
Dotaz používá `input()`, proto XAPI nevolej uvnitř události `key` (terminál je tam v raw režimu).

## Vstupní soubor a runtime

- **Python:** vstupním souborem je `"main"` z config.json; bez něj `main.py`, pak `<jméno_pluginu>.py`, pak jediný `.py` v `src/`.
  Je-li jich víc a žádný nesedí, shell napíše, že máš v config.json uvést `"main"`.
- **Runtime:** `"runtime": "python" | "wasm"`; bez něj `.py` v `src/` = Python, jen `.wasm`/`.wat`/`.c`/`.rs` = WASM.
- **Python + WASM dohromady:** `inst = self.load_wasm("fast")` načte `src/fast.wasm` (nebo `fast.wat`) do sandboxu;
  `inst.call("funkce", argumenty…)`.
- Starší manifest `gluesh.json` se pořád načte.

## Nastavení pluginu a další klíče config.json

- `settings` – **výchozí** hodnoty. Uživatel je mění (`plugin set`, `config set plugins.NÁZEV.KLÍČ`) a ukládají se do
  `~/.config/leapsh/plugins/config/<NÁZEV>.json`. V kódu `self.setting("klíč", výchozí)`, `self.settings()`, `self.set_setting(k, v)`.
  Typ nové hodnoty se hlídá podle výchozí (bool, číslo, text, seznam, objekt).
- `settings_info` – popisy klíčů (`plugin settings NÁZEV` je zobrazí).
- `completions` – deklarativní doplňování Tabem (viz `docs/TABCOMPLETE.md`).
- `min_shell` – minimální verze shellu (`"2.3.0"`); starší shell plugin přeskočí a napíše proč.
- `requires`, `platforms`, `extends`, `runtime`, `main`, `wasm`, `commands`, `events`, `segments`, `limits`, `permissions`.
  `leapsh-compile-plugin` upozorní na neznámé klíče (překlepy).

## Ladění a odolnost

- `plugin reload NÁZEV` znovu načte jediný plugin (včetně addonů) – změny kódu i `config.json` se projeví bez restartu.
- Plugin, který v událostech selže 50×, přestane události dostávat (pojistka); `plugin reload NÁZEV` ho oživí.
- Události `config_change` a `plugin_setting_change` umožní pluginu reagovat na změnu nastavení za běhu.
