import logging
import os
import subprocess
import time
import threading
from typing import Callable, Optional

import pyudev

USB_MOUNT = "/mnt/vr-usb"
SETTLE_DELAY = 1.5  # seconds to wait after device appears before mounting

log = logging.getLogger(__name__)


class USBMonitor:
    def __init__(self, on_mounted: Callable[[], None], on_unmounted: Callable[[], None]):
        self._on_mounted = on_mounted
        self._on_unmounted = on_unmounted
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem="block", device_type="partition")
        self._mounted_device: Optional[str] = None
        self._observer: Optional[pyudev.MonitorObserver] = None
        self._lock = threading.Lock()

    def start(self):
        os.makedirs(USB_MOUNT, exist_ok=True)
        self._observer = pyudev.MonitorObserver(self._monitor, callback=self._handle_event)
        self._observer.start()
        # Check for already-connected USB devices
        self._scan_existing()

    def stop(self):
        if self._observer:
            self._observer.stop()
        self._unmount()

    def _scan_existing(self):
        for device in self._context.list_devices(subsystem="block", DEVTYPE="partition"):
            if self._try_mount(device.device_node):
                return

    def _handle_event(self, action: str, device):
        if action == "add":
            # Brief delay for filesystem to settle after device appears
            time.sleep(SETTLE_DELAY)
            self._try_mount(device.device_node)
        elif action == "remove":
            with self._lock:
                if self._mounted_device == device.device_node:
                    self._unmount()

    def _try_mount(self, device_node: str) -> bool:
        with self._lock:
            # Already have something mounted — try to clean up first
            if self._mounted_device:
                return False

            try:
                result = subprocess.run(
                    ["mount", "-o", "ro", device_node, USB_MOUNT],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    self._mounted_device = device_node
                    log.info("Mounted %s at %s", device_node, USB_MOUNT)
                    threading.Thread(target=self._on_mounted, daemon=True).start()
                    return True
                else:
                    log.debug("Could not mount %s: %s", device_node, result.stderr.decode().strip())
            except subprocess.TimeoutExpired:
                log.warning("Mount timed out for %s", device_node)
            except Exception as e:
                log.warning("Mount error for %s: %s", device_node, e)
        return False

    def _unmount(self):
        # Must be called with _lock held or at shutdown
        if not self._mounted_device:
            return
        device = self._mounted_device
        self._mounted_device = None
        try:
            subprocess.run(["umount", USB_MOUNT], capture_output=True, timeout=10)
        except Exception as e:
            log.warning("Unmount error: %s", e)
        log.info("Unmounted %s", device)
        threading.Thread(target=self._on_unmounted, daemon=True).start()
