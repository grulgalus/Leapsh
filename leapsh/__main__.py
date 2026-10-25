import os
import sys
import time

from . import __version__
from .shell import Shell


HELP = """leapsh – shell s pluginy, tématy a addony (Python + WASM)

použití: leapsh [volby] [soubor]
  -c PŘÍKAZ      spustí příkaz(y) a skončí
  --version      verze
  --dev          vývojářský režim: plugins-dev a plné tracebacky
  --norc         nespouštět ~/.config/leapsh/rc
  --no-plugins   záchranný režim bez pluginů
  -h, --help     tato nápověda
  soubor         soubor s příkazy (jeden na řádek)
"""


class Args:
    command = None
    version = dev = norc = no_plugins = False
    file = None


def parse_args(argv):
    a, i = Args(), 0
    while i < len(argv):
        x = argv[i]
        if x in ("-h", "--help"):
            print(HELP, end="")
            raise SystemExit(0)
        elif x == "-c":
            if i + 1 >= len(argv):
                print("leapsh: -c potřebuje příkaz", file=sys.stderr)
                raise SystemExit(2)
            a.command, i = argv[i + 1], i + 1
        elif x == "--version":
            a.version = True
        elif x == "--dev":
            a.dev = True
        elif x == "--norc":
            a.norc = True
        elif x == "--no-plugins":
            a.no_plugins = True
        elif x.startswith("-") and x != "-":
            print(f"leapsh: neznámá volba {x}\n{HELP}", file=sys.stderr, end="")
            raise SystemExit(2)
        else:
            a.file = x
        i += 1
    return a


def main(argv=None):
    t0 = time.perf_counter()
    args = parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.version:
        print(f"leapsh {__version__}")
        return 0
    if args.norc:
        os.environ["LEAPSH_NORC"] = "1"
    if args.dev:
        os.environ["LEAPSH_DEV"] = os.environ["LEAPSH_DEBUG"] = "1"
    from .env_check import check_environment, migrate_legacy_home
    migrated = migrate_legacy_home()
    sh = Shell()
    sh.startup_t0 = t0
    notices = check_environment(sh.config, probe=sys.stdin.isatty() and args.command is None)
    if not args.no_plugins:
        sh.manager.load_all()
    if args.command is not None:
        return sh.run_lines(args.command.split("\n"))
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return sh.run_lines(f.read().split("\n"))
    if not sys.stdin.isatty():
        return sh.run_lines(sys.stdin.read().split("\n"))
    if sh.config.data.get("startup_msg", True) and not os.environ.get("LEAPSH_QUIET"):
        n = len(sh.manager.loaded) + len(sh.manager.addons)
        sh.startup_ms = (time.perf_counter() - t0) * 1000
        print(f"\x1b[2mleapsh {__version__} • ⚡ {sh.startup_ms:.0f} ms • {n} pluginů/addonů • téma {sh.config.data.get('theme')} • 'help' pro nápovědu\x1b[0m")
    if migrated and not os.environ.get("LEAPSH_QUIET"):
        print(f"\x1b[2m↪ převzata data ze staré složky {migrated}\x1b[0m")
    for level, text in ([] if os.environ.get("LEAPSH_QUIET") else notices):
        print(f"\x1b[{'33' if level == 'warn' else '2'}m{'⚠' if level == 'warn' else 'ℹ'} {text}\x1b[0m")
    os.environ["LEAPSH_ACTIVE"] = "1"
    return sh.repl()


if __name__ == "__main__":
    sys.exit(main())
