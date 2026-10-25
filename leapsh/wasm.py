"""Čistě pythonový interpret WebAssembly (MVP + sign-extension, saturating trunc, bulk memory, multi-value).

Bez závislostí, takže běží i v Termuxu. Pluginy jsou v sandboxu: modul vidí jen to, co mu hostitel předá
v `imports`, a běží s limitem „paliva“ (zpětné skoky a volání) a paměti.

    inst = Instance(wasm_bytes, imports={"leapsh": {"say": lambda p, n: ...}})
    inst.call("leapsh_command", 1, 2, 3, 4)
"""
import math
import struct

M32, M64 = 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF
PAGE = 65536
I32, I64, F32, F64, FUNCREF, EXTERNREF = 0x7F, 0x7E, 0x7D, 0x7C, 0x70, 0x6F
VALTYPES = (I32, I64, F32, F64, FUNCREF, EXTERNREF)


class WasmError(Exception):
    """Chybný nebo nepodporovaný modul."""


class Trap(Exception):
    """Běh modulu skončil pastí (dělení nulou, mimo paměť, vypršelo palivo, …)."""


# ---------------------------------------------------------------- tabulka operací (sdílí ji i assembler)
_NUM = ("i32.eqz i32.eq i32.ne i32.lt_s i32.lt_u i32.gt_s i32.gt_u i32.le_s i32.le_u i32.ge_s i32.ge_u "
        "i64.eqz i64.eq i64.ne i64.lt_s i64.lt_u i64.gt_s i64.gt_u i64.le_s i64.le_u i64.ge_s i64.ge_u "
        "f32.eq f32.ne f32.lt f32.gt f32.le f32.ge f64.eq f64.ne f64.lt f64.gt f64.le f64.ge "
        "i32.clz i32.ctz i32.popcnt i32.add i32.sub i32.mul i32.div_s i32.div_u i32.rem_s i32.rem_u "
        "i32.and i32.or i32.xor i32.shl i32.shr_s i32.shr_u i32.rotl i32.rotr "
        "i64.clz i64.ctz i64.popcnt i64.add i64.sub i64.mul i64.div_s i64.div_u i64.rem_s i64.rem_u "
        "i64.and i64.or i64.xor i64.shl i64.shr_s i64.shr_u i64.rotl i64.rotr "
        "f32.abs f32.neg f32.ceil f32.floor f32.trunc f32.nearest f32.sqrt f32.add f32.sub f32.mul f32.div "
        "f32.min f32.max f32.copysign "
        "f64.abs f64.neg f64.ceil f64.floor f64.trunc f64.nearest f64.sqrt f64.add f64.sub f64.mul f64.div "
        "f64.min f64.max f64.copysign "
        "i32.wrap_i64 i32.trunc_f32_s i32.trunc_f32_u i32.trunc_f64_s i32.trunc_f64_u "
        "i64.extend_i32_s i64.extend_i32_u i64.trunc_f32_s i64.trunc_f32_u i64.trunc_f64_s i64.trunc_f64_u "
        "f32.convert_i32_s f32.convert_i32_u f32.convert_i64_s f32.convert_i64_u f32.demote_f64 "
        "f64.convert_i32_s f64.convert_i32_u f64.convert_i64_s f64.convert_i64_u f64.promote_f32 "
        "i32.reinterpret_f32 i64.reinterpret_f64 f32.reinterpret_i32 f64.reinterpret_i64 "
        "i32.extend8_s i32.extend16_s i64.extend8_s i64.extend16_s i64.extend32_s").split()
_MEM = ("i32.load i64.load f32.load f64.load i32.load8_s i32.load8_u i32.load16_s i32.load16_u "
        "i64.load8_s i64.load8_u i64.load16_s i64.load16_u i64.load32_s i64.load32_u "
        "i32.store i64.store f32.store f64.store i32.store8 i32.store16 i64.store8 i64.store16 i64.store32").split()
_SAT = ("i32.trunc_sat_f32_s i32.trunc_sat_f32_u i32.trunc_sat_f64_s i32.trunc_sat_f64_u "
        "i64.trunc_sat_f32_s i64.trunc_sat_f32_u i64.trunc_sat_f64_s i64.trunc_sat_f64_u").split()

OPCODES = {n: 0x45 + i for i, n in enumerate(_NUM)}                 # numerické 0x45..0xC4
OPCODES.update({n: 0x28 + i for i, n in enumerate(_MEM)})           # paměť 0x28..0x3E
OPCODES.update({"unreachable": 0x00, "nop": 0x01, "block": 0x02, "loop": 0x03, "if": 0x04, "else": 0x05,
                "end": 0x0B, "br": 0x0C, "br_if": 0x0D, "br_table": 0x0E, "return": 0x0F, "call": 0x10,
                "call_indirect": 0x11, "drop": 0x1A, "select": 0x1B, "local.get": 0x20, "local.set": 0x21,
                "local.tee": 0x22, "global.get": 0x23, "global.set": 0x24, "memory.size": 0x3F,
                "memory.grow": 0x40, "i32.const": 0x41, "i64.const": 0x42, "f32.const": 0x43, "f64.const": 0x44})
FC_OPCODES = {n: i for i, n in enumerate(_SAT)}
FC_OPCODES.update({"memory.init": 8, "data.drop": 9, "memory.copy": 10, "memory.fill": 11})
LOAD_SIZES = {0x28: (4, False, 32), 0x29: (8, False, 64), 0x2C: (1, True, 32), 0x2D: (1, False, 32),
              0x2E: (2, True, 32), 0x2F: (2, False, 32), 0x30: (1, True, 64), 0x31: (1, False, 64),
              0x32: (2, True, 64), 0x33: (2, False, 64), 0x34: (4, True, 64), 0x35: (4, False, 64)}
STORE_SIZES = {0x36: 4, 0x37: 8, 0x3A: 1, 0x3B: 2, 0x3C: 1, 0x3D: 2, 0x3E: 4}


# ---------------------------------------------------------------- číselná sémantika
def s32(x):
    return x - 0x100000000 if x & 0x80000000 else x


def s64(x):
    return x - 0x10000000000000000 if x & 0x8000000000000000 else x


def f32r(x):
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def _fdiv(a, b):
    if b == 0:
        if a == 0 or a != a:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _fmin(a, b):
    if a != a or b != b:
        return math.nan
    if a == 0 and b == 0:
        return a if math.copysign(1, a) < 0 else b
    return min(a, b)


def _fmax(a, b):
    if a != a or b != b:
        return math.nan
    if a == 0 and b == 0:
        return a if math.copysign(1, a) > 0 else b
    return max(a, b)


def _fround(fn):
    def r(a):
        if a != a or a in (math.inf, -math.inf):
            return a
        v = float(fn(a))
        return math.copysign(0.0, a) if v == 0 else v
    return r


def _sqrt(a):
    if a != a or a < 0:
        return math.nan
    return math.sqrt(a)


def _build_tables():
    B, U = {}, {}                                    # binární a unární operace podle jména
    for bits, M, sg in ((32, M32, s32), (64, M64, s64)):
        p, sh = f"i{bits}.", bits - 1
        mask = bits - 1
        U[p + "eqz"] = lambda a: int(a == 0)
        B[p + "eq"] = lambda a, b: int(a == b)
        B[p + "ne"] = lambda a, b: int(a != b)
        B[p + "lt_u"] = lambda a, b: int(a < b)
        B[p + "gt_u"] = lambda a, b: int(a > b)
        B[p + "le_u"] = lambda a, b: int(a <= b)
        B[p + "ge_u"] = lambda a, b: int(a >= b)
        B[p + "lt_s"] = lambda a, b, sg=sg: int(sg(a) < sg(b))
        B[p + "gt_s"] = lambda a, b, sg=sg: int(sg(a) > sg(b))
        B[p + "le_s"] = lambda a, b, sg=sg: int(sg(a) <= sg(b))
        B[p + "ge_s"] = lambda a, b, sg=sg: int(sg(a) >= sg(b))
        U[p + "clz"] = lambda a, bits=bits: bits - a.bit_length()
        U[p + "ctz"] = lambda a, bits=bits: (a & -a).bit_length() - 1 if a else bits
        U[p + "popcnt"] = lambda a: bin(a).count("1")
        B[p + "add"] = lambda a, b, M=M: (a + b) & M
        B[p + "sub"] = lambda a, b, M=M: (a - b) & M
        B[p + "mul"] = lambda a, b, M=M: (a * b) & M
        B[p + "and"] = lambda a, b: a & b
        B[p + "or"] = lambda a, b: a | b
        B[p + "xor"] = lambda a, b: a ^ b
        B[p + "shl"] = lambda a, b, M=M, mask=mask: (a << (b & mask)) & M
        B[p + "shr_u"] = lambda a, b, mask=mask: a >> (b & mask)
        B[p + "shr_s"] = lambda a, b, M=M, sg=sg, mask=mask: (sg(a) >> (b & mask)) & M

        def rotl(a, b, M=M, bits=bits, mask=mask):
            k = b & mask
            return ((a << k) | (a >> (bits - k))) & M if k else a

        def rotr(a, b, M=M, bits=bits, mask=mask):
            k = b & mask
            return ((a >> k) | (a << (bits - k))) & M if k else a

        def div_u(a, b):
            if b == 0:
                raise Trap("integer divide by zero")
            return a // b

        def rem_u(a, b):
            if b == 0:
                raise Trap("integer divide by zero")
            return a % b

        def div_s(a, b, M=M, sg=sg, sh=sh):
            if b == 0:
                raise Trap("integer divide by zero")
            x, y = sg(a), sg(b)
            if x == -(1 << sh) and y == -1:
                raise Trap("integer overflow")
            q = abs(x) // abs(y)
            return (-q if (x < 0) != (y < 0) else q) & M

        def rem_s(a, b, M=M, sg=sg):
            if b == 0:
                raise Trap("integer divide by zero")
            x, y = sg(a), sg(b)
            r = abs(x) % abs(y)
            return (-r if x < 0 else r) & M

        B[p + "rotl"], B[p + "rotr"] = rotl, rotr
        B[p + "div_u"], B[p + "rem_u"], B[p + "div_s"], B[p + "rem_s"] = div_u, rem_u, div_s, rem_s
    for bits, rnd in ((32, f32r), (64, lambda x: x)):
        p = f"f{bits}."
        B[p + "eq"] = lambda a, b: int(a == b)
        B[p + "ne"] = lambda a, b: int(a != b)
        B[p + "lt"] = lambda a, b: int(a < b)
        B[p + "gt"] = lambda a, b: int(a > b)
        B[p + "le"] = lambda a, b: int(a <= b)
        B[p + "ge"] = lambda a, b: int(a >= b)
        U[p + "abs"] = abs
        U[p + "neg"] = lambda a: -a
        U[p + "ceil"] = _fround(math.ceil)
        U[p + "floor"] = _fround(math.floor)
        U[p + "trunc"] = _fround(math.trunc)
        U[p + "nearest"] = _fround(round)
        U[p + "sqrt"] = lambda a, rnd=rnd: rnd(_sqrt(a))
        B[p + "add"] = lambda a, b, rnd=rnd: rnd(a + b)
        B[p + "sub"] = lambda a, b, rnd=rnd: rnd(a - b)
        B[p + "mul"] = lambda a, b, rnd=rnd: rnd(a * b)
        B[p + "div"] = lambda a, b, rnd=rnd: rnd(_fdiv(a, b))
        B[p + "min"], B[p + "max"] = _fmin, _fmax
        B[p + "copysign"] = lambda a, b: math.copysign(a, b)
    # konverze
    U["i32.wrap_i64"] = lambda a: a & M32
    U["i64.extend_i32_s"] = lambda a: s32(a) & M64
    U["i64.extend_i32_u"] = lambda a: a
    U["i32.extend8_s"] = lambda a: ((a & 0xFF) - 0x100 if a & 0x80 else a & 0xFF) & M32
    U["i32.extend16_s"] = lambda a: ((a & 0xFFFF) - 0x10000 if a & 0x8000 else a & 0xFFFF) & M32
    U["i64.extend8_s"] = lambda a: ((a & 0xFF) - 0x100 if a & 0x80 else a & 0xFF) & M64
    U["i64.extend16_s"] = lambda a: ((a & 0xFFFF) - 0x10000 if a & 0x8000 else a & 0xFFFF) & M64
    U["i64.extend32_s"] = lambda a: s32(a & M32) & M64

    def trunc(bits, signed, sat):
        lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        mask = M32 if bits == 32 else M64

        def f(a):
            if a != a:
                if sat:
                    return 0
                raise Trap("invalid conversion to integer")
            if a in (math.inf, -math.inf):
                if sat:
                    return (hi if a > 0 else lo) & mask
                raise Trap("integer overflow")
            v = int(a)
            if v < lo or v > hi:
                if sat:
                    return (hi if v > hi else lo) & mask
                raise Trap("integer overflow")
            return v & mask
        return f

    for bits in (32, 64):
        for fb in (32, 64):
            for signed in (True, False):
                sfx = "s" if signed else "u"
                U[f"i{bits}.trunc_f{fb}_{sfx}"] = trunc(bits, signed, False)
                U[f"i{bits}.trunc_sat_f{fb}_{sfx}"] = trunc(bits, signed, True)
    for fb, rnd in ((32, f32r), (64, lambda x: x)):
        U[f"f{fb}.convert_i32_s"] = lambda a, rnd=rnd: rnd(float(s32(a)))
        U[f"f{fb}.convert_i32_u"] = lambda a, rnd=rnd: rnd(float(a))
        U[f"f{fb}.convert_i64_s"] = lambda a, rnd=rnd: rnd(float(s64(a)))
        U[f"f{fb}.convert_i64_u"] = lambda a, rnd=rnd: rnd(float(a))
    U["f32.demote_f64"] = f32r
    U["f64.promote_f32"] = lambda a: a
    U["i32.reinterpret_f32"] = lambda a: struct.unpack("<I", struct.pack("<f", a))[0]
    U["i64.reinterpret_f64"] = lambda a: struct.unpack("<Q", struct.pack("<d", a))[0]
    U["f32.reinterpret_i32"] = lambda a: struct.unpack("<f", struct.pack("<I", a))[0]
    U["f64.reinterpret_i64"] = lambda a: struct.unpack("<d", struct.pack("<Q", a))[0]
    return B, U


_BIN_BY_NAME, _UN_BY_NAME = _build_tables()
BIN = {OPCODES[n]: f for n, f in _BIN_BY_NAME.items() if n in OPCODES}
UN = {OPCODES[n]: f for n, f in _UN_BY_NAME.items() if n in OPCODES}
SAT = {FC_OPCODES[n]: f for n, f in _UN_BY_NAME.items() if n in FC_OPCODES}
_NAN_CANON = math.nan


# ---------------------------------------------------------------- čtení binárního formátu
class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def eof(self):
        return self.p >= len(self.d)

    def u8(self):
        if self.p >= len(self.d):
            raise WasmError("neočekávaný konec modulu")
        b = self.d[self.p]
        self.p += 1
        return b

    def take(self, n):
        if self.p + n > len(self.d):
            raise WasmError("neočekávaný konec modulu")
        b = self.d[self.p:self.p + n]
        self.p += n
        return bytes(b)

    def u(self):
        r, shift = 0, 0
        while True:
            b = self.u8()
            r |= (b & 0x7F) << shift
            if not b & 0x80:
                return r
            shift += 7
            if shift > 70:
                raise WasmError("příliš dlouhé LEB128")

    def s(self, bits=64):
        r, shift = 0, 0
        while True:
            b = self.u8()
            r |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                if b & 0x40:
                    r -= 1 << shift
                return r
            if shift > 70:
                raise WasmError("příliš dlouhé LEB128")

    def f32(self):
        return struct.unpack("<f", self.take(4))[0]

    def f64(self):
        return struct.unpack("<d", self.take(8))[0]

    def name(self):
        return self.take(self.u()).decode("utf-8", "replace")

    def limits(self):
        flag = self.u8()
        mn = self.u()
        return mn, (self.u() if flag & 1 else None)


class FuncType:
    __slots__ = ("params", "results")

    def __init__(self, params, results):
        self.params, self.results = tuple(params), tuple(results)

    def __eq__(self, o):
        return self.params == o.params and self.results == o.results

    def __hash__(self):
        return hash((self.params, self.results))


class Module:
    def __init__(self, data):
        data = bytes(data)
        if data[:4] != b"\0asm":
            raise WasmError("není WebAssembly (chybí hlavička \\0asm)")
        if data[4:8] != b"\x01\0\0\0":
            raise WasmError("nepodporovaná verze WebAssembly")
        self.types, self.imports, self.func_types = [], [], []
        self.tables, self.mems, self.globals, self.exports = [], [], [], {}
        self.start, self.elems, self.datas, self.bodies = None, [], [], []
        r = Reader(data, 8)
        while not r.eof():
            sid, size = r.u8(), r.u()
            end = r.p + size
            sec = Reader(data[:end], r.p)
            self._section(sid, sec)
            r.p = end

    def _expr(self, r):
        """Konstantní výraz -> ('const', hodnota) nebo ('global', index)."""
        op = r.u8()
        if op == 0x41:
            v = ("const", r.s(32) & M32)
        elif op == 0x42:
            v = ("const", r.s(64) & M64)
        elif op == 0x43:
            v = ("const", r.f32())
        elif op == 0x44:
            v = ("const", r.f64())
        elif op == 0x23:
            v = ("global", r.u())
        elif op == 0xD0:
            r.u8()
            v = ("const", None)
        elif op == 0xD2:
            v = ("const", r.u())
        else:
            raise WasmError(f"nepodporovaný konstantní výraz (0x{op:02x})")
        if r.u8() != 0x0B:
            raise WasmError("konstantní výraz nekončí 'end'")
        return v

    def _section(self, sid, r):
        if sid == 0:
            return
        if sid == 1:
            for _ in range(r.u()):
                if r.u8() != 0x60:
                    raise WasmError("očekáván funkční typ")
                params = [r.u8() for _ in range(r.u())]
                results = [r.u8() for _ in range(r.u())]
                self.types.append(FuncType(params, results))
        elif sid == 2:
            for _ in range(r.u()):
                mod, name, kind = r.name(), r.name(), r.u8()
                if kind == 0:
                    desc = r.u()
                    self.func_types.append(desc)
                elif kind == 1:
                    r.u8()
                    desc = r.limits()
                elif kind == 2:
                    desc = r.limits()
                else:
                    desc = (r.u8(), r.u8())
                self.imports.append((mod, name, kind, desc))
        elif sid == 3:
            for _ in range(r.u()):
                self.func_types.append(r.u())
        elif sid == 4:
            for _ in range(r.u()):
                r.u8()
                self.tables.append(r.limits())
        elif sid == 5:
            for _ in range(r.u()):
                self.mems.append(r.limits())
        elif sid == 6:
            for _ in range(r.u()):
                vt, mut = r.u8(), r.u8()
                self.globals.append((vt, mut, self._expr(r)))
        elif sid == 7:
            for _ in range(r.u()):
                name, kind, idx = r.name(), r.u8(), r.u()
                self.exports[name] = (kind, idx)
        elif sid == 8:
            self.start = r.u()
        elif sid == 9:
            for _ in range(r.u()):
                flag = r.u()
                if flag in (0, 2):
                    table = r.u() if flag == 2 else 0
                    if flag == 2:
                        r.u8()
                    off = self._expr(r)
                    self.elems.append((table, off, [r.u() for _ in range(r.u())]))
                elif flag in (1, 3):
                    r.u8()
                    for _ in range(r.u()):
                        r.u()
                else:
                    raise WasmError("nepodporovaný typ element segmentu")
        elif sid == 10:
            for _ in range(r.u()):
                size = r.u()
                end = r.p + size
                locs = []
                for _ in range(r.u()):
                    n, t = r.u(), r.u8()
                    if n > 50000:
                        raise WasmError("příliš mnoho lokálních proměnných")
                    locs += [t] * n
                self.bodies.append((locs, r.d[r.p:end]))
                r.p = end
        elif sid == 11:
            for _ in range(r.u()):
                flag = r.u()
                if flag == 1:
                    self.datas.append((None, None, r.take(r.u())))
                elif flag in (0, 2):
                    if flag == 2:
                        r.u()
                    off = self._expr(r)
                    self.datas.append((0, off, r.take(r.u())))
                else:
                    raise WasmError("nepodporovaný datový segment")
        # sekce 12 (data count) a ostatní nepotřebujeme


# ---------------------------------------------------------------- předdekódování těla funkce
def _blocktype(r, types):
    b = r.d[r.p]
    if b == 0x40:
        r.p += 1
        return 0, 0
    if b in VALTYPES:
        r.p += 1
        return 0, 1
    idx = r.s(33)
    t = types[idx]
    return len(t.params), len(t.results)


def decode_body(raw, types):
    """Tělo funkce -> seznam n-tic (op, a, b, c) s předpočítanými skoky."""
    r = Reader(raw)
    code, open_ = [], []
    while not r.eof():
        op = r.u8()
        if op in (0x02, 0x03, 0x04):
            np_, nr = _blocktype(r, types)
            open_.append(len(code))
            code.append([op, np_, nr, -1, -1])      # op, params, results, end_pc, else_pc
        elif op == 0x05:
            code[open_[-1]][4] = len(code)
            code.append([0x05, open_[-1]])
        elif op == 0x0B:
            if open_:
                code[open_.pop()][3] = len(code)
            code.append([0x0B])
        elif op in (0x0C, 0x0D):
            code.append([op, r.u()])
        elif op == 0x0E:
            n = r.u()
            tbl = [r.u() for _ in range(n)]
            code.append([op, tbl, r.u()])
        elif op in (0x10,):
            code.append([op, r.u()])
        elif op == 0x11:
            ti = r.u()
            code.append([op, ti, r.u()])
        elif op == 0x1C:
            for _ in range(r.u()):
                r.u8()
            code.append([0x1B])
        elif 0x20 <= op <= 0x24:
            code.append([op, r.u()])
        elif 0x28 <= op <= 0x3E:
            r.u()
            code.append([op, r.u()])
        elif op in (0x3F, 0x40):
            r.u8()
            code.append([op])
        elif op == 0x41:
            code.append([op, r.s(32) & M32])
        elif op == 0x42:
            code.append([op, r.s(64) & M64])
        elif op == 0x43:
            code.append([op, r.f32()])
        elif op == 0x44:
            code.append([op, r.f64()])
        elif op == 0xFC:
            sub = r.u()
            if sub in SAT:
                code.append([0xFC00 + sub])
            elif sub == 8:
                seg = r.u()
                r.u8()
                code.append([0xFC08, seg])
            elif sub == 9:
                code.append([0xFC09, r.u()])
            elif sub == 10:
                r.u8()
                r.u8()
                code.append([0xFC0A])
            elif sub == 11:
                r.u8()
                code.append([0xFC0B])
            else:
                raise WasmError(f"nepodporovaná instrukce 0xFC {sub}")
        elif op in (0x00, 0x01, 0x0F, 0x1A, 0x1B) or 0x45 <= op <= 0xC4:
            code.append([op])
        else:
            raise WasmError(f"nepodporovaná instrukce 0x{op:02x}")
    return code


# ---------------------------------------------------------------- instance
class Memory:
    def __init__(self, pages, max_pages, limit):
        self.max = min(max_pages if max_pages is not None else 65536, limit)
        if pages > self.max:
            raise WasmError(f"modul chce {pages} stránek paměti, limit je {self.max}")
        self.data = bytearray(pages * PAGE)

    def grow(self, n):
        old = len(self.data) // PAGE
        if old + n > self.max:
            return -1
        self.data.extend(bytes(n * PAGE))
        return old


class HostFunc:
    def __init__(self, ftype, fn):
        self.type, self.fn = ftype, fn


class Func:
    __slots__ = ("type", "locals", "raw", "code")

    def __init__(self, ftype, locs, raw):
        self.type, self.locals, self.raw, self.code = ftype, locs, raw, None


class Instance:
    def __init__(self, module, imports=None, fuel=5_000_000, max_pages=256, max_depth=120):
        self.module = module if isinstance(module, Module) else Module(module)
        m = self.module
        imports = imports or {}
        self.fuel_limit, self.fuel, self.max_depth, self.depth = fuel, fuel, max_depth, 0
        self.funcs, self.globals, self.gmut, self.tables, self.memory = [], [], [], [], None
        ftype_idx = 0
        for mod, name, kind, desc in m.imports:
            host = imports.get(mod, {}).get(name)
            if host is None:
                raise WasmError(f"chybí import {mod}.{name}")
            if kind == 0:
                self.funcs.append(HostFunc(m.types[m.func_types[ftype_idx]], host))
                ftype_idx += 1
            elif kind == 2:
                self.memory = host
            elif kind == 3:
                self.globals.append(host)
                self.gmut.append(False)
            else:
                raise WasmError(f"nepodporovaný import {mod}.{name} (tabulky)")
        for i, (locs, raw) in enumerate(m.bodies):
            self.funcs.append(Func(m.types[m.func_types[ftype_idx + i]], locs, raw))
        for mn, mx in m.mems:
            self.memory = Memory(mn, mx, max_pages)
        for mn, mx in m.tables:
            self.tables.append([None] * mn)
        for vt, mut, expr in m.globals:
            self.globals.append(self._const(expr))
            self.gmut.append(bool(mut))
        for table, off, idxs in m.elems:
            o = self._const(off)
            if o + len(idxs) > len(self.tables[table]):
                raise WasmError("element segment mimo tabulku")
            self.tables[table][o:o + len(idxs)] = idxs
        self.passive = {}
        for i, (mem, off, data) in enumerate(m.datas):
            if mem is None:
                self.passive[i] = data
            else:
                o = self._const(off)
                if self.memory is None or o + len(data) > len(self.memory.data):
                    raise WasmError("datový segment mimo paměť")
                self.memory.data[o:o + len(data)] = data
        if m.start is not None:
            self._invoke(m.start, [])

    def _const(self, expr):
        kind, v = expr
        return v if kind == "const" else self.globals[v]

    # ---------- veřejné API ----------
    def has(self, name):
        return name in self.module.exports and self.module.exports[name][0] == 0

    def exported_memory(self):
        e = self.module.exports.get("memory")
        return self.memory if e and e[0] == 2 else None

    def call(self, name, *args):
        e = self.module.exports.get(name)
        if not e or e[0] != 0:
            raise WasmError(f"modul neexportuje funkci {name}")
        f = self.funcs[e[1]]
        if len(args) != len(f.type.params):
            raise WasmError(f"{name} čeká {len(f.type.params)} argumentů, dostala {len(args)}")
        conv = []
        for a, t in zip(args, f.type.params):
            conv.append((a & M32) if t == I32 else (a & M64) if t == I64 else f32r(float(a)) if t == F32 else float(a))
        self.fuel, self.depth = self.fuel_limit, 0
        res = self._invoke(e[1], conv)
        out = [s32(v) if t == I32 else s64(v) if t == I64 else v for v, t in zip(res, f.type.results)]
        return None if not out else out[0] if len(out) == 1 else tuple(out)

    def read(self, ptr, n):
        mem = self.exported_memory()
        if mem is None or ptr < 0 or n < 0 or ptr + n > len(mem.data):
            raise Trap("čtení mimo paměť modulu")
        return bytes(mem.data[ptr:ptr + n])

    def write(self, ptr, data):
        mem = self.exported_memory()
        if mem is None or ptr < 0 or ptr + len(data) > len(mem.data):
            raise Trap("zápis mimo paměť modulu")
        mem.data[ptr:ptr + len(data)] = data

    # ---------- vykonávání ----------
    def _invoke(self, fidx, args):
        f = self.funcs[fidx]
        if isinstance(f, HostFunc):
            r = f.fn(*args)
            if r is None:
                return []
            return list(r) if isinstance(r, (tuple, list)) else [r]
        self.depth += 1
        if self.depth > self.max_depth:
            raise Trap("příliš hluboká rekurze")
        try:
            if f.code is None:
                f.code = decode_body(f.raw, self.module.types)
            return self._run(f, args)
        finally:
            self.depth -= 1

    def _run(self, f, args):
        code = f.code
        loc = list(args) + [0.0 if t in (F32, F64) else 0 for t in f.locals]
        st, labels, pc = [], [], 0
        n = len(code)
        nres = len(f.type.results)
        mem = self.memory
        glob = self.globals
        # implicitní návěští celé funkce
        labels.append((n, 0, nres, False))
        while pc < n:
            ins = code[pc]
            op = ins[0]
            pc += 1
            if op == 0x20:
                st.append(loc[ins[1]])
            elif op == 0x21:
                loc[ins[1]] = st.pop()
            elif op == 0x22:
                loc[ins[1]] = st[-1]
            elif op in BIN:
                b = st.pop()
                st[-1] = BIN[op](st[-1], b)
            elif op in UN:
                st[-1] = UN[op](st[-1])
            elif op == 0x41 or op == 0x42 or op == 0x43 or op == 0x44:
                st.append(ins[1])
            elif op == 0x0B:
                if labels:
                    labels.pop()
            elif op == 0x02:
                labels.append((ins[3] + 1, len(st) - ins[1], ins[2], False))
            elif op == 0x03:
                labels.append((pc, len(st) - ins[1], ins[1], True))
            elif op == 0x04:
                cond = st.pop()
                if cond:
                    labels.append((ins[3] + 1, len(st) - ins[1], ins[2], False))
                elif ins[4] >= 0:
                    labels.append((ins[3] + 1, len(st) - ins[1], ins[2], False))
                    pc = ins[4] + 1
                else:
                    pc = ins[3] + 1
            elif op == 0x05:
                pc = code[ins[1]][3]                # konec then-větve -> na `end`, který shodí návěští
            elif op in (0x0C, 0x0D, 0x0E):
                if op == 0x0D:
                    if not st.pop():
                        continue
                    depth = ins[1]
                elif op == 0x0E:
                    i = st.pop()
                    depth = ins[1][i] if i < len(ins[1]) else ins[2]
                else:
                    depth = ins[1]
                idx = len(labels) - 1 - depth
                target, height, arity, is_loop = labels[idx]
                if arity:
                    vals = st[len(st) - arity:]
                    del st[height:]
                    st.extend(vals)
                else:
                    del st[height:]
                if is_loop:
                    del labels[idx + 1:]
                    self.fuel -= 1
                    if self.fuel < 0:
                        raise Trap("vypršel limit instrukcí (nekonečná smyčka?)")
                else:
                    del labels[idx:]
                pc = target
                if idx == 0:                        # skok na návěští funkce = návrat
                    break
            elif op == 0x0F:
                break
            elif op == 0x10:
                callee = self.funcs[ins[1]]
                k = len(callee.type.params)
                a = st[len(st) - k:] if k else []
                if k:
                    del st[len(st) - k:]
                self.fuel -= 1
                if self.fuel < 0:
                    raise Trap("vypršel limit instrukcí (nekonečná rekurze?)")
                st.extend(self._invoke(ins[1], a))
            elif op == 0x11:
                i = st.pop()
                table = self.tables[ins[2]]
                if i >= len(table) or table[i] is None:
                    raise Trap("call_indirect: prázdný prvek tabulky")
                callee = self.funcs[table[i]]
                if callee.type != self.module.types[ins[1]]:
                    raise Trap("call_indirect: nesedí typ funkce")
                k = len(callee.type.params)
                a = st[len(st) - k:] if k else []
                if k:
                    del st[len(st) - k:]
                self.fuel -= 1
                if self.fuel < 0:
                    raise Trap("vypršel limit instrukcí")
                st.extend(self._invoke(table[i], a))
            elif op == 0x23:
                st.append(glob[ins[1]])
            elif op == 0x24:
                glob[ins[1]] = st.pop()
            elif op in LOAD_SIZES or op in (0x2A, 0x2B):
                ea = st.pop() + ins[1]
                data = mem.data
                if op == 0x2A:
                    if ea + 4 > len(data):
                        raise Trap("čtení mimo paměť")
                    st.append(struct.unpack_from("<f", data, ea)[0])
                elif op == 0x2B:
                    if ea + 8 > len(data):
                        raise Trap("čtení mimo paměť")
                    st.append(struct.unpack_from("<d", data, ea)[0])
                else:
                    size, signed, bits = LOAD_SIZES[op]
                    if ea + size > len(data):
                        raise Trap("čtení mimo paměť")
                    v = int.from_bytes(data[ea:ea + size], "little", signed=signed)
                    st.append(v & (M32 if bits == 32 else M64))
            elif op in STORE_SIZES or op in (0x38, 0x39):
                v = st.pop()
                ea = st.pop() + ins[1]
                data = mem.data
                if op == 0x38:
                    if ea + 4 > len(data):
                        raise Trap("zápis mimo paměť")
                    struct.pack_into("<f", data, ea, v) if v == v and abs(v) != math.inf else \
                        data.__setitem__(slice(ea, ea + 4), struct.pack("<f", f32r(v)))
                elif op == 0x39:
                    if ea + 8 > len(data):
                        raise Trap("zápis mimo paměť")
                    struct.pack_into("<d", data, ea, v)
                else:
                    size = STORE_SIZES[op]
                    if ea + size > len(data):
                        raise Trap("zápis mimo paměť")
                    data[ea:ea + size] = (v & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
            elif op == 0x1A:
                st.pop()
            elif op == 0x1B:
                c, b = st.pop(), st.pop()
                if not c:
                    st[-1] = b
            elif op == 0x3F:
                st.append(len(mem.data) // PAGE)
            elif op == 0x40:
                st.append(mem.grow(st.pop()) & M32)
            elif op == 0x00:
                raise Trap("unreachable")
            elif op == 0x01:
                pass
            elif op >= 0xFC00:
                sub = op - 0xFC00
                if sub in SAT:
                    st[-1] = SAT[sub](st[-1])
                elif sub == 8:
                    cnt, src, dst = st.pop(), st.pop(), st.pop()
                    seg = self.passive.get(ins[1], b"")
                    if src + cnt > len(seg) or dst + cnt > len(mem.data):
                        raise Trap("memory.init mimo rozsah")
                    mem.data[dst:dst + cnt] = seg[src:src + cnt]
                elif sub == 9:
                    self.passive[ins[1]] = b""
                elif sub == 10:
                    cnt, src, dst = st.pop(), st.pop(), st.pop()
                    if src + cnt > len(mem.data) or dst + cnt > len(mem.data):
                        raise Trap("memory.copy mimo rozsah")
                    mem.data[dst:dst + cnt] = mem.data[src:src + cnt]
                elif sub == 11:
                    cnt, val, dst = st.pop(), st.pop(), st.pop()
                    if dst + cnt > len(mem.data):
                        raise Trap("memory.fill mimo rozsah")
                    mem.data[dst:dst + cnt] = bytes([val & 0xFF]) * cnt
            else:
                raise Trap(f"neznámá instrukce 0x{op:02x}")
        return st[len(st) - nres:] if nres else []
