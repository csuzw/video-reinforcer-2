# Video Reinforcer

A Raspberry Pi 4 / Pi 5 kiosk application for video reinforcement audiometry. An Elgato Stream Deck (or keyboard) triggers full-screen looping video on a specific HDMI monitor, with audio delivered through that monitor's built-in speakers. Only one video plays at a time. Monitors are blank and silent otherwise.

---

## Supported hardware and OS

| Component | Requirement |
|---|---|
| **Device** | Raspberry Pi 5 or Pi 4 (tested mainly on Pi 5). Other Linux PCs should work, untested |
| **Operating system** | Raspberry Pi OS (Lite or Desktop, 64-bit), or any Debian-based Linux with systemd that packages labwc, greetd, udisks2, mpv and Python 3 |
| **Monitors** | Up to 2, connected via HDMI (or DisplayPort etc. on a PC); audio delivered over HDMI |
| **Input device** | Elgato Stream Deck (any model) and/or USB keyboard |
| **Config/video storage** | USB stick |

Hardware is detected every time the app starts (`src/hardware.py`):
- **Monitor 1 and 2:** the first two external ports, HDMI before DisplayPort, in port-number order. On a Pi that's `HDMI-A-1` and `HDMI-A-2`.
- **Audio:** on a Pi, each HDMI port's own sound device (`vc4hdmi0`/`vc4hdmi1`). On other hardware there's no reliable automatic mapping, so the system default sound device is used unless you set one (see [Hardware settings](#hardware-settings)).

The provided setup script (`install/setup.sh`) uses `apt-get` and is written for Debian-based distributions (Raspberry Pi OS, Ubuntu, etc.). On other package managers the dependencies would need to be installed manually before running the app.

---

## How it works

1. The Pi boots directly into the app — no login prompt.
2. The app reads `config.json` from a USB stick to determine which buttons play which videos on which monitor.
3. Press a Stream Deck button (or keyboard key) → video starts looping on the assigned monitor, and that key gets a red border on the Stream Deck (the colour is configurable).
4. Press the same button again → video stops, monitor goes blank.
5. Press a different button → current video stops, new video starts on its assigned monitor.
6. Remove the USB stick → both monitors show an error message, all buttons go dark.
7. Re-insert the USB stick (with the same or updated config) → app reloads automatically, no reboot needed.

### Architecture

The kiosk is an ordinary auto-login desktop session, set up the same way a normal desktop login works:

1. **greetd** (a small login manager) logs the kiosk user in at boot. By default that's the user who ran setup, e.g. the one created in Raspberry Pi Imager.
2. The session (`install/vr-session`) starts **labwc**, the Wayland compositor that Raspberry Pi OS's own desktop uses. labwc in turn runs the app (`install/vr-app`).
3. The app starts a persistent **mpv** process per monitor. Each mpv asks labwc to make it fullscreen on its monitor's output.
4. The Python process handles config loading, USB hot-plug, Stream Deck and keyboard input, and controls each mpv over IPC.

Nothing runs as root. logind, the standard Linux session manager, gives the session the display, keyboard and sound devices. udisks2, the standard way desktops mount removable drives, mounts the USB stick read-only under `/media/<user>/`.

If the app crashes it is restarted within a few seconds, and so is labwc. Pressing the quit button ends the kiosk and starts the normal desktop, if one is installed.

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
  "playing_border_color": "#FF0000",
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

### `playing_border_color` (optional)

While a video is playing, its key on the Stream Deck shows a thick coloured border. The border moves when you switch videos and disappears when the video stops, including when an error ends playback. This sets the border colour as a hex value, e.g. `"#00FF00"` for green. Default: `"#FF0000"` (red). An invalid value shows a configuration error on screen.

### `buttons`

Each entry maps a Stream Deck key index to a video. Key `"0"` is the top-left button on the Stream Deck, counting left to right, then top to bottom (on a 5×3 Classic, `"3"` is the fourth key on the top row). Every button is always on the Stream Deck — the optional `key` field adds a keyboard shortcut for it as well.

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

Stops the app cleanly and starts the normal desktop as the same user (on Raspberry Pi OS Lite, which has no desktop, you get a text login prompt instead). The kiosk starts again at the next reboot.

| Field | Required | Description |
|---|---|---|
| `stream_deck_button` | No | Stream Deck key index for the quit button |
| `key` | No | Keyboard key that triggers quit |
| `button.*` | No | Appearance of the quit key on the Stream Deck (same fields as above) |

Either or both of `stream_deck_button` and `key` can be specified. If `quit` is omitted entirely, there is no quit button: get to a terminal with Ctrl+Alt+F2 or SSH instead (see [Getting back to the desktop or a shell](#getting-back-to-the-desktop-or-a-shell)).

### Using a keyboard only (no Stream Deck)

The app only needs a Stream Deck if some action can't be triggered from the keyboard. To run with a keyboard alone:

- **every** entry in `buttons` must have a `key`, and
- if `quit` has a `stream_deck_button`, it must also have a `key`.

If any button (or quit) has no `key` and no Stream Deck is connected, the monitors show *"Stream Deck not connected"* along with the actions that have no keyboard key. Add a `key` to each listed action, or remove it, then re-insert the USB stick.

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

`1` is the micro-HDMI port closest to the USB-C power connector (labelled HDMI0 on the board, on both the Pi 4 and Pi 5). `2` is the other port. This can be changed in the hardware settings below.

---

## Hardware settings

Normally nothing needs setting: outputs and audio are detected automatically. To override them, edit `video-reinforcer.conf` on the SD card's boot partition. Plug the SD card into any PC; it's the drive called `bootfs`. The file is `/boot/firmware/video-reinforcer.conf` on the Pi itself. On a non-Pi machine use `/etc/video-reinforcer/hardware.conf` instead.

Setup creates the file with every line commented out. Remove the `#` from the lines you need and reboot:

```ini
# Swap which physical port is monitor 1 and monitor 2
MONITOR_1_OUTPUT=HDMI-A-2
MONITOR_2_OUTPUT=HDMI-A-1

# Sound device for each monitor (list them with: mpv --audio-device=help)
MONITOR_1_AUDIO=alsa/plughw:CARD=vc4hdmi0,DEV=0
MONITOR_2_AUDIO=alsa/plughw:CARD=vc4hdmi1,DEV=0
```

Output names are the DRM connector names, listed by `ls /sys/class/drm/` (e.g. `card1-HDMI-A-1` → `HDMI-A-1`). If you only change the output, the audio follows it automatically on a Pi.

---

## Installation

### 1. Install a 64-bit Linux OS

The easiest option is [Raspberry Pi OS](https://www.raspberrypi.com/software/) (Lite or Desktop, 64-bit), flashed with Raspberry Pi Imager. When prompted:

- Set a hostname, username, and password
- **Enable SSH** in the advanced options (optional, but handy for remote maintenance)

Other Debian-based distributions should work too, as long as they package `labwc`, `greetd`, `udisks2`, `mpv`, `ffmpeg` and `python3`.

### 2. Clone and run setup

Open a terminal on the Pi in one of these ways:
- **Over SSH:** `ssh <username>@<pi-hostname>`
- **On the Pi's desktop** (Raspberry Pi OS Desktop): open Terminal from the menu
- **With a keyboard plugged into the Pi**, if there's no desktop or the kiosk is already on screen: press Ctrl+Alt+F2 and log in with your username and password

Then:

```bash
git clone https://github.com/csuzw/video-reinforcer-2.git
cd video-reinforcer-2
sudo bash install/setup.sh
```

The setup script:
- Installs system packages: `mpv`, `labwc`, `greetd`, `udisks2`, Python dev tools, HID libraries
- Deploys the app to `/opt/video-reinforcer`
- Generates a blank video used as the OSD background
- Picks the kiosk user: the user who ran `sudo`. Set `VR_USER=name` to choose a different one (it's created if it doesn't exist): `sudo VR_USER=kiosk bash install/setup.sh`
- Adds that user to the `input` group, so the app can read the keyboard
- Configures greetd to log that user in at boot, and makes greetd the display manager in place of the desktop's own (e.g. `lightdm`)
- Removes the previous design's leftovers if found: the `labwc` and `video-reinforcer` system services, seatd, the root autologin on tty1, and `fbcon=map:1` in `cmdline.txt`

When run over SSH or from a Ctrl+Alt+F2 text console, setup starts the kiosk straight away and the screen switches to it (press Ctrl+Alt+F2 to get back to your console). When run from a terminal on the desktop, it doesn't, because that would close the desktop it's running in. Reboot instead.

### 3. Insert the USB stick and reboot

```bash
sudo reboot
```

The Pi boots directly into the app. Insert your configured USB stick and the buttons will light up.

---

## Updating the app

From a terminal on the Pi (SSH, or Ctrl+Alt+F2 with a keyboard; see [Installation](#2-clone-and-run-setup)):

```bash
cd video-reinforcer-2
git pull
sudo bash install/setup.sh && sudo reboot
```

The reboot isn't strictly needed (setup restarts the kiosk itself), but it confirms the Pi comes up cleanly from cold. Upgrading from a version before the greetd session works the same way; see [Troubleshooting](#troubleshooting).

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

If a quit button is configured in `config.json`, pressing it stops the app cleanly and starts the normal desktop as the kiosk user. On a system with no desktop you get a text login prompt instead. The kiosk starts again at the next reboot.

### From a keyboard

Ctrl+Alt+F2 switches to a text console where you can log in. Ctrl+Alt+F7 switches back to the kiosk.

### Via SSH or a text console

```bash
# Restart the kiosk (also picks up a re-run of setup.sh)
sudo systemctl restart greetd

# Going back to the normal desktop permanently (Raspberry Pi OS Desktop)
sudo systemctl disable greetd
sudo systemctl enable --force lightdm
sudo reboot
# ...and to return to the kiosk later, re-run: sudo bash install/setup.sh
```

### Useful commands

```bash
# View live logs (app, then compositor)
journalctl -t video-reinforcer -f
journalctl -t labwc -b

# Both together for this boot, then greetd (the login manager) on its own
journalctl -b -t video-reinforcer -t labwc
journalctl -b -u greetd

# Is the kiosk session running?
loginctl list-sessions
systemctl status greetd
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
| Stream Deck not connected (and some button or quit has no keyboard `key`) | Error on all monitors listing the actions with no keyboard key | Connect the Stream Deck — buttons relight automatically — or add a `key` to each listed action in `config.json` |

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
- The app plays sound straight to each monitor's own sound device, and switches PipeWire (the desktop's sound server) off while the kiosk runs so it can't hold those devices. Errors from mpv, including sound device errors, are in the log: `journalctl -t video-reinforcer -b`
- On non-Pi hardware, set the sound device for each monitor in the [hardware settings](#hardware-settings).

**The kiosk doesn't appear after boot (boot messages, a login prompt, or a blank screen)**

Log in over SSH, or press Ctrl+Alt+F2 on a keyboard plugged into the Pi for a text console, and collect:
```bash
journalctl -b -t video-reinforcer -t labwc --no-pager | tail -100
journalctl -b -u greetd --no-pager
loginctl list-sessions
```
- No session for the kiosk user, or greetd errors: greetd isn't set up. Re-run `sudo bash install/setup.sh` and reboot.
- labwc errors: the compositor couldn't start on the display. The log says why.
- App errors: the Python app is failing and being restarted every few seconds. The log shows the traceback.

**USB stick not detected (the error stays on screen with the stick inserted)**
- The stick is mounted by udisks2, which only mounts for the user of the active session on the screen. Check the kiosk session is the active one: `loginctl list-sessions`, then `loginctl show-session <id> -p Active`.
- The log shows each mount attempt: `journalctl -t video-reinforcer | grep -i usb`
- The stick must be FAT32, exFAT or NTFS (or any filesystem Linux reads), with `config.json` at its root.

**Upgrading from a version before the greetd session**

Earlier versions ran labwc and the app as root system services, with workarounds for boot timing (seatd, splash-screen ordering, `fbcon=map:1`, DRM card detection). Those caused the "fine on first boot, stuck after a restart" problems, especially on a Pi 4. Updating the app (`git pull`, then `sudo bash install/setup.sh`) removes all of them and switches to the greetd session. Reboot afterwards.

If the old version is stuck on boot messages, plug a keyboard into the Pi and press Ctrl+Alt+F2 to get a login prompt for running the update.
