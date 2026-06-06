import logging
import threading
from typing import Callable, Optional, Tuple

from PIL import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper

log = logging.getLogger(__name__)


class DeckManager:
    def __init__(self, on_button_press: Callable[[int], None]):
        self._on_press = on_button_press
        self._deck: Optional[StreamDeck] = None
        self._key_count = 0
        self._lock = threading.Lock()

    def connect(self) -> bool:
        devices = DeviceManager().enumerate()
        if not devices:
            log.warning("No Stream Deck found")
            return False

        self._deck = devices[0]
        self._deck.open()
        self._deck.reset()
        self._key_count = self._deck.key_count()
        self._deck.set_brightness(80)
        self._deck.set_key_callback(self._key_callback)

        log.info("Stream Deck connected: %s, %d keys", self._deck.deck_type(), self._key_count)
        return True

    def key_count(self) -> int:
        return self._key_count

    def key_image_size(self) -> Tuple[int, int]:
        if not self._deck:
            return (72, 72)
        fmt = self._deck.key_image_format()
        return (fmt["size"][0], fmt["size"][1])

    def set_key_image(self, key: int, image: Image.Image):
        if not self._deck or key >= self._key_count:
            return
        native = PILHelper.to_native_format(self._deck, image.convert("RGB").resize(
            self.key_image_size(), Image.LANCZOS
        ))
        with self._lock:
            self._deck.set_key_image(key, native)

    def clear_all_keys(self):
        if not self._deck:
            return
        blank = Image.new("RGB", self.key_image_size(), (0, 0, 0))
        native = PILHelper.to_native_format(self._deck, blank)
        with self._lock:
            for i in range(self._key_count):
                self._deck.set_key_image(i, native)

    def shutdown(self):
        if self._deck:
            try:
                self._deck.reset()
                self._deck.close()
            except Exception:
                pass

    def _key_callback(self, deck, key: int, pressed: bool):
        if pressed:
            self._on_press(key)
