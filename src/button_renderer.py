import os
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_LABEL_COLOR = (255, 255, 255)
_LABEL_SHADOW = (0, 0, 0)
_LABEL_FONT_SIZE = 14
_LABEL_MARGIN = 6  # pixels from bottom


def render_button(
    size: Tuple[int, int],
    style_type: str,
    color: Optional[str] = None,
    image_path: Optional[str] = None,
    label: Optional[str] = None,
) -> Image.Image:
    if style_type == "image" and image_path and os.path.exists(image_path):
        try:
            img = Image.open(image_path).convert("RGB").resize(size, Image.LANCZOS)
        except Exception:
            img = _solid(size, color)
    else:
        img = _solid(size, color)

    if label:
        _draw_label(img, label)

    return img


def render_blank(size: Tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (0, 0, 0))


def _solid(size: Tuple[int, int], hex_color: Optional[str]) -> Image.Image:
    try:
        h = (hex_color or "#222222").lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r, g, b = 34, 34, 34
    return Image.new("RGB", size, (r, g, b))


def _draw_label(img: Image.Image, text: str):
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT_PATH, _LABEL_FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - w) // 2
    y = img.height - h - _LABEL_MARGIN

    draw.text((x + 1, y + 1), text, fill=_LABEL_SHADOW, font=font)
    draw.text((x, y), text, fill=_LABEL_COLOR, font=font)
