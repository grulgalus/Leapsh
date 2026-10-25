"""Assembler textového formátu WebAssembly (WAT) -> .wasm, v čistém Pythonu (funguje i v Termuxu).

Podporuje: type, import, func (flat i složené/folded zápisy), memory, table, elem, global, data, export, start,
návěští ($jména), block/loop/if, br_table, call_indirect, všechny číselné instrukce a pamětové operace.

    from leapsh.wat import assemble
    wasm_bytes = assemble(open("plugin.wat").read())
"""
import math
import re
import struct

from .wasm import FC_OPCODES, OPCODES

VALTYPES = {"i32": 0x7F, "i64": 0x7E, "f32": 0x7D, "f64": 0x7C, "funcref": 0x70, "externref": 0x6F}
KINDS = {"func": 0, "table": 1, "memory": 2, "global": 3}
LOAD_STORE = {n for n, c in OPCODES.items() if 0x28 <= c <= 0x3E}
DEFAULT_ALIGN = {"i32.load": 2, "i64.load": 3, "f32.load": 2, "f64.load": 3, "i32.load8_s": 0, "i32.load8_u": 0,
                 "i32.load16_s": 1, "i32.load16_u": 1, "i64.load8_s": 0, "i64.load8_u": 0, "i64.load16_s": 1,
                 "i64.load16_u": 1, "i64.load32_s": 2, "i64.load32_u": 2, "i32.store": 2, "i64.store": 3,
                 "f32.store": 2, "f64.store": 3, "i32.store8": 0, "i32.store16": 1, "i64.store8": 0,
                 "i64.store16": 1, "i64.store32": 2}


class WatError(Exception):
    pass


# ---------------------------------------------------------------- tokenizer
def tokenize(text):
    """Text -> vnořené seznamy; atomy jsou str, řetězcové literály bytes."""
    stack, i, n = [[]], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith(";;", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("(;", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("(;", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith(";)", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise WatError("neuzavřený komentář (; ;)")
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            if len(stack) < 2:
                raise WatError("přebývá ')'")
            lst = stack.pop()
            stack[-1].append(lst)
            i += 1
        elif c == '"':
            i, out = i + 1, bytearray()
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                    e = text[i] if i < n else ""
                    if e in "nrt\\\"'":
                        out += {"n": b"\n", "r": b"\r", "t": b"\t", "\\": b"\\", '"': b'"', "'": b"'"}[e]
                        i += 1
                    elif e == "u":
                        j = text.index("}", i)
                        out += chr(int(text[i + 2:j], 16)).encode("utf-8")
                        i = j + 1
                    else:
                        out.append(int(text[i:i + 2], 16))
                        i += 2
                else:
                    out += text[i].encode("utf-8")
                    i += 1
            if i >= n:
                raise WatError("neuzavřený řetězec")
            i += 1
            stack[-1].append(bytes(out))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()";':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if len(stack) != 1:
        raise WatError("chybí ')'")
    return stack[0]


# ---------------------------------------------------------------- kódování
def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def vec(items):
    return uleb(len(items)) + b"".join(items)


def name_bytes(b):
    b = b if isinstance(b, bytes) else b.encode("utf-8")
    return uleb(len(b)) + b


def parse_int(tok, bits):
    t = tok.replace("_", "")
    neg = t.startswith("-")
    body = t.lstrip("+-")
    try:
        v = int(body, 16) if body.lower().startswith("0x") else int(body, 10)
    except ValueError:
        raise WatError(f"neplatné číslo '{tok}'")
    v = -v if neg else v
    if not -(1 << (bits - 1)) <= v < (1 << bits):
        raise WatError(f"číslo {tok} se nevejde do i{bits}")
    return v - (1 << bits) if v >= (1 << (bits - 1)) else v


def parse_float(tok):
    t = tok.replace("_", "").lower()
    sign = -1.0 if t.startswith("-") else 1.0
    t = t.lstrip("+-")
    if t == "inf":
        return sign * math.inf
    if t.startswith("nan"):
        return math.nan
    try:
        return sign * (float.fromhex(t) if t.startswith("0x") else float(t))
    except ValueError:
        raise WatError(f"neplatné číslo '{tok}'")


def is_id(x):
    return isinstance(x, str) and x.startswith("$")


class Lookup:
    def __init__(self, what):
        self.what, self.names, self.count = what, {}, 0

    def add(self, ident=None):
        if ident:
            self.names[ident] = self.count
        self.count += 1
        return self.count - 1

    def get(self, tok):
        if isinstance(tok, str) and tok.startswith("$"):
            if tok not in self.names:
                raise WatError(f"neznámé {self.what} {tok}")
            return self.names[tok]
        try:
            return int(tok)
        except (TypeError, ValueError):
            raise WatError(f"neplatný index {self.what}: {tok!r}")


# ---------------------------------------------------------------- tělo funkce
class Body:
    def __init__(self, asm, locals_):
        self.asm, self.locals, self.labels, self.out = asm, locals_, [], bytearray()

    def label_depth(self, tok):
        if is_id(tok):
            for d, name in enumerate(reversed(self.labels)):
                if name == tok:
                    return d
            raise WatError(f"neznámé návěští {tok}")
        return int(tok)

    def blocktype(self, items, j):
        params, results, tidx = [], [], None
        while j < len(items) and isinstance(items[j], list) and items[j] and items[j][0] in ("param", "result", "type"):
            h = items[j]
            if h[0] == "type":
                tidx = self.asm.types_lookup.get(h[1])
            elif h[0] == "param":
                params += [VALTYPES[t] for t in h[1:] if not is_id(t)]
            else:
                results += [VALTYPES[t] for t in h[1:]]
            j += 1
        if tidx is not None:
            return uleb(tidx) if False else sleb(tidx), j
        if not params and not results:
            return b"\x40", j
        if not params and len(results) == 1:
            return bytes([results[0]]), j
        return sleb(self.asm.type_index(params, results)), j

    def seq(self, items):
        i = 0
        while i < len(items):
            it = items[i]
            if isinstance(it, list):
                self.folded(it)
                i += 1
            elif isinstance(it, str):
                i = self.flat(items, i)
            else:
                raise WatError(f"neočekávaný řetězec v kódu: {it!r}")

    # ---- plochý zápis
    def flat(self, items, i):
        op = items[i]
        j = i + 1
        if op in ("block", "loop", "if"):
            label = None
            if j < len(items) and is_id(items[j]):
                label, j = items[j], j + 1
            bt, j = self.blocktype(items, j)
            self.out.append(OPCODES[op])
            self.out += bt
            self.labels.append(label)
            return j
        if op == "else":
            self.out.append(0x05)
            return j
        if op == "end":
            self.out.append(0x0B)
            if self.labels:
                self.labels.pop()
            return j
        imms = []
        if op in ("local.get", "local.set", "local.tee", "global.get", "global.set", "call", "br", "br_if",
                  "i32.const", "i64.const", "f32.const", "f64.const", "data.drop"):
            imms = [items[j]] if j < len(items) else []
            j += 1
        elif op == "br_table":
            while j < len(items) and isinstance(items[j], str) and (is_id(items[j]) or items[j].isdigit()):
                imms.append(items[j])
                j += 1
        elif op in LOAD_STORE:
            while j < len(items) and isinstance(items[j], str) and items[j].startswith(("offset=", "align=")):
                imms.append(items[j])
                j += 1
        elif op in ("call_indirect", "select"):
            while j < len(items) and isinstance(items[j], list) and items[j] and items[j][0] in ("type", "param", "result"):
                imms.append(items[j])
                j += 1
        self.op(op, imms)
        return j

    # ---- složený zápis
    def folded(self, lst):
        if not lst or not isinstance(lst[0], str):
            raise WatError(f"neplatný výraz {lst!r}")
        op, rest = lst[0], lst[1:]
        if op in ("block", "loop"):
            label, k = (rest[0], 1) if rest and is_id(rest[0]) else (None, 0)
            bt, k = self.blocktype(rest, k)
            self.out.append(OPCODES[op])
            self.out += bt
            self.labels.append(label)
            self.seq(rest[k:])
            self.out.append(0x0B)
            self.labels.pop()
            return
        if op == "if":
            label, k = (rest[0], 1) if rest and is_id(rest[0]) else (None, 0)
            bt, k = self.blocktype(rest, k)
            then_i = next((x for x in range(k, len(rest)) if isinstance(rest[x], list) and rest[x] and rest[x][0] == "then"), None)
            if then_i is None:
                raise WatError("if bez (then ...)")
            self.seq(rest[k:then_i])                         # podmínka
            self.out.append(0x04)
            self.out += bt
            self.labels.append(label)
            self.seq(rest[then_i][1:])
            if then_i + 1 < len(rest) and rest[then_i + 1][0] == "else":
                self.out.append(0x05)
                self.seq(rest[then_i + 1][1:])
            self.out.append(0x0B)
            self.labels.pop()
            return
        imms, children = [], []
        for x in rest:
            if isinstance(x, list) and not (x and x[0] in ("type", "param", "result") and op in ("call_indirect", "select")):
                children.append(x)
            else:
                imms.append(x)
        for c in children:
            self.folded(c)
        self.op(op, imms)

    # ---- jedna instrukce
    def op(self, op, imms):
        o = self.out
        if op in FC_OPCODES:
            o.append(0xFC)
            o += uleb(FC_OPCODES[op])
            if op == "memory.init":
                o += uleb(int(imms[0])) + b"\0"
            elif op == "data.drop":
                o += uleb(int(imms[0]))
            elif op == "memory.copy":
                o += b"\0\0"
            elif op == "memory.fill":
                o += b"\0"
            return
        if op not in OPCODES:
            raise WatError(f"neznámá instrukce '{op}'")
        o.append(OPCODES[op])
        if op in ("local.get", "local.set", "local.tee"):
            o += uleb(self.locals.get(imms[0]))
        elif op in ("global.get", "global.set"):
            o += uleb(self.asm.globals.get(imms[0]))
        elif op == "call":
            o += uleb(self.asm.funcs.get(imms[0]))
        elif op in ("br", "br_if"):
            o += uleb(self.label_depth(imms[0]))
        elif op == "br_table":
            depths = [self.label_depth(x) for x in imms]
            o += uleb(len(depths) - 1) + b"".join(uleb(d) for d in depths[:-1]) + uleb(depths[-1])
        elif op == "call_indirect":
            tidx, params, results = None, [], []
            for h in imms:
                if h[0] == "type":
                    tidx = self.asm.types_lookup.get(h[1])
                elif h[0] == "param":
                    params += [VALTYPES[t] for t in h[1:] if not is_id(t)]
                else:
                    results += [VALTYPES[t] for t in h[1:]]
            o += uleb(tidx if tidx is not None else self.asm.type_index(params, results)) + b"\0"
        elif op == "select" and imms:
            o[-1] = 0x1C
            o += vec([bytes([VALTYPES[t]]) for h in imms if h[0] == "result" for t in h[1:]])
        elif op == "i32.const":
            o += sleb(parse_int(imms[0], 32))
        elif op == "i64.const":
            o += sleb(parse_int(imms[0], 64))
        elif op == "f32.const":
            o += struct.pack("<f", parse_float(imms[0]))
        elif op == "f64.const":
            o += struct.pack("<d", parse_float(imms[0]))
        elif op in LOAD_STORE:
            offset, align = 0, DEFAULT_ALIGN[op]
            for x in imms:
                k, _, v = x.partition("=")
                if k == "offset":
                    offset = int(v, 0)
                else:
                    align = int(v, 0).bit_length() - 1
            o += uleb(align) + uleb(offset)
        elif op in ("memory.size", "memory.grow"):
            o.append(0)


# ---------------------------------------------------------------- modul
class Assembler:
    def __init__(self):
        self.types, self.types_lookup = [], Lookup("typ")
        self.funcs, self.globals = Lookup("funkci"), Lookup("globál")
        self.tables, self.mems = Lookup("tabulku"), Lookup("paměť")
        self.imports, self.func_decls, self.table_decls, self.mem_decls = [], [], [], []
        self.global_decls, self.exports, self.elems, self.datas = [], [], [], []
        self.start = None

    def type_index(self, params, results):
        t = (tuple(params), tuple(results))
        if t not in self.types:
            self.types.append(t)
        return self.types.index(t)

    # ---- pomocné čtení signatur
    def signature(self, items):
        """-> (params[valtype], results[valtype], paramnames[(id|None)], type_idx|None, rest)"""
        params, names, results, tidx, k = [], [], [], None, 0
        while k < len(items) and isinstance(items[k], list) and items[k] and items[k][0] in ("param", "result", "type"):
            h = items[k]
            if h[0] == "type":
                tidx = self.types_lookup.get(h[1])
            elif h[0] == "param":
                if len(h) >= 3 and is_id(h[1]):
                    params.append(VALTYPES[h[2]])
                    names.append(h[1])
                else:
                    for t in h[1:]:
                        params.append(VALTYPES[t])
                        names.append(None)
            else:
                results += [VALTYPES[t] for t in h[1:]]
            k += 1
        return params, results, names, tidx, items[k:]

    def build(self, fields):
        # --- průchod 1: deklarace a indexy
        for f in fields:
            if not isinstance(f, list) or not f:
                raise WatError(f"neplatné pole modulu: {f!r}")
            kind, rest = f[0], f[1:]
            if kind == "type":
                ident = rest[0] if is_id(rest[0]) else None
                ft = rest[1 if ident else 0]
                p, r, _, _, _ = self.signature(ft[1:])
                self.types.append((tuple(p), tuple(r)))
                self.types_lookup.add(ident)
        for f in fields:
            kind, rest = f[0], f[1:]
            if kind == "import":
                mod, nm, desc = rest[0], rest[1], rest[2]
                ident = desc[1] if len(desc) > 1 and is_id(desc[1]) else None
                dr = desc[2 if ident else 1:]
                if desc[0] == "func":
                    p, r, _, tidx, _ = self.signature(dr)
                    self.imports.append((mod, nm, 0, uleb(tidx if tidx is not None else self.type_index(p, r))))
                    self.funcs.add(ident)
                elif desc[0] == "memory":
                    self.imports.append((mod, nm, 2, self.limits(dr)))
                    self.mems.add(ident)
                elif desc[0] == "global":
                    gt = dr[0]
                    mut = isinstance(gt, list)
                    self.imports.append((mod, nm, 3, bytes([VALTYPES[gt[1] if mut else gt], int(mut)])))
                    self.globals.add(ident)
                else:
                    raise WatError(f"nepodporovaný import '{desc[0]}'")
        for f in fields:
            kind, rest = f[0], f[1:]
            ident = rest[0] if rest and is_id(rest[0]) else None
            body = rest[1:] if ident else rest
            if kind == "func":
                exports, imp, k = [], None, 0
                while k < len(body) and isinstance(body[k], list) and body[k] and body[k][0] in ("export", "import"):
                    if body[k][0] == "export":
                        exports.append(body[k][1])
                    else:
                        imp = body[k]
                    k += 1
                p, r, names, tidx, code = self.signature(body[k:])
                ti = tidx if tidx is not None else self.type_index(p, r)
                if tidx is not None:
                    p, r = list(self.types[tidx][0]), list(self.types[tidx][1])
                    names = (names + [None] * len(p))[:len(p)]
                fi = self.funcs.add(ident)
                for e in exports:
                    self.exports.append((e, 0, fi))
                if imp:
                    self.imports.append((imp[1], imp[2], 0, uleb(ti)))
                    # import musí být před definovanými: indexy řešíme přeřazením níže
                    raise WatError("inline (import ...) u func použij jako samostatný (import ...)")
                self.func_decls.append((ti, p, names, code))
            elif kind == "memory":
                exports, k = [], 0
                while k < len(body) and isinstance(body[k], list) and body[k][0] == "export":
                    exports.append(body[k][1])
                    k += 1
                idx = self.mems.add(ident)
                for e in exports:
                    self.exports.append((e, 2, idx))
                self.mem_decls.append(self.limits(body[k:]))
            elif kind == "table":
                exports, k = [], 0
                while k < len(body) and isinstance(body[k], list) and body[k][0] == "export":
                    exports.append(body[k][1])
                    k += 1
                idx = self.tables.add(ident)
                for e in exports:
                    self.exports.append((e, 1, idx))
                rest2 = body[k:]
                if rest2 and rest2[0] == "funcref" and len(rest2) > 1 and isinstance(rest2[1], list) and rest2[1][0] == "elem":
                    fl = rest2[1][1:]
                    self.table_decls.append(self.limits([str(len(fl)), str(len(fl))]))
                    self.elems.append((idx, [["i32.const", "0"]], fl))
                else:
                    self.table_decls.append(self.limits([x for x in rest2 if x != "funcref"]))
            elif kind == "global":
                exports, k = [], 0
                while k < len(body) and isinstance(body[k], list) and body[k][0] == "export":
                    exports.append(body[k][1])
                    k += 1
                idx = self.globals.add(ident)
                for e in exports:
                    self.exports.append((e, 3, idx))
                gt = body[k]
                mut = isinstance(gt, list)
                self.global_decls.append((bytes([VALTYPES[gt[1] if mut else gt], int(mut)]), body[k + 1:]))
            elif kind == "export":
                nm, desc = rest[0], rest[1]
                lk = {"func": self.funcs, "table": self.tables, "memory": self.mems, "global": self.globals}[desc[0]]
                self.exports.append((nm, KINDS[desc[0]], ("lazy", lk, desc[1])))
            elif kind == "start":
                self.start = ("lazy", self.funcs, rest[0])
            elif kind == "data":
                k = 1 if rest and is_id(rest[0]) else 0
                rest2 = rest[k:]
                if rest2 and isinstance(rest2[0], list):
                    off = rest2[0][1:] if rest2[0][0] == "offset" else [rest2[0]]
                    self.datas.append((off, b"".join(x for x in rest2[1:] if isinstance(x, bytes))))
                else:
                    self.datas.append((None, b"".join(x for x in rest2 if isinstance(x, bytes))))
            elif kind == "elem":
                k = 1 if rest and is_id(rest[0]) else 0
                rest2 = rest[k:]
                off = rest2[0][1:] if rest2[0][0] == "offset" else [rest2[0]]
                fl = [x for x in rest2[1:] if x != "func"]
                self.elems.append((0, off, fl))
            elif kind in ("type", "import"):
                pass
            else:
                raise WatError(f"nepodporované pole '{kind}'")
        return self.encode()

    @staticmethod
    def limits(items):
        nums = [x for x in items if isinstance(x, str) and re.fullmatch(r"\d+", x)]
        if not nums:
            raise WatError("chybí velikost (memory/table)")
        if len(nums) == 1:
            return b"\x00" + uleb(int(nums[0]))
        return b"\x01" + uleb(int(nums[0])) + uleb(int(nums[1]))

    def const_expr(self, items):
        b = Body(self, Lookup("lokál"))
        b.seq(items)
        return bytes(b.out) + b"\x0B"

    def resolve(self, ref):
        return ref[1].get(ref[2]) if isinstance(ref, tuple) else ref

    def encode(self):
        def section(sid, payload):
            return bytes([sid]) + uleb(len(payload)) + payload

        out = bytearray(b"\0asm\x01\0\0\0")
        if self.types:
            out += section(1, vec([b"\x60" + vec([bytes([t]) for t in p]) + vec([bytes([t]) for t in r])
                                   for p, r in self.types]))
        if self.imports:
            out += section(2, vec([name_bytes(m) + name_bytes(n) + bytes([k]) + d for m, n, k, d in self.imports]))
        if self.func_decls:
            out += section(3, vec([uleb(t) for t, _, _, _ in self.func_decls]))
        if self.table_decls:
            out += section(4, vec([b"\x70" + d for d in self.table_decls]))
        if self.mem_decls:
            out += section(5, vec(self.mem_decls))
        if self.global_decls:
            out += section(6, vec([t + self.const_expr(e) for t, e in self.global_decls]))
        if self.exports:
            out += section(7, vec([name_bytes(n) + bytes([k]) + uleb(self.resolve(i)) for n, k, i in self.exports]))
        if self.start is not None:
            out += section(8, uleb(self.resolve(self.start)))
        if self.elems:
            out += section(9, vec([b"\x00" + self.const_expr(off) + vec([uleb(self.funcs.get(x)) for x in fl])
                                   for _, off, fl in self.elems]))
        if self.func_decls:
            codes = []
            for ti, params, names, code in self.func_decls:
                locs = Lookup("lokál")
                for nm in names:
                    locs.add(nm)
                local_types, rest = [], []
                for x in code:
                    if isinstance(x, list) and x and x[0] == "local":
                        if len(x) >= 3 and is_id(x[1]):
                            locs.add(x[1])
                            local_types.append(VALTYPES[x[2]])
                        else:
                            for t in x[1:]:
                                locs.add()
                                local_types.append(VALTYPES[t])
                    else:
                        rest.append(x)
                body = Body(self, locs)
                body.seq(rest)
                data = vec([uleb(1) + bytes([t]) for t in local_types]) + bytes(body.out) + b"\x0B"
                codes.append(uleb(len(data)) + data)
            out += section(10, vec(codes))
        if self.datas:
            parts = []
            for off, data in self.datas:
                parts.append((b"\x00" + self.const_expr(off) if off is not None else b"\x01") + uleb(len(data)) + data)
            out += section(11, vec(parts))
        return bytes(out)


def assemble(text):
    """WAT text -> bajty .wasm. Při chybě vyvolá WatError s popisem."""
    forms = tokenize(text)
    if len(forms) == 1 and isinstance(forms[0], list) and forms[0] and forms[0][0] == "module":
        fields = forms[0][1:]
        if fields and is_id(fields[0]):
            fields = fields[1:]
    else:
        fields = forms
    try:
        return Assembler().build(fields)
    except (KeyError, IndexError) as exc:
        raise WatError(f"chyba v zápisu ({type(exc).__name__}: {exc})") from None
