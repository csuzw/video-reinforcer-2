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
usb_monitor.py       — pyudev watcher for USB mount/unmount
video_player.py      — one persistent mpv process per monitor; IPC + watchdog
display_manager.py   — coordinates video players; detects monitor connect/disconnect
deck_manager.py      — Stream Deck input + USB hotplug detection; reconnects automatically
keyboard_reader.py   — evdev raw keyboard input
button_renderer.py   — PIL image rendering for Stream Deck keys
```

## Hardware notes

- Raspberry Pi 5 with two micro-HDMI ports
- HDMI-A-1 is the port closest to the USB-C power connector (monitor 1)
- HDMI-A-2 is the other port (monitor 2)
- Elgato Stream Deck: any model supported (Mini, Classic, XL, etc.)
- App runs as root (required for USB mounting and DRM access)
- Videos loop indefinitely; only one video plays at a time across both monitors
