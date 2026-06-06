import glob
import logging
import os
import threading
from typing import Callable, Dict, List, Optional

from .video_player import CONNECTORS, VideoPlayer

log = logging.getLogger(__name__)


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
        self._drm_grantor_fd: Optional[int] = None

    def start(self):
        connected = _detect_connected_monitors()
        log.info("Connected monitors: %s", connected)

        lease_fds: Dict[int, int] = {}
        if len(connected) > 1:
            try:
                from .drm_lease import create_leases
                self._drm_grantor_fd, lease_fds = create_leases()
                log.info("DRM leases active for monitors %s", sorted(lease_fds))
            except Exception as exc:
                log.warning("DRM leases unavailable (%s) — only one monitor may render video", exc)

        with self._lock:
            self._players = {i: VideoPlayer(i, on_error=self._handle_player_error) for i in connected}
        for monitor, player in self._players.items():
            player.start(lease_fd=lease_fds.get(monitor))

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
        """Display an error message on all connected monitors via OSD."""
        self._playing_monitor = None
        with self._lock:
            players = list(self._players.values())
        for player in players:
            player.show_error_text(message)

    def clear_error(self):
        """Remove error screens, return all monitors to blank."""
        with self._lock:
            players = list(self._players.values())
        for player in players:
            player.clear_error_text()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        self._stop_all_players()
        with self._lock:
            players = list(self._players.values())
            self._players.clear()
        for player in players:
            player.shutdown()
        if self._drm_grantor_fd is not None:
            try:
                os.close(self._drm_grantor_fd)
            except OSError:
                pass
            self._drm_grantor_fd = None

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
