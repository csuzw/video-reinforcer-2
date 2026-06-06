"""
Stub out Linux-only and hardware libraries so the test suite runs on any platform.
On a Pi with the real libraries installed they'll already be in sys.modules and
these lines are no-ops.
"""
import sys
from unittest.mock import MagicMock

_STUBS = [
    "pyudev",
    "evdev",
    "StreamDeck",
    "StreamDeck.DeviceManager",
    "StreamDeck.Devices",
    "StreamDeck.Devices.StreamDeck",
    "StreamDeck.ImageHelpers",
]

for _mod in _STUBS:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
