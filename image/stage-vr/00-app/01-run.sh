#!/bin/bash -e
# Install the app exactly as on a hand-built Pi, by running install/setup.sh
# inside the image. VR_IMAGE_BUILD=1 makes it install and enable without
# starting anything.
SRC=/opt/video-reinforcer-src

rm -rf "${ROOTFS_DIR}${SRC}"
cp -a files/video-reinforcer-src "${ROOTFS_DIR}${SRC}"
install -d "${ROOTFS_DIR}/opt/video-reinforcer"
install -m 644 files/image-version "${ROOTFS_DIR}/opt/video-reinforcer/image-version"

on_chroot << CHROOT
git config --system --add safe.directory ${SRC}
VR_IMAGE_BUILD=1 bash ${SRC}/install/setup.sh
CHROOT
