#!/bin/sh
# Adiciona o Chromaqui! ao menu de aplicativos (somente para o seu usuário; não precisa de sudo).
#   ./install-desktop.sh            instala   |   ./install-desktop.sh --uninstall   remove
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
if [ "$1" = "--uninstall" ]; then
  rm -f "$APPS/chromaqui.desktop"
  find "$ICONS" -name chromaqui.png -path '*/apps/*' -delete 2>/dev/null || true
  echo "Chromaqui! removido do menu."
  exit 0
fi
mkdir -p "$APPS"
for d in "$HERE"/icons/hicolor/*/apps; do
  s="$(basename "$(dirname "$d")")"
  mkdir -p "$ICONS/$s/apps"
  cp "$d/chromaqui.png" "$ICONS/$s/apps/chromaqui.png"
done
sed "s|^Exec=.*|Exec=\"$HERE/Chromaqui/Chromaqui\" %f|" "$HERE/chromaqui.desktop" > "$APPS/chromaqui.desktop"
chmod +x "$APPS/chromaqui.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$ICONS" >/dev/null 2>&1 || true
echo "Chromaqui! adicionado ao menu de aplicativos ($APPS/chromaqui.desktop)."
