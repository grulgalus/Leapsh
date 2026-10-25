"""Řádkový editor s událostmi kláves (raw režim terminálu)."""
import os
import re
import select
import sys

try:
    import termios
except ImportError:  # např. Windows – shell poběží jen v neinteraktivním režimu
    termios = None

from ._fast import term_size
from .theme import RESET, visible_len

CSI_TILDE = {"1": "home", "2": "insert", "3": "delete", "4": "end", "5": "pageup", "6": "pagedown",
             "7": "home", "8": "end", "15": "f5", "17": "f6", "18": "f7", "19": "f8",
             "20": "f9", "21": "f10", "23": "f11", "24": "f12"}
CSI_FINAL = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
             "P": "f1", "Q": "f2", "R": "f3", "S": "f4"}


class LineEditor:
    def __init__(self, shell):
        self.shell = shell
        self.buffer = ""
        self.cursor = 0
        self.prompt = ""
        self.rprompt = ""
        self.done = False
        self.result = None
        self._hist_idx = None
        self._hist_stash = ""
        self._in_change = False
        self._idle_reset = False
        self._pprefix, self._pidx = None, 0
        self._tab = None
        self.fd = None

    # ================= API pro pluginy =================
    def insert(self, text):
        self.buffer = self.buffer[:self.cursor] + text + self.buffer[self.cursor:]
        self.cursor += len(text)

    def set_buffer(self, text, cursor=None):
        self.buffer = text
        self.cursor = len(text) if cursor is None else max(0, min(cursor, len(text)))

    def move(self, pos):
        self.cursor = max(0, min(pos, len(self.buffer)))

    def submit(self):
        self.done = True
        self.result = self.buffer
        self._hist_idx = None
        self.redraw(final=True)

    def print_above(self, text):
        """Vypíše text nad řádek a řádek překreslí."""
        sys.stdout.write("\r\x1b[K" + text.replace("\n", "\r\n") + "\r\n")
        self.redraw()

    def reset_idle(self):
        """Plugin po dlouhé akci (spořič) vynuluje počítadlo nečinnosti."""
        self._idle_reset = True

    def bell(self):
        sys.stdout.write("\a")
        sys.stdout.flush()

    # ================= čtení řádku =================
    def read_line(self, prompt=None):
        """Přečte řádek. S prompt=... vykreslí jen tento krátký prompt (pokračovací řádky heredocu)."""
        if termios is None or not sys.stdin.isatty() or not sys.stdout.isatty():
            line = sys.stdin.readline()
            return None if line == "" else line.rstrip("\n")
        if prompt is None:
            head, last, rprompt = self.shell.render_prompt()
        else:
            head, last, rprompt = "", prompt, ""
        if head:
            sys.stdout.write(head + RESET + "\r\n")
        self.prompt = last + RESET
        self.rprompt = rprompt
        self.buffer, self.cursor = "", 0
        self.done, self.result = False, None
        self._hist_idx = None
        self._tab = None
        fd = self.fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            new = termios.tcgetattr(fd)
            new[0] &= ~(termios.ICRNL | termios.INLCR | termios.IXON | termios.ISTRIP)
            new[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
            new[6][termios.VMIN] = 1
            new[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            self.redraw()
            while not self.done:
                name, ch = self._read_key(fd)
                self._dispatch(name, ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()
        return self.result

    def _dispatch(self, name, ch):
        before = self.buffer
        if name not in ("pageup", "pagedown"):
            self._pprefix = None
        if name not in ("tab", "shift-tab"):
            self._tab = None
        ev = self.shell.events.emit("key", key=name, char=ch, buffer=self.buffer,
                                    cursor=self.cursor, editor=self)
        if not ev.cancelled:
            self._default(name, ch)
        if self.buffer != before and not self.done and not self._in_change:
            self._in_change = True
            try:
                self.shell.events.emit("input_change", buffer=self.buffer, previous=before,
                                       cursor=self.cursor, editor=self)
            finally:
                self._in_change = False
        if not self.done:
            self.redraw()

    # ================= čtení kláves =================
    def _read_byte(self, fd):
        idle = 0
        while not select.select([fd], [], [], 1.0)[0]:
            idle += 1
            self.shell.events.emit("idle", seconds=idle, editor=self)
            if self._idle_reset:
                idle, self._idle_reset = 0, False
        return os.read(fd, 1)

    def _read_key(self, fd):
        b = self._read_byte(fd)
        if not b:
            return "ctrl-d", ""
        c = b[0]
        if c == 0x1b:
            if not select.select([fd], [], [], 0.05)[0]:
                return "esc", ""
            n = os.read(fd, 1)
            if n == b"[":
                return self._read_csi(fd), ""
            if n == b"O":
                f = os.read(fd, 1).decode("latin-1")
                return CSI_FINAL.get(f, "esc"), ""
            if n == b"\x7f":
                return "alt-backspace", ""
            if n:
                return "alt-" + n.decode("latin-1", "replace"), ""
            return "esc", ""
        if c in (13, 10):
            return "enter", ""
        if c == 9:
            return "tab", ""
        if c in (127, 8):
            return "backspace", ""
        if c < 32:
            return "ctrl-" + chr(c + 96), ""
        n = 3 if c >= 0xF0 else 2 if c >= 0xE0 else 1 if c >= 0xC0 else 0
        data = bytes([c])
        for _ in range(n):
            data += os.read(fd, 1)
        ch = data.decode("utf-8", "replace")
        return ch, ch

    def _read_csi(self, fd):
        params = ""
        final = ""
        while True:
            b = os.read(fd, 1)
            if not b:
                return "esc"
            c = b.decode("latin-1")
            if "@" <= c <= "~":
                final = c
                break
            params += c
        nums = params.split(";")
        mod = int(nums[1]) - 1 if len(nums) > 1 and nums[1].isdigit() else 0
        prefix = ("ctrl-" if mod & 4 else "") + ("alt-" if mod & 2 else "") + ("shift-" if mod & 1 else "")
        if final == "Z":
            return "shift-tab"
        if final == "~":
            return prefix + CSI_TILDE.get(nums[0], "unknown")
        return prefix + CSI_FINAL.get(final, "unknown")

    # ================= výchozí klávesy =================
    def _word_back(self):
        i = self.cursor
        while i > 0 and self.buffer[i - 1].isspace():
            i -= 1
        while i > 0 and not self.buffer[i - 1].isspace():
            i -= 1
        return i

    def _word_fwd(self):
        i, n = self.cursor, len(self.buffer)
        while i < n and self.buffer[i].isspace():
            i += 1
        while i < n and not self.buffer[i].isspace():
            i += 1
        return i

    def _default(self, name, ch):
        b, c = self.buffer, self.cursor
        if ch and len(ch) >= 1 and name == ch and ch >= " " and ch != "\x7f":
            self.insert(ch)
        elif name == "enter":
            self.submit()
        elif name == "backspace":
            if c > 0:
                self.buffer, self.cursor = b[:c - 1] + b[c:], c - 1
        elif name == "delete":
            self.buffer = b[:c] + b[c + 1:]
        elif name in ("left", "ctrl-b"):
            self.move(c - 1)
        elif name in ("right", "ctrl-f"):
            self.move(c + 1)
        elif name in ("home", "ctrl-a"):
            self.move(0)
        elif name in ("end", "ctrl-e"):
            self.move(len(b))
        elif name in ("ctrl-left", "alt-b"):
            self.move(self._word_back())
        elif name in ("ctrl-right", "alt-f"):
            self.move(self._word_fwd())
        elif name in ("up", "ctrl-p"):
            self._history(-1)
        elif name in ("down", "ctrl-n"):
            self._history(1)
        elif name == "tab":
            self._complete()
        elif name == "shift-tab":
            self._complete(-1)
        elif name == "ctrl-r":
            self._reverse_search()
        elif name in ("pageup", "pagedown"):
            self._history_prefix(-1 if name == "pageup" else 1)
        elif name == "ctrl-c":
            self.result, self.done = "", True
            self.buffer = b
            self.redraw(final=True)
            sys.stdout.write("^C")
        elif name == "ctrl-d":
            if not b:
                self.result, self.done = None, True
            else:
                self.buffer = b[:c] + b[c + 1:]
        elif name == "ctrl-l":
            sys.stdout.write("\x1b[H\x1b[2J")
        elif name == "ctrl-u":
            self.buffer, self.cursor = b[c:], 0
        elif name == "ctrl-k":
            self.buffer = b[:c]
        elif name in ("ctrl-w", "alt-backspace"):
            i = self._word_back()
            self.buffer, self.cursor = b[:i] + b[c:], i

    def _history_prefix(self, step):
        """PageUp/PageDown: najde v historii příkaz začínající tím, co už je napsáno."""
        hist = self.shell.history
        if self._pprefix is None:
            self._pprefix, self._pidx = self.buffer, len(hist)
        i = self._pidx + step
        while 0 <= i < len(hist) and not hist[i].startswith(self._pprefix):
            i += step
        if 0 <= i < len(hist):
            self._pidx = i
            self.set_buffer(hist[i])
        elif step > 0:
            self._pidx = len(hist)
            self.set_buffer(self._pprefix)
        else:
            self.bell()

    def _reverse_search(self):
        """Ctrl-R: průběžné hledání v historii. Enter spustí, Esc/Ctrl-G/Ctrl-C zruší, jiná klávesa vloží nález."""
        hist, query, pos = self.shell.history, "", None
        saved = (self.buffer, self.cursor)

        def find(start):
            q = query.lower()
            for i in range(min(start, len(hist) - 1), -1, -1):
                if q in hist[i].lower():
                    return i
            return None

        while True:
            text = hist[pos] if pos is not None else ""
            miss = " \x1b[31m(nenalezeno)\x1b[0m" if query and pos is None else ""
            cols = term_size()[0]
            line = f"(hledání)`{query}': {text}"[:max(10, cols - 14)]
            sys.stdout.write(f"\r\x1b[K\x1b[2m(hledání)\x1b[0m`{query}': {line[len('(hledání)`' + query + chr(39) + ': '):]}{miss}")
            sys.stdout.flush()
            name, ch = self._read_key(self.fd)
            if name == "ctrl-r":
                p = find((pos - 1) if pos is not None else len(hist) - 1)
                if p is None:
                    self.bell()
                else:
                    pos = p
            elif name == "backspace":
                query = query[:-1]
                pos = find(len(hist) - 1) if query else None
            elif ch and name == ch and ch >= " ":
                query += ch
                pos = find(pos if pos is not None else len(hist) - 1)
            elif name in ("esc", "ctrl-g", "ctrl-c"):
                self.buffer, self.cursor = saved
                return
            else:
                if pos is not None:
                    self.set_buffer(hist[pos])
                else:
                    self.buffer, self.cursor = saved
                if name == "enter" and pos is not None:
                    self.submit()
                return

    def _history(self, step):
        hist = self.shell.history
        if step < 0:
            if not hist:
                return
            if self._hist_idx is None:
                self._hist_stash = self.buffer
                self._hist_idx = len(hist) - 1
            else:
                self._hist_idx = max(0, self._hist_idx - 1)
            self.set_buffer(hist[self._hist_idx])
        else:
            if self._hist_idx is None:
                return
            self._hist_idx += 1
            if self._hist_idx >= len(hist):
                self._hist_idx = None
                self.set_buffer(self._hist_stash)
            else:
                self.set_buffer(hist[self._hist_idx])

    # ================= doplňování =================
    def _complete(self, step=1):
        """Tab: doplní, při nejednoznačnosti ukáže nabídku; další Tab (Shift-Tab zpět) prochází kandidáty."""
        t = self._tab
        if t and self.buffer == t["expected"] and self.cursor == t["cursor"]:
            if t["idx"] < 0 and step < 0:
                t["idx"] = 0
            t["idx"] = (t["idx"] + step) % len(t["cands"])
            text = t["cands"][t["idx"]]
            self.buffer = t["head"] + text + t["tail"]
            self.cursor = len(t["head"]) + len(text)
            t["expected"], t["cursor"] = self.buffer, self.cursor
            return
        self._tab = None
        if step < 0:
            return
        left = self.buffer[:self.cursor]
        m = re.search(r"[^\s|;&<>]*$", left)
        word, start = m.group(0), m.start()
        before = left[:start].rstrip()
        first = before == "" or before.endswith(("|", ";", "&&", "||", "&", "("))
        dirs_only = before.split()[-1:] in (["cd"], ["pushd"]) if before else False
        cands = []
        if word == "~":
            cands = ["~/"]
        elif first and "/" not in word and not word.startswith((".", "~")):
            cands += self._command_candidates(word)
        else:
            cands += self._file_candidates(word, dirs_only)
        ev = self.shell.events.emit("complete", word=word, first=first, buffer=self.buffer, left=left,
                                    dirs_only=dirs_only, editor=self, candidates=cands)
        cands = sorted(set(ev.data["candidates"]))
        if not cands:
            self.bell()
            return
        if len(cands) == 1:
            text = cands[0] + ("" if cands[0].endswith("/") else " ")
            self.buffer = self.buffer[:start] + text + self.buffer[self.cursor:]
            self.cursor = start + len(text)
            return
        common = os.path.commonprefix(cands)
        if len(common) > len(word) and (not ev.data.get("ignore_case") or common.lower().startswith(word.lower())):
            self.buffer = self.buffer[:start] + common + self.buffer[self.cursor:]
            self.cursor = start + len(common)
            return
        cols = term_size()[0]
        w = max(len(x) for x in cands) + 2
        per = max(1, cols // w)
        sys.stdout.write("\r\n")
        for i in range(0, len(cands), per):
            row = ""
            for x in cands[i:i + per]:
                pad = " " * (w - len(x))
                row += (f"\x1b[1;34m{x}\x1b[0m" if x.endswith("/") else x) + pad
            sys.stdout.write(row.rstrip() + "\r\n")
        if self.shell.config.data.get("tab_cycle", True):
            self._tab = {"head": self.buffer[:start], "tail": self.buffer[self.cursor:], "cands": cands, "idx": -1,
                         "expected": self.buffer, "cursor": self.cursor}

    def _command_candidates(self, word, ic=False):
        names = set(self.shell.commands) | set(self.shell.aliases) | self.shell.executables()
        if ic:
            w = word.lower()
            return [n for n in names if n.lower().startswith(w)]
        return [n for n in names if n.startswith(word)]

    def _file_candidates(self, word, dirs_only=False, ic=False):
        expanded = os.path.expanduser(word)
        d, base = os.path.split(expanded)
        shown = word[:len(word) - len(base)]
        out = []
        try:
            names = os.listdir(d or ".")
        except OSError:
            return out
        b = base.lower() if ic else base
        for n in names:
            if not (n.lower() if ic else n).startswith(b) or (n.startswith(".") and not base.startswith(".")):
                continue
            isdir = os.path.isdir(os.path.join(d or ".", n))
            if dirs_only and not isdir:
                continue
            out.append(shown + n.replace(" ", "\\ ") + ("/" if isdir else ""))
        return out

    # ================= vykreslení =================
    def redraw(self, final=False):
        cols = term_size()[0]
        pw = visible_len(self.prompt)
        avail = max(8, cols - pw - 1)
        buf, cur = self.buffer, self.cursor
        ev = self.shell.events.emit("input_render", buffer=buf, cursor=cur, ghost="", styler=None)
        ghost = (ev.data.get("ghost") or "") if (cur == len(buf) and not final) else ""
        start = max(0, cur - avail)
        view = buf[start:start + avail]
        ghost = ghost[:max(0, avail - len(view))]
        shown = view
        styler = ev.data.get("styler")
        if styler and view:
            try:
                shown = styler(view)
            except Exception as exc:
                self.shell.report_error("styler", "input_render", exc)
        out = "\r" + self.prompt + shown
        if ghost:
            out += "\x1b[90m" + ghost + RESET
        out += "\x1b[K"
        rl = visible_len(self.rprompt)
        if not final and self.rprompt and pw + visible_len(view) + visible_len(ghost) + rl + 2 < cols:
            out += f"\x1b[{cols - rl}G" + self.rprompt + RESET
        if not final:
            out += f"\r\x1b[{pw + visible_len(view[:cur - start]) + 1}G"
        sys.stdout.write(out)
        sys.stdout.flush()
