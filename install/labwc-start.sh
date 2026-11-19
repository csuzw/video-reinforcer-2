#!/bin/bash
# Start labwc on the DRM device that actually drives the HDMI ports.
#
# The Pi has two DRM devices: v3d (3D GPU, render-only, no outputs) and vc4
# (the display controller, which owns HDMI-A-1/HDMI-A-2). Which one becomes
# card0 and which becomes card1 depends on driver probe order. On a Pi 4 it
# changes from boot to boot. If labwc is pointed at v3d it has no outputs, and
# the screens stay black while the app waits forever for labwc.
#
# So instead of hard-coding a card number, look for the card that has HDMI
# connectors in sysfs (e.g. /sys/class/drm/card1-HDMI-A-1) and use that.

# vc4 can finish probing slightly after this unit starts: wait up to ~10s.
for _ in $(seq 1 50); do
    for conn in /sys/class/drm/card*-HDMI-A-*; do
        [ -e "$conn" ] || continue
        name="$(basename "$conn")"   # e.g. card1-HDMI-A-1
        card="${name%%-*}"           # e.g. card1
        if [ -e "/dev/dri/$card" ]; then
            echo "labwc-start: using /dev/dri/$card (found $name)"
            export WLR_DRM_DEVICES="/dev/dri/$card"
            exec /usr/bin/labwc "$@"
        fi
    done
    sleep 0.2
done

# No HDMI-capable card found. Let wlroots pick a device itself instead of
# failing outright; LABWC_FALLBACK_OUTPUT keeps labwc running even with no
# outputs, so the app still starts and the Stream Deck still works.
echo "labwc-start: no DRM device with HDMI connectors found; letting wlroots auto-detect" >&2
unset WLR_DRM_DEVICES
exec /usr/bin/labwc "$@"
