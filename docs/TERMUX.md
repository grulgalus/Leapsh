# leapsh v Termuxu

```sh
pkg install git            # nebo si stáhni ZIP a rozbal ho
cd leapsh
sh termux/termux-setup.sh  # nainstaluje python, git, termux-api, leapsh
leapsh
```

- **Klávesy**: Tab, šipky a Ctrl jsou v extra řádku Termuxu. Vzorová konfigurace s Home/End/PgUp je v `termux/extra-keys.example`
  (zkopíruj do `~/.termux/termux.properties`, pak `termux-reload-settings`).
- **Notifikace a baterie**: `pkg install termux-api` a nainstaluj aplikaci *Termux:API* (F-Droid). Pak fungují
  addon `cmd_timer_notify`, příkaz `tnotify` a segment `{battery}`.
- **Výchozí shell**: `./install.sh --default-shell` přidá spuštění do `~/.bashrc`. Když by se něco pokazilo,
  otevři nový session a napiš `LEAPSH_SKIP=1 bash`, nebo smaž blok `>>> leapsh >>>` z `~/.bashrc`.
- **Barvy**: témata `neon` a `dracula` používají truecolor – Termux ho podporuje. Pro 256 barev dej do témat číselné barvy (`{208}`).
- **Python**: stačí `python` z `pkg`. Žádné pip balíčky nejsou potřeba.
- Plugin `termux_extras` se načítá jen v Termuxu (`"platforms": ["termux"]`).

## Automatická kontrola při startu

leapsh při každém spuštění ověří prostředí a zapíše výsledek do `~/.config/leapsh/config.json`:
`"termux": {"available": …, "api": …, "api_working": …}` (viz README). Když v Termuxu chybí Termux:API, napíše, jak to opravit;
mimo Termux upozorní, že funkce jen pro Termux nejsou dostupné. Diagnostika: `doctor`.
