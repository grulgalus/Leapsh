"""Malé náhrady těžkých modulů standardní knihovny (shutil, socket…), aby start shellu byl rychlý."""
import os


def which(cmd, path=None):
    """Jako shutil.which, ale bez importu shutil (ten tahá kompresní moduly)."""
    if os.sep in cmd:
        return cmd if os.path.isfile(cmd) and os.access(cmd, os.X_OK) else None
    for d in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        p = os.path.join(d or ".", cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def term_size(default=(80, 24)):
    """(sloupce, řádky) terminálu."""
    try:
        return tuple(os.get_terminal_size(1))
    except (OSError, ValueError):
        try:
            return tuple(os.get_terminal_size(0))
        except (OSError, ValueError):
            return (int(os.environ.get("COLUMNS") or default[0]), int(os.environ.get("LINES") or default[1]))


def hostname():
    try:
        return os.uname().nodename.split(".")[0]
    except (AttributeError, OSError):
        return "localhost"
