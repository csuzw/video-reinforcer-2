import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

USB_MOUNT = "/mnt/vr-usb"
CONFIG_FILE = "config.json"


class ConfigError(Exception):
    pass


@dataclass
class ButtonStyle:
    type: str  # "color" or "image"
    color: str = "#222222"
    image: Optional[str] = None
    label: Optional[str] = None


@dataclass
class ButtonConfig:
    video: str
    monitor: int  # 1 or 2
    style: ButtonStyle

    def video_path(self) -> str:
        return os.path.join(USB_MOUNT, self.video)

    def image_path(self) -> Optional[str]:
        if self.style.type == "image" and self.style.image:
            return os.path.join(USB_MOUNT, self.style.image)
        return None


@dataclass
class AppConfig:
    buttons: Dict[int, ButtonConfig]


def load_config() -> AppConfig:
    config_path = os.path.join(USB_MOUNT, CONFIG_FILE)
    if not os.path.exists(config_path):
        raise ConfigError("config.json not found on USB stick")
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config.json: {e}")
    return _parse(data)


def _parse(data: dict) -> AppConfig:
    if "buttons" not in data:
        raise ConfigError("config.json missing 'buttons' section")

    buttons: Dict[int, ButtonConfig] = {}
    for key_str, btn in data["buttons"].items():
        try:
            idx = int(key_str)
        except ValueError:
            raise ConfigError(f"Button key '{key_str}' must be an integer")

        if "video" not in btn:
            raise ConfigError(f"Button {key_str} missing 'video' field")

        monitor = btn.get("monitor", 1)
        if monitor not in (1, 2):
            raise ConfigError(f"Button {key_str} monitor must be 1 or 2, got {monitor!r}")

        raw_style = btn.get("button", {})
        style_type = raw_style.get("type", "color")
        if style_type not in ("color", "image"):
            raise ConfigError(f"Button {key_str} style type must be 'color' or 'image'")

        style = ButtonStyle(
            type=style_type,
            color=raw_style.get("color", "#222222"),
            image=raw_style.get("image"),
            label=raw_style.get("label"),
        )
        buttons[idx] = ButtonConfig(video=btn["video"], monitor=monitor, style=style)

    if not buttons:
        raise ConfigError("config.json defines no buttons")

    return AppConfig(buttons=buttons)
