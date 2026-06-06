import logging
import os
import signal
import subprocess
import threading
from typing import Dict, Optional

from .button_renderer import render_button
from .config_loader import AppConfig, ConfigError, load_config
from .deck_manager import DeckManager
from .display_manager import DisplayManager
from .keyboard_reader import KeyboardReader
from .usb_monitor import USBMonitor

log = logging.getLogger(__name__)

USB_MOUNT = "/mnt/vr-usb"
_SYSTEMD_SERVICE = "video-reinforcer"
_TRANSIENT_ERROR_DURATION = 4.0  # seconds before auto-clearing a transient error

_MSG_NO_USB = (
    "No USB stick detected.\n"
    "Please insert the USB stick\n"
    "with videos and config.json."
)
_MSG_NO_DECK = (
    "Stream Deck disconnected.\n"
    "Please reconnect it.\n"
    "(Keyboard input is still active.)"
)


class App:
    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._playing_button: Optional[int] = None
        self._key_map: Dict[str, int] = {}

        # Hardware state — drives what is shown on screen
        self._usb_ok = False
        self._deck_connected = False
        self._transient_timer: Optional[threading.Timer] = None

        self._display = DisplayManager(on_player_error=self._on_player_error)
        self._deck = DeckManager(
            on_button_press=self._on_deck_press,
            on_connected=self._on_deck_connected,
            on_disconnected=self._on_deck_disconnected,
        )
        self._keyboard = KeyboardReader(on_key=self._on_key)
        self._usb = USBMonitor(
            on_mounted=self._on_usb_mounted,
            on_unmounted=self._on_usb_unmounted,
        )
        self._stop = threading.Event()

    def run(self):
        log.info("Video Reinforcer starting")
        self._display.start()
        self._display.show_error(_MSG_NO_USB)

        self._deck_connected = self._deck.connect()
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
            self._usb_ok = False
            self._config = None
            self._playing_button = None
            self._key_map = {}
            self._display.show_error(f"Configuration error:\n{e}\n\nCheck config.json on the USB stick.")
            self._deck.clear_all_keys()
            return

        self._config = config
        self._usb_ok = True
        self._playing_button = None
        self._key_map = config.key_map()
        self._cancel_transient_error()
        self._refresh_display()
        self._apply_deck_layout()
        log.info("Config loaded — %d button(s) configured", len(config.buttons))

    def _on_usb_unmounted(self):
        log.info("USB removed")
        self._cancel_transient_error()
        self._usb_ok = False
        self._config = None
        self._playing_button = None
        self._key_map = {}
        self._display.show_error(_MSG_NO_USB)
        self._deck.clear_all_keys()

    # ------------------------------------------------------------------
    # Stream Deck events
    # ------------------------------------------------------------------

    def _on_deck_connected(self):
        log.info("Stream Deck reconnected")
        self._deck_connected = True
        self._refresh_display()
        self._apply_deck_layout()

    def _on_deck_disconnected(self):
        log.info("Stream Deck disconnected")
        self._deck_connected = False
        # Only show the deck error if USB is OK (USB error takes priority)
        if self._usb_ok and self._playing_button is None:
            self._display.show_error(_MSG_NO_DECK)

    # ------------------------------------------------------------------
    # Player errors (monitor unplugged, video unplayable)
    # ------------------------------------------------------------------

    def _on_player_error(self, monitor: int, message: str):
        self._playing_button = None
        self._cancel_transient_error()
        self._display.show_error(message)

    # ------------------------------------------------------------------
    # Button / keyboard input
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
            self._cancel_transient_error()
            self._display.stop()
            self._playing_button = None
            log.info("Button %d: stopped", key)
            self._refresh_display()
        else:
            if not os.path.exists(video_path):
                log.error("Video not found: %s", video_path)
                self._show_transient_error(f"Video file not found:\n{btn.video}\n\nCheck the USB stick.")
                return
            if not self._display.play(btn.monitor, video_path):
                self._show_transient_error(
                    f"Monitor {btn.monitor} is not connected.\nCheck cables and config.json."
                )
                return
            self._cancel_transient_error()
            self._playing_button = key
            log.info("Button %d: playing %s on monitor %d", key, video_path, btn.monitor)

    # ------------------------------------------------------------------
    # Display state
    # ------------------------------------------------------------------

    def _refresh_display(self):
        """Show the appropriate persistent message, or clear if everything is fine."""
        if not self._usb_ok:
            self._display.show_error(_MSG_NO_USB)
        elif not self._deck_connected:
            self._display.show_error(_MSG_NO_DECK)
        else:
            self._display.clear_error()

    # ------------------------------------------------------------------
    # Transient errors (auto-clear after a few seconds)
    # ------------------------------------------------------------------

    def _show_transient_error(self, message: str):
        self._cancel_transient_error()
        self._playing_button = None
        self._display.show_error(message)
        self._transient_timer = threading.Timer(
            _TRANSIENT_ERROR_DURATION, self._clear_transient_error
        )
        self._transient_timer.daemon = True
        self._transient_timer.start()

    def _clear_transient_error(self):
        self._transient_timer = None
        # Restore the correct persistent state rather than unconditionally clearing
        self._refresh_display()

    def _cancel_transient_error(self):
        if self._transient_timer:
            self._transient_timer.cancel()
            self._transient_timer = None

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
    # Quit
    # ------------------------------------------------------------------

    def _quit(self):
        log.info("Quit requested — stopping service")
        result = subprocess.run(
            ["systemctl", "stop", _SYSTEMD_SERVICE],
            capture_output=True,
        )
        if result.returncode != 0:
            log.warning("systemctl stop failed — exiting directly")
            self._stop.set()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self):
        log.info("Shutting down")
        self._cancel_transient_error()
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
