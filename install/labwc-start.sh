#!/bin/bash
# Start labwc on the right display device, with window rules for this hardware.
#
# src/hardware.py does the detection (shared with the app so both agree):
#  - finds the DRM device that drives the external ports. On a Pi the 3D GPU
#    (v3d, no outputs) and the display controller (vc4) swap between card0 and
#    card1 across boots, so the number must never be hard-coded;
#  - writes labwc's rc.xml, mapping monitor 1/2 to the detected outputs (or
#    the overrides in video-reinforcer.conf).
APP_DIR=/opt/video-reinforcer
RC_DIR="$APP_DIR/labwc"

card="$(cd "$APP_DIR" && "$APP_DIR/venv/bin/python3" -m src.hardware labwc-setup "$RC_DIR/rc.xml")"

if [ -n "$card" ]; then
    echo "labwc-start: using $card"
    export WLR_DRM_DEVICES="$card"
else
    # Let wlroots pick a device itself rather than failing outright;
    # LABWC_FALLBACK_OUTPUT keeps labwc running even with no outputs, so the
    # app still starts and the Stream Deck still works.
    echo "labwc-start: no display device with external ports found; letting wlroots auto-detect" >&2
    unset WLR_DRM_DEVICES
fi

# The Pi 5 needs libliftoff for DRM plane allocation. Other hardware doesn't.
if grep -qa "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
    export WLR_DRM_FORCE_LIBLIFTOFF=1
fi

exec /usr/bin/labwc -C "$RC_DIR" "$@"
