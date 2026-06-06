import glob
import logging
import os
import tempfile
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from .video_player import VideoPlayer, CONNECTORS

log = logging.getLogger(__name__)

_ERROR_RESOLUTION = (1920, 1080)
_ERROR_BG = (20, 20, 20)
_ERROR_FG = (210, 60, 60)
_ERROR_FONT_SIZE = 42
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _detect_connected_monitors() -> List[int]:
    """Return sorted list of monitor indices (1, 2) that have a display connected.

    Reads DRM connector status from sysfs. Falls back to all monitors if the
    paths don't exist (e.g. running outside a Pi / before DRM initialises).
    """
    connected = []
    for monitor_idx, connector in CONNECTORS.items():
        pattern = f"/sys/class/drm/card*-{connector}/status"
        for path in glob.glob(pattern):
            try:
                status = open(path).read().strip()
                if status == "connected":
                    connected.append(monitor_idx)
            except Exception:
                pass

    if not connected:
        log.warning("Could not detect monitor connections via sysfs — assuming all connected")
        return sorted(CONNECTORS.keys())

    return sorted(connected)


class DisplayManager:
    def __init__(self):
        self._players: Dict[int, VideoPlayer] = {}
        self._playing_monitor: Optional[int] = None
        self._tmp_files: list[str] = []

    def start(self):
        connected = _detect_connected_monitors()
        log.info("Connected monitors: %s", connected)
        self._players = {i: VideoPlayer(i) for i in connected}
        for player in self._players.values():
            player.start()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self, monitor: int, path: str) -> bool:
        """Stop anything currently playing (any monitor), start video on target monitor.

        Returns False if the monitor is not connected (and no video is started).
        If the monitor was plugged in after startup, a player is started on demand.
        """
        if monitor not in self._players and not self._try_add_monitor(monitor):
            log.warning("Monitor %d is not connected", monitor)
            return False
        self._stop_all_players()
        self._playing_monitor = monitor
        self._players[monitor].play(path)
        return True

    def stop(self):
        """Stop the currently playing video and blank its monitor."""
        self._stop_all_players()

    @property
    def playing_monitor(self) -> Optional[int]:
        return self._playing_monitor

    # ------------------------------------------------------------------
    # Error screens
    # ------------------------------------------------------------------

    def show_error(self, message: str):
        """Display an error message on both monitors."""
        self._stop_all_players()
        img_path = self._render_error_png(message)
        for player in self._players.values():
            player.play(img_path)
        # _playing_monitor stays None — error is not a user-triggered video

    def clear_error(self):
        """Remove error screens and return both monitors to blank."""
        self._stop_all_players()
        self._cleanup_tmp()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self._stop_all_players()
        self._cleanup_tmp()
        for player in self._players.values():
            player.shutdown()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _try_add_monitor(self, monitor: int) -> bool:
        """Check whether a monitor has been connected since startup and, if so, start a player for it."""
        connector = CONNECTORS.get(monitor)
        if not connector:
            return False
        pattern = f"/sys/class/drm/card*-{connector}/status"
        for path in glob.glob(pattern):
            try:
                if open(path).read().strip() == "connected":
                    log.info("Monitor %d connected since startup — starting player", monitor)
                    player = VideoPlayer(monitor)
                    player.start()
                    self._players[monitor] = player
                    return True
            except Exception:
                pass
        return False

    def _stop_all_players(self):
        for player in self._players.values():
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
            # Drop shadow for legibility
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
