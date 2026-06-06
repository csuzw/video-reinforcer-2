"""Tests for DisplayManager logic — VideoPlayer is mocked, no mpv required."""
from unittest.mock import MagicMock, patch, call
import pytest

from src.display_manager import DisplayManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dm(on_error=None):
    """Return a DisplayManager with no real players started."""
    with patch("src.display_manager._detect_connected_monitors", return_value=[]):
        dm = DisplayManager(on_player_error=on_error or MagicMock())
        dm.start()
    return dm


def _add_player(dm, monitor):
    """Insert a mock VideoPlayer for the given monitor index."""
    p = MagicMock()
    p.monitor = monitor
    dm._players[monitor] = p
    return p


# ---------------------------------------------------------------------------
# start() — monitor detection
# ---------------------------------------------------------------------------

class TestStart:
    def test_creates_players_for_detected_monitors(self):
        with patch("src.display_manager._detect_connected_monitors", return_value=[1, 2]), \
             patch("src.display_manager.VideoPlayer") as MockVP:
            dm = DisplayManager(on_player_error=MagicMock())
            dm.start()
        assert MockVP.call_count == 2

    def test_creates_player_for_single_monitor(self):
        with patch("src.display_manager._detect_connected_monitors", return_value=[1]), \
             patch("src.display_manager.VideoPlayer") as MockVP:
            dm = DisplayManager(on_player_error=MagicMock())
            dm.start()
        assert MockVP.call_count == 1

    def test_no_players_when_no_monitors(self):
        dm = _make_dm()
        assert len(dm._players) == 0


# ---------------------------------------------------------------------------
# play()
# ---------------------------------------------------------------------------

class TestPlay:
    def test_returns_true_for_connected_monitor(self):
        dm = _make_dm()
        _add_player(dm, 1)
        assert dm.play(1, "/path/to/video.mp4") is True

    def test_returns_false_for_unconnected_monitor(self):
        dm = _make_dm()
        with patch("src.display_manager.glob.glob", return_value=[]):
            result = dm.play(2, "/path/to/video.mp4")
        assert result is False

    def test_calls_play_on_correct_player(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        _add_player(dm, 2)
        dm.play(1, "/video.mp4")
        p1.play.assert_called_once_with("/video.mp4")

    def test_stops_all_players_before_playing(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        p2 = _add_player(dm, 2)
        dm.play(1, "/video.mp4")
        p1.stop.assert_called_once()
        p2.stop.assert_called_once()

    def test_only_one_monitor_plays_at_a_time(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        p2 = _add_player(dm, 2)

        dm.play(1, "/v1.mp4")
        dm.play(2, "/v2.mp4")

        # After switching to monitor 2, monitor 1 should have been stopped
        assert p1.stop.call_count == 2  # once when 1 started, once when 2 started
        p2.play.assert_called_once_with("/v2.mp4")

    def test_sets_playing_monitor(self):
        dm = _make_dm()
        _add_player(dm, 1)
        dm.play(1, "/video.mp4")
        assert dm.playing_monitor == 1

    def test_play_on_different_monitor_updates_playing_monitor(self):
        dm = _make_dm()
        _add_player(dm, 1)
        _add_player(dm, 2)
        dm.play(1, "/v1.mp4")
        dm.play(2, "/v2.mp4")
        assert dm.playing_monitor == 2

    def test_unconnected_monitor_does_not_change_playing_monitor(self):
        dm = _make_dm()
        _add_player(dm, 1)
        dm.play(1, "/v1.mp4")
        with patch("src.display_manager.glob.glob", return_value=[]):
            dm.play(2, "/v2.mp4")
        assert dm.playing_monitor == 1  # unchanged


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

class TestStop:
    def test_stops_all_players(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        p2 = _add_player(dm, 2)
        dm.stop()
        p1.stop.assert_called_once()
        p2.stop.assert_called_once()

    def test_clears_playing_monitor(self):
        dm = _make_dm()
        _add_player(dm, 1)
        dm.play(1, "/video.mp4")
        dm.stop()
        assert dm.playing_monitor is None


# ---------------------------------------------------------------------------
# show_error() / clear_error()
# ---------------------------------------------------------------------------

class TestErrorDisplay:
    def test_show_error_plays_on_all_connected_monitors(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        p2 = _add_player(dm, 2)
        with patch("src.display_manager.DisplayManager._render_error_video", return_value="/tmp/err.png"):
            dm.show_error("Something went wrong")
        p1.play.assert_called_once_with("/tmp/err.png")
        p2.play.assert_called_once_with("/tmp/err.png")

    def test_show_error_stops_current_video_first(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        dm.play(1, "/video.mp4")
        p1.stop.reset_mock()
        with patch("src.display_manager.DisplayManager._render_error_video", return_value="/tmp/err.png"):
            dm.show_error("Error")
        p1.stop.assert_called_once()

    def test_show_error_on_single_monitor(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        with patch("src.display_manager.DisplayManager._render_error_video", return_value="/tmp/err.png"):
            dm.show_error("Monitor 2 missing")
        p1.play.assert_called_once()

    def test_clear_error_stops_all_players(self):
        dm = _make_dm()
        p1 = _add_player(dm, 1)
        p2 = _add_player(dm, 2)
        dm.clear_error()
        p1.stop.assert_called_once()
        p2.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Player error handling (monitor unplug / video failure)
# ---------------------------------------------------------------------------

class TestPlayerError:
    def test_player_error_removes_player_from_dict(self):
        on_error = MagicMock()
        dm = _make_dm(on_error=on_error)
        _add_player(dm, 1)
        _add_player(dm, 2)

        dm._handle_player_error(1, "Monitor 1 lost")

        assert 1 not in dm._players
        assert 2 in dm._players

    def test_player_error_clears_playing_monitor(self):
        on_error = MagicMock()
        dm = _make_dm(on_error=on_error)
        _add_player(dm, 1)
        dm.play(1, "/video.mp4")

        dm._handle_player_error(1, "Monitor 1 lost")

        assert dm.playing_monitor is None

    def test_player_error_notifies_callback(self):
        on_error = MagicMock()
        dm = _make_dm(on_error=on_error)
        _add_player(dm, 1)

        dm._handle_player_error(1, "Monitor 1 lost")

        on_error.assert_called_once_with(1, "Monitor 1 lost")

    def test_player_error_on_non_playing_monitor_does_not_clear_playing(self):
        on_error = MagicMock()
        dm = _make_dm(on_error=on_error)
        _add_player(dm, 1)
        _add_player(dm, 2)
        dm.play(1, "/video.mp4")

        dm._handle_player_error(2, "Monitor 2 lost")  # monitor 2 errored, but 1 was playing

        assert dm.playing_monitor == 1
