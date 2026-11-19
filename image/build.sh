#!/bin/bash
# Build the Video Reinforcer SD card image (Raspberry Pi 4 / 5, 64-bit).
#
# Uses Raspberry Pi's own image builder, pi-gen, in Docker: Raspberry Pi OS
# Lite (stages 0-2) plus our stage-vr, which installs the app and Tailscale.
# The output is image/deploy/video-reinforcer-*.img.xz, ready for Raspberry
# Pi Imager.
#
# Needs: Linux (or WSL) with Docker, git, openssl. On an x86 machine the arm64
# parts run under QEMU emulation and take much longer; CI builds on an arm64
# runner (see .github/workflows/image.yml).
#
# The app in the image is a snapshot of this repo's current commit (HEAD), so
# commit before building. Nothing secret goes into the image.
set -euo pipefail

# pi-gen "arm64" branch (64-bit Raspberry Pi OS, Debian trixie). Pinned so a
# build is reproducible; bump deliberately.
PI_GEN_REPO="https://github.com/RPi-Distro/pi-gen.git"
PI_GEN_REF="${PI_GEN_REF:-c0d2c9f2cffc08bc56850b0a3eb23178f4226e8a}"
APP_REPO_URL="https://github.com/csuzw/video-reinforcer-2.git"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
WORK="$HERE/work"
PIGEN="$WORK/pi-gen"

echo "=== Fetching pi-gen ($PI_GEN_REF) ==="
rm -rf "$WORK"
mkdir -p "$WORK"
git clone --quiet "$PI_GEN_REPO" "$PIGEN"
git -C "$PIGEN" checkout --quiet "$PI_GEN_REF"

echo "=== Adding stage-vr ==="
cp -r "$HERE/stage-vr" "$PIGEN/stage-vr"
# Stage 2 is Raspberry Pi OS Lite; don't export it as an image of its own.
touch "$PIGEN/stage2/SKIP_IMAGES"

# Snapshot of the app, with git metadata so `vr-update` can pull new versions
# on the device. A detached HEAD is fine: vr-update checks out a branch.
APP_SNAPSHOT="$PIGEN/stage-vr/00-app/files/video-reinforcer-src"
git clone --quiet --no-local "$REPO" "$APP_SNAPSHOT"
git -C "$APP_SNAPSHOT" checkout --quiet "$(git -C "$REPO" rev-parse HEAD)"
git -C "$APP_SNAPSHOT" remote set-url origin "$APP_REPO_URL"
APP_VERSION="$(git -C "$REPO" describe --tags --always 2>/dev/null || git -C "$REPO" rev-parse --short HEAD)"
echo "$APP_VERSION" > "$PIGEN/stage-vr/00-app/files/image-version"
echo "App version: $APP_VERSION"

echo "=== Writing config ==="
cp "$HERE/config" "$PIGEN/config"
# The first user's password is random and never recorded: nobody logs in with
# it. Remote access is via Tailscale SSH or SSH keys (see image/README.md).
echo "FIRST_USER_PASS='$(openssl rand -hex 24)'" >> "$PIGEN/config"

echo "=== Building (this takes a while) ==="
cd "$PIGEN"
GIT_HASH="$(git -C "$REPO" rev-parse HEAD)" ./build-docker.sh

mkdir -p "$HERE/deploy"
find "$PIGEN/deploy" -maxdepth 1 -name '*.img.xz' -exec mv {} "$HERE/deploy/" \;
ls -lh "$HERE/deploy"
