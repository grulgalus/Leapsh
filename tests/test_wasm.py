"""WASM interpret a WAT assembler. Číselné instrukce se porovnávají se skutečným V8 (node), pokud je k dispozici."""
import itertools
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from leapsh.wasm import Instance, Trap, WasmError, _BIN_BY_NAME, _UN_BY_NAME, FC_OPCODES, OPCODES  # noqa: E402
from leapsh.wat import WatError, assemble  # noqa: E402
import wasm_node  # noqa: E402

INTS = [0, 1, 2, 3, 5, 7, 31, 32, 33, 63, 64, 100, 255, 256, 65535, -1, -2, -5, 12345678, -12345678,
        0x7FFFFFFF, -0x80000000]
BIG = [0x7FFFFFFFFFFFFFFF, -0x8000000000000000, 1 << 32, (1 << 32) - 1, -(1 << 32), 0x123456789ABCDEF]
FLOATS = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, 2.5, -2.5, 3.7, -3.7, 100.0, 1e10, -1e10, 1e30, 3.4e38,
          1e-40, 16777217.0, 4294967296.0, 2147483648.0, -2147483648.0, 2147483647.0, 9.3e18, 1.8e19, -9.3e18,
          math.inf, -math.inf, math.nan]
VALUES = {"i32": INTS, "i64": INTS + BIG, "f32": FLOATS, "f64": FLOATS}
CMP = ("eq", "ne", "lt", "gt", "le", "ge")


def signature(name):
    t, op = name.split(".")
    if op == "eqz" or op.split("_")[0] in CMP:
        return ([t] if op == "eqz" else [t, t]), "i32"
    if op.startswith("trunc_"):
        src = op.split("_")[2] if op.startswith("trunc_sat") else op.split("_")[1]
        return [src], t
    if op.startswith("convert_"):
        return [op.split("_")[1]], t
    if op == "wrap_i64":
        return ["i64"], "i32"
    if op.startswith("extend_"):
        return [op.split("_")[1]], "i64"
    if op == "demote_f64":
        return ["f64"], "f32"
    if op == "promote_f32":
        return ["f32"], "f64"
    if op.startswith("reinterpret_"):
        return [op.split("_")[1]], t
    if op.startswith("extend"):
        return [t], t
    if op in ("clz", "ctz", "popcnt", "abs", "neg", "ceil", "floor", "trunc", "nearest", "sqrt"):
        return [t], t
    return [t, t], t


def wat_name(n):
    return n.replace(".", "_")


def all_ops():
    names = [n for n in _BIN_BY_NAME if n in OPCODES] + [n for n in _UN_BY_NAME if n in OPCODES or n in FC_OPCODES]
    return sorted(set(names))


def module_for(ops):
    fns = []
    for n in ops:
        params, res = signature(n)
        ps = " ".join(f"(param {t})" for t in params)
        args = " ".join(f"(local.get {i})" for i in range(len(params)))
        fns.append(f'(func (export "{wat_name(n)}") {ps} (result {res}) ({n} {args}))')
    return "(module " + " ".join(fns) + ")"


class TestAgainstV8(unittest.TestCase):
    @unittest.skipUnless(wasm_node.NODE, "node není k dispozici")
    def test_every_numeric_op_matches_v8(self):
        ops = all_ops()
        wasm = assemble(module_for(ops))
        inst = Instance(wasm)
        calls, spec = [], []
        for n in ops:
            params, res = signature(n)
            combos = itertools.product(*[VALUES[t] for t in params])
            if len(params) == 2 and params[0] in ("i64", "f32", "f64"):
                combos = itertools.islice(combos, 0, None, 3)         # méně kombinací pro velké množiny
            for c in combos:
                args = [(t, v) for t, v in zip(params, c)]
                calls.append((wat_name(n), args, res))
                spec.append((n, c, res))
        expected = wasm_node.run_node(wasm, calls)
        self.assertEqual(len(expected), len(calls))
        bad = []
        for (name, args, res), (n, c, _), exp in zip(calls, spec, expected):
            try:
                got = ("ok", wasm_node.enc_result(inst.call(name, *[v for _, v in args]), res))
            except Trap:
                got = ("trap", "")
            if got[0] != exp[0] or (got[0] == "ok" and str(got[1]) != str(exp[1])):
                bad.append((n, c, got, exp))
        self.assertFalse(bad, f"{len(bad)} rozdílů z {len(calls)}, např. {bad[:5]}")
        self.assertGreater(len(calls), 5000)


FACT = r'''
(module
  (memory (export "memory") 1)
  (data (i32.const 8) "hello")
  (type $bin (func (param i32 i32) (result i32)))
  (table 2 funcref)
  (elem (i32.const 0) $add $mul)
  (global $g (mut i32) (i32.const 7))
  (func $add (param i32 i32) (result i32) (i32.add (local.get 0) (local.get 1)))
  (func $mul (param i32 i32) (result i32) (i32.mul (local.get 0) (local.get 1)))
  (func $fact (export "fact") (param $n i32) (result i32)
    (if (result i32) (i32.le_s (local.get $n) (i32.const 1))
      (then (i32.const 1))
      (else (i32.mul (local.get $n) (call $fact (i32.sub (local.get $n) (i32.const 1)))))))
  (func (export "sum") (param $n i32) (result i32)
    (local $i i32) (local $acc i32)
    (block $done (loop $again
      (br_if $done (i32.gt_s (local.get $i) (local.get $n)))
      (local.set $acc (i32.add (local.get $acc) (local.get $i)))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br $again)))
    (local.get $acc))
  (func (export "pick") (param $i i32) (result i32)
    (block $c (block $b (block $a
      (br_table $a $b $c (local.get $i)))
      (return (i32.const 10)))
      (return (i32.const 20)))
    (i32.const 30))
  (func (export "ind") (param $f i32) (param $a i32) (param $b i32) (result i32)
    (call_indirect (type $bin) (local.get $a) (local.get $b) (local.get $f)))
  (func (export "byte") (param $p i32) (result i32) (i32.load8_u (local.get $p)))
  (func (export "put") (param $p i32) (param $v i64) (i64.store (local.get $p) (local.get $v)))
  (func (export "get") (param $p i32) (result i64) (i64.load (local.get $p)))
  (func (export "multi") (param i32) (result i32 i32) (local.get 0) (i32.add (local.get 0) (i32.const 1)))
  (func (export "oob") (result i32) (i32.load (i32.const 65535)))
  (func (export "spin") (loop $l (br $l)))
  (func (export "deep") (param $n i32) (result i32) (call $deep2 (local.get $n)))
  (func $deep2 (param $n i32) (result i32) (call $deep2 (i32.add (local.get $n) (i32.const 1))))
  (func (export "g") (result i32) (global.set $g (i32.add (global.get $g) (i32.const 1))) (global.get $g))
  (func (export "grow") (result i32) (memory.grow (i32.const 1)))
)'''


class TestInterpreter(unittest.TestCase):
    def setUp(self):
        self.w = assemble(FACT)
        self.i = Instance(self.w, max_pages=3)

    def test_control_flow_and_calls(self):
        i = self.i
        self.assertEqual(i.call("fact", 10), 3628800)
        self.assertEqual(i.call("sum", 100), 5050)
        self.assertEqual([i.call("pick", k) for k in (0, 1, 2, 9)], [10, 20, 30, 30])
        self.assertEqual((i.call("ind", 0, 6, 7), i.call("ind", 1, 6, 7)), (13, 42))
        self.assertEqual(i.call("multi", 4), (4, 5))

    def test_memory_globals_and_limits(self):
        i = self.i
        self.assertEqual(chr(i.call("byte", 8)), "h")
        i.call("put", 100, -2)
        self.assertEqual(i.call("get", 100), -2)
        self.assertEqual(i.read(8, 5), b"hello")
        self.assertEqual((i.call("g"), i.call("g")), (8, 9))
        with self.assertRaises(Trap):
            i.call("oob")                                   # čtení těsně za první stránkou
        with self.assertRaises(Trap):
            i.read(10 ** 9, 4)
        self.assertEqual((i.call("grow"), i.call("grow"), i.call("grow")), (1, 2, -1))   # limit 3 stránky
        self.assertEqual(i.call("oob"), 0)                  # po zvětšení už je adresa platná

    def test_sandbox_limits(self):
        with self.assertRaisesRegex(Trap, "limit instrukcí"):
            self.i.call("spin")
        with self.assertRaisesRegex(Trap, "rekurze|limit"):
            self.i.call("deep", 0)

    def test_host_imports(self):
        got = []
        w = assemble('(module (import "h" "say" (func $s (param i32))) (func (export "go") (call $s (i32.const 42))))')
        Instance(w, {"h": {"say": got.append}}).call("go")
        self.assertEqual(got, [42])
        with self.assertRaisesRegex(WasmError, "chybí import"):
            Instance(w, {})

    def test_bad_modules(self):
        with self.assertRaises(WasmError):
            Instance(b"nope")
        with self.assertRaises(WatError):
            assemble("(module (func (i32.nonsense)))")
        with self.assertRaises(WatError):
            assemble("(module (func (br $nikde)))")

    @unittest.skipUnless(wasm_node.NODE, "node není k dispozici")
    def test_program_matches_v8(self):
        calls = [("fact", [("i32", 10)], "i32"), ("sum", [("i32", 1000)], "i32"), ("pick", [("i32", 1)], "i32"),
                 ("ind", [("i32", 1), ("i32", 6), ("i32", 7)], "i32"), ("oob", [], "i32")]
        exp = wasm_node.run_node(self.w, calls)
        got = []
        for name, args, _ in calls:
            try:
                got.append(["ok", self.i.call(name, *[v for _, v in args])])
            except Trap:
                got.append(["trap"])
        self.assertEqual([e[0] for e in exp], [g[0] for g in got])
        self.assertEqual([e[1] for e in exp if e[0] == "ok"], [g[1] for g in got if g[0] == "ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
