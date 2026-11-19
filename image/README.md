# Video Reinforcer SD card image

A ready-to-flash Raspberry Pi OS Lite (64-bit, Debian trixie) image with the
app already installed. It works on both the Pi 4 and the Pi 5. Flash it, plug
in the USB stick and monitors, and power on. There's no setup script and no
SSH needed.

It also includes [Tailscale](https://tailscale.com), so each device can be
reached for support from anywhere, without knowing its IP address.

> **Status:** new. The build is automated, but the image has not yet been
> tested on every Pi model. Report problems with the device model and what
> the screens show.

---

## Getting the image

- **Releases:** tagged versions (`v*`) attach `video-reinforcer-*.img.xz` to
  the GitHub release.
- **Any branch build:** GitHub → Actions → *Build SD card image* → pick a run →
  *Artifacts*. The download is a zip containing the `.img.xz`; unzip it but
  leave the `.img.xz` as it is.

## Flashing

1. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. *Choose OS* → *Use custom* → select the `.img.xz`.
3. When asked about OS customisation, choose *Edit settings* and set:
   - **Hostname**, e.g. `vr-clinic-a`. It becomes the device's name in
     Tailscale. Use a different one per device.
   - **Wi-Fi** network and country, unless it will use an Ethernet cable.
   - Optionally, under *Services*, **enable SSH with public-key auth only** and
     paste your public key. This is a fallback for when Tailscale isn't set up.
   - Leave the username alone, or set any; nothing depends on it.

   If Imager doesn't offer customisation for the custom image, edit
   `network-config` on the card's `bootfs` drive by hand for Wi-Fi (there are
   examples in the file).
4. Write the card. Before ejecting it, add the Tailscale key (below).

## Tailscale (remote access)

### One-off account setup

Do this once in the [Tailscale admin console](https://login.tailscale.com/admin):

1. **Access controls:** add a tag for the devices and allow yourself to SSH in:
   ```jsonc
   "tagOwners": {
     "tag:video-reinforcer": ["autogroup:admin"]
   },
   "ssh": [
     {
       "action": "accept",
       "src":    ["autogroup:admin"],
       "dst":    ["tag:video-reinforcer"],
       "users":  ["root", "vr"]
     }
   ]
   ```
   If your policy has restrictive `acls`/`grants`, also allow admins to reach
   `tag:video-reinforcer`. The default allow-all policy needs nothing extra.
2. **Settings → Keys → Generate auth key:** tick **Reusable** and
   **Pre-approved**, and set tag `tag:video-reinforcer`. One key can then be
   used for every device until it expires (max 90 days; make a new one after
   that). Tagged devices never expire once joined.

The key is never put in this repo or the image. It's added to each card
after flashing.

### Per device

After flashing, open the card's **`bootfs`** drive on your PC and create a
text file called **`tailscale-authkey`** containing just the key
(`tskey-auth-…`). A Notepad file saved as `tailscale-authkey.txt` works too.

On first boot with a network connection, the device joins your tailnet under
its hostname and **deletes the key file**. If there's no network yet, it
keeps the file and tries again on each boot.

A card flashed without a key can be added later. Put the file on `bootfs`
and reboot, or SSH in and run `sudo tailscale up --ssh`.

### Connecting

```bash
ssh vr@vr-clinic-a           # Tailscale SSH (from any device on your tailnet)
ssh root@vr-clinic-a
```

Useful once connected:

```bash
journalctl -u video-reinforcer -b      # app log for this boot
journalctl -u labwc -b                 # display/compositor log
cat /opt/video-reinforcer/image-version
sudo vr-update                         # update app to latest master
sudo vr-update some-branch             # ...or to a branch, to test a fix
```

## Updating devices

- **Over Tailscale:** `sudo vr-update`. It pulls from GitHub and re-runs
  `install/setup.sh`, the same as on a hand-built Pi.
- **Or re-flash** with a newer image. The USB stick keeps all the videos and
  config, so nothing on the card needs keeping, apart from any
  `video-reinforcer.conf` hardware overrides.

## Hardware settings

`bootfs` also contains `video-reinforcer.conf` for overriding which port is
monitor 1/2 and which sound device each uses. Normally it needs no changes
(see *Hardware settings* in the main README).

---

## Building the image yourself

CI builds it on every push that changes `image/` or `install/` (see
`.github/workflows/image.yml`). That's the easy way. To build locally:

- Linux or WSL2 with Docker, git and openssl.
- Commit first: the image contains the repo's current commit, not
  uncommitted changes.

```bash
bash image/build.sh
# → image/deploy/video-reinforcer-*.img.xz
```

On an x86 PC the 64-bit Arm parts run under QEMU emulation, which is slow:
expect an hour or more. On an arm64 machine (including a Pi 5) it's much
faster.

### How it works

- **pi-gen** (Raspberry Pi's own image builder, pinned in `build.sh`) builds
  stages 0–2, which is Raspberry Pi OS Lite.
- **`stage-vr/00-app`** copies this repo to `/opt/video-reinforcer-src` and
  runs `install/setup.sh` inside the image, with `VR_IMAGE_BUILD=1` so it
  installs and enables services without trying to start them.
- **`stage-vr/01-tailscale`** installs Tailscale and the one-off
  `vr-tailscale-up` service that joins using the key file.
- **`config`** sets the hostname `video-reinforcer`, user `vr` (random
  password, never recorded), UK locale, no password SSH, and keeps cloud-init
  so Imager's settings apply.
