#!/bin/bash -e
install -m 755 files/vr-tailscale-up "${ROOTFS_DIR}/usr/local/sbin/vr-tailscale-up"
install -m 644 files/vr-tailscale-up.service "${ROOTFS_DIR}/etc/systemd/system/vr-tailscale-up.service"
on_chroot << CHROOT
systemctl enable tailscaled
systemctl enable vr-tailscale-up
CHROOT
