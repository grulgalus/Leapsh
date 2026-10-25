# Příklady

Zkopíruj do uživatelského adresáře a načti:

```sh
mkdir -p ~/.config/leapsh/plugins ~/.config/leapsh/addons
cp -r examples/plugins/hello_events ~/.config/leapsh/plugins/
cp -r examples/addons/hello_shout  ~/.config/leapsh/addons/
# v leapsh:
reload
hello          # → AHOJ! DOSUD JSI STISKL N KLÁVES.   (addon změnil text)
plugin disable hello_shout
hello          # → Ahoj! ...
```
Alt+H vloží `hello ` na řádek (vlastní klávesová zkratka přes událost `key`).
