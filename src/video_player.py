import json
import logging
import os
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

_SOCKET_TEMPLATE = "/tmp/mpv-monitor-{monitor}.sock"
_BLANK_VIDEO = "/opt/video-reinforcer/blank.mp4"

# DRM connector names on Pi 5 — HDMI-A-1 is the first port (closest to USB-C power)
CONNECTORS = {
    1: "HDMI-A-1",
    2: "HDMI-A-2",
}

# ALSA audio devices matching each HDMI port (vc4hdmi0 = HDMI-A-1, vc4hdmi1 = HDMI-A-2)
AUDIO_DEVICES = {
    1: "alsa/plughw:CARD=vc4hdmi0,DEV=0",
    2: "alsa/plughw:CARD=vc4hdmi1,DEV=0",
}


class VideoPlayer:
    """Controls a persistent mpv process assigned to one HDMI output.

    Fires on_error(monitor, message) if mpv exits unexpectedly (e.g. monitor
    unplugged) or if a video fails to play (corrupt/unsupported file).
    """

    def __init__(self, monitor: int, on_error: Callable[[int, str], None]):
        self.monitor = monitor
        self._on_error = on_error
        self._socket_path = _SOCKET_TEMPLATE.format(monitor=monitor)
        self._process: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._send_lock = threading.Lock()
        self._loading = False  # True between loadfile command and playback-restart event

    def start(self):
        if os.path.exists(self._socket_path):
            os.remove(self._socket_path)

        connector = CONNECTORS.get(self.monitor, f"HDMI-A-{self.monitor}")
        audio_device = AUDIO_DEVICES.get(self.monitor)
        cmd = [
            "mpv",
            "--vo=drm",
            f"--drm-connector={connector}",
            "--loop-file=inf",
            "--fullscreen",
            "--no-terminal",
            "--really-quiet",
            "--idle=yes",
            "--pause",
            f"--input-ipc-server={self._socket_path}",
        ]
        if audio_device:
            cmd.append(f"--audio-device={audio_device}")
        self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._running = True

        # Wait up to 5 s for IPC socket to appear
        for _ in range(50):
            if os.path.exists(self._socket_path):
                break
            time.sleep(0.1)
        else:
            log.error("Monitor %d: mpv socket never appeared", self.monitor)
            self._running = False
            return

        self._connect()
        threading.Thread(target=self._reader, daemon=True, name=f"mpv-reader-{self.monitor}").start()
        threading.Thread(target=self._watchdog, daemon=True, name=f"mpv-watchdog-{self.monitor}").start()
        # Style OSD text used for error messages
        self._send(["set_property", "osd-font-size", 52])
        self._send(["set_property", "osd-color", "#D23C3C"])
        self._send(["set_property", "osd-border-color", "#000000"])
        self._send(["set_property", "osd-border-size", 2])
        log.info("Monitor %d player ready (connector=%s)", self.monitor, connector)

    def play(self, path: str):
        self._loading = True
        self._send(["loadfile", path, "replace"])
        self._send(["set_property", "pause", False])
        log.info("Monitor %d: playing %s", self.monitor, path)

    def stop(self):
        self._loading = False
        self._send(["loadfile", _BLANK_VIDEO, "replace"])
        self._send(["set_property", "pause", False])
        log.info("Monitor %d: stopped", self.monitor)

    def show_error_text(self, message: str):
        """Display error message via mpv OSD overlaid on a black background.

        Loads a pre-generated silent black video so mpv renders frames
        (OSD requires active rendering). {\\an5} centres the text on screen.
        """
        self._loading = False  # cancel any in-progress video load
        self._send(["loadfile", _BLANK_VIDEO, "replace"])
        self._send(["set_property", "pause", False])
        self._send(["show-text", message, 2147483647])
        log.info("Monitor %d: showing error", self.monitor)

    def clear_error_text(self):
        """Clear OSD error text and return to a blank screen."""
        self._send(["show-text", "", 1])
        self.stop()

    def shutdown(self):
        self._running = False
        self._loading = False
        self._close_socket()
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _watchdog(self):
        """Fires on_error if mpv exits without being told to."""
        if self._process:
            self._process.wait()
        if self._running:
            self._running = False
            log.error("Monitor %d: mpv exited unexpectedly (monitor disconnected?)", self.monitor)
            self._on_error(self.monitor, f"Monitor {self.monitor} lost.\nCheck the HDMI cable.")

    def _reader(self):
        """Reads JSON events from mpv IPC and detects playback failures."""
        buf = ""
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            self._handle_event(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except OSError:
                break

    def _handle_event(self, msg: dict):
        event = msg.get("event")
        if event == "end-file":
            reason = msg.get("reason", "")
            if reason == "error" and self._running and self._loading:
                self._loading = False
                log.error("Monitor %d: mpv reported end-file error", self.monitor)
                self._on_error(
                    self.monitor,
                    "Video could not be played.\nThe file may be corrupt or in an unsupported format."
                )
            else:
                self._loading = False
        elif event == "playback-restart":
            self._loading = False

    # ------------------------------------------------------------------
    # IPC helpers
    # ------------------------------------------------------------------

    def _connect(self):
        self._close_socket()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self._socket_path)
            self._sock = sock
        except Exception as e:
            log.error("Monitor %d: socket connect failed: %s", self.monitor, e)

    def _send(self, command: list):
        with self._send_lock:
            if not self._sock:
                return
            try:
                self._sock.sendall((json.dumps({"command": command}) + "\n").encode())
            except Exception as e:
                log.warning("Monitor %d: IPC send failed: %s", self.monitor, e)
                self._sock = None

    def _close_socket(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
