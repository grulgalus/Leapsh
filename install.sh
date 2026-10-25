#!/usr/bin/env sh
# Instalace leapsh (Linux i Termux).
#   ./install.sh                  nainstaluje a vytvoří příkaz `leapsh`
#   ./install.sh --default-shell  navíc spouští leapsh při startu bashe/zsh (s pojistkou)
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
TERMUX=0
case "${PREFIX:-}" in *com.termux*) TERMUX=1;; esac

if ! command -v python3 >/dev/null 2>&1; then
  if [ "$TERMUX" = 1 ]; then
    echo "→ instaluji python (pkg install python)"; pkg install -y python
  else
    echo "Chybí python3. Nainstaluj ho (např. sudo apt install python3) a spusť znovu." >&2; exit 1
  fi
fi
if ! command -v git >/dev/null 2>&1 && [ "$TERMUX" = 1 ]; then
  echo "→ instaluji git (pro plugin git_prompt)"; pkg install -y git || true
fi

DEST="${LEAPSH_PREFIX:-$HOME/.local/share/leapsh}"
if [ "$TERMUX" = 1 ]; then BINDIR="$PREFIX/bin"; else BINDIR="$HOME/.local/bin"; fi
mkdir -p "$DEST" "$BINDIR"
if [ "$SRC" != "$DEST" ]; then
  rm -rf "$DEST/leapsh" "$DEST/plugins" "$DEST/addons" "$DEST/templates" "$DEST/bin" "$DEST/docs" "$DEST/tools"
  cp -R "$SRC/leapsh" "$SRC/plugins" "$SRC/addons" "$SRC/templates" "$SRC/bin" "$SRC/docs" "$SRC/tools" "$DEST/"
  cp "$SRC/README.md" "$SRC/LICENSE" "$DEST/" 2>/dev/null || true
fi
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
# předkompilace bytecode: rychlejší start shellu a vestavěných pluginů
python3 -m compileall -q "$DEST/leapsh" "$DEST/plugins" "$DEST/addons" >/dev/null 2>&1 || true
ln -sf "$DEST/bin/leapsh" "$BINDIR/leapsh"
ln -sf "$DEST/bin/leapsh" "$BINDIR/lsh"
ln -sf "$DEST/tools/leapsh-plugin-init.sh" "$BINDIR/leapsh-plugin-init"
ln -sf "$DEST/tools/leapsh-compile-plugin.sh" "$BINDIR/leapsh-compile-plugin"
chmod +x "$DEST/bin/leapsh" "$DEST/bin/lsh" "$DEST/tools/"*.sh "$DEST/tools/"*.py
echo "✓ nainstalováno do $DEST, příkazy: leapsh a lsh v $BINDIR"
case ":$PATH:" in *":$BINDIR:"*) ;; *) echo "! přidej do PATH: export PATH=\"$BINDIR:\$PATH\"";; esac

if [ "${1:-}" = "--default-shell" ]; then
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || { [ "$rc" = "$HOME/.bashrc" ] && touch "$rc" || continue; }
    grep -q '>>> leapsh >>>' "$rc" 2>/dev/null && continue
    cat >> "$rc" <<'RC'

# >>> leapsh >>>
# Spustí leapsh při startu interaktivního shellu. Když leapsh spadne, zůstaneš v bashi.
# Dočasné vypnutí: LEAPSH_SKIP=1 bash   (v Termuxu: Nový session a hned napsat `LEAPSH_SKIP=1 bash`)
case $- in *i*)
  if [ -z "${LEAPSH_SKIP:-}" ] && [ -z "${LEAPSH_ACTIVE:-}" ] && command -v leapsh >/dev/null 2>&1; then
    leapsh && exit
  fi;;
esac
# <<< leapsh <<<
RC
    echo "✓ přidáno do $rc"
  done
fi
echo "Hotovo. Spusť: leapsh"
