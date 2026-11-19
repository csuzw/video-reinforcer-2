# Video Reinforcer — Project Guide

## Purpose

This is a clinical kiosk application used during video reinforcement audiometry (rewarding children during hearing tests). Instantaneous video playback is critical — any delay undermines the reward.

## Core design principle: fool-proof first

**Every error must be visible on screen. Nothing is silently logged and ignored.**

This app runs unattended in a clinical setting. The person operating it (an audiologist) needs to know immediately when something is wrong. Errors shown only in logs are invisible to them.

Rules that follow from this:
- Hardware can be plugged in or unplugged in any order, at any time — the app must handle it gracefully
- When something goes wrong, show a clear plain-English message on all connected screens
- When the problem is resolved, automatically recover without requiring a restart
- Transient errors (wrong button, missing video) auto-clear after a few seconds so they don't block normal use
- Persistent errors (no USB, bad config, hardware missing) stay until the issue is actually fixed

## What must always be displayed

| Situation | Screen behaviour |
|---|---|
| No USB stick | Error on all connected monitors |
| Bad/invalid config.json | Error on all connected monitors |
| USB replugged with valid config | Error clears, buttons re-light |
| Button pressed for disconnected monitor | 4-second error, then clears |
| Video file missing or unplayable | 4-second error, then clears |
| Monitor disconnected while running | Error on remaining monitors |
| Stream Deck disconnected | Error on all monitors |
| Stream Deck reconnected | Error clears, buttons re-light |

## Updating the README

**Always update README.md when making changes that affect:**
- User-facing behaviour (error handling, config format, button behaviour)
- Installation or setup steps
- Hardware requirements
- Troubleshooting guidance

README changes should be included in the same commit as the code change.

## Architecture overview

```
main.py              — event loop, state machine, wires everything together
config_loader.py     — parses + validates config.json from USB stick
usb_monitor.py       — pyudev watcher; mounts the USB stick via udisks2 (udisksctl)
hardware.py          — detects monitor outputs and audio devices; overrides file
video_player.py      — one persistent mpv process per monitor (--fs-screen-name); IPC + watchdog
display_manager.py   — coordinates video players; detects monitor connect/disconnect
deck_manager.py      — Stream Deck input + USB hotplug detection; reconnects automatically
keyboard_reader.py   — evdev raw keyboard input
button_renderer.py   — PIL image rendering for Stream Deck keys

install/setup.sh     — installs packages, deploys to /opt/video-reinforcer, configures greetd
install/vr-session   — greetd auto-login session: runs labwc, restarts it if it dies; desktop after quit
install/vr-app       — run by labwc -S: runs the app, restarts it after a crash
install/labwc/rc.xml — static labwc config (no compositor shortcuts)
```

## Boot / session design

The kiosk is an ordinary auto-login desktop session, not a root system service:
greetd logs the kiosk user in, logind hands the session the display, input and
sound devices, udisks2 mounts the USB stick. Do not reintroduce boot-ordering
workarounds (seatd, plymouth ordering, fbcon cmdline edits, DRM card
detection, root services) — that design was unreliable, especially on a Pi 4,
and is what this replaced. If something goes wrong at boot, look for what the
standard session machinery is missing rather than working around it.

## Hardware notes

- Raspberry Pi 5 (primary, tested) or Pi 4; both have two micro-HDMI ports
- Never hard-code the DRM card number: on a Pi 4, v3d/vc4 swap between card0/card1 across boots (wlroots picks the right one itself)
- HDMI-A-1 is the port closest to the USB-C power connector (monitor 1)
- HDMI-A-2 is the other port (monitor 2)
- Elgato Stream Deck: any model supported (Mini, Classic, XL, etc.)
- App runs as the kiosk user (by default whoever ran setup), not root
- Audio goes straight to each HDMI port's ALSA device; vr-session stops PipeWire while the kiosk runs
- Videos loop indefinitely; only one video plays at a time across both monitors
