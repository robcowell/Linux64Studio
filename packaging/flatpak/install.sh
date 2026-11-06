#!/bin/sh
# Installs Linux64Studio into a prefix (the Flatpak's /app), without pip: the package, a launcher
# for each command, the docs and examples the Tutorials tab shows, and the desktop entry, icon and
# AppStream metadata. Run from the top of the source.
set -eu
prefix="${1:-/app}"
app_id="io.github.linux64studio.Linux64Studio"
site="$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib', vars={'base': '$prefix'}))")"
mkdir -p "$site" "$prefix/bin"
cp -r src/l64s "$site/"
find "$site/l64s" -name __pycache__ -prune -exec rm -rf {} +
python3 -m compileall -q "$site/l64s"

# a launcher for each command in pyproject.toml's [project.scripts]
sed -n '/^\[project.scripts\]/,/^\[/p' pyproject.toml | grep '=' | while IFS= read -r line; do
    name="$(echo "$line" | cut -d= -f1 | tr -d ' ')"
    target="$(echo "$line" | cut -d= -f2 | tr -d ' "')"
    module="${target%%:*}"
    func="${target##*:}"
    cat > "$prefix/bin/$name" <<LAUNCHER
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$site")
from $module import $func
sys.exit($func())
LAUNCHER
    chmod +x "$prefix/bin/$name"
done

share="$prefix/share/linux64studio"
mkdir -p "$share"
cp -r docs examples "$share/"
install -Dm644 "packaging/flatpak/$app_id.desktop" "$prefix/share/applications/$app_id.desktop"
install -Dm644 "packaging/flatpak/$app_id.metainfo.xml" "$prefix/share/metainfo/$app_id.metainfo.xml"
install -Dm644 "src/l64s/data/icons/hicolor/scalable/apps/$app_id.svg" \
    "$prefix/share/icons/hicolor/scalable/apps/$app_id.svg"
