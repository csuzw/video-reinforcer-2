"""Tests for the App state machine — all hardware components are mocked."""
import pytest
from unittest.mock import MagicMock, patch, call

from src.config_loader import _parse
from src.main import EXIT_QUIT, App


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_TWO_BUTTON_CONFIG = {
    "buttons": {
        "0": {"video": "videos/v1.mp4", "monitor": 1, "key": "f1",
              "button": {"type": "color", "color": "#FF0000"}},
        "1": {"video": "videos/v2.mp4", "monitor": 2,
              "button": {"type": "color", "color": "#0000FF"}},
    }
}

_QUIT_CONFIG = {
    "quit": {"stream_deck_button": 5, "key": "f12"},
    "buttons": {
        "0": {"video": "videos/v1.mp4", "monitor": 1,
              "button": {"type": "color", "color": "#FF0000"}},
    }
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """App with all hardware mocked out, ready for state-machine testing."""
    with patch("src.main.DisplayManager") as MockDisplay, \
         patch("src.main.DeckManager") as MockDeck, \
         patch("src.main.KeyboardReader"), \
         patch("src.main.USBMonitor"):

        _app = App()
        _app._display = MockDisplay.return_value
        _app._deck = MockDeck.return_value
        _app._deck.key_image_size.return_value = (72, 72)
        _app._deck.key_count.return_value = 15  # a Stream Deck Classic
        _app._deck.has_hardware_paging.return_value = False
        _app._deck.screen_size.return_value = None
        # play() returns True (connected) by default
        _app._display.play.return_value = True
        yield _app


# ---------------------------------------------------------------------------
# USB mount / unmount
# ---------------------------------------------------------------------------

class TestUSBEvents:
    def test_valid_config_sets_usb_ok(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        assert app._usb_ok is True

    def test_valid_config_loads_buttons(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        assert app._config is not None
        assert len(app._config.buttons) == 2

    def test_valid_config_clears_error_screen(self, app):
        app._deck_connected = True  # deck already connected, so error screen should clear
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._display.clear_error.assert_called()

    def test_valid_config_applies_deck_layout(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._deck.clear_all_keys.assert_called()
        assert app._deck.set_key_image.call_count == 2

    def test_invalid_config_shows_error(self, app):
        from src.config_loader import ConfigError
        with patch("src.main.load_config", side_effect=ConfigError("bad")):
            app._on_usb_mounted()
        app._display.show_error.assert_called()
        assert app._usb_ok is False

    def test_invalid_config_clears_deck(self, app):
        from src.config_loader import ConfigError
        with patch("src.main.load_config", side_effect=ConfigError("bad")):
            app._on_usb_mounted()
        app._deck.clear_all_keys.assert_called()

    def test_usb_unmount_shows_error(self, app):
        app._on_usb_unmounted()
        app._display.show_error.assert_called()

    def test_usb_unmount_clears_config(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._on_usb_unmounted()
        assert app._config is None
        assert app._usb_ok is False

    def test_usb_unmount_clears_deck(self, app):
        app._on_usb_unmounted()
        app._deck.clear_all_keys.assert_called()

    def test_key_map_built_from_config(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        assert "f1" in app._key_map
        assert app._key_map["f1"] is app._config.buttons[0]


# ---------------------------------------------------------------------------
# Button press — playback logic
# ---------------------------------------------------------------------------

class TestButtonPress:
    def _load_config(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._display.reset_mock()
        app._deck.reset_mock()

    def test_press_with_no_config_ignored(self, app):
        app._on_deck_press(0)
        app._display.play.assert_not_called()

    def test_press_unconfigured_button_ignored(self, app):
        self._load_config(app)
        app._on_deck_press(99)
        app._display.play.assert_not_called()

    def test_press_plays_correct_video_on_correct_monitor(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        app._display.play.assert_called_once()
        args = app._display.play.call_args
        assert args[0][0] == 1  # monitor 1
        assert "v1.mp4" in args[0][1]

    def test_press_sets_playing(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        assert app._playing is app._config.buttons[0]

    def test_same_button_press_stops_video(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
            app._display.reset_mock()
            app._on_deck_press(0)
        app._display.stop.assert_called_once()
        assert app._playing is None

    def test_different_button_stops_current_and_starts_new(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
            app._display.reset_mock()
            app._on_deck_press(1)
        # play() is called (which internally stops all before starting new)
        app._display.play.assert_called_once()
        assert app._playing is app._config.buttons[1]

    def test_missing_video_shows_transient_error(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=False):
            app._on_deck_press(0)
        app._display.show_error.assert_called()
        assert app._playing is None

    def test_unconnected_monitor_shows_transient_error(self, app):
        self._load_config(app)
        app._display.play.return_value = False  # monitor not connected
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        app._display.show_error.assert_called()
        assert app._playing is None


# ---------------------------------------------------------------------------
# Playing-key border on the Stream Deck
# ---------------------------------------------------------------------------

class TestPlayingBorder:
    def _load_config(self, app, config=_TWO_BUTTON_CONFIG):
        with patch("src.main.load_config", return_value=_parse(config)):
            app._on_usb_mounted()

    def test_play_draws_border_on_playing_key(self, app):
        self._load_config(app)
        with patch("src.main.render_button") as render, \
             patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        assert render.call_count == 1
        assert render.call_args.kwargs["border_color"] == "#FF0000"
        assert app._deck.set_key_image.call_args[0][0] == 0

    def test_stop_removes_border(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
            with patch("src.main.render_button") as render:
                app._on_deck_press(0)
        assert render.call_args.kwargs["border_color"] is None

    def test_switching_moves_border(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
            app._deck.set_key_image.reset_mock()
            with patch("src.main.render_button") as render:
                render.side_effect = lambda **kw: kw.get("border_color")
                app._on_deck_press(1)
        drawn = {c[0][0]: c[0][1] for c in app._deck.set_key_image.call_args_list}
        assert drawn == {0: None, 1: "#FF0000"}

    def test_player_error_removes_border(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        with patch("src.main.render_button") as render:
            app._on_player_error(1, "Monitor 1 disconnected")
        assert render.call_args.kwargs["border_color"] is None

    def test_custom_border_color_used(self, app):
        config = dict(_TWO_BUTTON_CONFIG, playing_border_color="#00FF00")
        self._load_config(app, config)
        with patch("src.main.render_button") as render, \
             patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        assert render.call_args.kwargs["border_color"] == "#00FF00"

    def test_deck_reconnect_keeps_border_on_playing_key(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        with patch("src.main.render_button") as render:
            render.side_effect = lambda **kw: kw.get("border_color")
            app._deck.set_key_image.reset_mock()
            app._on_deck_connected()
        drawn = {c[0][0]: c[0][1] for c in app._deck.set_key_image.call_args_list}
        assert drawn[0] == "#FF0000"
        assert drawn[1] is None


# ---------------------------------------------------------------------------
# Keyboard input
# ---------------------------------------------------------------------------

class TestKeyboardInput:
    def _load_config(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._display.reset_mock()

    def test_mapped_key_triggers_button(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_key("f1")
        app._display.play.assert_called_once()

    def test_unmapped_key_ignored(self, app):
        self._load_config(app)
        app._on_key("f9")
        app._display.play.assert_not_called()

    def test_quit_key_calls_quit(self, app):
        with patch("src.main.load_config", return_value=_parse(_QUIT_CONFIG)):
            app._on_usb_mounted()
        with patch.object(app, "_quit") as mock_quit:
            app._on_key("f12")
        mock_quit.assert_called_once()


# ---------------------------------------------------------------------------
# Stream Deck connect / disconnect
# ---------------------------------------------------------------------------

class TestDeckEvents:
    def test_deck_disconnect_sets_flag(self, app):
        app._deck_connected = True
        app._on_deck_disconnected()
        assert app._deck_connected is False

    def test_deck_disconnect_shows_error_when_deck_required(self, app):
        """Deck error shown when config has a button with no keyboard key."""
        app._config = _parse(_TWO_BUTTON_CONFIG)  # button 1 has no key → requires deck
        app._usb_ok = True
        app._deck_connected = True
        app._playing = None

        app._on_deck_disconnected()

        app._display.show_error.assert_called()
        message = app._display.show_error.call_args[0][0]
        assert "button 1" in message
        assert "button 0" not in message

    def test_deck_disconnect_no_error_when_deck_not_required(self, app):
        """No error when every button and quit also has a keyboard key."""
        keyboard_only = {
            "buttons": {
                "0": {"video": "v1.mp4", "key": "1", "button": {"type": "color", "color": "#FF0000"}},
                "1": {"video": "v2.mp4", "key": "2", "button": {"type": "color", "color": "#0000FF"}},
            }
        }
        app._config = _parse(keyboard_only)
        app._usb_ok = True
        app._deck_connected = True
        app._playing = None

        app._on_deck_disconnected()

        app._display.show_error.assert_not_called()

    def test_deck_disconnect_during_playing_does_not_interrupt(self, app):
        """Critical: a video reward must not be interrupted by a deck disconnect."""
        app._usb_ok = True
        app._deck_connected = True
        app._playing = object()  # video is playing

        app._on_deck_disconnected()

        app._display.show_error.assert_not_called()

    def test_deck_reconnect_sets_flag(self, app):
        app._deck_connected = False
        app._on_deck_connected()
        assert app._deck_connected is True

    def test_deck_reconnect_relights_buttons(self, app):
        with patch("src.main.load_config", return_value=_parse(_TWO_BUTTON_CONFIG)):
            app._on_usb_mounted()
        app._deck.reset_mock()
        app._deck.key_image_size.return_value = (72, 72)

        app._on_deck_connected()

        app._deck.clear_all_keys.assert_called()
        assert app._deck.set_key_image.call_count == 2

    def test_deck_reconnect_clears_deck_error(self, app):
        app._usb_ok = True
        app._deck_connected = False

        app._on_deck_connected()

        app._display.clear_error.assert_called()


# ---------------------------------------------------------------------------
# Player errors (monitor unplug / video failure)
# ---------------------------------------------------------------------------

class TestPlayerErrors:
    def test_player_error_shows_error_on_screen(self, app):
        app._on_player_error(1, "Monitor 1 lost.\nCheck the HDMI cable.")
        app._display.show_error.assert_called_once_with("Monitor 1 lost.\nCheck the HDMI cable.")

    def test_player_error_clears_playing_button(self, app):
        app._playing = object()
        app._on_player_error(1, "error")
        assert app._playing is None


# ---------------------------------------------------------------------------
# Transient error state management
# ---------------------------------------------------------------------------

class TestTransientErrors:
    def test_transient_error_shown_on_screen(self, app):
        app._config = _parse(_TWO_BUTTON_CONFIG)
        app._usb_ok = True
        app._show_transient_error("Test error")
        app._display.show_error.assert_called_with("Test error")

    def test_transient_error_clears_to_ready_when_everything_ok(self, app):
        app._config = _parse(_TWO_BUTTON_CONFIG)
        app._usb_ok = True
        app._deck_connected = True
        app._show_transient_error("Test error")
        app._display.reset_mock()

        app._clear_transient_error()

        app._display.clear_error.assert_called()

    def test_transient_error_clears_to_usb_error_when_usb_missing(self, app):
        """If USB is removed while transient error is showing, clearing shows USB error."""
        app._config = None
        app._usb_ok = False
        app._show_transient_error("Test error")
        app._display.reset_mock()

        app._clear_transient_error()

        app._display.show_error.assert_called()
        app._display.clear_error.assert_not_called()

    def test_cancel_transient_error_cancels_timer(self, app):
        app._config = _parse(_TWO_BUTTON_CONFIG)
        app._show_transient_error("Test error")
        assert app._transient_timer is not None
        app._cancel_transient_error()
        assert app._transient_timer is None


# ---------------------------------------------------------------------------
# Quit
# ---------------------------------------------------------------------------

class TestQuit:
    def test_quit_sets_stop_event(self, app):
        app._quit()
        assert app._stop.is_set()

    def test_quit_exits_with_quit_status(self, app):
        """vr-app tells a deliberate quit (hand over to the desktop) from a crash by this."""
        app._quit()
        assert app._exit_code == EXIT_QUIT

    def test_exit_status_is_zero_unless_quit(self, app):
        assert app._exit_code == 0

    def test_quit_button_on_deck_triggers_quit(self, app):
        with patch("src.main.load_config", return_value=_parse(_QUIT_CONFIG)):
            app._on_usb_mounted()
        with patch.object(app, "_quit") as mock_quit:
            app._on_deck_press(5)
        mock_quit.assert_called_once()

    def test_non_quit_deck_button_does_not_quit(self, app):
        with patch("src.main.load_config", return_value=_parse(_QUIT_CONFIG)):
            app._on_usb_mounted()
        with patch.object(app, "_quit") as mock_quit, \
             patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(0)
        mock_quit.assert_not_called()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

_PAGED_CONFIG = {
    "pages": [
        {"0": {"video": "a.mp4", "monitor": 1, "key": "f1"}, "1": {"video": "b.mp4", "monitor": 2}},
        {"0": {"video": "c.mp4", "monitor": 1}, "1": {"video": "d.mp4", "monitor": 2}},
        {"0": {"video": "e.mp4", "monitor": 1}},
    ]
}


class TestPaging:
    def _load(self, app, config=_PAGED_CONFIG, key_count=15, neo=False):
        app._deck_connected = True
        app._deck.key_count.return_value = key_count
        app._deck.has_hardware_paging.return_value = neo
        with patch("src.main.load_config", return_value=_parse(config)):
            app._on_usb_mounted()
        app._display.reset_mock()

    def _play(self, app, deck_key):
        with patch("src.main.os.path.exists", return_value=True):
            app._on_deck_press(deck_key)

    def test_starts_on_first_page(self, app):
        self._load(app)
        self._play(app, 0)
        assert app._display.play.call_args[0][1].endswith("a.mp4")

    def test_next_key_shows_next_page(self, app):
        self._load(app)
        app._on_deck_press(14)  # default next key on a 15-key deck
        self._play(app, 0)
        assert app._display.play.call_args[0][1].endswith("c.mp4")

    def test_previous_from_first_page_wraps_to_last(self, app):
        self._load(app)
        app._on_deck_press(13)
        assert app._page == 2

    def test_next_from_last_page_wraps_to_first(self, app):
        self._load(app)
        for _ in range(3):
            app._on_deck_press(14)
        assert app._page == 0

    def test_paging_keys_drawn(self, app):
        app._deck_connected = True
        with patch("src.main.render_paging_key") as render:
            self._load(app)
        drawn = {c[0][0] for c in app._deck.set_key_image.call_args_list}
        assert {13, 14} <= drawn
        assert render.call_count == 2

    def test_page_change_does_not_stop_video(self, app):
        self._load(app)
        self._play(app, 0)
        app._on_deck_press(14)
        app._display.stop.assert_not_called()
        assert app._playing is app._config.pages[0][0]

    def test_border_only_drawn_on_playing_page(self, app):
        self._load(app)
        self._play(app, 0)
        with patch("src.main.render_button") as render:
            render.side_effect = lambda **kw: kw.get("border_color")
            app._on_deck_press(14)
        borders = [c.kwargs["border_color"] for c in render.call_args_list]
        assert "#FF0000" not in borders

    def test_same_key_on_another_page_switches_video(self, app):
        self._load(app)
        self._play(app, 0)
        app._on_deck_press(14)
        self._play(app, 0)
        app._display.stop.assert_not_called()  # switched, not toggled off
        assert app._playing is app._config.pages[1][0]

    def test_keyboard_key_works_from_any_page(self, app):
        self._load(app)
        app._on_deck_press(14)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_key("f1")
        assert app._display.play.call_args[0][1].endswith("a.mp4")

    def test_page_down_key_changes_page(self, app):
        self._load(app)
        app._on_key("pagedown")
        assert app._page == 1
        app._on_key("pageup")
        assert app._page == 0

    def test_neo_touch_buttons_change_page(self, app):
        self._load(app, key_count=8, neo=True)
        app._change_page(1)  # what DeckManager calls for the right touch button
        assert app._page == 1
        app._deck.set_page_lights.assert_called_with(True)

    def test_neo_has_no_on_screen_paging_keys(self, app):
        self._load(app, key_count=8, neo=True)
        assert app._layout.previous_key is None
        app._on_deck_press(7)  # an ordinary key, not paging
        assert app._page == 0

    def test_single_page_ignores_paging(self, app):
        self._load(app, config=_TWO_BUTTON_CONFIG)
        app._on_key("pagedown")
        assert app._page == 0

    def test_deck_reconnect_keeps_page(self, app):
        self._load(app)
        app._on_deck_press(14)
        app._on_deck_connected()
        assert app._page == 1

    def test_smaller_deck_resets_page_if_gone(self, app, tmp_path):
        for i in range(20):
            f = tmp_path / "Monitor 1" / "Videos" / f"{i:02d}.mp4"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"")
        from src.config_loader import load_config
        config = load_config(str(tmp_path))
        app._deck_connected = True
        app._deck.key_count.return_value = 6  # Mini: 4 per page → 5 pages
        with patch("src.main.load_config", return_value=config):
            app._on_usb_mounted()
        assert len(app._layout.pages) == 5
        app._page = 4
        app._deck.key_count.return_value = 32  # XL: 1 page
        app._on_deck_connected()
        assert app._page == 0
        assert len(app._layout.pages) == 1


class TestLayoutWarnings:
    def test_layout_warning_shown_briefly(self, app):
        app._deck_connected = True
        config = {"buttons": {"0": {"video": "a.mp4"}, "20": {"video": "b.mp4"}}}
        with patch("src.main.load_config", return_value=_parse(config)):
            app._on_usb_mounted()
        message = app._display.show_error.call_args[0][0]
        assert "15 keys" in message
        assert app._transient_timer is not None
        app._cancel_transient_error()

    def test_folder_mode_no_deck_message(self, app, tmp_path):
        f = tmp_path / "Monitor 1" / "Videos" / "a.mp4"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"")
        from src.config_loader import load_config
        with patch("src.main.load_config", return_value=load_config(str(tmp_path))):
            app._on_usb_mounted()
        message = app._display.show_error.call_args[0][0]
        assert "Connect a Stream Deck" in message
        assert "config.json" not in message
