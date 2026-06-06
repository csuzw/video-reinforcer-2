"""Tests for the App state machine — all hardware components are mocked."""
import pytest
from unittest.mock import MagicMock, patch, call

from src.config_loader import _parse
from src.main import App


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
        assert app._key_map["f1"] == 0


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
        app._on_button_press(0)
        app._display.play.assert_not_called()

    def test_press_unconfigured_button_ignored(self, app):
        self._load_config(app)
        app._on_button_press(99)
        app._display.play.assert_not_called()

    def test_press_plays_correct_video_on_correct_monitor(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_button_press(0)
        app._display.play.assert_called_once()
        args = app._display.play.call_args
        assert args[0][0] == 1  # monitor 1
        assert "v1.mp4" in args[0][1]

    def test_press_sets_playing_button(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_button_press(0)
        assert app._playing_button == 0

    def test_same_button_press_stops_video(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_button_press(0)
            app._display.reset_mock()
            app._on_button_press(0)
        app._display.stop.assert_called_once()
        assert app._playing_button is None

    def test_different_button_stops_current_and_starts_new(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=True):
            app._on_button_press(0)
            app._display.reset_mock()
            app._on_button_press(1)
        # play() is called (which internally stops all before starting new)
        app._display.play.assert_called_once()
        assert app._playing_button == 1

    def test_missing_video_shows_transient_error(self, app):
        self._load_config(app)
        with patch("src.main.os.path.exists", return_value=False):
            app._on_button_press(0)
        app._display.show_error.assert_called()
        assert app._playing_button is None

    def test_unconnected_monitor_shows_transient_error(self, app):
        self._load_config(app)
        app._display.play.return_value = False  # monitor not connected
        with patch("src.main.os.path.exists", return_value=True):
            app._on_button_press(0)
        app._display.show_error.assert_called()
        assert app._playing_button is None


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
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            app._on_key("f12")
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Stream Deck connect / disconnect
# ---------------------------------------------------------------------------

class TestDeckEvents:
    def test_deck_disconnect_sets_flag(self, app):
        app._deck_connected = True
        app._on_deck_disconnected()
        assert app._deck_connected is False

    def test_deck_disconnect_shows_error_when_idle(self, app):
        app._usb_ok = True
        app._deck_connected = True
        app._playing_button = None

        app._on_deck_disconnected()

        app._display.show_error.assert_called()

    def test_deck_disconnect_during_playing_does_not_interrupt(self, app):
        """Critical: a video reward must not be interrupted by a deck disconnect."""
        app._usb_ok = True
        app._deck_connected = True
        app._playing_button = 0  # video is playing

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
        app._playing_button = 0
        app._on_player_error(1, "error")
        assert app._playing_button is None


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
    def test_quit_calls_systemctl_stop(self, app):
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            app._quit()
        mock_run.assert_called_once()
        assert "stop" in mock_run.call_args[0][0]

    def test_quit_falls_back_to_stop_event_if_systemctl_fails(self, app):
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            app._quit()
        assert app._stop.is_set()

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
