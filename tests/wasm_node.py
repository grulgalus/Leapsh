"""Pomocník pro testy: spustí .wasm ve V8 (node) a vrátí výsledky, aby šlo ověřit náš interpret proti referenci."""
import json
import shutil
import struct
import subprocess

NODE = shutil.which("node")

JS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const bytes = Buffer.from(input.wasm, 'hex');
const dv = new DataView(new ArrayBuffer(8));
function enc(v, t) {
  if (t === 'i32') return v;
  if (t === 'i64') return v.toString();
  if (typeof v !== 'number') return String(v);
  if (Number.isNaN(v)) return 'nan';
  dv.setFloat64(0, v); return dv.getBigUint64(0).toString(16);
}
function dec(a) {
  if (a.t === 'i32') return a.v;
  if (a.t === 'i64') return BigInt(a.v);
  if (a.v === 'nan') return NaN;
  if (a.v === 'inf') return Infinity;
  if (a.v === '-inf') return -Infinity;
  if (a.v === '-0') return -0;
  return Number(a.v);
}
WebAssembly.instantiate(bytes, {}).then(({instance}) => {
  const out = [];
  for (const [name, args, rt] of input.calls) {
    try { out.push(['ok', enc(instance.exports[name](...args.map(dec)), rt)]); }
    catch (e) { out.push(['trap', String(e.message)]); }
  }
  console.log(JSON.stringify(out));
}).catch(e => { console.log(JSON.stringify({error: String(e.message)})); });
"""


def fbits(x):
    return format(struct.unpack("<Q", struct.pack("<d", x))[0], "x")


def run_node(wasm, calls):
    """calls: [(export, [(typ, hodnota)...], typ_výsledku)] -> [('ok', repr) | ('trap', msg)]"""
    payload = {"wasm": wasm.hex(), "calls": [
        [name, [{"t": t, "v": enc_arg(t, v)} for t, v in args], rt] for name, args, rt in calls]}
    r = subprocess.run([NODE, "-e", JS], input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    out = json.loads(r.stdout)
    if isinstance(out, dict):
        raise RuntimeError("node: " + out["error"])
    return out


def enc_arg(t, v):
    if t == "i32":
        return v
    if t == "i64":
        return str(v)
    if v != v:
        return "nan"
    if v in (float("inf"), float("-inf")):
        return "inf" if v > 0 else "-inf"
    if v == 0 and str(v).startswith("-"):
        return "-0"
    return repr(v)


def enc_result(v, rt):
    """Výsledek našeho interpretu ve stejném tvaru jako enc() v JS."""
    if rt == "i32":
        return v
    if rt == "i64":
        return str(v)
    if v != v:
        return "nan"
    return fbits(v)
