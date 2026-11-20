import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import folder_scanner


CONFIG_FILE = "config.json"


class ConfigError(Exception):
    pass


@dataclass
class ButtonStyle:
    type: str  # "color" or "image"
    color: str = "#222222"
    image: Optional[str] = None
    label: Optional[str] = None
    badge: Optional[str] = None  # small corner marker, e.g. the monitor number


@dataclass(eq=False)  # compared by identity: two buttons can play the same video
class ButtonConfig:
    video: str
    monitor: int  # 1 or 2
    style: ButtonStyle
    key: Optional[str] = None  # normalized lowercase keyboard key, e.g. "f1", "1", "a"
    root: str = ""  # folder the USB stick is mounted at; paths are relative to it

    def video_path(self) -> str:
        return os.path.join(self.root, self.video)

    def image_path(self) -> Optional[str]:
        if self.style.type == "image" and self.style.image:
            return os.path.join(self.root, self.style.image)
        return None


@dataclass
class QuitConfig:
    stream_deck_button: Optional[int] = None
    key: Optional[str] = None  # normalized lowercase, e.g. "f12", "escape"
    style: ButtonStyle = field(default_factory=lambda: ButtonStyle(
        type="color", color="#CC0000", label="QUIT"
    ))


@dataclass
class PagingConfig:
    """Stream Deck keys used for previous/next page on decks without
    hardware page buttons. None means 'pick a default for this deck'."""
    previous: Optional[int] = None
    next: Optional[int] = None


@dataclass
class DeckLayout:
    """What goes on which Stream Deck key, for one particular deck."""
    pages: List[Dict[int, ButtonConfig]]
    previous_key: Optional[int] = None  # on-screen paging keys; None if not shown
    next_key: Optional[int] = None
    warnings: List[str] = field(default_factory=list)

    def page_count(self) -> int:
        return max(1, len(self.pages))


DEFAULT_PLAYING_BORDER_COLOR = "#FF0000"
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Folder mode: key colour (when a video has no picture) and corner badge per monitor
_MONITOR_COLORS = {1: "#457B9D", 2: "#E76F51"}


@dataclass
class AppConfig:
    # Explicit pages from config.json: page → {key index → button}.
    pages: List[Dict[int, ButtonConfig]] = field(default_factory=list)
    quit: Optional[QuitConfig] = None
    playing_border_color: str = DEFAULT_PLAYING_BORDER_COLOR
    paging: PagingConfig = field(default_factory=PagingConfig)
    # Folder mode: buttons in order, laid out onto pages to fit the deck.
    auto_buttons: List[ButtonConfig] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # shown briefly after loading

    @property
    def buttons(self) -> Dict[int, ButtonConfig]:
        """The first page (all of it, for a single-page config)."""
        return self.pages[0] if self.pages else {}

    def all_buttons(self) -> List[ButtonConfig]:
        if self.auto_buttons:
            return list(self.auto_buttons)
        return [btn for page in self.pages for _, btn in sorted(page.items())]

    def key_map(self) -> Dict[str, ButtonConfig]:
        """Map normalized key name → button. Keys work whatever page is showing."""
        return {btn.key: btn for btn in self.all_buttons() if btn.key}

    def deck_only_actions(self) -> List[str]:
        """Human-readable names of actions that have no keyboard key (Stream Deck only)."""
        if self.auto_buttons:
            actions = ["all videos"]
        else:
            multi = len(self.pages) > 1
            actions = [
                (f"page {p} button {idx}" if multi else f"button {idx}")
                for p, page in enumerate(self.pages, start=1)
                for idx, btn in sorted(page.items()) if btn.key is None
            ]
        if self.quit and self.quit.stream_deck_button is not None and self.quit.key is None:
            actions.append("quit")
        return actions

    def requires_deck(self) -> bool:
        """True if any action can only be triggered via Stream Deck (no keyboard key)."""
        return bool(self.deck_only_actions())

    def layout(self, key_count: int, hardware_paging: bool) -> DeckLayout:
        """Arrange the buttons for a deck with key_count keys.

        hardware_paging: the deck has its own page buttons (Stream Deck Neo),
        so every key is free for videos. key_count 0 means no deck connected.
        """
        if self.auto_buttons:
            return self._auto_layout(key_count, hardware_paging)
        return self._explicit_layout(key_count, hardware_paging)

    def _auto_layout(self, key_count: int, hardware_paging: bool) -> DeckLayout:
        if key_count <= 0:
            return DeckLayout(pages=[])
        n = len(self.auto_buttons)
        free = list(range(key_count))
        prev_key = next_key = None
        if n > key_count and not hardware_paging and key_count >= 3:
            next_key = free.pop()  # the last two keys become ◀ ▶
            prev_key = free.pop()
        pages: List[Dict[int, ButtonConfig]] = [
            dict(zip(free, self.auto_buttons[start:start + len(free)]))
            for start in range(0, n, len(free))
        ]
        warnings = []
        if len(pages) > 1 and prev_key is None and not hardware_paging:
            warnings.append("Not all videos fit on this Stream Deck.")
            pages = pages[:1]
        return DeckLayout(pages=pages, previous_key=prev_key, next_key=next_key, warnings=warnings)

    def _paging_keys(self, key_count: int):
        """On-screen page keys for an explicit config: as set, or the last two keys."""
        prev_key = self.paging.previous if self.paging.previous is not None else key_count - 2
        next_key = self.paging.next if self.paging.next is not None else key_count - 1
        return prev_key, next_key

    def _explicit_layout(self, key_count: int, hardware_paging: bool) -> DeckLayout:
        pages = [dict(page) for page in self.pages]
        warnings: List[str] = []
        prev_key = next_key = None
        if key_count <= 0:
            return DeckLayout(pages=pages)

        if len(pages) > 1 and not hardware_paging:
            prev_key, next_key = self._paging_keys(key_count)
            bad = [k for k in (prev_key, next_key) if not 0 <= k < key_count]
            if bad or prev_key == next_key:
                warnings.append(
                    f"Page keys {prev_key} and {next_key} don't fit this\n"
                    f"{key_count}-key Stream Deck. Check \"paging\" in config.json."
                )
                prev_key = next_key = None
            else:
                quit_key = self.quit.stream_deck_button if self.quit else None
                if quit_key in (prev_key, next_key):
                    warnings.append(
                        f"Quit and a page key are both on key {quit_key}.\n"
                        "Check \"paging\" in config.json."
                    )
                for p, page in enumerate(pages, start=1):
                    for k in (prev_key, next_key):
                        if k in page:
                            warnings.append(
                                f"Page {p} button {k} is hidden by a page key.\n"
                                "Move it, or set \"paging\" in config.json."
                            )
                            del page[k]

        for p, page in enumerate(pages, start=1):
            too_big = sorted(k for k in page if k >= key_count)
            if too_big:
                where = f"Page {p} button" if len(pages) > 1 else "Button"
                nums = ", ".join(str(k) for k in too_big)
                warnings.append(
                    f"{where} {nums} won't show: this\n"
                    f"Stream Deck has {key_count} keys (0-{key_count - 1})."
                )
        return DeckLayout(pages=pages, previous_key=prev_key, next_key=next_key, warnings=warnings)


def load_config(usb_root: str) -> AppConfig:
    config_path = os.path.join(usb_root, CONFIG_FILE)
    if not os.path.exists(config_path):
        return _load_folders(usb_root)
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config.json: {e}")
    return _parse(data, usb_root)


# ----------------------------------------------------------------------
# Folder mode: no config.json, buttons come from Monitor 1 / Monitor 2
# ----------------------------------------------------------------------

def _load_folders(usb_root: str) -> AppConfig:
    try:
        scan = folder_scanner.scan(usb_root)
    except OSError as e:
        raise ConfigError(f"Could not read the USB stick: {e}")

    if not scan.monitor_folders:
        raise ConfigError(
            "No config.json or Monitor folders found.\n\n"
            "Put videos in folders named\n"
            "\"Monitor 1/Videos\" and \"Monitor 2/Videos\",\n"
            "or add a config.json."
        )
    if not scan.videos:
        folders = " and ".join(f"\"{f}\"" for f in scan.monitor_folders)
        raise ConfigError(f"No videos found in {folders}.")

    buttons = []
    for v in scan.videos:
        if v.picture:
            style = ButtonStyle(type="image", image=v.picture, badge=str(v.monitor),
                                color=_MONITOR_COLORS[v.monitor])
        else:
            style = ButtonStyle(type="color", color=_MONITOR_COLORS[v.monitor],
                                label=v.label, badge=str(v.monitor))
        buttons.append(ButtonConfig(video=v.path, monitor=v.monitor, style=style, root=usb_root))

    warnings = []
    if scan.orphan_pictures:
        shown = scan.orphan_pictures[:4]
        more = len(scan.orphan_pictures) - len(shown)
        lines = "\n".join(shown) + (f"\n...and {more} more" if more > 0 else "")
        warnings.append(f"Pictures with no matching video:\n{lines}\n\nCheck the file names match.")

    return AppConfig(auto_buttons=buttons, warnings=warnings)


# ----------------------------------------------------------------------
# config.json
# ----------------------------------------------------------------------

def _parse(data: dict, root: str = "") -> AppConfig:
    if "buttons" in data and "pages" in data:
        raise ConfigError("config.json has both 'buttons' and 'pages' — use one or the other")
    if "pages" in data:
        raw_pages = data["pages"]
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ConfigError("'pages' must be a list of pages, e.g. \"pages\": [ {...}, {...} ]")
        pages = [
            _parse_buttons(page, root, prefix=f"Page {p} button ")
            for p, page in enumerate(raw_pages, start=1)
        ]
    elif "buttons" in data:
        pages = [_parse_buttons(data["buttons"], root, prefix="Button ")]
    else:
        raise ConfigError("config.json missing 'buttons' section (or 'pages')")

    if not any(pages):
        raise ConfigError("config.json defines no buttons")
    for p, page in enumerate(pages, start=1):
        if not page and len(pages) > 1:
            raise ConfigError(f"Page {p} in config.json has no buttons")

    quit_cfg = _parse_quit(data.get("quit"))
    paging = _parse_paging(data.get("paging"))

    border = data.get("playing_border_color", DEFAULT_PLAYING_BORDER_COLOR)
    if not isinstance(border, str) or not _HEX_COLOR_RE.match(border):
        raise ConfigError(
            f"playing_border_color must be a hex colour like \"#FF0000\", got {border!r}"
        )

    config = AppConfig(pages=pages, quit=quit_cfg, playing_border_color=border, paging=paging)
    _check_duplicate_keys(config)
    return config


def _parse_buttons(raw: dict, root: str, prefix: str) -> Dict[int, ButtonConfig]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{prefix.strip()}s must be written as {{\"0\": {{...}}, \"1\": {{...}}}}")
    buttons: Dict[int, ButtonConfig] = {}
    for key_str, btn in raw.items():
        try:
            idx = int(key_str)
        except ValueError:
            raise ConfigError(f"Button key '{key_str}' must be an integer")
        name = f"{prefix}{key_str}"

        if "video" not in btn:
            raise ConfigError(f"{name} missing 'video' field")

        monitor = btn.get("monitor", 1)
        if monitor not in (1, 2):
            raise ConfigError(f"{name} monitor must be 1 or 2, got {monitor!r}")

        raw_style = btn.get("button", {})
        style_type = raw_style.get("type", "color")
        if style_type not in ("color", "image"):
            raise ConfigError(f"{name} style type must be 'color' or 'image'")

        keyboard_key = btn.get("key")
        if keyboard_key:
            keyboard_key = keyboard_key.lower()

        style = ButtonStyle(
            type=style_type,
            color=raw_style.get("color", "#222222"),
            image=raw_style.get("image"),
            label=raw_style.get("label"),
        )
        buttons[idx] = ButtonConfig(
            video=btn["video"],
            monitor=monitor,
            style=style,
            key=keyboard_key,
            root=root,
        )
    return buttons


def _check_duplicate_keys(config: AppConfig):
    seen = set()
    for btn in config.all_buttons():
        if btn.key and btn.key in seen:
            raise ConfigError(f"Keyboard key \"{btn.key}\" is used by more than one button")
        if btn.key:
            seen.add(btn.key)


def _parse_quit(data: Optional[dict]) -> Optional[QuitConfig]:
    if not data:
        return None

    deck_button = data.get("stream_deck_button")
    if deck_button is not None and not isinstance(deck_button, int):
        raise ConfigError("quit.stream_deck_button must be an integer")

    key = data.get("key")
    if key:
        key = key.lower()

    raw_style = data.get("button", {})
    style = ButtonStyle(
        type=raw_style.get("type", "color"),
        color=raw_style.get("color", "#CC0000"),
        image=raw_style.get("image"),
        label=raw_style.get("label", "QUIT"),
    )

    return QuitConfig(stream_deck_button=deck_button, key=key, style=style)


def _parse_paging(data: Optional[dict]) -> PagingConfig:
    if not data:
        return PagingConfig()
    if not isinstance(data, dict):
        raise ConfigError("'paging' must look like {\"previous\": 10, \"next\": 14}")
    result = PagingConfig()
    for name in ("previous", "next"):
        value = data.get(name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ConfigError(f"paging.{name} must be a Stream Deck key number, got {value!r}")
        setattr(result, name, value)
    return result
