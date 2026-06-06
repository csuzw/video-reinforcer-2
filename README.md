# Video Reinforcer

A Raspberry Pi 5 kiosk application for video reinforcement audiometry. An Elgato Stream Deck (or keyboard) triggers full-screen looping video on a specific HDMI monitor, with audio delivered through that monitor's built-in speakers. Only one video plays at a time. Monitors are blank and silent otherwise.

## How it works

1. The Pi boots directly into the app — no desktop, no login prompt.
2. The app reads `config.json` from a USB stick to determine which buttons play which videos on which monitor.
3. Press a Stream Deck button (or keyboard key) → video starts looping on the assigned monitor.
4. Press the same button again → video stops, monitor goes blank.
5. Press a different button → current video stops, new video starts on its assigned monitor.
6. Remove the USB stick → both monitors show an error message, all buttons go dark.
7. Re-insert the USB stick (with the same or updated config) → app reloads automatically, no reboot needed.

---

## Hardware requirements

- Raspberry Pi 5
- Up to 2 HDMI monitors with built-in speakers (audio is delivered via HDMI)
- Elgato Stream Deck — any model works (Mini 6-key, Classic 15-key, XL 32-key, etc.)
- USB stick for videos and configuration
- Optional: USB keyboard (can be used instead of or alongside the Stream Deck)

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

The app looks for `config.json` at the root of the USB stick. Videos and button images can be in any subfolder — the paths in `config.json` are relative to the root of the USB stick.

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

Stops the app cleanly and prevents it from auto-restarting until manually started again (useful for maintenance or accessing the underlying OS via SSH).

| Field | Required | Description |
|---|---|---|
| `stream_deck_button` | No | Stream Deck key index for the quit button |
| `key` | No | Keyboard key that triggers quit |
| `button.*` | No | Appearance of the quit key on the Stream Deck (same fields as above) |

Either or both of `stream_deck_button` and `key` can be specified. If `quit` is omitted entirely, there is no quit button — use SSH instead (see below).

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

`1` refers to the HDMI port closest to the USB-C power connector on the Pi 5. `2` is the other port.

---

## Installation

### 1. Flash Raspberry Pi OS Lite (64-bit)

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/). When prompted:

- Choose **Raspberry Pi OS Lite (64-bit)** — no desktop needed
- **Enable SSH** in the advanced options (this gives you a way back in if anything goes wrong)
- Set a hostname, username, and password

### 2. Clone and run setup

SSH into the Pi, then:

```bash
git clone https://github.com/csuzw/video-reinforcer-2.git
cd video-reinforcer-2
sudo bash install/setup.sh
```

The setup script installs system dependencies (`mpv`, Python packages, etc.), deploys the app to `/opt/video-reinforcer`, and registers it as a systemd service that starts automatically on boot.

### 3. Insert the USB stick and reboot

```bash
sudo reboot
```

The Pi will boot directly into the app. Insert your configured USB stick and the buttons will light up.

---

## Updating the app

To pull the latest code and redeploy:

```bash
cd video-reinforcer-2
git pull
sudo bash install/setup.sh
```

---

## Running the tests

The test suite covers config parsing, button rendering, display logic, and the full app state machine. Tests run on the Pi without any hardware connected — all hardware components (mpv, Stream Deck, USB mounting) are mocked out.

```bash
# Install dev dependencies (once)
pip3 install -r requirements-dev.txt

# Run all tests
cd /path/to/video-reinforcer-2
python3 -m pytest tests/ -v
```

Example output:

```
tests/test_config_loader.py::TestParseButtons::test_minimal_valid_config PASSED
tests/test_config_loader.py::TestParseButtons::test_missing_buttons_section PASSED
...
tests/test_main.py::TestDeckEvents::test_deck_disconnect_during_playing_does_not_interrupt PASSED
```

The tests do **not** require a USB stick, Stream Deck, monitors, or videos to be present.

---

## Updating videos or button config

No app update needed — just edit the files on the USB stick from any PC, then re-insert it into the Pi. The app detects the replug and reloads automatically.

---

## Getting back to a normal shell

The app runs as a background service. The underlying Raspberry Pi OS is always intact. Several ways to access it:

### Via SSH (recommended)

```bash
ssh pi@<pi-ip-address>

# Stop the app (stays stopped until manually started or rebooted)
sudo systemctl stop video-reinforcer

# Prevent it from starting on next boot
sudo systemctl disable video-reinforcer

# Re-enable and start it again later
sudo systemctl enable video-reinforcer && sudo systemctl start video-reinforcer
```

### Via the quit button

If a quit button is configured in `config.json`, pressing it stops the service cleanly. The monitors will go blank. You can then SSH in or plug in a keyboard and use the Pi normally.

### Useful commands

```bash
# View live logs from the app
journalctl -u video-reinforcer -f

# Check service status
systemctl status video-reinforcer

# Restart the app (e.g. after a config change requires restart)
sudo systemctl restart video-reinforcer
```

---

## Error handling and recovery

The app is designed to display a clear message on screen for every error state, and to recover automatically when the problem is resolved — no restart required.

| Situation | What you see | Recovery |
|---|---|---|
| No USB stick | Error on all monitors, buttons dark | Insert USB stick |
| Bad config.json | Error on all monitors, buttons dark | Fix config, re-insert USB stick |
| USB replugged | Config reloads automatically | — |
| Button pressed for disconnected monitor | 4-second error, then clears | Check cables or fix config.json |
| Video file missing or unplayable | 4-second error, then clears | Check files on USB stick |
| Monitor unplugged while running | Error on remaining monitors | Reconnect monitor |
| Stream Deck unplugged | Error on all monitors | Reconnect Stream Deck — buttons relight automatically |

---

## Troubleshooting

**Monitors show an error message**
- The error message on screen will tell you the specific problem.
- Check the USB stick is inserted and contains `config.json` at its root.
- Check `config.json` is valid JSON (use a JSON validator on another PC).
- Check that all video and image paths in `config.json` match files that exist on the USB stick.

**Video plays but no audio**
- Ensure the monitor's volume is turned up.
- Check the correct monitor is assigned in `config.json` — monitor `1` is the HDMI port nearest the power connector.

**App doesn't start on boot**
- Check: `systemctl status video-reinforcer`
- Check logs: `journalctl -u video-reinforcer -f`
- Re-run `sudo bash install/setup.sh` to reinstall.
