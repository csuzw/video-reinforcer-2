#!/bin/bash
# Video Reinforcer — setup script (Raspberry Pi 4 / 5, or any Debian-based Linux)
# Run as root: sudo bash setup.sh
#
# Also used to build the SD card image (image/), where it runs inside a chroot
# with VR_IMAGE_BUILD=1: nothing is started or restarted, only installed and
# enabled, because there is no running system to act on.
set -e

APP_DIR="/opt/video-reinforcer"
MOUNT_POINT="/mnt/vr-usb"
SERVICE="video-reinforcer"
BOOT_DIR="/boot/firmware"   # Raspberry Pi boot partition (FAT, editable from any PC)
IMAGE_BUILD="${VR_IMAGE_BUILD:-0}"

echo "=== Video Reinforcer Setup ==="

# ---- System dependencies ----
apt-get update
apt-get install -y \
    mpv \
    ffmpeg \
    labwc \
    seatd \
    python3-pip \
    python3-venv \
    python3-dev \
    gcc \
    git \
    libhidapi-libusb0 \
    libudev-dev \
    fonts-dejavu-core

# ---- Mount point ----
mkdir -p "$MOUNT_POINT"

# ---- Stream Deck udev rule (allows non-root access; also works running as root) ----
cat > /etc/udev/rules.d/50-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", GROUP="plugdev", TAG+="uaccess"
EOF
if [ "$IMAGE_BUILD" != "1" ]; then
    udevadm control --reload-rules
    udevadm trigger
fi

# ---- Deploy application ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$(dirname "$SCRIPT_DIR")"

mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/src"
cp -r "$APP_SRC/src" "$APP_DIR/"
cp "$APP_SRC/requirements.txt" "$APP_DIR/"

# ---- Updater: `sudo vr-update [branch]` pulls from GitHub and re-runs this script ----
echo "$APP_SRC" > "$APP_DIR/source-dir"
install -m 755 "$SCRIPT_DIR/vr-update" /usr/local/sbin/vr-update
sed -i 's/\r$//' /usr/local/sbin/vr-update  # tolerate a Windows checkout

# ---- Python dependencies ----
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ---- Blank video for OSD error display ----
# A 1-second looping black video that error messages are overlaid on via mpv OSD.
ffmpeg -y -loglevel error \
    -f lavfi -i "color=black:size=1920x1080:rate=1" \
    -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
    -t 1 -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p \
    -c:a aac -b:a 32k -shortest \
    "$APP_DIR/blank.mp4"

# ---- Disable desktop display manager (conflicts with labwc Wayland compositor) ----
# labwc takes exclusive DRM/KMS ownership; no other display manager can run alongside it.
# Save the DM name so it can be restarted automatically when the app stops.
DM_ID=""
for DM in lightdm gdm gdm3 sddm xdm lxdm; do
    # Accept active (fresh install) or disabled (re-run after prior setup)
    if systemctl is-active --quiet "$DM" 2>/dev/null || \
       systemctl list-unit-files "${DM}.service" 2>/dev/null | grep -qE "enabled|disabled"; then
        DM_ID="${DM}.service"
        break
    fi
done
if [ -n "$DM_ID" ]; then
    echo "$DM_ID" > "$APP_DIR/display-manager"
    echo "Detected display manager: $DM_ID"
else
    rm -f "$APP_DIR/display-manager"
    echo "No display manager detected (terminal-only setup)"
fi
if [ "$IMAGE_BUILD" = "1" ]; then
    systemctl disable lightdm gdm gdm3 sddm xdm lxdm 2>/dev/null || true
else
    systemctl disable --now lightdm gdm gdm3 sddm xdm lxdm 2>/dev/null || true
fi

# ---- Kernel console tweaks (Raspberry Pi only) ----
# The kernel's own framebuffer console (vc4drmfb) grabs DRM master at boot and
# never releases it, so labwc gets "Device or resource busy" / "Permission
# denied" on every commit and the screen is stuck on the raw text console.
# Redirecting fbcon to fb1 (absent on this hardware) keeps it off the real
# DRM device, leaving master free for labwc to claim immediately.
CMDLINE="$BOOT_DIR/cmdline.txt"
if [ -f "$CMDLINE" ]; then
    sed -i 's/ console=tty1//; s/ vt.global_cursor_default=0//' "$CMDLINE"
    grep -q "fbcon=map:1" "$CMDLINE" || sed -i 's/$/ fbcon=map:1/' "$CMDLINE"
    grep -q "consoleblank=0" "$CMDLINE" || sed -i 's/$/ consoleblank=0/' "$CMDLINE"
else
    echo "No $CMDLINE (not a Raspberry Pi?) — skipping kernel console tweaks"
fi

# ---- Hardware override file (example, all commented out) ----
# Lives on the boot partition so it can be edited from any PC. Never
# overwrites an existing file.
if [ -d "$BOOT_DIR" ] && [ ! -e "$BOOT_DIR/video-reinforcer.conf" ]; then
    cp "$SCRIPT_DIR/video-reinforcer.conf.example" "$BOOT_DIR/video-reinforcer.conf"
fi

# ---- Auto-login on tty1 (app runs via systemd, not login shell, but useful for debug) ----
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I \$TERM
EOF

# ---- labwc launcher ----
# rc.xml (window rules) is generated at every boot by labwc-start.sh from the
# detected hardware, so it is not installed here.
mkdir -p "$APP_DIR/labwc"
cp "$SCRIPT_DIR/labwc-start.sh" "$APP_DIR/labwc-start.sh"
sed -i 's/\r$//' "$APP_DIR/labwc-start.sh"  # tolerate a Windows checkout
chmod 755 "$APP_DIR/labwc-start.sh"

# ---- Install and enable systemd services ----
cp "$SCRIPT_DIR/labwc.service" /etc/systemd/system/
cp "$SCRIPT_DIR/video-reinforcer.service" /etc/systemd/system/
[ "$IMAGE_BUILD" = "1" ] || systemctl daemon-reload
systemctl enable seatd
systemctl enable labwc
systemctl enable "$SERVICE"
if [ "$IMAGE_BUILD" != "1" ]; then
    # Start in dependency order; labwc waits for seatd, app waits for labwc
    systemctl restart seatd
    systemctl restart labwc
    systemctl restart "$SERVICE"
fi

echo ""
echo "=== Setup complete ==="
echo "Service status: systemctl status $SERVICE"
echo "Logs:           journalctl -u $SERVICE -f"
