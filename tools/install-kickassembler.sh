#!/usr/bin/env bash
# Download Kick Assembler (the latest, from its official site) into Linux64Studio's data folder,
# where Linux64Studio finds it when Preferences doesn't name a KickAss.jar. Run it again to update.
set -euo pipefail
url="https://theweb.dk/KickAssembler/KickAssembler.zip"
dest="${XDG_DATA_HOME:-$HOME/.local/share}/linux64studio/KickAssembler"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $url"
curl -fsSL -o "$tmp/KickAssembler.zip" "$url"
unzip -q "$tmp/KickAssembler.zip" -d "$tmp/unpacked"
if [[ ! -f "$tmp/unpacked/KickAss.jar" ]]; then
    echo "The download has no KickAss.jar in it" >&2
    exit 1
fi
mkdir -p "$(dirname "$dest")"
rm -rf "$dest"
mv "$tmp/unpacked" "$dest"
version="$(cd "$tmp"; java -jar "$dest/KickAss.jar" 2>&1 | grep -o 'Kick Assembler v[0-9.]*')" || version=""
echo "Installed ${version:-Kick Assembler} in $dest"
