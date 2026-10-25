# Nástroje pro autory pluginů

Dva skripty v `tools/` (po `./install.sh` jsou v PATH jako `leapsh-plugin-init` a `leapsh-compile-plugin`). Existují jako
`.py` i `.sh` (obal, který zavolá Python); stejné funkce jsou v shellu jako `plugin create`, `plugin compile`, `plugin install`.

## leapsh-plugin-init

```
leapsh-plugin-init NÁZEV [--type plugin|addon|theme] [--runtime python|wasm] [--lang wat|c] [--extends PLUGIN] [--dir SLOŽKA]
```
Vytvoří `NÁZEV/config.json` + `NÁZEV/src/…` (výchozí umístění `~/.config/leapsh/plugins`, u addonu `addons`).
WASM plugin ve WAT se rovnou sestaví, takže funguje okamžitě.

## leapsh-compile-plugin

```
leapsh-compile-plugin [SLOŽKA] [-o VÝSTUP] [--no-pack] [--no-source] [--install] [--force]
```
1. zkontroluje `config.json` (název, typ, runtime, addon musí mít `extends`);
2. **Python:** zkontroluje syntaxi všech `src/**/*.py` a že `main.py` obsahuje třídu odvozenou od `Plugin`/`Addon`;
3. **WASM:** sestaví `src/plugin.wasm` ze `plugin.wat` (vestavěný assembler), `plugin.c` (clang) nebo `plugin.rs` (rustc),
   ověří exporty podle manifestu a že modul importuje jen `leapsh.*` z ABI;
4. zabalí do `NÁZEV-VERZE.leapsh` (zip se složkou pluginu; `--no-source` vynechá zdroje WASM pluginu).
Návratový kód 0 = v pořádku, 1 = chyba (použitelné v CI).

## Balíček .leapsh a instalace

`plugin install BALÍČEK.leapsh` (nebo `--install` u kompilátoru) rozbalí balíček do `~/.config/leapsh/plugins` (addon do `addons`),
zkontroluje cesty (žádné `..`) a manifest, existující plugin přepíše jen s `--force`. Pak `reload`.

**Bezpečnost:** Python plugin v balíčku je normální kód s plnými právy uživatele – instaluj jen důvěryhodné. WASM plugin je
v sandboxu a může jen to, co nabízí ABI.
