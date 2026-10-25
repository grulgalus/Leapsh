;; WASM plugin pro leapsh (ABI v1). Úpravy sestavíš příkazem:  leapsh-compile-plugin .
;; Příkaz __NAME__ pozdraví, událost command_after počítá příkazy, segment {__NAME__} v promptu ukáže počet.
(module
  (import "leapsh" "say"    (func $say (param i32 i32)))
  (import "leapsh" "result" (func $result (param i32 i32)))
  (memory (export "memory") 1)

  ;; paměť: 0..3 počítadlo, 64.. text, 160 konec bufferu pro číslo, od 256 halda
  (data (i32.const 64) "Ahoj z WASM pluginu!")          ;; 20 bajtů
  (global $heap (mut i32) (i32.const 256))

  ;; alokátor pro řetězce, které shell předává modulu (uvolňuje je v opačném pořadí => stačí zásobník)
  (func (export "leapsh_alloc") (param $n i32) (result i32)
    (local $p i32)
    (local.set $p (global.get $heap))
    (global.set $heap (i32.add (local.get $p) (i32.and (i32.add (local.get $n) (i32.const 7)) (i32.const -8))))
    (local.get $p))
  (func (export "leapsh_free") (param $p i32) (param $n i32)
    (if (i32.eq (i32.add (local.get $p) (i32.and (i32.add (local.get $n) (i32.const 7)) (i32.const -8)))
                (global.get $heap))
      (then (global.set $heap (local.get $p)))))

  ;; událost: jméno a JSON data jsou v paměti; vrať 0 (pokračuj) nebo 1 (zruš událost)
  (func (export "leapsh_event") (param $np i32) (param $nl i32) (param $dp i32) (param $dl i32) (result i32)
    (i32.store (i32.const 0) (i32.add (i32.load (i32.const 0)) (i32.const 1)))
    (i32.const 0))

  ;; příkaz: návratový kód = výstupní kód příkazu
  (func (export "leapsh_command") (param $np i32) (param $nl i32) (param $ap i32) (param $al i32) (result i32)
    (call $say (i32.const 64) (i32.const 20))
    (i32.const 0))

  ;; segment promptu: číslo -> text -> result()
  (func $utoa (param $n i32) (result i32)
    (local $p i32)
    (local.set $p (i32.const 160))
    (loop $l
      (local.set $p (i32.sub (local.get $p) (i32.const 1)))
      (i32.store8 (local.get $p) (i32.add (i32.const 48) (i32.rem_u (local.get $n) (i32.const 10))))
      (local.set $n (i32.div_u (local.get $n) (i32.const 10)))
      (br_if $l (local.get $n)))
    (local.get $p))
  (func (export "leapsh_segment") (param $np i32) (param $nl i32) (result i32)
    (local $p i32)
    (local.set $p (call $utoa (i32.load (i32.const 0))))
    (call $result (local.get $p) (i32.sub (i32.const 160) (local.get $p)))
    (i32.const 0))
)
