#!/bin/bash -e
# Add Tailscale's apt repository (Debian trixie). Done from the host side,
# where curl is guaranteed; the package itself is installed by 01-packages.
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg \
	-o "${ROOTFS_DIR}/usr/share/keyrings/tailscale-archive-keyring.gpg"
curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list \
	-o "${ROOTFS_DIR}/etc/apt/sources.list.d/tailscale.list"
on_chroot << CHROOT
apt-get update
CHROOT
