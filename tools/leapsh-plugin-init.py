#!/usr/bin/env python3
"""leapsh-plugin-init – vytvoří kostru pluginu (složka + config.json + src/).

  leapsh-plugin-init muj_plugin                       Python plugin
  leapsh-plugin-init muj_plugin --runtime wasm        WASM plugin ve WAT (sestaví se hned)
  leapsh-plugin-init muj_plugin --runtime wasm --lang c
  leapsh-plugin-init muj_addon --type addon --extends git_prompt
  leapsh-plugin-init muj_motiv --type theme
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leapsh.devtools import cli_init  # noqa: E402

sys.exit(cli_init(sys.argv[1:]))
