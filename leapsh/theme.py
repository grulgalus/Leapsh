"""Barvy a šablony promptu."""
import re
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
RESET = "\x1b[0m"
TOKEN_RE = re.compile(r"\{([^{}]+)\}")
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}$")

_BASE = {
    "black": 30, "red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35,
    "cyan": 36, "white": 37, "gray": 90, "grey": 90, "bright_red": 91,
    "bright_green": 92, "bright_yellow": 93, "bright_blue": 94,
    "bright_magenta": 95, "bright_cyan": 96, "bright_white": 97,
}
_ATTR = {"reset": 0, "bold": 1, "dim": 2, "italic": 3, "underline": 4, "blink": 5, "reverse": 7}


def _token(tok):
    if tok in _ATTR:
        return str(_ATTR[tok])
    bg = tok.startswith("on_")
    t = tok[3:] if bg else tok
    if t in _BASE:
        return str(_BASE[t] + (10 if bg else 0))
    if t.isdigit() and int(t) <= 255:
        return ("48;5;" if bg else "38;5;") + t
    if HEX_RE.match(t):
        r, g, b = int(t[1:3], 16), int(t[3:5], 16), int(t[5:7], 16)
        return ("48;2;" if bg else "38;2;") + f"{r};{g};{b}"
    return None


def style_code(spec):
    """'bold red', '208', '#ff8800', 'on_blue' -> ANSI sekvence (nebo None, když spec není styl)."""
    if not isinstance(spec, str):
        return None
    codes = []
    for tok in spec.replace(",", " ").split():
        c = _token(tok)
        if c is None:
            return None
        codes.append(c)
    return ("\x1b[" + ";".join(codes) + "m") if codes else None


def char_width(c):
    if unicodedata.combining(c):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def visible_len(s):
    """Zobrazená šířka v sloupcích (bez ANSI kódů, emoji = 2 sloupce)."""
    return sum(char_width(c) for c in ANSI_RE.sub("", s))


def render(template, resolve):
    def sub(m):
        try:
            v = resolve(m.group(1).strip())
        except Exception:
            v = ""
        return "" if v is None else str(v)
    return TOKEN_RE.sub(sub, template)
