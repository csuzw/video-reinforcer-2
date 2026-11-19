#!/bin/bash
# Video Reinforcer — setup script (Raspberry Pi 4 / 5, or any Debian-based Linux)
# Run as root: sudo bash install/setup.sh
#
# The kiosk is an ordinary auto-login desktop session: greetd (a small login
# manager) logs the kiosk user in at boot and runs install/vr-session, which
# starts the labwc compositor and the app. The app runs as that user, not
# root; logind gives it the display, keyboard and sound devices, and udisks2
# mounts the USB stick.
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root: sudo bash install/setup.sh" >&2
    exit 1
fi

APP_DIR="/opt/video-reinforcer"
ETC_DIR="/etc/video-reinforcer"
BOOT_DIR="/boot/firmware"   # Raspberry Pi boot partition (FAT, editable from any PC)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$(dirname "$SCRIPT_DIR")"

echo "=== Video Reinforcer Setup ==="

# ---- System dependencies ----
apt-get update
apt-get install -y \
    mpv \
    ffmpeg \
    labwc \
    greetd \
    udisks2 \
    polkitd \
    python3-pip \
    python3-venv \
    python3-dev \
    gcc \
    libhidapi-libusb0 \
    libudev-dev \
    fonts-dejavu-core

# ---- Kiosk user ----
# The user greetd logs in automatically. Defaults to whoever ran sudo (on a
# Pi, the user created in Raspberry Pi Imager), so quitting the app lands on
# their own desktop. Set VR_USER=name to choose another; it is created if it
# does not exist.
KIOSK_USER="${VR_USER:-}"
if [ -z "$KIOSK_USER" ] && [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    KIOSK_USER="$SUDO_USER"
fi
if [ -z "$KIOSK_USER" ]; then
    KIOSK_USER="$(getent passwd 1000 | cut -d: -f1)"
fi
KIOSK_USER="${KIOSK_USER:-kiosk}"
if ! id "$KIOSK_USER" >/dev/null 2>&1; then
    echo "Creating user $KIOSK_USER"
    useradd --create-home --shell /bin/bash "$KIOSK_USER"
fi
# input: read the keyboard directly (evdev). The others are normally granted
# to the active session by logind anyway; membership keeps things working if
# the user is also logged in elsewhere.
for GROUP in input video render audio plugdev; do
    if getent group "$GROUP" >/dev/null; then
        usermod -aG "$GROUP" "$KIOSK_USER"
    fi
done
echo "Kiosk user: $KIOSK_USER"

# ---- Stream Deck udev rule ----
# uaccess gives the logged-in user access to the deck.
cat > /etc/udev/rules.d/50-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", GROUP="plugdev", MODE="0660", TAG+="uaccess"
EOF
udevadm control --reload-rules
udevadm trigger

# ---- Deploy application ----
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/src"
cp -r "$APP_SRC/src" "$APP_DIR/"
cp "$APP_SRC/requirements.txt" "$APP_DIR/"

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

# ---- Kiosk session ----
install -m 755 "$SCRIPT_DIR/vr-session" "$SCRIPT_DIR/vr-app" "$APP_DIR/"
mkdir -p "$APP_DIR/labwc"
install -m 644 "$SCRIPT_DIR/labwc/rc.xml" "$APP_DIR/labwc/rc.xml"
# Tolerate a Windows checkout
sed -i 's/\r$//' "$APP_DIR/vr-session" "$APP_DIR/vr-app" "$APP_DIR/labwc/rc.xml"

# ---- Desktop to hand over to when the app quits ----
# Prefer the Raspberry Pi desktop; otherwise any other Wayland desktop. With
# none, quitting leaves a text login prompt.
mkdir -p "$ETC_DIR"
DESKTOP_FILE=""
for F in /usr/share/wayland-sessions/rpd-labwc.desktop /usr/share/wayland-sessions/*.desktop; do
    [ -f "$F" ] || continue
    [ "$(basename "$F")" = "labwc.desktop" ] && continue   # bare compositor, not a desktop
    DESKTOP_FILE="$F"
    break
done
if [ -n "$DESKTOP_FILE" ]; then
    desktop_key() { sed -n "s/^$1=//p" "$DESKTOP_FILE" | head -n1; }
    cat > "$ETC_DIR/desktop.env" << EOF
# Written by setup.sh: the desktop started when the app's quit button is used.
DESKTOP_EXEC='$(desktop_key Exec)'
DESKTOP_NAMES='$(desktop_key DesktopNames | sed 's/;$//; s/;/:/g')'
DESKTOP_SESSION_NAME='$(basename "$DESKTOP_FILE" .desktop)'
EOF
    echo "Desktop after quit: $DESKTOP_FILE"
else
    rm -f "$ETC_DIR/desktop.env"
    echo "No desktop installed: quitting the app will show a text login prompt"
fi

# ---- Hardware override file (example, all commented out) ----
# Lives on the boot partition so it can be edited from any PC. Never
# overwrites an existing file.
if [ -d "$BOOT_DIR" ] && [ ! -e "$BOOT_DIR/video-reinforcer.conf" ]; then
    cp "$SCRIPT_DIR/video-reinforcer.conf.example" "$BOOT_DIR/video-reinforcer.conf"
fi

# ---- Remove the previous root-service design, if installed ----
# Earlier versions ran labwc and the app as root system services, with seatd,
# a root autologin on tty1 and a kernel console override. None of it is
# needed now, and seatd in particular would intercept labwc's device access.
for UNIT in video-reinforcer labwc; do
    if [ -e "/etc/systemd/system/$UNIT.service" ]; then
        systemctl disable --now "$UNIT" 2>/dev/null || true
        rm -f "/etc/systemd/system/$UNIT.service"
    fi
done
systemctl disable --now seatd 2>/dev/null || true
umount /mnt/vr-usb 2>/dev/null || true
rmdir /mnt/vr-usb 2>/dev/null || true
rm -f "$APP_DIR/labwc-start.sh" "$APP_DIR/display-manager"
AUTOLOGIN=/etc/systemd/system/getty@tty1.service.d/autologin.conf
if grep -q -- "--autologin root" "$AUTOLOGIN" 2>/dev/null; then
    rm -f "$AUTOLOGIN"
    rmdir /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
fi
if [ -f "$BOOT_DIR/cmdline.txt" ]; then
    sed -i 's/ fbcon=map:1//' "$BOOT_DIR/cmdline.txt"
fi

# ---- greetd: log the kiosk user in at boot ----
if [ -f /etc/greetd/config.toml ] && [ ! -f /etc/greetd/config.toml.orig ]; then
    cp /etc/greetd/config.toml /etc/greetd/config.toml.orig
fi
cat > /etc/greetd/config.toml << EOF
# Written by Video Reinforcer setup.sh (original saved as config.toml.orig).

[terminal]
vt = 7

# Runs once at boot: the kiosk.
[initial_session]
command = "$APP_DIR/vr-session"
user = "$KIOSK_USER"

# Shown if the kiosk session ends (quit with no desktop installed, or after
# logging out of the desktop). Reboot to start the kiosk again.
[default_session]
command = "/usr/sbin/agreety --cmd /bin/bash"
user = "_greetd"
EOF

# greetd replaces any other display manager (only one can own the screen).
# The old one stays installed; see README "Going back to the normal desktop".
OTHER_DMS="lightdm gdm gdm3 sddm xdm lxdm"
for DM in $OTHER_DMS; do
    systemctl disable "$DM" 2>/dev/null || true
done
systemctl daemon-reload
systemctl enable --force greetd   # --force: take over display-manager.service
systemctl set-default graphical.target

# ---- Start now, unless that would kill the session running this script ----
SESSION_SERVICE=""
SESSION_ID="$(cat /proc/self/sessionid 2>/dev/null || true)"
if [ -n "$SESSION_ID" ] && [ "$SESSION_ID" != "4294967295" ]; then
    SESSION_SERVICE="$(loginctl show-session "$SESSION_ID" -p Service --value 2>/dev/null || true)"
fi
echo ""
echo "=== Setup complete ==="
case "$SESSION_SERVICE" in
    greetd|lightdm|gdm*|sddm|xdm|lxdm)
        echo "Run from a desktop session, so not restarting the display now."
        echo "Reboot to start the kiosk: sudo reboot"
        ;;
    *)
        echo "Starting the kiosk..."
        for DM in $OTHER_DMS; do
            systemctl stop "$DM" 2>/dev/null || true
        done
        systemctl restart greetd
        echo "If the kiosk does not appear, reboot: sudo reboot"
        ;;
esac
echo "Logs: journalctl -t video-reinforcer -t labwc -f"
