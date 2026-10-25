# Příklad nastavení pluginů

Soubory v `~/.config/leapsh/plugins/config/` (stačí uvést jen to, co měníš). Nebo příkazem `config set plugins.NÁZEV.KLÍČ HODNOTA`.

`cmd_timer.json`
```json
{"threshold": 5}
```
`git_prompt.json`
```json
{"dirty": true, "color": "yellow", "dirty_color": "red"}
```
`keybinds.json`
```json
{"bindings": {"ctrl-g": "git status -sb", "alt-l": "ls -la", "alt-p": "+git push "}}
```
`tabcomplete.json`
```json
{"ignore_case": true, "specs": {"deploy": {"1": ["staging", "prod"], "--region": ["eu", "us"]}}}
```
`arcade.json`
```json
{"screensaver": true, "idle_seconds": 60}
```
