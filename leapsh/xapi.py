"""XAPI s oprávněními pro pluginy.

Plugin smí číst baterii, IP, jazyk… až když to uživatel jednou povolí. Volba se uloží do config.json
(klíč "permissions") a jde ji spravovat příkazy `plugin perms` a `plugin revoke`.
"""
import json
import sys

from ._fast import which

PERMS = {
    "read_language": "přečíst jazyk shellu",
    "read_theme": "přečíst aktuální téma",
    "write_config": "zapisovat do konfigurace shellu",
    "read_battery": "přečíst stav baterie",
    "read_network": "zjistit místní IP adresu",
}


def check_perm(shell, key, perm):
    perms = shell.config.data.get("permissions", {}).get(key, {})
    if perm in perms:
        return bool(perms[perm])
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False          # bez terminálu se neptáme a nepovolujeme (nic se neukládá)
    print(f"\n\x1b[1;41;37m 🛡️ LEAPSH SECURITY \x1b[0m Plugin \x1b[1;36m{key}\x1b[0m chce oprávnění: "
          f"\x1b[1;33m{perm}\x1b[0m ({PERMS.get(perm, '?')})")
    try:
        ans = input("Povolit trvale? [Y/n]: ").strip().lower()
    except EOFError:
        return False
    ok = ans in ("", "y", "a", "yes", "ano")
    shell.config.data.setdefault("permissions", {}).setdefault(key, {})[perm] = ok
    shell.config.save()
    return ok


class XAPI:
    def __init__(self, shell, key):
        self.shell, self.key = shell, key

    def _ok(self, perm):
        return check_perm(self.shell, self.key, perm)

    def lang(self):
        return self.shell.config.data.get("lang", "cs") if self._ok("read_language") else "N/A"

    def theme(self):
        return self.shell.config.data.get("theme", "default") if self._ok("read_theme") else "N/A"

    def set_conf(self, key, val):
        if self._ok("write_config"):
            self.shell.config.data[key] = val
            self.shell.config.save()
            return True
        return False

    def battery(self):
        if not self._ok("read_battery"):
            return "N/A"
        if not which("termux-battery-status"):
            return "N/A"
        import subprocess
        try:
            out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5).stdout
            return str(json.loads(out).get("percentage", "N/A")) + "%"
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return "N/A"

    def ip(self):
        if not self._ok("read_network"):
            return "N/A"
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))      # UDP: nic se neodešle, jen zjistí výchozí rozhraní
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"
