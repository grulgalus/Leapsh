"""Generátor kostry pluginu / tématu / addonu ze složky templates/."""
import re
import shutil
from pathlib import Path

from .config import APP_DIR, config_dir

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def scaffold(kind, name, target=None, root=None):
    """kind: plugin | theme | addon | wasm-wat | wasm-c. root = adresář, kam se složka pluginu vytvoří."""
    from .settings import RESERVED_NAMES
    if name in RESERVED_NAMES:
        raise ValueError(f"název {name} je rezervovaný (složka plugins/{name}/ má jiný účel)")
    if not NAME_RE.match(name):
        raise ValueError("název smí obsahovat jen malá písmena, číslice a _ (a začínat písmenem)")
    src = APP_DIR / "templates" / kind
    if not src.is_dir():
        raise FileNotFoundError(f"chybí šablona {src}")
    base = Path(root) if root else config_dir() / ("addons" if kind == "addon" else "plugins")
    dest = base / name
    if dest.exists():
        raise FileExistsError(f"{dest} už existuje")
    shutil.copytree(src, dest)
    cls = "".join(p.capitalize() for p in name.split("_"))
    for f in dest.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            text = (text.replace("__NAME__", name).replace("__CLASS__", cls)
                    .replace("__TARGET__", target or "git_prompt")
                    .replace("__THEME__", name.removeprefix("theme_")))
            f.write_text(text, encoding="utf-8")
    return dest
