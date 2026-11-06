#!/usr/bin/env bash
# Build the Linux64Studio Flatpak: linux64studio.flatpak, a single file to install with
#     flatpak install --user linux64studio.flatpak
# Needs flatpak-builder (sudo apt install flatpak-builder) and the GNOME 51 SDK:
#     flatpak install --user flathub org.gnome.Platform//51 org.gnome.Sdk//51
# --install also installs it for you (flatpak run io.github.linux64studio.Linux64Studio).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"
app_id="io.github.linux64studio.Linux64Studio"
flatpak-builder --user --force-clean --repo=flatpak-repo flatpak-build "packaging/flatpak/$app_id.yml"
flatpak build-bundle flatpak-repo linux64studio.flatpak "$app_id" \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
echo "Built $here/linux64studio.flatpak"
if [[ "${1:-}" == "--install" ]]; then
    flatpak install --user -y --reinstall linux64studio.flatpak
    echo "Installed: flatpak run $app_id, or Linux64Studio in the app menu"
fi
