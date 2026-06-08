import logging
import threading
import time
from typing import Callable, Optional, Tuple

import pyudev
from PIL import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper

log = logging.getLogger(__name__)

_STREAMDECK_VENDOR_ID = "0fd9"
_RECONNECT_ATTEMPTS = 5
_RECONNECT_DELAY = 1.0  # seconds between reconnect attempts


class DeckManager:
    def __init__(
        self,
        on_button_press: Callable[[int], None],
        on_connected: Callable[[], None],
        on_disconnected: Callable[[], None],
    ):
        self._on_press = on_button_press
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._deck: Optional[StreamDeck] = None
        self._key_count = 0
        self._lock = threading.Lock()
        self._usb_observer: Optional[pyudev.MonitorObserver] = None

    def connect(self) -> bool:
        """Attempt initial connection. Returns True if a deck is found."""
        result = self._open_deck()
        self._start_usb_watch()
        return result

    def key_count(self) -> int:
        return self._key_count

    def key_image_size(self) -> Tuple[int, int]:
        with self._lock:
            if not self._deck:
                return (72, 72)
            fmt = self._deck.key_image_format()
            return (fmt["size"][0], fmt["size"][1])

    def set_key_image(self, key: int, image: Image.Image):
        with self._lock:
            if not self._deck or key >= self._key_count:
                return
            try:
                fmt = self._deck.key_image_format()
                size = (fmt["size"][0], fmt["size"][1])
                native = PILHelper.to_native_format(
                    self._deck,
                    image.convert("RGB").resize(size, Image.LANCZOS),
                )
                self._deck.set_key_image(key, native)
            except Exception as e:
                log.warning("set_key_image failed: %s", e)

    def clear_all_keys(self):
        with self._lock:
            if not self._deck:
                return
            size = (self._deck.key_image_format()["size"][0], self._deck.key_image_format()["size"][1])
            blank = PILHelper.to_native_format(self._deck, Image.new("RGB", size, (0, 0, 0)))
            try:
                for i in range(self._key_count):
                    self._deck.set_key_image(i, blank)
            except Exception as e:
                log.warning("clear_all_keys failed: %s", e)

    def shutdown(self):
        if self._usb_observer:
            self._usb_observer.stop()
        with self._lock:
            if self._deck:
                try:
                    self._deck.reset()
                    self._deck.close()
                except Exception:
                    pass
                self._deck = None

    # ------------------------------------------------------------------
    # USB hotplug
    # ------------------------------------------------------------------

    def _start_usb_watch(self):
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="usb")
        self._usb_observer = pyudev.MonitorObserver(monitor, callback=self._handle_usb_event)
        self._usb_observer.start()
        log.debug("Stream Deck USB watcher started")

    def _handle_usb_event(self, device):
        action = device.action
        vendor = device.get("ID_VENDOR_ID", "").lower()
        if vendor != _STREAMDECK_VENDOR_ID:
            return

        if action == "remove":
            with self._lock:
                if self._deck is None:
                    return
                try:
                    self._deck.close()
                except Exception:
                    pass
                self._deck = None
                self._key_count = 0
            log.warning("Stream Deck disconnected")
            self._on_disconnected()

        elif action == "add":
            # Run reconnect in a thread so the udev callback returns promptly
            threading.Thread(target=self._reconnect, daemon=True).start()

    def _reconnect(self):
        time.sleep(1.5)  # give the device time to fully initialise
        for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
            with self._lock:
                if self._deck is not None:
                    return  # already connected
            if self._open_deck():
                self._on_connected()
                return
            log.warning("Stream Deck reconnect attempt %d/%d failed", attempt, _RECONNECT_ATTEMPTS)
            time.sleep(_RECONNECT_DELAY)
        log.error("Could not reconnect Stream Deck after %d attempts", _RECONNECT_ATTEMPTS)

    # ------------------------------------------------------------------
    # Device open / close
    # ------------------------------------------------------------------

    def _open_deck(self) -> bool:
        devices = DeviceManager().enumerate()
        if not devices:
            log.warning("No Stream Deck found")
            return False
        try:
            deck = devices[0]
            deck.open()
            deck.reset()
            with self._lock:
                self._deck = deck
                self._key_count = deck.key_count()
            deck.set_brightness(80)
            deck.set_key_callback(self._key_callback)
            log.info("Stream Deck connected: %s, %d keys", deck.deck_type(), deck.key_count())
            return True
        except Exception as e:
            log.error("Failed to open Stream Deck: %s", e)
            return False

    def _key_callback(self, deck, key: int, pressed: bool):
        if pressed:
            self._on_press(key)
