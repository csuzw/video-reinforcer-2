import os
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_LABEL_COLOR = (255, 255, 255)
_LABEL_SHADOW = (0, 0, 0)
_LABEL_FONT_SIZE = 14
_LABEL_MIN_FONT_SIZE = 9
_LABEL_MARGIN = 6  # pixels from bottom
_PAGING_KEY_COLOR = (40, 40, 40)
_ARROW_COLOR = (230, 230, 230)


def render_button(
    size: Tuple[int, int],
    style_type: str,
    color: Optional[str] = None,
    image_path: Optional[str] = None,
    label: Optional[str] = None,
    border_color: Optional[str] = None,
    badge: Optional[str] = None,
) -> Image.Image:
    """Render a key image. border_color draws a thick frame (used for the playing key).
    badge draws a small marker in the top-left corner (e.g. the monitor number)."""
    if style_type == "image" and image_path and os.path.exists(image_path):
        try:
            img = Image.open(image_path).convert("RGB").resize(size, Image.LANCZOS)
        except Exception:
            img = _solid(size, color)
    else:
        img = _solid(size, color)

    if label:
        _draw_label(img, label)

    if badge:
        _draw_badge(img, badge, color)

    if border_color:
        _draw_border(img, border_color)

    return img


def render_blank(size: Tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (0, 0, 0))


def render_paging_key(size: Tuple[int, int], direction: int, page: int, page_count: int) -> Image.Image:
    """A ◀ (direction -1) or ▶ (direction +1) key, with 'page/count' underneath."""
    img = Image.new("RGB", size, _PAGING_KEY_COLOR)
    draw = ImageDraw.Draw(img)
    w, h = size
    half = min(w, h) // 5
    cx, cy = w // 2, h // 2 - h // 10
    if direction < 0:
        points = [(cx - half, cy), (cx + half, cy - half), (cx + half, cy + half)]
    else:
        points = [(cx + half, cy), (cx - half, cy - half), (cx - half, cy + half)]
    draw.polygon(points, fill=_ARROW_COLOR)
    _draw_label(img, f"{page}/{page_count}")
    return img


def render_screen_text(size: Tuple[int, int], text: str) -> Image.Image:
    """Centred white text on black, for the Stream Deck Neo's info screen."""
    img = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font(max(10, size[1] // 2 - 4))
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (size[0] - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = (size[1] - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((x, y), text, fill=_LABEL_COLOR, font=font)
    return img


def _parse_hex(hex_color: Optional[str], default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    try:
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return default


def _solid(size: Tuple[int, int], hex_color: Optional[str]) -> Image.Image:
    return Image.new("RGB", size, _parse_hex(hex_color, (34, 34, 34)))


def _font(size: int):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _border_width(img: Image.Image) -> int:
    return max(4, min(img.size) // 10)  # ~7px on a 72px key, ~9px on XL


def _draw_border(img: Image.Image, hex_color: str):
    width = _border_width(img)
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [0, 0, img.width - 1, img.height - 1],
        outline=_parse_hex(hex_color, (255, 0, 0)),
        width=width,
    )


def _draw_badge(img: Image.Image, text: str, hex_color: Optional[str]):
    """White disc with the text in the key's colour, inside where the border goes."""
    draw = ImageDraw.Draw(img)
    inset = _border_width(img) + 1
    diameter = max(14, min(img.size) // 4)
    draw.ellipse([inset, inset, inset + diameter, inset + diameter],
                 fill=(255, 255, 255), outline=(0, 0, 0))
    font = _font(max(8, diameter - 6))
    bbox = draw.textbbox((0, 0), text, font=font)
    x = inset + (diameter - (bbox[2] - bbox[0])) // 2 - bbox[0] + 1
    y = inset + (diameter - (bbox[3] - bbox[1])) // 2 - bbox[1] + 1
    draw.text((x, y), text, fill=_parse_hex(hex_color, (0, 0, 0)), font=font)


def _draw_label(img: Image.Image, text: str):
    draw = ImageDraw.Draw(img)
    # Keep clear of where the playing border goes, so the label stays readable
    inset = _border_width(img)
    max_width = img.width - 2 * inset
    # Shrink long labels to fit the key, then shorten with "…" if still too wide.
    font = _font(_LABEL_FONT_SIZE)
    for size in range(_LABEL_FONT_SIZE, _LABEL_MIN_FONT_SIZE - 1, -1):
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            break
    if draw.textlength(text, font=font) > max_width:
        while len(text) > 1 and draw.textlength(text + "…", font=font) > max_width:
            text = text[:-1]
        text = text.rstrip() + "…"

    bbox = draw.textbbox((0, 0), text, font=font)
    x = (img.width - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = img.height - bbox[3] - max(_LABEL_MARGIN, inset + 2)

    draw.text((x + 1, y + 1), text, fill=_LABEL_SHADOW, font=font)
    draw.text((x, y), text, fill=_LABEL_COLOR, font=font)
