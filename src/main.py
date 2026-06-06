import logging
import os
import signal
import subprocess
import threading
from typing import Dict, Optional

from .button_renderer import render_blank, render_button
from .config_loader import AppConfig, ConfigError, QuitConfig, load_config
from .deck_manager import DeckManager
from .display_manager import DisplayManager
from .keyboard_reader import KeyboardReader
from .usb_monitor import USBMonitor

log = logging.getLogger(__name__)

USB_MOUNT = "/mnt/vr-usb"

_NO_USB_MSG = "No USB stick detected.\nPlease insert the USB stick\nwith videos and config.json."
_BAD_CONFIG_MSG = "Configuration error:\n{detail}\n\nCheck config.json on the USB stick."
_SYSTEMD_SERVICE = "video-reinforcer"


class App:
    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._playing_button: Optional[int] = None
        self._key_map: Dict[str, int] = {}  # keyboard key → button index

        self._display = DisplayManager()
        self._deck = DeckManager(on_button_press=self._on_deck_press)
        self._keyboard = KeyboardReader(on_key=self._on_key)
        self._usb = USBMonitor(
            on_mounted=self._on_usb_mounted,
            on_unmounted=self._on_usb_unmounted,
        )
        self._stop = threading.Event()

    def run(self):
        log.info("Video Reinforcer starting")
        self._display.start()
        self._display.show_error(_NO_USB_MSG)

        if not self._deck.connect():
            log.warning("No Stream Deck found — continuing without it")

        self._keyboard.start()
        self._usb.start()

        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        signal.signal(signal.SIGINT, lambda *_: self._stop.set())

        self._stop.wait()
        self._shutdown()

    # ------------------------------------------------------------------
    # USB events
    # ------------------------------------------------------------------

    def _on_usb_mounted(self):
        log.info("USB mounted — loading config")
        try:
            config = load_config()
        except ConfigError as e:
            log.error("Config error: %s", e)
            self._config = None
            self._playing_button = None
            self._key_map = {}
            self._display.show_error(_BAD_CONFIG_MSG.format(detail=str(e)))
            self._deck.clear_all_keys()
            return

        self._config = config
        self._playing_button = None
        self._key_map = config.key_map()
        self._display.clear_error()
        self._apply_deck_layout()
        log.info("Config loaded — %d button(s) configured", len(config.buttons))

    def _on_usb_unmounted(self):
        log.info("USB removed")
        self._config = None
        self._playing_button = None
        self._key_map = {}
        self._display.show_error(_NO_USB_MSG)
        self._deck.clear_all_keys()

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------

    def _on_deck_press(self, key: int):
        if self._config and self._config.quit and self._config.quit.stream_deck_button == key:
            self._quit()
            return
        self._on_button_press(key)

    def _on_key(self, key_name: str):
        if self._config and self._config.quit and self._config.quit.key == key_name:
            self._quit()
            return
        button_index = self._key_map.get(key_name)
        if button_index is not None:
            self._on_button_press(button_index)

    def _on_button_press(self, key: int):
        if not self._config:
            return

        btn = self._config.buttons.get(key)
        if btn is None:
            return

        video_path = btn.video_path()

        if self._playing_button == key:
            self._display.stop()
            self._playing_button = None
            log.info("Button %d: stopped", key)
        else:
            if not os.path.exists(video_path):
                log.error("Video not found: %s", video_path)
                return
            self._display.play(btn.monitor, video_path)
            self._playing_button = key
            log.info("Button %d: playing %s on monitor %d", key, video_path, btn.monitor)

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit(self):
        log.info("Quit requested — stopping service")
        # Ask systemd to stop the service; systemd-stopped services don't auto-restart.
        # If not running under systemd, fall back to a clean exit (systemd will restart it).
        result = subprocess.run(
            ["systemctl", "stop", _SYSTEMD_SERVICE],
            capture_output=True,
        )
        if result.returncode != 0:
            log.warning("systemctl stop failed (not running under systemd?) — exiting directly")
            self._stop.set()

    # ------------------------------------------------------------------
    # Deck layout
    # ------------------------------------------------------------------

    def _apply_deck_layout(self):
        if not self._config:
            return

        size = self._deck.key_image_size()
        self._deck.clear_all_keys()

        for idx, btn in self._config.buttons.items():
            img = render_button(
                size=size,
                style_type=btn.style.type,
                color=btn.style.color,
                image_path=btn.image_path(),
                label=btn.style.label,
            )
            self._deck.set_key_image(idx, img)

        # Render quit button on Stream Deck if configured
        quit_cfg = self._config.quit
        if quit_cfg and quit_cfg.stream_deck_button is not None:
            img = render_button(
                size=size,
                style_type=quit_cfg.style.type,
                color=quit_cfg.style.color,
                image_path=None,
                label=quit_cfg.style.label,
            )
            self._deck.set_key_image(quit_cfg.stream_deck_button, img)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self):
        log.info("Shutting down")
        self._keyboard.stop()
        self._usb.stop()
        self._display.shutdown()
        self._deck.shutdown()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    App().run()


if __name__ == "__main__":
    main()
