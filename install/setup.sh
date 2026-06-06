#!/bin/bash
# Video Reinforcer — Raspberry Pi 5 setup script
# Run as root: sudo bash setup.sh
set -e

APP_DIR="/opt/video-reinforcer"
MOUNT_POINT="/mnt/vr-usb"
SERVICE="video-reinforcer"

echo "=== Video Reinforcer Setup ==="

# ---- System dependencies ----
apt-get update
apt-get install -y \
    mpv \
    python3-pip \
    python3-dev \
    libhidapi-libusb0 \
    libudev-dev \
    fonts-dejavu-core

# ---- Mount point ----
mkdir -p "$MOUNT_POINT"

# ---- Stream Deck udev rule (allows non-root access; also works running as root) ----
cat > /etc/udev/rules.d/50-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", GROUP="plugdev", TAG+="uaccess"
EOF
udevadm control --reload-rules
udevadm trigger

# ---- Deploy application ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$(dirname "$SCRIPT_DIR")"

mkdir -p "$APP_DIR"
cp -r "$APP_SRC/src" "$APP_DIR/"
cp "$APP_SRC/requirements.txt" "$APP_DIR/"

# ---- Python dependencies ----
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ---- Blank video for OSD error display ----
# mpv --vo=drm requires audio+video; this 1-second loop is the silent black background
# that error messages are overlaid on via OSD.
ffmpeg -y \
    -f lavfi -i "color=black:size=1920x1080:rate=1" \
    -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
    -t 1 -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p \
    -c:a aac -b:a 32k -shortest \
    "$APP_DIR/blank.mp4"

# ---- Disable desktop display manager (conflicts with DRM video output) ----
# The app uses mpv --vo=drm which needs exclusive display access.
# Save the active display manager name first so quit can restore it.
DM_ID=$(systemctl show -p Id display-manager.service 2>/dev/null | cut -d= -f2)
if [ -n "$DM_ID" ]; then
    echo "$DM_ID" > "$APP_DIR/display-manager"
    echo "Detected display manager: $DM_ID"
fi
systemctl disable --now lightdm gdm sddm 2>/dev/null || true

# ---- Disable console blanking (keeps DRM state clean) ----
if ! grep -q "consoleblank=0" /boot/firmware/cmdline.txt 2>/dev/null; then
    sed -i 's/$/ consoleblank=0/' /boot/firmware/cmdline.txt
fi

# ---- Auto-login on tty1 (app runs via systemd, not login shell, but useful for debug) ----
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I \$TERM
EOF

# ---- Install and enable systemd service ----
cp "$SCRIPT_DIR/video-reinforcer.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

echo ""
echo "=== Setup complete ==="
echo "Service status: systemctl status $SERVICE"
echo "Logs:           journalctl -u $SERVICE -f"
