import logging
import select
import threading
import time
from typing import Callable, List, Optional

import pyudev

log = logging.getLogger(__name__)

try:
    import evdev
    from evdev import categorize, ecodes
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_KEY_PREFIX = "KEY_"
_RESCAN_SETTLE_DELAY = 1.0  # seconds to let device nodes appear after a hotplug event


def _normalize(keycode) -> str:
    """Convert evdev keycode to config-friendly lowercase string.

    Examples: 'KEY_F1' → 'f1', ['KEY_A', 'KEY_B'] → 'a'
    """
    if isinstance(keycode, list):
        keycode = keycode[0]
    name = str(keycode).upper()
    if name.startswith(_KEY_PREFIX):
        name = name[len(_KEY_PREFIX):]
    return name.lower()


class KeyboardReader:
    """Reads raw key-down events from all connected keyboards via evdev.

    Keyboards can be plugged or unplugged at any time, so a udev watcher
    triggers a rescan on every input hotplug event — no restart needed.
    """

    def __init__(self, on_key: Callable[[str], None]):
        self._on_key = on_key
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._devices: List = []
        self._lock = threading.Lock()
        self._udev_observer: Optional[pyudev.MonitorObserver] = None

    def start(self):
        if not _AVAILABLE:
            log.warning("evdev not installed — keyboard input disabled")
            return
        self._running = True
        self._rescan()
        self._start_udev_watch()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._udev_observer:
            self._udev_observer.stop()
        with self._lock:
            for dev in self._devices:
                try:
                    dev.close()
                except Exception:
                    pass
            self._devices = []

    # ------------------------------------------------------------------
    # Hotplug
    # ------------------------------------------------------------------

    def _start_udev_watch(self):
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="input")
        self._udev_observer = pyudev.MonitorObserver(monitor, callback=self._handle_udev_event)
        self._udev_observer.start()
        log.debug("Keyboard hotplug watcher started")

    def _handle_udev_event(self, device):
        if device.action not in ("add", "remove"):
            return
        # Run off the udev callback thread so it returns promptly; give
        # device nodes a moment to settle before re-enumerating.
        threading.Thread(target=self._rescan_after_settle, daemon=True).start()

    def _rescan_after_settle(self):
        time.sleep(_RESCAN_SETTLE_DELAY)
        self._rescan()

    def _rescan(self):
        found = self._find_keyboards()
        with self._lock:
            for dev in self._devices:
                try:
                    dev.close()
                except Exception:
                    pass
            self._devices = found
        if found:
            log.info("Keyboard reader active (%d device(s))", len(found))
        else:
            log.info("No keyboards detected")

    # ------------------------------------------------------------------
    # Device discovery / reading
    # ------------------------------------------------------------------

    def _find_keyboards(self) -> list:
        found = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                # Must have key events and at least one letter key to be a keyboard
                if ecodes.EV_KEY in caps and ecodes.KEY_A in caps[ecodes.EV_KEY]:
                    found.append(dev)
                    log.info("Found keyboard: %s (%s)", dev.name, path)
            except Exception:
                pass
        return found

    def _run(self):
        while self._running:
            with self._lock:
                device_map = {dev.fd: dev for dev in self._devices}
            try:
                readable, _, _ = select.select(device_map, [], [], 1.0)
                for fd in readable:
                    dev = device_map.get(fd)
                    if dev is None:
                        continue
                    try:
                        for event in dev.read():
                            if event.type == ecodes.EV_KEY:
                                key_event = categorize(event)
                                if key_event.keystate == key_event.key_down:
                                    self._on_key(_normalize(key_event.keycode))
                    except OSError:
                        pass  # device went away mid-read; rescan will clean it up
            except Exception as e:
                if self._running:
                    log.warning("Keyboard read error: %s", e)
