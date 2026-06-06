import glob
import logging
import os
import tempfile
import threading
from typing import Callable, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from .video_player import CONNECTORS, VideoPlayer

log = logging.getLogger(__name__)

_ERROR_RESOLUTION = (1920, 1080)
_ERROR_BG = (20, 20, 20)
_ERROR_FG = (210, 60, 60)
_ERROR_FONT_SIZE = 42
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _detect_connected_monitors() -> List[int]:
    """Return sorted list of monitor indices that have a display connected.

    Falls back to all defined monitors if sysfs is unavailable (e.g. on non-Pi hardware).
    """
    connected = []
    for monitor_idx, connector in CONNECTORS.items():
        for path in glob.glob(f"/sys/class/drm/card*-{connector}/status"):
            try:
                if open(path).read().strip() == "connected":
                    connected.append(monitor_idx)
            except Exception:
                pass

    if not connected:
        log.warning("Could not detect monitors via sysfs — assuming all connected")
        return sorted(CONNECTORS.keys())

    return sorted(connected)


class DisplayManager:
    def __init__(self, on_player_error: Callable[[int, str], None]):
        self._on_player_error = on_player_error
        self._players: Dict[int, VideoPlayer] = {}
        self._lock = threading.Lock()
        self._playing_monitor: Optional[int] = None
        self._tmp_files: list[str] = []

    def start(self):
        connected = _detect_connected_monitors()
        log.info("Connected monitors: %s", connected)
        with self._lock:
            self._players = {i: VideoPlayer(i, on_error=self._handle_player_error) for i in connected}
        for player in self._players.values():
            player.start()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self, monitor: int, path: str) -> bool:
        """Stop anything currently playing, start video on target monitor.

        Returns False if the monitor is not connected. Attempts to dynamically
        start a player if the monitor was connected after startup.
        """
        with self._lock:
            if monitor not in self._players and not self._try_add_monitor_locked(monitor):
                log.warning("Monitor %d is not connected", monitor)
                return False
        self._stop_all_players()
        with self._lock:
            player = self._players.get(monitor)
        if player:
            self._playing_monitor = monitor
            player.play(path)
        return True

    def stop(self):
        self._stop_all_players()

    @property
    def playing_monitor(self) -> Optional[int]:
        return self._playing_monitor

    # ------------------------------------------------------------------
    # Error screens
    # ------------------------------------------------------------------

    def show_error(self, message: str):
        """Display an error message on all connected monitors."""
        self._stop_all_players()
        img_path = self._render_error_png(message)
        with self._lock:
            players = list(self._players.values())
        for player in players:
            player.play(img_path)

    def clear_error(self):
        """Remove error screens, return all monitors to blank."""
        self._stop_all_players()
        self._cleanup_tmp()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self._stop_all_players()
        self._cleanup_tmp()
        with self._lock:
            players = list(self._players.values())
            self._players.clear()
        for player in players:
            player.shutdown()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _handle_player_error(self, monitor: int, message: str):
        """Called by VideoPlayer when mpv exits unexpectedly or a video fails."""
        log.error("Player error on monitor %d: %s", monitor, message)
        with self._lock:
            self._players.pop(monitor, None)
            if self._playing_monitor == monitor:
                self._playing_monitor = None
        self._on_player_error(monitor, message)

    def _try_add_monitor_locked(self, monitor: int) -> bool:
        """Check sysfs and start a player if the monitor is now connected.

        Must be called with self._lock held.
        """
        connector = CONNECTORS.get(monitor)
        if not connector:
            return False
        for path in glob.glob(f"/sys/class/drm/card*-{connector}/status"):
            try:
                if open(path).read().strip() == "connected":
                    log.info("Monitor %d connected since startup — starting player", monitor)
                    player = VideoPlayer(monitor, on_error=self._handle_player_error)
                    player.start()
                    self._players[monitor] = player
                    return True
            except Exception:
                pass
        return False

    def _stop_all_players(self):
        with self._lock:
            players = list(self._players.values())
        for player in players:
            player.stop()
        self._playing_monitor = None

    def _render_error_png(self, message: str) -> str:
        img = Image.new("RGB", _ERROR_RESOLUTION, _ERROR_BG)
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype(_FONT_PATH, _ERROR_FONT_SIZE)
        except Exception:
            font = ImageFont.load_default()

        lines = message.split("\n")
        line_h = _ERROR_FONT_SIZE + 12
        total_h = len(lines) * line_h
        y = (_ERROR_RESOLUTION[1] - total_h) // 2

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
            x = (_ERROR_RESOLUTION[0] - w) // 2
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0), font=font)
            draw.text((x, y), line, fill=_ERROR_FG, font=font)
            y += line_h

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        img.save(tmp.name)
        self._tmp_files.append(tmp.name)
        return tmp.name

    def _cleanup_tmp(self):
        for path in self._tmp_files:
            try:
                os.unlink(path)
            except Exception:
                pass
        self._tmp_files.clear()
