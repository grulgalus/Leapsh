#!/usr/bin/env sh
# Odinstalace leapsh (konfigurace v ~/.config/leapsh zůstane, pokud nedáš --purge).
set -eu
TERMUX=0; case "${PREFIX:-}" in *com.termux*) TERMUX=1;; esac
DEST="${LEAPSH_PREFIX:-$HOME/.local/share/leapsh}"
if [ "$TERMUX" = 1 ]; then BINDIR="$PREFIX/bin"; else BINDIR="$HOME/.local/bin"; fi
rm -f "$BINDIR/leapsh" "$BINDIR/lsh" "$BINDIR/leapsh-plugin-init" "$BINDIR/leapsh-compile-plugin"; rm -rf "$DEST"
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  [ -f "$rc" ] && sed -i '/>>> leapsh >>>/,/<<< leapsh <<</d' "$rc" || true
done
[ "${1:-}" = "--purge" ] && rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/leapsh" && echo "✓ smazána i konfigurace"
echo "✓ leapsh odinstalován"
