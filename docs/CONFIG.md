# Konfigurace

## Soubory v ~/.config/leapsh/

| cesta | co to je |
|---|---|
| `config.json` | hlavní nastavení shellu |
| `history` | historie (jeden příkaz na řádek, práva 600) |
| `rc` | startovací soubor: příkazy, které se spustí při startu interaktivního shellu |
| `plugins/<název>/` | tvoje pluginy (`config.json` + `src/`) |
| `plugins/config/<název>.json` | **nastavení pluginů** (jeden soubor na plugin, jen hodnoty, které jsi změnil) |
| `addons/<název>/` | tvoje addony |
| `plugins-dev/` | pluginy načítané jen s `leapsh --dev` |

Složky `config` a `data` v `plugins/` jsou rezervované (nelze je použít jako název pluginu).

## config.json (hlavní)

| klíč | výchozí | význam |
|---|---|---|
| `theme` | `rounded` | aktivní téma |
| `aliases` | `{ll, la, ls, grep, c}` | aliasy |
| `disabled` | `["highlight_rainbow"]` | vypnuté pluginy (spravuje `plugin enable/disable`) |
| `history_size` / `history_dedupe` / `history_file` | `5000` / `true` / – | historie |
| `termux` | `{"auto": true, …}` | detekce Termuxu a Termux:API (zapisuje shell sám) |
| `warn_not_termux` | `true` | hlášení při startu mimo Termux |
| `startup_msg` | `true` | hlavička při startu |
| `tab_cycle` | `true` | opakovaný Tab prochází nabídku |
| `lang` | `cs` | jazyk (čte ho XAPI) |
| `permissions` | `{}` | udělená oprávnění pluginům (`plugin perms`) |

## Příkaz config

| příkaz | co dělá |
|---|---|
| `config` | zobrazí config.json (barevně) |
| `config keys [TEXT]` | známé klíče s typem, hodnotou a popisem (`*` = změněno oproti výchozímu) |
| `config get KLÍČ` | hodnota (tečková cesta: `termux.auto`, `aliases.ll`); `config KLÍČ` je zkratka |
| `config set KLÍČ [na\|to\|=] HODNOTA` | změní hodnotu, typ se hlídá, změna platí hned |
| `config toggle KLÍČ` | přepne true/false (i u nastavení pluginů) |
| `config add KLÍČ HODNOTA…` / `config remove …` | přidá/odebere položky seznamu (`config add disabled pet`) |
| `config unset KLÍČ` / `config reset KLÍČ` | smaže klíč / vrátí výchozí hodnotu |
| `config diff` | co se liší od výchozího stavu (`+` přidáno, `~` změněno, `-` chybí) |
| `config validate` | zkontroluje typy, existenci tématu a pluginů v `disabled`, typy nastavení pluginů |
| `config undo` | vrátí poslední změnu; druhé `undo` ji vrátí zpět |
| `config export [SOUBOR\|-]` | záloha config.json **i nastavení všech pluginů** do jednoho JSON |
| `config import SOUBOR [--merge]` | obnoví ze zálohy (bez `--merge` nahradí, s ním sloučí); jde vrátit přes `undo` |
| `config plugins [PLUGIN]` | nastavení pluginů (obsah `plugins/config/`) |
| `config path` / `config edit` | umístění souborů / otevře v `$EDITOR` a znovu načte |

**Typová kontrola:** `true/false` (i `ano/ne/on/off/1/0`), číslo musí být číslo, text zůstane textem
(`config set theme true` nastaví téma „true“, které neexistuje, takže se odmítne), seznam a objekt chtějí JSON
(v apostrofech: `'["a","b"]'`).

**Ochrana před překlepy:** `config set histroy_size 10` se odmítne a nabídne `history_size`. Vlastní klíče, které nic nepřipomínají,
projdou; podobný název si vynutíš přes `--force`.

**Zálohy:** před každou změnou se uloží předchozí `config.json` do `config.json.bak`. `config undo` ji vrací (jedna úroveň).

**Okamžité použití:** téma, aliasy, historie a vypnuté pluginy se projeví hned. Každá změna vyvolá událost `config_change`
(`key`, `old`, `new`), změna nastavení pluginu `plugin_setting_change` (`plugin`, `key`, `old`, `new`).

Klíč `plugins.NÁZEV.KLÍČ` mění nastavení pluginu: `config set plugins.cmd_timer.threshold 5` je totéž co `plugin set cmd_timer threshold 5`.

## Starší verze

Nastavení pluginů bylo dřív v `config.json` pod klíčem `settings`. Při prvním startu se přesune do `plugins/config/` a z `config.json` zmizí.
Data ze složek `~/.config/boltsh`, `~/.config/gluesh` a `~/.config/plush` se při prvním startu převezmou.
