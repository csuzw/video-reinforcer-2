import glob
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from .video_player import CONNECTORS, VideoPlayer

log = logging.getLogger(__name__)


def _detect_connected_monitors() -> List[int]:
    """Return sorted list of monitor indices that have a display connected.

    Falls back to all defined monitors if sysfs is unavailable (e.g. on non-Pi hardware).
    """
    connected = []
    for monitor_idx, connector in CONNECTORS.items():
        if _is_monitor_connected(connector):
            connected.append(monitor_idx)

    if not connected:
        log.warning("Could not detect monitors via sysfs — assuming all connected")
        return sorted(CONNECTORS.keys())

    return sorted(connected)


def _is_monitor_connected(connector: str) -> bool:
    for path in glob.glob(f"/sys/class/drm/card*-{connector}/status"):
        try:
            if open(path).read().strip() == "connected":
                return True
        except Exception:
            pass
    return False


class DisplayManager:
    def __init__(self, on_player_error: Callable[[int, str], None]):
        self._on_player_error = on_player_error
        self._players: Dict[int, VideoPlayer] = {}
        self._lock = threading.Lock()
        self._playing_monitor: Optional[int] = None
        self._running = False

    def start(self):
        connected = _detect_connected_monitors()
        log.info("Connected monitors: %s", connected)

        with self._lock:
            self._players = {i: VideoPlayer(i, on_error=self._handle_player_error) for i in connected}
        for player in self._players.values():
            player.start()

        self._running = True
        threading.Thread(target=self._hotplug_watcher, daemon=True, name="hotplug-watcher").start()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self, monitor: int, path: str) -> bool:
        """Stop anything currently playing, start video on target monitor.

        Returns False if the monitor is not connected.
        """
        with self._lock:
            if monitor not in self._players:
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
        self._running = False
        self._stop_all_players()
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

    def _hotplug_watcher(self):
        """Poll sysfs every second for HDMI connect/disconnect events.

        Under the Wayland/labwc architecture mpv does not exit when a monitor
        is unplugged (the compositor moves its window), so we cannot rely on
        the VideoPlayer watchdog alone.  This thread detects the physical
        connector state and explicitly stops/starts players as needed.
        """
        known: Dict[int, bool] = {}
        with self._lock:
            for idx in CONNECTORS:
                known[idx] = idx in self._players

        while self._running:
            time.sleep(1)
            for monitor_idx, connector in list(CONNECTORS.items()):
                is_connected = _is_monitor_connected(connector)
                was_connected = known.get(monitor_idx, False)

                if was_connected and not is_connected:
                    known[monitor_idx] = False
                    log.info("Monitor %d disconnected", monitor_idx)
                    with self._lock:
                        player = self._players.pop(monitor_idx, None)
                        if self._playing_monitor == monitor_idx:
                            self._playing_monitor = None
                    if player:
                        player.shutdown()
                    self._on_player_error(
                        monitor_idx,
                        f"Monitor {monitor_idx} disconnected.\nCheck the HDMI cable.",
                    )

                elif not was_connected and is_connected:
                    known[monitor_idx] = True
                    log.info("Monitor %d connected", monitor_idx)
                    with self._lock:
                        already = monitor_idx in self._players
                    if not already:
                        # Brief pause lets labwc register the new output
                        # before the mpv window tries to move to it.
                        time.sleep(2)
                        player = VideoPlayer(monitor_idx, on_error=self._handle_player_error)
                        player.start()
                        with self._lock:
                            self._players[monitor_idx] = player

    def _stop_all_players(self):
        with self._lock:
            players = list(self._players.values())
        for player in players:
            player.stop()
        self._playing_monitor = None
