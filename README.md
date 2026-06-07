# Video Reinforcer

A Raspberry Pi 5 kiosk application for video reinforcement audiometry. An Elgato Stream Deck (or keyboard) triggers full-screen looping video on a specific HDMI monitor, with audio delivered through that monitor's built-in speakers. Only one video plays at a time. Monitors are blank and silent otherwise.

---

## Supported hardware and OS

| Component | Requirement |
|---|---|
| **Pi model** | Raspberry Pi 5 only |
| **Operating system** | Any 64-bit Linux with labwc, seatd, mpv, systemd, and Python 3 |
| **Monitors** | Up to 2, connected via micro-HDMI; audio delivered over HDMI |
| **Input device** | Elgato Stream Deck (any model) and/or USB keyboard |
| **Config/video storage** | USB stick |

The app itself has no OS-specific code. The Pi 5 requirement comes from the hardware: the audio device names, DRM card assignment, and DRM plane allocation flags are all Pi 5-specific. The provided setup script (`install/setup.sh`) uses `apt-get` and is written for Debian-based distributions (Raspberry Pi OS, Ubuntu, etc.). On other package managers the dependencies would need to be installed manually before running the app.

---

## How it works

1. The Pi boots directly into the app — no login prompt.
2. The app reads `config.json` from a USB stick to determine which buttons play which videos on which monitor.
3. Press a Stream Deck button (or keyboard key) → video starts looping on the assigned monitor.
4. Press the same button again → video stops, monitor goes blank.
5. Press a different button → current video stops, new video starts on its assigned monitor.
6. Remove the USB stick → both monitors show an error message, all buttons go dark.
7. Re-insert the USB stick (with the same or updated config) → app reloads automatically, no reboot needed.

### Architecture

The app runs as a systemd service. It starts **labwc** (the default Wayland compositor on Raspberry Pi OS Bookworm) to drive both HDMI outputs, then launches a persistent **mpv** process per monitor. labwc places each mpv window on the correct output and fullscreens it. The Python process manages config loading, USB hot-plug, Stream Deck input, and IPC to each mpv instance.

When the app stops (via the quit button or `systemctl stop`), the desktop display manager restarts automatically.

---

## USB stick layout

```
/usb-stick/
  config.json
  videos/
    reward1.mp4
    reward2.mp4
  button-images/       ← optional, only needed for image-style buttons
    stars.png
```

The app looks for `config.json` at the root of the USB stick. Videos and button images can be in any subfolder — paths in `config.json` are relative to the root of the USB stick.

---

## config.json reference

```json
{
  "quit": {
    "stream_deck_button": 5,
    "key": "F12",
    "button": {
      "type": "color",
      "color": "#CC0000",
      "label": "QUIT"
    }
  },
  "buttons": {
    "0": {
      "video": "videos/reward1.mp4",
      "monitor": 1,
      "key": "F1",
      "button": {
        "type": "color",
        "color": "#E63946",
        "label": "Left"
      }
    },
    "1": {
      "video": "videos/reward2.mp4",
      "monitor": 2,
      "key": "F2",
      "button": {
        "type": "image",
        "image": "button-images/stars.png",
        "label": "Right"
      }
    }
  }
}
```

### `buttons`

Each entry maps a Stream Deck key index to a video. Key `"0"` is the top-left button on the Stream Deck.

| Field | Required | Description |
|---|---|---|
| `video` | Yes | Path to the video file, relative to the USB stick root |
| `monitor` | No | Which monitor to play on — `1` or `2` (default: `1`) |
| `key` | No | Keyboard key that triggers this button (see key names below) |
| `button.type` | No | `"color"` or `"image"` (default: `"color"`) |
| `button.color` | No | Hex colour for the Stream Deck key, e.g. `"#E63946"` |
| `button.image` | No | Path to a PNG/JPG to display on the key (when type is `"image"`) |
| `button.label` | No | Short text drawn at the bottom of the key |

Buttons not listed in `config.json` remain dark on the Stream Deck.

### `quit` (optional)

Stops the app cleanly and returns to the desktop. The service does not restart until the Pi is rebooted or the service is started manually via SSH.

| Field | Required | Description |
|---|---|---|
| `stream_deck_button` | No | Stream Deck key index for the quit button |
| `key` | No | Keyboard key that triggers quit |
| `button.*` | No | Appearance of the quit key on the Stream Deck (same fields as above) |

Either or both of `stream_deck_button` and `key` can be specified. If `quit` is omitted entirely, there is no quit button — use SSH instead.

### Keyboard key names

Key names are case-insensitive. Common values:

| Config value | Key |
|---|---|
| `"F1"` – `"F12"` | Function keys |
| `"1"` – `"0"` | Number row |
| `"a"` – `"z"` | Letter keys |
| `"space"` | Space bar |
| `"enter"` | Enter / Return |
| `"escape"` | Escape |

### Monitor numbering

`1` is the micro-HDMI port closest to the USB-C power connector on the Pi 5. `2` is the other port.

---

## Installation

### 1. Install a 64-bit Linux OS

The easiest option is [Raspberry Pi OS](https://www.raspberrypi.com/software/) (Lite or Desktop, 64-bit), flashed with Raspberry Pi Imager. When prompted:

- **Enable SSH** in the advanced options
- Set a hostname, username, and password

Any other 64-bit Linux distribution works provided `labwc`, `seatd`, `mpv`, `ffmpeg`, `python3`, and `libhidapi` are available.

### 2. Clone and run setup

SSH into the Pi, then:

```bash
git clone https://github.com/csuzw/video-reinforcer-2.git
cd video-reinforcer-2
sudo bash install/setup.sh
```

The setup script:
- Installs system packages: `mpv`, `labwc`, `seatd`, Python dev tools, HID libraries
- Deploys the app to `/opt/video-reinforcer`
- Generates a blank video used as the OSD background
- Disables any running desktop display manager (saves its name so it can be restored when the app exits)
- Installs and enables three systemd services: `seatd`, `labwc`, and `video-reinforcer`

### 3. Insert the USB stick and reboot

```bash
sudo reboot
```

The Pi boots directly into the app. Insert your configured USB stick and the buttons will light up.

---

## Updating the app

```bash
cd video-reinforcer-2
git pull
sudo bash install/setup.sh
```

---

## Running the tests

The test suite covers config parsing, button rendering, display logic, and the full app state machine. Tests run without any hardware connected — all hardware components (mpv, Stream Deck, USB mounting) are mocked out.

```bash
pip3 install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

---

## Updating videos or button config

No app update needed — just edit the files on the USB stick from any PC, then re-insert it into the Pi. The app detects the replug and reloads automatically.

---

## Getting back to the desktop or a shell

### Via the quit button

If a quit button is configured in `config.json`, pressing it stops the app cleanly. The desktop display manager restarts automatically and you can log in normally.

### Via SSH

```bash
ssh <username>@<pi-hostname>

# Stop the app — desktop restarts automatically
sudo systemctl stop video-reinforcer

# Prevent it from starting on next boot
sudo systemctl disable video-reinforcer

# Re-enable and start it again
sudo systemctl enable video-reinforcer && sudo systemctl start video-reinforcer
```

### Useful commands

```bash
# View live logs
journalctl -u video-reinforcer -f

# Check service status
systemctl status video-reinforcer

# Check compositor status
systemctl status labwc
```

---

## Error handling and recovery

Every error state is shown on screen in plain English. The app recovers automatically when the problem is resolved — no restart needed.

| Situation | What you see | Recovery |
|---|---|---|
| No USB stick | Error on all monitors, buttons dark | Insert USB stick |
| Bad `config.json` | Error on all monitors, buttons dark | Fix config, re-insert USB stick |
| USB replugged | Config reloads automatically | — |
| Button pressed for disconnected monitor | 4-second error, then clears | Check cables or fix `config.json` |
| Video file missing or unplayable | 4-second error, then clears | Check files on USB stick |
| Monitor unplugged while running | Error on remaining monitors | Reconnect monitor |
| Stream Deck unplugged | Error on all monitors | Reconnect — buttons relight automatically |

---

## Troubleshooting

**Monitors show an error message**
- The error text on screen describes the specific problem.
- Check the USB stick is inserted and contains `config.json` at its root.
- Validate `config.json` with a JSON validator on another PC.
- Check that all video and image paths in `config.json` match files on the USB stick.

**Video plays but no audio**
- Ensure the monitor's volume is turned up.
- Check the correct monitor is assigned in `config.json` — monitor `1` is the port nearest the power connector.

**App doesn't start on boot**
```bash
systemctl status video-reinforcer
systemctl status labwc
journalctl -u video-reinforcer -b
```
- Re-running `sudo bash install/setup.sh` will reinstall and restart everything.

**Monitors stay blank after boot (no error message)**
- labwc may have failed to start. Check: `systemctl status labwc`
- If labwc crashed, check: `journalctl -u labwc -b`

**Pi boots to a text console / login prompt instead of the kiosk app**
- All services may show as "active" yet nothing is on screen — something else
  held DRM master when labwc started, so it can never render
  (`journalctl -u labwc -b` shows repeated `drmModeAtomicCommit: Permission
  denied` and `journalctl -u seatd -b` shows `Could not make device fd drm
  master: Device or resource busy`). The screen then just shows the kernel's
  raw console (with the autologin root shell on top).
- Two known causes, both fixed by the current `setup.sh`/`labwc.service`:
  - The kernel's own framebuffer console (`vc4drmfb`) binding to the real
    display — fixed by `fbcon=map:1` in `/boot/firmware/cmdline.txt`
    (redirects it to a non-existent `fb1`, so it never claims the real device).
  - Plymouth (boot splash) still holding master when labwc starts — fixed by
    `labwc.service` ordering itself `After=plymouth-quit.service`, the same
    dependency display managers like lightdm use.
- If you hit this after manually editing service files, re-run
  `sudo bash install/setup.sh` to reinstall them and reboot.
