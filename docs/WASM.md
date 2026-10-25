# WASM pluginy

Plugin může být napsaný v čemkoli, co se přeloží do WebAssembly (WAT, C, Rust, …). leapsh ho spouští ve vlastním interpretu
(`leapsh/wasm.py`, čistý Python, žádné závislosti → funguje v Termuxu). Modul je v **sandboxu**: nevidí soubory, síť ani proměnné
prostředí, jen to, co mu shell nabídne přes importy `leapsh.*`. Běží s limity: počet zpětných skoků a volání (`fuel`) a paměť.
Nekonečná smyčka nebo past (dělení nulou, přístup mimo paměť) plugin nezastaví shell: chyba se vypíše a shell jede dál.

## Manifest

```json
{
  "name": "pocitadlo", "version": "0.1.0", "type": "plugin",
  "runtime": "wasm", "wasm": "plugin.wasm",
  "commands": {"pocitadlo": "ukáže počet příkazů"},
  "events": ["command_after"],
  "segments": ["pocitadlo"],
  "limits": {"fuel": 2000000, "memory_pages": 16}
}
```
Soubor `src/plugin.wasm` vzniká z `src/plugin.wat` / `plugin.c` / `plugin.rs` příkazem `leapsh-compile-plugin`.
(Když existuje jen `plugin.wat`, shell ho při načtení sestaví sám.)

## ABI v1

**Co modul exportuje**

| export | podpis | popis |
|---|---|---|
| `memory` | – | povinný |
| `leapsh_alloc` | `(size) -> ptr` | povinný, když se předávají řetězce (události, příkazy, segmenty) |
| `leapsh_free` | `(ptr, size)` | volitelný; shell uvolňuje v opačném pořadí, než alokoval, takže stačí zásobníkový alokátor |
| `leapsh_on_load` / `leapsh_on_unload` | `()` | volitelné |
| `leapsh_event` | `(name_ptr, name_len, json_ptr, json_len) -> i32` | pro události z `events`; `0` = pokračuj, `1` = zruš (`ev.cancel()`) |
| `leapsh_command` | `(name_ptr, name_len, args_ptr, args_len) -> i32` | pro příkazy z `commands`; `args` je JSON pole řetězců; návratová hodnota = výstupní kód |
| `leapsh_segment` | `(name_ptr, name_len) -> i32` | pro segmenty z `segments`; text vrať přes `result()` |

Řetězce jsou UTF-8. Data události jsou JSON objekt jen z jednoduchých hodnot (řetězce, čísla, bool), např.
`{"line": "ls", "command": "ls", "rc": 0, "duration": 0.01}`.

**Co smí modul importovat** (modul `leapsh`)

| import | podpis | popis |
|---|---|---|
| `say` | `(ptr, len)` | vypíše text |
| `warn` | `(ptr, len)` | vypíše varování (stderr) |
| `result` | `(ptr, len)` | nastaví návratový text: u segmentu text segmentu; u události `command_before` nový řádek příkazu; u `prompt_render` nový prompt |
| `setting_int` | `(key_ptr, key_len, default) -> i32` | nastavení pluginu (`plugin set jmeno klíč 5`) |
| `time_ms` | `() -> i64` | čas v ms |

Jiný import = chyba při načtení (kontroluje to i `leapsh-compile-plugin`).

## Příklad ve WAT (celé šablona: `leapsh-plugin-init muj --runtime wasm`)

```wat
(module
  (import "leapsh" "say" (func $say (param i32 i32)))
  (memory (export "memory") 1)
  (data (i32.const 64) "Ahoj z WASM!")
  (func (export "leapsh_command") (param i32 i32 i32 i32) (result i32)
    (call $say (i32.const 64) (i32.const 12))
    (i32.const 0)))
```

## Příklad v C (bez libc)

```c
#include "leapsh.h"
LEAPSH_EXPORT("leapsh_command") int leapsh_command(const char *n, int nl, const char *a, int al) {
    leapsh_say("Ahoj z C!", 9);
    return 0;
}
```
Sestavení: `leapsh-compile-plugin .` volá `clang --target=wasm32 -nostdlib -O2 -Wl,--no-entry -Wl,--allow-undefined`
(Termux: `pkg install clang lld`).

## Podporováno a nepodporováno

Podporováno: celé WebAssembly MVP, sign-extension, saturating trunc, bulk memory (`memory.copy/fill/init`), multi-value, tabulky
a `call_indirect`, importované funkce. Číselné instrukce jsou ověřené proti V8.
Nepodporováno: WASI, SIMD, vlákna, reference types, importované tabulky. Validace modulu je minimální – bezpečnost zajišťuje sandbox
a limity, ne validátor. Interpret je v Pythonu, takže je řádově pomalejší než nativní runtime; na události, příkazy a segmenty stačí.

## Ladění

`LEAPSH_DEBUG=1 leapsh` vypisuje plné tracebacky. `plugin info jmeno` ukáže příkazy, segmenty a události modulu.
