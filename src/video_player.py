import json
import logging
import os
import socket
import subprocess
import time
from typing import Optional

log = logging.getLogger(__name__)

_SOCKET_TEMPLATE = "/tmp/mpv-monitor-{monitor}.sock"

# DRM connector names on Pi 5 — HDMI-A-1 is the first port (closest to USB-C power)
_CONNECTORS = {
    1: "HDMI-A-1",
    2: "HDMI-A-2",
}


class VideoPlayer:
    """Controls a single persistent mpv process assigned to one HDMI output."""

    def __init__(self, monitor: int):
        self.monitor = monitor
        self._socket_path = _SOCKET_TEMPLATE.format(monitor=monitor)
        self._process: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None

    def start(self):
        if os.path.exists(self._socket_path):
            os.remove(self._socket_path)

        connector = _CONNECTORS.get(self.monitor, f"HDMI-A-{self.monitor}")
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
        self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait up to 5 s for the IPC socket to appear
        for _ in range(50):
            if os.path.exists(self._socket_path):
                break
            time.sleep(0.1)
        else:
            log.error("Monitor %d: mpv socket never appeared", self.monitor)
            return

        self._connect()
        log.info("Monitor %d player ready (connector=%s)", self.monitor, connector)

    def play(self, path: str):
        self._send(["loadfile", path, "replace"])
        self._send(["set_property", "pause", False])
        log.info("Monitor %d: playing %s", self.monitor, path)

    def stop(self):
        self._send(["stop"])
        log.info("Monitor %d: stopped", self.monitor)

    def shutdown(self):
        self._close_socket()
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()

    # ------------------------------------------------------------------
    # IPC helpers
    # ------------------------------------------------------------------

    def _connect(self):
        self._close_socket()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self._socket_path)
            sock.settimeout(2.0)
            self._sock = sock
        except Exception as e:
            log.error("Monitor %d: socket connect failed: %s", self.monitor, e)

    def _send(self, command: list):
        if self._sock is None:
            self._connect()
        if self._sock is None:
            return
        try:
            msg = json.dumps({"command": command}) + "\n"
            self._sock.sendall(msg.encode())
        except Exception as e:
            log.warning("Monitor %d: IPC send failed (%s), reconnecting", self.monitor, e)
            self._sock = None

    def _close_socket(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
