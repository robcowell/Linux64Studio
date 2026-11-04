#!/usr/bin/env bash
# Add Linux64Studio to the desktop's app menu (Cinnamon, GNOME, KDE…), using this checkout's .venv.
# Run it again after moving the checkout. tools/install-desktop.sh --uninstall removes it.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
app_id="io.github.linux64studio.Linux64Studio"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$data/applications"
icons="$data/icons/hicolor/scalable/apps"
desktop="$apps/$app_id.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$desktop" "$icons/$app_id.svg"
    update-desktop-database "$apps" 2>/dev/null || true
    gtk-update-icon-cache -q -t "$data/icons/hicolor" 2>/dev/null || true
    echo "Removed Linux64Studio from the app menu"
    exit 0
fi

exe="$here/.venv/bin/linux64studio"
if [[ ! -x "$exe" ]]; then
    echo "Run 'uv venv --system-site-packages .venv && uv pip install --python .venv -e .' first" >&2
    exit 1
fi
mkdir -p "$apps" "$icons"
cp "$here/src/l64s/data/icons/hicolor/scalable/apps/$app_id.svg" "$icons/$app_id.svg"
cat > "$desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Linux64Studio
GenericName=C64 Development Environment
Comment=Write, build and debug Commodore 64 programs (CBM prg Studio compatible)
Exec="$exe" %F
Path=$HOME
Icon=$app_id
Terminal=false
StartupNotify=true
StartupWMClass=$app_id
Categories=Development;IDE;
Keywords=C64;Commodore;6502;6510;assembler;BASIC;retro;CBM;VICE;sprite;
MimeType=text/x-asm;
DESKTOP
chmod +x "$desktop"
update-desktop-database "$apps" 2>/dev/null || true
gtk-update-icon-cache -q -t "$data/icons/hicolor" 2>/dev/null || true
echo "Installed $desktop"
echo "Linux64Studio is in the app menu under Programming (search for C64 or Linux64Studio)."
