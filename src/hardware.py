"""Hardware detection: which display output and audio device each monitor uses.

Everything is auto-detected from sysfs/procfs, so the same code runs on a
Pi 4, a Pi 5 or a generic Linux PC. Any value can be overridden with a plain
KEY=VALUE file (see CONFIG_PATHS). The first location is on the SD card's
boot partition, which can be edited from any PC:

    MONITOR_1_OUTPUT=HDMI-A-1
    MONITOR_2_OUTPUT=HDMI-A-2
    MONITOR_1_AUDIO=alsa/plughw:CARD=vc4hdmi0,DEV=0
    MONITOR_2_AUDIO=alsa/plughw:CARD=vc4hdmi1,DEV=0

The output name is passed to mpv (--fs-screen-name), which asks the
compositor to fullscreen its window on that output.
"""
import glob
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

DRM_ROOT = "/sys/class/drm"
ASOUND_CARDS = "/proc/asound/cards"
CONFIG_PATHS = (
    "/boot/firmware/video-reinforcer.conf",
    "/etc/video-reinforcer/hardware.conf",
)
MONITOR_INDICES = (1, 2)

# Connector types that are physical external ports, in the order they are
# assigned to monitor 1, 2. Internal panels (eDP, DSI, LVDS), Writeback,
# Virtual and Composite are never used.
_PORT_TYPES = ("HDMI-A", "HDMI-B", "DP", "DVI-D", "DVI-I", "DVI-A", "VGA")
_CONNECTOR_RE = re.compile(r"^(card\d+)-(.+)-(\d+)$")
_ASOUND_ID_RE = re.compile(r"^\s*\d+\s+\[(\S+)\s*\]")


@dataclass(frozen=True)
class Monitor:
    index: int
    output: str  # DRM connector / Wayland output name, e.g. "HDMI-A-1"
    audio_device: Optional[str]  # mpv --audio-device value; None = mpv default


# ----------------------------------------------------------------------
# Display outputs
# ----------------------------------------------------------------------

def _port_connectors(drm_root: str) -> Dict[str, List[Tuple[int, int, str]]]:
    """card name -> [(type order, number, connector name)] for physical ports."""
    cards: Dict[str, List[Tuple[int, int, str]]] = {}
    for path in glob.glob(os.path.join(drm_root, "card*-*")):
        m = _CONNECTOR_RE.match(os.path.basename(path))
        if not m:
            continue
        card, ctype, num = m.group(1), m.group(2), int(m.group(3))
        if ctype not in _PORT_TYPES:
            continue
        cards.setdefault(card, []).append((_PORT_TYPES.index(ctype), num, f"{ctype}-{num}"))
    for conns in cards.values():
        conns.sort()
    return cards


def detected_outputs(drm_root: Optional[str] = None) -> List[str]:
    """Physical output names on the display card, in monitor order."""
    drm_root = drm_root or DRM_ROOT
    cards = _port_connectors(drm_root)
    if not cards:
        return []
    return [name for _, _, name in cards[sorted(cards)[0]]]


def is_output_connected(output: str, drm_root: Optional[str] = None) -> bool:
    drm_root = drm_root or DRM_ROOT
    for path in glob.glob(os.path.join(drm_root, f"card*-{output}", "status")):
        try:
            with open(path) as f:
                if f.read().strip() == "connected":
                    return True
        except OSError:
            pass
    return False


# ----------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------

def _alsa_card_ids(cards_file: str) -> List[str]:
    try:
        with open(cards_file) as f:
            return [m.group(1) for m in map(_ASOUND_ID_RE.match, f) if m]
    except OSError:
        return []


def detected_audio_device(output: str, cards_file: Optional[str] = None) -> Optional[str]:
    """ALSA device that plays through the given output's speakers, if known.

    Raspberry Pi: each HDMI port has its own ALSA card, vc4hdmi0 = HDMI-A-1,
    vc4hdmi1 = HDMI-A-2. Other hardware (e.g. Intel HDA, where every port is
    a numbered device on one card) has no reliable mapping, so None is
    returned and mpv uses the system default; set MONITOR_n_AUDIO to override.
    """
    cards_file = cards_file or ASOUND_CARDS
    m = re.match(r"^HDMI-A-(\d+)$", output)
    if m:
        card_id = f"vc4hdmi{int(m.group(1)) - 1}"
        if card_id in _alsa_card_ids(cards_file):
            return f"alsa/plughw:CARD={card_id},DEV=0"
    return None


# ----------------------------------------------------------------------
# Overrides + resolution
# ----------------------------------------------------------------------

def load_overrides(paths: Optional[Iterable[str]] = None) -> Dict[str, str]:
    """Read KEY=VALUE overrides from the first file that exists.

    Tolerates files written on Windows: BOM, CRLF, quotes, comments.
    """
    paths = CONFIG_PATHS if paths is None else paths
    for path in paths:
        try:
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        values: Dict[str, str] = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                values[key.strip().upper()] = value
        log.info("Hardware overrides from %s: %s", path, values)
        return values
    return {}


def resolve_monitors(
    drm_root: Optional[str] = None,
    cards_file: Optional[str] = None,
    config_paths: Optional[Iterable[str]] = None,
) -> Dict[int, Monitor]:
    """Monitor index -> Monitor. Monitors with no output available are omitted."""
    drm_root = drm_root or DRM_ROOT
    cards_file = cards_file or ASOUND_CARDS
    config_paths = CONFIG_PATHS if config_paths is None else config_paths
    overrides = load_overrides(config_paths)
    outputs = detected_outputs(drm_root)
    monitors: Dict[int, Monitor] = {}
    for idx in MONITOR_INDICES:
        output = overrides.get(f"MONITOR_{idx}_OUTPUT")
        if output is None and idx <= len(outputs):
            output = outputs[idx - 1]
        if output is None:
            continue
        audio = overrides.get(f"MONITOR_{idx}_AUDIO") or detected_audio_device(output, cards_file)
        monitors[idx] = Monitor(index=idx, output=output, audio_device=audio)
    return monitors
