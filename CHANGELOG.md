# Changelog

## 2.3.0 – leapsh
- **Přejmenováno na leapsh** = Lightning-fast Event-driven Add-on & Plugin SHell (alias `lsh`). Data ze starých složek se převezmou.
- **Nastavení pluginů** v `~/.config/leapsh/plugins/config/<plugin>.json` (dřív v `config.json`; migrace automaticky), typová kontrola,
  `plugin set/unset/settings`, události `config_change` a `plugin_setting_change`.
- **Příkaz `config`**: zobrazí, `get`, `set` (hlídá typ, použije hned), `toggle`, `add`/`remove` (seznamy), `unset`, `reset`, `keys` (popisy klíčů),
  `diff`, `validate`, `undo`, `export`/`import` (včetně nastavení pluginů), `plugins`, `path`, `edit`; ochrana před překlepy v klíčích; klíč `plugins.NÁZEV.KLÍČ`.
- **Plugin `tabcomplete`** (+ addon `tabcomplete_extra`): git větve, pkg/apt, ssh, `$PROMĚNNÉ`, config, deklarativní `completions`, vlastní specifikace,
  extension point `tab_providers`. Editor: opakovaný Tab prochází nabídku, Shift-Tab zpět, adresáře modře.
- **Plugin systém:** `plugin reload NÁZEV`, `min_shell`, pojistka proti pluginu, který pořád padá, `settings_info`, kontrola neznámých klíčů.

## 2.2.0 – leapsh
- **Přejmenováno na leapsh** (bolt = blesk i šroub), alias `lsh`. Data ze `~/.config/gluesh` se při prvním startu převezmou.
- **Rychlost:** start 84 → ~48 ms; jednoduché příkazy přes `posix_spawn` bez bashe; stav (`cd`/`export`) se zachytává jen když je
  potřeba; líné importy těžkých modulů; `git status` na pozadí; bytecode vestavěných pluginů; v hlavičce se ukazuje čas startu.
- **Termux:** detekce Termuxu (`pkg`, proměnné) a Termux:API se zapisuje do `config.json` (`termux.available/api/api_working`);
  v Termuxu bez API a mimo Termux shell při startu napíše, co chybí; příkaz `doctor`.
- **Historie** `~/.config/leapsh/history`: Ctrl-R, PageUp/PageDown, `!!` `!$` `!N` `!text`, `history -s/-d/-c`, bez duplicit, práva 600.
- **Pluginy:** manifest `config.json`; vstupní `.py` i WASM modul se můžou jmenovat libovolně; runtime se pozná sám;
  Python plugin může volat WASM (`self.load_wasm`).
- Nové: `autocd`, `z` (jump), kontextové doplňování Tabem (`plugin enable <Tab>`), startovací soubor `rc`, `doctor`, výchozí barevné aliasy.

## 2.1.0
- **WASM pluginy** (`"runtime": "wasm"`): vlastní interpret v čistém Pythonu, sandbox s limitem instrukcí a paměti,
  ABI v1 (`docs/WASM.md`). Číselné instrukce ověřeny proti V8.
- **WAT assembler** ve standardní knihovně: WASM plugin jde napsat a sestavit bez jakýchkoli nástrojů.
- **leapsh-plugin-init** a **leapsh-compile-plugin** (`.py` i `.sh`), balíčky `.leapsh`, `plugin compile/install`.
- Úklid: sjednocené názvy (`toolbox`, `themes_extra`, motivy rounded/mono/grid, příkaz `cmds`), odstraněny zbytky starých projektů.

## 2.0.0 – leapsh
- Nový název: leapsh (glue + sh), alias `lsh`.
- Nový formát pluginů: složka + `config.json` + kód v `src/` (balíček, relativní importy, bez `.pyc`); platí i pro addony a témata.
- Sloučení dvou shellů do jednoho: XAPI s oprávněními, telemetrie `{perf}`, témata jako funkce, balíčky témat, heredoc, `--dev`, `q`,
  příkazy `py`, `ai`, `gfetch`, autocorrect.
- Příkazy v řetězu (`a; b && c`) mají každý vlastní události a hooky.

## 1.1.0
- Mazlíček, achievementy, zvýrazňování syntaxe, hry (snake, train, matrix), spořič, tipy při startu.

## 1.0.0
- Shell s pluginy postavenými na událostech, témata jako pluginy, addony, Linux i Termux.
