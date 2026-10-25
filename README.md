# leapsh – bleskový shell s pluginy

**LEAPSH** je zkratka: **L**ightning-fast **E**vent-driven **A**dd-on & **P**lugin **SH**ell
(bleskový shell řízený událostmi, s pluginy a addony – psanými v Pythonu i ve WASM).

| písmeno | význam | v praxi |
|---|---|---|
| **L** | Lightning-fast | start ~50 ms, jednoduché příkazy bez bashe, líné importy |
| **E** | Event-driven | pluginy se věší na události: psaní, klávesy, příkazy, změna složky, nečinnost… |
| **A** | Add-on | addony rozšiřují existující pluginy (extension pointy, `wrap()`, úpravy témat) |
| **P** | Plugin | pluginy v Pythonu nebo WASM (sandbox), témata jsou taky pluginy |
| **SH** | SHell | shell pro Linux a Termux |

*Leap* znamená skok: rychle vpřed, a taky skáče po složkách (`z`). Krátký alias: `lsh`.

Python, žádné závislosti. Všechno se dá rozšířit pluginy, které se věší na **události**. **Témata** jsou taky pluginy a **addony**
jsou doplňky existujících pluginů. Plugin může být **Python** nebo **WASM**, nebo obojí dohromady.

## Rychlý start

```sh
# Termux (nainstaluje python, git, termux-api a leapsh)
sh termux/termux-setup.sh

# Linux
./install.sh

leapsh        # nebo krátce: lsh
```
Vyzkoušet bez instalace: `./bin/leapsh`. Jako výchozí shell při startu terminálu: `./install.sh --default-shell`
(pojistka: když leapsh spadne, zůstaneš v bashi; vypnutí `LEAPSH_SKIP=1 bash`).
Při prvním spuštění se jednorázově převezme historie a nastavení ze staré složky `~/.config/gluesh`, pokud existuje.

## Termux a Termux:API

Při každém startu shell zjistí, kde běží, a zapíše to do `~/.config/leapsh/config.json`:
```json
"termux": {"available": true, "api": true, "api_working": true}
```
- `available`: jsme v Termuxu (proměnné Termuxu, nebo příkaz `pkg` v Termuxu),
- `api`: je nainstalovaný balíček `termux-api`,
- `api_working`: aplikace **Termux:API** opravdu odpovídá (ověřuje se na pozadí, start nezdržuje).

V Termuxu bez API shell při startu napíše, jak to opravit (`pkg install termux-api` + aplikace z F-Droidu), a aby měl všechny funkce
(baterie, notifikace, vibrace). **Mimo Termux** napíše, že funkce jen pro Termux nebudou dostupné, a všechno ostatní funguje.
Vypnout hlášení: `"warn_not_termux": false`. Vypnout automatiku a nastavit ručně: `"termux": {"auto": false, "available": true, ...}`.
Diagnostika kdykoli: příkaz `doctor`.

## Kde jsou soubory

```
~/.config/leapsh/
├── config.json              hlavní nastavení (téma, aliasy, termux, historie…)  → příkaz `config`
├── history                  historie příkazů
├── rc                       startovací soubor (příkazy při startu)
├── plugins/                 TVOJE pluginy (jedna složka na plugin: config.json + src/)
│   └── config/              NASTAVENÍ pluginů: jeden soubor na plugin, např. cmd_timer.json
└── addons/                  tvoje addony
```
Vestavěné pluginy jsou v adresáři instalace; plugin stejného jména v `~/.config/leapsh/plugins/` je přebije.
`plugin create` a `plugin install` ukládají do `~/.config/leapsh/plugins/`. Jiné umístění: `LEAPSH_HOME=/cesta`.

## Příkaz `config`

```sh
config                                    # zobrazí config.json
config get termux.available               # hodnota (tečková cesta)
config set theme dracula                  # změní a hned použije (typ se hlídá: true/false, čísla, text, JSON)
config set history_size na 2000           # „na“, „to“ nebo „=“ jako oddělovač jsou volitelné
config set aliases.gs git status -sb      # nový alias
config set plugins.cmd_timer.threshold 5  # nastavení pluginu (ukládá se do plugins/config/cmd_timer.json)
config toggle startup_msg                 # přepne true/false
config add disabled pet                   # přidá do seznamu (plugin se hned vypne)
config unset aliases.gs   ·   config reset history_size
config keys                               # všechny klíče s popisem   ·   config diff  = co jsem změnil
config validate                           # zkontroluje typy a hodnoty
config undo                               # vrátí poslední změnu (znovu = zpět)
config export zaloha.json   ·   config import zaloha.json [--merge]   # záloha i nastavení pluginů
config path   ·   config plugins   ·   config edit
```
JSON s uvozovkami dej do apostrofů: `config set moje.pole '["a","b"]'`. Špatný typ se odmítne
(`config set history_size abc` → „očekávám celé číslo“), překlep v názvu klíče taky (`histroy_size` → „myslel jsi history_size?“).
Tab doplňuje klíče i hodnoty.

## Tab doplňování (plugin `tabcomplete`)

- `plugin enable <Tab>` jména pluginů, `config set <Tab>` klíče, `theme set <Tab>` motivy, `config set startup_msg <Tab>` true/false.
- `git checkout <Tab>` větve a tagy (čte `.git` přímo, bez volání gitu), `git push <Tab>` remoty, `pkg install ne<Tab>` balíčky
  (z apt seznamů), `ssh <Tab>` hosty z `~/.ssh/config` a `known_hosts`, `echo $HO<Tab>` proměnné, `sudo git st<Tab>`.
- **Opakovaný Tab** prochází nabídku, **Shift-Tab** zpět. Adresáře jsou v nabídce modře.
- Vlastní doplňování bez kódu: `config set plugins.tabcomplete.specs '{"mytool":["start","stop"]}'` nebo klíč
  `"completions"` v `config.json` libovolného pluginu. `ignore_case` doplňuje bez ohledu na velikost písmen.
- Addony přidávají další nástroje (`tabcomplete_extra`: docker, npm, pip, cargo, systemctl). `tabcomplete 'git ch'` ukáže, co by se nabídlo.
- Podrobně: `docs/TABCOMPLETE.md`.

## Plugin = složka + `config.json` + `src/`

```
muj_plugin/
├── config.json      manifest (název, verze, popis, výchozí nastavení)
└── src/             veškerý kód, soubory se můžou jmenovat libovolně
    ├── muj_plugin.py   Python (nebo main.py; víc souborů? v config.json: "main": "soubor.py")
    ├── fast.wasm       WASM modul (nebo .wat / .c / .rs, které sestaví leapsh-compile-plugin)
    └── pomocnik.py     další kód: `from .pomocnik import neco`
```
Nastavení pluginu (`"settings"` = výchozí hodnoty) si uživatel mění přes `plugin set` / `config set plugins.…`; ukládá se do
`~/.config/leapsh/plugins/config/<plugin>.json`. Další klíče: `settings_info` (popisy), `completions`, `min_shell`, `requires`, `platforms`.

Runtime se pozná sám: v `src/` je `.py` = Python, jen `.wasm`/`.wat`/`.c` = WASM (nebo explicitně `"runtime"` v config.json).
Python plugin může volat WASM: `inst = self.load_wasm("fast"); inst.call("sum", 1, 2)`.

```sh
leapsh-plugin-init ahoj                              # Python plugin
leapsh-plugin-init ahoj --runtime wasm               # WASM plugin ve WAT (sestaví se hned, bez nástrojů)
leapsh-plugin-init ahoj --runtime wasm --lang c      # WASM plugin v C (clang + lld)
leapsh-plugin-init muj_addon --type addon --extends git_prompt
leapsh-compile-plugin ahoj                           # kontrola + sestavení + balíček ahoj-0.1.0.leapsh
```
V shellu totéž: `plugin create ahoj [--wasm|--c|--theme]`, `plugin compile CESTA`, `plugin install BALÍČEK.leapsh`.

```python
# src/ahoj.py  (Python plugin)
from leapsh.api import Plugin

class Ahoj(Plugin):
    def on_load(self):
        self.on("command_after", self.after)           # událost
        self.add_command("ahoj", self.cmd, "pozdrav")  # příkaz
        self.add_segment("ahoj", lambda ctx: "👋")     # {ahoj} v promptu

    def after(self, ev):
        if ev.rc != 0:
            self.say(f"příkaz selhal s kódem {ev.rc}")

    def cmd(self, shell, args):
        shell.say("ahoj!")
        return 0
```
WASM pluginy a jejich ABI: `docs/WASM.md`. Nástroje: `docs/TOOLS.md`. Starší manifest `gluesh.json` se pořád načte.

## Co umí

- **Rychlost:** start ~50 ms (Python sám ~11 ms), jednoduché příkazy bez bashe přes `posix_spawn`, stav (`cd`, `export`) se zachytává
  jen tam, kde je potřeba, `git status` v promptu běží na pozadí, předkompilovaný bytecode vestavěných pluginů.
- **Historie** v `~/.config/leapsh/history` (práva 600, bez duplicit, sbalí se sama): ↑↓, **Ctrl-R** hledání, PageUp/PageDown
  podle začátku řádku, `!!`, `!$`, `!N`, `!text`, příkaz `history` (`-s hledat`, `-d smazat`, `-c`).
- Řádkový editor: šipky, Home/End, Ctrl+A/E/U/K/W, Tab (příkazy, soubory, **jména pluginů a témat**), heredoc (`cat <<EOF`).
- Příkazy běží přes bash/sh: roury, `&&`, přesměrování, globy; `cd` a `export` se pamatují.
- Startovací soubor `~/.config/leapsh/rc` (aliasy, `export`, `theme set` …), `autocd` (napiš jen `projekty`), `z projekty` (skákání po složkách).
- Pád pluginu shell neshodí. Záchranný režim: `leapsh --no-plugins`, vývojářský: `leapsh --dev`, bez rc: `--norc`.
- Oprávnění pro pluginy (XAPI): číst baterii, IP… až po schválení (`plugin perms`).
- WASM pluginy v sandboxu: bez souborů a sítě, s limitem instrukcí a paměti.

## Příkazy

| příkaz | co dělá |
|---|---|
| `help`, `cmds`, `doctor` | nápověda / tabulka příkazů / diagnostika (Termux, API, historie, pluginy) |
| `config [get\|set\|unset\|reset\|path\|plugins\|edit]` | zobrazí a mění konfiguraci |
| `history [N\|all]`, `history -s TEXT`, `-d Č`, `-c`, `--path` | historie |
| `plugin list / info X / enable X / disable X` | správa pluginů (platí hned, bez restartu) |
| `plugin reload [X]` | znovu načte jeden plugin (i s addony) nebo všechny |
| `plugin set X klíč hodnota` / `unset` / `settings X` | nastavení pluginu (typ se hlídá) |
| `plugin create N [--theme\|--wasm\|--c]` | kostra pluginu |
| `plugin compile CESTA` / `plugin install BALÍČEK` | kontrola, sestavení, balíček `.leapsh` / instalace |
| `plugin perms [X]` / `plugin revoke X [oprávnění]` | oprávnění pluginů |
| `addon list / create jmeno cíl` | addony |
| `theme list / set X / preview / new X` | témata |
| `z ČÁST`, `z -l` | skok do navštívené složky |
| `events` | všechny události a počet handlerů |
| `py KÓD`, `ai DOTAZ`, `gfetch` | Python v shellu, cht.sh, info o systému |
| `alias`, `unalias`, `reload`, `leapsh`, `exit`/`q` | základ |

## Vestavěné pluginy

| plugin | popis |
|---|---|
| `git_prompt` | segmenty `{git}` a `{git_box}` (větev, změny; `git status` na pozadí) |
| `cmd_timer` | po pomalém příkazu vypíše čas; `{last_time}` |
| `autosuggest` | šedý návrh z historie, přijmeš ho → nebo End |
| `syntax_highlight` | barvy při psaní (příkaz zelený, neexistující červený…) |
| `tabcomplete` | chytré doplňování Tabem (git, pkg, ssh, config, specifikace) |
| `autocorrect` | opravy překlepů: `sl` → `ls`, `gti` → `git`… |
| `autocd` | napsaná složka = `cd` |
| `jump` | `z` – skákání po složkách podle četnosti a čerstvosti |
| `did_you_mean` | „Myslel jsi: …“ |
| `keybinds` | vlastní zkratky: `bind ctrl-g git status -sb` |
| `pet` | mazlíček `{pet}` v promptu (`pet`, `pet feed`) |
| `achievements` | 11 trofejí |
| `arcade` | `snake`, `train`, `matrix` + spořič po nečinnosti |
| `toolbox` | `cmds`, `py`, `ai`, `gfetch` |
| `motd` | tip při startu |
| `event_logger` | ladění: `evlog on` |
| `termux_extras` | jen Termux: `{battery}`, `battery`, `tnotify` |
| `themes_extra` | rounded (výchozí), hacker, mono, cyberpunk, grid |
| `theme_classic / neon / minimal / dracula` | další témata |

Addony: `tabcomplete_extra`, `git_prompt_stash`, `cmd_timer_notify`, `neon_clock`, `pet_hat`, `achievements_notify`,
`highlight_rainbow` (ve výchozím stavu vypnutý), `termux_haptics` (jen Termux).

## Struktura projektu

```
leapsh/       jádro (shell, editor, události, loader, API, XAPI, WASM interpret, WAT assembler, devtools, env_check)
plugins/      vestavěné pluginy a témata   (každý: config.json + src/)
addons/       vestavěné addony             (každý: config.json + src/)
templates/    šablony: plugin, addon, theme, wasm-wat, wasm-c
tools/        leapsh-plugin-init, leapsh-compile-plugin (.py i .sh)
examples/     ukázkový plugin + addon
tests/        python3 -m unittest discover -s tests
docs/         PLUGINS, WASM, TOOLS, ADDONS, EVENTS, THEMES, TERMUX
termux/       instalace a klávesy pro Termux
bin/          leapsh, lsh
```
Uživatelské věci jsou v `~/.config/leapsh/{plugins,addons,plugins-dev}` a přebíjejí vestavěné se stejným jménem.
Jiné umístění: `LEAPSH_HOME=/cesta`.

## Omezení

- Víceřádkové konstrukce kromě heredocu (`for … do … done` přes víc řádků) a široké znaky (CJK) editor zatím nezvládá.
- Příkazy leapsh uvnitř `$( )` nebo `{ }` se předají bashi, který je nezná.
- Ctrl-Z (job control) není; `&` na pozadí funguje přes bash.
- WASM interpret je v čistém Pythonu (~5 milionů instrukcí/s): na události, příkazy a segmenty promptu to stačí, na výpočty ne.
  Addony zatím jen v Pythonu.
