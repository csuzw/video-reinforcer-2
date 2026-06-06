import logging
import select
import threading
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

try:
    import evdev
    from evdev import categorize, ecodes
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_KEY_PREFIX = "KEY_"


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
    """Reads raw key-down events from all connected keyboards via evdev."""

    def __init__(self, on_key: Callable[[str], None]):
        self._on_key = on_key
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._devices: List = []

    def start(self):
        if not _AVAILABLE:
            log.warning("evdev not installed — keyboard input disabled")
            return
        self._devices = self._find_keyboards()
        if not self._devices:
            log.info("No keyboards detected")
            return
        log.info("Keyboard reader started (%d device(s))", len(self._devices))
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        for dev in self._devices:
            try:
                dev.close()
            except Exception:
                pass

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
        device_map = {dev.fd: dev for dev in self._devices}
        while self._running:
            try:
                readable, _, _ = select.select(device_map, [], [], 1.0)
                for fd in readable:
                    for event in device_map[fd].read():
                        if event.type == ecodes.EV_KEY:
                            key_event = categorize(event)
                            if key_event.keystate == key_event.key_down:
                                self._on_key(_normalize(key_event.keycode))
            except Exception as e:
                if self._running:
                    log.warning("Keyboard read error: %s", e)
