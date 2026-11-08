#!/bin/bash
# Video Reinforcer — Raspberry Pi 5 setup script
# Run as root: sudo bash setup.sh
set -e

APP_DIR="/opt/video-reinforcer"
MOUNT_POINT="/mnt/vr-usb"
SERVICE="video-reinforcer"
SETUP_UNIT="video-reinforcer-setup"
SETUP_LOG="/var/log/video-reinforcer-setup.log"
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: setup must run as root. Use: sudo bash $0" >&2
    exit 1
fi

# ---- Survive the desktop being stopped ----
# This script stops the desktop display manager (lightdm etc.) part-way
# through. If it was launched from a terminal window on that desktop, stopping
# the desktop kills the terminal and the script with it, leaving a half-done
# install that boots to a login prompt. So when we detect we're inside a
# graphical session, relaunch ourselves as a transient systemd unit (outside
# the session) and just follow its log here until the desktop goes away.
in_graphical_session() {
    local sid type
    sid=$(sed -n 's|.*/session-\([^/]*\)\.scope.*|\1|p' /proc/self/cgroup | head -n1)
    [ -n "$sid" ] || return 1
    type=$(loginctl show-session "$sid" -p Type --value 2>/dev/null) || return 1
    [ "$type" = "x11" ] || [ "$type" = "wayland" ] || [ "$type" = "mir" ]
}

if [ -z "$VR_SETUP_DETACHED" ] && in_graphical_session; then
    : > "$SETUP_LOG"
    echo "Running from a desktop session. The desktop will be shut down during"
    echo "setup, so setup is continuing in the background where it can't be killed."
    echo ""
    echo "  - This window will close part-way through. That is expected."
    echo "  - When setup finishes, the screen switches to the Video Reinforcer app."
    echo "  - If anything fails, the error is shown on screen and saved to:"
    echo "      $SETUP_LOG"
    echo ""
    systemctl reset-failed "$SETUP_UNIT" 2>/dev/null || true
    systemd-run --quiet --unit="$SETUP_UNIT" --collect \
        --setenv=VR_SETUP_DETACHED=1 \
        --setenv=DEBIAN_FRONTEND=noninteractive \
        /bin/bash -c "exec /bin/bash '$SCRIPT_PATH' >>'$SETUP_LOG' 2>&1"
    SETUP_PID=$(systemctl show -p MainPID --value "$SETUP_UNIT")
    if [ -n "$SETUP_PID" ] && [ "$SETUP_PID" != "0" ]; then
        tail -n +1 -f --pid="$SETUP_PID" "$SETUP_LOG"
    else
        cat "$SETUP_LOG"
    fi
    exit 0
fi

# When running detached nobody is watching a terminal and the desktop may
# already be gone, so on failure switch to the text console and say so.
on_detached_error() {
    local line=$1 rc=$2
    chvt 1 2>/dev/null || true
    {
        printf '\n\n*** VIDEO REINFORCER SETUP FAILED (line %s, exit code %s) ***\n\n' "$line" "$rc"
        tail -n 15 "$SETUP_LOG"
        printf '\nFull log: %s\n' "$SETUP_LOG"
        printf 'Log in with your Pi username/password and re-run:\n'
        printf '    sudo bash %s\n\n' "$SCRIPT_PATH"
    } > /dev/tty1 2>/dev/null || true
}
if [ -n "$VR_SETUP_DETACHED" ]; then
    trap 'on_detached_error "$LINENO" "$?"' ERR
fi

echo "=== Video Reinforcer Setup ==="

# ---- System dependencies ----
apt-get update
apt-get install -y \
    mpv \
    labwc \
    seatd \
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
# A 1-second looping black video that error messages are overlaid on via mpv OSD.
ffmpeg -y \
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
systemctl disable --now lightdm gdm gdm3 sddm xdm lxdm 2>/dev/null || true

# ---- Kernel console tweaks ----
# The kernel's own framebuffer console (vc4drmfb) grabs DRM master at boot and
# never releases it, so labwc gets "Device or resource busy" / "Permission
# denied" on every commit and the screen is stuck on the raw text console.
# Redirecting fbcon to fb1 (absent on this hardware) keeps it off the real
# DRM device, leaving master free for labwc to claim immediately.
# Only applies on a Raspberry Pi; other machines have no cmdline.txt.
CMDLINE=""
for f in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
    if [ -f "$f" ]; then CMDLINE="$f"; break; fi
done
if [ -n "$CMDLINE" ]; then
    sed -i 's/ console=tty1//' "$CMDLINE"
    sed -i 's/ vt.global_cursor_default=0//' "$CMDLINE"
    if ! grep -q "fbcon=map:1" "$CMDLINE"; then
        sed -i 's/$/ fbcon=map:1/' "$CMDLINE"
    fi
    if ! grep -q "consoleblank=0" "$CMDLINE"; then
        sed -i 's/$/ consoleblank=0/' "$CMDLINE"
    fi
else
    echo "WARNING: no cmdline.txt found (not a Raspberry Pi?) - skipping kernel console tweaks."
    echo "         This app is designed for a Raspberry Pi 5; other hardware is untested."
fi

# ---- Auto-login on tty1 (app runs via systemd, not login shell, but useful for debug) ----
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I \$TERM
EOF

# ---- Deploy labwc kiosk config ----
mkdir -p "$APP_DIR/labwc"
cp "$SCRIPT_DIR/labwc/rc.xml" "$APP_DIR/labwc/rc.xml"

# ---- Install and enable systemd services ----
cp "$SCRIPT_DIR/labwc.service" /etc/systemd/system/
cp "$SCRIPT_DIR/video-reinforcer.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable seatd
systemctl enable labwc
systemctl enable "$SERVICE"
# Start in dependency order; labwc waits for seatd, app waits for labwc
systemctl restart seatd
systemctl restart labwc
systemctl restart "$SERVICE"

echo ""
echo "=== Setup complete ==="
echo "Service status: systemctl status $SERVICE"
echo "Logs:           journalctl -u $SERVICE -f"
