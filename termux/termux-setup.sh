#!/data/data/com.termux/files/usr/bin/sh
# Jedním příkazem: balíčky + instalace leapsh v Termuxu.
set -eu
pkg update -y
pkg install -y python git termux-api coreutils
cd "$(dirname "$0")/.."
./install.sh "$@"
echo
echo "Tip: pro notifikace a baterii nainstaluj z F-Droidu aplikaci Termux:API."
echo "Tip: klávesy pro leapsh (Tab, Ctrl, šipky) nastavíš v ~/.termux/termux.properties – viz termux/extra-keys.example"
