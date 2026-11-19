"""Watches for USB sticks and mounts them read-only through udisks2.

The app runs as an ordinary user in a desktop session, so it cannot call
mount(8) itself. udisks2 is the standard way desktops mount removable media:
its default policy lets the user of the active local session mount removable
drives without a password, and refuses system disks (the SD card, or the boot
SSD on a USB-booted Pi). Mounts appear under /media/<user>/<label>.
"""
import logging
import subprocess
import time
import threading
from typing import Callable, Optional

import pyudev

SETTLE_DELAY = 1.5  # seconds to wait after device appears before mounting
_MOUNT_ROOTS = ("/media/", "/run/media/")  # where udisks2 puts removable media

log = logging.getLogger(__name__)


def _existing_mount(device_node: str, mounts_file: str = "/proc/mounts") -> Optional[str]:
    """Where device_node is already mounted as removable media, if anywhere.

    Mounts outside the udisks media folders (e.g. "/" or /boot/firmware) are
    ignored, so system partitions are never mistaken for the USB stick.
    """
    try:
        with open(mounts_file) as f:
            for line in f:
                fields = line.split()
                if len(fields) < 2 or fields[0] != device_node:
                    continue
                # /proc/mounts escapes spaces in paths as \040
                path = fields[1].replace("\\040", " ")
                if path.startswith(_MOUNT_ROOTS):
                    return path
    except OSError:
        pass
    return None


def _parse_mount_output(text: str) -> Optional[str]:
    """Mount point from udisksctl's "Mounted /dev/sda1 at /media/u/STICK"."""
    marker = " at "
    if marker not in text:
        return None
    return text.split(marker, 1)[1].strip().rstrip(".") or None


class USBMonitor:
    def __init__(self, on_mounted: Callable[[], None], on_unmounted: Callable[[], None]):
        self._on_mounted = on_mounted
        self._on_unmounted = on_unmounted
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem="block", device_type="partition")
        self._mounted_device: Optional[str] = None
        self._mount_point: Optional[str] = None
        self._we_mounted = False
        self._observer: Optional[pyudev.MonitorObserver] = None
        self._lock = threading.Lock()

    @property
    def mount_point(self) -> Optional[str]:
        """Folder the current USB stick is mounted at, or None."""
        return self._mount_point

    def start(self):
        self._observer = pyudev.MonitorObserver(self._monitor, callback=self._handle_event)
        self._observer.start()
        # Check for already-connected USB devices
        self._scan_existing()

    def stop(self):
        if self._observer:
            self._observer.stop()
        with self._lock:
            self._unmount(notify=False)

    def _scan_existing(self):
        for device in self._context.list_devices(subsystem="block", DEVTYPE="partition"):
            if self._try_mount(device.device_node):
                return

    def _handle_event(self, device):
        action = device.action
        if action == "add":
            # Brief delay for filesystem to settle after device appears
            time.sleep(SETTLE_DELAY)
            self._try_mount(device.device_node)
        elif action == "remove":
            with self._lock:
                if self._mounted_device == device.device_node:
                    # The device is gone; udisks2 cleans up its own mount.
                    self._we_mounted = False
                    self._unmount(notify=True)

    def _try_mount(self, device_node: str) -> bool:
        with self._lock:
            if self._mounted_device:
                return False

            path = _existing_mount(device_node)
            we_mounted = False
            if path is None:
                path = self._udisks_mount(device_node)
                we_mounted = path is not None
            if path is None:
                return False

            self._mounted_device = device_node
            self._mount_point = path
            self._we_mounted = we_mounted
            log.info("USB stick %s at %s", device_node, path)
            threading.Thread(target=self._on_mounted, daemon=True).start()
            return True

    def _udisks_mount(self, device_node: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["udisksctl", "mount", "--no-user-interaction", "-b", device_node, "-o", "ro"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            log.error("udisksctl not found; install udisks2 (re-run setup.sh)")
            return None
        except subprocess.TimeoutExpired:
            log.warning("Mount timed out for %s", device_node)
            return None
        if result.returncode != 0:
            # Expected for system partitions (not authorised) and partitions
            # without a filesystem; only worth a debug line.
            log.debug("Not mounting %s: %s", device_node, result.stderr.strip())
            return None
        path = _parse_mount_output(result.stdout)
        if path is None:
            log.warning("Mounted %s but could not read where: %r", device_node, result.stdout)
        return path

    def _unmount(self, notify: bool):
        # Must be called with _lock held
        if not self._mounted_device:
            return
        device = self._mounted_device
        if self._we_mounted:
            try:
                subprocess.run(
                    ["udisksctl", "unmount", "--no-user-interaction", "-b", device],
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                log.warning("Unmount error: %s", e)
        self._mounted_device = None
        self._mount_point = None
        self._we_mounted = False
        log.info("USB stick %s removed", device)
        if notify:
            threading.Thread(target=self._on_unmounted, daemon=True).start()
