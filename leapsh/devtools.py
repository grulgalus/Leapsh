"""Nástroje pro autory pluginů: init (kostra), compile (kontrola + sestavení + balíček .leapsh), install."""
import argparse
import ast
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from .config import LEGACY_MANIFESTS, MANIFEST, config_dir
from .scaffold import NAME_RE, scaffold
from .wasm import Module, WasmError
from .loader import detect_runtime, entry_file
from .wasm_plugin import ALLOWED_IMPORTS, locate
from .wat import WatError, assemble

SOURCE_SUFFIXES = (".wat", ".c", ".h", ".rs")


def load_manifest(path):
    mpath = next((Path(path) / n for n in (MANIFEST,) + LEGACY_MANIFESTS if (Path(path) / n).is_file()), None)
    if mpath is None:
        raise FileNotFoundError(f"{path}: chybí {MANIFEST} (je to složka pluginu?)")
    try:
        return json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{mpath}: neplatný JSON ({exc})") from None


KNOWN_KEYS = {"name", "version", "type", "description", "settings", "settings_info", "requires", "extends", "platforms",
              "runtime", "main", "wasm", "commands", "events", "segments", "limits", "permissions", "theme", "themes",
              "completions", "min_shell", "author", "license", "homepage"}


def check_manifest(m):
    errs, warns = [], []
    unknown = sorted(set(m) - KNOWN_KEYS)
    if unknown:
        warns.append("neznámé klíče v config.json (překlep?): " + ", ".join(unknown))
    if not NAME_RE.match(str(m.get("name", ""))):
        errs.append("name: malá písmena, číslice a _ (začíná písmenem)")
    if not m.get("version"):
        warns.append("chybí version")
    if not m.get("description"):
        warns.append("chybí description")
    if m.get("type", "plugin") not in ("plugin", "theme", "addon"):
        errs.append("type: plugin | theme | addon")
    if m.get("type") == "addon" and not m.get("extends"):
        errs.append("addon musí mít extends")
    if m.get("runtime", "python") not in ("python", "wasm"):
        errs.append("runtime: python | wasm")
    if m.get("runtime") == "wasm" and m.get("type", "plugin") != "plugin":
        errs.append("WASM runtime zatím jen pro type=plugin")
    return errs, warns


# ---------------------------------------------------------------- Python
def check_python(path, m):
    errs, warns, src = [], [], Path(path) / "src"
    files = sorted(src.rglob("*.py")) if src.is_dir() else []
    entry = None
    if m.get("type") != "theme":
        try:
            entry = entry_file(src, m, m.get("name", ""))
        except (FileNotFoundError, RuntimeError) as exc:
            errs.append(str(exc))
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), str(f))
        except SyntaxError as exc:
            errs.append(f"{f.relative_to(path)}:{exc.lineno}: {exc.msg}")
            continue
        if f == entry:
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for b in c.bases}
            if not bases & {"Plugin", "Addon"}:
                errs.append(f"{f.relative_to(path)}: žádná třída odvozená od Plugin/Addon")
    return errs, warns, len(files)


# ---------------------------------------------------------------- WASM
def validate_wasm(data, m):
    errs, info = [], []
    try:
        mod = Module(data)
    except WasmError as exc:
        return [f"neplatný modul: {exc}"], info
    for imod, name, kind, _ in mod.imports:
        if imod != "leapsh" or kind != 0 or name not in ALLOWED_IMPORTS:
            errs.append(f"import {imod}.{name}: shell nabízí jen leapsh.{{{', '.join(sorted(ALLOWED_IMPORTS))}}}")
    ex = {n for n, (k, _) in mod.exports.items() if k == 0}
    if mod.exports.get("memory", (None,))[0] != 2:
        errs.append("modul musí exportovat paměť jako 'memory'")
    need = []
    if m.get("commands"):
        need.append("leapsh_command")
    if m.get("events"):
        need.append("leapsh_event")
    if m.get("segments"):
        need.append("leapsh_segment")
    for n in need:
        if n not in ex:
            errs.append(f"manifest to vyžaduje, ale modul neexportuje {n}")
    if need and "leapsh_alloc" not in ex:
        errs.append("chybí export leapsh_alloc (shell přes něj předává řetězce)")
    info.append(f"{len(data)} B, {len(mod.func_types)} funkcí, exporty: {', '.join(sorted(ex))}")
    return errs, info


def build_wasm(path, m, log=print):
    """Zdroj (.wat / .c / .rs) -> src/<wasm>. Vrací (chyby, info)."""
    src = Path(path) / "src"
    try:
        out, source = locate(src, m)
    except RuntimeError as exc:
        return [str(exc)], []
    stem = out.stem
    wat, c, rs = src / f"{stem}.wat", src / f"{stem}.c", src / f"{stem}.rs"
    if wat.is_file():
        try:
            out.write_bytes(assemble(wat.read_text(encoding="utf-8")))
            log(f"  WAT -> {out.name} (vestavěný assembler)")
        except WatError as exc:
            return [f"{wat.name}: {exc}"], []
    elif c.is_file():
        clang = shutil.which("clang")
        if not clang:
            return ["pro .c je potřeba clang + lld (Termux: pkg install clang lld)"], []
        r = subprocess.run([clang, "--target=wasm32", "-nostdlib", "-O2", "-Wl,--no-entry", "-Wl,--allow-undefined",
                            "-o", str(out), str(c)], capture_output=True, text=True)
        if r.returncode:
            return ["clang: " + (r.stderr.strip() or "selhalo")[:1500]], []
        log(f"  C -> {out.name} (clang)")
    elif rs.is_file():
        rustc = shutil.which("rustc")
        if not rustc:
            return ["pro .rs je potřeba rustc s cílem wasm32-unknown-unknown"], []
        r = subprocess.run([rustc, "--target", "wasm32-unknown-unknown", "--crate-type", "cdylib", "-O",
                            "-C", "panic=abort", "-o", str(out), str(rs)], capture_output=True, text=True)
        if r.returncode:
            return ["rustc: " + (r.stderr.strip() or "selhalo")[:1500]], []
        log(f"  Rust -> {out.name} (rustc)")
    elif not out.is_file():
        return [f"chybí zdroj ({stem}.wat / {stem}.c / {stem}.rs) i hotový {out.name}"], []
    errs, info = validate_wasm(out.read_bytes(), m)
    return errs, info


# ---------------------------------------------------------------- balíček
def pack_plugin(path, m, out_dir, include_source=True):
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{m['name']}-{m.get('version', '0')}.leapsh"
    built_wasm = detect_runtime(path, m) == "wasm" and locate(path / "src", m)[0].is_file()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(path.rglob("*")):
            rel = f.relative_to(path)
            if f.is_dir() or "__pycache__" in rel.parts or f.suffix == ".pyc" or rel.parts[0].startswith("."):
                continue
            if not include_source and built_wasm and f.suffix in SOURCE_SUFFIXES:
                continue
            z.write(f, f"{m['name']}/{rel.as_posix()}")
    return out


def compile_plugin(path, out_dir=None, pack=True, include_source=True, log=print):
    """Zkontroluje (a u WASM sestaví) plugin. Vrací (ok, balíček|None)."""
    path = Path(path).resolve()
    try:
        m = load_manifest(path)
    except (OSError, ValueError) as exc:
        log(f"✗ {exc}")
        return False, None
    errs, warns = check_manifest(m)
    log(f"▶ {m.get('name', path.name)} {m.get('version', '')}  [{m.get('type', 'plugin')}, "
        f"{detect_runtime(path, m)}]")
    kind = m.get("type", "plugin")
    if kind == "theme":
        if not (m.get("theme") or m.get("themes")) and not (path / "src").is_dir():
            errs.append("téma nemá klíč theme/themes")
    elif detect_runtime(path, m) == "wasm":
        e, info = build_wasm(path, m, log)
        errs += e
        for line in info:
            log(f"  {line}")
    else:
        e, w, n = check_python(path, m)
        errs += e
        warns += w
        log(f"  zkontrolováno {n} souborů .py")
    for w in warns:
        log(f"  ! {w}")
    for e in errs:
        log(f"  ✗ {e}")
    if errs:
        log(f"✗ {len(errs)} chyb – balíček nevytvořen")
        return False, None
    pkg = None
    if pack:
        pkg = pack_plugin(path, m, out_dir or path.parent, include_source)
        log(f"✓ balíček: {pkg}")
    else:
        log("✓ v pořádku")
    return True, pkg


def install_package(file, force=False, root=None):
    """Rozbalí .leapsh do ~/.config/leapsh/{plugins,addons}. Vrací cílovou složku."""
    file = Path(file)
    with zipfile.ZipFile(file) as z:
        tops = set()
        for n in z.namelist():
            p = Path(n)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"nebezpečná cesta v balíčku: {n}")
            tops.add(p.parts[0])
        if len(tops) != 1:
            raise ValueError("balíček musí obsahovat jedinou složku pluginu")
        top = tops.pop()
        try:
            name = next((n for n in (MANIFEST,) + LEGACY_MANIFESTS if f"{top}/{n}" in z.namelist()), MANIFEST)
            m = json.loads(z.read(f"{top}/{name}").decode("utf-8"))
        except (KeyError, ValueError):
            raise ValueError(f"balíček neobsahuje platný {MANIFEST}") from None
        errs, _ = check_manifest(m)
        if errs:
            raise ValueError("neplatný manifest: " + "; ".join(errs))
        base = Path(root) if root else config_dir() / ("addons" if m.get("type") == "addon" else "plugins")
        dest = base / m["name"]
        if dest.exists():
            if not force:
                raise FileExistsError(f"{dest} už existuje (použij --force)")
            shutil.rmtree(dest)
        base.mkdir(parents=True, exist_ok=True)
        for n in z.namelist():
            if n.endswith("/"):
                continue
            target = base / m["name"] / Path(n).relative_to(top)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
    return dest


# ---------------------------------------------------------------- CLI
def cli_init(argv):
    ap = argparse.ArgumentParser(prog="leapsh-plugin-init", description="Vytvoří kostru pluginu.")
    ap.add_argument("name", help="název (malá písmena, číslice, _)")
    ap.add_argument("--type", choices=("plugin", "addon", "theme"), default="plugin")
    ap.add_argument("--runtime", choices=("python", "wasm"), default="python")
    ap.add_argument("--lang", choices=("wat", "c"), default="wat", help="jazyk WASM pluginu (výchozí wat)")
    ap.add_argument("--extends", help="u addonu: jméno rozšiřovaného pluginu")
    ap.add_argument("--dir", help="kam složku vytvořit (výchozí ~/.config/leapsh/plugins nebo addons)")
    a = ap.parse_args(argv)
    if a.type == "addon" and not a.extends:
        ap.error("addon potřebuje --extends PLUGIN")
    if a.runtime == "wasm" and a.type != "plugin":
        ap.error("WASM runtime je jen pro type=plugin")
    kind = a.type if a.runtime == "python" else f"wasm-{a.lang}"
    try:
        dest = scaffold(kind, a.name, a.extends, a.dir)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ vytvořeno: {dest}")
    for f in sorted(dest.rglob("*")):
        if f.is_file():
            print(f"    {f.relative_to(dest)}")
    if kind == "wasm-wat":
        ok, _ = compile_plugin(dest, pack=False, log=lambda s: None)
        print("  plugin.wasm sestaven" if ok else "  ! sestavení selhalo, spusť leapsh-compile-plugin")
    print("Další kroky: uprav src/, pak  leapsh-compile-plugin " + str(dest) + "  a v leapsh `reload`.")
    return 0


def cli_compile(argv):
    ap = argparse.ArgumentParser(prog="leapsh-compile-plugin", description="Zkontroluje, sestaví a zabalí plugin.")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("-o", "--out", help="složka pro balíček .leapsh (výchozí: nadřazená složka)")
    ap.add_argument("--no-pack", action="store_true", help="jen zkontrolovat/sestavit")
    ap.add_argument("--no-source", action="store_true", help="do balíčku WASM pluginu nedávat zdroje (.wat/.c/.rs)")
    ap.add_argument("--install", action="store_true", help="po sestavení balíček nainstalovat")
    ap.add_argument("--force", action="store_true", help="při --install přepsat existující")
    a = ap.parse_args(argv)
    ok, pkg = compile_plugin(a.path, a.out, pack=not a.no_pack or a.install, include_source=not a.no_source)
    if ok and a.install and pkg:
        try:
            print(f"✓ nainstalováno: {install_package(pkg, a.force)}")
        except (ValueError, FileExistsError, OSError) as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
    return 0 if ok else 1
