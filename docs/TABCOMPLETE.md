# Doplňování Tabem

Základ je v editoru: Tab doplní příkaz (na prvním místě) nebo soubor. Při nejednoznačnosti doplní společný začátek, potom ukáže
nabídku; **další Tab prochází kandidáty, Shift-Tab zpět** (`"tab_cycle": false` v config.json to vypne). Plugin `tabcomplete`
podle kontextu kandidáty nahrazuje chytřejšími.

## Co umí

| příkaz | doplňuje |
|---|---|
| `plugin`, `addon`, `theme`, `history`, `config`, `help`, `unalias` | podpříkazy, jména pluginů/motivů/aliasů, klíče a hodnoty nastavení |
| `git` | podpříkazy; větve, tagy a vzdálené větve (z `.git`), remoty u `push/pull/fetch` |
| `pkg`, `apt`, `apt-get` | podpříkazy; názvy balíčků od 2 znaků (z apt seznamů, Termux i Debian) |
| `ssh`, `scp`, `sftp`, `mosh` | hosty z `~/.ssh/config` a `known_hosts` (i `uživatel@host`) |
| `export`, `unset`, `printenv`, `$PROM` | názvy proměnných prostředí |
| `sudo`, `time`, `env`, `nohup`… | přeskočí se a doplňuje se příkaz za nimi |

## Vlastní doplňování bez kódu

Klíč `completions` v `config.json` libovolného pluginu, nebo `specs` v nastavení pluginu `tabcomplete`
(`config set plugins.tabcomplete.specs '{...}'`):

```json
{"mytool":   ["start", "stop"],
 "deploy":   {"1": ["staging", "prod"], "--region": ["eu", "us"], "*": ["--dry-run"]}}
```
Seznam platí pro všechny argumenty. Objekt: klíč `"1"`, `"2"` … = kolikátý argument, `"--region"` = hodnoty za tímto přepínačem,
`"*"` = ostatní pozice.

## Vlastní poskytovatel (Python)

Addon přidá poskytovatele přes extension point `tab_providers`:

```python
from leapsh.api import Addon

class MojeDoplnovani(Addon):
    def on_load(self):
        self.extend("tab_providers", self.pridej)

    def pridej(self, providers, **ctx):
        providers["mytool"] = lambda c: ["start", "stop"] if c.n == 1 else None
        return providers
```
`ctx` poskytovatele: `n` (kolikátý argument se píše), `words` (slova příkazu před rozepsaným), `word`, `cmd`, `cwd`, `shell`.
Vrátí-li poskytovatel `None`, použije se výchozí doplňování souborů. Ladění: `tabcomplete 'mytool st'`.

## Nastavení

`plugin set tabcomplete ignore_case true` doplňuje bez ohledu na velikost písmen (`cat dok<Tab>` → `Dokument.txt`).

## Událost complete

Vlastní plugin může na událost `complete` reagovat sám: `ev.word`, `ev.left` (text před kurzorem), `ev.first` (příkaz na začátku),
`ev.editor`, `ev.data["candidates"]` (seznam, který lze měnit).
