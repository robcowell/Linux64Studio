#!/usr/bin/env bash
# Add Linux64Studio to the desktop app launcher (uses this checkout's .venv).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
exe="$here/.venv/bin/linux64studio"
if [[ ! -x "$exe" ]]; then
    echo "Run 'uv venv --system-site-packages .venv && uv pip install --python .venv -e .' first" >&2
    exit 1
fi
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
cat > "$apps/io.github.linux64studio.Linux64Studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Linux64Studio
Comment=Commodore 64 development environment
Exec="$exe" %F
Icon=applications-games
Terminal=false
Categories=Development;IDE;
MimeType=text/x-asm;
StartupWMClass=io.github.linux64studio.Linux64Studio
DESKTOP
update-desktop-database "$apps" 2>/dev/null || true
echo "Installed $apps/io.github.linux64studio.Linux64Studio.desktop"
