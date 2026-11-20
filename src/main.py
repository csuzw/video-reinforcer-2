import logging
import os
import signal
import sys
import threading
from typing import Dict, Optional

from .button_renderer import render_button, render_paging_key, render_screen_text
from .config_loader import AppConfig, ButtonConfig, ConfigError, DeckLayout, load_config
from .deck_manager import DeckManager
from .display_manager import DisplayManager
from .keyboard_reader import KeyboardReader
from .usb_monitor import USBMonitor

log = logging.getLogger(__name__)

_TRANSIENT_ERROR_DURATION = 4.0  # seconds before auto-clearing a transient error

# Keyboard keys that change page (when not used by a button in config.json)
_PREVIOUS_PAGE_KEYS = ("pageup",)
_NEXT_PAGE_KEYS = ("pagedown",)

# Exit status for a deliberate quit (quit button/key). install/vr-app restarts
# the app after any other non-zero exit (a crash), and stops on 0 (SIGTERM,
# e.g. the session ending at shutdown). Keep in sync with install/vr-app.
EXIT_QUIT = 10

_MSG_NO_USB = (
    "No USB stick detected.\n"
    "Please insert the USB stick\n"
    "with videos."
)


def _no_deck_message(config: AppConfig) -> str:
    """Explain why a Stream Deck is needed and how to avoid needing one."""
    if config.auto_buttons:
        return (
            "Stream Deck not connected.\n\n"
            "Connect a Stream Deck to choose videos."
        )
    actions = ", ".join(config.deck_only_actions())
    return (
        "Stream Deck not connected.\n\n"
        f"No keyboard key set for: {actions}\n\n"
        "Connect a Stream Deck, or add a \"key\"\n"
        "for these in config.json."
    )


class App:
    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._layout: DeckLayout = DeckLayout(pages=[])
        self._page = 0  # index into self._layout.pages
        self._playing: Optional[ButtonConfig] = None
        self._key_map: Dict[str, ButtonConfig] = {}

        # Hardware state — drives what is shown on screen
        self._usb_ok = False
        self._deck_connected = False
        self._transient_timer: Optional[threading.Timer] = None

        self._display = DisplayManager(on_player_error=self._on_player_error)
        self._deck = DeckManager(
            on_button_press=self._on_deck_press,
            on_connected=self._on_deck_connected,
            on_disconnected=self._on_deck_disconnected,
            on_page=self._change_page,
        )
        self._keyboard = KeyboardReader(on_key=self._on_key)
        self._usb = USBMonitor(
            on_mounted=self._on_usb_mounted,
            on_unmounted=self._on_usb_unmounted,
        )
        self._stop = threading.Event()
        self._exit_code = 0

    def run(self) -> int:
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
        return self._exit_code

    # ------------------------------------------------------------------
    # USB events
    # ------------------------------------------------------------------

    def _on_usb_mounted(self):
        log.info("USB mounted — loading config")
        try:
            config = load_config(self._usb.mount_point)
        except ConfigError as e:
            log.error("Config error: %s", e)
            self._forget_config()
            self._display.show_error(f"Configuration error:\n{e}\n\nCheck the USB stick.")
            self._deck.clear_all_keys()
            return

        self._config = config
        self._usb_ok = True
        self._playing = None
        self._key_map = config.key_map()
        self._page = 0
        self._cancel_transient_error()
        self._refresh_display()
        warnings = self._relayout()
        source = "folders" if config.auto_buttons else "config.json"
        log.info("Config loaded from %s — %d button(s)", source, len(config.all_buttons()))
        self._show_warnings(config.warnings + warnings)

    def _on_usb_unmounted(self):
        log.info("USB removed")
        self._cancel_transient_error()
        self._forget_config()
        self._display.show_error(_MSG_NO_USB)
        self._deck.clear_all_keys()

    def _forget_config(self):
        self._usb_ok = False
        self._config = None
        self._layout = DeckLayout(pages=[])
        self._page = 0
        self._playing = None
        self._key_map = {}

    # ------------------------------------------------------------------
    # Stream Deck events
    # ------------------------------------------------------------------

    def _on_deck_connected(self):
        log.info("Stream Deck reconnected")
        self._deck_connected = True
        self._refresh_display()
        warnings = self._relayout()
        if self._playing is None:
            self._show_warnings(warnings)

    def _on_deck_disconnected(self):
        log.info("Stream Deck disconnected")
        self._deck_connected = False
        if self._usb_ok and self._playing is None:
            if self._config and self._config.requires_deck():
                self._display.show_error(_no_deck_message(self._config))

    # ------------------------------------------------------------------
    # Player errors (monitor unplugged, video unplayable)
    # ------------------------------------------------------------------

    def _on_player_error(self, monitor: int, message: str):
        self._set_playing(None)
        self._cancel_transient_error()
        self._display.show_error(message)

    # ------------------------------------------------------------------
    # Button / keyboard input
    # ------------------------------------------------------------------

    def _on_deck_press(self, key: int):
        if not self._config:
            return
        if self._config.quit and self._config.quit.stream_deck_button == key:
            self._quit()
            return
        if key == self._layout.previous_key:
            self._change_page(-1)
            return
        if key == self._layout.next_key:
            self._change_page(1)
            return
        btn = self._current_page().get(key)
        if btn is not None:
            self._on_button_press(btn)

    def _on_key(self, key_name: str):
        if not self._config:
            return
        if self._config.quit and self._config.quit.key == key_name:
            self._quit()
            return
        btn = self._key_map.get(key_name)
        if btn is not None:
            self._on_button_press(btn)
        elif key_name in _PREVIOUS_PAGE_KEYS:
            self._change_page(-1)
        elif key_name in _NEXT_PAGE_KEYS:
            self._change_page(1)

    def _on_button_press(self, btn: ButtonConfig):
        if not self._config:
            return

        video_path = btn.video_path()

        if self._playing is btn:
            self._cancel_transient_error()
            self._display.stop()
            self._set_playing(None)
            log.info("Stopped %s", btn.video)
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
            # Video is already starting — redraw keys afterwards so the
            # border never delays playback.
            self._set_playing(btn)
            log.info("Playing %s on monitor %d", video_path, btn.monitor)

    def _set_playing(self, btn: Optional[ButtonConfig]):
        """Update the playing button and move the Stream Deck border to match."""
        old = self._playing
        self._playing = btn
        if old is btn:
            return
        size = self._deck.key_image_size()
        for key, page_btn in self._current_page().items():
            if page_btn is old or page_btn is btn:
                self._draw_button_key(key, page_btn, size)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _current_page(self) -> Dict[int, ButtonConfig]:
        pages = self._layout.pages
        return pages[self._page] if 0 <= self._page < len(pages) else {}

    def _change_page(self, delta: int):
        """Go to the previous (-1) or next (+1) page, wrapping round at the ends.
        Whatever is playing keeps playing."""
        count = len(self._layout.pages)
        if count <= 1:
            return
        self._page = (self._page + delta) % count
        log.info("Page %d of %d", self._page + 1, count)
        self._apply_deck_layout()

    def _relayout(self):
        """Fit the buttons to the connected deck. Returns any layout warnings."""
        if not self._config:
            return []
        self._layout = self._config.layout(
            self._deck.key_count() if self._deck_connected else 0,
            self._deck_connected and self._deck.has_hardware_paging(),
        )
        if self._page >= len(self._layout.pages):
            self._page = 0
        self._apply_deck_layout()
        for w in self._layout.warnings:
            log.warning("Layout: %s", w.replace("\n", " "))
        return list(self._layout.warnings)

    # ------------------------------------------------------------------
    # Display state
    # ------------------------------------------------------------------

    def _refresh_display(self):
        """Show the appropriate persistent message, or clear if everything is fine."""
        if not self._usb_ok:
            self._display.show_error(_MSG_NO_USB)
        elif not self._deck_connected and self._config and self._config.requires_deck():
            self._display.show_error(_no_deck_message(self._config))
        else:
            self._display.clear_error()

    # ------------------------------------------------------------------
    # Transient errors (auto-clear after a few seconds)
    # ------------------------------------------------------------------

    def _show_warnings(self, warnings):
        if warnings:
            self._show_transient_error("\n\n".join(warnings))

    def _show_transient_error(self, message: str):
        self._cancel_transient_error()
        self._set_playing(None)
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

        for key, btn in self._current_page().items():
            self._draw_button_key(key, btn, size)

        page, count = self._page + 1, self._layout.page_count()
        if self._layout.previous_key is not None:
            self._deck.set_key_image(self._layout.previous_key, render_paging_key(size, -1, page, count))
        if self._layout.next_key is not None:
            self._deck.set_key_image(self._layout.next_key, render_paging_key(size, 1, page, count))

        if self._deck.has_hardware_paging():
            self._deck.set_page_lights(count > 1)
            screen = self._deck.screen_size()
            if screen:
                text = f"Page {page} of {count}" if count > 1 else ""
                self._deck.set_screen_image(render_screen_text(screen, text))

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

    def _draw_button_key(self, key: int, btn: ButtonConfig, size):
        """Draw one video button's key, with a border if it is the one playing."""
        if not self._config:
            return
        img = render_button(
            size=size,
            style_type=btn.style.type,
            color=btn.style.color,
            image_path=btn.image_path(),
            label=btn.style.label,
            border_color=self._config.playing_border_color if btn is self._playing else None,
            badge=btn.style.badge,
        )
        self._deck.set_key_image(key, img)

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit(self):
        # The session script (install/vr-session) sees EXIT_QUIT and hands
        # the screen over to the desktop, or a login prompt if there is none.
        log.info("Quit requested — exiting")
        self._exit_code = EXIT_QUIT
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
    sys.exit(App().run())


if __name__ == "__main__":
    main()
