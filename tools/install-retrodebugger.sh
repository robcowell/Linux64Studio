#!/usr/bin/env bash
# Download RetroDebugger (the latest release's Linux x64 build, from its GitHub releases) into
# Linux64Studio's data folder, where Debugger → Debug in RetroDebugger finds it when Preferences
# doesn't name one. Run it again to update.
set -euo pipefail
api="https://api.github.com/repos/slajerek/RetroDebugger/releases/latest"
dest="${XDG_DATA_HOME:-$HOME/.local/share}/linux64studio/RetroDebugger"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Finding the latest release: $api"
url="$(curl -fsSL "$api" | grep -o '"browser_download_url": *"[^"]*linux-x64[^"]*"' | head -n 1 | sed 's/.*"\(https[^"]*\)"/\1/')"
if [[ -z "$url" ]]; then
    echo "The latest release has no Linux x64 download" >&2
    exit 1
fi
echo "Downloading $url"
curl -fsSL -o "$tmp/download" "$url"
mkdir -p "$tmp/unpacked"
case "$url" in
    *.zip) unzip -q "$tmp/download" -d "$tmp/unpacked" ;;
    *.tar.gz|*.tgz) tar -xzf "$tmp/download" -C "$tmp/unpacked" ;;
    *) echo "Don't know how to unpack $url" >&2; exit 1 ;;
esac
exe="$(find "$tmp/unpacked" -type f \( -name RetroDebugger -o -name retrodebugger \) | head -n 1)"
if [[ -z "$exe" ]]; then
    echo "The download has no RetroDebugger program in it" >&2
    exit 1
fi
chmod +x "$exe"
mkdir -p "$(dirname "$dest")"
rm -rf "$dest"
mv "$tmp/unpacked" "$dest"
echo "Installed RetroDebugger in $dest"
