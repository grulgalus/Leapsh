import contextlib
import json
import os
import random
import select
import sys
import time

try:
    import termios
except ImportError:
    termios = None

from leapsh._fast import term_size
from leapsh.api import Plugin
from leapsh.config import config_dir

ARROWS = {b"\x1b[A": "up", b"\x1b[B": "down", b"\x1b[C": "right", b"\x1b[D": "left",
          b"\x1bOA": "up", b"\x1bOB": "down", b"\x1bOC": "right", b"\x1bOD": "left"}
LETTERS = {b"w": "up", b"s": "down", b"d": "right", b"a": "left", b"k": "up", b"j": "down", b"l": "right", b"h": "left"}


@contextlib.contextmanager
def cbreak(fd):
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[0] &= ~(termios.ICRNL | termios.IXON)
    new[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
    new[6][termios.VMIN], new[6][termios.VTIME] = 1, 0
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def swallow_key(fd):
    """Spolkne jen jednu stisknutou klávesu (i vícebajtovou), ne celý zbytek vstupu."""
    b = os.read(fd, 1)
    extra = 0
    if b == b"\x1b":
        while extra < 6 and select.select([fd], [], [], 0.02)[0]:
            os.read(fd, 1)
            extra += 1
    elif b and b[0] >= 0xC0:
        for _ in range(3 if b[0] >= 0xF0 else 2 if b[0] >= 0xE0 else 1):
            os.read(fd, 1)


@contextlib.contextmanager
def alt_screen():
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


class SnakeGame:
    """Čistá logika hada (bez terminálu, aby šla testovat)."""
    DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    def __init__(self, w, h, rng=None):
        self.w, self.h, self.rng = w, h, rng or random.Random()
        cx, cy = w // 2, h // 2
        self.body = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.dir = self.pending = "right"
        self.score, self.alive = 0, True
        self.food = self._new_food()

    def turn(self, d):
        if d in self.DIRS:
            dx, dy = self.DIRS[self.dir]
            if self.DIRS[d] != (-dx, -dy):
                self.pending = d

    def _new_food(self):
        free = [(x, y) for x in range(self.w) for y in range(self.h) if (x, y) not in self.body]
        return self.rng.choice(free) if free else None

    def step(self):
        self.dir = self.pending
        dx, dy = self.DIRS[self.dir]
        nx, ny = self.body[0][0] + dx, self.body[0][1] + dy
        if not (0 <= nx < self.w and 0 <= ny < self.h) or (nx, ny) in self.body[:-1]:
            self.alive = False
            return False
        self.body.insert(0, (nx, ny))
        if (nx, ny) == self.food:
            self.score += 1
            self.food = self._new_food()
        else:
            self.body.pop()
        return True


TRAIN = [
    r"      _______                                                  ",
    r"  ___/ _____ \___   _________   _________   _________   ______ ",
    r" |  _ | | o | |  | |  _ _ _  | |  _ _ _  | |  _ _ _  | |  __  |",
    r" |_|_|_|_____|__|_|_|_|_|_|__|_|_|_|_|_|__|_|_|_|_|_|__|_|__|_|",
    r"   (O)  (O)  (O)    (o)(o)       (o)(o)       (o)(o)      (o)  ",
]


class Arcade(Plugin):
    def on_load(self):
        self.add_command("snake", self.cmd_snake, "hra had (šipky/WASD, q = konec)")
        self.add_command("train", self.cmd_train, "projede vlak")
        self.add_command("matrix", self.cmd_matrix, "matrix déšť; matrix [sekundy]; libovolná klávesa ukončí")
        self.on("idle", self.on_idle)

    # ---------- společné ----------
    def _tty(self, shell):
        if termios is None or not (sys.stdin.isatty() and sys.stdout.isatty()):
            shell.say("tohle potřebuje interaktivní terminál")
            return False
        return True

    # ---------- matrix ----------
    def run_matrix(self, fd, max_seconds=None):
        cols, rows = term_size()
        cols -= 1
        chars = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ$#@%&*+=<>"
        drops = [random.randint(-rows, 0) for _ in range(cols)]
        trail = [random.randint(5, max(6, rows // 2)) for _ in range(cols)]
        t0 = time.time()
        with alt_screen():
            while True:
                if select.select([fd], [], [], 0.06)[0]:
                    swallow_key(fd)
                    break
                if max_seconds and time.time() - t0 > max_seconds:
                    break
                buf = []
                for x in range(cols):
                    if random.random() < 0.3:
                        continue
                    y = drops[x]
                    if 0 <= y < rows:
                        buf.append(f"\x1b[{y + 1};{x + 1}H\x1b[1;97m{random.choice(chars)}")
                    if 0 <= y - 1 < rows:
                        buf.append(f"\x1b[{y};{x + 1}H\x1b[0;32m{random.choice(chars)}")
                    tail = y - trail[x]
                    if 0 <= tail < rows:
                        buf.append(f"\x1b[{tail + 1};{x + 1}H ")
                    drops[x] += 1
                    if tail > rows:
                        drops[x], trail[x] = random.randint(-8, 0), random.randint(5, max(6, rows // 2))
                sys.stdout.write("".join(buf))
                sys.stdout.flush()

    def cmd_matrix(self, shell, args):
        if not self._tty(shell):
            return 1
        secs = float(args[0]) if args and args[0].replace(".", "", 1).isdigit() else None
        fd = sys.stdin.fileno()
        with cbreak(fd):
            self.run_matrix(fd, secs)
        return 0

    def on_idle(self, ev):
        if self.setting("screensaver", True) and ev.seconds >= int(self.setting("idle_seconds", 60)):
            self.run_matrix(ev.editor.fd)
            ev.editor.reset_idle()
            ev.editor.redraw()

    # ---------- vlak ----------
    def cmd_train(self, shell, args):
        if not self._tty(shell):
            return 1
        cols, rows = term_size()
        width = max(len(r) for r in TRAIN)
        top = max(1, rows // 2 - len(TRAIN) // 2)
        fd = sys.stdin.fileno()
        with cbreak(fd), alt_screen():
            for offset in range(cols + width):
                if select.select([fd], [], [], 0.025)[0]:
                    swallow_key(fd)
                    break
                x = cols - offset
                lines = []
                for i, row in enumerate(TRAIN):
                    row = row.ljust(width)
                    seg = (" " * x + row)[:cols] if x >= 0 else row[-x:cols - x]
                    lines.append(f"\x1b[{top + i};1H\x1b[33m{seg.ljust(cols)}")
                sys.stdout.write("".join(lines))
                sys.stdout.flush()
        return 0

    # ---------- snake ----------
    def _best(self):
        try:
            return int(json.loads((config_dir() / "snake.json").read_text(encoding="utf-8")).get("best", 0))
        except (OSError, ValueError):
            return 0

    def _save_best(self, n):
        try:
            p = config_dir() / "snake.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"best": n}), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def parse_keys(data):
        """Bajty z klávesnice -> 'quit' / směr / None."""
        if data in (b"q", b"\x03", b"\x1b"):
            return "quit"
        found = None
        for seq, d in ARROWS.items():
            if seq in data:
                found = d
        for i in range(len(data)):
            d = LETTERS.get(data[i:i + 1])
            if d:
                found = d
        return found

    def draw(self, g, best, msg=""):
        top = "┌" + "──" * g.w + "┐"
        rows = []
        cells = set(g.body)
        for y in range(g.h):
            line = []
            for x in range(g.w):
                if (x, y) == g.body[0]:
                    line.append("\x1b[1;92m██\x1b[0m")
                elif (x, y) in cells:
                    line.append("\x1b[32m██\x1b[0m")
                elif (x, y) == g.food:
                    line.append("\x1b[1;31m()\x1b[0m")
                else:
                    line.append("  ")
            rows.append("│" + "".join(line) + "│")
        head = f" SNAKE   skóre {g.score}   rekord {best}   (šipky/WASD, q = konec)"
        out = "\x1b[H" + "\x1b[K\r\n".join([head, top] + rows + ["└" + "──" * g.w + "┘", msg]) + "\x1b[K"
        sys.stdout.write(out)
        sys.stdout.flush()

    def cmd_snake(self, shell, args):
        if not self._tty(shell):
            return 1
        cols, rows = term_size()
        g = SnakeGame(max(10, min((cols - 2) // 2, 36)), max(8, min(rows - 5, 18)))
        best, fd, quit_ = self._best(), sys.stdin.fileno(), False
        with cbreak(fd), alt_screen():
            while g.alive and not quit_:
                self.draw(g, best)
                deadline = time.monotonic() + max(0.05, 0.14 - g.score * 0.003)
                while True:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    if select.select([fd], [], [], left)[0]:
                        k = self.parse_keys(os.read(fd, 16))
                        if k == "quit":
                            quit_ = True
                            break
                        if k:
                            g.turn(k)
                if not quit_:
                    g.step()
            new_best = max(best, g.score)
            if not quit_:
                self.draw(g, new_best, f" GAME OVER – skóre {g.score}" + ("  🎉 nový rekord!" if g.score > best else "") + "   (libovolná klávesa)")
                time.sleep(0.4)
                select.select([fd], [], [], 5)
        if g.score > best:
            self._save_best(g.score)
        shell.say(f"snake: skóre {g.score}, rekord {max(best, g.score)}")
        return 0
