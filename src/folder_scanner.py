"""Find videos and their button pictures from the USB stick's folder layout.

Used when there is no config.json:

    Monitor 1/
      Videos/     01 Elephant.mp4   Train.mp4
      Pictures/   01 Elephant.png   Train.jpg
    Monitor 2/
      Videos/ ...
      Pictures/ ...

A picture belongs to the video with the same name (ignoring case and the
file extension). Names are matched forgivingly: "monitor1", "MONITOR 1",
"Video", "Images" etc. all work, and files may also sit directly in the
Monitor folder. Order is by name, numbers compared as numbers, so a "01 "
style prefix controls the order; it's left off the key label.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg", ".ts",
}
PICTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

_MONITOR_RE = re.compile(r"^monitor\s*[-_]?\s*([12])$", re.IGNORECASE)
_VIDEO_DIRS = {"videos", "video"}
_PICTURE_DIRS = {"pictures", "picture", "images", "image"}
_ORDER_PREFIX_RE = re.compile(r"^\d+[\s._-]*")


@dataclass
class FoundVideo:
    monitor: int
    path: str  # relative to the USB stick root, '/' separated
    label: str
    picture: Optional[str] = None  # relative path


@dataclass
class ScanResult:
    monitor_folders: List[str] = field(default_factory=list)  # as named on the stick
    videos: List[FoundVideo] = field(default_factory=list)  # in button order
    orphan_pictures: List[str] = field(default_factory=list)  # relative paths


def scan(root: str) -> ScanResult:
    result = ScanResult()
    monitors: Dict[int, str] = {}
    for name in sorted(_list(root)):
        m = _MONITOR_RE.match(name)
        if m and os.path.isdir(os.path.join(root, name)):
            monitors.setdefault(int(m.group(1)), name)

    for monitor in sorted(monitors):
        folder = monitors[monitor]
        result.monitor_folders.append(folder)
        videos, pictures = _scan_monitor(root, folder)

        used = set()
        for stem, rel in sorted(videos, key=lambda v: _natural_key(v[0])):
            picture = pictures.get(stem.casefold())
            if picture:
                used.add(stem.casefold())
            result.videos.append(FoundVideo(
                monitor=monitor, path=rel, label=_label(stem), picture=picture,
            ))
        result.orphan_pictures.extend(
            rel for stem, rel in sorted(pictures.items()) if stem not in used
        )
    return result


def _scan_monitor(root: str, folder: str):
    """Return ([(stem, rel_path)] of videos, {casefolded stem: rel_path} of pictures)."""
    videos = []
    pictures: Dict[str, str] = {}
    dirs = [folder]
    for name in sorted(_list(os.path.join(root, folder))):
        if name.casefold() in _VIDEO_DIRS | _PICTURE_DIRS and os.path.isdir(os.path.join(root, folder, name)):
            dirs.append(f"{folder}/{name}")

    for rel_dir in dirs:
        for name in sorted(_list(os.path.join(root, rel_dir))):
            path = os.path.join(root, rel_dir, name)
            if not os.path.isfile(path):
                continue
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            rel = f"{rel_dir}/{name}"
            if ext in VIDEO_EXTENSIONS:
                videos.append((stem, rel))
            elif ext in PICTURE_EXTENSIONS:
                pictures.setdefault(stem.casefold(), rel)
    return videos, pictures


def _list(path: str) -> List[str]:
    """Directory entries, skipping hidden and system files (._x, .DS_Store, Thumbs.db)."""
    return [
        n for n in os.listdir(path)
        if not n.startswith(".") and n.casefold() not in ("thumbs.db", "desktop.ini")
        and n.casefold() != "system volume information"
    ]


def _label(stem: str) -> str:
    label = _ORDER_PREFIX_RE.sub("", stem).strip()
    return label or stem


def _natural_key(text: str):
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
            for part in re.split(r"(\d+)", text) if part]
