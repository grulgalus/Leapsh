#!/usr/bin/env python3
"""leapsh-compile-plugin – zkontroluje a sestaví plugin a zabalí ho do <název>-<verze>.leapsh.

  leapsh-compile-plugin [složka_pluginu]            výchozí: aktuální složka
  leapsh-compile-plugin . -o dist/                  kam uložit balíček
  leapsh-compile-plugin . --no-pack                 jen zkontrolovat/sestavit
  leapsh-compile-plugin . --install                 po sestavení nainstalovat
Python: kontrola syntaxe a manifestu. WASM: .wat (vestavěný assembler), .c (clang), .rs (rustc) -> plugin.wasm.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leapsh.devtools import cli_compile  # noqa: E402

sys.exit(cli_compile(sys.argv[1:]))
